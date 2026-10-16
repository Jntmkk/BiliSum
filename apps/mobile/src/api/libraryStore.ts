import { useCallback, useEffect, useRef, useState } from 'react';

import type { LibraryQuery } from '@/src/features/library';
import {
  listVideoLibrary,
  type LibraryRequest,
  type VideoAssetSummary,
  type VideoFolder,
  type VideoLibrary,
} from './client';

/**
 * 视频库的进程内共享缓存。库页和合集页读同一份 `/videos/library`
 * 响应（一次同时返回 videos / folders / collections），避免各自拉一遍。
 * 不做持久化：进前台时由调用方 refresh。
 */
interface LibrarySnapshot {
  data: VideoLibrary | null;
  error: string | null;
  loading: boolean;
  refreshing: boolean;
  /** 上次成功拉取的时间戳（ms） */
  fetchedAt: number | null;
}

let snapshot: LibrarySnapshot = {
  data: null,
  error: null,
  loading: false,
  refreshing: false,
  fetchedAt: null,
};

const listeners = new Set<() => void>();
let inFlight: Promise<void> | null = null;

function emit() {
  for (const l of listeners) l();
}

function set(patch: Partial<LibrarySnapshot>) {
  snapshot = { ...snapshot, ...patch };
  emit();
}

export function getLibrarySnapshot(): LibrarySnapshot {
  return snapshot;
}

async function fetchLibrary(mode: 'initial' | 'refresh') {
  if (inFlight) return inFlight;
  set(
    mode === 'refresh'
      ? { refreshing: true }
      : { loading: snapshot.data == null, error: snapshot.data == null ? null : snapshot.error },
  );
  inFlight = (async () => {
    try {
      const data = await listVideoLibrary();
      set({ data, error: null, loading: false, refreshing: false, fetchedAt: Date.now() });
    } catch (e) {
      set({
        error: e instanceof Error ? e.message : '加载失败',
        loading: false,
        refreshing: false,
      });
    } finally {
      inFlight = null;
    }
  })();
  return inFlight;
}

/** 下次进入时重新拉取（新建任务后调用） */
export function invalidateLibrary() {
  snapshot = { ...snapshot, fetchedAt: null };
}

export function useLibrary() {
  const [, force] = useState(0);

  useEffect(() => {
    const listener = () => force((n) => n + 1);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  const refresh = useCallback(() => fetchLibrary('refresh'), []);

  // 首次挂载且没有数据时自动拉取
  useEffect(() => {
    if (snapshot.data == null && !snapshot.loading) void fetchLibrary('initial');
  }, []);

  return { ...snapshot, refresh };
}

/** 聚焦时若缓存已失效则重新拉取 */
export function refreshLibraryIfStale() {
  if (snapshot.fetchedAt == null) void fetchLibrary('refresh');
}

// ---- 分页版（库页专用） ----

const PAGE_SIZE = 20;
const SEARCH_DEBOUNCE_MS = 300;

export interface LibraryPage {
  videos: VideoAssetSummary[];
  folders: VideoFolder[];
  /** 平台 facet，由服务端全量去重后下发；分页下不能从当前页推导 */
  platforms: string[];
  total: number;
  hasMore: boolean;
  /** 首屏加载：只在还没有数据时为真，翻页不会整屏闪 */
  loading: boolean;
  loadingMore: boolean;
  refreshing: boolean;
  error: string | null;
}

const EMPTY_PAGE: LibraryPage = {
  videos: [],
  folders: [],
  platforms: [],
  total: 0,
  hasMore: false,
  loading: false,
  loadingMore: false,
  refreshing: false,
  error: null,
};

function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

function realtimeKey(q: LibraryQuery): string {
  return [
    q.status,
    q.sort,
    q.platforms.join(','),
    q.folderIds.join(','),
    q.favoritesOnly ? '1' : '0',
  ].join('|');
}

/**
 * 库页的深度分页（无限滚动）。筛选/排序/搜索全部交给服务端，
 * 所以搜索词要防抖、条件一变就回到 offset=0。
 * 合集页继续用 [[useLibrary]] 拿全量快照，不受这里的分页影响。
 */
export function useLibraryPage(query: LibraryQuery) {
  const debouncedQuery = useDebouncedValue(query.query, SEARCH_DEBOUNCE_MS);
  const [page, setPage] = useState<LibraryPage>(EMPTY_PAGE);

  // 每次渲染同步最新的请求参数与结果，供 loadMore 读取，避免把 page 塞进 useCallback 依赖
  const paramsRef = useRef<LibraryRequest>({});
  paramsRef.current = {
    q: debouncedQuery,
    status: query.status,
    sort: query.sort,
    platforms: query.platforms,
    folderIds: query.folderIds,
    favoritesOnly: query.favoritesOnly,
    includeCollectionVideos: true,
  };
  const pageRef = useRef(page);
  pageRef.current = page;
  // 每次「重置」开启新一代，旧世代的响应回来时直接丢弃，防止筛选连点导致结果错位
  const generationRef = useRef(0);
  const loadingMoreRef = useRef(false);

  const fetchPage = useCallback(
    async (offset: number, mode: 'reset' | 'more' | 'refresh', limitOverride?: number) => {
      const generation =
        mode === 'more' ? generationRef.current : (generationRef.current += 1);
      const limit = limitOverride ?? PAGE_SIZE;

      if (mode === 'more') {
        if (loadingMoreRef.current) return;
        loadingMoreRef.current = true;
        setPage((prev) => ({ ...prev, loadingMore: true }));
      } else {
        loadingMoreRef.current = false;
        setPage((prev) => ({
          ...prev,
          loading: mode === 'reset' && prev.videos.length === 0,
          loadingMore: false,
          refreshing: mode === 'refresh',
          error: null,
        }));
      }

      try {
        const res = await listVideoLibrary({ ...paramsRef.current, limit, offset });
        if (generation !== generationRef.current) return;
        setPage((prev) => ({
          videos: mode === 'more' ? [...prev.videos, ...res.videos] : res.videos,
          folders: res.folders,
          platforms: res.platforms ?? [],
          total: res.total ?? res.videos.length,
          hasMore: res.has_more ?? false,
          loading: false,
          loadingMore: false,
          refreshing: false,
          error: null,
        }));
      } catch (e) {
        if (generation !== generationRef.current) return;
        setPage((prev) => ({
          ...prev,
          loading: false,
          loadingMore: false,
          refreshing: false,
          error: e instanceof Error ? e.message : '加载失败',
        }));
      } finally {
        if (mode === 'more') loadingMoreRef.current = false;
      }
    },
    [],
  );

  const key = `${debouncedQuery}|${realtimeKey(query)}`;

  useEffect(() => {
    void fetchPage(0, 'reset');
  }, [key, fetchPage]);

  /** 下拉刷新：回到第一页（和常见无限滚动列表一致） */
  const refresh = useCallback(() => fetchPage(0, 'refresh'), [fetchPage]);

  /**
   * 轮询用：按当前已加载数量重取，不会把翻到第 N 页的列表缩回第一页。
   * （`refresh` 从 offset 0 取一页，用于后台轮询会「吃掉」用户已翻的页。）
   */
  const refreshLoaded = useCallback(
    () => fetchPage(0, 'refresh', Math.max(PAGE_SIZE, pageRef.current.videos.length)),
    [fetchPage],
  );

  const loadMore = useCallback(() => {
    const prev = pageRef.current;
    if (!prev.hasMore || loadingMoreRef.current || prev.loading) return;
    void fetchPage(prev.videos.length, 'more');
  }, [fetchPage]);

  return { ...page, refresh, refreshLoaded, loadMore };
}
