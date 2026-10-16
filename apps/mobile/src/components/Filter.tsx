import type { ReactNode } from 'react';
import { Modal, Pressable, ScrollView, View } from 'react-native';

import { useColors } from '@/src/theme/colors';
import { layout, spacing } from '@/src/theme/layout';
import { radius } from '@/src/theme/radius';
import { Icon } from './Icon';
import { Txt } from './Txt';

/** 筛选栏里的下拉触发器，形如「全部状态 ▾」 */
export function FilterTrigger({
  label,
  active,
  onPress,
  /** 有选中项时显示的数字角标 */
  count,
}: {
  label: string;
  active?: boolean;
  onPress: () => void;
  count?: number;
}) {
  const colors = useColors();
  return (
    <Pressable
      onPress={onPress}
      hitSlop={6}
      style={({ pressed }) => ({
        flexDirection: 'row',
        alignItems: 'center',
        gap: 2,
        height: 32,
        paddingHorizontal: spacing.md,
        borderRadius: radius.pill,
        backgroundColor: active ? colors.accent : colors.fill,
        opacity: pressed ? 0.7 : 1,
      })}>
      <Txt
        variant="subheadline"
        numberOfLines={1}
        style={{ color: active ? '#FFFFFF' : colors.label, fontWeight: '500' }}>
        {label}
        {count != null && count > 0 ? ` ${count}` : ''}
      </Txt>
      <Icon
        sf="chevron.down"
        ion="chevron-down"
        size={11}
        weight="semibold"
        color={active ? '#FFFFFF' : colors.secondaryLabel}
      />
    </Pressable>
  );
}

/**
 * 电商式下拉面板：在当前行下方展开 + 半透明遮罩。
 * top 由筛选行 onLayout 量出，面板贴着它下沿渲染。
 */
export function DropdownOverlay({
  visible,
  top,
  onClose,
  children,
}: {
  visible: boolean;
  top: number;
  onClose: () => void;
  children: ReactNode;
}) {
  const colors = useColors();
  if (!visible) return null;
  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <Pressable
        style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.25)' }}
        onPress={onClose}>
        <View style={{ marginTop: top }}>
          {/* 吞掉面板内的点击，避免冒泡到遮罩把面板关掉 */}
          <Pressable onPress={() => {}}>
            <View
              style={{
                backgroundColor: colors.surface,
                borderBottomLeftRadius: radius.lg,
                borderBottomRightRadius: radius.lg,
                overflow: 'hidden',
              }}>
              <ScrollView
                style={{ maxHeight: 420 }}
                contentContainerStyle={{ paddingVertical: spacing.sm }}
                keyboardShouldPersistTaps="handled">
                {children}
              </ScrollView>
            </View>
          </Pressable>
        </View>
      </Pressable>
    </Modal>
  );
}

interface Option<T> {
  value: T;
  label: string;
  /** 右侧的计数 / 补充说明 */
  detail?: string;
}

/** 单选列表 */
export function OptionList<T extends string | number | null>({
  options,
  value,
  onChange,
}: {
  options: Option<T>[];
  value: T;
  onChange: (value: T) => void;
}) {
  const colors = useColors();
  return (
    <View>
      {options.map((o) => {
        const selected = o.value === value;
        return (
          <Pressable
            key={String(o.value)}
            onPress={() => onChange(o.value)}
            style={({ pressed }) => ({
              flexDirection: 'row',
              alignItems: 'center',
              gap: spacing.sm,
              minHeight: layout.touchTarget,
              paddingHorizontal: layout.margin,
              backgroundColor: pressed ? colors.fill : 'transparent',
            })}>
            <Txt
              variant="body"
              color={selected ? 'accent' : 'label'}
              style={{ flex: 1 }}
              numberOfLines={1}>
              {o.label}
            </Txt>
            {o.detail ? (
              <Txt variant="footnote" color="tertiary">
                {o.detail}
              </Txt>
            ) : null}
            {selected ? (
              <Icon sf="checkmark" ion="checkmark" size={16} weight="semibold" color={colors.accent} />
            ) : null}
          </Pressable>
        );
      })}
    </View>
  );
}

/** 多条件面板里的一组标题 */
export function OptionGroup({
  title,
  children,
  first,
}: {
  title: string;
  children: ReactNode;
  first?: boolean;
}) {
  const colors = useColors();
  return (
    <View
      style={
        first
          ? undefined
          : {
              borderTopWidth: layout.hairline,
              borderTopColor: colors.separator,
              marginTop: spacing.sm,
              paddingTop: spacing.sm,
            }
      }>
      <Txt
        variant="footnote"
        color="secondary"
        style={{ paddingHorizontal: layout.margin, paddingVertical: spacing.xs }}>
        {title}
      </Txt>
      <View
        style={{
          flexDirection: 'row',
          flexWrap: 'wrap',
          gap: spacing.sm,
          paddingHorizontal: layout.margin,
        }}>
        {children}
      </View>
    </View>
  );
}

/** 多选面板里的一个可选标签 */
export function OptionChip({
  label,
  selected,
  onPress,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
}) {
  const colors = useColors();
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => ({
        paddingHorizontal: spacing.md,
        paddingVertical: 7,
        borderRadius: radius.sm,
        backgroundColor: selected ? colors.accent : colors.fill,
        opacity: pressed ? 0.7 : 1,
      })}>
      <Txt
        variant="subheadline"
        style={{ color: selected ? '#FFFFFF' : colors.label, fontWeight: selected ? '600' : '400' }}>
        {label}
      </Txt>
    </Pressable>
  );
}
