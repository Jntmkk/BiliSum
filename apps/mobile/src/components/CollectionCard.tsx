import { View } from 'react-native';

import type { VideoCollectionSummary } from '@/src/api/client';
import { spacing } from '@/src/theme/layout';
import { Txt } from './Txt';
import { VideoCover } from './VideoCover';

interface Props {
  collection: VideoCollectionSummary;
  onPress: () => void;
}

function summaryLine(collection: VideoCollectionSummary): {
  text: string;
  color: 'accent' | 'success' | 'secondary';
} {
  const { item_count: total, summarized_count: done } = collection;
  if (total > 0 && done >= total) {
    return { text: `已总结 ${done} · 全部完成`, color: 'success' };
  }
  return {
    text: `已总结 ${done} · 未总结 ${Math.max(0, total - done)}`,
    color: 'accent',
  };
}

/** 合集卡片：16:9 封面 + 右下角「N 集」覆层 */
export function CollectionCard({ collection, onPress }: Props) {
  const line = summaryLine(collection);
  return (
    <View style={{ marginBottom: spacing.xl }}>
      <VideoCover
        uri={collection.cover_url || null}
        corner="lg"
        badge={`${collection.item_count} 集`}
        onPress={onPress}
      />
      <View style={{ marginTop: spacing.sm, gap: spacing.xs }}>
        <Txt variant="headline" numberOfLines={2} onPress={onPress} suppressHighlighting>
          {collection.title}
        </Txt>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.xs }}>
          {collection.owner_name ? (
            <Txt variant="footnote" color="secondary" numberOfLines={1} style={{ flexShrink: 1 }}>
              {collection.owner_name} ·
            </Txt>
          ) : null}
          <Txt variant="footnote" color={line.color}>
            {line.text}
          </Txt>
        </View>
      </View>
    </View>
  );
}
