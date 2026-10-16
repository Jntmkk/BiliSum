import { useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  type ColorValue,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

import { useColors } from '@/src/theme/colors';
import { layout, spacing } from '@/src/theme/layout';
import { radius } from '@/src/theme/radius';
import { Txt } from './Txt';
import { Icon } from './Icon';
import type { TextVariant } from '@/src/theme/typography';

export type ButtonStyleKind = 'filled' | 'tinted' | 'plain' | 'destructive';
export type ButtonSize = 'regular' | 'large';

interface Props {
  title: string;
  onPress?: () => void;
  kind?: ButtonStyleKind;
  size?: ButtonSize;
  /** 前缀图标（SF Symbol / Ionicons 降级名） */
  sf?: React.ComponentProps<typeof Icon>['sf'];
  ion?: React.ComponentProps<typeof Icon>['ion'];
  disabled?: boolean;
  loading?: boolean;
  /** 撑满可用宽度 */
  fill?: boolean;
  style?: StyleProp<ViewStyle>;
}

/** iOS 的四种按钮样式（filled / tinted / plain / destructive） */
export function Button({
  title,
  onPress,
  kind = 'filled',
  size = 'regular',
  sf,
  ion,
  disabled,
  loading,
  fill,
  style,
}: Props) {
  const colors = useColors();
  const [focused, setFocused] = useState(false);

  const height = size === 'large' ? 50 : layout.touchTarget;
  const { background, foreground } = palette(colors, kind);

  const labelVariant: TextVariant = size === 'large' ? 'headline' : 'body';

  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || loading}
      onPressIn={() => setFocused(true)}
      onPressOut={() => setFocused(false)}
      style={({ pressed }) => [
        styles.base,
        {
          height,
          backgroundColor: background,
          opacity: disabled ? 0.4 : pressed || focused ? 0.75 : 1,
        },
        fill && styles.fill,
        style,
      ]}>
      {loading ? (
        <ActivityIndicator size="small" color={foreground} />
      ) : (
        sf &&
        ion && <Icon sf={sf} ion={ion} size={size === 'large' ? 19 : 17} color={foreground} />
      )}
      <Txt variant={labelVariant} style={{ color: foreground }}>
        {title}
      </Txt>
    </Pressable>
  );
}

function palette(
  colors: ReturnType<typeof useColors>,
  kind: ButtonStyleKind,
): { background: ColorValue; foreground: ColorValue } {
  switch (kind) {
    case 'filled':
      return { background: colors.accent, foreground: '#FFFFFF' };
    case 'tinted':
      return { background: colors.fill, foreground: colors.accent };
    case 'destructive':
      return { background: colors.danger, foreground: '#FFFFFF' };
    case 'plain':
      return { background: 'transparent', foreground: colors.accent };
  }
}

const styles = StyleSheet.create({
  base: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
  },
  fill: {
    alignSelf: 'stretch',
  },
});
