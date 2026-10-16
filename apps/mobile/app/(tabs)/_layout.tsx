import { NativeTabs } from 'expo-router/unstable-native-tabs';

import { useColors } from '@/src/theme/colors';

export default function TabsLayout() {
  const colors = useColors();

  return (
    <NativeTabs
      tintColor={colors.accent}
      backgroundColor={colors.background}
      blurEffect="systemChromeMaterial"
      minimizeBehavior="onScrollDown">
      <NativeTabs.Trigger name="(library)">
        <NativeTabs.Trigger.Label>库</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="rectangle.stack" md="video_library" />
      </NativeTabs.Trigger>

      <NativeTabs.Trigger name="collections">
        <NativeTabs.Trigger.Label>合集</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="rectangle.stack.badge.play" md="collections_bookmark" />
      </NativeTabs.Trigger>

      <NativeTabs.Trigger name="settings">
        <NativeTabs.Trigger.Label>我的</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="person.crop.circle" md="account_circle" />
      </NativeTabs.Trigger>
    </NativeTabs>
  );
}
