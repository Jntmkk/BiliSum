from types import SimpleNamespace

from video_sum_service.runtime_startup import (
    is_llm_only_instance,
    submit_mindmap_or_queue,
    submit_task_or_queue,
)


class FakeRepository:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, int, str, dict]] = []

    def update_status(self, task_id: str, status) -> None:
        raise AssertionError("llm_only instance must not touch task status")

    def update_error(self, task_id: str, code: str, message: str) -> None:
        raise AssertionError("llm_only instance must not touch task error")

    def append_event(self, task_id, stage, progress, message, payload=None) -> None:
        self.events.append((task_id, stage, progress, message, payload or {}))


def _make_app_state(executor_role: str) -> SimpleNamespace:
    return SimpleNamespace(
        settings_manager=SimpleNamespace(current=SimpleNamespace(executor_role=executor_role))
    )


def test_is_llm_only_instance() -> None:
    assert is_llm_only_instance(_make_app_state("llm_only")) is True
    assert is_llm_only_instance(_make_app_state("full")) is False
    assert is_llm_only_instance(_make_app_state("")) is False
    assert is_llm_only_instance(_make_app_state("LLM_ONLY")) is True


def test_submit_task_or_queue_marks_external_on_llm_only() -> None:
    repository = FakeRepository()
    record = SimpleNamespace(task_id="task-1")

    submit_task_or_queue(_make_app_state("llm_only"), repository, record)

    assert len(repository.events) == 1
    task_id, stage, _progress, _message, payload = repository.events[0]
    assert task_id == "task-1"
    assert stage == "external"
    assert payload.get("executor_role") == "llm_only"


def test_submit_mindmap_or_queue_marks_external_on_llm_only() -> None:
    repository = FakeRepository()

    submit_mindmap_or_queue(_make_app_state("llm_only"), repository, "task-2", force=True)

    assert len(repository.events) == 1
    task_id, stage, _progress, _message, payload = repository.events[0]
    assert task_id == "task-2"
    assert stage == "mindmap_external"
    assert payload.get("executor_role") == "llm_only"
    assert payload.get("force") is True
