import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from video_sum_core.models.tasks import InputType, TaskInput, TaskOptions, TaskResult, TaskStatus
from video_sum_core.pipeline.base import PipelineContext, PipelineEvent, PipelineRunner, PipelineTranscription
from video_sum_service.offpeak import (
    OffPeakScheduler,
    is_peak_now,
    parse_peak_windows,
)
from video_sum_service.repository import SqliteTaskRepository
from video_sum_service.worker import TaskWorker

SHANGHAI = ZoneInfo("Asia/Shanghai")
# 2026-10-12 是周一，2026-10-17 是周六（测试用固定日期，避免依赖运行当天）。
MONDAY = datetime(2026, 10, 12, tzinfo=SHANGHAI)
SATURDAY = datetime(2026, 10, 17, tzinfo=SHANGHAI)


def make_settings(**overrides) -> SimpleNamespace:
    values = {
        "offpeak_timezone": "Asia/Shanghai",
        "offpeak_peak_windows": "09:00-12:00,14:00-18:00",
        "offpeak_peak_weekdays": "0,1,2,3,4",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# ----------------------------------------------------------------------
# parse_peak_windows
# ----------------------------------------------------------------------


def test_parse_peak_windows_basic_and_tolerant() -> None:
    assert parse_peak_windows("09:00-12:00, 14:00-18:00") == [(540, 720), (840, 1080)]
    assert parse_peak_windows("") == []
    assert parse_peak_windows(None) == []
    # 坏段跳过，不影响好段
    assert parse_peak_windows("bad,09:00-12:00,25:00-26:00,09:00-09:00") == [(540, 720)]


def test_parse_peak_windows_overnight() -> None:
    assert parse_peak_windows("22:00-07:00") == [(1320, 420)]
    assert is_peak_now(make_settings(offpeak_peak_windows="22:00-07:00", offpeak_peak_weekdays="0,1,2,3,4,5,6"), now=MONDAY.replace(hour=23))
    assert not is_peak_now(make_settings(offpeak_peak_windows="22:00-07:00", offpeak_peak_weekdays="0,1,2,3,4,5,6"), now=MONDAY.replace(hour=12))


# ----------------------------------------------------------------------
# is_peak_now
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (MONDAY.replace(hour=8, minute=59), False),
        (MONDAY.replace(hour=9, minute=0), True),
        (MONDAY.replace(hour=11, minute=59), True),
        (MONDAY.replace(hour=12, minute=0), False),
        (MONDAY.replace(hour=13, minute=59), False),
        (MONDAY.replace(hour=14, minute=0), True),
        (MONDAY.replace(hour=17, minute=59), True),
        (MONDAY.replace(hour=18, minute=0), False),
        (MONDAY.replace(hour=23, minute=30), False),
        # 周末全天闲时
        (SATURDAY.replace(hour=10, minute=0), False),
        (SATURDAY.replace(hour=15, minute=0), False),
    ],
)
def test_is_peak_now_default_windows(now: datetime, expected: bool) -> None:
    assert is_peak_now(make_settings(), now=now) is expected


def test_is_peak_now_custom_weekdays() -> None:
    settings = make_settings(offpeak_peak_weekdays="5,6")  # 仅周末高峰（假想场景）
    assert is_peak_now(settings, now=SATURDAY.replace(hour=10))
    assert not is_peak_now(settings, now=MONDAY.replace(hour=10))


def test_is_peak_now_empty_config_means_never_peak() -> None:
    assert not is_peak_now(make_settings(offpeak_peak_weekdays=""), now=MONDAY.replace(hour=10))
    assert not is_peak_now(make_settings(offpeak_peak_windows=""), now=MONDAY.replace(hour=10))


def test_is_peak_now_unknown_timezone_falls_back_to_shanghai() -> None:
    settings = make_settings(offpeak_timezone="Not/AZone")
    # 回退到 Asia/Shanghai：周一 10:00 仍是高峰
    assert is_peak_now(settings, now=MONDAY.replace(hour=10))
    assert not is_peak_now(settings, now=MONDAY.replace(hour=13))


def test_is_peak_now_utc_input_converted_to_local() -> None:
    # 周一 01:00 UTC = 上海 09:00 → 高峰
    utc_now = datetime(2026, 10, 12, 1, 0, tzinfo=timezone.utc)
    assert is_peak_now(make_settings(), now=utc_now)


# ----------------------------------------------------------------------
# OffPeakScheduler
# ----------------------------------------------------------------------


def create_repository() -> SqliteTaskRepository:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    repository = SqliteTaskRepository(connection)
    repository.initialize()
    return repository


def make_scheduler(repository: SqliteTaskRepository, app_state, settings=None) -> OffPeakScheduler:
    settings_manager = SimpleNamespace(current=settings or make_settings())
    return OffPeakScheduler(repository, app_state, settings_manager=settings_manager)


def test_scheduler_round_skips_during_peak() -> None:
    repository = create_repository()
    record = repository.create_task(TaskInput(input_type=InputType.URL, source="https://example.com/v"))
    repository.update_status(record.task_id, TaskStatus.WAITING_OFFPEAK)
    worker = SimpleNamespace(resume_offpeak_task=pytest.fail)  # 任何调用都算失败

    scheduler = make_scheduler(repository, SimpleNamespace(task_worker=worker), make_settings())
    peak_now = MONDAY.replace(hour=10)
    with patch("video_sum_service.offpeak.is_peak_now", return_value=True):
        with patch("video_sum_service.runtime_startup.runtime_worker_ready", return_value=True):
            scheduler._round(SimpleNamespace())  # settings 已被 patch 覆盖
    assert repository.get_task(record.task_id).status == TaskStatus.WAITING_OFFPEAK


def test_scheduler_round_resumes_waiting_tasks_offpeak() -> None:
    repository = create_repository()
    records = [
        repository.create_task(TaskInput(input_type=InputType.URL, source=f"https://example.com/v{i}"))
        for i in range(2)
    ]
    for record in records:
        repository.update_status(record.task_id, TaskStatus.WAITING_OFFPEAK)
    resumed: list[str] = []

    def resume(task_id: str) -> bool:
        resumed.append(task_id)
        return True

    worker = SimpleNamespace(resume_offpeak_task=resume)
    app_state = SimpleNamespace(task_worker=worker)
    scheduler = make_scheduler(repository, app_state)

    with patch("video_sum_service.offpeak.is_peak_now", return_value=False):
        with patch("video_sum_service.runtime_startup.runtime_worker_ready", return_value=True):
            scheduler._round(make_settings())
    assert sorted(resumed) == sorted(record.task_id for record in records)
    assert scheduler.status()["lastResumedCount"] == 2


def test_scheduler_round_survives_resume_failure_and_skips_unready_worker() -> None:
    repository = create_repository()
    record = repository.create_task(TaskInput(input_type=InputType.URL, source="https://example.com/v"))
    repository.update_status(record.task_id, TaskStatus.WAITING_OFFPEAK)

    def failing_resume(task_id: str) -> bool:
        raise RuntimeError("boom")

    worker = SimpleNamespace(resume_offpeak_task=failing_resume)
    scheduler = make_scheduler(repository, SimpleNamespace(task_worker=worker))
    # 单个恢复失败不抛出
    with patch("video_sum_service.offpeak.is_peak_now", return_value=False):
        with patch("video_sum_service.runtime_startup.runtime_worker_ready", return_value=True):
            scheduler._round(make_settings())
    assert scheduler.status()["lastRoundError"] is None

    # worker 未就绪时整轮跳过
    with patch("video_sum_service.offpeak.is_peak_now", return_value=False):
        with patch("video_sum_service.runtime_startup.runtime_worker_ready", return_value=False):
            scheduler._round(make_settings())


# ----------------------------------------------------------------------
# Repository
# ----------------------------------------------------------------------


def test_list_offpeak_waiting_tasks_filters_status() -> None:
    repository = create_repository()
    parked = repository.create_task(TaskInput(input_type=InputType.URL, source="https://example.com/parked"))
    queued = repository.create_task(TaskInput(input_type=InputType.URL, source="https://example.com/queued"))
    done = repository.create_task(TaskInput(input_type=InputType.URL, source="https://example.com/done"))
    repository.update_status(parked.task_id, TaskStatus.WAITING_OFFPEAK)
    repository.update_status(queued.task_id, TaskStatus.QUEUED)
    repository.update_status(done.task_id, TaskStatus.COMPLETED)

    waiting = repository.list_offpeak_waiting_tasks()
    assert [record.task_id for record in waiting] == [parked.task_id]
    # 恢复扫描不包含 waiting_offpeak，不会与启动恢复冲突
    assert all(record.task_id != parked.task_id for record in repository.list_recoverable_tasks())


# ----------------------------------------------------------------------
# Worker gate + resume
# ----------------------------------------------------------------------


class StagedOffpeakRunner(PipelineRunner):
    """模拟分段管线：转写立即返回，摘要阶段等待手动放行。"""

    def __init__(self) -> None:
        self.summary_started: list[str] = []
        self._summary_release: dict[str, object] = {}

    def supports_staged_execution(self) -> bool:
        return True

    def run_transcription(self, context: PipelineContext, on_event=None) -> PipelineTranscription:
        if on_event is not None:
            # 模拟转写完成事件：result 会被 worker 持久化到 result_json
            on_event(
                PipelineEvent(
                    stage="transcribing",
                    progress=86,
                    message="转写完成",
                    payload={"result": TaskResult(transcript_text=f"转写-{context.task_id}", segments=[{"start": 0.0, "end": 1.0, "text": "hi"}]).model_dump()},
                )
            )
        return PipelineTranscription(
            title=context.task_input.title or context.task_id,
            transcript=f"转写-{context.task_id}",
            segments=[{"start": 0.0, "end": 1.0, "text": "hi"}],
            task_dir=Path(f"/tmp/{context.task_id}"),
        )

    def run_summary(self, context: PipelineContext, transcription: PipelineTranscription, on_event=None) -> TaskResult:
        self.summary_started.append(context.task_id)
        return TaskResult(overview=f"总结-{context.task_id}", transcript_text=transcription.transcript)

    def preflight(self, context: PipelineContext, on_event=None) -> None:
        return None


def make_worker(repository: SqliteTaskRepository, runner: PipelineRunner) -> TaskWorker:
    return TaskWorker(
        repository,
        runner,
        auto_generate_mindmap=False,
        transcription_concurrency=1,
        llm_concurrency=1,
    )


def create_scheduled_task(repository: SqliteTaskRepository, schedule: str):
    return repository.create_task(
        TaskInput(
            input_type=InputType.URL,
            source="https://example.com/video",
            title="测试视频",
            options=TaskOptions(schedule=schedule),
        )
    )


def wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met before timeout")


def test_offpeak_task_parked_during_peak_and_resumed() -> None:
    repository = create_repository()
    record = create_scheduled_task(repository, "offpeak")
    runner = StagedOffpeakRunner()
    worker = make_worker(repository, runner)

    with patch("video_sum_service.worker.is_peak_now", return_value=True):
        worker.submit(record)
        # patch 必须覆盖整个异步转写过程，直到停车落库
        wait_for(lambda: repository.get_task(record.task_id).status == TaskStatus.WAITING_OFFPEAK)
    time.sleep(0.2)
    # LLM 阶段完全没有启动
    assert runner.summary_started == []
    refreshed = repository.get_task(record.task_id)
    assert refreshed.status == TaskStatus.WAITING_OFFPEAK
    # 转写结果已持久化（恢复的数据来源）
    assert refreshed.result is not None
    assert refreshed.result.transcript_text
    # 内存 staging 已清空（worker 重建安全）
    assert record.task_id not in worker._staged_transcriptions
    # batch 项以 waiting_offpeak 收尾，batch 条可完成
    batch = worker.snapshot()["batch"]
    item = batch["items"][0]
    assert item["status"] == TaskStatus.WAITING_OFFPEAK.value
    assert batch["completed_at"] is not None

    # 重复恢复被拒绝（幂等）
    assert worker.resume_offpeak_task(record.task_id) is True
    assert worker.resume_offpeak_task(record.task_id) is False
    wait_for(lambda: repository.get_task(record.task_id).status == TaskStatus.COMPLETED)
    assert runner.summary_started == [record.task_id]
    events = repository.list_events(record.task_id)
    stages = [event.stage for event in events]
    assert "waiting_offpeak" in stages
    assert "offpeak_resumed" in stages


def test_offpeak_task_runs_immediately_offpeak() -> None:
    repository = create_repository()
    record = create_scheduled_task(repository, "offpeak")
    runner = StagedOffpeakRunner()
    worker = make_worker(repository, runner)

    with patch("video_sum_service.worker.is_peak_now", return_value=False):
        worker.submit(record)
        wait_for(lambda: repository.get_task(record.task_id).status == TaskStatus.COMPLETED)
    assert runner.summary_started == [record.task_id]


def test_immediate_task_runs_during_peak() -> None:
    repository = create_repository()
    record = create_scheduled_task(repository, "immediate")
    runner = StagedOffpeakRunner()
    worker = make_worker(repository, runner)

    with patch("video_sum_service.worker.is_peak_now", return_value=True):
        worker.submit(record)
        wait_for(lambda: repository.get_task(record.task_id).status == TaskStatus.COMPLETED)
    assert runner.summary_started == [record.task_id]


def test_resume_offpeak_task_rejects_non_parked_or_missing_transcript() -> None:
    repository = create_repository()
    running = create_scheduled_task(repository, "immediate")
    repository.update_status(running.task_id, TaskStatus.RUNNING)
    empty = create_scheduled_task(repository, "offpeak")
    repository.update_status(empty.task_id, TaskStatus.WAITING_OFFPEAK)

    worker = make_worker(repository, StagedOffpeakRunner())
    assert worker.resume_offpeak_task(running.task_id) is False
    assert worker.resume_offpeak_task(empty.task_id) is False
    assert worker.resume_offpeak_task("no-such-task") is False


# ----------------------------------------------------------------------
# REST：run-now
# ----------------------------------------------------------------------


def test_run_now_endpoint_paths() -> None:
    from fastapi import HTTPException

    from video_sum_service.app import app
    from video_sum_service.routers import tasks as tasks_router

    repository = create_repository()
    app.state.task_repository = repository
    app.state.task_worker = None
    request = type("Request", (), {"app": app})()

    record = create_scheduled_task(repository, "offpeak")
    repository.update_status(record.task_id, TaskStatus.WAITING_OFFPEAK)
    repository.save_result(record.task_id, TaskResult(transcript_text="转写内容", segments=[]))

    # worker 不可用 → 503
    with pytest.raises(HTTPException) as exc_info:
        tasks_router.run_task_now(record.task_id, request)
    assert exc_info.value.status_code == 503

    # 正常恢复 → 返回 running 详情
    worker = make_worker(repository, StagedOffpeakRunner())
    app.state.task_worker = worker
    with patch("video_sum_service.worker.is_peak_now", return_value=True):
        response = tasks_router.run_task_now(record.task_id, request)
    assert response.status == TaskStatus.RUNNING

    # 已恢复（非 waiting_offpeak）→ 400
    with pytest.raises(HTTPException) as exc_info:
        tasks_router.run_task_now(record.task_id, request)
    assert exc_info.value.status_code == 400

    # 不存在 → 404
    with pytest.raises(HTTPException) as exc_info:
        tasks_router.run_task_now("no-such-task", request)
    assert exc_info.value.status_code == 404
