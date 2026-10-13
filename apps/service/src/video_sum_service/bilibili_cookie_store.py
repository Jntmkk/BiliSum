"""B 站登录态持久化：数据库为权威，本地文件为物化镜像。

MySQL（多实例共库）模式下 cookie 存在 ``bilibili_cookies`` 单行表里，
因此任一台服务器扫码登录后另一台无需重启即可共用同一登录态。本地
Netscape 文件仍然保留，因为 yt-dlp 只接受真实文件路径。

SQLite / 桌面模式维持历史行为（只读写文件）：Electron 登录窗口会直接
写文件，若让数据库成为权威，桌面端会读到陈旧内容。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from video_sum_infra.db import DatabaseSession, database_dialect_from_url, open_database

from video_sum_service.context import settings_manager

logger = logging.getLogger("video_sum_service.app")

_COOKIE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS bilibili_cookies (
    id INTEGER PRIMARY KEY,
    cookie_text TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

# How often the cached cookie row is re-read from the database. Both
# instances poll it lazily, so a login on one server becomes visible on the
# other within this window (the dynamics watcher itself runs every 600s).
COOKIE_REFRESH_TTL_SECONDS = 10.0


def canonical_cookie_file() -> Path:
    """本实例的规范 cookie 文件路径（服务端自身调用 B 站接口用）。"""
    return Path(settings_manager.current.data_dir) / "cookies" / "bilibili.txt"


def resolved_cookie_file() -> Path:
    """yt-dlp 实际使用的 cookie 文件：优先设置项，未配置时用规范路径。"""
    configured = str(getattr(settings_manager.current, "ytdlp_cookies_file", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return canonical_cookie_file()


def _contains_sessdata(text: str) -> bool:
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) >= 7 and "bilibili.com" in fields[0] and fields[5] == "SESSDATA" and fields[6]:
            return True
    return False


def _read_text_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _write_text_file(path: Path, text: str) -> None:
    """原子写（临时文件 + rename），避免中断写出半截 cookie 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


class BilibiliCookieStore:
    """登录态存储后端接口。"""

    def read(self) -> str | None:
        raise NotImplementedError

    def write(self, text: str) -> None:
        raise NotImplementedError

    def ensure_file(self, path: Path) -> None:
        return None

    def close(self) -> None:
        pass


class FileBilibiliCookieStore(BilibiliCookieStore):
    """文件存储（历史行为，SQLite / 桌面模式）。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> str | None:
        return _read_text_file(self.path)

    def write(self, text: str) -> None:
        _write_text_file(self.path, text)


class DbBilibiliCookieStore(BilibiliCookieStore):
    """单行 ``bilibili_cookies`` 表存储（共库多实例共享登录态）。

    连接惰性建立：settings 管理器在导入期就构造好了，那时仓库会话尚未
    打开（与 ``DbSettingsStore`` 同理）。
    """

    def __init__(self, session_factory: Callable[[], DatabaseSession], path: Path) -> None:
        self._session_factory = session_factory
        self._canonical_path = path
        self._session: DatabaseSession | None = None
        self._lock = threading.RLock()
        self._cached_row: tuple[str, str] | None = None
        self._cached_at = 0.0

    @classmethod
    def from_url(cls, database_url: str, path: Path) -> "DbBilibiliCookieStore":
        return cls(lambda: open_database(database_url), path)

    def _session_locked(self) -> DatabaseSession:
        if self._session is None:
            session = self._session_factory()
            with session.cursor() as cursor:
                cursor.execute(_COOKIE_TABLE_DDL)
            self._session = session
        return self._session

    def _row(self) -> tuple[str, str] | None:
        """读取缓存行；库不可用时返回 None（调用方回退本地文件）。"""
        now = time.monotonic()
        with self._lock:
            if now - self._cached_at < COOKIE_REFRESH_TTL_SECONDS:
                return self._cached_row
            try:
                rows = self._session_locked().execute(
                    "SELECT cookie_text, updated_at FROM bilibili_cookies WHERE id = 1"
                )
            except Exception as exc:  # noqa: BLE001 - 数据库故障时回退本地文件
                logger.warning("failed to read shared bilibili cookie: %s", exc)
                self._cached_at = now
                return self._cached_row
            self._cached_row = (
                (str(rows[0]["cookie_text"]), str(rows[0]["updated_at"])) if rows else None
            )
            self._cached_at = now
            return self._cached_row

    def read(self) -> str | None:
        row = self._row()
        if row is not None and row[0].strip():
            return row[0]
        # 首次切到共享存储：库里还没有行，但本机卷里可能已有登录态，单向回填一次。
        legacy = _read_text_file(self._canonical_path)
        if legacy and _contains_sessdata(legacy):
            self.write(legacy)
            return legacy
        return legacy

    def write(self, text: str) -> None:
        updated_at = datetime.now(UTC).isoformat()
        with self._lock:
            session = self._session_locked()
            with session.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO bilibili_cookies (id, cookie_text, updated_at)
                    VALUES (1, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        cookie_text = excluded.cookie_text,
                        updated_at = excluded.updated_at
                    """,
                    (text, updated_at),
                )
            self._cached_row = (text, updated_at)
            self._cached_at = time.monotonic()
        _write_text_file(self._canonical_path, text)

    def ensure_file(self, path: Path) -> None:
        """把库里的登录态物化到文件，供 yt-dlp / 服务端解析使用。

        仅当文件缺失或比库行更旧时才写，避免用旧库内容覆盖本机更新的文件
        （例如 Electron 登录窗口刚导出的 cookie）。
        """
        row = self._row()
        if row is None:
            self.read()
            return
        text, updated_at = row
        if not text.strip():
            return
        for target in dict.fromkeys((path, self._canonical_path)):
            if _file_is_current(target, updated_at):
                continue
            _write_text_file(target, text)

    def close(self) -> None:
        with self._lock:
            if self._session is not None:
                self._session.close()
                self._session = None


def _file_is_current(path: Path, updated_at: str) -> bool:
    """文件存在且不早于数据库行时间（保留 1s 容差给同一瞬间的写入）。"""
    if not path.exists():
        return False
    try:
        row_epoch = datetime.fromisoformat(updated_at).timestamp()
    except ValueError:
        return False
    try:
        return path.stat().st_mtime >= row_epoch - 1
    except OSError:
        return False


def create_bilibili_cookie_store(base_settings: Any) -> BilibiliCookieStore:
    """按数据库方言选择存储后端：MySQL 共库共享，其余沿用本地文件。"""
    path = Path(str(getattr(base_settings, "data_dir", "") or ".")) / "cookies" / "bilibili.txt"
    database_url = str(getattr(base_settings, "database_url", "") or "")
    if database_url and database_dialect_from_url(database_url) == "mysql":
        return DbBilibiliCookieStore.from_url(database_url, path)
    return FileBilibiliCookieStore(path)


_store_lock = threading.Lock()
_store: BilibiliCookieStore | None = None
_store_key: tuple[str, str] | None = None


def get_bilibili_cookie_store() -> BilibiliCookieStore:
    """进程级单例；设置里的数据库地址/数据目录变化时自动重建。"""
    global _store, _store_key
    current = settings_manager.current
    key = (
        str(getattr(current, "database_url", "") or ""),
        str(getattr(current, "data_dir", "") or ""),
    )
    with _store_lock:
        if _store is None or _store_key != key:
            if _store is not None:
                _store.close()
            _store = create_bilibili_cookie_store(current)
            _store_key = key
        return _store


def reset_bilibili_cookie_store_for_tests() -> None:
    global _store, _store_key
    with _store_lock:
        if _store is not None:
            _store.close()
        _store = None
        _store_key = None


def materialize_bilibili_cookie_file(path: Path | None = None) -> Path:
    """确保 cookie 文件是最新的，返回其路径（用于 yt-dlp 等要求真实文件的场景）。"""
    target = Path(path).expanduser() if path is not None else resolved_cookie_file()
    try:
        get_bilibili_cookie_store().ensure_file(target)
    except Exception as exc:  # noqa: BLE001 - 物化失败不应中断任务
        logger.warning("failed to materialize bilibili cookie file: %s", exc)
    return target
