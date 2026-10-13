import json
import sqlite3
import tempfile
from pathlib import Path

from video_sum_infra.config import ServiceSettings
from video_sum_infra.db import SQLiteSession
from video_sum_service.settings_manager import SettingsManager, SettingsUpdatePayload
from video_sum_service.settings_store import (
    DbSettingsStore,
    FileSettingsStore,
    SettingsStore,
    create_settings_store,
)


def make_base(tmp_path: Path, **overrides) -> ServiceSettings:
    values = {
        "data_dir": tmp_path / "data",
        "cache_dir": tmp_path / "cache",
        "tasks_dir": tmp_path / "tasks",
        "database_url": f"sqlite:///{tmp_path}/video_sum.db",
        "host": "127.0.0.1",
        "port": 3838,
    }
    values.update(overrides)
    return ServiceSettings(_env_file=None, **values)


def make_db_store() -> DbSettingsStore:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return DbSettingsStore(lambda: SQLiteSession(connection))


def test_file_store_roundtrip(tmp_path: Path) -> None:
    store = FileSettingsStore(tmp_path / "settings.json")
    assert store.load() is None
    store.save({"language": "en"})
    assert store.load() == {"language": "en"}
    assert store.has_data()


def test_file_mode_preserves_settings_file(tmp_path: Path) -> None:
    base = make_base(tmp_path)
    manager = SettingsManager(base, store=FileSettingsStore(tmp_path / "data" / "settings.json"))
    manager.load()
    assert manager.has_persisted_settings is False
    manager.save(SettingsUpdatePayload(language="en"))
    assert manager.has_persisted_settings is True
    reloaded = SettingsManager(base, store=FileSettingsStore(tmp_path / "data" / "settings.json"))
    assert reloaded.load().language == "en"


def test_create_settings_store_picks_backend_by_scheme(tmp_path: Path) -> None:
    sqlite_base = make_base(tmp_path)
    assert isinstance(create_settings_store(sqlite_base), FileSettingsStore)
    mysql_base = make_base(tmp_path, database_url="mysql://u:p@h:3306/db")
    assert isinstance(create_settings_store(mysql_base), DbSettingsStore)


def test_db_store_roundtrip_and_version() -> None:
    store = make_db_store()
    assert store.load() is None
    assert store.has_data() is False
    store.save({"language": "en"})
    store.save({"language": "zh"})
    assert store.load() == {"language": "zh"}
    assert store.version() == 2
    assert store.has_data() is True


def test_db_mode_seeds_from_settings_json_and_forces_local_fields(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir(parents=True)
    (tmp_path / "data" / "settings.json").write_text(
        json.dumps(
            {
                "language": "en",
                "llm_model": "deepseek-flash",
                "database_url": "sqlite:////other/machine/x.db",
                "data_dir": "/other/machine/data",
                "host": "0.0.0.0",
            }
        ),
        encoding="utf-8",
    )
    base = make_base(tmp_path, database_url="mysql://u:p@h:3306/db")
    store = make_db_store()
    manager = SettingsManager(base, store=store)
    settings = manager.load()

    # Seeded values follow into the DB...
    assert settings.language == "en"
    assert settings.llm_model == "deepseek-flash"
    # ...but instance-local fields always come from the local environment.
    assert settings.database_url == "mysql://u:p@h:3306/db"
    assert settings.data_dir == tmp_path / "data"
    assert settings.host == "127.0.0.1"
    # Seed is persisted to the DB; the local file is left untouched.
    assert store.load() is not None
    on_disk = json.loads((tmp_path / "data" / "settings.json").read_text(encoding="utf-8"))
    assert on_disk["database_url"] == "sqlite:////other/machine/x.db"


def test_db_mode_shared_config_across_instances(tmp_path: Path) -> None:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    base_a = make_base(tmp_path, database_url="mysql://u:p@h:3306/db", port=3838)
    base_b = make_base(
        tmp_path / "b",
        database_url="mysql://u:p@h:3306/db",
        port=3939,
    )
    manager_a = SettingsManager(base_a, store=DbSettingsStore(lambda: SQLiteSession(connection)))
    manager_a.load()
    manager_a.save(SettingsUpdatePayload(language="en"))

    manager_b = SettingsManager(base_b, store=DbSettingsStore(lambda: SQLiteSession(connection)))
    settings_b = manager_b.load()
    assert settings_b.language == "en"
    assert settings_b.port == 3939  # instance-local field stays local


def test_db_mode_save_masks_secrets(tmp_path: Path) -> None:
    store = make_db_store()
    manager = SettingsManager(make_base(tmp_path, database_url="mysql://u:p@h:3306/db"), store=store)
    manager.load()
    manager.save(SettingsUpdatePayload(llm_api_key="sk-real-secret"))
    manager.save(SettingsUpdatePayload(llm_api_key="******"))
    assert manager.current.llm_api_key == "sk-real-secret"
    assert store.load()["llm_api_key"] == "sk-real-secret"


def test_file_store_never_auto_refreshes(tmp_path: Path, monkeypatch) -> None:
    base = make_base(tmp_path)
    store = FileSettingsStore(tmp_path / "data" / "settings.json")
    manager = SettingsManager(base, store=store)
    manager.load()

    class ExplodingStore(SettingsStore):
        def version(self) -> int:
            raise AssertionError("file store must not be version-probed")

    manager._store = ExplodingStore()
    assert manager.current.language == base.language


def test_db_mode_detects_external_change_within_ttl_window(tmp_path: Path, monkeypatch) -> None:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    store = DbSettingsStore(lambda: SQLiteSession(connection))
    base = make_base(tmp_path, database_url="mysql://u:p@h:3306/db")
    manager = SettingsManager(base, store=store)
    manager.load()
    assert manager.current.language == "zh"

    # Another instance writes through the same store.
    store.save({**manager.current.model_dump(mode="json"), "language": "en"})
    # Simulate the TTL window having elapsed so the version probe runs.
    manager._loaded_at = 0.0
    assert manager.current.language == "en"
