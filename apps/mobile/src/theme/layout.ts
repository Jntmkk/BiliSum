import { StyleSheet } from 'react-native';

/** 8pt 网格，4pt 为半步 */
export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const layout = {
  /** 屏幕左右标准边距 */
  margin: 16,
  /** HIG 最小触控区 */
  touchTarget: 44,
  /** 列表行最小高度 */
  listRowMinHeight: 44,
  /** 网格封面间距 */
  gridGutter: 12,
  /** B 站原生封面比例 */
  coverAspect: 16 / 9,
  /** 1px 分隔线 */
  hairline: StyleSheet.hairlineWidth,
} as const;
