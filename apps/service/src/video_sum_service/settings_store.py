"""Pluggable settings persistence backends.

``FileSettingsStore`` keeps the historical behavior: settings live in
``{data_dir}/settings.json``. ``DbSettingsStore`` persists the same JSON
payload in a single-row ``settings`` table through the shared
``DatabaseSession`` dialect layer, so instances backed by MySQL share one
configuration. The store is chosen from the ``database_url`` scheme.
"""

import json
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from video_sum_infra.db import (
    DatabaseSession,
    SQLiteSession,
    database_dialect_from_url,
    open_database,
)

_SETTINGS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY,
    settings_json TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
)
"""


class SettingsStore:
    """Settings persistence backend interface.

    ``load`` returns the stored raw dict (or None when empty); ``save``
    persists the full settings dump. ``version`` bumps on every save in the
    database backend so other instances can detect changes cheaply.
    """

    def load(self) -> dict[str, Any] | None:
        raise NotImplementedError

    def save(self, data: dict[str, Any]) -> None:
        raise NotImplementedError

    def version(self) -> int:
        return 0

    def has_data(self) -> bool:
        return self.load() is not None

    def close(self) -> None:
        pass


class FileSettingsStore(SettingsStore):
    """JSON file storage (historical behavior, used for SQLite setups)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, Any] | None:
        if not self._path.exists():
            return None
        return json.loads(self._path.read_text(encoding="utf-8"))

    def save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write (temp file + rename) so an interrupted or concurrent
        # write can never leave a truncated settings.json.
        tmp_path = self._path.with_name(self._path.name + ".tmp")
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, self._path)

    def has_data(self) -> bool:
        return self._path.exists()


class DbSettingsStore(SettingsStore):
    """Single-row ``settings`` table storage for database-backed instances.

    The connection is created lazily on first use because the settings
    manager is constructed at import time, before the app lifespan opens the
    repository session.
    """

    def __init__(self, session_factory: Callable[[], DatabaseSession]) -> None:
        self._session_factory = session_factory
        self._session: DatabaseSession | None = None
        self._lock = threading.Lock()

    @classmethod
    def from_url(cls, database_url: str) -> "DbSettingsStore":
        return cls(lambda: open_database(database_url))

    def _get_session(self) -> DatabaseSession:
        with self._lock:
            if self._session is None:
                session = self._session_factory()
                with session.cursor() as cursor:
                    cursor.execute(_SETTINGS_TABLE_DDL)
                self._session = session
            return self._session

    def load(self) -> dict[str, Any] | None:
        rows = self._get_session().execute("SELECT settings_json FROM settings WHERE id = 1")
        if not rows:
            return None
        return json.loads(str(rows[0]["settings_json"]))

    def save(self, data: dict[str, Any]) -> None:
        from datetime import UTC, datetime

        payload = json.dumps(data, ensure_ascii=False)
        updated_at = datetime.now(UTC).isoformat()
        with self._get_session().cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO settings (id, settings_json, version, updated_at)
                VALUES (1, ?, 1, ?)
                ON CONFLICT(id) DO UPDATE SET
                    settings_json = excluded.settings_json,
                    version = version + 1,
                    updated_at = excluded.updated_at
                """,
                (payload, updated_at),
            )

    def version(self) -> int:
        rows = self._get_session().execute("SELECT version FROM settings WHERE id = 1")
        return int(rows[0]["version"]) if rows else 0

    def has_data(self) -> bool:
        rows = self._get_session().execute("SELECT id FROM settings WHERE id = 1")
        return bool(rows)

    def close(self) -> None:
        with self._lock:
            if self._session is not None:
                self._session.close()
                self._session = None


def create_settings_store(base_settings: Any) -> SettingsStore:
    """Pick the store backend from the configured database URL.

    MySQL-backed instances share configuration through the database; SQLite
    and anything else keep the local settings.json file.
    """

    database_url = str(getattr(base_settings, "database_url", "") or "")
    if database_url and database_dialect_from_url(database_url) == "mysql":
        return DbSettingsStore.from_url(database_url)
    return FileSettingsStore(Path(base_settings.data_dir) / "settings.json")


# Re-exported for tests that build a store over an in-memory SQLite connection.
__all__ = [
    "DatabaseSession",
    "DbSettingsStore",
    "FileSettingsStore",
    "SQLiteSession",
    "SettingsStore",
    "create_settings_store",
]
