from __future__ import annotations

import sqlite3
from pathlib import Path

from video_sum_service import video_assets
from video_sum_service.context import COVER_CACHE_DIR
from video_sum_service.repository import SqliteTaskRepository
from video_sum_service.schemas import VideoAssetRecord


def create_repository() -> tuple[SqliteTaskRepository, sqlite3.Connection]:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    repository = SqliteTaskRepository(connection)
    repository.initialize()
    return repository, connection


def bilibili_video(cover_url: str, canonical_id: str = "BV-covertest") -> VideoAssetRecord:
    return VideoAssetRecord(
        canonical_id=canonical_id,
        platform="bilibili",
        title="封面测试",
        source_url=f"https://www.bilibili.com/video/{canonical_id}/",
        cover_url=cover_url,
        is_global_visible=False,
    )


def test_missing_cached_cover_reprobes_and_relocalizes(monkeypatch, tmp_path: Path) -> None:
    repository, _connection = create_repository()
    video = repository.upsert_video_asset(bilibili_video("/media/covers/BV-covertest.jpg"))
    target = COVER_CACHE_DIR / "BV-covertest.jpg"
    target.unlink(missing_ok=True)

    probe_calls: list[str] = []

    def fake_probe(url: str, force_refresh: bool = False):
        probe_calls.append(url)
        refreshed = bilibili_video("https://i1.hdslb.com/bfs/archive/fake.jpg")
        return refreshed, [], False

    def fake_cache(source_url: str, canonical_id: str, referer_url: str | None = None) -> str:
        assert source_url == "https://i1.hdslb.com/bfs/archive/fake.jpg"
        return f"/media/covers/{canonical_id}.jpg"

    monkeypatch.setattr(video_assets, "probe_video_asset", fake_probe)
    monkeypatch.setattr(video_assets, "cache_cover_image", fake_cache)

    updated = video_assets.localize_video_cover(repository, video)

    assert probe_calls == ["https://www.bilibili.com/video/BV-covertest/"]
    assert updated.cover_url == "/media/covers/BV-covertest.jpg"
    stored = repository.get_video_asset(video.video_id)
    assert stored is not None
    assert stored.cover_url == "/media/covers/BV-covertest.jpg"


def test_existing_cached_cover_skips_probe(monkeypatch) -> None:
    repository, _connection = create_repository()
    target = COVER_CACHE_DIR / "BV-covertest.jpg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"fake-jpg")
    try:
        video = repository.upsert_video_asset(bilibili_video("/media/covers/BV-covertest.jpg"))

        def fake_probe(url: str, force_refresh: bool = False):
            raise AssertionError("probe must not run when cached cover file exists")

        monkeypatch.setattr(video_assets, "probe_video_asset", fake_probe)

        updated = video_assets.localize_video_cover(repository, video)
        assert updated.cover_url == "/media/covers/BV-covertest.jpg"
    finally:
        target.unlink(missing_ok=True)
