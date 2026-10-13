import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  View as RNView,
  useColorScheme,
} from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';

import { Text, View } from '@/components/Themed';
import { listTasks, type TaskStatus, type TaskSummary } from '@/src/api/client';
import { formatDuration, formatRelativeTime } from '@/src/utils/format';

type FilterKey = 'active' | 'completed' | 'failed';

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'active', label: '进行中' },
  { key: 'completed', label: '已完成' },
  { key: 'failed', label: '失败' },
];

const STATUS_META: Record<TaskStatus, { label: string; color: string }> = {
  queued: { label: '排队中', color: '#8e44ad' },
  running: { label: '进行中', color: '#2980b9' },
  completed: { label: '已完成', color: '#27ae60' },
  failed: { label: '失败', color: '#e74c3c' },
  cancelled: { label: '已取消', color: '#95a5a6' },
};

function matchesFilter(task: TaskSummary, filter: FilterKey): boolean {
  switch (filter) {
    case 'active':
      return task.status === 'queued' || task.status === 'running';
    case 'completed':
      return task.status === 'completed' || task.status === 'cancelled';
    case 'failed':
      return task.status === 'failed';
  }
}

/** 有新任务或结束信号时触发一次刷新 */
function useTaskPolling(onTick: () => void) {
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const onTickRef = useRef(onTick);
  onTickRef.current = onTick;

  const start = useCallback(() => {
    if (timer.current) return;
    timer.current = setInterval(() => onTickRef.current(), 3000);
  }, []);

  const stop = useCallback(() => {
    if (timer.current) {
      clearInterval(timer.current);
      timer.current = null;
    }
  }, []);

  useEffect(() => stop, [stop]);
  return { start, stop };
}

export default function TasksScreen() {
  const router = useRouter();
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';

  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterKey>('active');

  const fetchTasks = useCallback(async () => {
    try {
      const data = await listTasks();
      setTasks(data);
      setError(null);
      return data;
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
      return null;
    }
  }, []);

  // 首次加载
  useEffect(() => {
    fetchTasks().finally(() => setLoading(false));
  }, [fetchTasks]);

  const hasActive = useMemo(
    () => tasks.some((t) => t.status === 'queued' || t.status === 'running'),
    [tasks],
  );

  const { start, stop } = useTaskPolling(async () => {
    await fetchTasks();
  });

  // 回到本页 / 有进行中任务时开启轮询
  useFocusEffect(
    useCallback(() => {
      fetchTasks();
      return () => stop();
    }, [fetchTasks, stop]),
  );
  useEffect(() => {
    if (hasActive) start();
    else stop();
  }, [hasActive, start, stop]);

  const filtered = useMemo(
    () =>
      tasks
        .filter((t) => matchesFilter(t, filter))
        .sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [tasks, filter],
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await fetchTasks();
    setRefreshing(false);
  }, [fetchTasks]);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <RNView
        style={[
          styles.filterBar,
          { borderColor: isDark ? '#333' : '#e0e0e0' },
        ]}>
        {FILTERS.map((f) => {
          const active = filter === f.key;
          const count = tasks.filter((t) => matchesFilter(t, f.key)).length;
          return (
            <Pressable
              key={f.key}
              style={[styles.filterItem, active && styles.filterItemActive]}
              onPress={() => setFilter(f.key)}>
              <Text style={[styles.filterText, active && styles.filterTextActive]}>
                {f.label}
                {count > 0 ? ` ${count}` : ''}
              </Text>
            </Pressable>
          );
        })}
      </RNView>

      {error ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable onPress={() => fetchTasks()}>
            <Text style={styles.retryText}>点击重试</Text>
          </Pressable>
        </View>
      ) : (
        <FlatList
          data={filtered}
          keyExtractor={(item) => item.task_id}
          contentContainerStyle={filtered.length === 0 && styles.emptyContainer}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          }
          ListEmptyComponent={
            <View style={styles.center}>
              <Text style={styles.emptyEmoji}>🎬</Text>
              <Text style={styles.emptyTitle}>暂无任务</Text>
              <Text style={styles.emptySubtitle}>
                切换到「新建」，粘贴 B 站 / YouTube 链接开始总结
              </Text>
            </View>
          }
          renderItem={({ item }) => (
            <TaskCard task={item} onPress={() => router.push(`/task/${item.task_id}`)} />
          )}
        />
      )}
    </View>
  );
}

function TaskCard({
  task,
  onPress,
}: {
  task: TaskSummary;
  onPress: () => void;
}) {
  const meta = STATUS_META[task.status];
  const displayTitle =
    task.title ?? task.page_title ?? task.source;

  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.card, pressed && styles.cardPressed]}>
      <View style={styles.cardBody}>
        <View style={styles.cardHeader}>
          <RNView style={styles.cardTitleBox}>
            <Text style={styles.cardTitle} numberOfLines={2}>
              {displayTitle}
            </Text>
          </RNView>
          <RNView style={[styles.badge, { backgroundColor: meta.color }]}>
            <Text style={styles.badgeText}>{meta.label}</Text>
          </RNView>
        </View>
        <Text style={styles.cardMeta} numberOfLines={1}>
          {formatRelativeTime(task.created_at)}
          {task.status === 'completed' && task.task_duration_seconds
            ? ` · 耗时 ${formatDuration(task.task_duration_seconds)}`
            : ''}
        </Text>
      </View>
    </Pressable>
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
  filterBar: {
    flexDirection: 'row',
    borderBottomWidth: 1,
  },
  filterItem: {
    flex: 1,
    paddingVertical: 12,
    alignItems: 'center',
  },
  filterItemActive: {
    borderBottomWidth: 2,
    borderBottomColor: '#fb7299',
  },
  filterText: {
    fontSize: 14,
    opacity: 0.6,
  },
  filterTextActive: {
    opacity: 1,
    fontWeight: '600',
  },
  errorText: {
    color: '#e74c3c',
    marginBottom: 8,
  },
  retryText: {
    color: '#2980b9',
  },
  emptyContainer: {
    flexGrow: 1,
  },
  emptyEmoji: {
    fontSize: 48,
    marginBottom: 16,
  },
  emptyTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    marginBottom: 8,
  },
  emptySubtitle: {
    fontSize: 14,
    opacity: 0.6,
    textAlign: 'center',
  },
  card: {
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#ccc',
  },
  cardPressed: {
    opacity: 0.6,
  },
  cardBody: {
    backgroundColor: 'transparent',
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 8,
    marginBottom: 6,
  },
  cardTitleBox: {
    flex: 1,
  },
  cardTitle: {
    fontSize: 15,
    fontWeight: '600',
    lineHeight: 20,
  },
  badge: {
    borderRadius: 4,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  badgeText: {
    color: '#fff',
    fontSize: 11,
  },
  cardMeta: {
    fontSize: 12,
    opacity: 0.5,
  },
});
