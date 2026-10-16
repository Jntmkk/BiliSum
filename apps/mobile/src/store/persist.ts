import { useCallback, useEffect, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

/**
 * 异步持久化的状态。初期 hydrated=false，调用方决定是否等它
 * （库页会等，避免先渲染默认视图再闪一下切换）。
 */
export function usePersistedState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(initial);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let alive = true;
    AsyncStorage.getItem(key)
      .then((raw) => {
        if (!alive || raw == null) return;
        try {
          setValue(JSON.parse(raw) as T);
        } catch {
          // 旧格式或损坏，保留默认值
        }
      })
      .finally(() => {
        if (alive) setHydrated(true);
      });
    return () => {
      alive = false;
    };
  }, [key]);

  const update = useCallback(
    (next: T) => {
      setValue(next);
      void AsyncStorage.setItem(key, JSON.stringify(next));
    },
    [key],
  );

  return [value, update, hydrated] as const;
}
