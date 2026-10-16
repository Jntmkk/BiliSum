import sqlite3

from video_sum_service.repository import SqliteTaskRepository


def create_repository() -> SqliteTaskRepository:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    repository = SqliteTaskRepository(connection)
    repository.initialize()
    return repository


def test_create_subscription_is_idempotent_by_mid():
    repository = create_repository()
    first = repository.create_up_subscription("1001", "UP 甲", "https://face/1")
    second = repository.create_up_subscription("1001", "UP 甲重复")
    assert first["subscription_id"]
    assert second["subscription_id"] == first["subscription_id"]
    assert second["up_name"] == "UP 甲"  # 已存在则不覆盖名称


def test_list_subscriptions_enabled_filter():
    repository = create_repository()
    active = repository.create_up_subscription("1001", "A")
    repository.create_up_subscription("1002", "B")
    repository.update_up_subscription(active["subscription_id"], enabled=0)
    enabled = repository.list_up_subscriptions(enabled_only=True)
    assert [row["mid"] for row in enabled] == ["1002"]
    assert len(repository.list_up_subscriptions()) == 2


def test_insert_detection_is_idempotent():
    repository = create_repository()
    subscription = repository.create_up_subscription("1001", "A")
    detection_id, inserted = repository.insert_up_detected_video(
        subscription["subscription_id"], "BV1abc", title="视频", pubdate=100
    )
    assert inserted is True
    again_id, again = repository.insert_up_detected_video(
        subscription["subscription_id"], "BV1abc", title="视频", pubdate=100
    )
    assert again is False
    assert again_id == detection_id


def test_feed_pagination_and_unread_counts():
    repository = create_repository()
    subscription = repository.create_up_subscription("1001", "A")
    sid = subscription["subscription_id"]
    for index in range(5):
        repository.insert_up_detected_video(
            sid, f"BV1{index}", title=f"视频{index}", pubdate=index * 10
        )
    assert repository.count_unread_up_dynamics() == 5
    assert repository.count_unread_up_dynamics_by_subscription(sid) == 5

    rows, total = repository.list_up_detected_videos(limit=2, offset=0)
    assert total == 5
    assert [row["bvid"] for row in rows] == ["BV14", "BV13"]

    rows, total = repository.list_up_detected_videos(unread_only=True, limit=10, offset=0)
    assert total == 5

    repository.mark_up_dynamics_read(detection_ids=[rows[0]["detection_id"]])
    assert repository.count_unread_up_dynamics() == 4

    repository.mark_up_dynamics_read(subscription_id=sid)
    assert repository.count_unread_up_dynamics() == 0
    rows, total = repository.list_up_detected_videos(unread_only=True)
    assert total == 0


def test_mark_all_read():
    repository = create_repository()
    subscription = repository.create_up_subscription("1001", "A")
    repository.insert_up_detected_video(subscription["subscription_id"], "BV1a", pubdate=1)
    repository.insert_up_detected_video(subscription["subscription_id"], "BV1b", pubdate=2)
    assert repository.mark_up_dynamics_read() == 2
    assert repository.count_unread_up_dynamics() == 0


def test_pending_and_missing_detection_queries():
    repository = create_repository()
    subscription = repository.create_up_subscription("1001", "A")
    sid = subscription["subscription_id"]
    detection_id, _ = repository.insert_up_detected_video(sid, "BV1a", pubdate=1)

    # 未关联资产：missing_asset 命中
    assert len(repository.list_up_detections_missing_asset()) == 1
    repository.update_up_detected_video(detection_id, video_id="asset-1")
    assert repository.list_up_detections_missing_asset() == []

    # 已关联资产但未提交任务：missing_task 命中
    assert len(repository.list_up_detections_missing_task()) == 1
    repository.update_up_detected_video(detection_id, task_id="task-1", task_status="queued")
    assert repository.list_up_detections_missing_task() == []

    # 任务未达终态：pending 命中
    assert len(repository.list_up_detections_pending_task_status()) == 1
    repository.update_up_detected_video(detection_id, task_status="completed")
    assert repository.list_up_detections_pending_task_status() == []


def test_delete_subscription_cascades_detections():
    repository = create_repository()
    subscription = repository.create_up_subscription("1001", "A")
    sid = subscription["subscription_id"]
    repository.insert_up_detected_video(sid, "BV1a", pubdate=1)
    repository.delete_up_subscription(sid)
    assert repository.list_up_subscriptions() == []
    rows, total = repository.list_up_detected_videos()
    assert total == 0
    assert rows == []
