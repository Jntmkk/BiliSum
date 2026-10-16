import { useCallback, useMemo, useRef, useState } from 'react';
import { FlatList, RefreshControl, View } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { VideoCollectionSummary } from '@/src/api/client';
import { useLibrary } from '@/src/api/libraryStore';
import { CollectionCard } from '@/src/components/CollectionCard';
import { EmptyState } from '@/src/components/EmptyState';
import { DropdownOverlay, FilterTrigger, OptionList } from '@/src/components/Filter';
import { useTabSwipe } from '@/src/features/tabSwipe';
import { useColors } from '@/src/theme/colors';
import { layout, spacing } from '@/src/theme/layout';
import { radius } from '@/src/theme/radius';

type SortKey = 'recent' | 'recentSummary' | 'itemsDesc';
type OpenMenu = 'owner' | 'sort' | null;

const ALL_OWNERS = '__all__';

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: 'recent', label: '最近添加' },
  { value: 'recentSummary', label: '最近总结' },
  { value: 'itemsDesc', label: '集数从多到少' },
];

function sortCollections(
  list: VideoCollectionSummary[],
  sort: SortKey,
): VideoCollectionSummary[] {
  const copy = [...list];
  switch (sort) {
    case 'recent':
      return copy.sort((a, b) =>
        (b.latest_video_updated_at ?? '').localeCompare(a.latest_video_updated_at ?? ''),
      );
    case 'recentSummary':
      // 合集没有 last_summary_at，用「已总结数 / 总数」比不出来，退回最近更新
      return copy.sort((a, b) =>
        (b.last_checked_at ?? '').localeCompare(a.last_checked_at ?? ''),
      );
    case 'itemsDesc':
      return copy.sort((a, b) => b.item_count - a.item_count);
  }
}

export default function CollectionsScreen() {
  const colors = useColors();
  const router = useRouter();
  const library = useLibrary();
  const insets = useSafeAreaInsets();
  const panHandlers = useTabSwipe(1);

  const collections = useMemo(() => library.data?.collections ?? [], [library.data]);

  const [owner, setOwner] = useState<string>(ALL_OWNERS);
  const [sort, setSort] = useState<SortKey>('recent');
  const [open, setOpen] = useState<OpenMenu>(null);
  const [dropdownTop, setDropdownTop] = useState(0);
  const rowRef = useRef<View>(null);

  // UP 主选项由现有合集去重生成
  const owners = useMemo(() => {
    const counts = new Map<string, number>();
    for (const c of collections) {
      const name = c.owner_name?.trim();
      if (name) counts.set(name, (counts.get(name) ?? 0) + 1);
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([name, count]) => ({ value: name, label: name, detail: `${count}` }));
  }, [collections]);

  const visible = useMemo(() => {
    const filtered =
      owner === ALL_OWNERS
        ? collections
        : collections.filter((c) => c.owner_name === owner);
    return sortCollections(filtered, sort);
  }, [collections, owner, sort]);

  const openMenu = useCallback((menu: Exclude<OpenMenu, null>) => {
    rowRef.current?.measureInWindow((_x, y, _w, h) => setDropdownTop(y + h));
    setOpen((cur) => (cur === menu ? null : menu));
  }, []);

  return (
    // 这个页面关掉了原生 header，安全区得自己让开，否则顶部信息顶到状态栏
    <View
      {...panHandlers}
      style={{ flex: 1, backgroundColor: colors.groupedBackground, paddingTop: insets.top }}>
      <View
        ref={rowRef}
        onLayout={() => {
          if (open) rowRef.current?.measureInWindow((_x, y, _w, h) => setDropdownTop(y + h));
        }}
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: spacing.sm,
          paddingHorizontal: layout.margin,
          paddingTop: spacing.sm,
          paddingBottom: spacing.sm,
        }}>
        <FilterTrigger
          label={owner === ALL_OWNERS ? '全部 UP 主' : owner}
          active={owner !== ALL_OWNERS}
          onPress={() => openMenu('owner')}
        />
        <FilterTrigger
          label={SORT_OPTIONS.find((o) => o.value === sort)?.label ?? '最近添加'}
          onPress={() => openMenu('sort')}
        />
      </View>

      {library.loading && collections.length === 0 ? (
        <View style={{ padding: layout.margin, gap: spacing.lg }}>
          {[0, 1].map((i) => (
            <View key={i} style={{ gap: spacing.sm }}>
              <View
                style={{
                  width: '100%',
                  aspectRatio: layout.coverAspect,
                  borderRadius: radius.md,
                  backgroundColor: colors.fill,
                }}
              />
              <View style={{ width: '70%', height: 14, borderRadius: 4, backgroundColor: colors.fill }} />
            </View>
          ))}
        </View>
      ) : library.error ? (
        <EmptyState
          sf="exclamationmark.triangle"
          ion="warning-outline"
          title="加载失败"
          description={library.error}
          actionLabel="重试"
          onAction={() => void library.refresh()}
        />
      ) : collections.length === 0 ? (
        <EmptyState
          sf="rectangle.stack.badge.play"
          ion="albums-outline"
          title="还没有合集"
          description={'合集来自 B 站的多 P 视频合集。\n在「库」里新建总结时，粘贴合集中任意一集的链接即可自动识别。'}
          actionLabel="去新建总结"
          onAction={() => router.push('/new')}
        />
      ) : (
        <FlatList
          data={visible}
          keyExtractor={(item) => item.collection_id}
          contentContainerStyle={{ paddingHorizontal: layout.margin, paddingTop: spacing.sm }}
          refreshControl={
            <RefreshControl refreshing={library.refreshing} onRefresh={library.refresh} />
          }
          renderItem={({ item }) => (
            <CollectionCard
              collection={item}
              onPress={() => router.push(`/collection/${item.collection_id}`)}
            />
          )}
          ListFooterComponent={<View style={{ height: spacing.xxl }} />}
        />
      )}

      <DropdownOverlay visible={open !== null} top={dropdownTop} onClose={() => setOpen(null)}>
        {open === 'owner' ? (
          <OptionList
            options={[{ value: ALL_OWNERS, label: '全部 UP 主' }, ...owners]}
            value={owner}
            onChange={(v) => {
              setOwner(v);
              setOpen(null);
            }}
          />
        ) : null}
        {open === 'sort' ? (
          <OptionList
            options={SORT_OPTIONS}
            value={sort}
            onChange={(v) => {
              setSort(v);
              setOpen(null);
            }}
          />
        ) : null}
      </DropdownOverlay>
    </View>
  );
}
