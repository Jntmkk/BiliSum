import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect, useMemo } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { useColorScheme } from 'react-native';
import 'react-native-reanimated';

import { colorsFor, type Appearance } from '@/src/theme/colors';

export { ErrorBoundary } from 'expo-router';

export const unstable_settings = {
  initialRouteName: '(tabs)',
};

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  useEffect(() => {
    void SplashScreen.hideAsync();
  }, []);

  return (
    <SafeAreaProvider>
      <RootLayoutNav />
    </SafeAreaProvider>
  );
}

function RootLayoutNav() {
  const scheme = useColorScheme();
  const appearance: Appearance = scheme === 'dark' ? 'dark' : 'light';
  const colors = colorsFor(appearance);

  // React Navigation 主题只管默认底色/文字色；系统色的深浅解析由
  // PlatformColor 自己做，所以两种外观共用同一份色表。
  const theme = useMemo(() => {
    const base = appearance === 'dark' ? DarkTheme : DefaultTheme;
    return {
      ...base,
      colors: {
        ...base.colors,
        background: colors.groupedBackground as string,
        card: colors.background as string,
        text: colors.label as string,
        border: colors.separator as string,
        primary: colors.accent as string,
      },
    };
  }, [appearance, colors]);

  return (
    <ThemeProvider value={theme}>
      <Stack screenOptions={{ headerBackButtonDisplayMode: 'minimal' }}>
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="video/[id]" options={{ title: '视频' }} />
        <Stack.Screen name="collection/[id]" options={{ title: '合集' }} />
        <Stack.Screen
          name="new"
          options={{
            title: '新建总结',
            presentation: 'formSheet',
            sheetAllowedDetents: [0.6, 1],
            sheetGrabberVisible: true,
            sheetCornerRadius: 20,
          }}
        />
      </Stack>
    </ThemeProvider>
  );
}
