"""
Phase 18 Round 1 — PlanProposal strict parser 单元测试

覆盖：
  - 正常解析（valid proposal）
  - unknown field reject（P06/P07 边界）
  - raw toolName/agentType/actionType/riskLevel/approvalRequired/retryPolicy/timeoutSeconds → reject（P07）
  - 重复 proposalStepId reject（P21）
  - 错误 primitive 类型 reject
  - 嵌套 unknown field reject
  - PlannerFailure canonical code
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.planning.proposal import (
    PlannerFailure,
    PlannerFailureCode,
    PlanProposal,
    PlanProposalStep,
)


def _valid_proposal_dict():
    return {
        "proposalId": "p1",
        "goal": "分析事故拥堵",
        "goalSummary": "事故+拥堵分析",
        "assumptions": ["事故风险高"],
        "steps": [
            {
                "proposalStepId": "s1",
                "intent": "analyze accident",
                "expectedOutcome": "事故影响",
                "requiredCapabilities": ["accident_analysis"],
                "evidenceNeeds": [],
                "riskHint": "high",
                "dependsOnProposalStepIds": [],
                "actionIntent": None,
                "parameterHints": {},
            },
        ],
        "requiredCapabilities": [],
        "evidenceNeeds": [],
        "riskHints": [],
        "confidence": 0.9,
        "plannerModel": "deepseek-chat",
        "plannerReasonSummary": "事故需通知",
        "capabilitySnapshotHash": "snap_abc",
        "planningModeUsed": "llm",
        "fallbackReason": None,
    }


class TestValidProposal:
    def test_valid_proposal_parses(self):
        p = PlanProposal.from_dict_strict(_valid_proposal_dict())
        assert p.proposalId == "p1"
        assert len(p.steps) == 1
        assert isinstance(p.steps[0], PlanProposalStep)
        assert p.steps[0].requiredCapabilities == ["accident_analysis"]


class TestUnknownFields:
    def test_unknown_top_level_field_rejected(self):
        d = _valid_proposal_dict()
        d["bogusField"] = "x"
        with pytest.raises(PlannerFailure) as ei:
            PlanProposal.from_dict_strict(d)
        assert ei.value.code == PlannerFailureCode.SCHEMA_INVALID

    def test_unknown_step_field_rejected(self):
        d = _valid_proposal_dict()
        d["steps"][0]["bogusStepField"] = "x"
        with pytest.raises(PlannerFailure) as ei:
            PlanProposal.from_dict_strict(d)
        assert ei.value.code == PlannerFailureCode.SCHEMA_INVALID


class TestRawFieldsRejected:
    """P07：LLM 偷偷输出 raw tool/agent/action/risk/approval 字段 → schema reject。"""

    @pytest.mark.parametrize("raw_field", [
        "toolName", "tool_name", "agentType", "agent_type", "actionType", "action_type",
        "approvalRequired", "approval_required", "riskLevel", "risk_level",
        "retryPolicy", "retry_policy", "timeoutSeconds", "timeout_seconds",
        "stepId", "step_id",
    ])
    def test_raw_field_on_step_rejected(self, raw_field):
        d = _valid_proposal_dict()
        d["steps"][0][raw_field] = "notify_wechat"
        with pytest.raises(PlannerFailure) as ei:
            PlanProposal.from_dict_strict(d)
        assert ei.value.code == PlannerFailureCode.SCHEMA_INVALID

    @pytest.mark.parametrize("raw_field", ["toolName", "agentType", "actionType", "riskLevel"])
    def test_raw_field_on_proposal_rejected(self, raw_field):
        d = _valid_proposal_dict()
        d[raw_field] = "notify_wechat"
        with pytest.raises(PlannerFailure) as ei:
            PlanProposal.from_dict_strict(d)
        assert ei.value.code == PlannerFailureCode.SCHEMA_INVALID


class TestDuplicateProposalStepId:
    def test_duplicate_proposal_step_id_rejected(self):
        # P21
        d = _valid_proposal_dict()
        d["steps"].append(dict(d["steps"][0]))  # same proposalStepId "s1"
        with pytest.raises(PlannerFailure) as ei:
            PlanProposal.from_dict_strict(d)
        assert ei.value.code == PlannerFailureCode.SCHEMA_INVALID
        assert "proposalStepId" in ei.value.message


class TestWrongPrimitiveType:
    def test_steps_not_list_rejected(self):
        d = _valid_proposal_dict()
        d["steps"] = "not-a-list"
        with pytest.raises(PlannerFailure) as ei:
            PlanProposal.from_dict_strict(d)
        assert ei.value.code == PlannerFailureCode.SCHEMA_INVALID

    def test_confidence_wrong_type_rejected(self):
        d = _valid_proposal_dict()
        d["confidence"] = "high"
        with pytest.raises(PlannerFailure) as ei:
            PlanProposal.from_dict_strict(d)
        assert ei.value.code == PlannerFailureCode.SCHEMA_INVALID

    def test_required_capabilities_not_str_list_rejected(self):
        d = _valid_proposal_dict()
        d["steps"][0]["requiredCapabilities"] = [123]
        with pytest.raises(PlannerFailure) as ei:
            PlanProposal.from_dict_strict(d)
        assert ei.value.code == PlannerFailureCode.SCHEMA_INVALID


class TestPlannerFailure:
    def test_canonical_codes_defined(self):
        for code in [
            "llm_unavailable", "timeout", "transport_error", "invalid_json",
            "schema_invalid", "unsupported_capability", "unsupported_plan_shape",
            "compile_error", "attempts_exhausted", "snapshot_mismatch",
            "invalid_parameter_hints",
        ]:
            assert code in PlannerFailureCode.__dict__.values()

    def test_to_dict(self):
        f = PlannerFailure(PlannerFailureCode.TIMEOUT, "超时", retryable=True)
        d = f.to_dict()
        assert d == {"code": "timeout", "message": "超时", "retryable": True}
