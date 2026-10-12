"""UP 主动态监控 REST API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from video_sum_service import bilibili_wbi
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
