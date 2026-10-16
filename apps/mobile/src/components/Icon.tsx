import { Ionicons } from '@expo/vector-icons';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { Platform, type ColorValue, type StyleProp, type ViewStyle } from 'react-native';

type IoniconName = React.ComponentProps<typeof Ionicons>['name'];

interface Props {
  /** SF Symbol 名，仅 iOS 生效 */
  sf: SymbolViewProps['name'];
  /** 非 iOS 平台的降级图标 */
  ion: IoniconName;
  size?: number;
  color?: ColorValue;
  weight?: SymbolViewProps['weight'];
  style?: StyleProp<ViewStyle>;
}

/**
 * expo-symbols 只在 name 是 {ios,android,web} 对象时才非 iOS 生效，
 * 传字符串会渲染 fallback。所以这里显式分平台：iOS 用真 SF Symbols，
 * 其余平台用 Ionicons，省得为每个图标写三种名字。
 */
export function Icon({ sf, ion, size = 20, color, weight = 'regular', style }: Props) {
  if (Platform.OS === 'ios') {
    return (
      <SymbolView
        name={sf}
        size={size}
        tintColor={color}
        weight={weight}
        resizeMode="scaleAspectFit"
        style={style}
      />
    );
  }
  // Ionicons 的 style 声明成 TextStyle，但这里只用来摆位置（margin / alignSelf）
  return <Ionicons name={ion} size={size} color={color as string} style={style as never} />;
}
