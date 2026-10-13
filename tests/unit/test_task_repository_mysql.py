"""MySQL integration tests for the repository.

Skipped unless VIDEO_SUM_TEST_MYSQL_URL points at a reachable MySQL server,
e.g. mysql://root:secret@127.0.0.1:3306. The test database is created and
dropped automatically.
"""

import os
import uuid
from urllib.parse import urlparse

import pytest
from video_sum_core.models.tasks import InputType, TaskInput, TaskResult, TaskStatus
from video_sum_infra.db import open_database
from video_sum_service.repository import TaskRepository
from video_sum_service.schemas import VideoAssetRecord

MYSQL_URL = os.environ.get("VIDEO_SUM_TEST_MYSQL_URL", "")

pytestmark = pytest.mark.skipif(not MYSQL_URL, reason="VIDEO_SUM_TEST_MYSQL_URL is not set")


def _server_url() -> str:
    parsed = urlparse(MYSQL_URL)
    auth = ""
    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth += f":{parsed.password}"
        auth += "@"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{auth}{parsed.hostname or '127.0.0.1'}{port}"


def _fresh_url(name: str) -> str:
    return f"{_server_url()}/{name}"


@pytest.fixture()
def repository():
    name = f"video_sum_test_{uuid.uuid4().hex[:8]}"
    admin = open_database(_server_url())
    try:
        admin.execute(f"CREATE DATABASE {name} CHARACTER SET utf8mb4")
    finally:
        admin.close()
    session = open_database(_fresh_url(name))
    repository = TaskRepository(session)
    repository.initialize()
    yield repository
    session.close()
    admin = open_database(_server_url())
    try:
        admin.execute(f"DROP DATABASE IF EXISTS {name}")
    finally:
        admin.close()


def _make_result() -> TaskResult:
    return TaskResult(knowledge_note_markdown="# 摘要\n\n内容")


def test_database_is_auto_created() -> None:
    """open_database must create a missing database (utf8mb4) before connecting."""
    name = f"video_sum_autocreate_{uuid.uuid4().hex[:8]}"
    session = open_database(_fresh_url(name))
    try:
        rows = session.execute(
            """
            SELECT DEFAULT_CHARACTER_SET_NAME AS charset
            FROM information_schema.SCHEMATA
            WHERE SCHEMA_NAME = ?
            """,
            (name,),
        )
        assert rows and rows[0]["charset"] == "utf8mb4"
    finally:
        session.close()
    admin = open_database(_server_url())
    try:
        admin.execute(f"DROP DATABASE IF EXISTS {name}")
    finally:
        admin.close()


def test_task_crud(repository: TaskRepository) -> None:
    record = repository.create_task(
        TaskInput(input_type=InputType.URL, source="https://example.com/video")
    )
    fetched = repository.get_task(record.task_id)
    assert fetched is not None
    assert fetched.task_id == record.task_id
    assert fetched.status == TaskStatus.QUEUED

    updated = repository.update_status(record.task_id, TaskStatus.RUNNING)
    assert updated is not None and updated.status == TaskStatus.RUNNING

    saved = repository.save_result(record.task_id, _make_result())
    assert saved is not None and saved.result is not None
    assert saved.result.knowledge_note_markdown == "# 摘要\n\n内容"

    repository.append_event(record.task_id, stage="summarize", progress=50, message=" halfway")
    events = repository.list_events(record.task_id)
    assert len(events) == 1
    assert events[0].message == " halfway"

    assert repository.delete_task(record.task_id) is True
    assert repository.get_task(record.task_id) is None


def test_video_asset_upsert_and_family_consolidation(repository: TaskRepository) -> None:
    asset = VideoAssetRecord(
        video_id="v1",
        canonical_id="BV1xx411c7mD",
        platform="bilibili",
        title="标题",
        source_url="https://www.bilibili.com/video/BV1xx411c7mD",
    )
    saved = repository.upsert_video_asset(asset)
    assert saved.video_id == "v1"

    page_variant = asset.model_copy(update={"video_id": "v2", "canonical_id": "BV1xx411c7mD?p=2"})
    consolidated = repository.upsert_video_asset(page_variant)
    assert consolidated.video_id == "v1"

    by_canonical = repository.get_video_asset_by_canonical_id("BV1xx411c7mD")
    assert by_canonical is not None and by_canonical.video_id == "v1"

    listed = repository.list_video_assets()
    assert [video.video_id for video in listed] == ["v1"]


def test_tags_folders_and_favorites(repository: TaskRepository) -> None:
    asset = repository.upsert_video_asset(
        VideoAssetRecord(
            video_id="v1",
            canonical_id="BV1xx411c7mD",
            platform="bilibili",
            title="标题",
            source_url="https://example.com",
        )
    )
    assert repository.add_video_tag(asset.video_id, "AI", source="manual") is True
    assert repository.add_video_tag(asset.video_id, "教程", source="auto", confidence=0.7) is True
    tags = repository.list_video_tags(asset.video_id)
    assert {tag.tag for tag in tags} == {"AI", "教程"}

    folder = repository.create_video_folder("收藏夹")
    assert folder is not None
    moved = repository.set_video_folders(asset.video_id, [folder.folder_id])
    assert moved is not None and folder.folder_id in (moved.folder_ids or [])

    favorited = repository.set_video_favorite(asset.video_id, True)
    assert favorited is not None and favorited.is_favorite is True


def test_knowledge_conversation_flow(repository: TaskRepository) -> None:
    conversation = repository.create_knowledge_conversation("测试会话")
    conversation_id = str(conversation["conversation_id"])

    message = repository.create_knowledge_message(conversation_id, "user", "问题")
    assert message is not None
    assistant = repository.create_knowledge_message(conversation_id, "assistant", "回答")
    assert assistant is not None

    messages = repository.list_knowledge_messages(conversation_id)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["sequence"] == 2

    updated = repository.update_knowledge_message(
        str(assistant["message_id"]), content="更好的回答"
    )
    assert updated is not None and updated["content"] == "更好的回答"

    job = repository.create_knowledge_job(
        conversation_id, str(assistant["message_id"]), "qa", "running", "问题"
    )
    assert job is not None
    listed_jobs = repository.list_knowledge_jobs(statuses=["running"])
    assert any(j["job_id"] == job["job_id"] for j in listed_jobs)

    assert repository.delete_knowledge_conversation(conversation_id) is True
    assert repository.get_knowledge_conversation(conversation_id) is None


def test_video_collection_flow(repository: TaskRepository) -> None:
    collection = repository.upsert_video_collection(
        {
            "collection_id": "col1",
            "title": "合集",
            "items": [
                {
                    "bvid": "BV1xx411c7mD",
                    "position": 1,
                    "title": "视频一",
                    "source_url": "https://example.com/1",
                }
            ],
        },
        "https://www.bilibili.com/list/1",
    )
    assert collection.collection_id == "col1"
    assert collection.item_count == 1

    refreshed = repository.refresh_video_collection(
        {
            "collection_id": "col1",
            "title": "合集",
            "items": [
                {
                    "bvid": "BV1xx411c7mD",
                    "position": 1,
                    "title": "视频一改名",
                    "source_url": "https://example.com/1",
                },
                {
                    "bvid": "BV1yy411c7mD",
                    "position": 2,
                    "title": "视频二",
                    "source_url": "https://example.com/2",
                },
            ],
        },
        "https://www.bilibili.com/list/1",
    )
    assert refreshed.item_count == 1
    assert len(refreshed.new_items) == 1

    added = repository.add_pending_video_collection_items("col1")
    assert len(added) == 1
    final = repository.get_video_collection("col1")
    assert final is not None and final.item_count == 2

    reordered = repository.reorder_video_collection_items(
        "col1", ["BV1yy411c7mD", "BV1xx411c7mD"]
    )
    assert reordered is not None
    # items stay in source order; custom order persists via custom_position
    assert [item.bvid for item in reordered.items] == ["BV1xx411c7mD", "BV1yy411c7mD"]
    assert {item.bvid: item.custom_position for item in reordered.items} == {
        "BV1xx411c7mD": 2,
        "BV1yy411c7mD": 1,
    }


def test_startup_backfill_runs(repository: TaskRepository) -> None:
    """initialize() re-run must stay idempotent (exercises the julianday backfill rewrite)."""
    repository.initialize()
    repository.initialize()
    assert repository.get_knowledge_chunk_count() == 0


def test_up_dynamics_flow(repository: TaskRepository) -> None:
    """UP subscription + detection rows round-trip on MySQL (merged up_* feature)."""
    subscription = repository.create_up_subscription("12345", up_name="测试UP")
    assert subscription["mid"] == "12345"

    fetched = repository.get_up_subscription(str(subscription["subscription_id"]))
    assert fetched is not None and fetched["up_name"] == "测试UP"

    listed = repository.list_up_subscriptions()
    assert len(listed) == 1

    detection_id, created = repository.insert_up_detected_video(
        str(subscription["subscription_id"]),
        "BV1xx411c7mD",
        title="新视频",
    )
    assert created is True

    unread, unread_total = repository.list_up_detected_videos(unread_only=True)
    assert unread_total == 1
    assert unread[0]["title"] == "新视频"

    marked = repository.mark_up_dynamics_read(detection_ids=[detection_id])
    assert marked == 1
    _, unread_total_after = repository.list_up_detected_videos(unread_only=True)
    assert unread_total_after == 0
