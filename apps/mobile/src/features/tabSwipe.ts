import { useRef } from 'react';
import { PanResponder } from 'react-native';
import { useRouter } from 'expo-router';
import * as Haptics from 'expo-haptics';

/** 与 `(tabs)/_layout.tsx` 里的 Trigger 顺序一致 */
const TAB_HREFS = ['/(tabs)/(library)', '/(tabs)/collections', '/(tabs)/settings'] as const;

/** 横向位移超过这个值才算切 tab */
const TRIGGER_DISTANCE = 60;
/** 超过这个位移、且明显比纵向更横，才把手势从列表手里抢过来 */
const CAPTURE_DISTANCE = 16;

/**
 * 左右滑动切换 tab。
 *
 * 原生 tab 栏（UITabBarController）本身不支持滑动切换 —— RNS 的 tabs host 上
 * 没有任何 swipe/pager 属性，所以手势只能在 JS 层自己接，切 tab 用瞬时导航。
 *
 * 必须在 capture 阶段判定：纵向 `ScrollView`/`FlatList` 会先拿到 responder，
 * 父级到冒泡阶段就再也抢不回来了。只有「横向为主」的手势才捕获。
 */
export function useTabSwipe(index: number) {
  const router = useRouter();
  const indexRef = useRef(index);
  indexRef.current = index;
  const routerRef = useRef(router);
  routerRef.current = router;

  const responder = useRef(
    PanResponder.create({
      onMoveShouldSetPanResponderCapture: (_, g) =>
        Math.abs(g.dx) > CAPTURE_DISTANCE && Math.abs(g.dx) > Math.abs(g.dy) * 1.5,
      onPanResponderTerminationRequest: () => false,
      onPanResponderRelease: (_, g) => {
        const current = indexRef.current;
        let next = current;
        if (g.dx <= -TRIGGER_DISTANCE) next = current + 1;
        else if (g.dx >= TRIGGER_DISTANCE) next = current - 1;
        if (next === current || next < 0 || next >= TAB_HREFS.length) return;
        void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        routerRef.current.navigate(TAB_HREFS[next]);
      },
    }),
  );

  return responder.current.panHandlers;
}
