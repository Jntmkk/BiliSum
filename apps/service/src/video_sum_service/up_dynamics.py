"""UP 主新视频动态监控轮询服务。

线程模型对照 ``knowledge/job_coordinator.py``：daemon 线程 + Event(wake/stop)，
每轮重读 settings 以热更新开关与轮询间隔；UP 之间串行请求并加随机抖动以规避
B 站风控。发现新视频后自动入库（video_assets）并自动提交总结任务。
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone
from threading import Event, Lock, Thread
from typing import Any

from video_sum_core.models.tasks import InputType, TaskInput, TaskOptions
from video_sum_service import bilibili_wbi
from video_sum_service.bilibili_wbi import (
    CookieInvalidError,
    CookieMissingError,
    RateLimitedError,
    UpDynamicsError,
    UpNotFoundError,
    UpVideoItem,
)
from video_sum_service.context import settings_manager as global_settings_manager
from video_sum_service.repository import SqliteTaskRepository
from video_sum_service.runtime_startup import submit_task_or_queue
from video_sum_service.schemas import TaskRecord, VideoAssetRecord

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 5
_TASK_TERMINAL_STATUSES = ("completed", "failed", "cancelled")


class UpDynamicsWatcher:
    """周期性拉取关注 UP 主的新投稿并自动入库 + 提交总结任务。"""

    def __init__(
        self,
        repository: SqliteTaskRepository,
        app_state: Any,
        *,
        settings_manager: Any | None = None,
        sleep_fn: Any = time.sleep,
    ) -> None:
        self._repository = repository
        self._app_state = app_state
        self._settings_manager = settings_manager or global_settings_manager
        self._sleep = sleep_fn
        self._stop = Event()
        self._wake = Event()
        self._lock = Lock()
        self._cookie_missing = False
        self._last_round_at: str | None = None
        self._last_round_error: str | None = None
        self._thread = Thread(target=self._run, name="up-dynamics-watcher", daemon=True)

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
        """唤醒轮询线程立即执行一轮（REST 手动刷新入口）。"""
        self._wake.set()

    def submit_detection_task(self, detection: dict[str, Any]) -> str | None:
        """对单条检出记录手动发起总结任务（REST「一键总结」入口）。"""
        bvid = str(detection.get("bvid") or "")
        if not bvid:
            return None
        if detection.get("video_id"):
            asset = self._repository.get_video_asset(str(detection["video_id"]))
        else:
            asset = self._repository.get_video_asset_by_canonical_id(bvid)
        if asset is None:
            cookie_header = bilibili_wbi.load_bilibili_cookie_header()
            if not cookie_header:
                raise CookieMissingError("B 站登录态缺失，无法拉取视频信息。")
            subscription = self._repository.get_up_subscription(str(detection.get("subscription_id") or ""))
            mid = str(subscription.get("mid") or "")
            items = bilibili_wbi.fetch_up_videos(mid, cookie_header) if mid else []
            item = next((entry for entry in items if entry.bvid == bvid), None)
            if item is None:
                return None
            asset = self._ensure_asset(item)
        task_id = self._submit_summary_task(
            asset,
            UpVideoItem(
                bvid=bvid,
                aid=detection.get("aid"),
                title=str(detection.get("title") or asset.title),
                cover_url=str(detection.get("cover_url") or ""),
                duration=int(detection.get("duration") or 0),
                pubdate=int(detection.get("pubdate") or 0),
                description=str(detection.get("description") or ""),
            ),
            use_offpeak_default=False,
        )
        if task_id:
            self._repository.update_up_detected_video(
                str(detection["detection_id"]),
                video_id=asset.video_id,
                task_id=task_id,
                task_status="queued",
                detection_status="task_submitted",
            )
        return task_id

    @property
    def running(self) -> bool:
        return self._thread.is_alive() and not self._stop.is_set()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self.running,
                "cookieReady": not self._cookie_missing,
                "lastRoundAt": self._last_round_at,
                "lastRoundError": self._last_round_error,
            }

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            settings = self._settings_manager.current
            interval = max(1, int(settings.up_dynamics_poll_interval_seconds or 600))
            if bool(settings.up_dynamics_enabled):
                try:
                    self._round()
                    with self._lock:
                        self._last_round_at = datetime.now(timezone.utc).isoformat()
                        self._last_round_error = None
                except Exception as exc:  # noqa: BLE001 - 单轮失败不应杀死线程
                    logger.exception("up dynamics poll round failed")
                    with self._lock:
                        self._last_round_error = str(exc)
            self._wake.wait(timeout=interval)
            self._wake.clear()

    # ------------------------------------------------------------------
    # 单轮逻辑
    # ------------------------------------------------------------------

    def _round(self) -> None:
        cookie_header = bilibili_wbi.load_bilibili_cookie_header()
        if not cookie_header:
            with self._lock:
                self._cookie_missing = True
            return
        with self._lock:
            self._cookie_missing = False

        subscriptions = self._repository.list_up_subscriptions(enabled_only=True)
        for index, subscription in enumerate(subscriptions):
            if self._stop.is_set():
                return
            if index > 0:
                self._sleep(random.uniform(2.0, 4.0))
            try:
                self._poll_subscription(subscription, cookie_header)
            except CookieInvalidError as exc:
                logger.warning("bilibili cookie invalid during up dynamics poll: %s", exc)
                with self._lock:
                    self._cookie_missing = True
                return
            except RateLimitedError as exc:
                logger.warning("bilibili rate limited during up dynamics poll: %s", exc)
                return
            except UpNotFoundError as exc:
                logger.warning("up subscription target missing: %s", exc)
                self._repository.update_up_subscription(
                    str(subscription["subscription_id"]),
                    last_error="UP 主不存在或已注销",
                )
            except UpDynamicsError as exc:
                logger.warning("up dynamics poll failed for mid=%s: %s", subscription.get("mid"), exc)
                self._record_subscription_failure(subscription, str(exc))
            except Exception as exc:  # noqa: BLE001 - 单 UP 失败不应中断整轮
                logger.exception("up dynamics poll crashed for mid=%s", subscription.get("mid"))
                self._record_subscription_failure(subscription, str(exc))

        self._sync_task_statuses()
        self._compensate_pending_detections(cookie_header)

    def _poll_subscription(self, subscription: dict[str, Any], cookie_header: str) -> None:
        subscription_id = str(subscription["subscription_id"])
        mid = str(subscription["mid"])
        items = bilibili_wbi.fetch_up_videos(mid, cookie_header)
        if not items:
            self._repository.update_up_subscription(
                subscription_id,
                last_checked_at=datetime.now(timezone.utc).isoformat(),
                last_error=None,
                consecutive_failures=0,
            )
            return

        newest = max(items, key=lambda item: item.pubdate)
        last_pubdate = subscription.get("last_video_pubdate")
        if last_pubdate is None:
            # 首次订阅：不回灌历史，只建立增量游标。
            self._repository.update_up_subscription(
                subscription_id,
                last_checked_at=datetime.now(timezone.utc).isoformat(),
                last_video_bvid=newest.bvid,
                last_video_pubdate=newest.pubdate,
                last_error=None,
                consecutive_failures=0,
            )
            return

        fresh = [item for item in items if item.pubdate > int(last_pubdate)]
        # 按发布时间正序处理，保证任务提交顺序与时间线一致。
        for item in sorted(fresh, key=lambda entry: entry.pubdate):
            if self._stop.is_set():
                return
            self._ingest_new_video(subscription_id, item)

        self._repository.update_up_subscription(
            subscription_id,
            last_checked_at=datetime.now(timezone.utc).isoformat(),
            last_video_bvid=newest.bvid,
            last_video_pubdate=newest.pubdate,
            last_error=None,
            consecutive_failures=0,
        )

    def _ingest_new_video(self, subscription_id: str, item: UpVideoItem) -> None:
        detection_id, inserted = self._repository.insert_up_detected_video(
            subscription_id,
            item.bvid,
            aid=item.aid,
            title=item.title,
            cover_url=item.cover_url,
            duration=item.duration,
            pubdate=item.pubdate,
            description=item.description,
        )
        if not inserted:
            return
        asset = self._ensure_asset(item)
        task_id = self._submit_summary_task(asset, item)
        self._repository.update_up_detected_video(
            detection_id,
            video_id=asset.video_id,
            task_id=task_id,
            task_status="queued",
            detection_status="task_submitted" if task_id else "ingested",
        )

    def _ensure_asset(self, item: UpVideoItem) -> VideoAssetRecord:
        existing = self._repository.get_video_asset_by_canonical_id(item.bvid)
        if existing is not None:
            return existing
        asset = VideoAssetRecord(
            canonical_id=item.bvid,
            platform="bilibili",
            title=item.title,
            source_url=f"https://www.bilibili.com/video/{item.bvid}/",
            cover_url=item.cover_url,
            duration=float(item.duration),
            is_global_visible=True,
        )
        return self._repository.upsert_video_asset(asset)

    def _submit_summary_task(
        self,
        asset: VideoAssetRecord,
        item: UpVideoItem,
        *,
        use_offpeak_default: bool = True,
    ) -> str | None:
        settings = self._settings_manager.current
        schedule = "offpeak" if (
            use_offpeak_default and bool(getattr(settings, "offpeak_schedule_default", False))
        ) else "immediate"
        record = TaskRecord(
            task_input=TaskInput(
                input_type=InputType.URL,
                source=f"https://www.bilibili.com/video/{item.bvid}/",
                title=item.title,
                platform_hint="bilibili",
                options=TaskOptions(schedule=schedule),
            ),
            video_id=asset.video_id,
            page_title=item.title,
        )
        record = self._repository.create_task_record(record)
        try:
            submit_task_or_queue(self._app_state, self._repository, record)
        except Exception as exc:  # noqa: BLE001 - 派发失败保留 queued 状态，启动恢复可重试
            logger.warning("auto submit summary task failed for %s: %s", item.bvid, exc)
            return None
        return record.task_id

    # ------------------------------------------------------------------
    # 补偿与状态同步
    # ------------------------------------------------------------------

    def _sync_task_statuses(self) -> None:
        for detection in self._repository.list_up_detections_pending_task_status():
            task_id = str(detection.get("task_id") or "")
            task = self._repository.get_task(task_id) if task_id else None
            if task is None:
                continue
            status = str(task.status.value if hasattr(task.status, "value") else task.status)
            if status in _TASK_TERMINAL_STATUSES:
                self._repository.update_up_detected_video(
                    str(detection["detection_id"]),
                    task_status=status,
                    detection_status="task_completed" if status == "completed" else f"task_{status}",
                )

    def _compensate_pending_detections(self, cookie_header: str) -> None:
        """崩溃补偿：已检出但未建任务的记录补提交（at-least-once）。"""
        for detection in self._repository.list_up_detections_missing_task(limit=100):
            if self._stop.is_set():
                return
            bvid = str(detection.get("bvid") or "")
            if not bvid:
                continue
            try:
                asset = None
                if detection.get("video_id"):
                    asset = self._repository.get_video_asset(str(detection["video_id"]))
                if asset is None:
                    asset = self._repository.get_video_asset_by_canonical_id(bvid)
                if asset is None:
                    subscription = self._repository.get_up_subscription(
                        str(detection.get("subscription_id") or "")
                    )
                    mid = str(subscription.get("mid") or "")
                    if not mid:
                        continue
                    items = bilibili_wbi.fetch_up_videos(mid, cookie_header)
                    item = next((entry for entry in items if entry.bvid == bvid), None)
                    if item is None:
                        continue
                    asset = self._ensure_asset(item)
                task_id = self._submit_summary_task(
                    asset,
                    UpVideoItem(
                        bvid=bvid,
                        aid=detection.get("aid"),
                        title=str(detection.get("title") or asset.title),
                        cover_url=str(detection.get("cover_url") or ""),
                        duration=int(detection.get("duration") or 0),
                        pubdate=int(detection.get("pubdate") or 0),
                        description=str(detection.get("description") or ""),
                    ),
                )
                if task_id:
                    self._repository.update_up_detected_video(
                        str(detection["detection_id"]),
                        video_id=asset.video_id,
                        task_id=task_id,
                        task_status="queued",
                        detection_status="task_submitted",
                    )
            except Exception as exc:  # noqa: BLE001 - 补偿失败下轮重试
                logger.warning("compensate detection %s failed: %s", detection.get("detection_id"), exc)

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _record_subscription_failure(self, subscription: dict[str, Any], error: str) -> None:
        failures = int(subscription.get("consecutive_failures") or 0) + 1
        fields: dict[str, Any] = {
            "last_error": error[:500],
            "consecutive_failures": failures,
        }
        if failures >= MAX_CONSECUTIVE_FAILURES:
            fields["enabled"] = 0
            fields["last_error"] = (error[:400] + "；连续失败已自动停用，请检查后重新启用。")[:500]
        self._repository.update_up_subscription(str(subscription["subscription_id"]), **fields)
