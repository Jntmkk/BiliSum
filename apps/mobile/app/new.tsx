import { useCallback, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';
import * as Haptics from 'expo-haptics';

import {
  createVideoTask,
  createVideoTasksBatch,
  probeVideo,
  type VideoProbeResponse,
} from '@/src/api/client';
import { invalidateLibrary } from '@/src/api/libraryStore';
import { Card, Separator } from '@/src/components/Card';
import { Icon } from '@/src/components/Icon';
import { Txt } from '@/src/components/Txt';
import { useColors } from '@/src/theme/colors';
import { layout, spacing } from '@/src/theme/layout';
import { radius } from '@/src/theme/radius';
import { formatClock } from '@/src/utils/format';
import { platformLabel } from '@/src/utils/status';

export default function NewTaskScreen() {
  const colors = useColors();
  const router = useRouter();

  const [url, setUrl] = useState('');
  const [probing, setProbing] = useState(false);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [probe, setProbe] = useState<VideoProbeResponse | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [submitting, setSubmitting] = useState(false);

  const onProbe = useCallback(async () => {
    setProbing(true);
    setProbeError(null);
    try {
      const result = await probeVideo(url.trim());
      setProbe(result);
      setSelected(new Set(result.pages.map((p) => p.page)));
    } catch (e) {
      setProbeError(e instanceof Error ? e.message : '解析失败');
    } finally {
      setProbing(false);
    }
  }, [url]);

  const toggle = useCallback((page: number) => {
    void Haptics.selectionAsync();
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(page)) next.delete(page);
      else next.add(page);
      return next;
    });
  }, []);

  const submit = useCallback(
    async (pages: number[], videoId: string, confirm: boolean) => {
      if (pages.length === 0) {
        await createVideoTask(videoId, {});
        return null;
      }
      return createVideoTasksBatch(videoId, { page_numbers: pages, confirm });
    },
    [],
  );

  const onSubmit = useCallback(async () => {
    if (!probe) return;
    setSubmitting(true);
    try {
      const videoId = probe.video.video_id;
      const pages = [...selected].sort((a, b) => a - b);

      // 先不带 confirm 探一次：已有成功摘要的分 P 会被列出来要求确认
      const first = await submit(pages, videoId, false);
      if (first?.requires_confirmation) {
        const n = first.conflict_pages.length;
        const names = first.conflict_pages
          .slice(0, 3)
          .map((p) => `P${p.page_number}`)
          .join('、');
        const go = await new Promise<boolean>((resolve) => {
          Alert.alert(
            '部分分 P 已有摘要',
            `${names}${n > 3 ? ` 等 ${n} 个分 P` : ''} 已有成功摘要，将跳过；其余分 P 继续生成。`,
            [
              { text: '取消', style: 'cancel', onPress: () => resolve(false) },
              { text: '继续', onPress: () => resolve(true) },
            ],
            { cancelable: true, onDismiss: () => resolve(false) },
          );
        });
        if (!go) return;
        await submit(pages, videoId, true);
      }

      invalidateLibrary();
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      // 跳进视频详情，让用户看到进度，而不是无声地退回列表
      router.replace(`/video/${videoId}`);
    } catch (e) {
      Alert.alert('提交失败', e instanceof Error ? e.message : '未知错误');
    } finally {
      setSubmitting(false);
    }
  }, [probe, selected, router, submit]);

  const allSelected = probe != null && selected.size === probe.pages.length;

  return (
    <KeyboardAvoidingView
      style={{ flex: 1, backgroundColor: colors.groupedBackground }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        contentContainerStyle={{ padding: layout.margin, gap: spacing.lg }}
        keyboardShouldPersistTaps="handled">
        <View style={{ gap: spacing.sm }}>
          <Txt variant="footnote" color="secondary">
            视频链接
          </Txt>
          <View
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: spacing.sm,
              paddingHorizontal: spacing.md,
              borderRadius: radius.md,
              backgroundColor: colors.surface,
            }}>
            <TextInput
              value={url}
              onChangeText={setUrl}
              editable={!probe}
              placeholder="粘贴 B 站 / YouTube 链接或 BV 号"
              placeholderTextColor={colors.tertiaryLabel as string}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
              returnKeyType="search"
              onSubmitEditing={() => url.trim() && void onProbe()}
              style={{
                flex: 1,
                height: layout.touchTarget + 6,
                fontSize: 17,
                color: colors.label as string,
              }}
            />
            {url.length > 0 && !probe ? (
              <Pressable onPress={() => setUrl('')} hitSlop={8}>
                <Icon sf="xmark.circle.fill" ion="close-circle" size={18} color={colors.tertiaryLabel} />
              </Pressable>
            ) : null}
          </View>
        </View>

        {probeError ? (
          <Txt variant="footnote" color="danger">
            {probeError}
          </Txt>
        ) : null}

        {!probe ? (
          <Pressable
            onPress={onProbe}
            disabled={probing || !url.trim()}
            style={({ pressed }) => ({
              height: 50,
              borderRadius: radius.md,
              alignItems: 'center',
              justifyContent: 'center',
              flexDirection: 'row',
              gap: spacing.sm,
              backgroundColor: colors.accent,
              opacity: probing || !url.trim() ? 0.4 : pressed ? 0.8 : 1,
            })}>
            {probing ? <ActivityIndicator size="small" color="#FFFFFF" /> : null}
            <Txt variant="headline" style={{ color: '#FFFFFF' }}>
              {probing ? '解析中…' : '开始解析'}
            </Txt>
          </Pressable>
        ) : (
          <>
            <Card>
              <View style={{ flexDirection: 'row', gap: spacing.md, padding: spacing.lg }}>
                <View style={{ flex: 1, gap: spacing.xs }}>
                  <Txt variant="headline" numberOfLines={3}>
                    {probe.video.title}
                  </Txt>
                  <Txt variant="footnote" color="secondary">
                    {platformLabel(probe.video.platform)}
                    {probe.video.duration ? ` · ${formatClock(probe.video.duration)}` : ''}
                    {probe.cached ? ' · 已在库中' : ''}
                  </Txt>
                </View>
              </View>

              {probe.pages.length > 0 ? (
                <>
                  <Separator inset="none" />
                  <View
                    style={{
                      flexDirection: 'row',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      paddingHorizontal: layout.margin,
                      paddingTop: spacing.md,
                    }}>
                    <Txt variant="footnote" color="secondary">
                      选择要总结的分集
                    </Txt>
                    <Pressable
                      hitSlop={8}
                      onPress={() =>
                        setSelected(
                          allSelected ? new Set() : new Set(probe.pages.map((p) => p.page)),
                        )
                      }>
                      <Txt variant="footnote" color="accent">
                        {allSelected ? '取消全选' : '全选'}
                      </Txt>
                    </Pressable>
                  </View>

                  {probe.pages.map((page, i) => {
                    const checked = selected.has(page.page);
                    return (
                      <View key={page.page}>
                        {i > 0 ? <Separator /> : null}
                        <Pressable
                          onPress={() => toggle(page.page)}
                          style={({ pressed }) => ({
                            flexDirection: 'row',
                            alignItems: 'center',
                            gap: spacing.md,
                            minHeight: 48,
                            paddingHorizontal: layout.margin,
                            paddingVertical: spacing.sm,
                            backgroundColor: pressed ? colors.fill : 'transparent',
                          })}>
                          <Icon
                            sf={checked ? 'checkmark.circle.fill' : 'circle'}
                            ion={checked ? 'checkmark-circle' : 'ellipse-outline'}
                            size={22}
                            color={checked ? colors.accent : colors.tertiaryLabel}
                          />
                          <Txt variant="body" numberOfLines={1} style={{ flex: 1 }}>
                            P{page.page} {page.title}
                          </Txt>
                          <Txt variant="footnote" color="tertiary" style={{ fontVariant: ['tabular-nums'] }}>
                            {formatClock(page.duration)}
                          </Txt>
                        </Pressable>
                      </View>
                    );
                  })}
                </>
              ) : null}
            </Card>

            <View style={{ flexDirection: 'row', gap: spacing.md }}>
              <Pressable
                onPress={() => {
                  setProbe(null);
                  setProbeError(null);
                  setSelected(new Set());
                }}
                disabled={submitting}
                style={({ pressed }) => ({
                  height: 50,
                  paddingHorizontal: spacing.lg,
                  borderRadius: radius.md,
                  alignItems: 'center',
                  justifyContent: 'center',
                  backgroundColor: colors.fill,
                  opacity: pressed ? 0.7 : 1,
                })}>
                <Txt variant="headline" color="accent">
                  重新输入
                </Txt>
              </Pressable>

              <Pressable
                onPress={onSubmit}
                disabled={submitting || (probe.pages.length > 0 && selected.size === 0)}
                style={({ pressed }) => ({
                  flex: 1,
                  height: 50,
                  borderRadius: radius.md,
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexDirection: 'row',
                  gap: spacing.sm,
                  backgroundColor: colors.accent,
                  opacity:
                    submitting || (probe.pages.length > 0 && selected.size === 0)
                      ? 0.4
                      : pressed
                        ? 0.8
                        : 1,
                })}>
                {submitting ? <ActivityIndicator size="small" color="#FFFFFF" /> : null}
                <Txt variant="headline" style={{ color: '#FFFFFF' }}>
                  {probe.pages.length > 0 ? `开始总结 (${selected.size})` : '开始总结'}
                </Txt>
              </Pressable>
            </View>
          </>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
