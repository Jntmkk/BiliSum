"""MySQL integration tests for database-backed settings.

Skipped unless VIDEO_SUM_TEST_MYSQL_URL points at a reachable MySQL server.
A dedicated database is created and dropped per test module run.
"""

import os
import uuid
from urllib.parse import urlparse

import pytest

from video_sum_infra.config import ServiceSettings
from video_sum_infra.db import open_database
from video_sum_service.settings_manager import SettingsManager, SettingsUpdatePayload
from video_sum_service.settings_store import DbSettingsStore, create_settings_store

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


DB_NAME = f"video_sum_settings_test_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def database_url():
    admin = open_database(_server_url())
    try:
        admin.execute(f"CREATE DATABASE {DB_NAME} CHARACTER SET utf8mb4")
    finally:
        admin.close()
    yield _fresh_url(DB_NAME)
    admin = open_database(_server_url())
    try:
        admin.execute(f"DROP DATABASE IF EXISTS {DB_NAME}")
    finally:
        admin.close()


def _base(tmp_path, database_url: str, port: int = 3838) -> ServiceSettings:
    return ServiceSettings(
        _env_file=None,
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        tasks_dir=tmp_path / "tasks",
        database_url=database_url,
        host="127.0.0.1",
        port=port,
    )


_managers: list[SettingsManager] = []


def _manager(tmp_path, database_url: str, port: int = 3838) -> SettingsManager:
    base = _base(tmp_path, database_url, port=port)
    manager = SettingsManager(base, store=create_settings_store(base))
    _managers.append(manager)
    return manager


@pytest.fixture(scope="module", autouse=True)
def _close_managers():
    yield
    for manager in _managers:
        manager.close()


def test_settings_roundtrip_on_mysql(database_url, tmp_path) -> None:
    manager = _manager(tmp_path, database_url)
    assert isinstance(manager._store, DbSettingsStore)
    manager.load()
    manager.save(SettingsUpdatePayload(language="en", llm_model="deepseek-flash"))
    reloaded = _manager(tmp_path / "again", database_url)
    settings = reloaded.load()
    assert settings.language == "en"
    assert settings.llm_model == "deepseek-flash"
    # Instance-local fields come from the environment, not the shared store.
    assert settings.database_url == database_url
    assert settings.port == 3838


def test_settings_shared_between_instances_on_mysql(database_url, tmp_path) -> None:
    manager_a = _manager(tmp_path / "a", database_url, port=3838)
    manager_a.load()
    manager_a.save(SettingsUpdatePayload(summary_mode="full-context"))

    manager_b = _manager(tmp_path / "b", database_url, port=3939)
    settings_b = manager_b.load()
    assert settings_b.summary_mode == "full-context"
    assert settings_b.port == 3939


def test_settings_secret_masking_survives_mysql_roundtrip(database_url, tmp_path) -> None:
    manager = _manager(tmp_path, database_url)
    manager.load()
    manager.save(SettingsUpdatePayload(llm_api_key="sk-mysql-secret"))
    manager.save(SettingsUpdatePayload(llm_api_key="******"))
    assert manager.current.llm_api_key == "sk-mysql-secret"
    raw = manager._store.load()
    assert raw["llm_api_key"] == "sk-mysql-secret"
