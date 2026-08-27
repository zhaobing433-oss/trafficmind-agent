"""
Decision Context Contract — Phase 19 Round 1

执行后决策点（Critic / Semantic Replanner / Assessment）的结构化证据契约。

关键不变量：
  - T0_SYSTEM 是唯一 trusted authority，且不含任何外部自由文本
  - T1/T2/T3/T4 一律 UNTRUSTED AS INSTRUCTIONS（含真实 Tool 返回的文本）
  - assembler 纯函数：无 provider 调用、无 budget claim、无持久化写入
  - prompt_projection 是模型可见内容的唯一来源
  - fingerprint_projection 机械派生自 prompt_projection（不维护第二份人工字段表）

术语：
  - SourceSnapshotDigest —— 标识 **collector 看到的世界**
  - contextFingerprint   —— 标识 **模型看到的世界**
  两者不同：ranking-only 输入（timestamp）改变 digest 但不改变 fingerprint。

digest / fingerprint 均为 operational fingerprint（内部完整 SHA256，展示时截断），
不是 collision-free 的数学证明。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


# ═══════════════════════════════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════════════════════════════


class DecisionType(str, Enum):
    """grounded 决策点（R1 只建立契约，不接线 production 行为）。"""
    CRITIC = "critic"
    SEMANTIC_REPLAN = "semantic_replan"
    ASSESSMENT = "assessment"


class TrustClass(str, Enum):
    """证据信任分级。仅 T0 具备 instruction authority。"""
    T0_SYSTEM = "T0_SYSTEM"        # 系统/代码产生：枚举、整数、系统生成 ID、时间戳
    T1_TOOL = "T1_TOOL"            # Tool / Simulation 结构化结果（含其文本 → 不可信）
    T2_AGENT = "T2_AGENT"          # Agent 派生 summary / 分析
    T3_KNOWLEDGE = "T3_KNOWLEDGE"  # RAG 文档 / Memory 内容
    T4_EXTERNAL = "T4_EXTERNAL"    # 用户 / 外部自由文本


#: T0 之外全部为 untrusted evidence（禁止进入 trusted instruction region）
UNTRUSTED_TRUST_CLASSES = (
    TrustClass.T1_TOOL, TrustClass.T2_AGENT,
    TrustClass.T3_KNOWLEDGE, TrustClass.T4_EXTERNAL,
)

#: trustClass 排序序数（越小越可信，用于确定性 ranking）
TRUST_ORDINAL: Dict[TrustClass, int] = {
    TrustClass.T0_SYSTEM: 0,
    TrustClass.T1_TOOL: 1,
    TrustClass.T2_AGENT: 2,
    TrustClass.T3_KNOWLEDGE: 3,
    TrustClass.T4_EXTERNAL: 4,
}


class FreeText(str):
    """自由文本标记。

    进入 prompt 时与普通 str 完全一致；进入 fingerprint 时被哈希而非原样写入。
    prompt_projection 必须用它包装所有非系统生成的文本，
    这样 fingerprint_projection 可以机械判定 literal vs contentHash。
    """
    __slots__ = ()


# ═══════════════════════════════════════════════════════════════════════════════
# canonical / hash 基础设施
# ═══════════════════════════════════════════════════════════════════════════════


def canonical_json(obj: Any) -> str:
    """稳定序列化（sorted keys / 无空格 / 不转义中文）。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)


def sha256_hex(text: str) -> str:
    """完整 SHA256 十六进制（内部使用完整值，不截断）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(value: Any) -> str:
    """内容哈希（结构化值先 canonical_json）。返回完整 SHA256。"""
    raw = value if isinstance(value, str) else canonical_json(value)
    return sha256_hex(raw)


def display_digest(full_hex: str) -> str:
    """SourceSnapshotDigest 展示形式（operational fingerprint，非 collision proof）。"""
    return "dsd_" + full_hex[:16]


def display_fingerprint(full_hex: str) -> str:
    """contextFingerprint 展示形式（operational fingerprint，非 collision proof）。"""
    return "dcf_" + full_hex[:16]


# ═══════════════════════════════════════════════════════════════════════════════
# SourceProjection —— normalize 层唯一输出
# ═══════════════════════════════════════════════════════════════════════════════

NORMALIZER_VERSION = "srcnorm_v1"
ASSEMBLER_VERSION = "dca_v1"


@dataclass(frozen=True)
class SourceProjection:
    """durable row 的确定性归一化投影。

    collector 与 SourceSnapshotDigest 共用同一份 projection —— 这使
    「same digest ⇒ same DecisionContext」按构造成立，而非靠论证。
    """
    sourceRef: str
    sourceType: str
    trustClass: TrustClass
    normalizedFields: Mapping[str, Any]
    timestamp: str = ""          # ranking 输入（recency）
    nodeId: str = ""             # ranking 输入（step locality / failure relation）
    stableContentHash: str = ""  # sha256(canonical_json(normalizedFields))

    def __post_init__(self):
        if not self.stableContentHash:
            object.__setattr__(self, "stableContentHash",
                               content_hash(dict(self.normalizedFields)))

    def digest_projection(self) -> Dict[str, Any]:
        """进入 SourceSnapshotDigest 的字段。

        必须覆盖**所有** selection/ranking 可见的稳定字段，否则会出现
        「digest 相同但 selection 不同」。timestamp / nodeId 是 ranking 输入，
        因此必须在内（即使它们不会 render 进 prompt）。
        """
        return {
            "sourceRef": self.sourceRef,
            "sourceType": self.sourceType,
            "trustClass": self.trustClass.value,
            "stableContentHash": self.stableContentHash,
            "timestamp": self.timestamp,
            "nodeId": self.nodeId,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# EvidenceRef —— 打包进 DecisionContext 的证据条目
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EvidenceRef:
    """选中并打包后的证据条目（summary 已受 per-evidence 上限约束）。"""
    evidenceId: str
    sourceType: str
    sourceRef: str
    trustClass: TrustClass
    summary: str
    timestamp: str = ""
    relevance: float = 0.0
    contentHash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidenceId": self.evidenceId,
            "sourceType": self.sourceType,
            "sourceRef": self.sourceRef,
            "trustClass": self.trustClass.value,
            "summary": self.summary,
            "timestamp": self.timestamp,
            "relevance": self.relevance,
            "contentHash": self.contentHash,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ContextBudget
# ═══════════════════════════════════════════════════════════════════════════════

#: 各决策点 evidence 字符预算（Design Lock V1 §7；单位为字符，非 token）
DECISION_BUDGET_CHARS: Dict[DecisionType, int] = {
    DecisionType.CRITIC: 6000,
    DecisionType.SEMANTIC_REPLAN: 4000,
    DecisionType.ASSESSMENT: 5000,
}

#: 估算换算（沿用 rag/v2/context_packer 既有约定；是估算，不是实测 token）
CHARS_PER_ESTIMATED_TOKEN = 2


@dataclass(frozen=True)
class ContextBudget:
    """确定性字符预算。不引入 tokenizer 依赖，不调用 LLM 压缩。"""
    totalChars: int
    perEvidenceChars: int = 400
    t3ProjectionChars: int = 200
    t1Ratio: float = 0.40
    t2Ratio: float = 0.25
    t3Ratio: float = 0.15
    t4Ratio: float = 0.10

    @classmethod
    def for_decision(cls, decision_type: DecisionType) -> "ContextBudget":
        return cls(totalChars=DECISION_BUDGET_CHARS[decision_type])

    def cap_for(self, trust: TrustClass) -> int:
        """该 trustClass 的子预算上限（T0 不设上限）。"""
        ratios = {
            TrustClass.T1_TOOL: self.t1Ratio,
            TrustClass.T2_AGENT: self.t2Ratio,
            TrustClass.T3_KNOWLEDGE: self.t3Ratio,
            TrustClass.T4_EXTERNAL: self.t4Ratio,
        }
        if trust == TrustClass.T0_SYSTEM:
            return self.totalChars
        return int(self.totalChars * ratios[trust])

    @property
    def estimatedTokens(self) -> int:
        """估算 token 数（totalChars / 2）。仅供报告，不作为硬约束。"""
        return self.totalChars // CHARS_PER_ESTIMATED_TOKEN


# ═══════════════════════════════════════════════════════════════════════════════
# ObservationView —— split-trust（identity/enum 可信，文本不可信）
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ObservationView:
    """Observation 的决策投影。

    split-trust：type/status/stepId/nodeId/failureCode 为 T0（枚举与系统 ID）；
    failureReason / outputSummary 源自 node_runs.error 与 tool 输出 → T1 文本，
    只能出现在 untrusted envelope 内。
    """
    type: str
    status: str
    stepId: str = ""
    nodeId: str = ""
    failureCode: str = ""
    failureReason: str = ""
    outputSummary: str = ""

    def trusted_fields(self) -> Dict[str, Any]:
        """T0 部分（可进入 trusted region）。"""
        return {"type": self.type, "status": self.status,
                "stepId": self.stepId, "nodeId": self.nodeId,
                "failureCode": self.failureCode}

    def untrusted_fields(self) -> Dict[str, Any]:
        """T1 文本部分（必须留在 untrusted envelope 内）。"""
        return {"failureReason": self.failureReason,
                "outputSummary": self.outputSummary}

    def to_dict(self) -> Dict[str, Any]:
        d = self.trusted_fields()
        d.update(self.untrusted_fields())
        return d


# ═══════════════════════════════════════════════════════════════════════════════
# DecisionContext
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class DecisionContext:
    """结构化、有界、来源可归因的决策上下文。

    R1 只建立契约与装配；production grounded prompt 接线属于 R2/R3。
    """
    decisionType: DecisionType
    rootRunId: str
    runId: str
    planId: str
    planVersion: int

    goal: str = ""
    goalType: str = ""

    currentStepId: str = ""
    currentNodeId: str = ""

    observation: Optional[ObservationView] = None
    executionEvidence: Tuple[EvidenceRef, ...] = ()
    trajectorySummary: Mapping[str, Any] = field(default_factory=dict)

    criticRecommendation: Optional[Mapping[str, Any]] = None
    criticBoundaryKey: Optional[str] = None

    completedWorkSummary: Tuple[Mapping[str, Any], ...] = ()
    remainingObjectives: Tuple[str, ...] = ()
    budgetSnapshot: Mapping[str, Any] = field(default_factory=dict)

    contextProvenance: Tuple[Mapping[str, Any], ...] = ()
    sourceSnapshotDigest: str = ""
    assemblerVersion: str = ASSEMBLER_VERSION
    truncated: bool = False

    @property
    def isEmpty(self) -> bool:
        """空上下文 —— legacy / assembly 失败时的退化形态。"""
        return not self.executionEvidence and self.observation is None


#: assembly 失败时的退化上下文（等价 Phase18 行为，绝不 fail workflow）
def empty_decision_context(decision_type: DecisionType, run_id: str = "",
                           plan_id: str = "", plan_version: int = 1,
                           root_run_id: str = "") -> DecisionContext:
    """构造空 DecisionContext（degrade 路径）。"""
    return DecisionContext(
        decisionType=decision_type,
        rootRunId=root_run_id or run_id,
        runId=run_id,
        planId=plan_id,
        planVersion=plan_version,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# prompt_projection / fingerprint_projection
# ═══════════════════════════════════════════════════════════════════════════════


def prompt_projection(ctx: DecisionContext) -> Dict[str, Any]:
    """**模型可见内容的唯一 structured source**。

    prompt builder 只允许消费本函数输出；未出现在这里的字段，模型看不见，
    因此也不进入 contextFingerprint。

    自由文本一律用 FreeText 包装 —— fingerprint_projection 据此机械判定
    literal vs contentHash，无需第二份人工字段白名单。
    """
    obs = ctx.observation
    payload: Dict[str, Any] = {
        "decisionType": ctx.decisionType.value,
        "planVersion": ctx.planVersion,
        "goal": FreeText(ctx.goal or ""),
        "goalType": ctx.goalType or "",
        "currentStepId": ctx.currentStepId or "",
        "currentNodeId": ctx.currentNodeId or "",
        "observation": {
            "type": obs.type if obs else "",
            "status": obs.status if obs else "",
            "stepId": obs.stepId if obs else "",
            "nodeId": obs.nodeId if obs else "",
            "failureCode": obs.failureCode if obs else "",
            "failureReason": FreeText(obs.failureReason if obs else ""),
            "outputSummary": FreeText(obs.outputSummary if obs else ""),
        },
        "executionEvidence": [
            {
                "evidenceId": e.evidenceId,
                "sourceType": e.sourceType,
                "trustClass": e.trustClass.value,
                "summary": FreeText(e.summary),
            }
            for e in ctx.executionEvidence
        ],
        "trajectorySummary": dict(ctx.trajectorySummary),
        "completedWorkSummary": [dict(w) for w in ctx.completedWorkSummary],
        "remainingObjectives": [FreeText(o) for o in ctx.remainingObjectives],
        "budgetSnapshot": dict(ctx.budgetSnapshot),
        "truncated": ctx.truncated,
    }
    if ctx.decisionType == DecisionType.SEMANTIC_REPLAN:
        rec = dict(ctx.criticRecommendation or {})
        payload["criticRecommendation"] = {
            "recommendation": rec.get("recommendation", ""),
            "confidence": rec.get("confidence", 0.0),
            "semanticFailureType": rec.get("semanticFailureType", ""),
            "reasonSummary": FreeText(rec.get("reasonSummary", "")),
        }
    return payload


def fingerprint_projection(value: Any) -> Any:
    """机械递归映射（无人工白名单）。

    FreeText          → "h:" + contentHash
    enum/int/bool/id  → literal
    dict / list       → 递归（list 保序，因为顺序对模型可见）
    """
    if isinstance(value, FreeText):
        return "h:" + content_hash(str(value))
    if isinstance(value, dict):
        return {k: fingerprint_projection(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [fingerprint_projection(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    return value


def compute_context_fingerprint(ctx: DecisionContext) -> str:
    """contextFingerprint —— 标识**模型看到的世界**（完整 SHA256）。

    未 render 的字段（relevance / timestamp / contextProvenance /
    criticBoundaryKey / assemblerVersion / run identity）不参与。
    """
    return sha256_hex(canonical_json(fingerprint_projection(prompt_projection(ctx))))


def compute_source_snapshot_digest(
    projections: Sequence[SourceProjection],
    system_state: Mapping[str, Any],
) -> str:
    """SourceSnapshotDigest —— 标识 **collector 看到的世界**（完整 SHA256）。

    覆盖完整 normalized collector input + 全部 selection/ranking 可见稳定字段，
    因此「same digest ⇒ same normalized input ⇒ same selection ⇒ same context」。
    只写哈希，不写 raw body / secret。
    """
    canon = {
        "normalizerVersion": NORMALIZER_VERSION,
        "assemblerVersion": ASSEMBLER_VERSION,
        "sources": sorted(
            [p.digest_projection() for p in projections],
            key=lambda d: (d["sourceRef"], d["sourceType"]),
        ),
        "systemState": dict(system_state),
    }
    return sha256_hex(canonical_json(canon))
