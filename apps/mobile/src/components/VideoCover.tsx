import { Image } from 'expo-image';
import { Pressable, View } from 'react-native';

import { resolveMediaUrl } from '@/src/api/media';
import { useServerUrl } from '@/src/store/settings';
import { useColors } from '@/src/theme/colors';
import { layout } from '@/src/theme/layout';
import { radius } from '@/src/theme/radius';
import { Txt } from './Txt';

interface Props {
  /** 接口返回的封面路径，可能是相对路径；绝对 URL 也支持 */
  uri: string | null | undefined;
  /** 16:9 横封面 */
  aspect?: number;
  /** 'none' 交给父级裁剪（如顶部通栏 hero 块），自己不要圆角 */
  corner?: keyof typeof radius | 'none';
  /** 右下角覆层文字：时长 / nP / N 集 */
  badge?: string;
  onPress?: () => void;
}

export function VideoCover({
  uri,
  aspect = layout.coverAspect,
  corner = 'md',
  badge,
  onPress,
}: Props) {
  const colors = useColors();
  const base = useServerUrl();
  const src = resolveMediaUrl(base, uri);

  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      style={{
        width: '100%',
        aspectRatio: aspect,
        borderRadius: corner === 'none' ? 0 : radius[corner],
        overflow: 'hidden',
        backgroundColor: colors.fill,
      }}>
      {src ? (
        <Image
          source={{ uri: src }}
          style={{ width: '100%', height: '100%' }}
          contentFit="cover"
          transition={120}
          cachePolicy="memory-disk"
        />
      ) : null}
      {badge ? (
        <View
          style={{
            position: 'absolute',
            right: 6,
            bottom: 6,
            paddingHorizontal: 6,
            paddingVertical: 2,
            borderRadius: 5,
            backgroundColor: 'rgba(0,0,0,0.65)',
          }}>
          <Txt variant="caption2" style={{ color: '#FFFFFF', fontVariant: ['tabular-nums'] }}>
            {badge}
          </Txt>
        </View>
      ) : null}
    </Pressable>
  );
}

/** 骨架占位，保持与封面相同比例避免布局跳动 */
export function CoverSkeleton({ aspect = layout.coverAspect }: { aspect?: number }) {
  const colors = useColors();
  return (
    <View
      style={{
        width: '100%',
        aspectRatio: aspect,
        borderRadius: radius.md,
        backgroundColor: colors.fill,
      }}
    />
  );
}
