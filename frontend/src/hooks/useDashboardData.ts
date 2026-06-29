/**
 * 仪表盘数据轮询 Hook
 * 每 15 秒自动刷新 stats 和 history
 */

import { useState, useEffect, useCallback } from 'react';
import { getStats, getHistory } from '../api';
import type { StatsResponse, EventRecord } from '../types';

export interface DashboardData {
  stats: StatsResponse | null;
  events: EventRecord[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useDashboardData(): DashboardData {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [s, h] = await Promise.all([
        getStats(),
        getHistory(50),
      ]);
      setStats(s);
      setEvents(h.records);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : '数据加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, 15000); // 15s 轮询
    return () => clearInterval(timer);
  }, [fetchData]);

  return { stats, events, loading, error, refresh: fetchData };
}
