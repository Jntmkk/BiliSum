import SegmentedControl, {
  type NativeSegmentedControlIOSChangeEvent,
} from '@react-native-segmented-control/segmented-control';
import type { NativeSyntheticEvent } from 'react-native';

import { useColors } from '@/src/theme/colors';

interface Props<T extends string> {
  values: { key: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}

/**
 * 包一层真正的 UISegmentedControl。文字色只能通过 fontStyle /
 * activeFontStyle 传，没有独立的 textColor prop。
 * 包一层函数组件是为了适配 RN 0.88 的函数组件类型（原包还是 class 组件声明）。
 */
export function Segmented<T extends string>({ values, value, onChange }: Props<T>) {
  const colors = useColors();
  const index = Math.max(
    0,
    values.findIndex((v) => v.key === value),
  );

  return (
    <SegmentedControl
      values={values.map((v) => v.label)}
      selectedIndex={index}
      onChange={(e: NativeSyntheticEvent<NativeSegmentedControlIOSChangeEvent>) => {
        const next = values[e.nativeEvent.selectedSegmentIndex];
        if (next) onChange(next.key);
      }}
      backgroundColor={String(colors.fill)}
      tintColor={String(colors.surface)}
      fontStyle={{ color: String(colors.label) }}
      activeFontStyle={{ color: String(colors.label), fontWeight: '600' }}
      style={{ height: 32, width: '100%' }}
    />
  );
}
