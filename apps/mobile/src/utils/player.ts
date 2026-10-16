/**
 * 内嵌播放器的 URL 构造。移植自桌面端 `apps/desktop/src/videoPlayer.ts`，
 * 保持两端的嵌入参数一致（同一个 `t`/`start` 跳转协议）。
 */

export type SupportedVideoPlatform = 'bilibili' | 'youtube';

export interface PlayerEmbedDescriptor {
  platform: SupportedVideoPlatform;
  embedUrl: string;
  sourceUrl: string;
  openLabel: string;
}

export function buildBilibiliEmbedUrl(sourceUrl?: string | null): string | null {
  if (!sourceUrl) return null;

  try {
    const url = new URL(sourceUrl);
    const host = url.hostname.toLowerCase();
    if (!host.includes('bilibili.com') && !host.includes('b23.tv')) return null;

    const bvidFromPath = url.pathname.match(/\/video\/(BV[0-9A-Za-z]+)/i)?.[1] ?? null;
    const aidFromPath = url.pathname.match(/\/video\/av(\d+)/i)?.[1] ?? null;
    const bvid = url.searchParams.get('bvid') ?? bvidFromPath;
    const aid = url.searchParams.get('aid') ?? aidFromPath;
    const page = url.searchParams.get('p') ?? '1';

    if (!bvid && !aid) return null;

    const embedUrl = new URL('https://player.bilibili.com/player.html');
    embedUrl.searchParams.set('isOutside', 'true');
    // 默认不自动播；是否起播由 withPlayerAutoplay 在装载时决定
    embedUrl.searchParams.set('autoplay', '0');
    embedUrl.searchParams.set('p', page);
    if (bvid) embedUrl.searchParams.set('bvid', bvid);
    if (aid) embedUrl.searchParams.set('aid', aid);
    return embedUrl.toString();
  } catch {
    return null;
  }
}

export function buildYouTubeEmbedUrl(sourceUrl?: string | null): string | null {
  if (!sourceUrl) return null;

  try {
    const url = new URL(sourceUrl);
    const host = url.hostname.toLowerCase();
    let videoId: string | null = null;

    if (host.endsWith('youtu.be')) {
      videoId = url.pathname.split('/').filter(Boolean)[0] ?? null;
    } else if (host.includes('youtube.com')) {
      if (url.pathname === '/watch') {
        videoId = url.searchParams.get('v');
      } else {
        videoId = url.pathname.match(/^\/shorts\/([^/?#]+)/i)?.[1] ?? null;
      }
    }

    if (!videoId) return null;

    const embedUrl = new URL(`https://www.youtube.com/embed/${videoId}`);
    embedUrl.searchParams.set('autoplay', '0');
    embedUrl.searchParams.set('rel', '0');
    return embedUrl.toString();
  } catch {
    return null;
  }
}

/** 装载播放器时决定要不要自动起播（点封面 = 播，点时间轴 = 维持原状态） */
export function withPlayerAutoplay(embedUrl: string, autoplay: boolean): string {
  const url = new URL(embedUrl);
  url.searchParams.set('autoplay', autoplay ? '1' : '0');
  return url.toString();
}

/** 首次起播用的跳转参数：bilibili 用 `t`、YouTube 用 `start` */
export function withPlayerSeek(
  embedUrl: string,
  platform: SupportedVideoPlatform,
  seconds: number | null,
): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return embedUrl;
  const url = new URL(embedUrl);
  const normalized = String(Math.floor(seconds));
  if (platform === 'youtube') url.searchParams.set('start', normalized);
  else url.searchParams.set('t', normalized);
  return url.toString();
}

/**
 * 播放中跳转：直接改 <video>.currentTime，**不重载 WebView**。
 * 重载会让 iOS 重新走一次自动播放策略（表现为「跳完还得手动点播放」），
 * 所以只有从封面起播才用 URL 带参数，之后一律走注入。
 * 玩家内嵌页把 <video> 放在顶层文档里，两边平台都取得到。
 */
export function buildSeekInjection(seconds: number, play: boolean): string {
  const target = Math.floor(seconds);
  return `(function(){
    var target = ${target}, play = ${play ? 'true' : 'false'}, tries = 0;
    function apply() {
      var v = document.querySelector('video');
      if (v && isFinite(v.duration) && v.duration > 0) {
        try { v.currentTime = target; } catch (e) {}
        if (play) { try { var p = v.play(); if (p && p.catch) p.catch(function () {}); } catch (e) {} }
        return;
      }
      if (++tries < 50) setTimeout(apply, 100);
    }
    apply();
    true;
  })();`;
}

export function buildPlayerEmbedDescriptor(
  sourceUrl?: string | null,
): PlayerEmbedDescriptor | null {
  const bilibiliEmbedUrl = buildBilibiliEmbedUrl(sourceUrl);
  if (bilibiliEmbedUrl && sourceUrl) {
    return {
      platform: 'bilibili',
      embedUrl: bilibiliEmbedUrl,
      sourceUrl,
      openLabel: '在 Bilibili 打开',
    };
  }

  const youtubeEmbedUrl = buildYouTubeEmbedUrl(sourceUrl);
  if (youtubeEmbedUrl && sourceUrl) {
    return {
      platform: 'youtube',
      embedUrl: youtubeEmbedUrl,
      sourceUrl,
      openLabel: '在 YouTube 打开',
    };
  }

  return null;
}
