"""B 站 WBI 签名与 UP 主视频列表客户端。

空间类 API（``/x/space/wbi/arc/search``、``/x/space/wbi/acc/info``）强制要求
WBI 签名（wts + w_rid）与登录态（SESSDATA）。签名算法为公开实现，mixin 置换表
逐字取自维护中的参考实现（bilibili-api-python），一处下标错位即全量 -352。
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import httpx

from video_sum_service.bilibili_cookies import BILIBILI_BROWSER_HEADERS
from video_sum_service.context import settings_manager

logger = logging.getLogger(__name__)

BILIBILI_NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
BILIBILI_SPACE_ACC_INFO_URL = "https://api.bilibili.com/x/space/wbi/acc/info"
BILIBILI_SPACE_ARC_SEARCH_URL = "https://api.bilibili.com/x/space/wbi/arc/search"
# 匿名下发 buvid3/buvid4 设备指纹，无需登录态。
BILIBILI_FINGER_SPI_URL = "https://api.bilibili.com/x/frontend/finger/spi"

# mixin 置换表（64 项，顺序不可更改；取自公开参考实现）。
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32,
    15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19,
    29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63,
    57, 62, 11, 36, 20, 34, 44, 52,
]

# 值中这些字符会在签名前被移除（算法约定）。
_WBI_VALUE_FILTER = str.maketrans("", "", "!'()*")

_WBI_KEY_TTL_SECONDS = 12 * 60 * 60
_SPACE_URL_RE = re.compile(r"space\.bilibili\.com/(\d+)")
_DM_RAND = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"

# 顶栏账号信息（头像/昵称）的缓存时长。前端每秒级轮询 system 接口，nav 接口
# 没必要跟着打；换 cookie 时缓存 key 自然失效，所以登录后无需手动清除。
_ACCOUNT_CACHE_TTL_SECONDS = 5 * 60.0
_account_lock = threading.Lock()
_account_cache: tuple[str, float, dict[str, object]] | None = None


class UpDynamicsError(Exception):
    """UP 动态抓取的基础异常，携带 B 站业务 code 与 message。"""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class CookieMissingError(UpDynamicsError):
    """本地没有可用的 B 站登录 cookie 文件。"""


class CookieInvalidError(UpDynamicsError):
    """登录态失效（-101 未登录 / -401 非法访问）。"""


class RateLimitedError(UpDynamicsError):
    """请求被风控限流（-412），调用方应退避。"""


class UpNotFoundError(UpDynamicsError):
    """UP 主不存在或已注销（acc/info -404）。"""


class WbiRiskControlError(UpDynamicsError):
    """WBI 签名校验失败（-352 / -2233），重试一次仍失败则上抛。"""


class UpstreamError(UpDynamicsError):
    """其他非 0 业务 code 或 HTTP 错误。"""


@dataclass(frozen=True)
class UpVideoItem:
    bvid: str
    aid: int | None
    title: str
    cover_url: str
    duration: int
    pubdate: int
    description: str


def bilibili_cookie_file() -> Path:
    return Path(settings_manager.current.data_dir) / "cookies" / "bilibili.txt"


def load_bilibili_cookie_header() -> str | None:
    """从 Netscape cookie 文件拼出 Cookie 头（含设备指纹）；必须含 SESSDATA 才算有效。"""
    cookie_path = bilibili_cookie_file()
    if not cookie_path.exists():
        return None
    try:
        parts: list[str] = []
        has_sessdata = False
        for line in cookie_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 7 or "bilibili.com" not in fields[0]:
                continue
            name, value = fields[5], fields[6]
            if not name or not value:
                continue
            if name == "SESSDATA":
                has_sessdata = True
            parts.append(f"{name}={value}")
        if not has_sessdata:
            return None
        return cookie_header_with_fingerprint("; ".join(parts)) if parts else None
    except OSError as exc:
        logger.warning("failed to read bilibili cookie file: %s", exc)
        return None


_FINGERPRINT_TTL_SECONDS = 12 * 60 * 60
_fingerprint_lock = threading.Lock()
_fingerprint_cache: tuple[float, dict[str, str]] | None = None


def _fetch_device_fingerprint() -> dict[str, str]:
    """匿名领取 buvid3/buvid4 设备指纹。

    2022-08-24 起 B 站 Web 接口要求携带 ``buvid3``，缺失会触发 -412；扫码登录
    导出的 cookie 里通常只有 buvid3 且未必带上，buvid4 更是没有。文档要求
    **持久化**（不要每次请求新生成），所以这里按进程缓存而非逐次请求。
    """
    with httpx.Client(timeout=10, follow_redirects=True, headers=BILIBILI_BROWSER_HEADERS) as client:
        response = client.get(BILIBILI_FINGER_SPI_URL)
        response.raise_for_status()
        payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise UpstreamError("B 站指纹接口响应格式无效")
    fingerprint = {
        key: str(data.get(source) or "").strip()
        for key, source in (("buvid3", "b_3"), ("buvid4", "b_4"))
    }
    if not fingerprint["buvid3"]:
        raise UpstreamError("B 站指纹接口未返回 buvid3")
    return {key: value for key, value in fingerprint.items() if value}


def _device_fingerprint_cookies() -> dict[str, str]:
    """取设备指纹 cookie（带进程级缓存）；失败时返回空字典而不是抛错。"""
    global _fingerprint_cache
    now = time.monotonic()
    with _fingerprint_lock:
        cached = _fingerprint_cache
        if cached is not None and (now - cached[0]) < _FINGERPRINT_TTL_SECONDS:
            return dict(cached[1])
    try:
        fingerprint = _fetch_device_fingerprint()
    except (httpx.HTTPError, ValueError, UpstreamError) as exc:
        logger.warning("failed to obtain bilibili device fingerprint: %s", exc)
        return {}
    with _fingerprint_lock:
        _fingerprint_cache = (now, fingerprint)
    return dict(fingerprint)


def cookie_header_with_fingerprint(cookie_header: str) -> str:
    """补齐 cookie 头里缺失的 buvid3/buvid4，已有的一律保留（文档要求持久沿用）。"""
    present = {
        part.split("=", 1)[0].strip()
        for part in cookie_header.split(";")
        if "=" in part
    }
    additions = [
        f"{name}={value}"
        for name, value in _device_fingerprint_cookies().items()
        if name not in present
    ]
    if not additions:
        return cookie_header
    return "; ".join([cookie_header, *additions]) if cookie_header else "; ".join(additions)


def reset_fingerprint_cache_for_tests() -> None:
    global _fingerprint_cache
    with _fingerprint_lock:
        _fingerprint_cache = None


def _fetch_bilibili_account(cookie_header: str) -> dict[str, object]:
    try:
        with httpx.Client(timeout=10, follow_redirects=True, headers=BILIBILI_BROWSER_HEADERS) as client:
            response = client.get(BILIBILI_NAV_URL, headers={"Cookie": cookie_header})
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("failed to load bilibili account info: %s", exc)
        return {
            "loggedIn": False,
            "mid": 0,
            "name": "",
            "face": "",
            "message": "B 站账号信息获取失败。",
        }
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not data.get("isLogin"):
        return {
            "loggedIn": False,
            "mid": 0,
            "name": "",
            "face": "",
            "message": "B 站登录态已失效，请重新登录。",
        }
    face = str(data.get("face") or "")
    if face.startswith("//"):
        face = "https:" + face
    return {
        "loggedIn": True,
        "mid": int(data.get("mid") or 0),
        "name": str(data.get("uname") or ""),
        "face": face,
        "message": "",
    }


def describe_bilibili_account(*, force: bool = False) -> dict[str, object]:
    """当前登录账号信息，供前端顶栏展示。

    未登录、登录态失效或接口异常都返回 ``loggedIn=False`` 而不抛异常：顶栏只是
    展示位，不该因为 B 站抖动而让整个 system 请求失败。
    """
    global _account_cache
    cookie_header = load_bilibili_cookie_header()
    if not cookie_header:
        return {
            "loggedIn": False,
            "mid": 0,
            "name": "",
            "face": "",
            "message": "尚未配置 B 站登录态。",
        }
    now = time.monotonic()
    with _account_lock:
        cached = _account_cache
        if (
            not force
            and cached is not None
            and cached[0] == cookie_header
            and (now - cached[1]) < _ACCOUNT_CACHE_TTL_SECONDS
        ):
            return dict(cached[2])
    result = _fetch_bilibili_account(cookie_header)
    with _account_lock:
        _account_cache = (cookie_header, now, result)
    return dict(result)


def _derive_mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    mixed = "".join(raw[i] if i < len(raw) else "" for i in MIXIN_KEY_ENC_TAB)
    return mixed[:32]


def _encode_params(params: dict[str, object]) -> str:
    """按 WBI 约定编码查询串。

    ``urllib.parse.urlencode`` 默认用 ``+`` 编码空格，而 B 站校验要求 ``%20``；
    签名与实际发送必须走同一个函数，否则算出的 ``w_rid`` 与实际请求对不上。
    十六进制字母 urlencode 默认大写，符合要求。
    """
    return urllib.parse.urlencode(sorted(params.items()), quote_via=urllib.parse.quote)


def _sign_params(params: dict[str, object], mixin_key: str) -> dict[str, object]:
    signed = {key: value for key, value in params.items() if key != "w_rid"}
    signed["wts"] = int(time.time())
    # 值过滤：算法约定移除 !'()* 字符。
    filtered = {
        key: str(value).translate(_WBI_VALUE_FILTER)
        for key, value in signed.items()
    }
    query = _encode_params(filtered)
    signed["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    return signed


class WbiSigner:
    """带内存缓存的 WBI 签名器；key 过期或 -352 时自动刷新。"""

    def __init__(self) -> None:
        self._img_key = ""
        self._sub_key = ""
        self._fetched_at = 0.0

    def _refresh_keys(self, client: httpx.Client, cookie_header: str) -> None:
        response = client.get(BILIBILI_NAV_URL, headers={"Cookie": cookie_header})
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        wbi_img = data.get("wbi_img") if isinstance(data, dict) else None
        if not isinstance(wbi_img, dict):
            raise UpstreamError("WBI nav 响应缺少 wbi_img 字段")
        img_url = str(wbi_img.get("img_url") or "")
        sub_url = str(wbi_img.get("sub_url") or "")
        img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
        sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
        if not img_key or not sub_key:
            raise UpstreamError("WBI nav 响应缺少 img_key/sub_key")
        self._img_key = img_key
        self._sub_key = sub_key
        self._fetched_at = time.monotonic()

    def _keys(self, client: httpx.Client, cookie_header: str) -> tuple[str, str]:
        stale = (time.monotonic() - self._fetched_at) > _WBI_KEY_TTL_SECONDS
        if not self._img_key or not self._sub_key or stale:
            self._refresh_keys(client, cookie_header)
        return self._img_key, self._sub_key

    def invalidate(self) -> None:
        # 必须连 key 一起清：stale 判断依赖 time.monotonic()(系统启动时长)，
        # 开机不足 _WBI_KEY_TTL_SECONDS 的机器上只清时间戳无法触发刷新，
        # -352 重试会用相同 key 再失败。
        self._img_key = ""
        self._sub_key = ""
        self._fetched_at = 0.0

    def sign(self, client: httpx.Client, cookie_header: str, params: dict[str, object]) -> dict[str, object]:
        img_key, sub_key = self._keys(client, cookie_header)
        return _sign_params(params, _derive_mixin_key(img_key, sub_key))


_signer = WbiSigner()


def _classify_code(url: str, code: int, message: str) -> UpDynamicsError:
    if code in (-101, -401):
        return CookieInvalidError(f"登录态失效（{code}）：{message}", code=code)
    if code == -412:
        return RateLimitedError(f"请求被限流（-412）：{message}", code=code)
    if code == -352:
        return WbiRiskControlError(f"WBI 风控校验失败（-352）：{message}", code=code)
    if code == -2233:
        return WbiRiskControlError(f"WBI 参数错误（-2233）：{message}", code=code)
    if code == -404 and "acc/info" in url:
        return UpNotFoundError(f"UP 主不存在（-404）：{message}", code=code)
    return UpstreamError(f"B 站接口返回错误（{code}）：{message}", code=code)


def _signed_get(
    url: str,
    params: dict[str, object],
    cookie_header: str,
    *,
    retry_on_risk_control: bool = True,
) -> dict[str, object]:
    """发起 WBI 签名 GET 请求并解析业务 code；必要时刷新 key 重试一次。"""
    # 设备指纹对所有 B 站 Web 接口都是硬要求，统一在这里补齐，签名与实际
    # 发送的 Cookie 才是同一份。
    cookie_header = cookie_header_with_fingerprint(cookie_header)
    with httpx.Client(timeout=30, follow_redirects=True, headers=BILIBILI_BROWSER_HEADERS) as client:
        attempt = 0
        while True:
            signed = _signer.sign(client, cookie_header, params)
            try:
                # 用 _encode_params 自己拼 query 而不是交给 httpx 的 params=：
                # httpx 会按自己的规则重新编码，和签名时的串不一致就必然 -352。
                response = client.get(
                    f"{url}?{_encode_params(signed)}",
                    headers={"Cookie": cookie_header},
                )
            except httpx.HTTPError as exc:
                raise UpstreamError(f"B 站接口请求失败：{exc}") from exc
            try:
                payload = response.json()
            except ValueError as exc:
                raise UpstreamError(f"B 站接口返回非 JSON（HTTP {response.status_code}）") from exc
            if response.status_code != 200:
                raise UpstreamError(f"B 站接口 HTTP {response.status_code}：{response.text[:200]}")
            code = int(payload.get("code") or 0)
            if code == 0:
                data = payload.get("data")
                return data if isinstance(data, dict) else {}
            message = str(payload.get("message") or payload.get("msg") or "")
            error = _classify_code(url, code, message)
            if isinstance(error, WbiRiskControlError) and retry_on_risk_control and attempt == 0:
                attempt += 1
                _signer.invalidate()
                logger.warning("wbi sign rejected (code %s), refreshing keys and retrying", code)
                continue
            raise error


def resolve_up_identity(query: str, cookie_header: str) -> dict[str, str]:
    """把空间 URL 或 UID 解析为 {mid, name, face}。"""
    text = str(query or "").strip()
    match = _SPACE_URL_RE.search(text)
    if match:
        mid = match.group(1)
    elif text.isdigit():
        mid = text
    else:
        raise UpDynamicsError("无法识别的 UP 主：请粘贴空间链接（space.bilibili.com/数字）或 UID")
    data = _signed_get(BILIBILI_SPACE_ACC_INFO_URL, {"mid": mid}, cookie_header)
    name = str(data.get("name") or "")
    if not name:
        raise UpNotFoundError(f"UP 主 {mid} 信息为空")
    face = str(data.get("face") or "")
    return {"mid": mid, "name": name, "face": face}


def _parse_duration_seconds(value: object) -> int:
    """vlist 的 length 字段是 'MM:SS' / 'HH:MM:SS' 格式字符串。"""
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        pass
    parts = text.split(":")
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return 0
    seconds = 0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def fetch_up_videos(
    mid: str,
    cookie_header: str,
    *,
    ps: int = 30,
    pn: int = 1,
) -> list[UpVideoItem]:
    """拉取 UP 主视频投稿列表（按发布时间倒序）。

    arc/search 的 vlist 只包含视频投稿，图文/转发动态不会出现，天然符合 v1 范围。
    """
    data = _signed_get(
        BILIBILI_SPACE_ARC_SEARCH_URL,
        {
            "mid": str(mid),
            "ps": int(ps),
            "pn": int(pn),
            "order": "pubdate",
            "platform": "web",
            "dm_img_list": "[]",
            "dm_img_str": "".join(random.sample(_DM_RAND, 2)),
            "dm_cover_img_str": "".join(random.sample(_DM_RAND, 2)),
            "dm_img_inter": json.dumps({"ds": [], "wh": [0, 0, 0], "of": [0, 0, 0]}, separators=(",", ":")),
        },
        cookie_header,
    )
    items: list[UpVideoItem] = []
    list_info = data.get("list")
    vlist = list_info.get("vlist") if isinstance(list_info, dict) else None
    if not isinstance(vlist, list):
        return items
    for entry in vlist:
        if not isinstance(entry, dict):
            continue
        bvid = str(entry.get("bvid") or "")
        if not bvid:
            continue
        cover = str(entry.get("pic") or "")
        if cover.startswith("//"):
            cover = "https:" + cover
        items.append(
            UpVideoItem(
                bvid=bvid,
                aid=int(entry["aid"]) if entry.get("aid") is not None else None,
                title=str(entry.get("title") or ""),
                cover_url=cover,
                duration=_parse_duration_seconds(entry.get("length")),
                pubdate=int(entry.get("created") or 0),
                description=str(entry.get("description") or ""),
            )
        )
    return items
