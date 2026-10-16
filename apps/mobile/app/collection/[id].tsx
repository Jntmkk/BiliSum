import { useMemo, useState } from 'react';
import { ActivityIndicator, Platform, Pressable, ScrollView, TextInput, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

import { getCollection } from '@/src/api/client';
import { useAsync } from '@/src/api/useAsync';
import { Card } from '@/src/components/Card';
import { EmptyState } from '@/src/components/EmptyState';
import { EpisodeRow } from '@/src/components/EpisodeRow';
import { Icon } from '@/src/components/Icon';
import { ProgressBar } from '@/src/components/ProgressBar';
import { Txt } from '@/src/components/Txt';
import { VideoCover } from '@/src/components/VideoCover';
import { useColors } from '@/src/theme/colors';
import { layout, spacing } from '@/src/theme/layout';
import { radius } from '@/src/theme/radius';
import { taskStatusLabel } from '@/src/utils/status';
import type { VideoCollectionItem } from '@/src/api/client';

/** 匹配标题 / BV 号 / 第几集，与桌面端合集详情页的搜索框一致 */
function matchItem(item: VideoCollectionItem, raw: string): boolean {
  const q = raw.trim().toLowerCase();
  if (!q) return true;
  if (item.title.toLowerCase().includes(q)) return true;
  if (item.bvid.toLowerCase().includes(q)) return true;
  return (
    String(item.position).includes(q) ||
    `第${item.position}集`.includes(q) ||
    `第${item.position}话` === q
  );
}

export default function CollectionDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const colors = useColors();
  const router = useRouter();
  const [search, setSearch] = useState('');

  const { data, loading, error, refresh } = useAsync(() => getCollection(id), [id]);

  // 合集有分区时按分区标题分组，否则平铺
  const groups = useMemo(() => {
    const items = (data?.items ?? []).filter((i) => matchItem(i, search));
    if (!items.some((i) => i.source_section_title)) {
      return [{ title: null as string | null, items }];
    }
    const map = new Map<string, VideoCollectionItem[]>();
    for (const item of items) {
      const key = item.source_section_title ?? '其他';
      const list = map.get(key);
      if (list) list.push(item);
      else map.set(key, [item]);
    }
    return [...map.entries()].map(([title, items]) => ({ title, items }));
  }, [data, search]);

  if (loading) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  if (error || !data) {
    return (
      <EmptyState
        sf="exclamationmark.triangle"
        ion="warning-outline"
        title="加载失败"
        description={error ?? '合集不存在'}
        actionLabel="重试"
        onAction={refresh}
      />
    );
  }

  const total = data.item_count || data.items.length;
  const done = data.summarized_count;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  let rowIndex = 0;

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.groupedBackground }}
      contentContainerStyle={{ paddingBottom: spacing.xxl }}>
      {/*
        头部整块铺 surface 卡片色，让「封面/标题/作者/进度」和下方条目卡片同色系，
        只剩分组底色一档落差；之前是系统 header 灰直接接列表底，跳变太硬。
        封面用 corner="none" 由这块裁剪左上/右上圆角，底部圆角由块自己收。
      */}
      <View
        style={{
          backgroundColor: colors.surface,
          borderBottomLeftRadius: radius.lg,
          borderBottomRightRadius: radius.lg,
          overflow: 'hidden',
          paddingBottom: spacing.md,
          marginBottom: spacing.md,
        }}>
        <VideoCover uri={data.cover_url || null} corner="none" />
        <View style={{ paddingHorizontal: layout.margin, paddingTop: spacing.md, gap: spacing.xs }}>
          {/* 与视频详情页保持一致：详情页主标题用 title3（20pt），不抢封面的视觉重心 */}
          <Txt variant="title3">{data.title}</Txt>
          <Txt variant="subheadline" color="secondary">
            {data.owner_name ? `${data.owner_name} · ` : ''}
            {total} 集
          </Txt>
          <View style={{ gap: spacing.xs, marginTop: spacing.xs }}>
            <ProgressBar value={pct} height={5} />
            <Txt variant="footnote" color="secondary">
              已总结 {done}/{total}
            </Txt>
          </View>
        </View>
      </View>

      {/* 合集条目受 B 站合集规模限制（几十~几百），一次全量加载后在本地过滤即可 */}
      <View style={{ paddingHorizontal: layout.margin, marginBottom: spacing.md }}>
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            gap: spacing.sm,
            paddingHorizontal: spacing.md,
            height: 36,
            borderRadius: radius.md,
            backgroundColor: colors.fill,
          }}>
          <Icon sf="magnifyingglass" ion="search" size={16} color={colors.secondaryLabel} />
          <TextInput
            value={search}
            onChangeText={setSearch}
            placeholder="搜索标题、BV号或第几集"
            placeholderTextColor={colors.secondaryLabel}
            autoCapitalize="none"
            autoCorrect={false}
            clearButtonMode="while-editing"
            style={{ flex: 1, color: colors.label, fontSize: 15 }}
          />
          {search.length > 0 && Platform.OS !== 'ios' ? (
            <Pressable onPress={() => setSearch('')} hitSlop={8}>
              <Icon sf="xmark.circle.fill" ion="close-circle" size={16} color={colors.secondaryLabel} />
            </Pressable>
          ) : null}
        </View>
      </View>

      {groups.every((g) => g.items.length === 0) ? (
        <EmptyState
          sf="magnifyingglass"
          ion="search"
          title="没有匹配的条目"
          description="试试其它关键词，或清空搜索框"
        />
      ) : null}

      {groups.map((group, gi) => (
        <View key={group.title ?? gi} style={{ marginBottom: spacing.lg }}>
          {group.title ? (
            <Txt
              variant="footnote"
              color="secondary"
              style={{
                paddingHorizontal: layout.margin + spacing.xs,
                marginBottom: spacing.sm,
              }}>
              {group.title}
            </Txt>
          ) : null}
          <Card>
            {group.items.map((item) => {
              const first = rowIndex === 0;
              rowIndex += 1;
              return (
                <EpisodeRow
                  key={`${item.bvid}-${item.position}`}
                  first={first}
                  position={item.position}
                  title={item.title}
                  disabled={!item.video_id}
                  onPress={
                    item.video_id ? () => router.push(`/video/${item.video_id}`) : undefined
                  }
                  subtitle={
                    <Txt
                      variant="footnote"
                      color={item.has_result ? 'success' : 'secondary'}>
                      {item.has_result
                        ? '已生成摘要'
                        : item.latest_status
                          ? taskStatusLabel(item.latest_status)
                          : '尚未生成摘要'}
                    </Txt>
                  }
                />
              );
            })}
          </Card>
        </View>
      ))}
    </ScrollView>
  );
}
