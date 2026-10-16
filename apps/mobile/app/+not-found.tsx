import { Stack, useRouter } from 'expo-router';
import { View } from 'react-native';

import { EmptyState } from '@/src/components/EmptyState';
import { useColors } from '@/src/theme/colors';

export default function NotFoundScreen() {
  const colors = useColors();
  const router = useRouter();
  return (
    <>
      <Stack.Screen options={{ title: '找不到页面' }} />
      <View style={{ flex: 1, backgroundColor: colors.groupedBackground }}>
        <EmptyState
          sf="questionmark.circle"
          ion="help-circle-outline"
          title="找不到这个页面"
          description="链接可能已经失效，或者对应的内容已被删除。"
          actionLabel="回到视频库"
          onAction={() => router.replace('/(tabs)/(library)')}
        />
      </View>
    </>
  );
}
