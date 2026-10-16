// Web 走 react-native-web，它不导出 PlatformColor（拿到的会是 undefined），
// 因此单独提供一份纯 hex 实现。Metro 在 web 平台会优先解析本文件。
import { useColorScheme } from 'react-native';

import {
  hexPalette,
  type Appearance,
  type ThemeColors,
} from './palette';

export type { Appearance, SemanticColor, ThemeColors } from './palette';

export function colorsFor(appearance: Appearance): ThemeColors {
  return hexPalette[appearance] as ThemeColors;
}

export function useColors(): ThemeColors {
  const appearance: Appearance = useColorScheme() === 'dark' ? 'dark' : 'light';
  return colorsFor(appearance);
}
