/**
 * 服务端把封面缓存到本地后返回的是相对路径（`/media/covers/...`），
 * 移动端必须自己拼上服务器地址才能加载。已经是绝对 URL 的原样返回。
 */
export function resolveMediaUrl(base: string | null, url: string | null | undefined): string | null {
  if (!url) return null;
  if (/^https?:\/\//i.test(url)) return url;
  if (!base) return null;
  const trimmed = base.replace(/\/+$/, '');
  return url.startsWith('/') ? `${trimmed}${url}` : `${trimmed}/${url}`;
}
