from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlencode, urlparse, urlunparse

from fastapi import HTTPException

from video_sum_core.models.tasks import InputType
from video_sum_core.utils import extract_bilibili_page, normalize_video_url
from video_sum_infra.runtime import ffmpeg_location

from video_sum_service.bilibili_wbi import load_bilibili_cookie_header
from video_sum_service.context import COVER_CACHE_DIR, settings_manager
from video_sum_service.integrations import cache_cover_image
from video_sum_service.repository import SqliteTaskRepository
from video_sum_service.schemas import VideoAssetRecord, VideoPageOptionResponse

logger = logging.getLogger("video_sum_service.app")
YoutubeDL = None
DownloadError = None

_BILIBILI_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.bilibili.com/",
}
LOCAL_VIDEO_SUFFIXES = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".wmv",
    ".webm",
    ".flv",
    ".m4v",
    ".ts",
    ".mpeg",
    ".mpg",
}
LOCAL_AUDIO_SUFFIXES = {
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".opus",
    ".wma",
}


def with_bilibili_page(url: str, page: int) -> str:
    parsed = urlparse(url)
    query_pairs: list[tuple[str, str]] = []
    if parsed.query:
        for chunk in parsed.query.split("&"):
            if not chunk:
                continue
            key, _, value = chunk.partition("=")
            if key != "p":
                query_pairs.append((key, value))
    query_pairs.append(("p", str(page)))
    encoded_query = urlencode(query_pairs)
    return parsed._replace(query=encoded_query).geturl()


def build_page_canonical_id(base_id: str, page: int) -> str:
    return f"{base_id}?p={page}"


def extract_page_part_from_title(base_title: str, page: int, title: str) -> str:
    candidate = str(title or "").strip()
    if not candidate:
        return ""

    normalized_base = re.sub(r"\s+", " ", base_title).strip()
    normalized_candidate = re.sub(r"\s+", " ", candidate).strip()
    if normalized_base and normalized_candidate.startswith(normalized_base):
        candidate = normalized_candidate[len(normalized_base):].strip(" -_")
    else:
        candidate = normalized_candidate

    candidate = re.sub(rf"^[Pp]0*{page}\s*", "", candidate).strip(" -_")
    candidate = re.sub(rf"^第?\s*0*{page}\s*[Pp]?\s*", "", candidate).strip(" -_")
    return candidate


def build_page_title(base_title: str, page: int, info: dict[str, object]) -> str:
    part = str(info.get("part") or "").strip()
    title = str(info.get("title") or "").strip()
    candidate = part or extract_page_part_from_title(base_title, page, title)
    if not candidate:
        return f"P{page}"
    return f"P{page} {candidate}"


def build_ydl_probe_options(*, extract_flat: bool = False) -> dict[str, object]:
    options: dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
        "http_headers": _BILIBILI_HTTP_HEADERS,
        "retries": 3,
        "extractor_retries": 3,
        "fragment_retries": 3,
        "sleep_interval_requests": 1,
        "socket_timeout": 30,
    }
    cookie_file = str(
        settings_manager.current.ytdlp_cookies_file
        or os.environ.get("VIDEO_SUM_YTDLP_COOKIES_FILE")
        or os.environ.get("YTDLP_COOKIES_FILE")
        or ""
    ).strip()
    if cookie_file:
        cookie_path = Path(cookie_file).expanduser()
        if cookie_path.exists() and cookie_path.is_file():
            options["cookiefile"] = str(cookie_path)
        else:
            logger.warning("yt-dlp cookie file does not exist: %s", cookie_path)
    if extract_flat:
        options["extract_flat"] = "in_playlist"
    return options


def extract_video_info(url: str, *, extract_flat: bool = False) -> dict[str, object]:
    global DownloadError, YoutubeDL
    if YoutubeDL is None:
        from yt_dlp import YoutubeDL as YtDlpYoutubeDL

        YoutubeDL = YtDlpYoutubeDL
    if DownloadError is None:
        from yt_dlp.utils import DownloadError as YtDlpDownloadError

        DownloadError = YtDlpDownloadError

    options = build_ydl_probe_options(extract_flat=extract_flat)
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        message = str(exc)
        if "Could not copy Chrome cookie database" in message:
            raise HTTPException(
                status_code=400,
                detail=(
                    "无法读取 Chrome 登录态：yt-dlp 不能复制 Chrome Cookie 数据库。"
                    "请通过 BiliSum 的 B 站登录窗口重新捕获登录态，或按教程导出 cookies.txt 并填写 yt-dlp Cookies 文件。"
                ),
            ) from exc
        if "Failed to decrypt with DPAPI" in message:
            raise HTTPException(
                status_code=400,
                detail=(
                    "无法读取浏览器登录态：yt-dlp 解密 Windows 浏览器 Cookie 失败（DPAPI）。"
                    "请通过 BiliSum 的 B 站登录窗口重新捕获登录态，或按教程导出 cookies.txt 并填写 yt-dlp Cookies 文件。"
                ),
            ) from exc
        if "HTTP Error 412" in message and "BiliBili" in message:
            raise HTTPException(
                status_code=400,
                detail=(
                    "B 站返回 HTTP 412，当前请求可能被风控拦截。"
                    "请稍后重试、切换网络，或通过 BiliSum 的 B 站登录窗口捕获登录态。"
                ),
            ) from exc
        raise
    if not isinstance(info, dict):
        raise HTTPException(status_code=400, detail="无法读取视频信息。")
    return info


def extract_thumbnail_url(payload: dict[str, object] | None) -> str:
    if not payload:
        return ""

    for key in ("thumbnail", "cover", "pic", "first_frame"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    thumbnails = payload.get("thumbnails")
    if isinstance(thumbnails, list):
        for item in reversed(thumbnails):
            if isinstance(item, dict):
                value = item.get("url")
                if isinstance(value, str) and value.strip():
                    return value.strip()
            elif isinstance(item, str) and item.strip():
                return item.strip()
    return ""


def first_non_empty(*values: str | None) -> str:
    return next((value.strip() for value in values if isinstance(value, str) and value.strip()), "")


def _normalize_bilibili_image_url(url: str) -> str:
    value = str(url or "").strip()
    if value.startswith("//"):
        return f"https:{value}"
    return value


# 「系列」(series) 反查的预算上限：超大系列/超多系列不能拖死 probe 请求。
# 注意：x/series/archives 服务端每页硬上限 20 条，请求更大 page_size 无效。
_SERIES_FALLBACK_MAX_LISTS = 10
_SERIES_FALLBACK_MAX_PAGES_PER_LIST = 60
_SERIES_FALLBACK_MAX_TOTAL_PAGES = 80
_SERIES_FALLBACK_PAGE_SIZE = 20
_SERIES_FALLBACK_PAGE_DELAY_SECONDS = 1.0


def _fetch_bilibili_series_collection_payload(
    normalized,
    video_data: dict[str, object],
) -> dict[str, object] | None:
    """视频页没有 ugc_season 时，反查 UP 的「系列」（series）集合。

    B 站视频页只暴露「合集」(ugc_season) 成员关系；「系列」成员关系
    必须调空间接口反查：seasons_series_list 拿系列清单，再逐页翻
    x/series/archives 定位目标视频所在的系列。
    """
    import random
    import time

    from video_sum_service.bilibili_wbi import WbiRiskControlError, _signed_get

    owner = video_data.get("owner") if isinstance(video_data.get("owner"), dict) else {}
    owner_mid = first_non_empty(str(owner.get("mid") or ""), str(owner.get("uid") or ""))
    if not owner_mid:
        return None
    cookie_header = load_bilibili_cookie_header() or ""
    try:
        lists_data = _signed_get(
            "https://api.bilibili.com/x/polymer/web-space/seasons_series_list",
            {"mid": owner_mid, "page_num": 1, "page_size": 20},
            cookie_header,
        )
    except Exception:
        logger.warning(
            "bilibili series fallback: list series failed mid=%s",
            owner_mid,
            exc_info=True,
        )
        return None

    lists_root = lists_data.get("items_lists") if isinstance(lists_data.get("items_lists"), dict) else {}
    series_metas: list[dict[str, object]] = []
    for entry in lists_root.get("series_list") or []:
        if not isinstance(entry, dict):
            continue
        meta = entry.get("meta") if isinstance(entry.get("meta"), dict) else {}
        series_id = first_non_empty(str(meta.get("series_id") or ""), str(meta.get("id") or ""))
        if series_id:
            series_metas.append(meta)
    # 小系列优先翻，尽快命中
    series_metas.sort(key=lambda meta: int(meta.get("total") or 0) if str(meta.get("total") or "").isdigit() else 0)

    target_bvid = normalized.canonical_id.lower()
    found_meta: dict[str, object] | None = None
    found_archives: list[dict[str, object]] = []
    pages_scanned = 0
    for meta in series_metas[:_SERIES_FALLBACK_MAX_LISTS]:
        series_id = first_non_empty(str(meta.get("series_id") or ""), str(meta.get("id") or ""))
        list_archives: list[dict[str, object]] = []
        seen_bvids: set[str] = set()
        page_total = 0
        hit = False
        for page_num in range(1, _SERIES_FALLBACK_MAX_PAGES_PER_LIST + 1):
            if pages_scanned >= _SERIES_FALLBACK_MAX_TOTAL_PAGES:
                break
            pages_scanned += 1
            try:
                page_data = _signed_get(
                    "https://api.bilibili.com/x/series/archives",
                    {
                        "mid": owner_mid,
                        "series_id": series_id,
                        # 分页参数是 pn/ps：page_num 会被静默忽略并永远回第 1 页
                        "pn": page_num,
                        "ps": _SERIES_FALLBACK_PAGE_SIZE,
                        "only_normal": "true",
                    },
                    cookie_header,
                )
            except WbiRiskControlError:
                # IP/cookie 被风控：继续扫只会加重风控，整个回退立即放弃
                logger.warning(
                    "bilibili series fallback: risk control hit, abort scan series_id=%s page=%s",
                    series_id,
                    page_num,
                )
                return None
            except Exception:
                logger.warning(
                    "bilibili series fallback: fetch archives failed series_id=%s page=%s",
                    series_id,
                    page_num,
                    exc_info=True,
                )
                break
            archives = [item for item in (page_data.get("archives") or []) if isinstance(item, dict)]
            if not archives:
                break
            if page_num == 1:
                page_info = page_data.get("page") if isinstance(page_data.get("page"), dict) else {}
                try:
                    page_total = int(page_info.get("total") or 0)
                except (TypeError, ValueError):
                    page_total = 0
            new_bvids = {
                str(item.get("bvid") or "").strip().lower()
                for item in archives
            } - seen_bvids
            if not new_bvids:
                # 超出末页后部分实现会夹取/回绕旧数据，靠重复检测止损
                break
            seen_bvids.update(new_bvids)
            list_archives.extend(archives)
            if target_bvid in new_bvids:
                hit = True
            if len(archives) < _SERIES_FALLBACK_PAGE_SIZE:
                break
            if page_total and page_num * _SERIES_FALLBACK_PAGE_SIZE >= page_total:
                break
            # 命中后仍翻完本系列（补齐 items），但请求间留间隔防风控
            time.sleep(_SERIES_FALLBACK_PAGE_DELAY_SECONDS + random.random() * 0.6)
        if hit and list_archives:
            found_meta, found_archives = meta, list_archives
            break
        time.sleep(_SERIES_FALLBACK_PAGE_DELAY_SECONDS)
    if found_meta is None:
        return None

    items: list[dict[str, object]] = []
    for archive in found_archives:
        bvid = str(archive.get("bvid") or "").strip()
        if not bvid:
            continue
        try:
            duration = float(archive["duration"]) if archive.get("duration") is not None else None
        except (TypeError, ValueError):
            duration = None
        items.append(
            {
                "position": len(items) + 1,
                "bvid": bvid,
                "title": first_non_empty(str(archive.get("title") or ""), bvid),
                "source_url": f"https://www.bilibili.com/video/{bvid}/",
                "cover_url": _normalize_bilibili_image_url(str(archive.get("pic") or "")),
                "duration": duration,
                "source_section_id": None,
                "source_section_title": None,
                "source_section_position": 1,
                "is_current": bvid.lower() == target_bvid,
            }
        )
    if len(items) < 2:
        return None

    collection_id = f"series-{first_non_empty(str(found_meta.get('series_id') or ''), str(found_meta.get('id') or ''))}"
    collection_referer = f"https://www.bilibili.com/video/{normalized.canonical_id}/"

    from concurrent.futures import ThreadPoolExecutor

    def cache_collection_item(item: dict[str, object]) -> dict[str, object]:
        cover_url = str(item.get("cover_url") or "").strip()
        if cover_url:
            item["cover_url"] = cache_cover_image(
                cover_url,
                f"collection-{collection_id}-{str(item.get('bvid') or 'video')}",
                referer_url=str(item.get("source_url") or collection_referer),
            )
        return item

    with ThreadPoolExecutor(max_workers=6, thread_name_prefix="bilibili-cover") as executor:
        items = list(executor.map(cache_collection_item, items))

    collection_cover_url = first_non_empty(
        _normalize_bilibili_image_url(str(found_meta.get("cover") or "")),
        _normalize_bilibili_image_url(str(video_data.get("pic") or "")),
    )
    cached_collection_cover = cache_cover_image(
        collection_cover_url,
        f"collection-{collection_id}",
        referer_url=collection_referer,
    )
    owner_name = first_non_empty(str(owner.get("name") or ""), str(owner.get("uname") or ""))
    owner_face = first_non_empty(str(owner.get("face") or ""), str(owner.get("avatar") or ""))
    cached_owner_face = cache_cover_image(
        owner_face,
        f"collection-{collection_id}-owner",
        referer_url=collection_referer,
    ) if owner_face else ""
    return {
        "collection_id": collection_id,
        "title": first_non_empty(str(found_meta.get("name") or ""), "Bilibili 系列"),
        "cover_url": cached_collection_cover,
        "owner_mid": owner_mid or None,
        "owner_name": owner_name or None,
        "owner_face": cached_owner_face or owner_face or None,
        "owner_url": f"https://space.bilibili.com/{owner_mid}" if owner_mid else None,
        "item_count": len(items),
        "items": items,
    }


def _with_trailing_slash(url: str) -> str:
    """给 B 站视频页 URL 补尾斜杠（斜杠必须落在 query 之前）。

    B 站 WAF 对无尾斜杠的 ``/video/BVxxx`` 的**重定向链**一律返回 412，
    带尾斜杠才正常；带 cookie 也救不回来，而 ``normalize_video_url`` 的
    产物不含斜杠。所以补齐必须发生在发起请求之前、且对每个调用方都生效。
    """
    parsed = urlparse(url)
    if not parsed.path or parsed.path.endswith("/"):
        return url
    return urlunparse(parsed._replace(path=f"{parsed.path}/"))


def _fetch_bilibili_initial_state_payload(url: str) -> dict[str, object]:
    import httpx

    # 数据中心 IP 匿名请求视频页会被风控（412）；带上用户登录态 cookies
    # （与 yt-dlp 下载用同一份 cookie 文件）即可正常拿到 __INITIAL_STATE__。
    # 412 对该 IP 是间歇性的，重试几次基本都能成功。
    headers = dict(_BILIBILI_HTTP_HEADERS)
    cookie_header = load_bilibili_cookie_header()
    if cookie_header:
        headers["Cookie"] = cookie_header

    # 补斜杠在这里统一做，避免某个调用方漏掉后拿到一个必然 412 的 URL
    # （重试 5 次也只是白等 30s）。
    url = _with_trailing_slash(url)

    response: httpx.Response | None = None
    for attempt in range(5):
        try:
            response = httpx.get(
                url,
                headers=headers,
                follow_redirects=True,
                timeout=30.0,
            )
            if response.status_code != 412:
                break
        except httpx.HTTPError:
            logger.warning(
                "failed to fetch bilibili page payload (attempt %d/5): %s",
                attempt + 1,
                url,
                exc_info=True,
            )
            response = None
        if attempt < 4:
            import time

            time.sleep(3 * (attempt + 1))
    if response is None:
        return {}
    if response.status_code != 200:
        logger.warning(
            "bilibili page fetch status=%s url=%s",
            response.status_code,
            url,
        )
    try:
        response.raise_for_status()
    except httpx.HTTPError:
        logger.warning("failed to fetch bilibili page payload: %s", url, exc_info=True)
        return {}

    match = re.search(r"__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;\s*\(function", response.text, re.S)
    if not match:
        return {}

    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        logger.warning("failed to parse bilibili page payload: %s", url, exc_info=True)
        return {}
    return payload if isinstance(payload, dict) else {}


def fetch_bilibili_page_catalog_payload(url: str) -> tuple[list[dict[str, object]], str]:
    payload = _fetch_bilibili_initial_state_payload(url)
    video_data = payload.get("videoData") or {}
    if not isinstance(video_data, dict):
        return [], ""

    pages = video_data.get("pages") or []
    cover_url = str(video_data.get("pic") or "").strip()
    return [item for item in pages if isinstance(item, dict)], cover_url


def fetch_bilibili_collection_payload(url: str) -> dict[str, object] | None:
    """Read a Bilibili season collection embedded in the video page."""
    try:
        normalized = normalize_video_url(url)
    except Exception:
        return None
    if normalized.platform != "bilibili":
        return None

    # 尾斜杠由 _fetch_bilibili_initial_state_payload 统一补齐。
    payload = _fetch_bilibili_initial_state_payload(normalized.normalized_url)
    video_data = payload.get("videoData") or {}
    if not isinstance(video_data, dict):
        return None
    season = video_data.get("ugc_season")
    if not isinstance(season, dict):
        # 「系列」(series) 不出现在视频页，回退反查 UP 空间接口
        return _fetch_bilibili_series_collection_payload(normalized, video_data)

    collection_id = str(season.get("id") or season.get("season_id") or "").strip()
    if not collection_id:
        return None
    collection_referer = f"https://www.bilibili.com/video/{normalized.canonical_id}/"
    items: list[dict[str, object]] = []
    sections = season.get("sections") or []
    for section_position, section in enumerate(
        sections if isinstance(sections, list) else [],
        start=1,
    ):
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("id") or section.get("section_id") or "").strip()
        section_title = str(section.get("title") or "").strip()
        episodes = section.get("episodes") or []
        for episode in episodes if isinstance(episodes, list) else []:
            if not isinstance(episode, dict):
                continue
            bvid = str(episode.get("bvid") or "").strip()
            if not bvid:
                continue
            arc = episode.get("arc") if isinstance(episode.get("arc"), dict) else {}
            page = episode.get("page") if isinstance(episode.get("page"), dict) else {}
            raw_duration = page.get("duration") or arc.get("duration")
            try:
                duration = float(raw_duration) if raw_duration is not None else None
            except (TypeError, ValueError):
                duration = None
            items.append(
                {
                    "position": len(items) + 1,
                    "bvid": bvid,
                    "title": first_non_empty(
                        str(arc.get("title") or ""),
                        str(episode.get("title") or ""),
                        bvid,
                    ),
                    "source_url": f"https://www.bilibili.com/video/{bvid}/",
                    "cover_url": first_non_empty(
                        str(arc.get("pic") or ""),
                        str(episode.get("cover") or ""),
                    ),
                    "duration": duration,
                    "source_section_id": section_id or None,
                    "source_section_title": section_title or None,
                    "source_section_position": section_position,
                    "is_current": bvid.lower() == normalized.canonical_id.lower(),
                }
            )

    if len(items) < 2:
        return None

    from concurrent.futures import ThreadPoolExecutor

    def cache_collection_item(item: dict[str, object]) -> dict[str, object]:
        cover_url = str(item.get("cover_url") or "").strip()
        if cover_url:
            item["cover_url"] = cache_cover_image(
                cover_url,
                f"collection-{collection_id}-{str(item.get('bvid') or 'video')}",
                referer_url=str(item.get("source_url") or collection_referer),
            )
        return item

    with ThreadPoolExecutor(max_workers=6, thread_name_prefix="bilibili-cover") as executor:
        items = list(executor.map(cache_collection_item, items))

    collection_cover_url = first_non_empty(str(season.get("cover") or ""), str(video_data.get("pic") or ""))
    cached_collection_cover = cache_cover_image(
        collection_cover_url,
        f"collection-{collection_id}",
        referer_url=collection_referer,
    )
    owner = video_data.get("owner") if isinstance(video_data.get("owner"), dict) else {}
    owner_mid = first_non_empty(str(owner.get("mid") or ""), str(owner.get("uid") or ""))
    owner_name = first_non_empty(str(owner.get("name") or ""), str(owner.get("uname") or ""))
    owner_face = first_non_empty(str(owner.get("face") or ""), str(owner.get("avatar") or ""))
    cached_owner_face = cache_cover_image(
        owner_face,
        f"collection-{collection_id}-owner",
        referer_url=collection_referer,
    ) if owner_face else ""
    return {
        "collection_id": collection_id,
        "title": first_non_empty(str(season.get("title") or ""), "Bilibili 合集"),
        "cover_url": cached_collection_cover,
        "owner_mid": owner_mid or None,
        "owner_name": owner_name or None,
        "owner_face": cached_owner_face or owner_face or None,
        "owner_url": f"https://space.bilibili.com/{owner_mid}" if owner_mid else None,
        "item_count": len(items),
        "items": items,
    }


def fetch_bilibili_page_catalog(url: str) -> list[dict[str, object]]:
    pages, _cover_url = fetch_bilibili_page_catalog_payload(url)
    return pages


def build_base_video_asset(
    *,
    canonical_id: str,
    platform: str,
    title: str,
    source_url: str,
    cover_url: str,
    duration: float | None,
    pages: list[VideoPageOptionResponse],
) -> VideoAssetRecord:
    return VideoAssetRecord(
        canonical_id=canonical_id,
        platform=platform,
        title=title,
        source_url=source_url,
        cover_url=cover_url,
        duration=duration,
        pages=pages,
    )


def merge_video_asset_metadata(
    existing: VideoAssetRecord,
    refreshed: VideoAssetRecord,
) -> VideoAssetRecord:
    existing_pages = {page.page: page for page in existing.pages}
    merged_pages: list[VideoPageOptionResponse] = []

    if refreshed.pages:
        for refreshed_page in refreshed.pages:
            existing_page = existing_pages.get(refreshed_page.page)
            if existing_page is None:
                merged_pages.append(refreshed_page)
                continue
            merged_pages.append(
                existing_page.model_copy(
                    update={
                        "title": refreshed_page.title or existing_page.title,
                        "source_url": refreshed_page.source_url or existing_page.source_url,
                        "cover_url": refreshed_page.cover_url or existing_page.cover_url,
                        "duration": refreshed_page.duration if refreshed_page.duration is not None else existing_page.duration,
                    }
                )
            )
        refreshed_page_numbers = {page.page for page in refreshed.pages}
        for existing_page in existing.pages:
            if existing_page.page not in refreshed_page_numbers:
                merged_pages.append(existing_page)
    else:
        merged_pages = list(existing.pages)

    cover_url = refreshed.cover_url or existing.cover_url
    if not cover_url and merged_pages:
        cover_url = next((page.cover_url for page in merged_pages if page.cover_url), "")

    return existing.model_copy(
        update={
            "platform": refreshed.platform or existing.platform,
            "title": refreshed.title or existing.title,
            "source_url": refreshed.source_url or existing.source_url,
            "cover_url": cover_url,
            "duration": refreshed.duration if refreshed.duration is not None else existing.duration,
            "pages": merged_pages,
        }
    )


def resolve_local_media_path(value: str) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    candidate_text = raw
    parsed = urlparse(raw)
    if parsed.scheme.lower() == "file":
        candidate_text = unquote(parsed.path or "")
        if re.match(r"^/[A-Za-z]:/", candidate_text):
            candidate_text = candidate_text.lstrip("/")

    candidate = Path(candidate_text).expanduser()
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved


def is_supported_local_media_file(path: Path) -> bool:
    return path.suffix.lower() in LOCAL_VIDEO_SUFFIXES | LOCAL_AUDIO_SUFFIXES


def infer_local_input_type(source: str | Path) -> InputType:
    path = source if isinstance(source, Path) else Path(str(source))
    return InputType.AUDIO_FILE if path.suffix.lower() in LOCAL_AUDIO_SUFFIXES else InputType.VIDEO_FILE


def build_local_media_canonical_id(file_path: Path) -> str:
    try:
        stats = file_path.stat()
        mtime_ns = getattr(stats, "st_mtime_ns", int(stats.st_mtime * 1_000_000_000))
        fingerprint = f"{str(file_path).lower()}|{stats.st_size}|{mtime_ns}"
    except OSError:
        fingerprint = str(file_path).lower()
    digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:24]
    return f"local-{digest}"


def resolve_ffprobe_executable() -> Path | None:
    ffmpeg_exe = ffmpeg_location()
    if ffmpeg_exe is not None:
        candidate = ffmpeg_exe.with_name("ffprobe.exe" if ffmpeg_exe.suffix.lower() == ".exe" else "ffprobe")
        if candidate.exists():
            return candidate

    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path:
        return Path(ffprobe_path).resolve()
    return None


def probe_local_media_duration(file_path: Path) -> float | None:
    ffprobe_exe = resolve_ffprobe_executable()
    if ffprobe_exe is None:
        return None

    try:
        result = subprocess.run(
            [
                str(ffprobe_exe),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        logger.warning("failed to probe local media duration: %s", file_path, exc_info=True)
        return None

    if result.returncode != 0:
        logger.warning("ffprobe duration failed path=%s stderr=%s", file_path, result.stderr.strip())
        return None

    try:
        duration = float((result.stdout or "").strip())
    except (TypeError, ValueError):
        return None
    return duration if duration >= 0 else None


def extract_local_video_cover(
    file_path: Path,
    canonical_id: str,
    duration: float | None,
    *,
    force_refresh: bool = False,
) -> str:
    if file_path.suffix.lower() not in LOCAL_VIDEO_SUFFIXES:
        return ""

    ffmpeg_exe = ffmpeg_location()
    if ffmpeg_exe is None:
        return ""

    COVER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = COVER_CACHE_DIR / f"{canonical_id}.jpg"
    if target.exists() and not force_refresh:
        return f"/media/covers/{target.name}"
    if force_refresh and target.exists():
        try:
            target.unlink()
        except OSError:
            logger.warning("failed to remove stale local cover: %s", target, exc_info=True)

    timestamp_seconds = 0.0
    if duration and duration > 1:
        timestamp_seconds = min(max(duration * 0.25, 0.2), max(duration - 0.2, 0.0))

    command = [str(ffmpeg_exe), "-y"]
    if timestamp_seconds > 0:
        command.extend(["-ss", f"{timestamp_seconds:.3f}"])
    command.extend(["-i", str(file_path), "-frames:v", "1", "-q:v", "2", str(target)])

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        logger.warning("failed to extract local video cover: %s", file_path, exc_info=True)
        return ""

    if result.returncode != 0 or not target.exists():
        logger.warning(
            "ffmpeg cover extraction failed path=%s returncode=%s stderr=%s",
            file_path,
            result.returncode,
            result.stderr.strip(),
        )
        return ""

    return f"/media/covers/{target.name}"


def probe_local_video_asset(
    file_path: Path,
    *,
    force_refresh: bool = False,
    title_override: str | None = None,
    canonical_id_override: str | None = None,
) -> VideoAssetRecord:
    canonical_id = canonical_id_override or build_local_media_canonical_id(file_path)
    duration = probe_local_media_duration(file_path)
    cover_url = extract_local_video_cover(
        file_path,
        canonical_id,
        duration,
        force_refresh=force_refresh,
    )
    title = str(title_override or "").strip() or file_path.stem.strip() or file_path.name
    return build_base_video_asset(
        canonical_id=canonical_id,
        platform="local",
        title=title,
        source_url=str(file_path),
        cover_url=cover_url,
        duration=duration,
        pages=[],
    )


def resolve_video_page(video: VideoAssetRecord, page_number: int | None) -> VideoPageOptionResponse | None:
    if not video.pages:
        return None
    target_page = page_number or 1
    return next((page for page in video.pages if page.page == target_page), None)


def probe_video_asset(
    url: str,
    force_refresh: bool = False,
) -> tuple[VideoAssetRecord, list[VideoPageOptionResponse], bool]:
    local_media_path = resolve_local_media_path(url)
    if local_media_path is not None:
        if not is_supported_local_media_file(local_media_path):
            raise HTTPException(status_code=400, detail="当前仅支持导入常见本地视频或音频文件。")
        return probe_local_video_asset(local_media_path, force_refresh=force_refresh), [], False

    normalized = normalize_video_url(url)
    normalized_url = normalized.normalized_url
    canonical_id = normalized.canonical_id
    platform = normalized.platform

    if platform not in {"bilibili", "youtube"}:
        raise HTTPException(status_code=400, detail="当前仅支持 Bilibili 或 YouTube 单条视频链接。")

    if platform == "youtube":
        info = extract_video_info(normalized_url)
        title = str(info.get("title") or canonical_id or normalized_url)
        thumbnail = str(info.get("thumbnail") or "")
        duration = float(info.get("duration")) if info.get("duration") else None
        actual_id = str(info.get("id") or canonical_id or normalized_url)
        cached_cover_url = cache_cover_image(thumbnail, actual_id, referer_url=normalized_url)
        return (
            build_base_video_asset(
                canonical_id=actual_id,
                platform="youtube",
                title=title,
                source_url=normalized_url,
                cover_url=cached_cover_url,
                duration=duration,
                pages=[],
            ),
            [],
            False,
        )

    requested_page = extract_bilibili_page(normalized_url)

    if requested_page is None:
        flat_info = extract_video_info(normalized_url, extract_flat=True)
        flat_entries = [entry for entry in flat_info.get("entries", []) if isinstance(entry, dict)]
        if len(flat_entries) > 1:
            top_title = str(flat_info.get("title") or canonical_id or normalized_url)
            top_id = str(flat_info.get("id") or canonical_id or normalized_url)
            catalog_entries, catalog_cover_url = fetch_bilibili_page_catalog_payload(normalized_url)
            catalog_by_page = {
                int(item.get("page") or 0): item
                for item in catalog_entries
                if str(item.get("page") or "").isdigit()
            }
            top_thumbnail = first_non_empty(
                extract_thumbnail_url(flat_info),
                catalog_cover_url,
                *(extract_thumbnail_url(entry) for entry in flat_entries),
                *(extract_thumbnail_url(entry) for entry in catalog_entries),
            )
            cached_cover_url = cache_cover_image(top_thumbnail, top_id, referer_url=normalized_url)
            pages: list[VideoPageOptionResponse] = []
            for index, entry in enumerate(flat_entries, start=1):
                page_url = str(
                    entry.get("url")
                    or with_bilibili_page(f"https://www.bilibili.com/video/{canonical_id}", index)
                )
                catalog_entry = catalog_by_page.get(index)
                page_title = build_page_title(
                    top_title,
                    index,
                    {
                        "part": str((catalog_entry or {}).get("part") or "").strip(),
                        "title": str(entry.get("title") or "").strip(),
                    },
                )
                pages.append(
                    VideoPageOptionResponse(
                        page=index,
                        title=page_title,
                        source_url=page_url,
                        cover_url=first_non_empty(
                            extract_thumbnail_url(entry),
                            extract_thumbnail_url(catalog_entry),
                            cached_cover_url,
                            top_thumbnail,
                        ),
                        duration=None,
                    )
                )

            return (
                build_base_video_asset(
                    canonical_id=top_id,
                    platform=str(flat_info.get("extractor_key") or "video").lower(),
                    title=top_title,
                    source_url=f"https://www.bilibili.com/video/{canonical_id}",
                    cover_url=cached_cover_url,
                    duration=None,
                    pages=pages,
                ),
                pages,
                True,
            )

    info = extract_video_info(normalized_url)

    title = str(info.get("title") or canonical_id or normalized_url)
    thumbnail = str(info.get("thumbnail") or "")
    duration = float(info.get("duration")) if info.get("duration") else None
    platform = str(info.get("extractor_key") or "video").lower()
    actual_id = str(info.get("id") or canonical_id or normalized_url)
    entries = [entry for entry in info.get("entries", []) if isinstance(entry, dict)]

    if entries:
        pages: list[VideoPageOptionResponse] = []
        for index, entry in enumerate(entries, start=1):
            page = int(entry.get("page") or entry.get("playlist_index") or index)
            page_title = build_page_title(title, page, entry)
            page_url = with_bilibili_page(f"https://www.bilibili.com/video/{canonical_id}", page)
            page_cover = str(entry.get("thumbnail") or thumbnail or "")
            page_duration = float(entry.get("duration")) if entry.get("duration") else None
            pages.append(
                VideoPageOptionResponse(
                    page=page,
                    title=page_title,
                    source_url=page_url,
                    cover_url=page_cover,
                    duration=page_duration,
                )
            )

        selected_page = requested_page or pages[0].page
        selected = next((item for item in pages if item.page == selected_page), pages[0])
        selected_cover = cache_cover_image(
            selected.cover_url or thumbnail,
            actual_id,
            referer_url=selected.source_url,
        )
        return (
            build_base_video_asset(
                canonical_id=actual_id,
                platform=platform,
                title=title,
                source_url=f"https://www.bilibili.com/video/{canonical_id}",
                cover_url=selected_cover,
                duration=duration,
                pages=pages,
            ),
            pages,
            requested_page is None and len(pages) > 1,
        )

    cached_cover_url = cache_cover_image(thumbnail, actual_id, referer_url=normalized_url)
    return (
        build_base_video_asset(
            canonical_id=actual_id,
            platform=platform,
            title=title,
            source_url=normalized_url,
            cover_url=cached_cover_url,
            duration=duration,
            pages=[],
        ),
        [],
        False,
    )


def localize_video_cover(task_store: SqliteTaskRepository, video: VideoAssetRecord) -> VideoAssetRecord:
    cover_file_missing = (
        bool(video.cover_url)
        and video.cover_url.startswith("/media/")
        and not (COVER_CACHE_DIR / video.cover_url.rsplit("/", 1)[-1]).exists()
    )
    if (not video.cover_url or cover_file_missing) and str(video.platform or "").lower() == "bilibili":
        probe_url = video.source_url or f"https://www.bilibili.com/video/{str(video.canonical_id).split('?', 1)[0]}"
        try:
            refreshed, _pages, _requires_selection = probe_video_asset(probe_url, force_refresh=True)
        except Exception:
            logger.warning("failed to refresh missing bilibili cover: %s", video.video_id, exc_info=True)
            return video
        merged = merge_video_asset_metadata(video, refreshed)
        if merged.cover_url and not merged.cover_url.startswith("/media/"):
            localized = cache_cover_image(merged.cover_url, merged.canonical_id, referer_url=merged.source_url)
            if localized != merged.cover_url:
                merged = merged.model_copy(update={"cover_url": localized})
        if merged.cover_url:
            return task_store.upsert_video_asset(merged)
        return video
    if not video.cover_url or video.cover_url.startswith("/media/"):
        return video
    localized = cache_cover_image(video.cover_url, video.canonical_id, referer_url=video.source_url)
    if localized == video.cover_url:
        return video
    updated = video.model_copy(update={"cover_url": localized})
    return task_store.upsert_video_asset(updated)
