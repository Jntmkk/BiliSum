"""MySQL integration tests for the shared Bilibili cookie store.

Skipped unless VIDEO_SUM_TEST_MYSQL_URL points at a reachable MySQL server.
A dedicated database is created and dropped per test module run: this covers
the MySQL dialect translation (DDL + ``ON CONFLICT`` upsert) that the SQLite
tests cannot.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest

from video_sum_infra.config import ServiceSettings
from video_sum_infra.db import open_database
from video_sum_service.bilibili_cookie_store import (
    DbBilibiliCookieStore,
    create_bilibili_cookie_store,
)

MYSQL_URL = os.environ.get("VIDEO_SUM_TEST_MYSQL_URL", "")

pytestmark = pytest.mark.skipif(not MYSQL_URL, reason="VIDEO_SUM_TEST_MYSQL_URL is not set")

COOKIE_TEXT = (
    "# Netscape HTTP Cookie File\n"
    ".bilibili.com\tTRUE\t/\tTRUE\t2000000000\tSESSDATA\tsession-value\n"
    "\n"
)


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


DB_NAME = f"video_sum_cookies_test_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def database_url():
    admin = open_database(_server_url())
    try:
        admin.execute(f"CREATE DATABASE {DB_NAME} CHARACTER SET utf8mb4")
    finally:
        admin.close()
    yield f"{_server_url()}/{DB_NAME}"
    admin = open_database(_server_url())
    try:
        admin.execute(f"DROP DATABASE IF EXISTS {DB_NAME}")
    finally:
        admin.close()


def _store(database_url: str, path: Path) -> DbBilibiliCookieStore:
    store = create_bilibili_cookie_store(
        ServiceSettings(
            _env_file=None,
            data_dir=path.parent,
            database_url=database_url,
        )
    )
    assert isinstance(store, DbBilibiliCookieStore)
    return store


def test_cookie_is_shared_between_instances(database_url, tmp_path) -> None:
    store_a = _store(database_url, tmp_path / "a" / "cookies" / "bilibili.txt")
    store_b = _store(database_url, tmp_path / "b" / "cookies" / "bilibili.txt")
    try:
        store_a.write(COOKIE_TEXT)

        assert store_b.read() == COOKIE_TEXT
        # 第二台实例读取时把共享登录态物化到自己卷里的文件
        store_b.ensure_file(tmp_path / "b" / "cookies" / "bilibili.txt")
        assert (tmp_path / "b" / "cookies" / "bilibili.txt").read_text(encoding="utf-8") == COOKIE_TEXT
    finally:
        store_a.close()
        store_b.close()


def test_repeat_login_overwrites_single_row(database_url, tmp_path) -> None:
    path = tmp_path / "cookies" / "bilibili.txt"
    store = _store(database_url, path)
    try:
        store.write(COOKIE_TEXT)
        refreshed = COOKIE_TEXT.replace("session-value", "refreshed-value")
        store.write(refreshed)

        reopened = _store(database_url, tmp_path / "other" / "bilibili.txt")
        try:
            assert reopened.read() == refreshed
        finally:
            reopened.close()
    finally:
        store.close()
