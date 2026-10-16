import { View } from 'react-native';

import { spacing } from '@/src/theme/layout';
import { useTone } from '@/src/theme/tone';
import type { StateDescriptor } from '@/src/utils/status';
import { Txt } from './Txt';

interface Props {
  state: StateDescriptor;
  /** 只在处理中时显示百分比（列表里通常不需要） */
  showPercent?: boolean;
}

/** 状态圆点 + 文案 */
export function StateBadge({ state, showPercent }: Props) {
  const tone = useTone();
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.xs + 2 }}>
      <View
        style={{
          width: 7,
          height: 7,
          borderRadius: 999,
          backgroundColor: tone(state.tone),
        }}
      />
      <Txt variant="footnote" color="secondary" numberOfLines={1}>
        {state.label}
        {showPercent && state.isActive && state.progress != null ? ` ${state.progress}%` : ''}
      </Txt>
    </View>
  );
}

/** 纯圆点，用于空间紧张的行 */
export function StateDot({ state }: { state: StateDescriptor }) {
  const tone = useTone();
  return (
    <View
      style={{
        width: 7,
        height: 7,
        borderRadius: 999,
        backgroundColor: tone(state.tone),
      }}
    />
  );
}
