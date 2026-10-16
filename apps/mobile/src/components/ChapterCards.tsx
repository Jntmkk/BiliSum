import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, View } from 'react-native';

import type { TaskResult } from '@/src/api/client';
import { Card, Separator } from '@/src/components/Card';
import { Icon } from '@/src/components/Icon';
import { SeekTime } from '@/src/components/SeekTime';
import { Txt } from '@/src/components/Txt';
import { buildChapterGroups, type ChapterGroup } from '@/src/features/chapters';
import { useColors } from '@/src/theme/colors';
import { layout, spacing } from '@/src/theme/layout';

interface Props {
  result: TaskResult;
  /** 传了才允许点时间跳转（非 B 站/YouTube 源不给） */
  onSeek?: (seconds: number) => void;
}

/**
 * 章节知识卡片：服务端把章节按主题聚成组，这里按 iOS grouped 列表的样式渲染成
 * 可折叠的分组卡片，组内每个小章节带可跳转的时间点。
 */
export function ChapterCards({ result, onSeek }: Props) {
  const groups = useMemo(() => buildChapterGroups(result), [result]);
  const [expanded, setExpanded] = useState<string[]>([]);

  const signature = useMemo(() => groups.map((g) => g.id).join('|'), [groups]);
  const signatureRef = useRef('');

  // 与桌面端一致：保留已展开的组；都收起了就把第一组展开，避免全是折叠态
  useEffect(() => {
    const visible = new Set(groups.map((g) => g.id));
    setExpanded((current) => {
      const kept = current.filter((id) => visible.has(id));
      if (!groups.length) return [];
      if (kept.length > 0 || signatureRef.current === signature) return kept;
      return [groups[0].id];
    });
    signatureRef.current = signature;
  }, [groups, signature]);

  const allExpanded = groups.length > 0 && expanded.length === groups.length;

  const toggleAll = useCallback(() => {
    setExpanded(allExpanded ? [] : groups.map((g) => g.id));
  }, [allExpanded, groups]);

  const toggleOne = useCallback((groupId: string) => {
    setExpanded((current) =>
      current.includes(groupId) ? current.filter((id) => id !== groupId) : [...current, groupId],
    );
  }, []);

  if (!groups.length) return null;

  const chapterCount = groups.reduce((sum, group) => sum + group.items.length, 0);

  return (
    <View style={{ gap: spacing.sm }}>
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          paddingHorizontal: layout.margin + spacing.xs,
        }}>
        <Txt variant="footnote" color="secondary">
          章节 · {chapterCount} 条
        </Txt>
        <Pressable onPress={toggleAll} hitSlop={8}>
          <Txt variant="footnote" color="accent">
            {allExpanded ? '全部收起' : '全部展开'}
          </Txt>
        </Pressable>
      </View>

      {groups.map((group) => (
        <ChapterGroupCard
          key={group.id}
          group={group}
          open={expanded.includes(group.id)}
          onToggle={() => toggleOne(group.id)}
          onSeek={onSeek}
        />
      ))}
    </View>
  );
}

function ChapterGroupCard({
  group,
  open,
  onToggle,
  onSeek,
}: {
  group: ChapterGroup;
  open: boolean;
  onToggle: () => void;
  onSeek?: (seconds: number) => void;
}) {
  const colors = useColors();

  return (
    <Card>
      <Pressable
        onPress={onToggle}
        style={({ pressed }) => ({
          flexDirection: 'row',
          alignItems: 'center',
          gap: spacing.md,
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.md,
          backgroundColor: pressed ? colors.fill : 'transparent',
        })}>
        <View style={{ flex: 1 }}>
          <Txt variant="subheadline" style={{ fontWeight: '600' }}>
            {group.title}
          </Txt>
          {group.meta ? (
            <Txt variant="caption1" color="tertiary" style={{ marginTop: 2 }}>
              {group.meta}
            </Txt>
          ) : null}
        </View>
        <Icon
          sf={open ? 'chevron.down' : 'chevron.right'}
          ion={open ? 'chevron-down' : 'chevron-forward'}
          size={13}
          weight="semibold"
          color={colors.tertiaryLabel}
        />
      </Pressable>

      {open
        ? group.items.map((item, index) => (
            <View key={item.id}>
              <Separator inset="none" />
              <View
                style={{
                  flexDirection: 'row',
                  gap: spacing.md,
                  paddingHorizontal: spacing.md,
                  paddingVertical: spacing.md,
                }}>
                <SeekTime
                  seconds={item.timestampSeconds}
                  onSeek={onSeek}
                  style={{ width: 44, alignItems: 'flex-end', paddingTop: 2 }}
                />
                <View style={{ flex: 1 }}>
                  <Txt variant="subheadline" style={{ fontWeight: '600', marginBottom: 3 }}>
                    {item.title}
                  </Txt>
                  <Txt variant="footnote" color="secondary" style={{ lineHeight: 20 }}>
                    {item.content}
                  </Txt>
                </View>
              </View>
            </View>
          ))
        : null}
    </Card>
  );
}
