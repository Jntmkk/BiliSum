/**
 * 章节知识卡片的组织逻辑。移植自桌面端 `apps/desktop/src/detailModel.ts` 的
 * `buildKnowledgeCards` / `buildChapterGroups`——两端同一套「主题分组 + 小章节」
 * 展示逻辑：优先用服务端给的主题组（`chapter_groups`），没有再退化到按 timeline
 * （或 `segment_summaries`）机械切分。
 */
import type { ChapterGroupItem, TaskResult, TimelineItem } from '@/src/api/client';
import { formatClock } from '@/src/utils/format';

export interface ChapterCard {
  id: string;
  title: string;
  content: string;
  /** 可跳转的时间点（秒）；没有就是不可跳 */
  timestampSeconds: number | null;
}

export interface ChapterGroup {
  id: string;
  title: string;
  /** 组标题下方的补充说明（起止时间 / 小章节数） */
  meta: string;
  items: ChapterCard[];
}

/** 组内小章节数超过这个数就换一种切分粒度 */
const SMALL_CHAPTER_LIMIT = 4;

export function buildChapterGroups(result: TaskResult | null | undefined): ChapterGroup[] {
  if (!result) return [];

  const backendGroups = Array.isArray(result.chapter_groups) ? result.chapter_groups : [];
  const fromBackend = backendGroups
    .map((group, index) => buildGroupFromBackend(group, index))
    .filter((group): group is ChapterGroup => group != null);

  if (fromBackend.length) return fromBackend;

  const cards = buildFlatCards(result);
  if (!cards.length) return [];

  const groupSize = cards.length <= SMALL_CHAPTER_LIMIT ? 2 : 3;
  const groups: ChapterGroup[] = [];
  for (let index = 0; index < cards.length; index += groupSize) {
    const items = cards.slice(index, index + groupSize);
    groups.push({
      id: `chapter-group-${groups.length}`,
      title: resolveContentTitle('', items.map((item) => item.title), items.map((item) => item.title).join('；'), '主题'),
      meta: [formatRange(items), `${items.length} 个小章节`].filter(Boolean).join(' · '),
      items,
    });
  }
  return groups;
}

function buildGroupFromBackend(group: ChapterGroupItem, groupIndex: number): ChapterGroup | null {
  if (!group || typeof group !== 'object') return null;

  const children = Array.isArray(group.children) ? group.children : [];
  const items = children
    .map((child, childIndex) => buildCard(child, `${groupIndex}-${childIndex}`))
    .filter((card): card is ChapterCard => card != null);

  if (!items.length) return null;

  const summary = String(group.summary ?? '').trim();
  const title = resolveContentTitle(
    String(group.title ?? '').trim(),
    items.map((item) => item.title),
    summary,
    '主题',
  );

  // 服务端给了 summary 就直接当说明用，跟桌面端一致
  const meta = summary || [formatRange(items), `${items.length} 个小章节`].filter(Boolean).join(' · ');

  return { id: `chapter-group-${groupIndex}`, title, meta, items };
}

function buildCard(item: TimelineItem, idSuffix: string): ChapterCard | null {
  if (!item || typeof item !== 'object') return null;

  const content = String(item.summary ?? '').trim();
  const title = resolveContentTitle(String(item.title ?? '').trim(), [], content, '章节');
  if (!title && !content) return null;

  const start = typeof item.start === 'number' && Number.isFinite(item.start) ? item.start : null;
  return {
    id: `chapter-${idSuffix}`,
    title: title || '章节',
    content: content || '当前章节暂未生成摘要。',
    timestampSeconds: start,
  };
}

/** timeline 缺失时用 segment_summaries 兜底 */
function buildFlatCards(result: TaskResult): ChapterCard[] {
  const timeline = Array.isArray(result.timeline) ? result.timeline : [];
  if (timeline.length) {
    return timeline
      .map((item, index) => buildCard(item, String(index)))
      .filter((card): card is ChapterCard => card != null);
  }

  const segments = Array.isArray(result.segment_summaries) ? result.segment_summaries : [];
  return segments
    .map((item) => String(item).trim())
    .filter(Boolean)
    .map((content, index) => ({
      id: `chapter-${index}`,
      title: `章节 ${index + 1}`,
      content,
      timestampSeconds: null,
    }));
}

function formatRange(items: ChapterCard[]): string {
  const times = items
    .map((item) => item.timestampSeconds)
    .filter((value): value is number => value != null);
  if (!times.length) return '';
  const first = formatClock(Math.min(...times));
  const last = formatClock(Math.max(...times));
  return first === last ? first : `${first} - ${last}`;
}

// ---- 标题规整：模型经常给出「章节 1」这类占位标题，需要从正文里推一个 ----

function resolveContentTitle(title: string, childTitles: string[], fallbackText: string, prefix: string): string {
  const normalized = normalizeTitle(title);
  if (normalized && !isPlaceholderTitle(normalized)) return normalized;

  for (const childTitle of childTitles) {
    const child = normalizeTitle(childTitle);
    if (child && !isPlaceholderTitle(child)) return child;
  }

  return deriveTitleFromText(fallbackText) || prefix;
}

function normalizeTitle(value: string): string {
  return value.trim().replace(/^[-•\d.()、\s]+/, '').slice(0, 24);
}

function isPlaceholderTitle(value: string): boolean {
  const normalized = value.trim().toLowerCase();
  return (
    /^(大)?章节\s*\d+$/.test(value.trim()) ||
    /^第?\s*\d+\s*(章|节|部分)$/.test(value.trim()) ||
    /^(part|section|chapter)\s*[-:：]?\s*\d+$/.test(normalized)
  );
}

function deriveTitleFromText(value: string): string {
  const compact = value
    .trim()
    .replace(/^(这一部分|本部分|这里|该部分|这一章|本章|本节|这一节)(主要)?(讲|介绍|讨论|说明|分析|围绕)?/, '')
    .split(/[。；!！?？\n]/)[0]
    ?.trim()
    .replace(/^[：:\-]+|[，,、；;：:]+$/g, '')
    .replace(/\s+/g, '');
  return compact ? compact.slice(0, 24) : '';
}
