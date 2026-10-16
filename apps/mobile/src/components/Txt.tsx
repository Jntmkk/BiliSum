import { Text, type TextProps, type TextStyle } from 'react-native';

import { useColors } from '@/src/theme/colors';
import { typographyFor, type TextVariant } from '@/src/theme/typography';

interface Props extends TextProps {
  variant?: TextVariant;
  /** token 语义名或任意色值；不传则跟随系统 label 色 */
  color?: 'label' | 'secondary' | 'tertiary' | 'accent' | 'success' | 'danger' | 'warning' | (string & {});
  center?: boolean;
}

const TOKEN_KEYS = {
  label: 'label',
  secondary: 'secondaryLabel',
  tertiary: 'tertiaryLabel',
  accent: 'accent',
  success: 'success',
  danger: 'danger',
  warning: 'warning',
} as const;

export function Txt({
  variant = 'body',
  color = 'label',
  center,
  style,
  ...rest
}: Props) {
  const colors = useColors();
  const tokenKey = TOKEN_KEYS[color as keyof typeof TOKEN_KEYS];
  const resolved = tokenKey ? colors[tokenKey] : color;

  const base: TextStyle = {
    ...typographyFor(variant),
    color: resolved as TextStyle['color'],
    ...(center ? { textAlign: 'center' } : null),
  };

  return <Text {...rest} style={[base, style]} />;
}
