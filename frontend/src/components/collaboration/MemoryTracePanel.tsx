/**
 * Memory V2 · 记忆追踪面板 — Phase 10
 *
 * 4 Tab：召回记忆 / 按Agent注入 / 写入结果 / 过滤与拒绝
 *
 * 所有 Hook 调用在组件顶层，确保渲染周期内 Hook 数量固定。
 */
import React, { useState, useEffect, useRef } from "react";
import { Tabs, Empty, Tag, Descriptions, Collapse, Spin, Alert, Card, Typography } from "antd";
import {
  DatabaseOutlined, RobotOutlined, EditOutlined,
  StopOutlined, CloseCircleOutlined,
} from "@ant-design/icons";
import type {
  MemoryTraceResponse, MemorySelectedItem, MemoryRejectedItem,
  AgentMemoryInjection, MemoryWriteResult,
} from "../../types/memory";
import {
  MEMORY_TYPE_LABELS, REJECTION_REASON_LABELS,
  EMPTY_MEMORY_TRACE,
} from "../../types/memory";
import { getRunMemoryTrace } from "../../api/memoryApi";

const { Text } = Typography;
const { Panel } = Collapse;

interface Props {
  runId: string;
  visible?: boolean;
}

/** 纯函数：按 memoryType 分组（不使用 Hook，无条件调用安全） */
function groupByType(items: MemorySelectedItem[]): Record<string, MemorySelectedItem[]> {
  const groups: Record<string, MemorySelectedItem[]> = {};
  for (const item of items) {
    const t = item.memoryType || "unknown";
    if (!groups[t]) groups[t] = [];
    groups[t].push(item);
  }
  return groups;
}

const MemoryTracePanel: React.FC<Props> = ({ runId, visible = true }) => {
  const [trace, setTrace] = useState<MemoryTraceResponse>(EMPTY_MEMORY_TRACE);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!runId || !visible) return;

    // Cancel any in-flight request
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    let cancelled = false;
    // Reset state for new runId
    setTrace(EMPTY_MEMORY_TRACE);
    setLoading(true);
    setError(null);

    getRunMemoryTrace(runId, controller.signal)
      .then((data) => { if (!cancelled) setTrace(data); })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(err?.safeMessage || "加载失败");
      })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [runId, visible]);

  // --- All Hooks called above this line; early returns below are safe ---

  if (!visible) return null;
  if (loading) return <Spin tip="加载记忆追踪…" />;
  if (error) return <Alert type="warning" message={error} showIcon />;

  if (!trace.hasTrace) {
    return (
      <Alert
        type="info"
        message="无记忆追踪数据"
        description={trace.message || "该运行创建于 Memory V2 之前，无记忆追踪数据。"}
        showIcon
      />
    );
  }

  // Plain computation — no Hook
  const selected: MemorySelectedItem[] = trace.selected || [];
  const rejected: MemoryRejectedItem[] = trace.rejected || [];
  const injectionMap: Record<string, AgentMemoryInjection> = trace.injectionMap || {};
  const writeResults: MemoryWriteResult[] = trace.writeResults || [];
  const byType = groupByType(selected);

  const tabItems = [
    {
      key: "recall",
      label: <><DatabaseOutlined /> 召回记忆 ({selected.length})</>,
      children: (
        <div>
          {selected.length === 0 ? (
            <Empty description="本轮未召回历史记忆" />
          ) : (
            Object.entries(byType).map(([type, items]) => (
              <Card
                key={type}
                size="small"
                title={<Text strong>{MEMORY_TYPE_LABELS[type] || type} ({items.length})</Text>}
                style={{ marginBottom: 8 }}
              >
                {items.slice(0, 10).map((item, idx) => (
                  <div key={idx} style={{ marginBottom: 4, fontSize: 12 }}>
                    <Tag>{item.memoryKey}</Tag>
                    <Text type="secondary">
                      score={item.score?.toFixed(2)} | {item.sourceType} | {item.reason}
                    </Text>
                    <div>
                      <Text code style={{ fontSize: 11 }}>
                        {JSON.stringify(item.value).slice(0, 120)}
                      </Text>
                    </div>
                  </div>
                ))}
              </Card>
            ))
          )}
        </div>
      ),
    },
    {
      key: "injection",
      label: <><RobotOutlined /> 按Agent注入 ({Object.keys(injectionMap).length})</>,
      children: (
        <Collapse accordion>
          {Object.keys(injectionMap).length === 0 ? (
            <Empty description="无Agent注入数据" />
          ) : (
            Object.entries(injectionMap).map(([agent, injection]) => (
              <Panel
                key={agent}
                header={
                  <span>
                    <Text strong>{agent}</Text>
                    <Tag style={{ marginLeft: 8 }}>{injection.itemCount} 项</Tag>
                  </span>
                }
              >
                {injection.itemCount === 0 ? (
                  <Text type="secondary">本轮未向该Agent注入历史记忆</Text>
                ) : (
                  (injection.items || []).map((item, i) => (
                    <div key={i} style={{ marginBottom: 4, fontSize: 12 }}>
                      <Tag color="blue">{item.memoryType && MEMORY_TYPE_LABELS[item.memoryType]}</Tag>
                      <Tag>{item.memoryKey}</Tag>
                      <Text type="secondary">{item.sourceType}</Text>
                    </div>
                  ))
                )}
              </Panel>
            ))
          )}
        </Collapse>
      ),
    },
    {
      key: "write",
      label: <><EditOutlined /> 写入结果 ({writeResults.length})</>,
      children: (
        <div>
          {writeResults.length === 0 ? (
            <Empty description="无写入结果" />
          ) : (
            writeResults.map((wr, idx) => {
              const colorMap: Record<string, string> = {
                create: "green", supersede: "orange", confirm: "blue",
                reject: "red", deduplicated: "default", no_op: "default",
              };
              return (
                <div key={idx} style={{ marginBottom: 6, fontSize: 12 }}>
                  <Tag color={colorMap[wr.action] || "default"}>{wr.action}</Tag>
                  <Tag>{MEMORY_TYPE_LABELS[wr.memoryType] || wr.memoryType}</Tag>
                  <Text>{wr.memoryKey}</Text>
                  {wr.itemId && <Text type="secondary" style={{ marginLeft: 8 }}>记录编号: {wr.itemId.slice(0, 12)}</Text>}
                  {wr.supersededId && (
                    <div style={{ marginTop: 2 }}>
                      <Text type="secondary">
                        <CloseCircleOutlined /> superseded: {wr.supersededId.slice(0, 12)}
                      </Text>
                    </div>
                  )}
                  {wr.reason && (
                    <div>
                      <Text type="secondary" italic>{wr.reason}</Text>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      ),
    },
    {
      key: "rejected",
      label: <><StopOutlined /> 过滤与拒绝 ({rejected.length})</>,
      children: (
        <div style={{ maxHeight: 400, overflow: "auto" }}>
          {rejected.length === 0 ? (
            <Empty description="无被拒绝/过滤的记忆" />
          ) : (
            rejected.map((r, idx) => (
              <div key={idx} style={{ marginBottom: 6, padding: 6, background: "#fff7f7", borderRadius: 4, fontSize: 12 }}>
                <Tag color="red">
                  {r.reason && REJECTION_REASON_LABELS[r.reason]
                    ? REJECTION_REASON_LABELS[r.reason]
                    : (r.reason || "未知拒绝原因")}
                </Tag>
                <Tag>{MEMORY_TYPE_LABELS[r.memoryType] || r.memoryType || "unknown"}</Tag>
                <Text strong>{r.memoryKey || "(无key)"}</Text>
                {r.eventThreadId && (
                  <Tag color="default">{String(r.eventThreadId)}</Tag>
                )}
                <div style={{ marginTop: 2 }}>
                  <Text type="secondary" style={{ fontSize: 10 }}>
                    {r.sourceRunId ? `run: ${String(r.sourceRunId)}` : ""}
                    {r.value ? ` · ${JSON.stringify(r.value).slice(0, 80)}` : ""}
                  </Text>
                </div>
              </div>
            ))
          )}
        </div>
      ),
    },
  ];

  return (
    <Card
      size="small"
      title={
        <span>
          <DatabaseOutlined /> Memory V2 · 记忆追踪
        </span>
      }
      style={{ marginTop: 12 }}
    >
      <Descriptions size="small" column={4} style={{ marginBottom: 12 }}>
        <Descriptions.Item label="Recall Intent">
          <Tag>{trace.recallIntent || "—"}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="Event Thread">
          <Text code style={{ fontSize: 11 }}>{(trace.eventThreadId || "").slice(0, 16)}</Text>
        </Descriptions.Item>
        <Descriptions.Item label="候选/选中/拒绝">
          {trace.candidates?.length ?? 0}/{selected.length}/{rejected.length}
        </Descriptions.Item>
        <Descriptions.Item label="注入Agent数">
          {Object.keys(injectionMap).length}
        </Descriptions.Item>
        <Descriptions.Item label="Token估算">{trace.tokenEstimate || 0}</Descriptions.Item>
        <Descriptions.Item label="Recall延迟">{trace.recallLatencyMs || 0}ms</Descriptions.Item>
        <Descriptions.Item label="Write延迟">{trace.writeLatencyMs || 0}ms</Descriptions.Item>
      </Descriptions>

      <Tabs defaultActiveKey="recall" size="small" items={tabItems} />
    </Card>
  );
};

export default MemoryTracePanel;
