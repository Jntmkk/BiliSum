import { View } from 'react-native';

import { spacing } from '@/src/theme/layout';
import { Button } from './Button';
import { Icon } from './Icon';
import { Txt } from './Txt';

interface Props {
  title: string;
  /** 补充说明，可多行 */
  description?: string;
  sf?: React.ComponentProps<typeof Icon>['sf'];
  ion?: React.ComponentProps<typeof Icon>['ion'];
  actionLabel?: string;
  onAction?: () => void;
  /** 次按钮（如「去设置」） */
  secondaryLabel?: string;
  onSecondary?: () => void;
}

/** 空状态 / 错误状态的统一版式：大图标 + 标题 + 说明 + 主按钮 */
export function EmptyState({
  title,
  description,
  sf,
  ion,
  actionLabel,
  onAction,
  secondaryLabel,
  onSecondary,
}: Props) {
  return (
    <View
      style={{
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
        paddingHorizontal: spacing.xxl,
        paddingBottom: spacing.xxl,
        gap: spacing.sm,
      }}>
      {sf && ion ? (
        <Icon sf={sf} ion={ion} size={52} color="#8E8E93" style={{ marginBottom: spacing.sm }} />
      ) : null}
      <Txt variant="headline" center>
        {title}
      </Txt>
      {description ? (
        <Txt variant="subheadline" color="secondary" center>
          {description}
        </Txt>
      ) : null}
      {actionLabel && onAction ? (
        <Button title={actionLabel} onPress={onAction} kind="tinted" style={{ marginTop: spacing.md }} />
      ) : null}
      {secondaryLabel && onSecondary ? (
        <Button title={secondaryLabel} onPress={onSecondary} kind="plain" size="regular" />
      ) : null}
    </View>
  );
}
