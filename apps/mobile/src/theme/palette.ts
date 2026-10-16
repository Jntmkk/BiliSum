import type { ColorValue } from 'react-native';

export type Appearance = 'light' | 'dark';

/**
 * 非 iOS 平台的 hex 兜底。Apple 不公布系统色的官方 hex，这里是社区逆向值，
 * 只用于 web 迭代与 Android 降级。iOS 上一律走 PlatformColor，由系统按
 * 浅色/深色与「增加对比度」等辅助功能设置解析。
 */
export const hexPalette = {
  light: {
    background: '#FFFFFF',
    groupedBackground: '#F2F2F7',
    surface: '#FFFFFF',
    raised: '#FFFFFF',
    input: '#FFFFFF',
    label: '#000000',
    secondaryLabel: 'rgba(60,60,67,0.60)',
    tertiaryLabel: 'rgba(60,60,67,0.30)',
    quaternaryLabel: 'rgba(60,60,67,0.18)',
    separator: 'rgba(60,60,67,0.29)',
    fill: 'rgba(120,120,128,0.20)',
    accent: '#007AFF',
    success: '#34C759',
    danger: '#FF3B30',
    warning: '#FF9500',
  },
  dark: {
    background: '#000000',
    groupedBackground: '#000000',
    surface: '#1C1C1E',
    raised: '#2C2C2E',
    input: '#1C1C1E',
    label: '#FFFFFF',
    secondaryLabel: 'rgba(235,235,245,0.60)',
    tertiaryLabel: 'rgba(235,235,245,0.30)',
    quaternaryLabel: 'rgba(235,235,245,0.16)',
    separator: 'rgba(84,84,88,0.60)',
    fill: 'rgba(120,120,128,0.36)',
    accent: '#0A84FF',
    success: '#30D158',
    danger: '#FF453A',
    warning: '#FF9F0A',
  },
} as const satisfies Record<Appearance, Record<string, string>>;

export type SemanticColor = keyof (typeof hexPalette)['light'];
export type ThemeColors = Record<SemanticColor, ColorValue>;
