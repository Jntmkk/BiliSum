import { type FormEvent, type KeyboardEvent, type PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from "react";

import type { ConfigHealth, UpdateState } from "../appModel";
import type { FeedbackCategory } from "../api";
import type { WorkerQueueItem, WorkerQueueSnapshot, WorkerSnapshot } from "../types";

const FEEDBACK_CATEGORY_OPTIONS: Array<{ value: FeedbackCategory; label: string }> = [
  { value: "bug", label: "问题反馈" },
  { value: "feature", label: "功能建议" },
  { value: "question", label: "使用疑问" },
  { value: "other", label: "其他" },
];

function feedbackIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2.5 3.75C2.5 3.06 3.06 2.5 3.75 2.5h8.5c.69 0 1.25.56 1.25 1.25v6.5c0 .69-.56 1.25-1.25 1.25H6l-2.6 2.21c-.4.34-1.02.05-1.02-.47V3.75Z" />
      <path d="M5.25 5.5h5.5M5.25 8h3.5" />
    </svg>
  );
}

type QueueStatusView = {
  completed: number;
  total: number;
  running: number;
  pending: number;
  concurrency: number;
  isParallel: boolean;
  tokenConsumed: number | null;
  runtimeSeconds: number | null;
  isActive: boolean;
  isCompleted: boolean;
  completionVisible: boolean;
  runningItems: WorkerQueueItem[];
  pendingItems: WorkerQueueItem[];
  completedItems: WorkerQueueItem[];
};

function firstNumber(...values: Array<number | null | undefined>): number | null {
  return values.find((value) => typeof value === "number" && Number.isFinite(value)) ?? null;
}

function queueSnapshot(worker: WorkerSnapshot | null | undefined): QueueStatusView {
  const taskQueue: WorkerQueueSnapshot = worker?.queues?.transcription ?? worker?.queues?.task ?? worker?.task ?? {};
  const batch = worker?.batch ?? worker?.active_batch ?? null;
  const completion = worker?.completion ?? (batch?.state === "completed" || batch?.state === "done" ? batch : null);
  const completed = firstNumber(
    batch?.completed_tasks,
    batch?.completed,
    worker?.completed_tasks,
    worker?.completed,
    taskQueue.completed_tasks,
    taskQueue.completed,
  ) ?? 0;
  const pending = firstNumber(batch?.pending_tasks, batch?.remaining, taskQueue.pending) ?? 0;
  const running = firstNumber(batch?.running_tasks, batch?.running, taskQueue.running) ?? 0;
  const explicitTotal = firstNumber(
    batch?.total_tasks,
    batch?.total,
    worker?.total_tasks,
    worker?.total,
    taskQueue.total_tasks,
    taskQueue.total,
  );
  const total = Math.max(0, explicitTotal ?? (completed + pending + running));
  const concurrency = Math.max(1, firstNumber(batch?.concurrency, taskQueue.concurrency) ?? 1);
  const mode = batch?.mode ?? batch?.concurrency_mode ?? worker?.mode ?? worker?.concurrency_mode;
  const isParallel = mode === "parallel" || mode === "concurrent" || (mode !== "serial" && concurrency > 1);
  const isActive = Boolean(worker?.has_active_tasks) || running > 0 || pending > 0 || (total > completed && total > 0);
  const completionVisible = Boolean(completion?.visible) || completion?.state === "completed" || completion?.state === "done";
  const isCompleted = completionVisible || (!isActive && total > 0 && completed >= total);
  const startedAt = batch?.started_at ?? taskQueue.started_at;
  const elapsedFromStart = startedAt ? Math.max(0, (Date.now() - new Date(startedAt).getTime()) / 1000) : null;

  return {
    completed,
    total,
    running,
    pending,
    concurrency,
    isParallel,
    tokenConsumed: firstNumber(batch?.total_tokens, batch?.token_consumed, worker?.total_tokens, worker?.token_consumed, taskQueue.total_tokens, taskQueue.token_consumed),
    runtimeSeconds: firstNumber(batch?.runtime_seconds, worker?.runtime_seconds, worker?.runtime, taskQueue.runtime_seconds) ?? elapsedFromStart,
    isActive,
    isCompleted,
    completionVisible,
    runningItems: batch?.items?.filter((item) => item.status === "running") ?? taskQueue.items?.filter((item) => item.status === "running") ?? [],
    pendingItems: batch?.items?.filter((item) => item.status === "queued" || item.status === "pending") ?? taskQueue.items?.filter((item) => item.status === "queued" || item.status === "pending") ?? [],
    completedItems: batch?.items?.filter((item) => ["completed", "done", "failed", "cancelled"].includes(item.status || "")) ?? taskQueue.items?.filter((item) => ["completed", "done", "failed", "cancelled"].includes(item.status || "")) ?? [],
  };
}

function formatTokenCount(value: number | null): string {
  if (value === null) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}m`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 100_000 ? 0 : 1)}k`;
  return Math.round(value).toLocaleString("zh-CN");
}

function formatRuntime(value: number | null): string {
  if (value === null) return "—";
  const totalSeconds = Math.max(0, Math.round(value));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function queueIcon() {
  return (
    <svg className="title-bar-queue-icon" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M4 4.25h8M4 8h8M4 11.75h5" />
      <circle cx="2" cy="4.25" r=".7" />
      <circle cx="2" cy="8" r=".7" />
      <circle cx="2" cy="11.75" r=".7" />
    </svg>
  );
}

export function TitleBar({
  darkMode,
  onToggleTheme,
  serviceOnline,
  backendRunning,
  runtimeDeviceLabel,
  runtimeReady,
  runtimeStatusText,
  version,
  updateState,
  configHealth,
  worker,
  onOpenSettings,
  onOpenUpdateDialog,
  onSubmitFeedback,
}: {
  darkMode: boolean;
  onToggleTheme(): void;
  serviceOnline: boolean;
  backendRunning?: boolean;
  runtimeDeviceLabel: string;
  runtimeReady: boolean;
  runtimeStatusText: string;
  version: string;
  updateState: UpdateState;
  configHealth: ConfigHealth;
  worker?: WorkerSnapshot | null;
  onOpenSettings(issueKey?: string): void;
  onOpenUpdateDialog(): void;
  onSubmitFeedback(input: { category: FeedbackCategory; description: string }): Promise<{ issueUrl: string }>;
}) {
  const [isMaximized, setIsMaximized] = useState(false);
  const [statusPopoverOpen, setStatusPopoverOpen] = useState(false);
  const [queuePopoverOpen, setQueuePopoverOpen] = useState(false);
  const [queuePage, setQueuePage] = useState<0 | 1>(0);
  const [completionDisplay, setCompletionDisplay] = useState<{ completed: number; total: number } | null>(null);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [feedbackCategory, setFeedbackCategory] = useState<FeedbackCategory>("bug");
  const [feedbackDescription, setFeedbackDescription] = useState("");
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false);
  const [feedbackIssueUrl, setFeedbackIssueUrl] = useState("");
  const [feedbackError, setFeedbackError] = useState("");
  const statusPopoverRef = useRef<HTMLDivElement | null>(null);
  const queuePopoverRef = useRef<HTMLDivElement | null>(null);
  const feedbackPopoverRef = useRef<HTMLDivElement | null>(null);
  const completionTimerRef = useRef<number | null>(null);
  const queueWasActiveRef = useRef(false);
  const queueView = useMemo(() => queueSnapshot(worker), [worker]);
  const isDesktopWindowControlsAvailable = Boolean(window.desktop?.window);
  const isMacOS = window.desktop?.window?.platform === "darwin";

  useEffect(() => {
    async function checkMaximized() {
      if (window.desktop) {
        const maximized = await window.desktop.window.isMaximized();
        setIsMaximized(maximized);
      }
    }
    void checkMaximized();
  }, []);

  useEffect(() => {
    function handlePointerDown(event: MouseEvent) {
      const target = event.target as Node;
      if (!statusPopoverRef.current?.contains(target)) {
        setStatusPopoverOpen(false);
      }
      if (!queuePopoverRef.current?.contains(target)) {
        setQueuePopoverOpen(false);
      }
      if (!feedbackPopoverRef.current?.contains(target)) {
        setFeedbackOpen(false);
      }
    }

    window.addEventListener("mousedown", handlePointerDown);
    return () => window.removeEventListener("mousedown", handlePointerDown);
  }, []);

  useEffect(() => {
    if (completionTimerRef.current !== null) {
      window.clearTimeout(completionTimerRef.current);
      completionTimerRef.current = null;
    }
    if (queueView.isActive) {
      if (!queueWasActiveRef.current) {
        setQueuePage(0);
      }
      queueWasActiveRef.current = true;
      setCompletionDisplay(null);
      return;
    }
    if (queueView.isCompleted && (queueWasActiveRef.current || queueView.completionVisible)) {
      setQueuePopoverOpen(false);
      setCompletionDisplay({ completed: queueView.completed, total: queueView.total });
      queueWasActiveRef.current = false;
      completionTimerRef.current = window.setTimeout(() => {
        setCompletionDisplay(null);
        completionTimerRef.current = null;
      }, 30_000);
    }
  }, [queueView.completed, queueView.completionVisible, queueView.isActive, queueView.isCompleted, queueView.total]);

  useEffect(() => () => {
    if (completionTimerRef.current !== null) {
      window.clearTimeout(completionTimerRef.current);
    }
  }, []);

  function handleStatusPopoverKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Escape") {
      return;
    }
    setStatusPopoverOpen(false);
    setQueuePopoverOpen(false);
    setFeedbackOpen(false);
  }

  const handleMaximize = async () => {
    if (window.desktop) {
      await window.desktop.window.maximize();
      const maximized = await window.desktop.window.isMaximized();
      setIsMaximized(maximized);
    }
  };

  const handleMinimize = async () => {
    if (window.desktop) {
      await window.desktop.window.minimize();
    }
  };

  const handleClose = async () => {
    if (window.desktop) {
      await window.desktop.window.close();
    }
  };

  const serviceStatusText = serviceOnline ? "在线" : backendRunning ? "启动中" : "离线";
  const hasNewVersion = ["available", "downloading", "downloaded", "installing"].includes(updateState.status);
  const hasConfigProblem = configHealth.checked && !configHealth.isConfigured;
  const runtimePending = serviceOnline && !runtimeReady;
  const statusPillText = hasConfigProblem ? "配置缺失" : hasNewVersion ? "有新版本" : runtimePending ? "运行环境准备中" : "运行状态";
  const runtimeEnvironmentText = runtimeDeviceLabel && runtimeDeviceLabel !== "-"
    ? `${runtimeStatusText} · ${runtimeDeviceLabel}`
    : runtimeStatusText;
  const versionStatusText = hasNewVersion && updateState.version ? updateState.version : version || "-";
  const configStatusText = !configHealth.checked
    ? "检测中"
    : configHealth.hasBlockingIssues
      ? "需立即补全"
      : configHealth.isConfigured
        ? "已就绪"
        : "建议补全";

  const queueVisible = queueView.isActive || completionDisplay !== null;
  const queueCount = completionDisplay
    ? `${completionDisplay.completed}/${completionDisplay.total}`
    : `${queueView.completed}/${queueView.total}`;
  const queueModeLabel = queueView.isParallel ? `并发 · ${queueView.running} 个运行中` : `非并发 · ${queueView.running} 个运行中`;

  function renderQueueTask(item: WorkerQueueItem, fallbackStatus: string) {
    const status = String(item.status || "").toLowerCase();
    const isFailed = status === "failed" || status === "cancelled" || status === "error";
    const isCompleted = status === "completed" || status === "done";
    const progress = isFailed ? 0 : isCompleted ? 100 : Math.max(0, Math.min(100, Math.round(item.progress ?? 0)));
    const statusClass = isFailed ? " is-failed" : isCompleted ? " is-completed" : "";
    return (
      <div className={`title-bar-queue-task${statusClass}`} key={item.task_id ?? `${item.title ?? fallbackStatus}-${progress}`}>
        <div className="title-bar-queue-task-top">
          <span>{item.title || fallbackStatus}</span>
          <span>{progress}%</span>
        </div>
        <div className="title-bar-queue-progress" aria-hidden="true"><i style={{ width: `${progress}%` }} /></div>
      </div>
    );
  }

  function handleQueuePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const target = event.currentTarget;
    target.setPointerCapture(event.pointerId);
    target.dataset.queueStartX = String(event.clientX);
    target.dataset.queueStartPage = String(queuePage);
  }

  function handleQueuePointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    const target = event.currentTarget;
    const startX = Number(target.dataset.queueStartX);
    const startPage = Number(target.dataset.queueStartPage);
    delete target.dataset.queueStartX;
    delete target.dataset.queueStartPage;
    if (!Number.isFinite(startX) || !Number.isFinite(startPage)) return;
    if (Math.abs(event.clientX - startX) < 28) return;
    setQueuePage(event.clientX < startX ? 1 : 0);
  }

  function handleQueuePointerCancel(event: ReactPointerEvent<HTMLDivElement>) {
    delete event.currentTarget.dataset.queueStartX;
    delete event.currentTarget.dataset.queueStartPage;
  }

  function handleOpenUpdateDialog() {
    setStatusPopoverOpen(false);
    onOpenUpdateDialog();
  }

  function toggleQueuePopover() {
    setStatusPopoverOpen(false);
    setQueuePopoverOpen((current) => !current);
  }

  function toggleStatusPopover() {
    setQueuePopoverOpen(false);
    setFeedbackOpen(false);
    setStatusPopoverOpen((current) => !current);
  }

  function toggleFeedbackPopover() {
    setStatusPopoverOpen(false);
    setQueuePopoverOpen(false);
    setFeedbackOpen((current) => {
      if (current) {
        return false;
      }
      setFeedbackError("");
      setFeedbackIssueUrl("");
      return true;
    });
  }

  async function handleFeedbackSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const description = feedbackDescription.trim();
    if (description.length < 5) {
      setFeedbackError("请至少填写 5 个字符的问题描述。");
      return;
    }
    setFeedbackSubmitting(true);
    setFeedbackError("");
    try {
      const result = await onSubmitFeedback({ category: feedbackCategory, description });
      setFeedbackIssueUrl(result.issueUrl);
    } catch (error) {
      setFeedbackError(error instanceof Error ? error.message : "提交失败，请稍后重试。");
    } finally {
      setFeedbackSubmitting(false);
    }
  }

  return (
    <div className="title-bar">
      <div className="title-bar-traffic-light-spacer" />
      <div className="title-bar-sidebar-brand">
        <div className="title-bar-brand-mark">
          <img src="/static/assets/icons/icon.svg" alt="" />
        </div>
        <span className="title-bar-brand-text">BiliSum</span>
        {version && version !== "-" ? (
          <span className="title-bar-version" title={`部署版本 ${version}`}>v{version}</span>
        ) : null}
      </div>
      <div className="title-bar-drag-region" />
      <div className="title-bar-controls">
        {queueVisible ? (
          <div
            className={`title-bar-queue-wrap ${queuePopoverOpen ? "is-open" : ""}`}
            ref={queuePopoverRef}
          >
            {completionDisplay ? (
              <div className="title-bar-queue-completion" role="status" aria-label="队列已完成">
                <svg className="title-bar-queue-completion-icon" viewBox="0 0 16 16" aria-hidden="true">
                  <circle cx="8" cy="8" r="7" fill="currentColor" />
                  <path d="m4.65 8.05 2.05 2.05 4.7-4.55" fill="none" stroke="var(--bg-card)" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <strong>{queueCount}</strong>
                <span className="title-bar-queue-completion-label">已完成</span>
              </div>
            ) : (
              <button
                className="title-bar-queue-trigger"
                type="button"
                onClick={toggleQueuePopover}
                aria-label="展开目前队列"
                aria-expanded={queuePopoverOpen}
                aria-haspopup="dialog"
                title="目前队列"
              >
                {queueIcon()}
                <strong>{queueCount}</strong>
                <span>目前队列</span>
              </button>
            )}
            {queuePopoverOpen && !completionDisplay ? (
              <div className="title-bar-queue-popover" role="dialog" aria-label="目前队列详情">
                <div className="title-bar-queue-popover-head">
                  <strong>目前队列</strong>
                  <span>{queueModeLabel}</span>
                </div>
                <div
                  className="title-bar-queue-carousel"
                  onPointerDown={handleQueuePointerDown}
                  onPointerUp={handleQueuePointerUp}
                  onPointerCancel={handleQueuePointerCancel}
                  onClick={(event) => event.stopPropagation()}
                >
                  <div className="title-bar-queue-carousel-viewport">
                    <div
                      className="title-bar-queue-carousel-track"
                      style={{ transform: `translate3d(-${queuePage * 50}%, 0, 0)` }}
                    >
                      <section className="title-bar-queue-page" aria-label="队列概览">
                        <div className="title-bar-queue-metrics">
                          <div className="title-bar-queue-metric">
                            <span>已完成/总任务</span>
                            <strong>{queueCount}</strong>
                            <small>本轮累计</small>
                          </div>
                          <div className="title-bar-queue-metric">
                            <span>目前运行</span>
                            <strong>{queueView.running}</strong>
                            <small>{queueView.isParallel ? "并发任务" : "非并发任务"}</small>
                          </div>
                          <div className="title-bar-queue-metric">
                            <span>剩下队列</span>
                            <strong>{queueView.pending}</strong>
                            <small>等待处理</small>
                          </div>
                        </div>
                      </section>
                      <section className="title-bar-queue-page" aria-label="Token 与运行时间">
                        <div className="title-bar-queue-resources">
                          <div className="title-bar-queue-resource">
                            <span>Token 消耗</span>
                            <strong>{formatTokenCount(queueView.tokenConsumed)}</strong>
                            <small>本轮累计</small>
                          </div>
                          <div className="title-bar-queue-resource">
                            <span>运行时间</span>
                            <strong>{formatRuntime(queueView.runtimeSeconds)}</strong>
                            <small>当前批次</small>
                          </div>
                        </div>
                      </section>
                    </div>
                  </div>
                  <div className="title-bar-queue-page-nav" role="group" aria-label="队列详情分页">
                    {[0, 1].map((page) => (
                      <button
                        className={queuePage === page ? "is-active" : ""}
                        key={page}
                        type="button"
                        onPointerDown={(event) => event.stopPropagation()}
                        onClick={(event) => {
                          event.stopPropagation();
                          setQueuePage(page as 0 | 1);
                        }}
                        aria-label={page === 0 ? "查看队列概览" : "查看 Token 与运行时间"}
                        aria-current={queuePage === page ? "page" : undefined}
                      />
                    ))}
                  </div>
                </div>
                <div className="title-bar-queue-section">
                  <div className="title-bar-queue-section-head"><span>目前运行</span><span>{queueView.running} 个{queueView.isParallel ? "并发" : ""}任务</span></div>
                  {queueView.runningItems.length > 0 ? queueView.runningItems.map((item) => renderQueueTask(item, "处理中")) : <p>当前运行 {queueView.running} 个任务。</p>}
                </div>
                <div className="title-bar-queue-section">
                  <div className="title-bar-queue-section-head"><span>剩下队列</span><span>{queueView.pending} 个任务</span></div>
                  {queueView.pendingItems.length > 0 ? queueView.pendingItems.map((item) => renderQueueTask(item, "等待处理")) : <p>等待队列为空。</p>}
                </div>
                <div className="title-bar-queue-section">
                  <div className="title-bar-queue-section-head"><span>已完成任务</span><span>{queueView.completed} 个任务</span></div>
                  {queueView.completedItems.length > 0 ? queueView.completedItems.map((item) => renderQueueTask(item, "已完成")) : <p>本轮已完成 {queueView.completed} 个任务。</p>}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
        <div
          className={`title-bar-status-wrap ${statusPopoverOpen ? "is-open" : ""}`}
          ref={statusPopoverRef}
          onKeyDown={handleStatusPopoverKeyDown}
        >
          <button
            className={`title-bar-status-pill ${
              hasConfigProblem ? "is-danger" : hasNewVersion ? "is-update" : serviceOnline ? (runtimePending ? "is-pending" : "is-success") : ""
            }`}
            type="button"
            onClick={toggleStatusPopover}
            aria-label="查看运行状态"
            aria-expanded={statusPopoverOpen}
            aria-haspopup="dialog"
            title="运行状态"
          >
            <span
              className={`title-bar-status-dot ${
                hasConfigProblem ? "is-danger" : hasNewVersion ? "is-update" : serviceOnline ? (runtimePending ? "is-pending" : "is-success") : backendRunning ? "is-pending" : ""
              }`}
            />
            <span>{statusPillText}</span>
          </button>

          <div
            className={`title-bar-status-popover ${statusPopoverOpen ? "is-visible" : ""}`}
            role="dialog"
            aria-label="运行状态详情"
          >
            <div className="title-bar-status-header">
              <h2>运行状态</h2>
            </div>
            <div className="title-bar-status-stack">
              <div className={`sidebar-status-item ${serviceOnline ? "is-success" : ""}`}>
                <span>服务</span>
                <strong>{serviceStatusText}</strong>
              </div>
              <div className={`sidebar-status-item ${runtimeReady ? "is-success" : serviceOnline ? "is-warning" : ""}`}>
                <span>运行环境</span>
                <strong>{runtimeEnvironmentText}</strong>
              </div>
              <div className={`sidebar-status-item ${configHealth.hasBlockingIssues ? "is-danger" : !configHealth.isConfigured ? "is-warning" : "is-success"}`}>
                <span>配置</span>
                <strong>{configStatusText}</strong>
              </div>
              <button
                className={`sidebar-status-item sidebar-status-item-button ${hasNewVersion ? "is-update" : ""}`}
                type="button"
                onClick={handleOpenUpdateDialog}
              >
                <span>版本</span>
                <strong>{versionStatusText}</strong>
              </button>
            </div>
            {hasConfigProblem ? (
              <div className="title-bar-status-actions">
                <p>{configHealth.summary}</p>
                <button
                  className="secondary-button title-bar-status-action"
                  type="button"
                  onClick={() => {
                    setStatusPopoverOpen(false);
                    onOpenSettings(configHealth.blockingIssues[0]?.key || configHealth.issues[0]?.key);
                  }}
                >
                  {configHealth.actionText}
                </button>
              </div>
            ) : null}
          </div>
        </div>
        <div
          className={`title-bar-feedback-wrap ${feedbackOpen ? "is-open" : ""}`}
          ref={feedbackPopoverRef}
        >
          <button
            className="title-bar-button"
            type="button"
            onClick={toggleFeedbackPopover}
            aria-label="反馈问题"
            aria-expanded={feedbackOpen}
            aria-haspopup="dialog"
            title="反馈问题"
          >
            {feedbackIcon()}
          </button>
          <div
            className={`title-bar-feedback-popover ${feedbackOpen ? "is-visible" : ""}`}
            role="dialog"
            aria-label="反馈问题"
          >
            {feedbackIssueUrl ? (
              <div className="title-bar-feedback-success">
                <p>已提交，感谢反馈！</p>
                <a href={feedbackIssueUrl} target="_blank" rel="noreferrer noopener">在 GitHub 上查看进展</a>
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => {
                    setFeedbackIssueUrl("");
                    setFeedbackDescription("");
                    setFeedbackCategory("bug");
                  }}
                >
                  继续反馈
                </button>
              </div>
            ) : (
              <form className="title-bar-feedback-form" onSubmit={handleFeedbackSubmit}>
                <label className="title-bar-feedback-field">
                  <span>反馈类型</span>
                  <select
                    className="select-field"
                    value={feedbackCategory}
                    onChange={(event) => setFeedbackCategory(event.target.value as FeedbackCategory)}
                  >
                    {FEEDBACK_CATEGORY_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </label>
                <label className="title-bar-feedback-field">
                  <span>问题描述</span>
                  <textarea
                    className="textarea-field"
                    value={feedbackDescription}
                    rows={4}
                    maxLength={5000}
                    placeholder="描述你遇到的问题…"
                    onChange={(event) => setFeedbackDescription(event.target.value)}
                  />
                </label>
                {feedbackError ? <p className="title-bar-feedback-error">{feedbackError}</p> : null}
                <button className="primary-button" type="submit" disabled={feedbackSubmitting}>
                  {feedbackSubmitting ? "提交中…" : "提交反馈"}
                </button>
                <p className="title-bar-feedback-note">提交后将自动附带当前页面、端类型与版本等环境信息。</p>
              </form>
            )}
          </div>
        </div>
        <button
          className="title-bar-button"
          type="button"
          onClick={onToggleTheme}
          aria-label={darkMode ? "切换到浅色模式" : "切换到深色模式"}
          title={darkMode ? "浅色模式" : "深色模式"}
        >
          {darkMode ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2.5v2.25M12 19.25v2.25M4.75 12H2.5M21.5 12h-2.25M5.9 5.9 4.3 4.3M19.7 19.7l-1.6-1.6M18.1 5.9l1.6-1.6M4.3 19.7l1.6-1.6" />
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 15.5A8.5 8.5 0 1 1 12.5 4a6.5 6.5 0 0 0 7.5 11.5Z" />
            </svg>
          )}
        </button>
        {isDesktopWindowControlsAvailable && !isMacOS ? (
          <>
            <button
              className="title-bar-button"
              type="button"
              onClick={handleMinimize}
              aria-label="最小化"
            >
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M2 6H10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </button>
            <button
              className="title-bar-button"
              type="button"
              onClick={handleMaximize}
              aria-label={isMaximized ? "还原" : "最大化"}
            >
              {isMaximized ? (
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <rect x="1.5" y="3.5" width="7" height="7" stroke="currentColor" strokeWidth="1.5" />
                  <path d="M3.5 3.5V1.5H9.5V3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              ) : (
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <rect x="1.5" y="1.5" width="9" height="9" stroke="currentColor" strokeWidth="1.5" />
                </svg>
              )}
            </button>
            <button
              className="title-bar-button close"
              type="button"
              onClick={handleClose}
              aria-label="关闭"
            >
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M2 2L10 10M10 2L2 10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </button>
          </>
        ) : null}
      </div>
    </div>
  );
}
