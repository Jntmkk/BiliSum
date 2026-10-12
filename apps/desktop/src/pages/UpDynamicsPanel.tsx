import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api";
import { ExternalLinkIcon, RefreshIcon, TrashIcon } from "../components/AppIcons";
import type { UpDetectedVideo, UpDynamicsStatus, UpSubscription } from "../types";
import { formatDuration } from "../utils";

const FEED_PAGE_SIZE = 20;
const FEED_REFRESH_INTERVAL_MS = 60_000;

function formatRelativeTime(pubdate: number): string {
  if (!pubdate) {
    return "-";
  }
  const diffSeconds = Date.now() / 1000 - pubdate;
  if (diffSeconds < 60) return "刚刚";
  if (diffSeconds < 3600) return `${Math.floor(diffSeconds / 60)} 分钟前`;
  if (diffSeconds < 86400) return `${Math.floor(diffSeconds / 3600)} 小时前`;
  if (diffSeconds < 86400 * 30) return `${Math.floor(diffSeconds / 86400)} 天前`;
  const date = new Date(pubdate * 1000);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

const TASK_BADGE_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "总结中",
  waiting_offpeak: "等待低峰期",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

function taskBadgeClass(taskStatus: string | null): string {
  if (!taskStatus) return "is-pending";
  if (taskStatus === "completed") return "is-completed";
  if (taskStatus === "failed" || taskStatus === "cancelled") return "is-failed";
  return "is-running";
}

const BILIBILI_IMAGE_HOST_PATTERN = /(^|\.)((hdslb|bilivideo|biliimg|acgvideo)\.com)$/i;

function proxiedImageUrl(url: string): string {
  if (!url) {
    return url;
  }
  let host = "";
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    return url;
  }
  if (!BILIBILI_IMAGE_HOST_PATTERN.test(host)) {
    return url;
  }
  return `/api/v1/dynamics/image-proxy?url=${encodeURIComponent(url)}`;
}

type UpDynamicsPanelProps = {
  active: boolean;
  onUnreadChange(count: number): void;
};

export function UpDynamicsPanel({ active, onUnreadChange }: UpDynamicsPanelProps) {
  const navigate = useNavigate();
  const [status, setStatus] = useState<UpDynamicsStatus | null>(null);
  const [subscriptions, setSubscriptions] = useState<UpSubscription[]>([]);
  const [feedItems, setFeedItems] = useState<UpDetectedVideo[]>([]);
  const [feedTotal, setFeedTotal] = useState(0);
  const [feedLoaded, setFeedLoaded] = useState(false);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [filterSubscriptionId, setFilterSubscriptionId] = useState<string | null>(null);
  const [addQuery, setAddQuery] = useState("");
  const [addBusy, setAddBusy] = useState(false);
  const [notice, setNotice] = useState<{ text: string; tone: "info" | "error" } | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [busyDetectionId, setBusyDetectionId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const feedPageRef = useRef(1);

  const subscriptionById = useMemo(
    () => new Map(subscriptions.map((subscription) => [subscription.subscription_id, subscription])),
    [subscriptions],
  );

  const showNotice = useCallback((text: string, tone: "info" | "error" = "info") => {
    setNotice({ text, tone });
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await api.getUpDynamicsStatus());
    } catch {
      /* 服务未启动时静默 */
    }
  }, []);

  const loadSubscriptions = useCallback(async () => {
    try {
      setSubscriptions(await api.listUpSubscriptions());
    } catch {
      /* 服务未启动时静默 */
    }
  }, []);

  const loadUnread = useCallback(async () => {
    try {
      const result = await api.getUpDynamicsUnreadCount();
      onUnreadChange(result.unread_count);
    } catch {
      /* 服务未启动时静默 */
    }
  }, [onUnreadChange]);

  const loadFeed = useCallback(
    async (page: number, append: boolean) => {
      try {
        const feed = await api.getUpDynamicsFeed({
          page,
          page_size: FEED_PAGE_SIZE,
          unread_only: unreadOnly || undefined,
          subscription_id: filterSubscriptionId || undefined,
        });
        setFeedItems((current) => (append ? [...current, ...feed.items] : feed.items));
        setFeedTotal(feed.total);
        onUnreadChange(feed.unread_count);
        return feed.items.length;
      } catch {
        /* 服务未启动时静默 */
        return 0;
      } finally {
        setFeedLoaded(true);
      }
    },
    [unreadOnly, filterSubscriptionId, onUnreadChange],
  );

  useEffect(() => {
    if (!active) {
      return;
    }
    void loadStatus();
    void loadSubscriptions();
    feedPageRef.current = 1;
    void loadFeed(1, false);
    const timer = window.setInterval(() => {
      feedPageRef.current = 1;
      void loadFeed(1, false);
      void loadUnread();
    }, FEED_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [active, loadFeed, loadStatus, loadSubscriptions, loadUnread]);

  const submitAdd = async () => {
    const query = addQuery.trim();
    if (!query || addBusy) {
      return;
    }
    setAddBusy(true);
    setNotice(null);
    try {
      const created = await api.createUpSubscription(query);
      setAddQuery("");
      showNotice(`已订阅 ${created.up_name || created.mid}。`);
      await loadSubscriptions();
      await loadStatus();
      feedPageRef.current = 1;
      await loadFeed(1, false);
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "订阅失败，请检查输入或登录态。", "error");
    } finally {
      setAddBusy(false);
    }
  };

  const toggleSubscription = async (subscription: UpSubscription) => {
    try {
      await api.updateUpSubscription(subscription.subscription_id, { enabled: !subscription.enabled });
      await loadSubscriptions();
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "更新订阅失败。", "error");
    }
  };

  const removeSubscription = async (subscription: UpSubscription) => {
    if (deleteConfirmId !== subscription.subscription_id) {
      setDeleteConfirmId(subscription.subscription_id);
      return;
    }
    setDeleteConfirmId(null);
    try {
      await api.deleteUpSubscription(subscription.subscription_id);
      if (filterSubscriptionId === subscription.subscription_id) {
        setFilterSubscriptionId(null);
      }
      showNotice(`已取消订阅 ${subscription.up_name || subscription.mid}。`);
      await loadSubscriptions();
      await loadUnread();
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "删除订阅失败。", "error");
    }
  };

  const markOneRead = async (detection: UpDetectedVideo) => {
    try {
      const result = await api.markUpDynamicsRead({ detection_ids: [detection.detection_id] });
      setFeedItems((current) =>
        current.map((item) => (item.detection_id === detection.detection_id ? { ...item, unread: false } : item)),
      );
      onUnreadChange(result.unread_count);
    } catch {
      /* 忽略标记失败 */
    }
  };

  const markAllRead = async () => {
    try {
      const result = await api.markUpDynamicsRead({ mark_all: true });
      setFeedItems((current) => current.map((item) => ({ ...item, unread: false })));
      onUnreadChange(result.unread_count);
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "标记已读失败。", "error");
    }
  };

  const refreshNow = async () => {
    if (refreshing) {
      return;
    }
    setRefreshing(true);
    try {
      await api.refreshUpDynamics();
      window.setTimeout(() => {
        void loadStatus();
        feedPageRef.current = 1;
        void loadFeed(1, false);
      }, 1500);
    } catch {
      /* 忽略刷新失败 */
    } finally {
      window.setTimeout(() => setRefreshing(false), 2000);
    }
  };

  const summarize = async (detection: UpDetectedVideo) => {
    if (busyDetectionId) {
      return;
    }
    setBusyDetectionId(detection.detection_id);
    setNotice(null);
    try {
      const updated = await api.summarizeUpDetection(detection.detection_id);
      setFeedItems((current) =>
        current.map((item) => (item.detection_id === detection.detection_id ? { ...item, ...updated } : item)),
      );
      showNotice("已提交总结任务。");
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "提交总结任务失败。", "error");
    } finally {
      setBusyDetectionId(null);
    }
  };

  const loadMore = async () => {
    if (loadingMore || feedItems.length >= feedTotal) {
      return;
    }
    setLoadingMore(true);
    try {
      const nextPage = feedPageRef.current + 1;
      const fetched = await loadFeed(nextPage, true);
      if (fetched > 0) {
        feedPageRef.current = nextPage;
      }
    } finally {
      setLoadingMore(false);
    }
  };

  const totalUnread = useMemo(
    () => subscriptions.reduce((sum, subscription) => sum + (subscription.unread_count || 0), 0),
    [subscriptions],
  );

  return (
    <div className="up-dynamics-panel">
      {status && !status.cookie_ready ? (
        <div className="up-dynamics-banner is-warning" role="alert">
          <div className="up-dynamics-banner-copy">
            <strong>B 站登录态缺失</strong>
            <span>监听 UP 动态需要 B 站 cookies，请先到设置页登录获取。</span>
          </div>
          <button className="secondary-button" type="button" onClick={() => navigate("/settings")}>
            去登录
          </button>
        </div>
      ) : null}

      {status?.last_round_error ? (
        <div className="up-dynamics-banner is-error" role="alert">
          <div className="up-dynamics-banner-copy">
            <strong>最近一轮监听出错</strong>
            <span>{status.last_round_error}</span>
          </div>
        </div>
      ) : null}

      {status && status.cookie_ready && !status.enabled ? (
        <div className="up-dynamics-banner is-info">
          <div className="up-dynamics-banner-copy">
            <strong>UP 动态监控未开启</strong>
            <span>开启后服务端会按设定间隔自动检查订阅 UP 的新投稿。</span>
          </div>
          <button className="secondary-button" type="button" onClick={() => navigate("/settings")}>
            去设置
          </button>
        </div>
      ) : null}

      <div className="up-dynamics-subscribe-bar">
        <div className="up-dynamics-subscribe-input-row">
          <input
            className="input-field"
            value={addQuery}
            onChange={(event) => setAddQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void submitAdd();
              }
            }}
            placeholder="粘贴 UP 主空间链接或输入 UID，如 https://space.bilibili.com/208259"
          />
          <button className="primary-button" type="button" disabled={addBusy || !addQuery.trim()} onClick={() => void submitAdd()}>
            {addBusy ? "订阅中..." : "添加订阅"}
          </button>
        </div>
        {subscriptions.length ? (
          <div className="up-dynamics-subscription-chips">
            {subscriptions.map((subscription) => {
              const isFiltering = filterSubscriptionId === subscription.subscription_id;
              return (
                <div key={subscription.subscription_id} className={`up-dynamics-chip ${subscription.enabled ? "" : "is-disabled"} ${isFiltering ? "is-filtering" : ""}`}>
                  <button
                    className="up-dynamics-chip-main"
                    type="button"
                    title={subscription.last_error ? `最近错误：${subscription.last_error}` : `${subscription.up_name}（mid: ${subscription.mid}）`}
                    onClick={() => setFilterSubscriptionId(isFiltering ? null : subscription.subscription_id)}
                  >
                    {subscription.up_face_url ? (
                      <img className="up-dynamics-chip-face" src={proxiedImageUrl(subscription.up_face_url)} alt="" loading="lazy" />
                    ) : (
                      <span className="up-dynamics-chip-face is-placeholder">{(subscription.up_name || "?").slice(0, 1)}</span>
                    )}
                    <span className="up-dynamics-chip-name">{subscription.up_name || subscription.mid}</span>
                    {subscription.unread_count ? <strong className="up-dynamics-chip-unread">{subscription.unread_count}</strong> : null}
                  </button>
                  <button
                    className={`up-dynamics-chip-toggle ${subscription.enabled ? "is-on" : ""}`}
                    type="button"
                    title={subscription.enabled ? "停用监听" : "启用监听"}
                    onClick={() => void toggleSubscription(subscription)}
                  >
                    {subscription.enabled ? "已启用" : "已停用"}
                  </button>
                  <button
                    className={`up-dynamics-chip-delete ${deleteConfirmId === subscription.subscription_id ? "is-confirm" : ""}`}
                    type="button"
                    title={deleteConfirmId === subscription.subscription_id ? "再次点击确认删除" : "删除订阅"}
                    onClick={() => void removeSubscription(subscription)}
                    onBlur={() => setDeleteConfirmId((current) => (current === subscription.subscription_id ? null : current))}
                  >
                    <TrashIcon width={14} height={14} />
                  </button>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="up-dynamics-hint">还没有订阅任何 UP 主。粘贴空间链接或 UID 即可开始监听新投稿。</p>
        )}
      </div>

      <div className="up-dynamics-toolbar">
        <button className={`library-segment ${unreadOnly ? "is-active" : ""}`} type="button" onClick={() => setUnreadOnly((value) => !value)}>
          仅未读
        </button>
        <button className="library-segment" type="button" disabled={!totalUnread} onClick={() => void markAllRead()}>
          全部已读
        </button>
        <button className={`library-segment ${refreshing ? "is-active" : ""}`} type="button" disabled={refreshing} onClick={() => void refreshNow()}>
          <RefreshIcon width={13} height={13} /> 刷新
        </button>
        {filterSubscriptionId ? (
          <button className="library-segment is-active" type="button" onClick={() => setFilterSubscriptionId(null)}>
            筛选：{subscriptionById.get(filterSubscriptionId)?.up_name || "未知 UP"} ×
          </button>
        ) : null}
        <span className="up-dynamics-toolbar-meta">
          {feedTotal} 条动态{status ? `，每 ${Math.round(status.poll_interval_seconds / 60)} 分钟自动检查` : ""}
        </span>
      </div>

      {notice ? <p className={`up-dynamics-notice is-${notice.tone}`}>{notice.text}</p> : null}

      {subscriptions.length === 0 ? (
        <div className="library-empty-state">
          <div className="library-empty-copy">
            <h4>开始监听 UP 动态</h4>
            <p>添加订阅后，UP 主的新投稿会自动入库并提交总结任务。</p>
          </div>
        </div>
      ) : !feedLoaded ? (
        <p className="up-dynamics-hint">加载中...</p>
      ) : feedItems.length === 0 ? (
        <div className="library-empty-state">
          <div className="library-empty-copy">
            <h4>{unreadOnly ? "没有未读动态" : "还没有检测到新投稿"}</h4>
            <p>{unreadOnly ? "所有动态都已读过。" : "等待 UP 主更新，发现新投稿后会自动入库并提交总结。"}</p>
          </div>
        </div>
      ) : (
        <>
          <ul className="up-dynamics-feed">
            {feedItems.map((detection) => {
              const subscription = subscriptionById.get(detection.subscription_id);
              const badgeLabel = detection.task_status ? TASK_BADGE_LABELS[detection.task_status] || detection.task_status : "待总结";
              const canSummarize = !detection.task_status || detection.task_status === "failed" || detection.task_status === "cancelled";
              const busy = busyDetectionId === detection.detection_id;
              return (
                <li key={detection.detection_id} className={`up-dynamics-item ${detection.unread ? "is-unread" : ""}`}>
                  <a
                    className="up-dynamics-item-cover"
                    href={`https://www.bilibili.com/video/${detection.bvid}/`}
                    target="_blank"
                    rel="noreferrer"
                    title="在 B 站打开"
                  >
                    {detection.cover_url ? <img src={proxiedImageUrl(detection.cover_url)} alt="" loading="lazy" /> : null}
                    {detection.duration ? <span className="up-dynamics-item-duration">{formatDuration(detection.duration)}</span> : null}
                  </a>
                  <div className="up-dynamics-item-body">
                    <div className="up-dynamics-item-title-row">
                      {detection.unread ? <span className="up-dynamics-item-dot" aria-label="未读" /> : null}
                      <a
                        className="up-dynamics-item-title"
                        href={`https://www.bilibili.com/video/${detection.bvid}/`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {detection.title || detection.bvid}
                      </a>
                      <ExternalLinkIcon width={13} height={13} />
                    </div>
                    <div className="up-dynamics-item-meta">
                      <span>{subscription?.up_name || "未知 UP"}</span>
                      <span>{formatRelativeTime(detection.pubdate)}</span>
                      <span className={`up-dynamics-badge ${taskBadgeClass(detection.task_status)}`}>{badgeLabel}</span>
                    </div>
                  </div>
                  <div className="up-dynamics-item-actions">
                    {canSummarize ? (
                      <button className="secondary-button" type="button" disabled={busy} onClick={() => void summarize(detection)}>
                        {busy ? "提交中..." : detection.task_status ? "重新总结" : "一键总结"}
                      </button>
                    ) : null}
                    {detection.task_status === "completed" && detection.video_id ? (
                      <button className="secondary-button" type="button" onClick={() => navigate(`/videos/${detection.video_id}`)}>
                        查看笔记
                      </button>
                    ) : null}
                    {detection.unread ? (
                      <button className="secondary-button" type="button" onClick={() => void markOneRead(detection)}>
                        标记已读
                      </button>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
          {feedItems.length < feedTotal ? (
            <div className="up-dynamics-load-more">
              <button className="library-pagination-button" type="button" disabled={loadingMore} onClick={() => void loadMore()}>
                {loadingMore ? "加载中..." : `加载更多（${feedItems.length} / ${feedTotal}）`}
              </button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
