/**
 * Session Memory 只读概览面板 — Phase 10
 */
import React, { useState, useEffect, useRef } from "react";
import { Drawer, Tabs, Empty, Tag, Card, Spin, Alert, Typography, Collapse } from "antd";
import { DatabaseOutlined, HistoryOutlined } from "@ant-design/icons";
import type { MemorySessionView, MemoryItem, MemoryEventThread } from "../../types/memory";
import {
  MEMORY_TYPE_LABELS, MEMORY_STATUS_LABELS, EMPTY_MEMORY_SESSION,
} from "../../types/memory";
import { getSessionMemory } from "../../api/memoryApi";

const { Text } = Typography;
const { Panel } = Collapse;

interface Props {
  sessionId: string;
  open: boolean;
  onClose: () => void;
}

const SessionMemoryPanel: React.FC<Props> = ({ sessionId, open, onClose }) => {
  const [data, setData] = useState<MemorySessionView>(EMPTY_MEMORY_SESSION);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!open || !sessionId) return;
    // Cancel previous request
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);
    getSessionMemory(sessionId, controller.signal)
      .then(setData)
      .catch((err) => {
        if (err?.name !== "AbortError") setError(err?.safeMessage || "加载失败");
      })
      .finally(() => setLoading(false));

    return () => controller.abort();
  }, [sessionId, open]);

  const currentItems: MemoryItem[] = Object.values(data.currentThread || {}).flat() as MemoryItem[];

  const typeGroups = (items: MemoryItem[]) => {
    const groups: Record<string, MemoryItem[]> = {};
    for (const item of items) {
      const t = item.memoryType || "other";
      if (!groups[t]) groups[t] = [];
      groups[t].push(item);
    }
    return groups;
  };

  const statusColor = (s: string) => {
    const m: Record<string, string> = {
      active: "green", confirmed: "blue", candidate: "gold",
      superseded: "orange", expired: "default", rejected: "red",
    };
    return m[s] || "default";
  };

  return (
    <Drawer
      title={<><DatabaseOutlined /> 会话记忆概览</>}
      placement="right"
      width={560}
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      {loading ? <Spin /> : error ? <Alert type="warning" message={error} showIcon /> : (
        <div style={{ fontSize: 13 }}>
          <Card size="small" style={{ marginBottom: 8 }}>
            <Text strong>当前事件线程</Text>
            <Tag color="blue" style={{ marginLeft: 8 }}>
              {(data.activeEventThreadId || "").slice(0, 16)}
            </Tag>
            <div style={{ marginTop: 8 }}>
              总计 {data.summary.totalItems} 项 ·
              活跃 {data.summary.activeItems} ·
              已确认 {data.summary.confirmedItems} ·
              候选 {data.summary.candidateItems} ·
              已覆盖 {data.summary.supersededItems}
            </div>
          </Card>

          <Tabs
            defaultActiveKey="current"
            size="small"
            items={[
              {
                key: "current",
                label: `当前线程 (${currentItems.length})`,
                children: currentItems.length === 0 ? (
                  <Empty description="当前线程无记忆数据" />
                ) : (
                  Object.entries(typeGroups(currentItems)).map(([type, items]) => (
                    <Card key={type} size="small" title={MEMORY_TYPE_LABELS[type] || type}
                          style={{ marginBottom: 6 }}>
                      {items.slice(0, 10).map((item, i) => (
                        <div key={i} style={{ marginBottom: 4 }}>
                          <Tag color={statusColor(item.status)}>
                            {MEMORY_STATUS_LABELS[item.status] || item.status}
                          </Tag>
                          <Tag>{item.memoryKey}</Tag>
                          <Text type="secondary" style={{ fontSize: 11 }}>
                            {item.sourceType} · {String(item.authorityLevel)}
                          </Text>
                        </div>
                      ))}
                    </Card>
                  ))
                ),
              },
              {
                key: "historical",
                label: `历史线程 (${(data.historicalThreads || []).length})`,
                children: (data.historicalThreads || []).length === 0 ? (
                  <Empty description="无历史事件线程" />
                ) : (
                  <Collapse>
                    {(data.historicalThreads || []).map((t) => (
                      <Panel
                        key={t.id}
                        header={
                          <span>
                            <HistoryOutlined /> {t.title || t.id.slice(0, 16)}
                            <Tag style={{ marginLeft: 8 }}>{t.status}</Tag>
                            <Text type="secondary" style={{ fontSize: 11 }}>
                              {t.itemCount} 项记忆 · {t.runCount} 轮
                            </Text>
                          </span>
                        }
                      >
                        <Text type="secondary">
                          创建: {t.createdAt} · 关闭: {t.closedAt || "—"}
                          <br />
                          起始Run: {t.startedRunId?.slice(0, 16)} ·
                          最后Run: {t.lastRunId?.slice(0, 16)}
                        </Text>
                      </Panel>
                    ))}
                  </Collapse>
                ),
              },
            ]}
          />
        </div>
      )}
    </Drawer>
  );
};

export default SessionMemoryPanel;
