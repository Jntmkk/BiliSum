from pathlib import Path

from video_sum_infra.config import ServiceSettings
from video_sum_service import artifact_store


def _settings(tmp_path: Path, **updates: object) -> ServiceSettings:
    base = {
        "data_dir": str(tmp_path / "data"),
        "cache_dir": str(tmp_path / "data" / "cache"),
        "tasks_dir": str(tmp_path / "data" / "tasks"),
    }
    base.update({k: str(v) for k, v in updates.items()})
    return ServiceSettings(**base, _env_file=None)


def test_relative_under_resolves_nested_paths(tmp_path: Path) -> None:
    root = tmp_path / "tasks"
    nested = root / "task-1" / "transcript.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("x", encoding="utf-8")
    assert artifact_store._relative_under(nested, root) == "task-1/transcript.txt"
    assert artifact_store._relative_under(root / "other.txt", root) == "other.txt"
    assert artifact_store._relative_under(tmp_path / "outside.txt", root) is None


def test_is_shareable_file_filters_by_suffix_and_size(tmp_path: Path) -> None:
    md = tmp_path / "note.md"
    md.write_text("content", encoding="utf-8")
    assert artifact_store._is_shareable_file(md) is True

    mp3 = tmp_path / "audio.mp3"
    mp3.write_bytes(b"x" * 10)
    assert artifact_store._is_shareable_file(mp3) is False

    empty = tmp_path / "empty.md"
    empty.write_text("", encoding="utf-8")
    assert artifact_store._is_shareable_file(empty) is False


def test_ensure_artifact_file_returns_original_when_oss_unconfigured(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    missing = Path(settings.tasks_dir) / "task-1" / "transcript.txt"
    assert artifact_store.ensure_artifact_file(settings, missing) == missing
    assert artifact_store.artifact_media_url(settings, missing) is None
    assert artifact_store.oss_share_available(settings) is False


def test_upload_task_artifacts_noop_when_oss_unconfigured(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    task_dir = Path(settings.tasks_dir) / "task-1"
    task_dir.mkdir(parents=True)
    (task_dir / "transcript.txt").write_text("hello", encoding="utf-8")
    assert artifact_store.upload_task_artifacts(settings, "task-1") == 0


def test_object_key_sanitizes_path_parts() -> None:
    assert artifact_store._object_key_for("tasks/task-1/transcript.txt") == (
        "artifact-store/tasks/task-1/transcript.txt"
    )
    assert artifact_store._object_key_for("../evil/../../x") == "artifact-store/evil/x"
