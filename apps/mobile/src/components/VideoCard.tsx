import { Pressable, View, type StyleProp, type ViewStyle } from 'react-native';

import type { VideoAssetSummary } from '@/src/api/client';
import { useColors } from '@/src/theme/colors';
import { layout, spacing } from '@/src/theme/layout';
import { radius } from '@/src/theme/radius';
import { formatClock } from '@/src/utils/format';
import { videoState } from '@/src/utils/status';
import { ProgressBar } from './ProgressBar';
import { StateBadge } from './StateBadge';
import { Txt } from './Txt';
import { VideoCover } from './VideoCover';

/** 封面右下角角标：多 P 显示 nP，否则显示时长 */
function coverBadge(asset: VideoAssetSummary): string | undefined {
  const pageCount = asset.pages?.length ?? 0;
  if (pageCount > 1) return `${pageCount}P`;
  return formatClock(asset.duration) || undefined;
}

interface CardProps {
  asset: VideoAssetSummary;
  onPress: () => void;
  /** 处理中任务的进度百分比 */
  progress?: number;
  style?: StyleProp<ViewStyle>;
}

/** 网格视图卡片 */
export function VideoCard({ asset, onPress, progress, style }: CardProps) {
  const state = videoState(asset);
  const badge = coverBadge(asset);

  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [{ opacity: pressed ? 0.7 : 1 }, style]}>
      <VideoCover uri={asset.cover_url || null} badge={badge} />
      <Txt
        variant="subheadline"
        numberOfLines={2}
        style={{ marginTop: spacing.sm, minHeight: 40, lineHeight: 20 }}>
        {asset.title}
      </Txt>
      <View style={{ marginTop: spacing.xs }}>
        <StateBadge state={{ ...state, progress }} showPercent />
        {state.isActive && progress != null ? <ProgressBar value={progress} /> : null}
      </View>
    </Pressable>
  );
}

/** 列表视图行：缩略图 + 标题 + 状态 + chevron */
export function VideoRow({ asset, onPress, progress, style }: CardProps) {
  const colors = useColors();
  const state = videoState(asset);
  const badge = coverBadge(asset);

  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        {
          flexDirection: 'row',
          alignItems: 'center',
          gap: spacing.md,
          paddingVertical: spacing.sm + 2,
          backgroundColor: pressed ? colors.fill : 'transparent',
        },
        style,
      ]}>
      <View style={{ width: 112 }}>
        <VideoCover uri={asset.cover_url || null} corner="sm" badge={badge} />
      </View>
      <View style={{ flex: 1, gap: spacing.xs }}>
        <Txt variant="subheadline" numberOfLines={2}>
          {asset.title}
        </Txt>
        <StateBadge state={{ ...state, progress }} showPercent />
        {state.isActive && progress != null ? <ProgressBar value={progress} /> : null}
      </View>
    </Pressable>
  );
}

/** 库页列表视图里的行容器（带 hairline + 左右边距） */
export function VideoListRow({ asset, onPress, progress }: CardProps) {
  const colors = useColors();
  return (
    <View
      style={{
        paddingHorizontal: layout.margin,
        borderBottomWidth: layout.hairline,
        borderBottomColor: colors.separator,
      }}>
      <VideoRow asset={asset} onPress={onPress} progress={progress} />
    </View>
  );
}

export const videoCardMetrics = {
  /** 两列网格：屏幕宽 - 左右边距 - 中间 gutter，再对半 */
  columnGap: layout.gridGutter,
  radius: radius.md,
};
