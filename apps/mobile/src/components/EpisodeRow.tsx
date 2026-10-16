import type { ReactNode } from 'react';
import { Pressable, View } from 'react-native';

import { useColors } from '@/src/theme/colors';
import { layout, spacing } from '@/src/theme/layout';
import { Icon } from './Icon';
import { Txt } from './Txt';

interface Props {
  /** 合集内的序号，右对齐等宽 */
  position: number;
  title: string;
  /** 副行：状态文案 */
  subtitle?: ReactNode;
  onPress?: () => void;
  /** 还没物化成视频资产，不可点 */
  disabled?: boolean;
  first?: boolean;
}

/** 合集详情里的一集：序号 + 标题 + 状态 + chevron */
export function EpisodeRow({
  position,
  title,
  subtitle,
  onPress,
  disabled,
  first = false,
}: Props) {
  const colors = useColors();
  return (
    <Pressable
      onPress={disabled ? undefined : onPress}
      disabled={disabled || !onPress}
      style={({ pressed }) => [
        {
          flexDirection: 'row',
          alignItems: 'center',
          gap: spacing.md,
          minHeight: 56,
          paddingVertical: spacing.sm,
          paddingHorizontal: layout.margin,
          opacity: disabled ? 0.45 : 1,
          backgroundColor: pressed ? colors.fill : 'transparent',
        },
        !first && {
          borderTopWidth: layout.hairline,
          borderTopColor: colors.separator,
          marginLeft: layout.margin,
          paddingLeft: 0,
        },
      ]}>
      <Txt variant="body" color="tertiary" style={{ minWidth: 20, fontVariant: ['tabular-nums'] }}>
        {position}
      </Txt>
      <View style={{ flex: 1, gap: 2 }}>
        <Txt variant="body" numberOfLines={2}>
          {title}
        </Txt>
        {subtitle ? (
          <Txt variant="footnote" color="secondary" numberOfLines={1}>
            {subtitle}
          </Txt>
        ) : null}
      </View>
      {!disabled && onPress ? (
        <Icon sf="chevron.right" ion="chevron-forward" size={14} color={colors.tertiaryLabel} />
      ) : null}
    </Pressable>
  );
}
