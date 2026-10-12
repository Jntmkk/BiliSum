import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  Share,
  StyleSheet,
  View as RNView,
  useColorScheme,
} from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import Markdown from 'react-native-markdown-display';

import { Text, View } from '@/components/Themed';
import {
  getTask,
  getTaskProgress,
  type TaskDetail,
  type TaskProgress,
} from '@/src/api/client';

type TabKey = 'summary' | 'timeline' | 'transcript';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'summary', label: '摘要' },
  { key: 'timeline', label: '时间轴' },
  { key: 'transcript', label: '全文' },
];

function formatTimestamp(seconds: number | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '00:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export default function TaskDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';

  const [task, setTask] = useState<TaskDetail | null>(null);
  const [progress, setProgress] = useState<TaskProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>('summary');
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const isActive = task?.status === 'queued' || task?.status === 'running';

  const fetchDetail = useCallback(async () => {
    try {
      const data = await getTask(id);
      setTask(data);
      setError(null);
      if (data.status === 'queued' || data.status === 'running') {
        setProgress(await getTaskProgress(id));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    }
  }, [id]);

  // 任务进行中时轮询详情 + 进度
  useEffect(() => {
    fetchDetail();
  }, [fetchDetail]);

  useEffect(() => {
    if (timer.current) {
      clearInterval(timer.current);
      timer.current = null;
    }
    if (isActive) {
      timer.current = setInterval(fetchDetail, 3000);
    }
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [isActive, fetchDetail]);

  const markdownStyles = {
    body: { color: isDark ? '#eee' : '#222', fontSize: 15, lineHeight: 24 },
    heading2: { fontSize: 18, fontWeight: '700' as const, marginVertical: 10 },
    heading3: { fontSize: 16, fontWeight: '600' as const, marginVertical: 8 },
    code_inline: {
      backgroundColor: isDark ? '#2a2a2a' : '#f0f0f0',
      borderRadius: 4,
      fontFamily: 'monospace',
    },
    fence: {
      backgroundColor: isDark ? '#2a2a2a' : '#f5f5f5',
      borderRadius: 8,
      padding: 10,
      fontFamily: 'monospace',
    },
    link: { color: '#fb7299' },
    list_item: { marginVertical: 4 },
  };

  if (error) {
    return (
      <View style={styles.center}>
        <Text style={styles.errorText}>{error}</Text>
        <Pressable onPress={fetchDetail}>
          <Text style={styles.linkText}>点击重试</Text>
        </Pressable>
      </View>
    );
  }

  if (!task) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  const result = task.result;

  return (
    <View style={styles.container}>
      {/* 页签栏 */}
      <RNView
        style={[
          styles.tabBar,
          { borderColor: isDark ? '#333' : '#e0e0e0' },
        ]}>
        {TABS.map((t) => (
          <Pressable
            key={t.key}
            style={[styles.tabItem, tab === t.key && styles.tabItemActive]}
            onPress={() => setTab(t.key)}>
            <Text style={[styles.tabText, tab === t.key && styles.tabTextActive]}>
              {t.label}
            </Text>
          </Pressable>
        ))}
      </RNView>

      {/* 进行中的进度提示 */}
      {isActive && (
        <RNView
          style={[
            styles.progressBanner,
            { backgroundColor: isDark ? '#22303c' : '#eaf4fd' },
          ]}>
          <ActivityIndicator size="small" />
          <Text style={styles.progressText}>
            {progress?.latest_message ??
              progress?.latest_stage ??
              '任务进行中…'}
            {progress && progress.progress > 0 ? ` (${progress.progress}%)` : ''}
          </Text>
        </RNView>
      )}

      {task.status === 'failed' && (
        <View style={styles.center}>
          <Text style={styles.errorText}>
            {task.error_message ?? '任务失败'}
          </Text>
        </View>
      )}

      {/* 摘要 */}
      {tab === 'summary' && (
        <ScrollView contentContainerStyle={styles.scrollContent}>
          {result?.overview ? (
            <RNView
              style={[
                styles.overviewBox,
                { backgroundColor: isDark ? '#2a2a2a' : '#f6f6f6' },
              ]}>
              <Text style={styles.overviewText}>{result.overview}</Text>
            </RNView>
          ) : null}
          {result?.knowledge_note_markdown ? (
            <Markdown style={markdownStyles}>
              {result.knowledge_note_markdown}
            </Markdown>
          ) : (
            !isActive && (
              <View style={styles.center}>
                <Text style={styles.emptyText}>暂无摘要内容</Text>
              </View>
            )
          )}
        </ScrollView>
      )}

      {/* 时间轴 */}
      {tab === 'timeline' && (
        <ScrollView contentContainerStyle={styles.scrollContent}>
          {result?.timeline && result.timeline.length > 0 ? (
            result.timeline.map((item, index) => (
              <RNView
                key={index}
                style={[
                  styles.timelineItem,
                  { borderColor: isDark ? '#333' : '#e0e0e0' },
                ]}>
                <RNView style={styles.timelineBadge}>
                  <Text style={styles.timelineTime}>
                    {formatTimestamp(item.start)}
                  </Text>
                </RNView>
                <RNView style={styles.timelineBody}>
                  <Text style={styles.timelineTitle}>{item.title ?? ''}</Text>
                  {item.summary ? (
                    <Text style={styles.timelineSummary}>{item.summary}</Text>
                  ) : null}
                </RNView>
              </RNView>
            ))
          ) : (
            <View style={styles.center}>
              <Text style={styles.emptyText}>暂无章节时间轴</Text>
            </View>
          )}
        </ScrollView>
      )}

      {/* 全文 */}
      {tab === 'transcript' && (
        <ScrollView contentContainerStyle={styles.scrollContent}>
          {result?.transcript_text ? (
            <>
              <Pressable
                style={styles.copyButton}
                onPress={() => Share.share({ message: result.transcript_text })}>
                <Text style={styles.linkText}>分享 / 复制全文</Text>
              </Pressable>
              <Text style={styles.transcriptText}>{result.transcript_text}</Text>
            </>
          ) : (
            <View style={styles.center}>
              <Text style={styles.emptyText}>暂无转写全文</Text>
            </View>
          )}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
  tabBar: {
    flexDirection: 'row',
    borderBottomWidth: 1,
  },
  tabItem: {
    flex: 1,
    paddingVertical: 12,
    alignItems: 'center',
  },
  tabItemActive: {
    borderBottomWidth: 2,
    borderBottomColor: '#fb7299',
  },
  tabText: {
    fontSize: 14,
    opacity: 0.6,
  },
  tabTextActive: {
    opacity: 1,
    fontWeight: '600',
  },
  progressBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    padding: 12,
    margin: 12,
    borderRadius: 8,
  },
  progressText: {
    fontSize: 13,
    flexShrink: 1,
  },
  scrollContent: {
    padding: 16,
    flexGrow: 1,
  },
  overviewBox: {
    borderRadius: 8,
    padding: 12,
    marginBottom: 16,
  },
  overviewText: {
    fontSize: 14,
    lineHeight: 22,
  },
  timelineItem: {
    flexDirection: 'row',
    borderLeftWidth: 2,
    paddingLeft: 12,
    paddingVertical: 10,
  },
  timelineBadge: {
    width: 52,
    paddingTop: 2,
  },
  timelineTime: {
    fontFamily: 'monospace',
    fontSize: 13,
    color: '#fb7299',
    fontWeight: '600',
  },
  timelineBody: {
    flex: 1,
  },
  timelineTitle: {
    fontSize: 15,
    fontWeight: '600',
    marginBottom: 4,
  },
  timelineSummary: {
    fontSize: 13,
    opacity: 0.65,
    lineHeight: 20,
  },
  copyButton: {
    marginBottom: 12,
  },
  transcriptText: {
    fontSize: 14,
    lineHeight: 24,
  },
  errorText: {
    color: '#e74c3c',
    marginBottom: 8,
    textAlign: 'center',
  },
  emptyText: {
    opacity: 0.5,
  },
  linkText: {
    color: '#2980b9',
  },
});
