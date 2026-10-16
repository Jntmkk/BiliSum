import type { TaskStatus } from '@/src/api/client';

/**
 * 状态语义色 key。screen 层用 useTone() 映射到 token 色。
 * active=系统橙、ok=系统绿、bad=系统红、muted=tertiaryLabel
 */
export type Tone = 'active' | 'ok' | 'bad' | 'muted';

export interface StateDescriptor {
  label: string;
  tone: Tone;
  /** 任务仍在处理中（需要轮询 / 显示进度条） */
  isActive: boolean;
  /** 0-100，仅在 isActive 时有意义 */
  progress?: number;
}

/** 视频资产层面的一句话状态。文案沿用 Web 端，保持两端一致。 */
export function videoState(asset: {
  latest_status: TaskStatus | null;
  has_result: boolean;
}): StateDescriptor {
  const { latest_status: status, has_result } = asset;

  if (status === 'queued') {
    return { label: '等待开始处理', tone: 'active', isActive: true };
  }
  if (status === 'waiting_offpeak') {
    return { label: '等待错峰处理', tone: 'active', isActive: true };
  }
  if (status === 'running') {
    return { label: '正在生成摘要', tone: 'active', isActive: true };
  }
  // 重跑失败但旧摘要还在 —— 仍视为已有摘要，避免抹掉用户已有的内容
  if (has_result) {
    return { label: '摘要已生成', tone: 'ok', isActive: false };
  }
  if (status === 'failed') {
    return { label: '本次生成失败', tone: 'bad', isActive: false };
  }
  if (status === 'cancelled') {
    return { label: '已取消生成', tone: 'muted', isActive: false };
  }
  // completed 却没有结果：少见，但确实存在
  if (status === 'completed') {
    return { label: '未产出摘要', tone: 'muted', isActive: false };
  }
  return { label: '尚未生成摘要', tone: 'muted', isActive: false };
}

/** 任务层面的状态文案（视频详情页里对单个任务用） */
export function taskStatusLabel(status: TaskStatus): string {
  switch (status) {
    case 'queued':
      return '排队中';
    case 'running':
      return '处理中';
    case 'waiting_offpeak':
      return '等待错峰';
    case 'completed':
      return '已完成';
    case 'failed':
      return '失败';
    case 'cancelled':
      return '已取消';
  }
}

export function taskStatusTone(status: TaskStatus | null): Tone {
  switch (status) {
    case 'queued':
    case 'running':
    case 'waiting_offpeak':
      return 'active';
    case 'completed':
      return 'ok';
    case 'failed':
      return 'bad';
    default:
      return 'muted';
  }
}

export function isActiveStatus(status: TaskStatus | null): boolean {
  return status === 'queued' || status === 'running' || status === 'waiting_offpeak';
}

/** 平台名展示：bilibili → Bilibili */
export function platformLabel(platform: string): string {
  const key = platform.toLowerCase();
  if (key === 'bilibili' || key === 'b站') return 'Bilibili';
  if (key === 'youtube') return 'YouTube';
  if (key === 'local') return '本地';
  return platform;
}
