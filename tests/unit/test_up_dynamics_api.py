import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from video_sum_service.app import app
from video_sum_service.repository import SqliteTaskRepository
from video_sum_service.routers import dynamics
from video_sum_service.schemas import (
    UpDynamicsMarkReadRequest,
    UpSubscriptionCreateRequest,
    UpSubscriptionUpdateRequest,
)


def create_repository() -> SqliteTaskRepository:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    repository = SqliteTaskRepository(connection)
    repository.initialize()
    return repository


def make_request(repository: SqliteTaskRepository, watcher=None):
    app.state.task_repository = repository
    app.state.up_dynamics_watcher = watcher
    return type("Request", (), {"app": app})()


def make_watcher(repository: SqliteTaskRepository) -> MagicMock:
    watcher = MagicMock()
    watcher.status.return_value = {
        "running": True,
        "cookieReady": True,
        "lastRoundAt": None,
        "lastRoundError": None,
    }
    watcher.submit_detection_task.return_value = "task-new"
    return watcher


def test_status_endpoint():
    repository = create_repository()
    repository.create_up_subscription("1001", "UP 甲")
    request = make_request(repository, make_watcher(repository))
    response = dynamics.get_dynamics_status(request)
    assert response.subscription_count == 1
    assert response.cookie_ready is True
    assert response.watcher_running is True


def test_create_subscription_success():
    repository = create_repository()
    request = make_request(repository, make_watcher(repository))
    identity = {"mid": "208259", "name": "某 UP", "face": "https://face/x.jpg"}
    with patch.object(dynamics.bilibili_wbi, "load_bilibili_cookie_header", return_value="cookie"):
        with patch.object(dynamics.bilibili_wbi, "resolve_up_identity", return_value=identity):
            response = dynamics.create_subscription(
                UpSubscriptionCreateRequest(query="https://space.bilibili.com/208259"), request
            )
    assert response.mid == "208259"
    assert response.up_name == "某 UP"
    assert response.enabled is True


def test_create_subscription_requires_cookie():
    repository = create_repository()
    request = make_request(repository, make_watcher(repository))
    with patch.object(dynamics.bilibili_wbi, "load_bilibili_cookie_header", return_value=None):
        try:
            dynamics.create_subscription(UpSubscriptionCreateRequest(query="208259"), request)
        except HTTPException as exc:
            assert exc.status_code == 409
        else:  # pragma: no cover
            raise AssertionError("expected HTTPException")


def test_create_subscription_rejects_duplicate_mid():
    repository = create_repository()
    repository.create_up_subscription("208259", "某 UP")
    request = make_request(repository, make_watcher(repository))
    with patch.object(dynamics.bilibili_wbi, "load_bilibili_cookie_header", return_value="cookie"):
        with patch.object(
            dynamics.bilibili_wbi,
            "resolve_up_identity",
            return_value={"mid": "208259", "name": "某 UP", "face": ""},
        ):
            try:
                dynamics.create_subscription(UpSubscriptionCreateRequest(query="208259"), request)
            except HTTPException as exc:
                assert exc.status_code == 409
                assert "已订阅" in exc.detail
            else:  # pragma: no cover
                raise AssertionError("expected HTTPException")


def test_update_and_delete_subscription():
    repository = create_repository()
    subscription = repository.create_up_subscription("1001", "A")
    sid = subscription["subscription_id"]
    request = make_request(repository, make_watcher(repository))

    updated = dynamics.update_subscription(sid, UpSubscriptionUpdateRequest(enabled=False), request)
    assert updated.enabled is False

    dynamics.delete_subscription(sid, request)
    try:
        dynamics.delete_subscription(sid, request)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:  # pragma: no cover
        raise AssertionError("expected HTTPException")


def test_feed_and_unread_and_mark_read():
    repository = create_repository()
    subscription = repository.create_up_subscription("1001", "A")
    sid = subscription["subscription_id"]
    for index in range(3):
        repository.insert_up_detected_video(sid, f"BV1{index}", title=f"视频{index}", pubdate=index)
    request = make_request(repository, make_watcher(repository))

    feed = dynamics.get_feed(request, page=1, page_size=2)
    assert feed.total == 3
    assert len(feed.items) == 2
    assert feed.unread_count == 3
    assert all(item.unread for item in feed.items)

    unread = dynamics.get_unread_count(request)
    assert unread.unread_count == 3

    after = dynamics.mark_read(UpDynamicsMarkReadRequest(mark_all=True), request)
    assert after.unread_count == 0

    feed = dynamics.get_feed(request, unread_only=True)
    assert feed.total == 0


def test_refresh_endpoint():
    repository = create_repository()
    watcher = make_watcher(repository)
    request = make_request(repository, watcher)
    response = dynamics.refresh_dynamics(request)
    assert response.accepted is True
    watcher.refresh_now.assert_called_once()


def test_summarize_detection_submits_task():
    repository = create_repository()
    subscription = repository.create_up_subscription("1001", "A")
    detection_id, _ = repository.insert_up_detected_video(
        subscription["subscription_id"], "BV1x", title="视频", pubdate=1
    )
    watcher = make_watcher(repository)

    def _fake_submit(detection):
        repository.update_up_detected_video(
            detection["detection_id"], task_id="task-new", task_status="queued"
        )
        return "task-new"

    watcher.submit_detection_task.side_effect = _fake_submit
    request = make_request(repository, watcher)
    response = dynamics.summarize_detection(detection_id, request)
    assert watcher.submit_detection_task.called is True
    assert response.task_id == "task-new"


def test_summarize_detection_rejects_inflight_task():
    repository = create_repository()
    subscription = repository.create_up_subscription("1001", "A")
    detection_id, _ = repository.insert_up_detected_video(
        subscription["subscription_id"], "BV1x", title="视频", pubdate=1
    )
    repository.update_up_detected_video(detection_id, task_id="task-1", task_status="running")
    request = make_request(repository, make_watcher(repository))
    try:
        dynamics.summarize_detection(detection_id, request)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:  # pragma: no cover
        raise AssertionError("expected HTTPException")
