import type { ReactNode } from 'react';
import { Pressable, View, type StyleProp, type ViewStyle } from 'react-native';

import { useColors } from '@/src/theme/colors';
import { layout, spacing } from '@/src/theme/layout';
import { radius } from '@/src/theme/radius';
import { Txt } from './Txt';

export type SeparatorInset = 'none' | 'content';

interface CardProps {
  children?: ReactNode;
  /** 是否加 16pt 屏幕边距；页面级 grouped 卡片保留，内嵌卡片关掉 */
  inset?: boolean;
  corner?: keyof typeof radius;
  style?: StyleProp<ViewStyle>;
}

/** grouped inset 卡片容器 */
export function Card({ children, inset = true, corner = 'md', style }: CardProps) {
  const colors = useColors();
  return (
    <View
      style={[
        {
          backgroundColor: colors.surface,
          borderRadius: radius[corner],
          overflow: 'hidden',
        },
        inset && { marginHorizontal: layout.margin },
        style,
      ]}>
      {children}
    </View>
  );
}

interface SectionProps {
  title?: string;
  /** 标题右侧的补充说明 */
  caption?: string;
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
}

/** 分组标题 + 卡片，iOS grouped 列表的标准结构 */
export function Section({ title, caption, children, style }: SectionProps) {
  return (
    <View style={[{ marginBottom: spacing.xl }, style]}>
      {title ? (
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'baseline',
            justifyContent: 'space-between',
            paddingHorizontal: layout.margin + spacing.xs,
            marginBottom: spacing.sm,
          }}>
          <Txt variant="footnote" color="secondary">
            {title}
          </Txt>
          {caption ? (
            <Txt variant="footnote" color="tertiary">
              {caption}
            </Txt>
          ) : null}
        </View>
      ) : null}
      {children}
    </View>
  );
}

interface RowProps {
  children: ReactNode;
  onPress?: () => void;
  /** hairline 左侧是否缩进到正文起点 */
  separatorInset?: SeparatorInset;
  /** 卡片首行不画 hairline */
  first?: boolean;
  style?: StyleProp<ViewStyle>;
  disabled?: boolean;
  minHeight?: number;
}

/** grouped 卡片内的一行 */
export function Row({
  children,
  onPress,
  separatorInset = 'content',
  first = false,
  style,
  disabled,
  minHeight = layout.listRowMinHeight,
}: RowProps) {
  const colors = useColors();
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || !onPress}
      style={({ pressed }) => [
        {
          minHeight,
          justifyContent: 'center',
          paddingHorizontal: layout.margin,
          paddingVertical: spacing.sm,
          opacity: disabled ? 0.4 : 1,
          backgroundColor: pressed && onPress ? colors.fill : 'transparent',
        },
        !first && {
          borderTopWidth: layout.hairline,
          borderTopColor: colors.separator,
          marginLeft: separatorInset === 'none' ? 0 : layout.margin,
          paddingLeft: separatorInset === 'none' ? layout.margin : 0,
        },
        style,
      ]}>
      {children}
    </Pressable>
  );
}

/** 卡片内自定义内容之间的分隔线 */
export function Separator({ inset = 'content' }: { inset?: SeparatorInset }) {
  const colors = useColors();
  return (
    <View
      style={{
        height: layout.hairline,
        backgroundColor: colors.separator,
        marginLeft: inset === 'none' ? 0 : layout.margin,
      }}
    />
  );
}
