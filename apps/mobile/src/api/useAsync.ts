import { useCallback, useEffect, useRef, useState } from 'react';

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refreshing: boolean;
}

/**
 * 一次性请求的加载状态。依赖变化时重新拉取；
 * refresh() 用于下拉刷新（保留旧数据，不清空）。
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    error: null,
    loading: true,
    refreshing: false,
  });
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const load = useCallback(async (mode: 'initial' | 'refresh' = 'initial') => {
    setState((s) => ({
      ...s,
      loading: mode === 'initial',
      refreshing: mode === 'refresh',
      error: mode === 'initial' ? null : s.error,
    }));
    try {
      const data = await fnRef.current();
      if (!alive.current) return;
      setState({ data, error: null, loading: false, refreshing: false });
    } catch (e) {
      if (!alive.current) return;
      setState((s) => ({
        ...s,
        error: e instanceof Error ? e.message : '加载失败',
        loading: false,
        refreshing: false,
      }));
    }
  }, []);

  useEffect(() => {
    void load('initial');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const refresh = useCallback(() => load('refresh'), [load]);
  const reload = useCallback(() => load('initial'), [load]);

  return { ...state, refresh, reload };
}
