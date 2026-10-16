import { View } from 'react-native';

import { useColors } from '@/src/theme/colors';

interface Props {
  /** 0-100；不确定进度传 undefined 走系统色 */
  value?: number;
  height?: number;
}

export function ProgressBar({ value, height = 3 }: Props) {
  const colors = useColors();
  const pct = Math.max(0, Math.min(100, value ?? 0));
  return (
    <View
      style={{
        height,
        borderRadius: 999,
        backgroundColor: colors.fill,
        overflow: 'hidden',
      }}>
      <View
        style={{
          width: `${pct}%`,
          height: '100%',
          borderRadius: 999,
          backgroundColor: colors.accent,
        }}
      />
    </View>
  );
}
