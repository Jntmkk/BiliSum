import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  ActionSheetIOS,
  Alert,
  Animated,
  Modal,
  Platform,
  Pressable,
  Share,
  View,
  useWindowDimensions,
} from 'react-native';
import { Stack, useLocalSearchParams } from 'expo-router';
import * as Haptics from 'expo-haptics';
import Markdown from 'react-native-markdown-display';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  createAggregateSummary,
  createVideoTask,
  getTask,
  getTaskProgress,
  getVideo,
  getVideoTasks,
  type TaskResult,
  type TaskStatus,
  type TaskSummary,
  type VideoAssetDetail,
  type VideoPageOption,
} from '@/src/api/client';
import { invalidateLibrary } from '@/src/api/libraryStore';
import { useAsync } from '@/src/api/useAsync';
import { Card, Separator } from '@/src/components/Card';
import { ChapterCards } from '@/src/components/ChapterCards';
import { EmptyState } from '@/src/components/EmptyState';
import { Icon } from '@/src/components/Icon';
import { ProgressBar } from '@/src/components/ProgressBar';
import { SeekTime } from '@/src/components/SeekTime';
import { Segmented } from '@/src/components/Segmented';
import { Txt } from '@/src/components/Txt';
import { VideoPlayer } from '@/src/components/VideoPlayer';
import { usePersistedState } from '@/src/store/persist';
import { useColors } from '@/src/theme/colors';
import { layout, spacing } from '@/src/theme/layout';
import { radius } from '@/src/theme/radius';
import { typographyFor } from '@/src/theme/typography';
import { formatClock } from '@/src/utils/format';
import { buildPlayerEmbedDescriptor } from '@/src/utils/player';
import { isActiveStatus, taskStatusLabel } from '@/src/utils/status';

type TabKey = 'summary' | 'chapters' | 'note' | 'timeline';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'summary', label: '摘要' },
  { key: 'chapters', label: '章节' },
  { key: 'note', label: '笔记' },
  { key: 'timeline', label: '时间轴' },
];

const AGGREGATE_PAGE = 0;

/** 播放器钉住策略：自动 = 只在播放中钉住 */
type PinMode = 'auto' | 'always' | 'never';
const PIN_KEY = 'bilisum.video.pin';
const PIN_CYCLE: PinMode[] = ['auto', 'always', 'never'];
const PIN_LABELS: Record<PinMode, string> = {
  auto: '自动',
  always: '始终',
  never: '从不',
};

/** 单选项下面那行解释，说明当前这项到底什么行为 */
const PIN_HINTS: Record<PinMode, string> = {
  auto: '视频在播放时钉住，暂停或停止后随内容一起滑走。',
  always: '一直钉在顶部，滚动时不动。',
  never: '始终跟着内容滚动，不钉住。',
};

/**
 * 原生 header 的高度在 iOS 上是系统固定的（headerStyle 只接受 backgroundColor），
 * 能压的只有标题字号；再配一行 + 省略号，避免长标题把中栏撑成多行。
 */
const HEADER_TITLE_SIZE = 15;

interface Part {
  /** 0 = 全集总结 */
  page: number;
  title: string;
  duration: number | null;
  /** 该分 P 的来源地址，用于内嵌播放；全集总结没有单一来源 */
  sourceUrl: string | null;
  /** 最近一次已完成且有结果的任务 */
  resultTaskId: string | null;
  /** 最近一次任务（含未完成的），用于判断状态与进度 */
  latestTaskId: string | null;
  status: TaskStatus | null;
}

function latestByPage(tasks: TaskSummary[], page: number): TaskSummary | null {
  const mine = tasks
    .filter((t) => (t.page_number ?? 1) === page)
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  return mine[0] ?? null;
}

/** 进度没变就别 setState，省一次渲染 */
function sameProgress(a: Record<string, number>, b: Record<string, number>): boolean {
  const ak = Object.keys(a);
  if (ak.length !== Object.keys(b).length) return false;
  return ak.every((k) => a[k] === b[k]);
}

function buildParts(
  video: VideoAssetDetail,
  tasks: TaskSummary[],
): Part[] {
  const parts: Part[] = [];

  if (video.pages.length > 1) {
    const agg = latestByPage(tasks, AGGREGATE_PAGE);
    parts.push({
      page: AGGREGATE_PAGE,
      title: '全集总结',
      duration: null,
      sourceUrl: null,
      resultTaskId: agg?.status === 'completed' ? agg.task_id : null,
      latestTaskId: agg?.task_id ?? null,
      status: agg?.status ?? null,
    });
  }

  const pages: VideoPageOption[] = video.pages.length
    ? video.pages
    : [
        {
          page: 1,
          title: video.title,
          source_url: video.source_url,
          cover_url: video.cover_url,
          duration: video.duration,
        },
      ];

  for (const p of pages) {
    const t = latestByPage(tasks, p.page);
    parts.push({
      page: p.page,
      title: p.title,
      duration: p.duration,
      sourceUrl: p.source_url,
      resultTaskId: t?.status === 'completed' ? t.task_id : null,
      latestTaskId: t?.task_id ?? null,
      status: t?.status ?? null,
    });
  }

  return parts;
}

export default function VideoDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const colors = useColors();
  const { width } = useWindowDimensions();

  const [tab, setTab] = useState<TabKey>('summary');
  const [selectedPage, setSelectedPage] = useState<number | null>(null);
  const [progress, setProgress] = useState<Record<string, number>>({});
  const [creating, setCreating] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [pinMode, setPinMode] = usePersistedState<PinMode>(PIN_KEY, 'auto');
  const [menuOpen, setMenuOpen] = useState(false);
  // 滚动距离（原生驱动）：播放器的钉住位置靠它算，不经过 JS 每帧重渲染
  const scrollY = useRef(new Animated.Value(0)).current;
  // 以下派生值必须放在 early return 之前——hook 数量不能随渲染分支变化
  // 「自动」只在播放中才钉住；「始终」一直钉；「从不」不钉
  const pinned = pinMode === 'always' || (pinMode === 'auto' && playing);
  // 播放器尺寸：与内容区同宽（左右各 layout.margin），16:9
  const playerWidth = width - layout.margin * 2;
  const playerHeight = playerWidth / layout.coverAspect;
  const PLAYER_TOP = spacing.md;
  // 上滚时把播放器往上带；钉住时到顶就停（clamp），不钉时一路带走（extend）
  const translateY = useMemo(
    () =>
      scrollY.interpolate({
        inputRange: [0, PLAYER_TOP],
        outputRange: [0, -PLAYER_TOP],
        extrapolate: pinned ? 'clamp' : 'extend',
      }),
    [scrollY, pinned],
  );
  // 时间轴跳转：秒数 + 非零 nonce（同一个秒数再点一次也要重新加载播放器）
  const [seek, setSeek] = useState<{ seconds: number | null; nonce: number }>({
    seconds: null,
    nonce: 0,
  });
  const onSeek = useCallback(
    (seconds: number) => setSeek((prev) => ({ seconds, nonce: prev.nonce + 1 })),
    []);

  const main = useAsync(
    () => Promise.all([getVideo(id), getVideoTasks(id)]).then(([video, tasks]) => ({ video, tasks })),
    [id],
  );

  const video = main.data?.video ?? null;
  const tasks = useMemo(() => main.data?.tasks ?? [], [main.data]);

  const parts = useMemo(() => (video ? buildParts(video, tasks) : []), [video, tasks]);

  // 默认选中第一个分 P（多 P 时不默认选中「全集总结」，避免误以为已有内容）
  const activePage = useMemo(() => {
    if (selectedPage != null) return selectedPage;
    const firstReal = parts.find((p) => p.page !== AGGREGATE_PAGE);
    return firstReal?.page ?? parts[0]?.page ?? 1;
  }, [selectedPage, parts]);

  const activePart = useMemo(
    () => parts.find((p) => p.page === activePage) ?? null,
    [parts, activePage],
  );

  // 换分 P 时清掉上次的跳转目标，否则新分 P 会从上一个视频的秒数开始播
  const activeSourceUrl = activePart?.sourceUrl ?? null;
  useEffect(() => {
    setSeek((prev) => ({ seconds: null, nonce: prev.nonce + 1 }));
  }, [activeSourceUrl]);

  // ---- 选中分 P 的结果：按 taskId 缓存 ----
  const resultCache = useRef(new Map<string, TaskResult>());
  const [result, setResult] = useState<TaskResult | null>(null);
  const [resultLoading, setResultLoading] = useState(false);

  useEffect(() => {
    const taskId = activePart?.resultTaskId ?? null;
    if (!taskId) {
      setResult(null);
      return;
    }
    const cached = resultCache.current.get(taskId);
    if (cached) {
      setResult(cached);
      return;
    }
    let alive = true;
    setResultLoading(true);
    getTask(taskId)
      .then((detail) => {
        if (!alive || !detail.result) return;
        resultCache.current.set(taskId, detail.result);
        setResult(detail.result);
      })
      .catch(() => {
        if (alive) setResult(null);
      })
      .finally(() => {
        if (alive) setResultLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [activePart?.resultTaskId]);
  // ---- 轮询：有任务在跑时刷新任务列表与进度 ----
  // 依赖只能用字符串 activeKey：数组每次随 data 变新引用，会让 effect 每轮都重跑，
  // 而 effect 里立刻又 reload，形成无限循环。
  const activeKey = useMemo(
    () =>
      tasks
        .filter((t) => isActiveStatus(t.status))
        .map((t) => t.task_id)
        .sort()
        .join(','),
    [tasks],
  );
  const mainReloadRef = useRef(main.reload);
  mainReloadRef.current = main.reload;

  useEffect(() => {
    if (!activeKey) {
      setProgress({});
      return;
    }
    const ids = activeKey.split(',');
    let cancelled = false;
    const tick = async () => {
      const entries = await Promise.all(
        ids.map(async (taskId) => {
          try {
            const p = await getTaskProgress(taskId);
            return [taskId, p.progress] as const;
          } catch {
            return [taskId, 0] as const;
          }
        }),
      );
      if (cancelled) return;
      const next = Object.fromEntries(entries);
      setProgress((prev) => (sameProgress(prev, next) ? prev : next));
      void mainReloadRef.current();
    };
    void tick();
    const timer = setInterval(tick, 3000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [activeKey]);

  const activeProgress =
    activePart?.latestTaskId != null ? progress[activePart.latestTaskId] : undefined;

  // ---- 生成 / 重新生成 ----
  const generate = useCallback(
    async (page: number) => {
      if (!video) return;
      setCreating(true);
      try {
        const detail =
          page === AGGREGATE_PAGE
            ? await createAggregateSummary(video.video_id)
            : await createVideoTask(video.video_id, { page_number: page });
        void detail;
        invalidateLibrary();
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
        await main.reload();
      } catch (e) {
        Alert.alert('提交失败', e instanceof Error ? e.message : '未知错误');
      } finally {
        setCreating(false);
      }
    },
    [video, main],
  );

  const onMenu = useCallback(() => {
    if (!video) return;
    setMenuOpen(true);
  }, [video]);

  const onSelectPart = useCallback((next: Part) => {
    setSelectedPage(next.page);
    setTab('summary');
    void Haptics.selectionAsync();
  }, []);

  const headerRight = useCallback(
    () => (
      <Pressable onPress={onMenu} hitSlop={10} style={{ paddingHorizontal: spacing.xs }}>
        <Icon sf="ellipsis.circle" ion="ellipsis-horizontal-circle" size={22} color={colors.accent} />
      </Pressable>
    ),
    [onMenu, colors.accent],
  );

  // 中栏用视频标题替代固定的「视频」，字号压小、单行、超出省略
  const headerTitle = useCallback(
    () => (
      <Txt
        numberOfLines={1}
        ellipsizeMode="tail"
        style={{
          fontSize: HEADER_TITLE_SIZE,
          fontWeight: '600',
          maxWidth: width - 150,
        }}>
        {video?.title ?? ''}
      </Txt>
    ),
    [video?.title, width],
  );

  if (main.loading && !video) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  if (main.error || !video) {
    return (
      <EmptyState
        sf="exclamationmark.triangle"
        ion="warning-outline"
        title="加载失败"
        description={main.error ?? '视频不存在'}
        actionLabel="重试"
        onAction={main.reload}
      />
    );
  }

  const isActive = isActiveStatus(activePart?.status ?? video.latest_status);
  // 只有 B 站 / YouTube 能内嵌播放，其它来源的时间轴就不可点
  const canSeek = !!buildPlayerEmbedDescriptor(activePart?.sourceUrl ?? video.source_url);

  return (
    <View style={{ flex: 1, overflow: 'hidden' }}>
      <Stack.Screen
        options={{
          headerRight,
          headerTitle,
          // 系统 header 的高度改不了，只能压标题字号；单行 + 省略号见 headerTitle
          headerTitleStyle: { fontSize: HEADER_TITLE_SIZE },
        }}
      />

      <Animated.ScrollView
        style={{ flex: 1, backgroundColor: colors.groupedBackground }}
        contentContainerStyle={{ paddingBottom: spacing.xxl }}
        onScroll={Animated.event([{ nativeEvent: { contentOffset: { y: scrollY } } }], {
          useNativeDriver: true,
        })}
        scrollEventThrottle={16}>
        {/* 给播放器占位：播放器是绝对定位的兄弟节点，这里留出它原本占的高度 */}
        <View style={{ height: PLAYER_TOP + playerHeight }} />
        {/* 标题不再在正文里重复一遍（header 已经有了）；时长走封面角标 */}
        <View style={{ height: spacing.md }} />

        {/* 分 P 切换（多 P 才有） */}
        {parts.length > 1 ? (
          <View style={{ paddingHorizontal: layout.margin, marginBottom: spacing.md }}>
            <PartMenu
              parts={parts}
              active={activePart}
              onSelect={onSelectPart}
              creating={creating}
              onGenerate={generate}
            />
          </View>
        ) : null}

        {/* 进度 */}
        {isActive ? (
          <View style={{ paddingHorizontal: layout.margin, marginBottom: spacing.md, gap: spacing.xs }}>
            <ProgressBar value={activeProgress ?? 0} />
            <Txt variant="footnote" color="secondary">
              {taskStatusLabel(activePart?.status ?? video.latest_status ?? 'running')}
              {activeProgress != null ? ` · ${activeProgress}%` : ''}
            </Txt>
          </View>
        ) : null}

        {/* 失败提示 */}
        {activePart?.status === 'failed' && !activePart.resultTaskId && video.latest_error_message ? (
          <View style={{ paddingHorizontal: layout.margin, marginBottom: spacing.md }}>
            <Card inset={false} style={{ padding: spacing.md }}>
              <Txt variant="footnote" color="danger">
                {video.latest_error_message}
              </Txt>
            </Card>
          </View>
        ) : null}

        <View style={{ paddingHorizontal: layout.margin, marginBottom: spacing.md }}>
          <Segmented values={TABS} value={tab} onChange={setTab} />
        </View>

        {resultLoading ? (
          <ActivityIndicator style={{ marginTop: spacing.xl }} />
        ) : !result ? (
          <EmptyState
            sf={isActive ? 'clock' : 'doc.text'}
            ion={isActive ? 'time-outline' : 'document-text-outline'}
            title={isActive ? '正在生成摘要' : '还没有摘要'}
            description={
              isActive
                ? '处理完成后会自动显示在这里'
                : activePart?.page === AGGREGATE_PAGE
                  ? '需要至少一个分 P 的摘要才能生成全集总结'
                  : '点击右上角 ⋯ 生成这份摘要'
            }
            actionLabel={isActive ? undefined : '生成摘要'}
            onAction={isActive ? undefined : () => void generate(activePage)}
          />
        ) : (
          // 不再套外层 paddingHorizontal：卡片自己带 16pt 外边距，
          // 叠在一起会变成 48pt/边，正文两边空荡荡
          <View style={{ gap: spacing.lg }}>
            {tab === 'summary' ? <SummaryTab result={result} /> : null}
            {tab === 'chapters' ? (
              <ChapterCards result={result} onSeek={canSeek ? onSeek : undefined} />
            ) : null}
            {tab === 'note' ? <NoteTab result={result} /> : null}
            {tab === 'timeline' ? (
              <TimelineTab result={result} onSeek={canSeek ? onSeek : undefined} />
            ) : null}
          </View>
        )}
      </Animated.ScrollView>

      {/*
        播放器只挂这一个实例（挂两个会同时出声）。
        它绝对定位在内容之上，位置 = 原位置 - 已滚动距离：
        · 不钉住时一路跟着内容往上走（extrapolate: extend），跟普通元素一样滑走；
        · 钉住时滚到顶就停住（clamp），盖在上方不动。
        内容区开头留了等高的占位，所以文字流不会跳。
      */}
      <Animated.View
        style={{
          position: 'absolute',
          top: PLAYER_TOP,
          left: layout.margin,
          right: layout.margin,
          zIndex: 1,
          transform: [{ translateY }],
        }}>
        <View
          style={{
            borderRadius: radius.lg,
            overflow: 'hidden',
            backgroundColor: '#000000',
            shadowColor: '#000',
            shadowOpacity: pinned ? 0.18 : 0,
            shadowRadius: 12,
            shadowOffset: { width: 0, height: 4 },
          }}>
          <VideoPlayer
            sourceUrl={activePart?.sourceUrl ?? video.source_url}
            coverUrl={video.cover_url || null}
            badge={
              video.pages.length > 1
                ? `${video.pages.length}P`
                : formatClock(video.duration) || undefined
            }
            seekSeconds={seek.seconds}
            seekNonce={seek.nonce}
            playing={playing}
            onPlayingChange={setPlaying}
          />
        </View>
      </Animated.View>

      <MenuSheet
        visible={menuOpen}
        onClose={() => setMenuOpen(false)}
        pinMode={pinMode}
        onPinMode={setPinMode}
        actions={[
          ...(result?.transcript_text
            ? [
                {
                  label: '分享 / 复制全文',
                  run: () => void Share.share({ message: result.transcript_text }),
                },
              ]
            : []),
          ...(activePart?.page !== AGGREGATE_PAGE || video.pages.length > 1
            ? [
                {
                  label: activePart?.resultTaskId ? '重新生成摘要' : '生成摘要',
                  run: () => void generate(activePage),
                },
              ]
            : []),
          { label: '复制视频链接', run: () => void Share.share({ message: video.source_url }) },
        ]}
      />
    </View>
  );
}

/**
 * ⋯ 菜单：自绘 ActionSheet。系统 ActionSheet 只能给一排文字，
 * 钉住策略需要「一组单选项」的形态，所以自己画。
 */
function MenuSheet({
  visible,
  onClose,
  pinMode,
  onPinMode,
  actions,
}: {
  visible: boolean;
  onClose: () => void;
  pinMode: PinMode;
  onPinMode: (mode: PinMode) => void;
  actions: { label: string; run: () => void }[];
}) {
  const colors = useColors();
  const insets = useSafeAreaInsets();

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={{ flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.4)' }} onPress={onClose}>
        {/* 吞掉面板内的点击，避免冒泡到遮罩把面板关掉 */}
        <Pressable onPress={() => {}}>
          <View
            style={{
              backgroundColor: colors.groupedBackground,
              borderTopLeftRadius: radius.lg,
              borderTopRightRadius: radius.lg,
              paddingTop: spacing.md,
              paddingBottom: insets.bottom + spacing.sm,
              gap: spacing.sm,
            }}>
            <Txt variant="footnote" color="secondary" style={{ paddingHorizontal: layout.margin + spacing.xs }}>
              钉住视频
            </Txt>
            <Card>
              {PIN_CYCLE.map((mode, i) => {
                const checked = mode === pinMode;
                return (
                  <View key={mode}>
                    {i > 0 ? <Separator /> : null}
                    <Pressable
                      onPress={() => {
                        onPinMode(mode);
                        void Haptics.selectionAsync();
                      }}
                      style={({ pressed }) => ({
                        flexDirection: 'row',
                        alignItems: 'center',
                        gap: spacing.md,
                        minHeight: layout.touchTarget,
                        paddingHorizontal: spacing.md,
                        backgroundColor: pressed ? colors.fill : 'transparent',
                      })}>
                      <Icon
                        sf={checked ? 'checkmark.circle.fill' : 'circle'}
                        ion={checked ? 'checkmark-circle' : 'ellipse-outline'}
                        size={22}
                        color={checked ? colors.accent : colors.tertiaryLabel}
                      />
                      <Txt variant="body" style={{ flex: 1 }}>
                        {PIN_LABELS[mode]}
                      </Txt>
                    </Pressable>
                  </View>
                );
              })}
            </Card>
            <Txt
              variant="footnote"
              color="tertiary"
              style={{ paddingHorizontal: layout.margin + spacing.xs }}>
              {PIN_HINTS[pinMode]}
            </Txt>

            <Card>
              {actions.map((a, i) => (
                <View key={a.label}>
                  {i > 0 ? <Separator /> : null}
                  <Pressable
                    onPress={() => {
                      onClose();
                      a.run();
                    }}
                    style={({ pressed }) => ({
                      justifyContent: 'center',
                      minHeight: layout.touchTarget,
                      paddingHorizontal: spacing.md,
                      backgroundColor: pressed ? colors.fill : 'transparent',
                    })}>
                    <Txt variant="body">{a.label}</Txt>
                  </Pressable>
                </View>
              ))}
            </Card>

            <Card>
              <Pressable
                onPress={onClose}
                style={({ pressed }) => ({
                  alignItems: 'center',
                  justifyContent: 'center',
                  minHeight: layout.touchTarget,
                  backgroundColor: pressed ? colors.fill : 'transparent',
                })}>
                <Txt variant="body" color="accent" style={{ fontWeight: '600' }}>
                  取消
                </Txt>
              </Pressable>
            </Card>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

/** 分 P 选择器：点开是原生 ActionSheet 列表 */
function PartMenu({
  parts,
  active,
  onSelect,
  onGenerate,
  creating,
}: {
  parts: Part[];
  active: Part | null;
  onSelect: (part: Part) => void;
  onGenerate: (page: number) => void;
  creating: boolean;
}) {
  const colors = useColors();

  const open = useCallback(() => {
    const options = parts.map((p) =>
      p.page === AGGREGATE_PAGE
        ? p.title
        : `P${p.page} ${p.title}${p.resultTaskId ? ' ✓' : ''}`,
    );
    const cancelIndex = options.length;

    if (Platform.OS === 'ios') {
      ActionSheetIOS.showActionSheetWithOptions(
        { options: [...options, '取消'], cancelButtonIndex: cancelIndex },
        (index) => {
          const part = parts[index];
          if (part) onSelect(part);
        },
      );
    } else {
      Alert.alert(
        '选择分 P',
        undefined,
        [
          ...parts.map((p) => ({ text: p.title, onPress: () => onSelect(p) })),
          { text: '取消', style: 'cancel' as const },
        ],
      );
    }
  }, [parts, onSelect]);

  const label = active
    ? active.page === AGGREGATE_PAGE
      ? '全集总结'
      : `P${active.page} ${active.title}`
    : '选择分 P';

  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
      <Pressable
        onPress={open}
        style={({ pressed }) => ({
          flex: 1,
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: spacing.sm,
          height: layout.touchTarget,
          paddingHorizontal: spacing.md,
          borderRadius: radius.md,
          backgroundColor: colors.surface,
          opacity: pressed ? 0.7 : 1,
        })}>
        <Txt variant="body" numberOfLines={1} style={{ flex: 1 }}>
          {label}
        </Txt>
        <Icon sf="chevron.up.chevron.down" ion="chevron-expand" size={13} color={colors.secondaryLabel} />
      </Pressable>

      {active && !active.resultTaskId && !isActiveStatus(active.status) ? (
        <Pressable
          onPress={() => onGenerate(active.page)}
          disabled={creating}
          style={({ pressed }) => ({
            height: layout.touchTarget,
            paddingHorizontal: spacing.md,
            borderRadius: radius.md,
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: colors.accent,
            opacity: creating ? 0.6 : pressed ? 0.8 : 1,
          })}>
          <Txt variant="subheadline" style={{ color: '#FFFFFF', fontWeight: '600' }}>
            生成
          </Txt>
        </Pressable>
      ) : null}
    </View>
  );
}

function SummaryTab({ result }: { result: TaskResult }) {
  const colors = useColors();
  return (
    <>
      {result.overview ? (
        <Card>
          <View style={{ padding: spacing.md, gap: spacing.sm }}>
            <Txt variant="footnote" color="secondary">
              核心概览
            </Txt>
            <Txt variant="body" style={{ lineHeight: 24 }}>
              {result.overview}
            </Txt>
          </View>
        </Card>
      ) : null}

      {result.key_points?.length ? (
        <Card>
          {result.key_points.map((point, i) => (
            <View key={i}>
              {i > 0 ? <Separator /> : null}
              <View
                style={{
                  flexDirection: 'row',
                  gap: spacing.md,
                  padding: spacing.md,
                }}>
                <View
                  style={{
                    width: 22,
                    height: 22,
                    borderRadius: radius.pill,
                    alignItems: 'center',
                    justifyContent: 'center',
                    backgroundColor: colors.fill,
                    marginTop: 1,
                  }}>
                  <Txt variant="caption1" color="secondary" style={{ fontWeight: '600' }}>
                    {i + 1}
                  </Txt>
                </View>
                <Txt variant="body" style={{ flex: 1, lineHeight: 24 }}>
                  {point}
                </Txt>
              </View>
            </View>
          ))}
        </Card>
      ) : null}

      {!result.overview && !result.key_points?.length ? (
        <Txt variant="body" color="secondary" center style={{ marginTop: spacing.xl }}>
          这份摘要还没有概览内容
        </Txt>
      ) : null}
    </>
  );
}

function NoteTab({
  result,
}: {
  result: TaskResult;
}) {
  const colors = useColors();
  const md = useMemo(() => markdownStyles(colors), [colors]);
  if (!result.knowledge_note_markdown) {
    return (
      <Txt variant="body" color="secondary" center style={{ marginTop: spacing.xl }}>
        这份摘要还没有生成知识笔记
      </Txt>
    );
  }
  return (
    <View style={{ paddingHorizontal: layout.margin }}>
      <Markdown style={md}>{result.knowledge_note_markdown}</Markdown>
    </View>
  );
}

function TimelineTab({
  result,
  onSeek,
}: {
  result: TaskResult;
  /** 传了才允许点时间戳跳转（非 B 站/YouTube 源不给） */
  onSeek?: (seconds: number) => void;
}) {
  const colors = useColors();
  if (!result.timeline?.length) {
    return (
      <Txt variant="body" color="secondary" center style={{ marginTop: spacing.xl }}>
        这份摘要还没有章节时间轴
      </Txt>
    );
  }
  return (
    <View style={{ paddingHorizontal: layout.margin }}>
      {result.timeline.map((item, i) => (
        <View key={i} style={{ flexDirection: 'row', gap: spacing.md }}>
          <View style={{ width: 52, alignItems: 'flex-end' }}>
            <SeekTime seconds={item.start} onSeek={onSeek} />
          </View>
          <View
            style={{
              width: layout.hairline * 2,
              backgroundColor: colors.separator,
              marginBottom: i === result.timeline.length - 1 ? 0 : 0,
            }}
          />
          <View style={{ flex: 1, paddingBottom: spacing.lg }}>
            {item.title ? (
              <Txt variant="subheadline" style={{ fontWeight: '600', marginBottom: 2 }}>
                {item.title}
              </Txt>
            ) : null}
            {item.summary ? (
              <Txt variant="footnote" color="secondary" style={{ lineHeight: 20 }}>
                {item.summary}
              </Txt>
            ) : null}
          </View>
        </View>
      ))}
    </View>
  );
}

/**
 * 每个标题都要显式给 lineHeight：react-native-markdown-display 的
 * AstRenderer 会把 body 的 fontSize/lineHeight 沿祖先链拷到内层 <Text>，
 * 字号大于行高时多行标题会重叠。
 */
function markdownStyles(colors: ReturnType<typeof useColors>) {
  const body = typographyFor('body');
  return {
    body: { color: colors.label as string, fontSize: body.fontSize, lineHeight: 24 },
    heading1: { ...typographyFor('title3'), marginVertical: spacing.md },
    heading2: { ...typographyFor('headline'), marginVertical: spacing.md },
    heading3: { ...typographyFor('subheadline'), fontWeight: '600' as const, marginVertical: spacing.sm },
    heading4: { ...typographyFor('subheadline'), fontWeight: '600' as const, marginVertical: spacing.sm },
    heading5: { ...typographyFor('footnote'), fontWeight: '600' as const, marginVertical: spacing.sm },
    heading6: { ...typographyFor('footnote'), fontWeight: '600' as const, marginVertical: spacing.sm },
    code_inline: {
      backgroundColor: colors.fill as string,
      borderRadius: 4,
      fontFamily: 'Menlo',
      fontSize: 15,
    },
    fence: {
      backgroundColor: colors.fill as string,
      borderRadius: radius.sm,
      padding: spacing.md,
      fontFamily: 'Menlo',
      fontSize: 13,
      lineHeight: 20,
    },
    link: { color: colors.accent as string },
    list_item: { marginVertical: spacing.xs },
    bullet_list: { marginVertical: spacing.sm },
    ordered_list: { marginVertical: spacing.sm },
    blockquote: {
      backgroundColor: colors.fill as string,
      borderLeftWidth: 3,
      borderLeftColor: colors.separator as string,
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.xs,
      marginVertical: spacing.sm,
    },
  };
}
