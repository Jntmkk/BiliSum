import { useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, View } from 'react-native';
import { WebView, type WebViewRef } from 'react-native-webview';

import { Icon } from '@/src/components/Icon';
import { VideoCover } from '@/src/components/VideoCover';
import { layout } from '@/src/theme/layout';
import { radius } from '@/src/theme/radius';
import {
  buildPlayerEmbedDescriptor,
  buildSeekInjection,
  withPlayerAutoplay,
  withPlayerSeek,
} from '@/src/utils/player';

interface Props {
  /** 视频来源页地址；B 站或 YouTube 才支持内嵌 */
  sourceUrl: string | null | undefined;
  coverUrl: string | null | undefined;
  badge?: string;
  /** 时间轴跳转的目标秒数 */
  seekSeconds?: number | null;
  /** 每次请求跳转都要换新值，否则同一个秒数不会触发跳转 */
  seekNonce?: number;
  /** 受控的播放态：详情页靠它决定往下滚时是否把播放器钉住 */
  playing: boolean;
  onPlayingChange: (playing: boolean) => void;
}

/**
 * 内嵌 B 站 / YouTube 播放器。默认显示封面，点封面以自动播放装载 WebView。
 *
 * 跳转一律**注入 currentTime**、不重载：重载会让 iOS 重新走一遍自动播放策略，
 * 结果就是「跳到时间点后还得手动点播放」。只有从封面首次装载才用 URL 带参数，
 * 那时 URL 上的 `t`/`autoplay` 才有意义。
 *
 * 「播放器已挂载」和「正在播放」是两回事：点时间轴时若本来没在播，会装载一个
 * 停在目标时间点的暂停态播放器（装载地址带 `t`、`autoplay=0`）。
 */
export function VideoPlayer({
  sourceUrl,
  coverUrl,
  badge,
  seekSeconds = null,
  seekNonce = 0,
  playing,
  onPlayingChange,
}: Props) {
  const descriptor = useMemo(() => buildPlayerEmbedDescriptor(sourceUrl), [sourceUrl]);
  const webRef = useRef<WebViewRef | null>(null);
  const [loading, setLoading] = useState(true);
  /** WebView 的装载地址；null = 未挂载，显示封面 */
  const [src, setSrc] = useState<string | null>(null);

  // effect 里要读最新值但不进依赖，用 ref 兜住
  const srcRef = useRef<string | null>(null);
  srcRef.current = src;
  const playingRef = useRef(playing);
  playingRef.current = playing;

  // 换视频 / 换分 P：卸载播放器，回到封面
  useEffect(() => {
    setSrc(null);
    setLoading(true);
  }, [descriptor]);

  const lastSeek = useRef(seekNonce);
  useEffect(() => {
    if (seekNonce === lastSeek.current) return;
    lastSeek.current = seekNonce;
    if (!descriptor || seekSeconds == null) return;

    if (srcRef.current) {
      // 已挂载：原地跳转，保持当前的播放/暂停状态
      webRef.current?.injectJavaScript(buildSeekInjection(seekSeconds, playingRef.current));
      return;
    }
    // 未挂载：用 URL 定位 + 按需起播
    setSrc(
      withPlayerAutoplay(
        withPlayerSeek(descriptor.embedUrl, descriptor.platform, seekSeconds),
        playingRef.current,
      ),
    );
    setLoading(true);
  }, [descriptor, seekNonce, seekSeconds]);

  if (!descriptor) {
    return <VideoCover uri={coverUrl} corner="lg" badge={badge} />;
  }

  const mounted = src != null;

  return (
    <View
      style={{
        width: '100%',
        aspectRatio: layout.coverAspect,
        borderRadius: radius.lg,
        overflow: 'hidden',
        backgroundColor: '#000000',
      }}>
      {mounted ? (
        <WebView
          ref={webRef}
          // B 站 iframe 会校验 Referer，缺了会白屏
          source={{ uri: src, headers: { Referer: 'https://www.bilibili.com' } }}
          style={{ flex: 1, backgroundColor: '#000000' }}
          allowsInlineMediaPlayback
          mediaPlaybackRequiresUserAction={false}
          allowsFullscreenVideo
          javaScriptEnabled
          domStorageEnabled
          originWhitelist={['*']}
          onLoadEnd={() => setLoading(false)}
          onError={() => setLoading(false)}
        />
      ) : (
        <VideoCover
          uri={coverUrl}
          corner="lg"
          badge={badge}
          aspect={layout.coverAspect}
          onPress={() => {
            setSrc(withPlayerAutoplay(descriptor.embedUrl, true));
            setLoading(true);
            onPlayingChange(true);
          }}
        />
      )}

      {mounted && loading ? (
        <View
          pointerEvents="none"
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            alignItems: 'center',
            justifyContent: 'center',
          }}>
          <ActivityIndicator color="#FFFFFF" />
        </View>
      ) : null}

      {/* 暂停态也要能退回封面，所以按「已挂载」显示而不是按「在播放」 */}
      {mounted ? (
        <Pressable
          onPress={() => {
            setSrc(null);
            setLoading(true);
            onPlayingChange(false);
          }}
          hitSlop={8}
          style={{
            position: 'absolute',
            left: 8,
            top: 8,
            width: 28,
            height: 28,
            borderRadius: 14,
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: 'rgba(0,0,0,0.55)',
          }}>
          <Icon sf="xmark" ion="close" size={15} color="#FFFFFF" />
        </Pressable>
      ) : null}
    </View>
  );
}
