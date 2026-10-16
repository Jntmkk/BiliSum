import { View } from 'react-native';

import { useColors } from '@/src/theme/colors';
import { layout, spacing } from '@/src/theme/layout';
import { radius } from '@/src/theme/radius';
import { CoverSkeleton } from './VideoCover';

function Bar({ width, height = 12 }: { width: number | `${number}%`; height?: number }) {
  const colors = useColors();
  return (
    <View
      style={{
        width,
        height,
        borderRadius: radius.sm / 2,
        backgroundColor: colors.fill,
      }}
    />
  );
}

/** 库页网格骨架：2 列 × n 行，尺寸与真实卡片一致以免加载完成时跳动 */
export function GridSkeleton({ columns = 2, rows = 3 }: { columns?: number; rows?: number }) {
  return (
    <View
      style={{
        flexDirection: 'row',
        flexWrap: 'wrap',
        paddingHorizontal: layout.margin,
        columnGap: layout.gridGutter,
        rowGap: spacing.xl,
      }}>
      {Array.from({ length: columns * rows }).map((_, i) => (
        <View
          key={i}
          style={{ width: `${100 / columns}%`, marginLeft: i % columns === 0 ? 0 : undefined }}>
          <CoverSkeleton />
          <View style={{ marginTop: spacing.sm, gap: spacing.xs }}>
            <Bar width="92%" />
            <Bar width="60%" />
          </View>
        </View>
      ))}
    </View>
  );
}

/** 列表骨架 */
export function ListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <View style={{ paddingHorizontal: layout.margin, gap: spacing.lg }}>
      {Array.from({ length: rows }).map((_, i) => (
        <View key={i} style={{ flexDirection: 'row', gap: spacing.md, alignItems: 'center' }}>
          <View style={{ width: 112 }}>
            <CoverSkeleton />
          </View>
          <View style={{ flex: 1, gap: spacing.sm }}>
            <Bar width="88%" />
            <Bar width="45%" height={10} />
          </View>
        </View>
      ))}
    </View>
  );
}
