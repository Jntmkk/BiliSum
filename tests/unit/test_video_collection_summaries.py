from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

import video_sum_service.app as service_app
from video_sum_service.app import app
from video_sum_service.auth import ACCESS_TOKEN_ENV, AccessTokenManager
from video_sum_service.repository import SqliteTaskRepository
from video_sum_service.schemas import VideoAssetRecord


def create_repository() -> tuple[SqliteTaskRepository, sqlite3.Connection]:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    repository = SqliteTaskRepository(connection)
    repository.initialize()
    return repository, connection


def add_collection_video(
    repository: SqliteTaskRepository,
    bvid: str,
    title: str,
) -> VideoAssetRecord:
    return repository.upsert_video_asset(
        VideoAssetRecord(
            canonical_id=bvid,
            platform="bilibili",
            title=title,
            source_url=f"https://www.bilibili.com/video/{bvid}/",
            is_global_visible=False,
        )
    )


def collection_item(position: int, bvid: str, title: str | None = None) -> dict[str, object]:
    return {
        "position": position,
        "bvid": bvid,
        "title": title or bvid,
        "source_url": f"https://www.bilibili.com/video/{bvid}/",
        "source_section_id": "section-1",
        "source_section_title": "第一章",
        "source_section_position": 1,
    }


def seed_collection(repository: SqliteTaskRepository) -> None:
    add_collection_video(repository, "BV-first", "第一集")
    add_collection_video(repository, "BV-second", "第二集")
    repository.upsert_video_collection(
        {
            "collection_id": "season-summary",
            "title": "摘要合集",
            "items": [
                collection_item(1, "BV-first"),
                collection_item(2, "BV-second"),
            ],
        },
        "https://example.com/season-summary",
    )


def test_collection_summaries_match_full_detail_counts() -> None:
    repository, _connection = create_repository()
    seed_collection(repository)

    full = repository.get_video_collection("season-summary")
    assert full is not None
    assert full.item_count == 2

    summaries = {
        summary.collection_id: summary
        for summary in repository.list_video_collection_summaries()
    }
    summary = summaries["season-summary"]

    assert summary.item_count == full.item_count == 2
    assert summary.summarized_count == 0
    assert summary.unsummarized_count == 2
    assert summary.view_sort_mode == full.view_sort_mode
    assert summary.view_group_mode == full.view_group_mode
    assert not hasattr(summary, "items")
    assert not hasattr(summary, "new_items")

    single = repository.get_video_collection_summary("season-summary")
    assert single is not None
    assert single.item_count == 2
    assert single.title == "摘要合集"
    assert repository.get_video_collection_summary("missing") is None


def test_collection_summary_tracks_soft_removed_items() -> None:
    repository, _connection = create_repository()
    seed_collection(repository)

    repository.refresh_video_collection(
        {
            "collection_id": "season-summary",
            "title": "摘要合集",
            "items": [collection_item(1, "BV-first")],
        },
        "https://example.com/season-summary",
    )

    summary = repository.get_video_collection_summary("season-summary")
    assert summary is not None
    assert summary.item_count == 1
    full = repository.get_video_collection("season-summary")
    assert full is not None
    assert [item.bvid for item in full.items] == ["BV-first"]


def test_collection_summary_includes_folder_memberships() -> None:
    repository, _connection = create_repository()
    seed_collection(repository)
    folder = repository.create_video_folder("合集目录")
    assert folder is not None
    repository.set_video_collection_folders("season-summary", [folder.folder_id])

    summary = repository.get_video_collection_summary("season-summary")
    assert summary is not None
    assert summary.folder_ids == [folder.folder_id]
    assert summary.folder_id == folder.folder_id


def test_library_http_returns_collection_summaries_without_items() -> None:
    repository, _connection = create_repository()
    seed_collection(repository)
    app.state.task_repository = repository
    original_access_token_manager = service_app.access_token_manager
    service_app.access_token_manager = AccessTokenManager(
        Path("unused"),
        env={ACCESS_TOKEN_ENV: "library-test-token"},
    )
    try:
        with TestClient(app) as client:
            app.state.task_repository = repository
            library_response = client.get(
                "/api/v1/videos/library",
                headers={"Authorization": "Bearer library-test-token"},
            )
            detail_response = client.get(
                "/api/v1/videos/collections/season-summary",
                headers={"Authorization": "Bearer library-test-token"},
            )
    finally:
        service_app.access_token_manager = original_access_token_manager

    assert library_response.status_code == 200
    collections = {
        collection["collection_id"]: collection
        for collection in library_response.json()["collections"]
    }
    collection = collections["season-summary"]
    assert collection["item_count"] == 2
    assert collection["unsummarized_count"] == 2
    assert "items" not in collection
    assert "new_items" not in collection

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert len(detail["items"]) == 2
