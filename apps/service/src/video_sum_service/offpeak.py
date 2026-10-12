"""低峰期 LLM 调度器。

DeepSeek 等服务商实行峰谷计价（工作日白天高峰、其余时间半价）。本模块提供：

- ``parse_peak_windows`` / ``is_peak_now``：按可配置的时区 / 星期 / 时段判断当前
  是否处于 LLM 高峰时段。
- ``OffPeakScheduler``：daemon 线程 + Event(wake/stop)，每轮重读 settings 热更新；
  非高峰时段把标记为 ``waiting_offpeak`` 的任务交还给 worker 恢复 LLM 阶段。

停车语义：``schedule=offpeak`` 意为「避开高峰计价」——闲时提交的任务立即执行，
只有高峰时段提交的任务在转写完成后暂停 LLM 阶段，转写工件在入库时已持久化，
恢复时直接从库中重建（见 ``TaskWorker.resume_offpeak_task``）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from threading import Event, Lock, Thread
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

DEFAULT_OFFPEAK_TIMEZONE = "Asia/Shanghai"
DEFAULT_OFFPEAK_PEAK_WINDOWS = "09:00-12:00,14:00-18:00"
DEFAULT_OFFPEAK_PEAK_WEEKDAYS = "0,1,2,3,4"  # Python weekday：周一=0 … 周日=6

OFFPEAK_SCHEDULER_INTERVAL_SECONDS = 30


def parse_peak_windows(raw: object) -> list[tuple[int, int]]:
    """把 ``"09:00-12:00,14:00-18:00"`` 解析成 [(start_min, end_min), ...]。

    容忍空白与坏段（跳过并告警）；支持跨零点时段（如 "22:00-07:00"）。
    """
    windows: list[tuple[int, int]] = []
    for segment in str(raw or "").split(","):
        segment = segment.strip()
        if not segment or "-" not in segment:
            if segment:
                logger.warning("offpeak: ignoring malformed peak window segment %r", segment)
            continue
        start_raw, _, end_raw = segment.partition("-")
        start = _parse_minute_of_day(start_raw.strip())
        end = _parse_minute_of_day(end_raw.strip())
        if start is None or end is None:
            logger.warning("offpeak: ignoring malformed peak window segment %r", segment)
            continue
        if start == end:
            logger.warning("offpeak: ignoring empty peak window segment %r", segment)
            continue
        windows.append((start, end))
    return windows


def _parse_minute_of_day(value: str) -> int | None:
    hour_raw, sep, minute_raw = value.partition(":")
    if not sep:
        return None
    try:
        hour = int(hour_raw)
        minute = int(minute_raw)
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def _parse_peak_weekdays(raw: object) -> set[int]:
    """把 ``"0,1,2,3,4"``（Python weekday，周一=0）解析成星期集合；空串→空集。"""
    days: set[int] = set()
    for segment in str(raw or "").split(","):
        segment = segment.strip()
        if not segment:
            continue
        try:
            day = int(segment)
        except ValueError:
            logger.warning("offpeak: ignoring malformed peak weekday %r", segment)
            continue
        if 0 <= day <= 6:
            days.add(day)
        else:
            logger.warning("offpeak: ignoring out-of-range peak weekday %r", segment)
    return days


def _resolve_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        logger.warning("offpeak: unknown timezone %r, fallback to %s", name, DEFAULT_OFFPEAK_TIMEZONE)
        return ZoneInfo(DEFAULT_OFFPEAK_TIMEZONE)


def is_peak_now(settings: Any, *, now: datetime | None = None) -> bool:
    """当前（settings 配置的时区下）是否处于 LLM 高峰时段。

    高峰日为 ``offpeak_peak_weekdays``（空集 = 永不高峰），高峰时段为
    ``offpeak_peak_windows``（空串 = 永不高峰）。
    """
    tz_name = str(getattr(settings, "offpeak_timezone", "") or "").strip() or DEFAULT_OFFPEAK_TIMEZONE
    local_tz = _resolve_timezone(tz_name)
    local_now = (now or datetime.now(timezone.utc)).astimezone(local_tz)
    weekdays = _parse_peak_weekdays(getattr(settings, "offpeak_peak_weekdays", DEFAULT_OFFPEAK_PEAK_WEEKDAYS))
    if not weekdays:
        return False
    if local_now.weekday() not in weekdays:
        return False
    windows = parse_peak_windows(getattr(settings, "offpeak_peak_windows", DEFAULT_OFFPEAK_PEAK_WINDOWS))
    minute = local_now.hour * 60 + local_now.minute
    return any(_window_contains(start, end, minute) for start, end in windows)


def _window_contains(start: int, end: int, minute: int) -> bool:
    if start < end:
        return start <= minute < end
    # 跨零点时段，如 22:00-07:00
    return minute >= start or minute < end


class OffPeakScheduler:
    """扫描 ``waiting_offpeak`` 任务并在低峰期交还 worker 执行。"""

    def __init__(
        self,
        repository: Any,
        app_state: Any,
        *,
        settings_manager: Any | None = None,
    ) -> None:
        from video_sum_service.context import settings_manager as global_settings_manager

        self._repository = repository
        self._app_state = app_state
        self._settings_manager = settings_manager or global_settings_manager
        self._stop = Event()
        self._wake = Event()
        self._lock = Lock()
        self._last_round_at: str | None = None
        self._last_round_error: str | None = None
        self._last_resumed_count: int = 0
        self._thread = Thread(target=self._run, name="offpeak-scheduler", daemon=True)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    def refresh_now(self) -> None:
        """唤醒调度线程立即执行一轮（REST 手动触发入口）。"""
        self._wake.set()

    @property
    def running(self) -> bool:
        return self._thread.is_alive() and not self._stop.is_set()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self.running,
                "lastRoundAt": self._last_round_at,
                "lastRoundError": self._last_round_error,
                "lastResumedCount": self._last_resumed_count,
                "waitingCount": len(self._repository.list_offpeak_waiting_tasks()),
            }

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            settings = self._settings_manager.current
            try:
                self._round(settings)
                with self._lock:
                    self._last_round_at = datetime.now(timezone.utc).isoformat()
                    self._last_round_error = None
            except Exception:  # noqa: BLE001 - 单轮失败不应杀死线程
                logger.exception("offpeak scheduler round failed")
                with self._lock:
                    self._last_round_error = "round failed"
            self._wake.wait(timeout=OFFPEAK_SCHEDULER_INTERVAL_SECONDS)
            self._wake.clear()

    # ------------------------------------------------------------------
    # 单轮逻辑
    # ------------------------------------------------------------------

    def _round(self, settings: Any) -> None:
        from video_sum_service.runtime_startup import runtime_worker_ready

        if is_peak_now(settings):
            return
        worker = getattr(self._app_state, "task_worker", None)
        if worker is None or not runtime_worker_ready(self._app_state):
            return
        resumed = 0
        for record in self._repository.list_offpeak_waiting_tasks():
            if self._stop.is_set():
                return
            try:
                if worker.resume_offpeak_task(record.task_id):
                    resumed += 1
            except Exception:  # noqa: BLE001 - 单个任务恢复失败不应中断整轮
                logger.exception("offpeak: resume parked task failed task_id=%s", record.task_id)
        with self._lock:
            self._last_resumed_count = resumed
        if resumed:
            logger.info("offpeak: resumed %d parked task(s)", resumed)
