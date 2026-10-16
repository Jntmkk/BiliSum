import { Platform, PlatformColor, useColorScheme } from 'react-native';

import {
  hexPalette,
  type Appearance,
  type SemanticColor,
  type ThemeColors,
} from './palette';

export type { Appearance, SemanticColor, ThemeColors } from './palette';

/** iOS 系统语义色名（UIColor 的语义色） */
const iosColorNames: Record<SemanticColor, string> = {
  background: 'systemBackground',
  groupedBackground: 'systemGroupedBackground',
  surface: 'secondarySystemBackground',
  raised: 'tertiarySystemBackground',
  input: 'tertiarySystemBackground',
  label: 'label',
  secondaryLabel: 'secondaryLabel',
  tertiaryLabel: 'tertiaryLabel',
  quaternaryLabel: 'quaternaryLabel',
  separator: 'separator',
  fill: 'systemFill',
  accent: 'systemBlue',
  success: 'systemGreen',
  danger: 'systemRed',
  warning: 'systemOrange',
};

// PlatformColor 自带浅深色解析，与 appearance 无关，构建一次复用
let iosColors: ThemeColors | null = null;

function iosThemeColors(): ThemeColors {
  if (!iosColors) {
    const built = {} as ThemeColors;
    for (const key of Object.keys(iosColorNames) as SemanticColor[]) {
      built[key] = PlatformColor(iosColorNames[key]);
    }
    iosColors = built;
  }
  return iosColors;
}

/** 供导航 options 等非 hook 场景使用 */
export function colorsFor(appearance: Appearance): ThemeColors {
  if (Platform.OS === 'ios') return iosThemeColors();
  return hexPalette[appearance] as ThemeColors;
}

export function useColors(): ThemeColors {
  const appearance: Appearance = useColorScheme() === 'dark' ? 'dark' : 'light';
  return colorsFor(appearance);
}
