"""
Phase 16 Round 3 — Agent Reliability & Tool Governance Tests

覆盖：
  - EventNormalizer（None/missing/malformed 处理，UNKNOWN ≠ ZERO）
  - C15（signal_fault + 拥堵证据 → CongestionAgent）
  - C30（duration=None 不崩溃，不伪造成 0）
  - ToolRegistry + ToolPolicy（READ_ONLY/HIGH_RISK/unknown fail-closed）
"""
from __future__ import annotations

import asyncio

import pytest

from backend.agent.event_normalizer import normalize_event, _coerce_numeric
from backend.agent.router import route_agents
from backend.agent.multi_agent import _get_event_info, AccidentAgent, multi_agent_analyze
from backend.agent.tool_policy import (
    PolicyDecision,
    ToolExecutionStatus,
    classify_tool_result,
    enforce_tool_request,
    evaluate_tool_request,
)
from backend.agent.tool_registry import get_tool_registry, reset_tool_registry, ToolRisk
from backend.tools.risk_tools import calculate_risk_score
from backend.tools.event_tools import standardize_event, safe_float
from backend.agent.event_chain import build_event_chain
from backend.agent.nodes import send_notification_node
from backend.workflow.state import TrafficWorkflowState
from backend.workflow.models import NodeConfig, NodeType
from backend.workflow.nodes.action import execute_action, is_current_action_approved
from backend.workflow.nodes.human_approval import execute_human_approval


# ═══════════════════════════════════════════════════════════════════════════════
# EventNormalizer — Numeric coercion
# ═══════════════════════════════════════════════════════════════════════════════

class TestNumericCoercion:
    def test_int(self):
        assert _coerce_numeric(123) == 123.0

    def test_float(self):
        assert _coerce_numeric(123.4) == 123.4

    def test_string_int(self):
        assert _coerce_numeric("123") == 123.0

    def test_string_float(self):
        assert _coerce_numeric("123.4") == 123.4

    def test_none_returns_none(self):
        assert _coerce_numeric(None) is None

    def test_empty_string_returns_none(self):
        assert _coerce_numeric("") is None

    def test_null_string_returns_none(self):
        assert _coerce_numeric("null") is None
        assert _coerce_numeric("N/A") is None

    def test_invalid_string_returns_none(self):
        assert _coerce_numeric("abc") is None

    def test_bool_returns_none(self):
        assert _coerce_numeric(True) is None


class TestNormalizeEvent:
    def test_normalize_numeric_fields(self):
        ev = normalize_event({"eventType": "accident", "avgSpeed": "16", "queueLength": 65})
        assert ev["avgSpeed"] == 16.0
        assert ev["queueLength"] == 65.0

    def test_unknown_fields_tracked(self):
        ev = normalize_event({"eventType": "accident", "duration": None, "avgSpeed": "N/A"})
        assert ev["duration"] is None
        assert ev["avgSpeed"] is None
        assert "duration" in ev["unknownFields"]
        assert "avgSpeed" in ev["unknownFields"]

    def test_invalid_value_warning(self):
        ev = normalize_event({"eventType": "accident", "duration": "abc"})
        assert ev["duration"] is None
        assert any("duration" in w for w in ev["normalizationWarnings"])

    def test_event_type_cn_normalized(self):
        ev = normalize_event({"eventType": "accident"})
        assert ev["eventTypeCn"] == "事故"

    def test_unknown_not_zero(self):
        """UNKNOWN ≠ ZERO — duration=None 不得变成 0。"""
        ev = normalize_event({"eventType": "accident", "duration": None})
        assert ev["duration"] is None, "None 不能被伪造成 0"


# ═══════════════════════════════════════════════════════════════════════════════
# C30 — duration=None 不崩溃
# ═══════════════════════════════════════════════════════════════════════════════

class TestC30NullSafety:
    def test_accident_agent_no_crash_on_none_duration(self):
        info = _get_event_info({
            "eventType": "accident", "roadName": "未知路段",
            "avgSpeed": None, "queueLength": None, "duration": None,
        })
        result = AccidentAgent().analyze(info)
        assert result["agentName"] == "AccidentAgent"
        # 不崩溃，且明确指出 duration 未知
        assert any("未知" in f for f in result["findings"])

    def test_multi_agent_analyze_no_crash_on_none(self):
        result = multi_agent_analyze({
            "eventType": "accident", "roadName": "未知路段",
            "avgSpeed": None, "queueLength": None, "duration": None,
            "weather": "clear", "timePeriod": "off_peak",
        })
        assert result["eventSummary"]["eventType"] == "事故"

    def test_duration_missing_no_crash(self):
        info = _get_event_info({"eventType": "accident", "roadName": "路"})
        result = AccidentAgent().analyze(info)
        assert result["agentName"] == "AccidentAgent"

    def test_duration_empty_string_no_crash(self):
        info = _get_event_info({"eventType": "accident", "duration": ""})
        result = AccidentAgent().analyze(info)
        assert result["agentName"] == "AccidentAgent"

    def test_duration_string_number(self):
        info = _get_event_info({"eventType": "accident", "duration": "600"})
        # "600" → 600.0，不崩溃
        result = AccidentAgent().analyze(info)
        assert result["agentName"] == "AccidentAgent"


# ═══════════════════════════════════════════════════════════════════════════════
# C15 — signal_fault + 拥堵证据 → CongestionAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestC15Routing:
    def test_signal_fault_with_congestion_adds_congestion_agent(self):
        """signal_fault + avgSpeed 低 → CongestionAgent 有资格。"""
        r = route_agents({
            "eventType": "signal_fault", "avgSpeed": 16, "queueLength": 65,
            "isMainRoad": True, "nearbySchool": True,
        })
        assert "SignalAgent" in r["selectedAgents"]
        assert "CongestionAgent" in r["selectedAgents"]

    def test_signal_fault_without_congestion_no_forced_congestion(self):
        """signal_fault 无拥堵证据 → 不强制 CongestionAgent。"""
        r = route_agents({
            "eventType": "signal_fault", "avgSpeed": 40, "queueLength": 10,
        })
        assert "SignalAgent" in r["selectedAgents"]
        assert "CongestionAgent" not in r["selectedAgents"]

    def test_congestion_evidence_via_queue_length(self):
        r = route_agents({"eventType": "signal_fault", "queueLength": 150})
        assert "CongestionAgent" in r["selectedAgents"]


# ═══════════════════════════════════════════════════════════════════════════════
# Tool Policy
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolPolicy:
    def test_read_only_allow(self):
        d = evaluate_tool_request("get_stats")
        assert d["decision"] == PolicyDecision.ALLOW.value

    def test_high_risk_require_approval(self):
        d = evaluate_tool_request("send_wechat_work")
        assert d["decision"] == PolicyDecision.REQUIRE_APPROVAL.value

    def test_unknown_tool_deny(self):
        d = evaluate_tool_request("delete_database_xyz")
        assert d["decision"] == PolicyDecision.DENY.value

    def test_registry_has_high_risk_notifications(self):
        reg = get_tool_registry()
        meta = reg.get("send_dingtalk")
        assert meta.riskLevel == ToolRisk.HIGH_RISK
        assert meta.approvalRequired is True

    def test_denied_tool_never_allow(self):
        # 未注册工具永远 deny
        for name in ["rm_rf", "drop_table", "exec_shell"]:
            assert evaluate_tool_request(name)["decision"] == PolicyDecision.DENY.value


# ═══════════════════════════════════════════════════════════════════════════════
# Malformed input robustness
# ═══════════════════════════════════════════════════════════════════════════════

class TestMalformedInput:
    def test_unknown_event_type_no_crash(self):
        r = route_agents({"eventType": "unknown_event_type_xyz"})
        # 未知名事件类型 → 默认组合，不崩溃
        assert "DispatchAgent" in r["selectedAgents"]

    def test_non_dict_event(self):
        # 非 dict 输入不崩溃
        ev = normalize_event(None)
        assert isinstance(ev, dict)

    def test_none_fields_everywhere(self):
        info = _get_event_info({
            "eventType": "accident", "roadName": None, "avgSpeed": None,
            "queueLength": None, "duration": None, "riskScore": None,
        })
        result = AccidentAgent().analyze(info)
        assert result["agentName"] == "AccidentAgent"


# ═══════════════════════════════════════════════════════════════════════════════
# Field Robustness — 遗留工具层 None/非法值不崩溃
# ═══════════════════════════════════════════════════════════════════════════════

class TestFieldRobustness:
    def test_risk_score_none_fields_no_crash(self):
        """calculate_risk_score 在 avgSpeed/queueLength/duration/confidence=None 时不崩溃。"""
        r = calculate_risk_score({
            "eventType": "accident", "avgSpeed": None, "queueLength": None,
            "duration": None, "confidence": None,
        })
        assert isinstance(r["riskScore"], int)
        assert r["riskLevel"] in ("低风险", "中风险", "高风险", "重大风险")

    def test_risk_score_malformed_string_no_crash(self):
        """非法字符串不抛异常，按默认值处理。"""
        r = calculate_risk_score({
            "eventType": "accident", "avgSpeed": "abc", "queueLength": "N/A",
            "duration": "", "confidence": "null",
        })
        assert isinstance(r["riskScore"], int)

    def test_standardize_event_none_no_crash(self):
        """standardize_event 在 vehicleCount/duration=None 时不崩溃（ZERO 语义回落）。"""
        se = standardize_event({
            "eventType": "accident", "roadName": "路",
            "avgSpeed": None, "queueLength": None, "duration": None,
            "vehicleCount": None, "confidence": None,
        })
        assert se["duration"] == 0.0
        assert se["vehicleCount"] == 0
        assert se["confidence"] == 0.9

    def test_event_chain_none_no_crash(self):
        """build_event_chain 在 None 数值字段上不崩溃（C30 关联路径）。"""
        info = _get_event_info({
            "eventType": "accident", "roadName": "未知路段",
            "avgSpeed": None, "queueLength": None, "duration": None,
        })
        chain = build_event_chain(info, [AccidentAgent().analyze(info)])
        assert "chain" in chain
        assert "triggerReasons" in chain


# ═══════════════════════════════════════════════════════════════════════════════
# Tool Failure Semantics（Section 17）
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolFailureSemantics:
    def test_none_result_is_failure(self):
        assert classify_tool_result(None) == ToolExecutionStatus.FAILURE

    def test_sent_false_is_failure(self):
        assert classify_tool_result({"sent": False, "error": "x"}) == ToolExecutionStatus.FAILURE

    def test_saved_false_is_failure(self):
        assert classify_tool_result({"saved": False}) == ToolExecutionStatus.FAILURE

    def test_status_failed_is_failure(self):
        assert classify_tool_result({"status": "failed"}) == ToolExecutionStatus.FAILURE

    def test_ok_result_is_success(self):
        assert classify_tool_result({"sent": True}) == ToolExecutionStatus.SUCCESS
        assert classify_tool_result({"saved": True}) == ToolExecutionStatus.SUCCESS

    def test_error_field_is_failure(self):
        assert classify_tool_result({"status": "executed", "error": "boom"}) == ToolExecutionStatus.FAILURE


# ═══════════════════════════════════════════════════════════════════════════════
# ToolPolicy 门禁（Section 11/12/13）— 阻止执行 + fail-closed
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolPolicyGate:
    def test_unknown_tool_denied(self):
        g = enforce_tool_request("rm_rf_everything")
        assert g["allowed"] is False
        assert g["status"] == ToolExecutionStatus.DENIED.value

    def test_high_risk_requires_approval(self):
        g = enforce_tool_request("notify_wechat")
        assert g["allowed"] is False
        assert g["status"] == ToolExecutionStatus.APPROVAL_REQUIRED.value
        assert g["approvalRequired"] is True

    def test_high_risk_allowed_when_approved(self):
        g = enforce_tool_request("notify_wechat", is_approved=True)
        assert g["allowed"] is True

    def test_read_only_allowed(self):
        g = enforce_tool_request("get_stats")
        assert g["allowed"] is True

    def test_write_allowed(self):
        g = enforce_tool_request("save_result")
        assert g["allowed"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# Workflow action 节点 ToolPolicy 集成（Section 13/14）
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkflowToolPolicyIntegration:
    """execute_action 必须阻止 denied / approval_required 的工具，绝不执行。"""

    def _state(self) -> TrafficWorkflowState:
        return TrafficWorkflowState(workflow_run_id="wfrun_test", workflow_definition_id="d1")

    def _action_config(self, action_type: str) -> NodeConfig:
        return NodeConfig(node_id="action1", node_type=NodeType.ACTION,
                          config={"action_type": action_type})

    def test_unknown_tool_denied_never_executed(self, monkeypatch):
        calls = []

        async def fake_dispatch(action_type, params, state):
            calls.append(action_type)
            return {"status": "executed"}

        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)
        result = asyncio.run(execute_action(self._state(), self._action_config("totally_unknown_tool")))
        assert result["status"] == "denied"
        assert result["executed"] is False
        assert calls == []  # 永不执行

    def test_high_risk_not_approved_never_executed(self, monkeypatch):
        calls = []

        async def fake_dispatch(action_type, params, state):
            calls.append(action_type)
            return {"status": "executed"}

        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)
        result = asyncio.run(execute_action(self._state(), self._action_config("notify_wechat")))
        assert result["status"] == "approval_required"
        assert result["approvalRequired"] is True
        assert calls == []

    def test_high_risk_approved_executes(self, monkeypatch):
        calls = []

        async def fake_dispatch(action_type, params, state):
            calls.append(action_type)
            return {"status": "executed", "sent": True}

        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)
        state = self._state()
        state.approved_actions = [{"actionType": "notify_wechat", "params": {}}]
        result = asyncio.run(execute_action(state, self._action_config("notify_wechat")))
        assert result["status"] == "succeeded"
        assert calls == ["notify_wechat"]

    def test_failed_dispatch_not_marked_success(self, monkeypatch):
        """工具返回失败结果（sent=False）时，不得标记为 succeeded。"""
        async def fake_dispatch(action_type, params, state):
            return {"sent": False, "error": "webhook down"}

        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)
        state = self._state()
        state.approved_actions = [{"actionType": "notify_wechat"}]
        result = asyncio.run(execute_action(state, self._action_config("notify_wechat")))
        assert result["status"] == "failed"  # 不是 succeeded

    def test_denied_tool_records_audit(self, monkeypatch):
        async def fake_dispatch(action_type, params, state):
            return {"status": "executed"}

        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)
        state = self._state()
        asyncio.run(execute_action(state, self._action_config("unknown_x")))
        assert any(e["eventType"] == "tool_denied" for e in state.audit_events)


# ═══════════════════════════════════════════════════════════════════════════════
# Approval Scope Isolation（Security Closure — 防 scope escalation）
# ═══════════════════════════════════════════════════════════════════════════════

class TestApprovalScopeIsolation:
    def _state(self) -> TrafficWorkflowState:
        return TrafficWorkflowState(workflow_run_id="wfrun_iso", workflow_definition_id="d1")

    def _config(self, action_type: str) -> NodeConfig:
        return NodeConfig(node_id="action1", node_type=NodeType.ACTION,
                          config={"action_type": action_type})

    def test_approve_a_does_not_authorize_b(self, monkeypatch):
        """批准 A (notify_wechat) 不得授权 B (simulation_traffic_diversion)。"""
        calls = []

        async def fake_dispatch(action_type, params, state):
            calls.append(action_type)
            return {"status": "executed", "sent": True}

        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)
        state = self._state()
        state.approved_actions = [{"actionType": "notify_wechat", "params": {}}]
        result = asyncio.run(execute_action(state, self._config("simulation_traffic_diversion")))
        assert result["status"] == "approval_required"
        assert result["executed"] is False
        assert calls == []  # B 从未被 dispatch

    def test_approve_a_executes_a(self, monkeypatch):
        """批准 A 后执行 A 应放行。"""
        calls = []

        async def fake_dispatch(action_type, params, state):
            calls.append(action_type)
            return {"status": "executed", "sent": True}

        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)
        state = self._state()
        state.approved_actions = [{"actionType": "notify_wechat", "params": {}}]
        result = asyncio.run(execute_action(state, self._config("notify_wechat")))
        assert result["status"] == "succeeded"
        assert calls == ["notify_wechat"]

    def test_rejected_action_blocked(self, monkeypatch):
        """被拒绝 → approved_actions 为空 → HIGH_RISK 仍 REQUIRE_APPROVAL。"""
        calls = []

        async def fake_dispatch(action_type, params, state):
            calls.append(action_type)
            return {"status": "executed"}

        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)
        state = self._state()
        state.approved_actions = []  # 拒绝后清空
        result = asyncio.run(execute_action(state, self._config("notify_wechat")))
        assert result["status"] == "approval_required"
        assert calls == []

    def test_proposal_alias_maps_to_workflow_action(self):
        """Agent 提案 actionType (traffic_diversion) 映射到 workflow action_type。"""
        state = self._state()
        state.approved_actions = [{"actionType": "traffic_diversion", "diversionRatio": 0.35}]
        assert is_current_action_approved(state, "simulation_traffic_diversion") is True
        assert is_current_action_approved(state, "notify_wechat") is False

    def test_run_level_approval_binds_to_declared_action(self):
        """文本摘要 + 模板声明 actionType → 只授权声明动作。"""
        state = self._state()
        state.approved_actions = [
            {"source": "CongestionAgent", "action": "通知交警", "urgency": "high"},
            {"actionType": "notify_wechat", "source": "workflow_template"},
        ]
        assert is_current_action_approved(state, "notify_wechat") is True
        assert is_current_action_approved(state, "simulation_traffic_diversion") is False
        assert is_current_action_approved(state, "notify_dingtalk") is False

    def test_text_summary_without_declared_action_fails_closed(self):
        """纯文本摘要（无声明 actionType）→ fail closed，不授权任何 high-risk。"""
        state = self._state()
        state.approved_actions = [{"source": "CongestionAgent", "action": "通知交警", "urgency": "high"}]
        assert is_current_action_approved(state, "notify_wechat") is False
        assert is_current_action_approved(state, "simulation_traffic_diversion") is False

    def test_cross_run_approval_isolated(self):
        """run 1 的审批不得授权 run 2。"""
        s1 = TrafficWorkflowState(workflow_run_id="run_1", workflow_definition_id="d1")
        s1.approved_actions = [{"actionType": "notify_wechat"}]
        s2 = TrafficWorkflowState(workflow_run_id="run_2", workflow_definition_id="d1")
        assert is_current_action_approved(s2, "notify_wechat") is False

    def test_approval_required_audit_persisted_in_state(self, monkeypatch):
        """审批被阻止时，audit 记录进入 state.audit_events（可随 state_json 持久化）。"""
        async def fake_dispatch(action_type, params, state):
            return {"status": "executed"}

        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)
        state = self._state()
        asyncio.run(execute_action(state, self._config("simulation_traffic_diversion")))
        evts = [e for e in state.audit_events if e["eventType"] == "tool_approval_required"]
        assert len(evts) == 1
        payload = evts[0]["payload"]
        assert payload["tool"] == "simulation_traffic_diversion"
        assert payload["decision"] == "require_approval"
        assert payload["workflowRunId"] == "wfrun_iso"
        assert payload["executed"] is False
        assert "timestamp" in payload

    def test_text_summary_approval_blocks_unrelated_high_risk(self, monkeypatch):
        """文本摘要 + 声明 notify_wechat → 尝试 simulation_traffic_diversion 被阻止。"""
        calls = []

        async def fake_dispatch(action_type, params, state):
            calls.append(action_type)
            return {"status": "executed", "sent": True}

        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)
        state = self._state()
        state.approved_actions = [
            {"source": "CongestionAgent", "action": "通知交警", "urgency": "high"},
            {"actionType": "notify_wechat", "source": "workflow_template"},
        ]
        result = asyncio.run(execute_action(state, self._config("simulation_traffic_diversion")))
        assert result["status"] == "approval_required"
        assert calls == []


class TestHumanApprovalDeclaredActions:
    def test_records_declared_action_types(self):
        """human_approval 将模板声明的 action_types 追加为结构化审批项。"""
        from backend.workflow.state import WorkflowRunStatus
        state = TrafficWorkflowState(workflow_run_id="wfrun_h", workflow_definition_id="d1")
        state.transition(WorkflowRunStatus.RUNNING)
        state.agent_outputs = {"CongestionAgent": {"summary": "通知交警", "urgency": "high"}}
        config = NodeConfig(node_id="ha", node_type=NodeType.HUMAN_APPROVAL,
                            config={"action_types": ["notify_wechat"]})
        asyncio.run(execute_human_approval(state, config))
        assert any(
            isinstance(a, dict) and a.get("actionType") == "notify_wechat"
            for a in state.proposed_actions
        )


# ═══════════════════════════════════════════════════════════════════════════════
# /analyze_event Auto-notify Bypass（Security Closure）
# ═══════════════════════════════════════════════════════════════════════════════

class TestAutoNotifyBypass:
    def test_high_risk_notify_blocked_without_approval(self, monkeypatch):
        """/analyze_event 无 HITL 上下文：HIGH_RISK 通知不得偷偷发送。"""
        import backend.config as cfg
        monkeypatch.setattr(cfg, "NOTIFY_ENABLED", True)
        monkeypatch.setattr(cfg, "HIGH_RISK_THRESHOLD", "高风险")

        calls = []

        def fake_notify(result):
            calls.append(result)
            return {"wechat": True, "dingtalk": True, "email": True}

        monkeypatch.setattr("backend.tools.notify_tools.notify_high_risk_event", fake_notify)

        state = {"result": {"eventId": "evt_high", "riskLevel": "高风险", "riskScore": 90}}
        out = send_notification_node(state)

        # 真实通知函数未被调用（无副作用）
        assert calls == []
        notif = out["result"]["notification"]
        assert notif["status"] == "approval_required"
        assert notif["executed"] is False

    def test_low_risk_no_notify_intent(self, monkeypatch):
        """低风险事件不触发通知意图。"""
        import backend.config as cfg
        monkeypatch.setattr(cfg, "NOTIFY_ENABLED", True)
        monkeypatch.setattr(cfg, "HIGH_RISK_THRESHOLD", "高风险")

        calls = []

        def fake_notify(result):
            calls.append(result)
            return {}

        monkeypatch.setattr("backend.tools.notify_tools.notify_high_risk_event", fake_notify)

        state = {"result": {"eventId": "evt_low", "riskLevel": "低风险", "riskScore": 20}}
        out = send_notification_node(state)
        assert calls == []
        assert "notification" not in out["result"]

    def test_policy_decision_persisted(self, monkeypatch):
        """ToolPolicy 决策通过 save_event_analysis 持久化（可读回）。"""
        import backend.config as cfg
        monkeypatch.setattr(cfg, "NOTIFY_ENABLED", True)
        monkeypatch.setattr(cfg, "HIGH_RISK_THRESHOLD", "高风险")
        monkeypatch.setattr("backend.tools.notify_tools.notify_high_risk_event", lambda r: None)

        saved = []

        def fake_save(result):
            saved.append(result)
            return True

        monkeypatch.setattr("backend.agent.nodes.save_event_analysis", fake_save)

        state = {"result": {"eventId": "evt1", "riskLevel": "高风险", "riskScore": 90,
                            "standardEvent": {}}}
        out = send_notification_node(state)

        assert out["result"]["notification"]["status"] == "approval_required"
        assert out["result"]["notification"]["executed"] is False
        assert len(saved) == 1  # 重新持久化了一次
        assert saved[0]["notification"]["decision"] == "require_approval"
        assert saved[0]["notification"]["tool"] == "notify_high_risk_event"
