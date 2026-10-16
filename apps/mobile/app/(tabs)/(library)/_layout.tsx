import { Stack } from 'expo-router';

export default function LibraryLayout() {
  return (
    <Stack>
      {/* 关掉原生导航栏：搜索栏改成页面内自绘。
          原生搜索栏（integrated）只能贴在导航栏尾部，也就是右侧；而这里要的是
          搜索框在左、加号紧挨其右，只能自己摆。顶部安全区由页面自己让开。 */}
      <Stack.Screen name="index" options={{ headerShown: false }} />
    </Stack>
  );
}
