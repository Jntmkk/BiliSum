import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  TextInput,
  View,
  type ViewInstance,
  useWindowDimensions,
} from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import * as Haptics from 'expo-haptics';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { VideoAssetSummary } from '@/src/api/client';
import { getTaskProgress } from '@/src/api/client';
import { useLibraryPage } from '@/src/api/libraryStore';
import {
  DEFAULT_LIBRARY_QUERY,
  SORT_OPTIONS,
  STATUS_OPTIONS,
  UNFILED,
  activeFilterCount,
  type LibraryQuery,
} from '@/src/features/library';
import { usePersistedState } from '@/src/store/persist';
import { useTabSwipe } from '@/src/features/tabSwipe';
import { useColors } from '@/src/theme/colors';
import { layout, spacing } from '@/src/theme/layout';
import { radius } from '@/src/theme/radius';
import { EmptyState } from '@/src/components/EmptyState';
import { Icon } from '@/src/components/Icon';
import { Txt } from '@/src/components/Txt';
import { VideoCard, VideoListRow } from '@/src/components/VideoCard';
import { GridSkeleton, ListSkeleton } from '@/src/components/Skeleton';
import {
  DropdownOverlay,
  FilterTrigger,
  OptionChip,
  OptionGroup,
  OptionList,
} from '@/src/components/Filter';
import { isActiveStatus, platformLabel } from '@/src/utils/status';

type ViewMode = 'grid' | 'list';
type OpenMenu = 'status' | 'sort' | 'filter' | null;

/** 进度没变就别 setState，省一次渲染 */
function sameProgress(a: Record<string, number>, b: Record<string, number>): boolean {
  const ak = Object.keys(a);
  if (ak.length !== Object.keys(b).length) return false;
  return ak.every((k) => a[k] === b[k]);
}

const VIEW_KEY = 'bilisum.library.view';
const QUERY_KEY = 'bilisum.library.query';

export default function LibraryScreen() {
  const colors = useColors();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const panHandlers = useTabSwipe(0);

  const [view, setView, viewHydrated] = usePersistedState<ViewMode>(VIEW_KEY, 'grid');
  const [savedQuery, setSavedQuery, queryHydrated] = usePersistedState<LibraryQuery>(
    QUERY_KEY,
    DEFAULT_LIBRARY_QUERY,
  );
  const [search, setSearch] = useState('');

  const library = useLibraryPage({
    ...savedQuery,
    query: search,
  });
  const videos = library.videos;
  const folders = library.folders;

  const [open, setOpen] = useState<OpenMenu>(null);
  const [dropdownTop, setDropdownTop] = useState(0);
  const rowRef = useRef<ViewInstance | null>(null);

  // ---- 轮询：有处理中的视频时定期刷新 ----
  // 库接口只给状态不给百分比，进度要单独问 /tasks/{id}/progress。
  // 依赖用字符串 key：数组每次随 data 变新引用会让 effect 反复重跑。
  const [progressByVideo, setProgressByVideo] = useState<Record<string, number>>({});
  const activeKey = useMemo(
    () =>
      videos
        .filter((v) => isActiveStatus(v.latest_status) && v.latest_task_id)
        .map((v) => `${v.video_id}:${v.latest_task_id}`)
        .sort()
        .join(','),
    [videos],
  );
  const refreshRef = useRef(library.refreshLoaded);
  refreshRef.current = library.refreshLoaded;
  useEffect(() => {
    if (!activeKey) {
      setProgressByVideo((prev) => (Object.keys(prev).length === 0 ? prev : {}));
      return;
    }
    const pairs = activeKey.split(',').map((s) => {
      const idx = s.indexOf(':');
      return { videoId: s.slice(0, idx), taskId: s.slice(idx + 1) };
    });
    let cancelled = false;
    const tick = async () => {
      const entries = await Promise.all(
        pairs.map(async ({ videoId, taskId }) => {
          try {
            const p = await getTaskProgress(taskId);
            return [videoId, p.progress] as const;
          } catch {
            return null;
          }
        }),
      );
      if (cancelled) return;
      const next = Object.fromEntries(
        entries.filter((e): e is readonly [string, number] => e !== null),
      );
      setProgressByVideo((prev) => (sameProgress(prev, next) ? prev : next));
      void refreshRef.current();
    };
    void tick();
    const timer = setInterval(tick, 3000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [activeKey]);

  // 从新建 / 详情页返回时刷新（invalidateLibrary 会把 fetchedAt 置空）
  useFocusEffect(
    useCallback(() => {
      void library.refresh();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []),
  );

  const progressOf = useCallback(
    (asset: VideoAssetSummary): number | undefined => progressByVideo[asset.video_id],
    [progressByVideo],
  );

  const openMenu = useCallback((menu: Exclude<OpenMenu, null>) => {
    rowRef.current?.measureInWindow((_x, y, _w, h) => setDropdownTop(y + h));
    setOpen((cur) => (cur === menu ? null : menu));
  }, []);

  const closeMenu = useCallback(() => setOpen(null), []);

  const cardWidth = (width - layout.margin * 2 - layout.gridGutter) / 2;

  const setStatus = useCallback(
    (status: LibraryQuery['status']) => {
      setSavedQuery({ ...savedQuery, status });
      closeMenu();
    },
    [savedQuery, setSavedQuery, closeMenu],
  );

  const setSort = useCallback(
    (sort: LibraryQuery['sort']) => {
      setSavedQuery({ ...savedQuery, sort });
      closeMenu();
    },
    [savedQuery, setSavedQuery, closeMenu],
  );

  const goNew = useCallback(() => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    router.push('/new');
  }, [router]);

  const notConfigured = library.error?.includes('设置服务器地址');
  const ready = viewHydrated && queryHydrated;

  // 加载中 / 出错 / 无匹配：都走列表的空态，这样它们跟列表一样在滚动视图里，
  // 能被安全区自动让开（这里 header 因为有搜索栏是半透明的，内容会铺到它下面）。
  const showSkeleton = !ready || (library.loading && videos.length === 0);
  const showError = !showSkeleton && !!library.error;
  const showEmpty = !showSkeleton && !showError && videos.length === 0;

  const toolbar = (
    <View
      ref={rowRef}
      onLayout={() => {
        if (open) rowRef.current?.measureInWindow((_x, y, _w, h) => setDropdownTop(y + h));
      }}
      style={{
        paddingHorizontal: layout.margin,
        paddingTop: spacing.sm,
        paddingBottom: spacing.sm,
        gap: spacing.sm,
        backgroundColor: colors.groupedBackground,
      }}
    >
      {/* 第一行：搜索框在左，加号紧挨其右。放同一行时搜索框才够宽，也符合
          「搜索是主操作、加号是它的补充」的层级。 */}
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
        <View
          style={{
            flex: 1,
            flexDirection: 'row',
            alignItems: 'center',
            gap: spacing.sm,
            height: 36,
            paddingHorizontal: spacing.md,
            borderRadius: radius.md,
            backgroundColor: colors.fill,
          }}
        >
          <Icon sf="magnifyingglass" ion="search" size={16} color={colors.secondaryLabel} />
          <TextInput
            value={search}
            onChangeText={setSearch}
            placeholder="搜索标题或 BV 号"
            placeholderTextColor={colors.secondaryLabel}
            autoCapitalize="none"
            autoCorrect={false}
            returnKeyType="search"
            clearButtonMode="while-editing"
            style={{ flex: 1, color: colors.label, fontSize: 15, padding: 0 }}
          />
        </View>

        <Pressable
          onPress={goNew}
          hitSlop={6}
          style={({ pressed }) => ({
            width: 30,
            height: 30,
            borderRadius: radius.pill,
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: colors.accent,
            opacity: pressed ? 0.7 : 1,
          })}
        >
          <Icon sf="plus" ion="add" size={15} weight="semibold" color="#FFFFFF" />
        </Pressable>
      </View>

      {/* 第二行：筛选与视图切换。挤在第一行会把搜索框压到只剩几十点宽。 */}
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
        <FilterTrigger
          label={STATUS_OPTIONS.find((o) => o.value === savedQuery.status)?.label ?? '全部状态'}
          active={savedQuery.status !== 'all'}
          onPress={() => openMenu('status')}
        />

        <FilterTrigger
          label={SORT_OPTIONS.find((o) => o.value === savedQuery.sort)?.label ?? '最近添加'}
          onPress={() => openMenu('sort')}
        />

        <FilterTrigger
          label="筛选"
          active={activeFilterCount(savedQuery) > 0}
          count={activeFilterCount(savedQuery)}
          onPress={() => openMenu('filter')}
        />

        <View style={{ flex: 1 }} />

        <Pressable
          onPress={() => setView(view === 'grid' ? 'list' : 'grid')}
          hitSlop={6}
          style={({ pressed }) => ({
            width: 32,
            height: 32,
            alignItems: 'center',
            justifyContent: 'center',
            opacity: pressed ? 0.6 : 1,
          })}
        >
          <Icon
            sf={view === 'grid' ? 'list.bullet' : 'square.grid.2x2'}
            ion={view === 'grid' ? 'list' : 'grid'}
            size={20}
            color={colors.accent}
          />
        </Pressable>
      </View>
    </View>
  );

  return (
    // 关掉了原生 header：顶部安全区得自己让开，否则搜索框顶到状态栏。
    // 根节点让开之后，列表自身的 safety area 顶部就是 0，automatic 不会再叠一次；
    // 底部仍由 automatic 让开 tab 栏，所以这里保持 automatic。
    <View
      {...panHandlers}
      style={{
        flex: 1,
        backgroundColor: colors.groupedBackground,
        paddingTop: insets.top,
      }}>
      {/* 工具行是列表的兄弟节点，而不是吸顶的 ListHeaderComponent：
          RN 的粘性头是按滚动框顶对齐的，没有导航栏时会顶到状态栏下面去 */}
      {toolbar}

      <FlatList
        style={{ flex: 1 }}
        contentInsetAdjustmentBehavior="automatic"
        key={view}
        data={showSkeleton || showError || showEmpty ? [] : videos}
        keyExtractor={(item) => item.video_id}
        numColumns={view === 'grid' ? 2 : 1}
        columnWrapperStyle={
          view === 'grid' ? { paddingHorizontal: layout.margin, gap: layout.gridGutter } : undefined
        }
        contentContainerStyle={{ paddingBottom: spacing.xl }}
        onEndReached={library.loadMore}
        onEndReachedThreshold={0.5}
        ListFooterComponent={
          videos.length > 0 ? (
            <View style={{ height: 44, alignItems: 'center', justifyContent: 'center' }}>
              {library.loadingMore ? (
                <ActivityIndicator />
              ) : library.hasMore ? null : (
                <Txt variant="footnote" color="tertiary">
                  已加载全部 {library.total} 个视频
                </Txt>
              )}
            </View>
          ) : undefined
        }
        ListEmptyComponent={
          showSkeleton ? (
            <View>
              {view === 'grid' ? <GridSkeleton /> : <ListSkeleton />}
            </View>
          ) : showError ? (
            <EmptyState
              sf="exclamationmark.triangle"
              ion="warning-outline"
              title={notConfigured ? '还没设置服务器' : '加载失败'}
              description={library.error ?? ''}
              actionLabel={notConfigured ? '去设置' : '重试'}
              onAction={() =>
                notConfigured ? router.push('/(tabs)/settings') : void library.refresh()
              }
            />
          ) : (
            <EmptyState
              sf="rectangle.stack"
              ion="albums-outline"
              title={videos.length === 0 ? '还没有视频' : '没有匹配的视频'}
              description={
                videos.length === 0
                  ? '粘贴 B 站 / YouTube 链接，开始生成摘要'
                  : '试试放宽筛选条件或换个搜索词'
              }
              actionLabel={videos.length === 0 ? '新建总结' : undefined}
              onAction={videos.length === 0 ? goNew : undefined}
            />
          )
        }
        refreshControl={
          <RefreshControl refreshing={library.refreshing} onRefresh={library.refresh} />
        }
        renderItem={({ item }) =>
          view === 'grid' ? (
            <View style={{ width: cardWidth }}>
              <VideoCard
                asset={item}
                progress={progressOf(item)}
                onPress={() => router.push(`/video/${item.video_id}`)}
              />
            </View>
          ) : (
            <VideoListRow
              asset={item}
              progress={progressOf(item)}
              onPress={() => router.push(`/video/${item.video_id}`)}
            />
          )
        }
      />

      <DropdownOverlay visible={open !== null} top={dropdownTop} onClose={closeMenu}>
        {open === 'status' ? (
          <OptionList
            options={STATUS_OPTIONS.map((o) => ({
              value: o.value,
              label: o.label,
            }))}
            value={savedQuery.status}
            onChange={setStatus}
          />
        ) : null}

        {open === 'sort' ? (
          <OptionList
            options={SORT_OPTIONS.map((o) => ({
              value: o.value,
              label: o.label,
            }))}
            value={savedQuery.sort}
            onChange={setSort}
          />
        ) : null}

        {open === 'filter' ? (
          <FilterPanel
            platforms={library.platforms}
            folders={folders}
            value={savedQuery}
            onChange={(next) => setSavedQuery(next)}
            onClose={closeMenu}
            resultCount={library.total}
          />
        ) : null}
      </DropdownOverlay>
    </View>
  );
}

/** 多条件筛选面板：平台 / 文件夹 / 其他 */
function FilterPanel({
  platforms,
  folders,
  value,
  onChange,
  onClose,
  resultCount,
}: {
  /** 服务端下发的平台 facet；分页时当前页推导不全 */
  platforms: string[];
  folders: { folder_id: string; name: string }[];
  value: LibraryQuery;
  onChange: (next: LibraryQuery) => void;
  onClose: () => void;
  resultCount: number;
}) {
  const colors = useColors();

  const toggle = <T,>(list: T[], item: T): T[] =>
    list.includes(item) ? list.filter((x) => x !== item) : [...list, item];

  return (
    <View>
      {platforms.length > 1 ? (
        <OptionGroup title="平台" first>
          {platforms.map((p) => (
            <OptionChip
              key={p}
              label={platformLabel(p)}
              selected={value.platforms.includes(p)}
              onPress={() => onChange({ ...value, platforms: toggle(value.platforms, p) })}
            />
          ))}
        </OptionGroup>
      ) : null}

      {/* 文件夹表目前是空的，这时只渲染「未归档」，不要留一个空分组 */}
      <OptionGroup title="文件夹" first={platforms.length <= 1}>
        <OptionChip
          label="未归档"
          selected={value.folderIds.includes(UNFILED)}
          onPress={() => onChange({ ...value, folderIds: toggle(value.folderIds, UNFILED) })}
        />
        {folders.map((f) => (
          <OptionChip
            key={f.folder_id}
            label={f.name}
            selected={value.folderIds.includes(f.folder_id)}
            onPress={() =>
              onChange({
                ...value,
                folderIds: toggle(value.folderIds, f.folder_id),
              })
            }
          />
        ))}
      </OptionGroup>

      <OptionGroup title="其他">
        <OptionChip
          label="仅收藏"
          selected={value.favoritesOnly}
          onPress={() => onChange({ ...value, favoritesOnly: !value.favoritesOnly })}
        />
      </OptionGroup>

      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingHorizontal: layout.margin,
          paddingTop: spacing.md,
          marginTop: spacing.md,
          borderTopWidth: layout.hairline,
          borderTopColor: colors.separator,
        }}
      >
        <Pressable
          onPress={() =>
            onChange({
              ...value,
              platforms: [],
              folderIds: [],
              favoritesOnly: false,
            })
          }
        >
          <Txt variant="body" color="accent">
            重置
          </Txt>
        </Pressable>
        <Pressable onPress={onClose}>
          <Txt variant="body" color="accent" style={{ fontWeight: '600' }}>
            确定 ({resultCount})
          </Txt>
        </Pressable>
      </View>
      <View style={{ height: spacing.sm }} />
    </View>
  );
}
