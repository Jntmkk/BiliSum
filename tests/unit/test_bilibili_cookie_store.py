from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from http.cookiejar import Cookie
from pathlib import Path
from types import SimpleNamespace

import pytest

import video_sum_service.bilibili_cookie_store as cookie_store_module
import video_sum_service.bilibili_cookies as bilibili_cookies
import video_sum_service.bilibili_wbi as bilibili_wbi
from video_sum_infra.config import ServiceSettings
from video_sum_infra.db import SQLiteSession
from video_sum_service.bilibili_cookie_store import (
    DbBilibiliCookieStore,
    FileBilibiliCookieStore,
    create_bilibili_cookie_store,
    get_bilibili_cookie_store,
    materialize_bilibili_cookie_file,
    reset_bilibili_cookie_store_for_tests,
    resolved_cookie_file,
)

COOKIE_TEXT = (
    "# Netscape HTTP Cookie File\n"
    ".bilibili.com\tTRUE\t/\tTRUE\t2000000000\tSESSDATA\tsession-value\n"
    ".bilibili.com\tTRUE\t/\tTRUE\t2000000000\tbili_jct\tcsrf-value\n"
    "\n"
)
COOKIE_TEXT_WITHOUT_LOGIN = (
    "# Netscape HTTP Cookie File\n"
    ".bilibili.com\tTRUE\t/\tTRUE\t2000000000\tbuvid3\tsome-device-id\n"
    "\n"
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_bilibili_cookie_store_for_tests()
    yield
    reset_bilibili_cookie_store_for_tests()


def make_cookie(name: str, value: str, domain: str = ".bilibili.com") -> Cookie:
    return Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=True,
        domain_initial_dot=domain.startswith("."),
        path="/",
        path_specified=True,
        secure=True,
        expires=2000000000,
        discard=False,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    )


def make_db_store(
    path: Path,
    *,
    cookie_text: str | None = None,
    updated_at: str | None = None,
) -> tuple[DbBilibiliCookieStore, SQLiteSession]:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    session = SQLiteSession(connection)
    store = DbBilibiliCookieStore(lambda: session, path)
    if cookie_text is not None:
        store.write(cookie_text)
        if updated_at is not None:
            with session.cursor() as cursor:
                cursor.execute(
                    "UPDATE bilibili_cookies SET updated_at = ? WHERE id = 1", (updated_at,)
                )
            # 绕过 10s 行缓存，让后续读取回到库里取更新后的时间戳。
            store._cached_at = 0.0
    return store, session


def row_count(session: SQLiteSession) -> int:
    return len(session.execute("SELECT id FROM bilibili_cookies WHERE id = 1"))


def test_file_store_roundtrip(tmp_path: Path) -> None:
    store = FileBilibiliCookieStore(tmp_path / "cookies" / "bilibili.txt")
    assert store.read() is None

    store.write(COOKIE_TEXT)

    assert (tmp_path / "cookies" / "bilibili.txt").read_text(encoding="utf-8") == COOKIE_TEXT
    assert store.read() == COOKIE_TEXT


def test_create_store_picks_backend_by_dialect(tmp_path: Path) -> None:
    sqlite_base = ServiceSettings(
        _env_file=None,
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path}/video_sum.db",
    )
    assert isinstance(create_bilibili_cookie_store(sqlite_base), FileBilibiliCookieStore)

    mysql_base = ServiceSettings(
        _env_file=None,
        data_dir=tmp_path / "data",
        database_url="mysql://u:p@h:3306/db",
    )
    assert isinstance(create_bilibili_cookie_store(mysql_base), DbBilibiliCookieStore)


def test_db_store_write_is_visible_to_other_instance(tmp_path: Path) -> None:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    session = SQLiteSession(connection)
    path_a = tmp_path / "a" / "cookies" / "bilibili.txt"
    path_b = tmp_path / "b" / "cookies" / "bilibili.txt"
    store_a = DbBilibiliCookieStore(lambda: session, path_a)
    store_b = DbBilibiliCookieStore(lambda: session, path_b)

    store_a.write(COOKIE_TEXT)

    assert store_b.read() == COOKIE_TEXT
    # 另一台实例读取时会把共享登录态物化到自己的卷里
    store_b.ensure_file(path_b)
    assert path_b.read_text(encoding="utf-8") == COOKIE_TEXT


def test_db_store_write_mirrors_canonical_file(tmp_path: Path) -> None:
    path = tmp_path / "cookies" / "bilibili.txt"
    store, _ = make_db_store(path)

    store.write(COOKIE_TEXT)

    assert path.read_text(encoding="utf-8") == COOKIE_TEXT


def test_ensure_file_writes_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "cookies" / "bilibili.txt"
    store, _ = make_db_store(path, cookie_text=COOKIE_TEXT)
    path.unlink()

    store.ensure_file(path)

    assert path.read_text(encoding="utf-8") == COOKIE_TEXT


def test_ensure_file_overwrites_stale_file(tmp_path: Path) -> None:
    path = tmp_path / "cookies" / "bilibili.txt"
    store, _ = make_db_store(path, cookie_text=COOKIE_TEXT)
    path.write_text(COOKIE_TEXT_WITHOUT_LOGIN, encoding="utf-8")
    past = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(path, (past, past))

    store.ensure_file(path)

    assert path.read_text(encoding="utf-8") == COOKIE_TEXT


def test_ensure_file_keeps_newer_local_file(tmp_path: Path) -> None:
    """本机文件比库行更新时不能被库内容覆盖（Electron 登录窗口刚导出的场景）。"""
    path = tmp_path / "cookies" / "bilibili.txt"
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    store, _ = make_db_store(path, cookie_text=COOKIE_TEXT, updated_at=old)
    path.write_text(COOKIE_TEXT_WITHOUT_LOGIN, encoding="utf-8")

    store.ensure_file(path)

    assert path.read_text(encoding="utf-8") == COOKIE_TEXT_WITHOUT_LOGIN


def test_ensure_file_materializes_configured_path_too(tmp_path: Path) -> None:
    """yt-dlp 用的是设置里的路径，与规范路径不同时两处都要补齐。"""
    canonical = tmp_path / "data" / "cookies" / "bilibili.txt"
    configured = tmp_path / "custom" / "cookies.txt"
    store, _ = make_db_store(canonical, cookie_text=COOKIE_TEXT)

    store.ensure_file(configured)

    assert configured.read_text(encoding="utf-8") == COOKIE_TEXT
    assert canonical.read_text(encoding="utf-8") == COOKIE_TEXT


def test_read_backfills_legacy_file_into_db(tmp_path: Path) -> None:
    path = tmp_path / "cookies" / "bilibili.txt"
    path.parent.mkdir(parents=True)
    path.write_text(COOKIE_TEXT, encoding="utf-8")
    store, session = make_db_store(path)

    assert store.read() == COOKIE_TEXT

    assert row_count(session) == 1


def test_read_skips_backfill_without_sessdata(tmp_path: Path) -> None:
    path = tmp_path / "cookies" / "bilibili.txt"
    path.parent.mkdir(parents=True)
    path.write_text(COOKIE_TEXT_WITHOUT_LOGIN, encoding="utf-8")
    store, session = make_db_store(path)

    assert store.read() == COOKIE_TEXT_WITHOUT_LOGIN

    assert row_count(session) == 0


def test_resolved_cookie_file_prefers_configured_setting(monkeypatch, tmp_path: Path) -> None:
    settings = SimpleNamespace(
        data_dir=tmp_path / "data",
        ytdlp_cookies_file=str(tmp_path / "custom" / "cookies.txt"),
    )
    monkeypatch.setattr(
        cookie_store_module, "settings_manager", SimpleNamespace(current=settings)
    )
    assert resolved_cookie_file() == tmp_path / "custom" / "cookies.txt"

    settings.ytdlp_cookies_file = ""
    assert resolved_cookie_file() == tmp_path / "data" / "cookies" / "bilibili.txt"


def test_get_store_uses_database_backend_for_mysql(monkeypatch, tmp_path: Path) -> None:
    settings = SimpleNamespace(
        data_dir=tmp_path / "data",
        database_url="mysql://u:p@h:3306/db",
    )
    monkeypatch.setattr(
        cookie_store_module, "settings_manager", SimpleNamespace(current=settings)
    )

    assert isinstance(get_bilibili_cookie_store(), DbBilibiliCookieStore)


def test_login_on_one_instance_is_visible_to_another(monkeypatch, tmp_path: Path) -> None:
    """实例 A 扫码登录写入共享库，实例 B（另一台机器、另一个卷）读到新登录态。"""
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    session = SQLiteSession(connection)
    store_a = DbBilibiliCookieStore(lambda: session, tmp_path / "a" / "cookies" / "bilibili.txt")
    store_b = DbBilibiliCookieStore(lambda: session, tmp_path / "b" / "cookies" / "bilibili.txt")

    # 实例 A：扫码登录
    monkeypatch.setattr(
        cookie_store_module, "settings_manager", SimpleNamespace(current=SimpleNamespace(data_dir=tmp_path / "a"))
    )
    monkeypatch.setattr(bilibili_cookies, "get_bilibili_cookie_store", lambda: store_a)
    bilibili_cookies._write_bilibili_cookies([make_cookie("SESSDATA", "session-value")])

    # 实例 B：自己的卷里什么都没有，但读取时应拿到共享库里的登录态
    monkeypatch.setattr(
        cookie_store_module, "settings_manager", SimpleNamespace(current=SimpleNamespace(data_dir=tmp_path / "b"))
    )
    monkeypatch.setattr(cookie_store_module, "get_bilibili_cookie_store", lambda: store_b)

    header = bilibili_wbi.load_bilibili_cookie_header()

    assert header is not None
    assert "SESSDATA=session-value" in header
    assert (tmp_path / "b" / "cookies" / "bilibili.txt").exists()


def test_materialize_returns_target_path_without_database(tmp_path: Path) -> None:
    path = tmp_path / "cookies" / "bilibili.txt"
    path.parent.mkdir(parents=True)
    path.write_text(COOKIE_TEXT, encoding="utf-8")

    assert materialize_bilibili_cookie_file(path) == path
    assert path.read_text(encoding="utf-8") == COOKIE_TEXT
