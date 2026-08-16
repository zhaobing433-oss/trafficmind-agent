/**
 * RAG V2 Evidence Card — Phase 11
 *
 * 展示单条 Evidence 的详细信息：
 * - Evidence ID, 标题, 章节, docType, 权威等级, 有效期
 * - retrievalChannels, RRF score, Rerank score
 * - 内容摘要
 */
import React from "react";
import { Card, Tag, Descriptions, Typography, Space, Tooltip } from "antd";
import {
  FileTextOutlined,
  ClockCircleOutlined,
  StarOutlined,
  LinkOutlined,
  NodeIndexOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import type { RagEvidenceItem } from "../../types/ragV2";
import {
  DOC_TYPE_LABELS,
  AUTHORITY_LABELS,
} from "../../types/ragV2";

const { Text, Paragraph } = Typography;

interface Props {
  evidence: RagEvidenceItem;
  highlighted?: boolean;
  onClick?: () => void;
}

const channelColors: Record<string, string> = {
  dense: "blue",
  sparse: "green",
  structured: "orange",
};

const RagEvidenceCard: React.FC<Props> = ({ evidence, highlighted, onClick }) => {
  const e = evidence;
  const isExpired = e.effectiveTo && new Date(e.effectiveTo) < new Date();

  return (
    <Card
      id={`evidence-${e.evidenceId}`}
      size="small"
      hoverable={!!onClick}
      onClick={onClick}
      style={{
        marginBottom: 12,
        borderColor: highlighted ? "#1890ff" : undefined,
        boxShadow: highlighted ? "0 0 8px rgba(24,144,255,0.3)" : undefined,
      }}
      extra={
        <Tag
          color={highlighted ? "blue" : "default"}
          style={{ fontWeight: "bold" }}
        >
          [{e.evidenceId}]
        </Tag>
      }
      title={
        <Space wrap size={[4, 4]}>
          <FileTextOutlined />
          <Text strong ellipsis={{ tooltip: e.title }}>
            {e.title || "未命名证据"}
          </Text>
          {isExpired && (
            <Tag color="red" icon={<ClockCircleOutlined />}>
              已过期
            </Tag>
          )}
        </Space>
      }
    >
      {/* Section path */}
      {e.sectionPath && (
        <Paragraph
          type="secondary"
          style={{ fontSize: 12, marginBottom: 8 }}
        >
          <NodeIndexOutlined /> {e.sectionPath}
        </Paragraph>
      )}

      {/* Meta tags */}
      <Space wrap size={[4, 4]} style={{ marginBottom: 8 }}>
        <Tooltip title="文档类型">
          <Tag>{DOC_TYPE_LABELS[e.docType] || e.docType}</Tag>
        </Tooltip>
        <Tooltip title="权威等级">
          <Tag
            icon={<SafetyCertificateOutlined />}
            color={
              e.authorityLevel === "official"
                ? "red"
                : e.authorityLevel === "professional"
                  ? "orange"
                  : "default"
            }
          >
            {AUTHORITY_LABELS[e.authorityLevel] || e.authorityLevel}
          </Tag>
        </Tooltip>
        {e.effectiveFrom && (
          <Tooltip title={`有效期: ${e.effectiveFrom} ~ ${e.effectiveTo || "无"}`}>
            <Tag icon={<ClockCircleOutlined />}>
              {e.effectiveFrom?.slice(0, 10)}
            </Tag>
          </Tooltip>
        )}
      </Space>

      {/* Channels + Scores */}
      <Space wrap size={[4, 4]} style={{ marginBottom: 8 }}>
        {e.retrievalChannels.map((ch) => (
          <Tooltip key={ch} title={`${ch} 通道命中`}>
            <Tag color={channelColors[ch] || "default"} icon={<LinkOutlined />}>
              {ch}
            </Tag>
          </Tooltip>
        ))}
        {e.rrfScore != null && (
          <Tooltip title="RRF 融合分数">
            <Tag color="purple">
              RRF: {e.rrfScore.toFixed(4)}
            </Tag>
          </Tooltip>
        )}
        {e.rerankScore != null && (
          <Tooltip title="Cross-Encoder 重排分数">
            <Tag icon={<StarOutlined />} color="gold">
              Rerank: {e.rerankScore.toFixed(4)}
            </Tag>
          </Tooltip>
        )}
      </Space>

      {/* Content preview — stopPropagation so "展开"/"收起" doesn't trigger card navigation */}
      <div onClick={(e) => e.stopPropagation()}>
        <Paragraph
          ellipsis={{ rows: 3, expandable: true, symbol: "展开" }}
          style={{
            fontSize: 13,
            color: "#555",
            background: "#fafafa",
            padding: 8,
            borderRadius: 4,
            marginBottom: 0,
            whiteSpace: "pre-wrap",
          }}
        >
          {e.content?.slice(0, 500) || e.contextualContent?.slice(0, 500) || "（无内容）"}
        </Paragraph>
      </div>

      {/* Source URI */}
      {e.sourceUri && (
        <Text type="secondary" style={{ fontSize: 11 }}>
          来源: {e.sourceUri}
        </Text>
      )}
    </Card>
  );
};

export default React.memo(RagEvidenceCard);
