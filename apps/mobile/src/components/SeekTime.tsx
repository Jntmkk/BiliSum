import { Pressable, type StyleProp, type ViewStyle } from 'react-native';

import { Txt } from '@/src/components/Txt';
import { formatClock } from '@/src/utils/format';

interface Props {
  seconds: number | null | undefined;
  /** 传了才可点；不可点时降为次要色，避免误以为能跳 */
  onSeek?: (seconds: number) => void;
  style?: StyleProp<ViewStyle>;
}

/**
 * 可点击的章节时间点。点一下让内嵌播放器跳到对应秒数，
 * 不可跳（非 B 站/YouTube 源，或没有时间点）时只当普通文字展示。
 */
export function SeekTime({ seconds, onSeek, style }: Props) {
  const seekable = onSeek != null && seconds != null;
  const text = formatClock(seconds);
  if (!text) return null;

  return (
    <Pressable
      onPress={seekable ? () => onSeek(seconds) : undefined}
      disabled={!seekable}
      hitSlop={6}
      style={style}>
      <Txt
        variant="footnote"
        color={seekable ? 'accent' : 'secondary'}
        style={{
          fontVariant: ['tabular-nums'],
          fontWeight: '600',
          textDecorationLine: seekable ? 'underline' : 'none',
          opacity: seekable ? 1 : 0.65,
        }}>
        {text}
      </Txt>
    </Pressable>
  );
}
