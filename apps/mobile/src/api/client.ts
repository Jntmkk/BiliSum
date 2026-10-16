/**
 * BiliSum service API client.
 *
 * 移动端只是表现层：所有业务逻辑（解析、排队、执行）都在服务端，
 * 这里只负责 HTTP 调用。类型手写对齐 service 的 schemas.py（已用
 * 运行中的 /openapi.json 核对），待 scripts/gen-api-types.mjs 装上
 * openapi-typescript 后可改为生成。
 */
import { getAccessToken, getServerUrl } from '@/src/store/settings';

// ---- 状态 ----

export type TaskStatus =
  | 'queued'
  | 'running'
  | 'waiting_offpeak'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type Platform = string;

// ---- 任务 ----

export interface TaskSummary {
  task_id: string;
  video_id: string | null;
  status: TaskStatus;
  input_type: string;
  source: string;
  title: string | null;
  page_number: number | null;
  page_title: string | null;
  created_at: string;
  updated_at: string;
  llm_total_tokens: number | null;
  task_duration_seconds: number | null;
}

export interface TaskProgress {
  task_id: string;
  status: TaskStatus;
  progress: number;
  latest_stage: string | null;
  latest_message: string | null;
  updated_at: string;
}

/** 后端 timeline 是 list[dict]，字段名历史上变过，这里按需取值并容错 */
export interface TimelineItem {
  start?: number;
  end?: number;
  title?: string;
  summary?: string;
  text?: string;
}

/** 服务端按主题聚合的章节组（`chapter_groups`），children 是组内小章节 */
export interface ChapterGroupItem {
  title?: string;
  start?: number;
  summary?: string;
  children?: TimelineItem[];
}

export interface TaskResult {
  overview: string;
  knowledge_note_markdown: string;
  transcript_text: string;
  key_points: string[];
  timeline: TimelineItem[];
  /** 主题化章节组；老任务可能没有 */
  chapter_groups?: ChapterGroupItem[];
  /** timeline 缺失时的退化素材 */
  segment_summaries?: string[];
  llm_total_tokens: number | null;
}

export interface TaskDetail extends TaskSummary {
  result: TaskResult | null;
  error_code: string | null;
  error_message: string | null;
}

// ---- 视频资产 ----

export interface VideoPageOption {
  page: number;
  title: string;
  source_url: string;
  cover_url: string;
  duration: number | null;
}

/** 列表卡片用（VideoAssetSummaryResponse） */
export interface VideoAssetSummary {
  video_id: string;
  canonical_id: string;
  platform: Platform;
  title: string;
  source_url: string;
  cover_url: string;
  duration: number | null;
  latest_task_id: string | null;
  latest_status: TaskStatus | null;
  latest_stage: string | null;
  latest_task_created_at: string | null;
  latest_task_completed_at: string | null;
  latest_task_duration_seconds: number | null;
  last_summary_at: string | null;
  has_result: boolean;
  is_favorite: boolean;
  folder_id: string | null;
  folder_ids: string[];
  pages: VideoPageOption[];
  created_at: string;
  updated_at: string;
}

/** 详情页用（VideoAssetDetailResponse） */
export interface VideoAssetDetail extends VideoAssetSummary {
  latest_result: TaskResult | null;
  latest_error_message: string | null;
}

export interface VideoFolder {
  folder_id: string;
  parent_id: string | null;
  name: string;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface VideoLibrary {
  videos: VideoAssetSummary[];
  folders: VideoFolder[];
  preferences: { new_video_position: 'front' | 'back' };
  collections: VideoCollectionSummary[];
  /** 过滤后的总数（分页用；旧服务端不返回时为 undefined） */
  total?: number;
  has_more?: boolean;
  /** 平台 facet：分页后不能从当前页推导，由服务端给 */
  platforms?: string[];
}

// ---- 合集 ----

export interface VideoCollectionSummary {
  collection_id: string;
  title: string;
  cover_url: string;
  folder_id: string | null;
  folder_ids: string[];
  is_favorite: boolean;
  latest_video_updated_at: string | null;
  owner_mid: string | null;
  owner_name: string | null;
  owner_face: string | null;
  owner_url: string | null;
  item_count: number;
  source_url: string;
  summarized_count: number;
  unsummarized_count: number;
  last_checked_at: string | null;
  auto_check_on_open: boolean;
  view_sort_mode: 'source' | 'source_desc' | 'recent_summary' | 'recent_update' | 'duration' | 'custom';
  view_group_mode: 'none' | 'status' | 'source_section';
}

export interface VideoCollectionItem {
  position: number;
  custom_position: number | null;
  bvid: string;
  title: string;
  source_url: string;
  cover_url: string;
  duration: number | null;
  source_section_id: string | null;
  source_section_title: string | null;
  source_section_position: number | null;
  is_current: boolean;
  video_id: string | null;
  has_result: boolean;
  latest_status: TaskStatus | null;
  last_summary_at: string | null;
  asset_updated_at: string | null;
  is_global_visible: boolean;
  is_new: boolean;
}

export interface VideoCollection extends VideoCollectionSummary {
  items: VideoCollectionItem[];
  new_items: VideoCollectionItem[];
}

// ---- 探针 / 新建 ----

export interface VideoProbeResponse {
  video: VideoAssetSummary;
  cached: boolean;
  requires_selection: boolean;
  pages: VideoPageOption[];
  collection: VideoCollectionSummary | null;
}

export interface VideoTaskCreateRequest {
  page_number?: number | null;
  visual_note_mode?: string | null;
  prompt_preset_id?: string | null;
  summary_scope?: string | null;
  schedule?: 'immediate' | 'offpeak' | null;
}

export interface VideoTaskBatchRequest {
  page_numbers?: number[];
  confirm?: boolean;
  prompt_preset_id?: string | null;
  schedule?: 'immediate' | 'offpeak' | null;
}

export interface VideoTaskBatchPage {
  page_number: number;
  page_title: string | null;
  action: string;
  reason: string | null;
  existing_task_id: string | null;
  existing_status: TaskStatus | null;
  has_existing_result: boolean;
  task: TaskDetail | null;
}

export interface VideoTaskBatchResponse {
  operation: string;
  requested_page_numbers: number[];
  requires_confirmation: boolean;
  created_tasks: TaskDetail[];
  skipped_pages: VideoTaskBatchPage[];
  conflict_pages: VideoTaskBatchPage[];
}

// ---- HTTP ----

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const base = await getServerUrl();
  if (!base) {
    throw new ApiError('请先在「我的」页设置服务器地址', 0);
  }
  const token = await getAccessToken();
  let res: Response;
  try {
    res = await fetch(`${base}/api/v1${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError('无法连接服务器，请检查「我的」页的地址', 0);
  }
  if (!res.ok) {
    if (res.status === 401) {
      throw new ApiError('访问密钥无效，请在「我的」页检查访问密钥', 401);
    }
    throw new ApiError(`请求失败：${res.status}`, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ---- 视频库 ----

export interface LibraryRequest {
  q?: string;
  status?: string;
  platforms?: string[];
  folderIds?: string[];
  favoritesOnly?: boolean;
  sort?: string;
  /** 让合集脚手架视频也进入平铺 */
  includeCollectionVideos?: boolean;
  limit?: number;
  offset?: number;
}

/** 数组值重复出现同名参数（`?platform=a&platform=b`），对应 FastAPI 的 `list[str]` */
function buildQuery(
  params: Record<string, string | number | boolean | string[] | undefined>,
): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === '' || value === false) continue;
    if (Array.isArray(value)) {
      if (value.length === 0) continue;
      for (const item of value) parts.push(`${key}=${encodeURIComponent(item)}`);
    } else {
      parts.push(`${key}=${encodeURIComponent(String(value))}`);
    }
  }
  return parts.length ? `?${parts.join('&')}` : '';
}

export function listVideoLibrary(params: LibraryRequest = {}) {
  const query = buildQuery({
    q: params.q,
    status: params.status,
    platform: params.platforms,
    folder_id: params.folderIds,
    favorites: params.favoritesOnly,
    sort: params.sort,
    include_collection_videos: params.includeCollectionVideos,
    limit: params.limit,
    offset: params.offset,
  });
  return request<VideoLibrary>(`/videos/library${query}`);
}

export function getVideo(videoId: string) {
  return request<VideoAssetDetail>(`/videos/${videoId}`);
}

export function getVideoTasks(videoId: string) {
  return request<TaskSummary[]>(`/videos/${videoId}/tasks`);
}

// ---- 任务 ----

export function getTask(taskId: string) {
  return request<TaskDetail>(`/tasks/${taskId}`);
}

export function getTaskProgress(taskId: string) {
  return request<TaskProgress>(`/tasks/${taskId}/progress`);
}

// ---- 新建 ----

export function probeVideo(url: string) {
  return request<VideoProbeResponse>('/videos/probe', {
    method: 'POST',
    body: JSON.stringify({ url }),
  });
}

export function createVideoTask(
  videoId: string,
  payload: VideoTaskCreateRequest = {},
) {
  return request<TaskDetail>(`/videos/${videoId}/tasks`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function createVideoTasksBatch(
  videoId: string,
  payload: VideoTaskBatchRequest = {},
) {
  return request<VideoTaskBatchResponse>(`/videos/${videoId}/tasks/batch`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 多 P 视频的全集总结 */
export function createAggregateSummary(
  videoId: string,
  pageNumbers?: number[],
) {
  return request<TaskDetail>(`/videos/${videoId}/tasks/aggregate-summary`, {
    method: 'POST',
    body: JSON.stringify({ page_numbers: pageNumbers ?? null }),
  });
}

// ---- 合集 ----

export function getCollection(collectionId: string) {
  return request<VideoCollection>(`/videos/collections/${collectionId}`);
}
