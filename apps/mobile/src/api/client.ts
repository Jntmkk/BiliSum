/**
 * BiliSum service API client.
 *
 * 移动端只是表现层：所有业务逻辑（解析、排队、执行）都在服务端，
 * 这里只负责 HTTP 调用。类型最终由 scripts/gen-api-types.mjs 从
 * FastAPI OpenAPI spec 生成，当前手写对齐 schemas.py，生成后替换。
 */
import { getAccessToken, getServerUrl } from '@/src/store/settings';

// ---- Task types (对齐 packages/core TaskStatus + service TaskSummaryResponse) ----

export type TaskStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled';

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

// ---- TaskResult / TaskDetail (对齐 core TaskResult + service TaskDetailResponse) ----

export interface TimelineItem {
  title?: string;
  start?: number;
  summary?: string;
}

export interface TaskResult {
  overview: string;
  knowledge_note_markdown?: string;
  transcript_text: string;
  key_points: string[];
  timeline: TimelineItem[];
  llm_total_tokens?: number | null;
}

export interface TaskDetail extends TaskSummary {
  result: TaskResult | null;
  error_code: string | null;
  error_message: string | null;
}

export interface VideoProbeRequest {
  url: string;
  force_refresh?: boolean;
}

// ---- Video probe (对齐 service VideoProbeResponse) ----

export interface VideoAssetSummary {
  video_id: string;
  platform: string;
  title: string;
  source_url: string;
  duration: number | null;
  latest_task_id: string | null;
  latest_status: TaskStatus | null;
}

export interface VideoPageOption {
  page: number;
  title: string;
  source_url: string;
  duration: number | null;
}

export interface VideoProbeResponse {
  video: VideoAssetSummary;
  cached: boolean;
  requires_selection: boolean;
  pages: VideoPageOption[];
}

export interface CreateVideoTaskRequest {
  page_number?: number | null;
  visual_note_mode?: string | null;
  prompt_preset_id?: string | null;
  summary_scope?: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const base = await getServerUrl();
  if (!base) {
    throw new Error('请先在「我的」页设置服务器地址');
  }
  const token = await getAccessToken();
  const res = await fetch(`${base}/api/v1${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    throw new Error(`请求失败: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function probeVideo(url: string) {
  return request<VideoProbeResponse>('/videos/probe', {
    method: 'POST',
    body: JSON.stringify({ url } satisfies VideoProbeRequest),
  });
}

export function createVideoTask(
  videoId: string,
  payload: CreateVideoTaskRequest = {},
) {
  return request<TaskDetail>(`/videos/${videoId}/tasks`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function listTasks() {
  return request<TaskSummary[]>('/tasks');
}

export function getTask(taskId: string) {
  return request<TaskDetail>(`/tasks/${taskId}`);
}

export function getTaskProgress(taskId: string) {
  return request<TaskProgress>(`/tasks/${taskId}/progress`);
}
