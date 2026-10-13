"""UP 主动态监控 REST API。"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse

from video_sum_service import bilibili_wbi
from video_sum_service.bilibili_cookies import BILIBILI_BROWSER_HEADERS
from video_sum_service.bilibili_wbi import (
    CookieInvalidError,
    CookieMissingError,
    UpDynamicsError,
    UpNotFoundError,
)
from video_sum_service.context import settings_manager
from video_sum_service.repository import SqliteTaskRepository
from video_sum_service.schemas import (
    UpDetectedVideoResponse,
    UpDynamicsFeedResponse,
    UpDynamicsMarkReadRequest,
    UpDynamicsRefreshResponse,
    UpDynamicsStatusResponse,
    UpDynamicsUnreadCountResponse,
    UpSubscriptionCreateRequest,
    UpSubscriptionResponse,
    UpSubscriptionUpdateRequest,
)
from video_sum_service.up_dynamics import UpDynamicsWatcher, _TASK_TERMINAL_STATUSES

router = APIRouter(prefix="/api/v1/dynamics", tags=["dynamics"])


def _repository(request: Request) -> SqliteTaskRepository:
    return request.app.state.task_repository


def _watcher(request: Request) -> UpDynamicsWatcher | None:
    return getattr(request.app.state, "up_dynamics_watcher", None)


def _require_cookie() -> str:
    header = bilibili_wbi.load_bilibili_cookie_header()
    if not header:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="B 站登录态缺失，请先在设置页扫码登录后再订阅 UP 主。",
        )
    return header


def _subscription_response(task_store: SqliteTaskRepository, row: dict) -> UpSubscriptionResponse:
    return UpSubscriptionResponse(
        subscription_id=str(row.get("subscription_id") or ""),
        mid=str(row.get("mid") or ""),
        up_name=str(row.get("up_name") or ""),
        up_face_url=str(row.get("up_face_url") or ""),
        enabled=bool(row.get("enabled")),
        last_checked_at=row.get("last_checked_at"),
        last_error=row.get("last_error"),
        consecutive_failures=int(row.get("consecutive_failures") or 0),
        unread_count=task_store.count_unread_up_dynamics_by_subscription(
            str(row.get("subscription_id") or "")
        ),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _detection_response(row: dict) -> UpDetectedVideoResponse:
    return UpDetectedVideoResponse(
        detection_id=str(row.get("detection_id") or ""),
        subscription_id=str(row.get("subscription_id") or ""),
        bvid=str(row.get("bvid") or ""),
        aid=row.get("aid"),
        title=str(row.get("title") or ""),
        cover_url=str(row.get("cover_url") or ""),
        duration=int(row.get("duration") or 0),
        pubdate=int(row.get("pubdate") or 0),
        description=str(row.get("description") or ""),
        video_id=row.get("video_id"),
        task_id=row.get("task_id"),
        task_status=row.get("task_status"),
        unread=row.get("read_at") is None,
        detection_status=str(row.get("detection_status") or "new"),
        created_at=row.get("created_at"),
    )


@router.get("/status", response_model=UpDynamicsStatusResponse)
def get_dynamics_status(request: Request) -> UpDynamicsStatusResponse:
    current = settings_manager.current
    watcher = _watcher(request)
    watcher_status = watcher.status() if watcher is not None else {}
    return UpDynamicsStatusResponse(
        enabled=bool(current.up_dynamics_enabled),
        poll_interval_seconds=int(current.up_dynamics_poll_interval_seconds or 600),
        cookie_ready=bool(watcher_status.get("cookieReady", True)),
        watcher_running=bool(watcher_status.get("running", False)),
        last_round_at=watcher_status.get("lastRoundAt"),
        last_round_error=watcher_status.get("lastRoundError"),
        subscription_count=len(_repository(request).list_up_subscriptions()),
    )


@router.post("/subscriptions", response_model=UpSubscriptionResponse, status_code=status.HTTP_201_CREATED)
def create_subscription(body: UpSubscriptionCreateRequest, request: Request) -> UpSubscriptionResponse:
    task_store = _repository(request)
    cookie_header = _require_cookie()
    try:
        identity = bilibili_wbi.resolve_up_identity(body.query, cookie_header)
    except CookieInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except UpNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UpDynamicsError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    existing = task_store.get_up_subscription_by_mid(identity["mid"])
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已订阅该 UP 主。")
    row = task_store.create_up_subscription(identity["mid"], identity["name"], identity["face"])
    watcher = _watcher(request)
    if watcher is not None:
        watcher.refresh_now()
    return _subscription_response(task_store, row)


@router.get("/subscriptions", response_model=list[UpSubscriptionResponse])
def list_subscriptions(request: Request) -> list[UpSubscriptionResponse]:
    task_store = _repository(request)
    return [_subscription_response(task_store, row) for row in task_store.list_up_subscriptions()]


@router.patch("/subscriptions/{subscription_id}", response_model=UpSubscriptionResponse)
def update_subscription(
    subscription_id: str,
    body: UpSubscriptionUpdateRequest,
    request: Request,
) -> UpSubscriptionResponse:
    task_store = _repository(request)
    row = task_store.get_up_subscription(subscription_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订阅不存在。")
    fields = body.model_dump(exclude_none=True)
    if fields:
        row = task_store.update_up_subscription(subscription_id, **fields)
    watcher = _watcher(request)
    if watcher is not None and fields.get("enabled"):
        watcher.refresh_now()
    return _subscription_response(task_store, row)


@router.delete("/subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subscription(subscription_id: str, request: Request) -> None:
    task_store = _repository(request)
    if not task_store.get_up_subscription(subscription_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订阅不存在。")
    task_store.delete_up_subscription(subscription_id)


@router.get("/feed", response_model=UpDynamicsFeedResponse)
def get_feed(
    request: Request,
    subscription_id: str | None = None,
    unread_only: bool = False,
    page: int = 1,
    page_size: int = 30,
) -> UpDynamicsFeedResponse:
    task_store = _repository(request)
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    rows, total = task_store.list_up_detected_videos(
        subscription_id=subscription_id,
        unread_only=unread_only,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return UpDynamicsFeedResponse(
        items=[_detection_response(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        unread_count=task_store.count_unread_up_dynamics(),
    )


@router.get("/feed/unread-count", response_model=UpDynamicsUnreadCountResponse)
def get_unread_count(request: Request) -> UpDynamicsUnreadCountResponse:
    return UpDynamicsUnreadCountResponse(unread_count=_repository(request).count_unread_up_dynamics())


@router.post("/feed/read", response_model=UpDynamicsUnreadCountResponse)
def mark_read(body: UpDynamicsMarkReadRequest, request: Request) -> UpDynamicsUnreadCountResponse:
    task_store = _repository(request)
    if body.mark_all:
        task_store.mark_up_dynamics_read()
    elif body.subscription_id is not None:
        task_store.mark_up_dynamics_read(subscription_id=body.subscription_id)
    else:
        task_store.mark_up_dynamics_read(detection_ids=body.detection_ids or [])
    return UpDynamicsUnreadCountResponse(unread_count=task_store.count_unread_up_dynamics())


@router.post("/refresh", response_model=UpDynamicsRefreshResponse)
def refresh_dynamics(request: Request) -> UpDynamicsRefreshResponse:
    watcher = _watcher(request)
    if watcher is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="动态监控服务未启动。")
    watcher.refresh_now()
    return UpDynamicsRefreshResponse(accepted=True)


_IMAGE_PROXY_HOST_SUFFIXES = (
    "hdslb.com",
    "bilivideo.com",
    "biliimg.net",
    "acgvideo.com",
    "bilibili.com",
)
_IMAGE_PROXY_CACHE_TTL_SECONDS = 7 * 24 * 3600
_IMAGE_PROXY_MAX_BYTES = 10 * 1024 * 1024
_OSS_KEY_PREFIX = "up-images"
_OSS_CLIENT_CACHE: dict[tuple[str, str, str, str], object] = {}


def _image_cache_dir(request: Request) -> Path:
    cache_dir = Path(settings_manager.current.cache_dir) / "up-images"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _is_proxyable_image_host(hostname: str) -> bool:
    host = hostname.lower().strip(".")
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in _IMAGE_PROXY_HOST_SUFFIXES)


def _oss_config(current: object) -> tuple[str, str, str, str, str] | None:
    """返回 (bucket, endpoint, ak, sk, public_base)；未配置完整时返回 None。"""
    bucket = str(getattr(current, "oss_bucket", "") or "").strip()
    endpoint = str(getattr(current, "oss_endpoint", "") or "").strip()
    ak = str(getattr(current, "oss_access_key_id", "") or "").strip()
    sk = str(getattr(current, "oss_access_key_secret", "") or "").strip()
    if not (bucket and endpoint and ak and sk):
        return None
    public_base = str(getattr(current, "oss_public_base_url", "") or "").strip()
    if not public_base:
        public_base = f"https://{bucket}.{endpoint}"
    return bucket, endpoint, ak, sk, public_base.rstrip("/")


def _oss_bucket_client(config: tuple[str, str, str, str, str]):
    try:
        import oss2  # type: ignore[import-not-found]
    except ImportError:
        return None
    bucket_name, endpoint, ak, sk, _public_base = config
    client_key = (bucket_name, endpoint, ak, sk)
    bucket = _OSS_CLIENT_CACHE.get(client_key)
    if bucket is None:
        bucket = oss2.Bucket(oss2.Auth(ak, sk), f"https://{endpoint}", bucket_name)
        _OSS_CLIENT_CACHE[client_key] = bucket
    return bucket


def _oss_upload(config: tuple[str, str, str, str, str], object_key: str, content: bytes, content_type: str) -> bool:
    bucket_name, endpoint, ak, sk, _public_base = config
    client_key = (bucket_name, endpoint, ak, sk)
    try:
        bucket = _oss_bucket_client(config)
        if bucket is None:
            return False
        bucket.put_object(object_key, content, headers={"Content-Type": content_type})
        return True
    except Exception:  # noqa: BLE001 - 上游 OSS 故障时回退本地缓存
        _OSS_CLIENT_CACHE.pop(client_key, None)
        return False


def _oss_signed_url(config: tuple[str, str, str, str, str], object_key: str, expires: int = 3600) -> str | None:
    """私有 Bucket 场景下生成临时签名 URL；签名失败返回 None。"""
    bucket_name, endpoint, ak, sk, _public_base = config
    client_key = (bucket_name, endpoint, ak, sk)
    try:
        bucket = _oss_bucket_client(config)
        if bucket is None:
            return None
        return bucket.sign_url("GET", object_key, expires)
    except Exception:  # noqa: BLE001 - 签名失败时回退本地缓存
        _OSS_CLIENT_CACHE.pop(client_key, None)
        return None


@router.get("/image-proxy")
def proxy_dynamics_image(url: str, request: Request) -> FileResponse:
    """代理 B 站图片（头像/封面），绕开 hdslb 防盗链；配置 OSS 时转存并 302 跳转。"""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or not _is_proxyable_image_host(parsed.hostname):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的图片地址。")

    cache_dir = _image_cache_dir(request)
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()
    image_path = cache_dir / key
    meta_path = cache_dir / f"{key}.json"

    fresh = (
        image_path.exists()
        and meta_path.exists()
        and (time.time() - image_path.stat().st_mtime) < _IMAGE_PROXY_CACHE_TTL_SECONDS
    )
    if not fresh:
        try:
            response = httpx.get(
                url,
                headers=BILIBILI_BROWSER_HEADERS,
                timeout=15.0,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=f"图片拉取失败：{exc}"
            ) from exc
        content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
        if response.status_code != 200 or not content_type.startswith("image/"):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"上游图片不可用（HTTP {response.status_code}）。",
            )
        if len(response.content) > _IMAGE_PROXY_MAX_BYTES:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="图片超出大小限制。")
        tmp_path = image_path.with_suffix(".tmp")
        tmp_path.write_bytes(response.content)
        tmp_path.replace(image_path)
        meta: dict[str, str] = {"content_type": content_type}
        oss = _oss_config(settings_manager.current)
        if oss is not None:
            object_key = f"{_OSS_KEY_PREFIX}/{key}"
            if _oss_upload(oss, object_key, response.content, content_type):
                meta["oss_object_key"] = object_key
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

    meta: dict[str, object] = {}
    content_type = "application/octet-stream"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        content_type = str(meta.get("content_type") or content_type)
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    oss = _oss_config(settings_manager.current)
    oss_object_key = str(meta.get("oss_object_key") or "").strip()
    if oss is not None and oss_object_key:
        signed_url = _oss_signed_url(oss, oss_object_key)
        if signed_url:
            return RedirectResponse(signed_url, status_code=status.HTTP_302_FOUND)
    oss_url = str(meta.get("oss_url") or "").strip()
    if oss_url:
        return RedirectResponse(oss_url, status_code=status.HTTP_302_FOUND)
    return FileResponse(
        image_path,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/feed/{detection_id}/summarize", response_model=UpDetectedVideoResponse)
def summarize_detection(detection_id: str, request: Request) -> UpDetectedVideoResponse:
    task_store = _repository(request)
    detection = task_store.get_up_detected_video(detection_id)
    if detection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="动态记录不存在。")
    task_status = str(detection.get("task_status") or "")
    if detection.get("task_id") and task_status not in _TASK_TERMINAL_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该视频已有进行中的总结任务。")

    watcher = _watcher(request)
    if watcher is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="动态监控服务未启动。")
    try:
        task_id = watcher.submit_detection_task(detection)
    except CookieMissingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not task_id:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="任务提交失败，请稍后重试。")

    refreshed = task_store.get_up_detected_video(detection_id)
    assert refreshed is not None
    return _detection_response(refreshed)
