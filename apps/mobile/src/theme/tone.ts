import type { ColorValue } from 'react-native';

import type { Tone } from '@/src/utils/status';
import { useColors, type ThemeColors } from './colors';

export function toneColor(colors: ThemeColors, tone: Tone): ColorValue {
  switch (tone) {
    case 'active':
      return colors.warning;
    case 'ok':
      return colors.success;
    case 'bad':
      return colors.danger;
    case 'muted':
      return colors.tertiaryLabel;
  }
}

export function useTone(): (tone: Tone) => ColorValue {
  const colors = useColors();
  return (tone: Tone) => toneColor(colors, tone);
}
