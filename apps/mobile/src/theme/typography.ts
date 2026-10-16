import { PixelRatio, type TextStyle } from 'react-native';

export type TextVariant =
  | 'largeTitle'
  | 'title1'
  | 'title2'
  | 'title3'
  | 'headline'
  | 'body'
  | 'callout'
  | 'subheadline'
  | 'footnote'
  | 'caption1'
  | 'caption2';

type Weight = '400' | '500' | '600' | '700';

interface VariantSpec {
  fontSize: number;
  lineHeight: number;
  fontWeight: Weight;
  letterSpacing?: number;
}

/**
 * iOS Dynamic Type 阶（pt）。fontFamily 留空即 SF Pro。
 * lineHeight 取 HIG 的 default leading。
 */
const SPEC: Record<TextVariant, VariantSpec> = {
  largeTitle: { fontSize: 34, lineHeight: 41, fontWeight: '700', letterSpacing: -0.5 },
  title1: { fontSize: 28, lineHeight: 34, fontWeight: '700', letterSpacing: -0.4 },
  title2: { fontSize: 22, lineHeight: 28, fontWeight: '700', letterSpacing: -0.3 },
  title3: { fontSize: 20, lineHeight: 25, fontWeight: '600', letterSpacing: -0.2 },
  headline: { fontSize: 17, lineHeight: 22, fontWeight: '600' },
  body: { fontSize: 17, lineHeight: 22, fontWeight: '400' },
  callout: { fontSize: 16, lineHeight: 21, fontWeight: '400' },
  subheadline: { fontSize: 15, lineHeight: 20, fontWeight: '400' },
  footnote: { fontSize: 13, lineHeight: 18, fontWeight: '400' },
  caption1: { fontSize: 12, lineHeight: 16, fontWeight: '400' },
  caption2: { fontSize: 11, lineHeight: 13, fontWeight: '400' },
};

/**
 * RN 会按 allowFontScaling 自动放大 fontSize，但显式写死的 lineHeight 不会跟着放大，
 * 于是大字号下文本会被行高截断。这里按当前字体缩放倍数把 lineHeight 一起放大。
 * web 上 getFontScale() 恒为 1，等价于原值。
 */
function scaledLineHeight(base: number): number {
  const scale = PixelRatio.getFontScale();
  return scale === 1 ? base : Math.round(base * scale * 100) / 100;
}

export function typographyFor(variant: TextVariant): TextStyle {
  const spec = SPEC[variant];
  return {
    fontSize: spec.fontSize,
    lineHeight: scaledLineHeight(spec.lineHeight),
    fontWeight: spec.fontWeight,
    ...(spec.letterSpacing != null ? { letterSpacing: spec.letterSpacing } : null),
  };
}

/** 紧凑布局用：限制放大上限，避免撑破固定高度容器 */
export function maxFontScale(multiplier: number): { maxFontSizeMultiplier: number } {
  return { maxFontSizeMultiplier: multiplier };
}

export { SPEC as typographySpec };
