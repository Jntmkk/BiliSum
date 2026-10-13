import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

from video_sum_service import bilibili_wbi
from video_sum_service.repository import SqliteTaskRepository
from video_sum_service.up_dynamics import MAX_CONSECUTIVE_FAILURES, UpDynamicsWatcher


def create_repository() -> SqliteTaskRepository:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    repository = SqliteTaskRepository(connection)
    repository.initialize()
    return repository


def make_watcher(repository: SqliteTaskRepository, **overrides) -> UpDynamicsWatcher:
    settings = SimpleNamespace(
        up_dynamics_enabled=True,
        up_dynamics_poll_interval_seconds=600,
    )
    settings_manager = SimpleNamespace(current=settings)
    watcher = UpDynamicsWatcher(
        repository,
        SimpleNamespace(),
        settings_manager=settings_manager,
        sleep_fn=lambda _seconds: None,
    )
    for key, value in overrides.items():
        setattr(watcher, key, value)
    return watcher


def make_item(bvid: str, pubdate: int, title: str = "视频") -> bilibili_wbi.UpVideoItem:
    return bilibili_wbi.UpVideoItem(
        bvid=bvid,
        aid=1,
        title=title,
        cover_url="https://pic/x.jpg",
        duration=100,
        pubdate=pubdate,
        description="",
    )


def _no_sleep_round(watcher: UpDynamicsWatcher):
    with patch("video_sum_service.up_dynamics.random.uniform", return_value=0.0):
        watcher._round()


def test_first_poll_establishes_cursor_without_backfill():
    repository = create_repository()
    subscription = repository.create_up_subscription("1001", "UP 甲")
    watcher = make_watcher(repository)

    items = [make_item("BV1new", 300), make_item("BV1old", 100)]
    with patch.object(bilibili_wbi, "load_bilibili_cookie_header", return_value="cookie"):
        with patch.object(bilibili_wbi, "fetch_up_videos", return_value=items) as fetch:
            _no_sleep_round(watcher)

    fetch.assert_called_once_with("1001", "cookie")
    # 首轮不回灌：无检出记录、无资产、无任务
    assert repository.list_up_detected_videos()[1] == 0
    assert repository.get_video_asset_by_canonical_id("BV1new") is None
    updated = repository.get_up_subscription(subscription["subscription_id"])
    assert updated["last_video_pubdate"] == 300
    assert updated["last_video_bvid"] == "BV1new"


def test_new_video_auto_ingested_and_task_submitted():
    repository = create_repository()
    subscription = repository.create_up_subscription("1001", "UP 甲")
    sid = subscription["subscription_id"]
    repository.update_up_subscription(sid, last_video_bvid="BV1old", last_video_pubdate=100)

    watcher = make_watcher(repository)
    items = [make_item("BV1new", 300, title="新视频"), make_item("BV1old", 100)]

    with patch.object(bilibili_wbi, "load_bilibili_cookie_header", return_value="cookie"):
        with patch.object(bilibili_wbi, "fetch_up_videos", return_value=items):
            with patch("video_sum_service.up_dynamics.submit_task_or_queue") as submit:
                _no_sleep_round(watcher)

    asset = repository.get_video_asset_by_canonical_id("BV1new")
    assert asset is not None
    assert asset.title == "新视频"
    assert asset.is_global_visible is True

    detections, total = repository.list_up_detected_videos()
    assert total == 1
    detection = detections[0]
    assert detection["video_id"] == asset.video_id
    assert detection["task_id"]
    assert detection["task_status"] == "queued"
    assert detection["detection_status"] == "task_submitted"

    submit.assert_called_once()
    record = submit.call_args.args[2]
    assert record.video_id == asset.video_id
    assert "BV1new" in record.task_input.source


def test_repeat_poll_does_not_duplicate_tasks():
    repository = create_repository()
    subscription = repository.create_up_subscription("1001", "UP 甲")
    sid = subscription["subscription_id"]
    # 预置游标，跳过首轮「建立游标不回灌」逻辑
    repository.update_up_subscription(sid, last_video_bvid="BV1old", last_video_pubdate=100)

    watcher = make_watcher(repository)
    first_items = [make_item("BV1new", 300)]

    with patch.object(bilibili_wbi, "load_bilibili_cookie_header", return_value="cookie"):
        with patch.object(bilibili_wbi, "fetch_up_videos", return_value=first_items):
            with patch("video_sum_service.up_dynamics.submit_task_or_queue") as submit:
                _no_sleep_round(watcher)
    assert submit.call_count == 1
    cursor = repository.get_up_subscription(sid)["last_video_pubdate"]
    assert cursor == 300

    # 第二轮拉到的仍是同一页（游标已前移，视为无新稿）
    second_items = [make_item("BV1new", 300), make_item("BV1older", 200)]
    with patch.object(bilibili_wbi, "load_bilibili_cookie_header", return_value="cookie"):
        with patch.object(bilibili_wbi, "fetch_up_videos", return_value=second_items):
            with patch("video_sum_service.up_dynamics.submit_task_or_queue") as submit2:
                _no_sleep_round(watcher)
    submit2.assert_not_called()
    assert repository.list_up_detected_videos()[1] == 1


def test_missing_task_compensation_resubmits():
    repository = create_repository()
    subscription = repository.create_up_subscription("1001", "UP 甲")
    sid = subscription["subscription_id"]
    # 模拟「检出后、提交任务前」崩溃：detection 存在、video_id 为空
    detection_id, _ = repository.insert_up_detected_video(sid, "BV1crash", title="崩溃视频", pubdate=50)

    watcher = make_watcher(repository)
    with patch.object(bilibili_wbi, "load_bilibili_cookie_header", return_value="cookie"):
        with patch.object(bilibili_wbi, "fetch_up_videos", return_value=[make_item("BV1crash", 50, "崩溃视频")]):
            with patch("video_sum_service.up_dynamics.submit_task_or_queue"):
                watcher._round()

    detection = repository.get_up_detected_video(detection_id)
    assert detection["task_id"]  # 补偿提交成功
    assert detection["video_id"]
    assert repository.get_video_asset_by_canonical_id("BV1crash") is not None


def test_cookie_missing_skips_round():
    repository = create_repository()
    repository.create_up_subscription("1001", "UP 甲")
    watcher = make_watcher(repository)
    with patch.object(bilibili_wbi, "load_bilibili_cookie_header", return_value=None):
        with patch.object(bilibili_wbi, "fetch_up_videos") as fetch:
            watcher._round()
    fetch.assert_not_called()
    assert watcher.status()["cookieReady"] is False


def test_cookie_invalid_stops_round():
    repository = create_repository()
    repository.create_up_subscription("1001", "A")
    repository.create_up_subscription("1002", "B")
    watcher = make_watcher(repository)

    def fake_fetch(mid, cookie):
        raise bilibili_wbi.CookieInvalidError("登录态失效")

    with patch.object(bilibili_wbi, "load_bilibili_cookie_header", return_value="cookie"):
        with patch.object(bilibili_wbi, "fetch_up_videos", side_effect=fake_fetch):
            _no_sleep_round(watcher)
    assert watcher.status()["cookieReady"] is False  # 登录态失效后标记 cookie 缺失


def test_rate_limited_aborts_remaining_ups():
    repository = create_repository()
    repository.create_up_subscription("1001", "A")
    repository.create_up_subscription("1002", "B")
    watcher = make_watcher(repository)

    calls = []

    def fake_fetch(mid, cookie):
        calls.append(mid)
        raise bilibili_wbi.RateLimitedError("请求过快")

    with patch.object(bilibili_wbi, "load_bilibili_cookie_header", return_value="cookie"):
        with patch.object(bilibili_wbi, "fetch_up_videos", side_effect=fake_fetch):
            _no_sleep_round(watcher)
    assert calls == ["1001"]  # 第一个 UP 限流后本轮剩余 UP 不再请求


def test_consecutive_failures_disable_subscription():
    repository = create_repository()
    subscription = repository.create_up_subscription("1001", "A")
    sid = subscription["subscription_id"]
    watcher = make_watcher(repository)

    for _ in range(MAX_CONSECUTIVE_FAILURES):
        with patch.object(bilibili_wbi, "load_bilibili_cookie_header", return_value="cookie"):
            with patch.object(
                bilibili_wbi,
                "fetch_up_videos",
                side_effect=bilibili_wbi.UpstreamError("上游错误"),
            ):
                _no_sleep_round(watcher)

    updated = repository.get_up_subscription(sid)
    assert updated["consecutive_failures"] == MAX_CONSECUTIVE_FAILURES
    assert updated["enabled"] == 0
    assert "自动停用" in updated["last_error"]


def test_up_not_found_records_error_but_stays_enabled():
    repository = create_repository()
    subscription = repository.create_up_subscription("1001", "A")
    sid = subscription["subscription_id"]
    watcher = make_watcher(repository)

    with patch.object(bilibili_wbi, "load_bilibili_cookie_header", return_value="cookie"):
        with patch.object(
            bilibili_wbi,
            "fetch_up_videos",
            side_effect=bilibili_wbi.UpNotFoundError("UP 主不存在"),
        ):
            _no_sleep_round(watcher)

    updated = repository.get_up_subscription(sid)
    assert updated["enabled"] == 1
    assert "不存在" in (updated["last_error"] or "")
