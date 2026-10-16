import type { VideoAssetSummary } from '@/src/api/client';
import { isActiveStatus } from '@/src/utils/status';

export type StatusFilter = 'all' | 'summarized' | 'unsummarized' | 'active' | 'failed';
export type SortKey = 'recent' | 'recentSummary' | 'durationDesc' | 'title';

/** 文件夹多选里的「未归档」哨兵值 */
export const UNFILED = '__none__';

export interface LibraryQuery {
  /** 标题本地搜索 */
  query: string;
  status: StatusFilter;
  sort: SortKey;
  /** 空数组 = 不限 */
  platforms: string[];
  /** 空数组 = 不限；含 [[UNFILED]] 表示包含未归档 */
  folderIds: string[];
  favoritesOnly: boolean;
}

export const DEFAULT_LIBRARY_QUERY: LibraryQuery = {
  query: '',
  status: 'all',
  sort: 'recent',
  platforms: [],
  folderIds: [],
  favoritesOnly: false,
};

export const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: '全部状态' },
  { value: 'summarized', label: '已总结' },
  { value: 'unsummarized', label: '未总结' },
  { value: 'active', label: '处理中' },
  { value: 'failed', label: '失败' },
];

export const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: 'recent', label: '最近添加' },
  { value: 'recentSummary', label: '最近总结' },
  { value: 'durationDesc', label: '时长从长到短' },
  { value: 'title', label: '标题' },
];

export function matchesStatus(asset: VideoAssetSummary, status: StatusFilter): boolean {
  switch (status) {
    case 'all':
      return true;
    case 'summarized':
      return asset.has_result;
    case 'unsummarized':
      return !asset.has_result && !isActiveStatus(asset.latest_status);
    case 'active':
      return isActiveStatus(asset.latest_status);
    case 'failed':
      return asset.latest_status === 'failed' && !asset.has_result;
  }
}

export function matchesQuery(asset: VideoAssetSummary, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return asset.title.toLowerCase().includes(q);
}

export function matchesFilters(asset: VideoAssetSummary, q: LibraryQuery): boolean {
  if (q.platforms.length && !q.platforms.includes(asset.platform)) return false;
  if (q.favoritesOnly && !asset.is_favorite) return false;
  if (q.folderIds.length) {
    const own = asset.folder_ids ?? [];
    const hit = own.some((id) => q.folderIds.includes(id));
    const unfiled = own.length === 0 && q.folderIds.includes(UNFILED);
    if (!hit && !unfiled) return false;
  }
  return true;
}

/** 时间戳缺失时按「最旧」处理，避免默认排序在脏数据上抛错 */
function cmpDesc(a: string | null | undefined, b: string | null | undefined): number {
  if (!a && !b) return 0;
  if (!a) return 1;
  if (!b) return -1;
  return b.localeCompare(a);
}

function bySort(a: VideoAssetSummary, b: VideoAssetSummary, sort: SortKey): number {
  switch (sort) {
    case 'recent':
      return cmpDesc(a.created_at, b.created_at);
    case 'recentSummary':
      // 没总结过的沉底
      return cmpDesc(a.last_summary_at, b.last_summary_at);
    case 'durationDesc':
      return (b.duration ?? 0) - (a.duration ?? 0);
    case 'title':
      return (a.title ?? '').localeCompare(b.title ?? '', 'zh-Hans-CN');
  }
}

/** 只做筛选与排序，搜索词单独走 matchesQuery 以便和筛选结果分开计数 */
export function applyLibraryQuery(
  videos: VideoAssetSummary[],
  q: LibraryQuery,
): VideoAssetSummary[] {
  return videos
    .filter(
      (v) =>
        matchesStatus(v, q.status) &&
        matchesFilters(v, q) &&
        matchesQuery(v, q.query),
    )
    .sort((a, b) => bySort(a, b, q.sort));
}

/** 筛选面板里能选的平台，从现有数据推导，避免写死 */
export function availablePlatforms(videos: VideoAssetSummary[]): string[] {
  return [...new Set(videos.map((v) => v.platform))].sort();
}

/** 「筛选」按钮上显示的条件数（不含状态下拉与搜索） */
export function activeFilterCount(q: LibraryQuery): number {
  return q.platforms.length + q.folderIds.length + (q.favoritesOnly ? 1 : 0);
}
