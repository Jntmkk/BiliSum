import { useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Button,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View as RNView,
  useColorScheme,
} from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';

import { Text, View } from '@/components/Themed';
import {
  createVideoTask,
  probeVideo,
  type VideoProbeResponse,
} from '@/src/api/client';

function formatVideoDuration(seconds: number | null): string {
  if (seconds == null) return '';
  const m = Math.floor(seconds / 60);
  const h = Math.floor(m / 60);
  return h > 0 ? `${h}:${String(m % 60).padStart(2, '0')}:${String(Math.floor(seconds % 60)).padStart(2, '0')}` : `${m}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
}

export default function NewTaskScreen() {
  const router = useRouter();
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';

  const [url, setUrl] = useState('');
  const [probing, setProbing] = useState(false);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [probeResult, setProbeResult] = useState<VideoProbeResponse | null>(null);

  const [selectedPages, setSelectedPages] = useState<Set<number>>(new Set());
  const [submitting, setSubmitting] = useState(false);

  async function handleProbe() {
    setProbing(true);
    setProbeError(null);
    setProbeResult(null);
    try {
      const result = await probeVideo(url.trim());
      setProbeResult(result);
      // 默认全选所有分集
      setSelectedPages(new Set(result.pages.map((p) => p.page)));
    } catch (e) {
      setProbeError(e instanceof Error ? e.message : '解析失败');
    } finally {
      setProbing(false);
    }
  }

  function togglePage(page: number) {
    setSelectedPages((prev) => {
      const next = new Set(prev);
      if (next.has(page)) {
        next.delete(page);
      } else {
        next.add(page);
      }
      return next;
    });
  }

  async function handleSubmit() {
    if (!probeResult) return;
    setSubmitting(true);
    try {
      const video = probeResult.video;
      // 单 P 或无分集选择：直接提交；多 P：逐集提交
      const targets =
        probeResult.pages.length > 0
          ? probeResult.pages.filter((p) => selectedPages.has(p.page))
          : [null];
      const details = [];
      for (const page of targets) {
        details.push(
          await createVideoTask(video.video_id, page ? { page_number: page.page } : {}),
        );
      }
      // 回到任务列表
      router.push('/(tabs)/');
      if (details.length > 1) {
        Alert.alert('已提交', `已提交 ${details.length} 个总结任务`);
      }
    } catch (e) {
      Alert.alert('提交失败', e instanceof Error ? e.message : '未知错误');
    } finally {
      setSubmitting(false);
    }
  }

  function handleReset() {
    setProbeResult(null);
    setProbeError(null);
    setSelectedPages(new Set());
  }

  const canSubmit =
    probeResult != null &&
    !submitting &&
    (probeResult.pages.length === 0 || selectedPages.size > 0);

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled">
      <Text style={styles.label}>粘贴 B 站 / YouTube 视频链接</Text>
      <RNView
        style={[
          styles.inputRow,
          { borderColor: isDark ? '#444' : '#ccc' },
        ]}>
        <TextInput
          style={styles.input}
          placeholder="https://www.bilibili.com/video/BV…"
          placeholderTextColor="#999"
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          editable={!probeResult}
          value={url}
          onChangeText={setUrl}
        />
        {url.length > 0 && !probeResult ? (
          <Pressable onPress={() => setUrl('')} hitSlop={8}>
            <Ionicons name="close-circle" size={20} color="#999" />
          </Pressable>
        ) : null}
      </RNView>

      {probeError ? <Text style={styles.errorText}>{probeError}</Text> : null}

      {!probeResult ? (
        <Button
          title={probing ? '解析中…' : '开始解析'}
          onPress={handleProbe}
          disabled={probing || !url.trim()}
        />
      ) : (
        <View style={styles.resultCard}>
          <Text style={styles.resultTitle} numberOfLines={2}>
            {probeResult.video.title}
          </Text>
          <Text style={styles.resultMeta}>
            {probeResult.video.platform}
            {probeResult.video.duration != null
              ? ` · ${formatVideoDuration(probeResult.video.duration)}`
              : ''}
            {probeResult.cached ? ' · 已在库中' : ''}
          </Text>

          {probeResult.pages.length > 0 ? (
            <>
              <Text style={styles.pagesLabel}>
                选择要总结的分集（已选 {selectedPages.size}/{probeResult.pages.length}）
              </Text>
              {probeResult.pages.map((page) => {
                const checked = selectedPages.has(page.page);
                return (
                  <Pressable
                    key={page.page}
                    style={styles.pageRow}
                    onPress={() => togglePage(page.page)}>
                    <Ionicons
                      name={checked ? 'checkbox' : 'square-outline'}
                      size={22}
                      color={checked ? '#fb7299' : '#999'}
                    />
                    <Text style={styles.pageTitle} numberOfLines={1}>
                      P{page.page} {page.title}
                    </Text>
                    <Text style={styles.pageDuration}>
                      {formatVideoDuration(page.duration)}
                    </Text>
                  </Pressable>
                );
              })}
            </>
          ) : null}

          <RNView style={styles.submitRow}>
            <RNView style={styles.resetButton}>
              <Button title="重新输入" onPress={handleReset} disabled={submitting} />
            </RNView>
            <RNView style={styles.submitButton}>
              {submitting ? (
                <RNView style={styles.submittingRow}>
                  <ActivityIndicator size="small" />
                  <Text style={styles.submittingText}>提交中…</Text>
                </RNView>
              ) : (
                <Button
                  title={
                    probeResult.pages.length > 0
                      ? `提交 ${selectedPages.size} 个任务`
                      : '提交总结'
                  }
                  onPress={handleSubmit}
                  disabled={!canSubmit}
                />
              )}
            </RNView>
          </RNView>
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  content: {
    padding: 24,
  },
  label: {
    fontSize: 14,
    marginBottom: 12,
    opacity: 0.7,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    marginBottom: 16,
  },
  input: {
    flex: 1,
    paddingVertical: 12,
    fontSize: 16,
  },
  errorText: {
    color: '#e74c3c',
    marginBottom: 12,
  },
  resultCard: {
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e0e0e0',
  },
  resultTitle: {
    fontSize: 17,
    fontWeight: '700',
    marginBottom: 6,
  },
  resultMeta: {
    fontSize: 13,
    opacity: 0.6,
    marginBottom: 16,
  },
  pagesLabel: {
    fontSize: 13,
    opacity: 0.7,
    marginBottom: 8,
  },
  pageRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 10,
    gap: 10,
  },
  pageTitle: {
    flex: 1,
    fontSize: 15,
  },
  pageDuration: {
    fontSize: 12,
    opacity: 0.5,
    fontVariant: ['tabular-nums'],
  },
  submitRow: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 20,
    backgroundColor: 'transparent',
  },
  resetButton: {
    flex: 1,
  },
  submitButton: {
    flex: 2,
    justifyContent: 'center',
  },
  submittingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  submittingText: {
    fontSize: 14,
    opacity: 0.6,
  },
});
