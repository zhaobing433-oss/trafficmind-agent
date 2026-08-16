/**
 * RAG V2 · 检索追踪面板 — Phase 11
 *
 * 6 Tab：检索计划 / 多路召回 / 融合与重排 / 最终证据 / 过滤与拒绝 / 性能
 *
 * 点击回答中的 [E1] 可滚动定位到对应 Evidence 卡片。
 * 使用 AbortController 控制请求生命周期。
 * 所有 Hook 调用在组件顶层，确保渲染周期内 Hook 数量固定。
 */
import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  Tabs, Empty, Tag, Descriptions, Collapse, Spin, Alert,
  Card, Typography, Statistic, Row, Col, Space,
} from "antd";
import {
  SearchOutlined, NodeIndexOutlined, SwapOutlined,
  SafetyCertificateOutlined, StopOutlined, DashboardOutlined,
  LinkOutlined, ClockCircleOutlined, WarningOutlined,
} from "@ant-design/icons";
import type { RagTrace, RagTraceStage, RagEvidenceItem, RetrievalRoute } from "../../types/ragV2";
import {
  EMPTY_RAG_TRACE, ROUTE_LABELS, EVIDENCE_STATE_LABELS,
  EVIDENCE_STATE_COLORS,
} from "../../types/ragV2";
import { ragV2GetTrace } from "../../api/ragV2Api";
import RagPanelErrorBoundary from "./RagPanelErrorBoundary";
import RagEvidenceCard from "./RagEvidenceCard";

const { Text } = Typography;
const { Panel } = Collapse;

interface Props {
  traceId: string;
  evidence?: RagEvidenceItem[];
  visible?: boolean;
  onEvidenceClick?: (evidenceId: string) => void;
}

/** 格式化毫秒 */
function fmtMs(ms: number): string {
  if (ms < 1000) return `${ms.toFixed(0)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

/** 提取 stage by name */
function findStage(stages: RagTraceStage[], name: string): RagTraceStage | undefined {
  return stages.find((s) => s.stage === name);
}

/** Safe string from Record<string, unknown> */
function safeStr(v: unknown, fallback: string = "—"): string {
  if (typeof v === "string") return v;
  if (typeof v === "number") return String(v);
  return fallback;
}

/** Safe number from Record<string, unknown> */
function safeNum(v: unknown, fallback: number = 0): number {
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const n = parseFloat(v);
    return isNaN(n) ? fallback : n;
  }
  return fallback;
}

/** Safe array from unknown */
function safeArr(v: unknown): string[] {
  if (Array.isArray(v)) return v.map((item) => String(item));
  return [];
}

const RagTracePanel: React.FC<Props> = ({
  traceId,
  evidence = [],
  visible = true,
  onEvidenceClick,
}) => {
  const [trace, setTrace] = useState<RagTrace>(EMPTY_RAG_TRACE);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [highlightedEvidence, setHighlightedEvidence] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Fetch trace
  useEffect(() => {
    if (!traceId || !visible) return;

    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    let cancelled = false;
    setTrace(EMPTY_RAG_TRACE);
    setLoading(true);
    setError(null);

    ragV2GetTrace(traceId, controller.signal)
      .then((data) => {
        if (!cancelled) {
          setTrace(data);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (
          err instanceof DOMException &&
          err.name === "AbortError"
        ) {
          return;
        }
        const msg =
          err && typeof err === "object" && "detail" in err
            ? String((err as Record<string, unknown>).detail)
            : String(err);
        setError(msg);
        setLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [traceId, visible]);

  // Scroll to evidence on click — also support document navigation
  const handleEvidenceClick = useCallback(
    (evidenceId: string, documentId?: string, chunkId?: string) => {
      setHighlightedEvidence(evidenceId);
      onEvidenceClick?.(evidenceId);

      // Phase 16 Round 2: Navigate to Knowledge document detail
      if (documentId) {
        const url = new URL(window.location.href);
        url.searchParams.set('view', 'qa');
        url.searchParams.set('knowledgeTab', 'documents');
        url.searchParams.set('knowledgeDocumentId', documentId);
        if (chunkId) url.searchParams.set('knowledgeChunkId', chunkId);
        window.location.href = url.toString();
        return;
      }

      setTimeout(() => {
        const el = document.getElementById(`evidence-${evidenceId}`);
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }, 100);
    },
    [onEvidenceClick],
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortRef.current) abortRef.current.abort();
    };
  }, []);

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 40 }}>
        <Spin tip="正在加载 RAG Trace..." />
      </div>
    );
  }

  if (error) {
    return (
      <Alert
        type="warning"
        message="RAG Trace 加载失败"
        description={error}
        style={{ margin: 8 }}
        showIcon
      />
    );
  }

  if (!trace.traceId) {
    return <Empty description="暂无 RAG Trace 数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }

  const retrievalStage = findStage(trace.stages, "hybrid_retrieval");
  const rerankStage = findStage(trace.stages, "rerank_and_policy");
  const evalStage = findStage(trace.stages, "evidence_evaluation");
  const genStage = findStage(trace.stages, "generation");
  const analysisStage = findStage(trace.stages, "query_analysis");

  const routeStr = safeStr(analysisStage?.output?.route);
  const routeKey = (routeStr as RetrievalRoute) || "cross_document";
  const complexity = safeStr(analysisStage?.output?.complexity, "simple");
  const entities = safeArr(analysisStage?.output?.explicitEntities || analysisStage?.output?.entities);
  const candidatesTotal = safeNum(retrievalStage?.output?.candidates, trace.candidatesTotal);
  const rejectedCount = safeNum(rerankStage?.output?.rejected, trace.rejectedTotal);
  const acceptedCount = safeNum(rerankStage?.output?.accepted, trace.acceptedTotal);
  const channelsUsed = safeNum(retrievalStage?.output?.channelsUsed, safeArr(retrievalStage?.output?.sample).length);

  // Tab items
  const tabItems = [
    // ── Tab 1: 检索计划 ──
    {
      key: "plan",
      label: (
        <span>
          <SearchOutlined /> 检索计划
        </span>
      ),
      children: (
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Descriptions bordered size="small" column={1}>
            <Descriptions.Item label="原始查询">
              <Text>{trace.originalQuery}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="重写查询">
              <Text code>{trace.rewrittenQuery || trace.originalQuery}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="路由">
              <Tag color="blue">
                {ROUTE_LABELS[routeKey] || routeStr}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="复杂度">
              <Tag>{complexity}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="显式实体">
              {entities.join(", ") || "—"}
            </Descriptions.Item>
            <Descriptions.Item label="需求面">
              {trace.requiredFacets?.join(", ") || "—"}
            </Descriptions.Item>
          </Descriptions>

          {trace.subqueries.length > 0 && (
            <>
              <Text strong>子查询分解 ({trace.subqueries.length})：</Text>
              {trace.subqueries.map((sq, i) => (
                <Tag key={i} style={{ marginBottom: 4 }}>
                  {i + 1}. {sq}
                </Tag>
              ))}
            </>
          )}

          {trace.usedMemoryIds.length > 0 && (
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="使用的 Memory ID">
                {trace.usedMemoryIds.join(", ")}
              </Descriptions.Item>
            </Descriptions>
          )}
        </Space>
      ),
    },

    // ── Tab 2: 多路召回 ──
    {
      key: "recall",
      label: (
        <span>
          <NodeIndexOutlined /> 多路召回 ({candidatesTotal})
        </span>
      ),
      children: (
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Row gutter={16}>
            <Col span={12}>
              <Card size="small">
                <Statistic
                  title="候选总数"
                  value={candidatesTotal}
                  suffix="条"
                />
              </Card>
            </Col>
            <Col span={12}>
              <Card size="small">
                <Statistic
                  title="检索通道"
                  value={channelsUsed}
                  suffix="路"
                />
              </Card>
            </Col>
          </Row>

          {retrievalStage && (
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="耗时">
                <ClockCircleOutlined /> {fmtMs(retrievalStage.durationMs)}
              </Descriptions.Item>
              <Descriptions.Item label="Dense 命中">
                {safeStr(retrievalStage.output?.denseCount)}
              </Descriptions.Item>
              <Descriptions.Item label="Sparse (BM25) 命中">
                {safeStr(retrievalStage.output?.sparseCount)}
              </Descriptions.Item>
              <Descriptions.Item label="Structured 命中">
                {safeStr(retrievalStage.output?.structuredCount)}
              </Descriptions.Item>
            </Descriptions>
          )}

          {safeArr(retrievalStage?.output?.sample).length > 0 && (
            <Collapse ghost>
              <Panel header="检索样本 (前3条)" key="samples">
                {safeArr(retrievalStage?.output?.sample).map((id, i) => (
                  <Tag key={i}>{id}</Tag>
                ))}
              </Panel>
            </Collapse>
          )}
        </Space>
      ),
    },

    // ── Tab 3: 融合与重排 ──
    {
      key: "rerank",
      label: (
        <span>
          <SwapOutlined /> 融合与重排 ({acceptedCount}/{candidatesTotal})
        </span>
      ),
      children: (
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Row gutter={16}>
            <Col span={8}>
              <Card size="small">
                <Statistic
                  title="接受"
                  value={acceptedCount}
                  valueStyle={{ color: "#3f8600" }}
                  suffix="条"
                />
              </Card>
            </Col>
            <Col span={8}>
              <Card size="small">
                <Statistic
                  title="拒绝"
                  value={rejectedCount}
                  valueStyle={{ color: "#cf1322" }}
                  suffix="条"
                />
              </Card>
            </Col>
            <Col span={8}>
              <Card size="small">
                <Statistic
                  title="RRF 窗口"
                  value={40}
                  suffix=""
                />
              </Card>
            </Col>
          </Row>

          {rerankStage && (
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="耗时">
                <ClockCircleOutlined /> {fmtMs(rerankStage.durationMs)}
              </Descriptions.Item>
              <Descriptions.Item label="Reranker 降级">
                {rerankStage.degraded ? (
                  <Tag color="orange" icon={<WarningOutlined />}>
                    已降级
                  </Tag>
                ) : (
                  <Tag color="green">正常</Tag>
                )}
              </Descriptions.Item>
            </Descriptions>
          )}
        </Space>
      ),
    },

    // ── Tab 4: 最终证据 ──
    {
      key: "evidence",
      label: (
        <span>
          <SafetyCertificateOutlined /> 最终证据 ({evidence.length || trace.evidenceTotal})
        </span>
      ),
      children: (
        <Space direction="vertical" style={{ width: "100%" }} size="small">
          {evalStage && (
            <Descriptions bordered size="small" column={1} style={{ marginBottom: 12 }}>
              <Descriptions.Item label="证据状态">
                <Tag color={EVIDENCE_STATE_COLORS[trace.evidenceState]}>
                  {EVIDENCE_STATE_LABELS[trace.evidenceState]}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="评估耗时">
                <ClockCircleOutlined /> {fmtMs(evalStage.durationMs)}
              </Descriptions.Item>
            </Descriptions>
          )}

          {evidence.length === 0 ? (
            <Empty
              description="无最终证据"
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          ) : (
            evidence.map((ev) => (
              <RagEvidenceCard
                key={ev.evidenceId}
                evidence={ev}
                highlighted={highlightedEvidence === ev.evidenceId}
                onClick={() => handleEvidenceClick(ev.evidenceId, ev.documentId as string | undefined, ev.chunkId as string | undefined)}
              />
            ))
          )}
        </Space>
      ),
    },

    // ── Tab 5: 过滤与拒绝 ──
    {
      key: "rejected",
      label: (
        <span>
          <StopOutlined /> 过滤与拒绝 ({rejectedCount})
        </span>
      ),
      children: (
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Alert
            message="以下候选被证据策略过滤"
            description="可能原因：已过期、权威等级过低、同文档超出上限、同章节超出上限、内容重复"
            type="info"
            showIcon
          />

          {rerankStage?.degraded && (
            <Alert
              message="Reranker 降级"
              description={trace.degradedReasons?.join("; ") || "使用确定性 fallback"}
              type="warning"
              showIcon
              icon={<WarningOutlined />}
            />
          )}
        </Space>
      ),
    },

    // ── Tab 6: 性能 ──
    {
      key: "perf",
      label: (
        <span>
          <DashboardOutlined /> 性能
        </span>
      ),
      children: (
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Row gutter={16}>
            <Col span={12}>
              <Card size="small">
                <Statistic
                  title="总耗时"
                  value={trace.totalLatencyMs}
                  precision={0}
                  suffix="ms"
                />
              </Card>
            </Col>
            <Col span={12}>
              <Card size="small">
                <Statistic
                  title="索引版本"
                  value={trace.indexVersion?.slice(0, 12) || "—"}
                />
              </Card>
            </Col>
          </Row>

          <Descriptions bordered size="small" column={1}>
            {trace.stages.map((s) => (
              <Descriptions.Item key={s.stage} label={s.stage}>
                <Space>
                  <ClockCircleOutlined />
                  <Text>{fmtMs(s.durationMs)}</Text>
                  {s.degraded && (
                    <Tag color="orange" icon={<WarningOutlined />}>
                      降级
                    </Tag>
                  )}
                  {s.error && (
                    <Tag color="red">{s.error}</Tag>
                  )}
                </Space>
              </Descriptions.Item>
            ))}
            <Descriptions.Item label="Embedding 模型">
              <LinkOutlined /> {trace.embeddingModel || "—"}
            </Descriptions.Item>
            <Descriptions.Item label="Reranker 模型">
              <LinkOutlined /> {trace.rerankerModel || "—"}
            </Descriptions.Item>
            <Descriptions.Item label="整体降级">
              {trace.degraded ? (
                <Tag color="orange" icon={<WarningOutlined />}>
                  已降级
                </Tag>
              ) : (
                <Tag color="green">正常</Tag>
              )}
            </Descriptions.Item>
          </Descriptions>
        </Space>
      ),
    },
  ];

  return (
    <Card
      size="small"
      title={
        <Space>
          <SearchOutlined />
          <Text strong>RAG Trace</Text>
          {trace.degraded && (
            <Tag color="orange" icon={<WarningOutlined />}>
              降级
            </Tag>
          )}
        </Space>
      }
      extra={
        <Text type="secondary" style={{ fontSize: 12 }}>
          {trace.traceId?.slice(0, 16)}…
        </Text>
      }
      style={{ marginBottom: 12 }}
    >
      <Tabs
        items={tabItems}
        size="small"
        defaultActiveKey="plan"
        destroyInactiveTabPane={false}
      />
    </Card>
  );
};

/** Wrapped with ErrorBoundary */
const RagTracePanelWithErrorBoundary: React.FC<Props> = (props) => (
  <RagPanelErrorBoundary fallbackTitle="RAG Trace 面板加载失败">
    <RagTracePanel {...props} />
  </RagPanelErrorBoundary>
);

export default RagTracePanelWithErrorBoundary;
