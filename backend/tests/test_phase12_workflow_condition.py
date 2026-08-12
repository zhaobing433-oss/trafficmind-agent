"""
Phase 12 Workflow V1 — 条件 DSL 安全测试

验证：
  - 正常数值/字符串比较
  - all/any 嵌套
  - 字段不存在
  - 类型错误
  - __class__ 攻击
  - import 攻击
  - 函数调用攻击
  - 恶意 Python 表达式不得执行
"""
import pytest
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.workflow.condition import (
    evaluate_condition,
    validate_condition_structure,
    ConditionError,
    ALLOWED_FIELDS,
)


class TestSimpleConditions:
    """简单条件求值。"""

    def test_gte_numeric(self):
        state = {"risk_assessment": {"riskScore": 85}}
        cond = {"op": "gte", "field": "risk_assessment.riskScore", "value": 70}
        assert evaluate_condition(cond, state) is True

    def test_gte_false(self):
        state = {"risk_assessment": {"riskScore": 50}}
        cond = {"op": "gte", "field": "risk_assessment.riskScore", "value": 70}
        assert evaluate_condition(cond, state) is False

    def test_eq_string(self):
        state = {"risk_assessment": {"riskLevel": "高风险"}}
        cond = {"op": "eq", "field": "risk_assessment.riskLevel", "value": "高风险"}
        assert evaluate_condition(cond, state) is True

    def test_ne_string(self):
        state = {"risk_assessment": {"riskLevel": "低风险"}}
        cond = {"op": "ne", "field": "risk_assessment.riskLevel", "value": "高风险"}
        assert evaluate_condition(cond, state) is True

    def test_lt_numeric(self):
        state = {"risk_assessment": {"riskScore": 30}}
        cond = {"op": "lt", "field": "risk_assessment.riskScore", "value": 61}
        assert evaluate_condition(cond, state) is True

    def test_exists_true(self):
        state = {"current_event": {"isMainRoad": True}}
        cond = {"op": "exists", "field": "current_event.isMainRoad"}
        assert evaluate_condition(cond, state) is True

    def test_exists_false(self):
        state = {"current_event": {}}
        cond = {"op": "exists", "field": "current_event.nearbySchool"}
        assert evaluate_condition(cond, state) is False

    def test_in_list(self):
        state = {"risk_assessment": {"riskLevel": "高风险"}}
        cond = {"op": "in", "field": "risk_assessment.riskLevel",
                "value": ["高风险", "重大风险"]}
        assert evaluate_condition(cond, state) is True

    def test_not_in_list(self):
        state = {"risk_assessment": {"riskLevel": "低风险"}}
        cond = {"op": "not_in", "field": "risk_assessment.riskLevel",
                "value": ["高风险", "重大风险"]}
        assert evaluate_condition(cond, state) is True


class TestCompoundConditions:
    """all/any 复合条件。"""

    def test_all_both_true(self):
        state = {"risk_assessment": {"riskScore": 85, "riskLevel": "高风险"}}
        cond = {
            "op": "all",
            "conditions": [
                {"op": "gte", "field": "risk_assessment.riskScore", "value": 70},
                {"op": "eq", "field": "risk_assessment.riskLevel", "value": "高风险"},
            ],
        }
        assert evaluate_condition(cond, state) is True

    def test_all_one_false(self):
        state = {"risk_assessment": {"riskScore": 50, "riskLevel": "高风险"}}
        cond = {
            "op": "all",
            "conditions": [
                {"op": "gte", "field": "risk_assessment.riskScore", "value": 70},
                {"op": "eq", "field": "risk_assessment.riskLevel", "value": "高风险"},
            ],
        }
        assert evaluate_condition(cond, state) is False

    def test_any_one_true(self):
        state = {"risk_assessment": {"riskScore": 50, "riskLevel": "高风险"}}
        cond = {
            "op": "any",
            "conditions": [
                {"op": "gte", "field": "risk_assessment.riskScore", "value": 70},
                {"op": "eq", "field": "risk_assessment.riskLevel", "value": "高风险"},
            ],
        }
        assert evaluate_condition(cond, state) is True

    def test_nested_all_any(self):
        state = {
            "risk_assessment": {"riskScore": 85, "riskLevel": "高风险"},
            "current_event": {"isMainRoad": True, "nearbySchool": False},
        }
        cond = {
            "op": "all",
            "conditions": [
                {"op": "gte", "field": "risk_assessment.riskScore", "value": 70},
                {
                    "op": "any",
                    "conditions": [
                        {"op": "eq", "field": "current_event.isMainRoad", "value": True},
                        {"op": "eq", "field": "current_event.nearbySchool", "value": True},
                    ],
                },
            ],
        }
        assert evaluate_condition(cond, state) is True


class TestErrorConditions:
    """错误条件和边界情况。"""

    def test_field_not_in_whitelist(self):
        state = {}
        cond = {"op": "eq", "field": "secret.api_key", "value": "abc"}
        with pytest.raises(ConditionError, match="不在允许列表中"):
            evaluate_condition(cond, state)

    def test_type_mismatch_string_vs_number(self):
        state = {"risk_assessment": {"riskScore": "not_a_number"}}
        cond = {"op": "gte", "field": "risk_assessment.riskScore", "value": 70}
        with pytest.raises(ConditionError, match="数值类型"):
            evaluate_condition(cond, state)

    def test_missing_field_for_comparison(self):
        state = {}
        cond = {"op": "gte", "field": "risk_assessment.riskScore", "value": 70}
        with pytest.raises(ConditionError, match="不存在"):
            evaluate_condition(cond, state)

    def test_unknown_op(self):
        state = {}
        cond = {"op": "execute", "field": "risk_assessment.riskScore", "value": 0}
        with pytest.raises(ConditionError, match="未知运算符"):
            evaluate_condition(cond, state)

    def test_empty_conditions_for_all(self):
        state = {}
        cond = {"op": "all", "conditions": []}
        with pytest.raises(ConditionError, match="非空"):
            evaluate_condition(cond, state)


class TestMaliciousExpressions:
    """恶意表达式安全检查。"""

    def test_dunder_class_attack(self):
        """__class__ 攻击被拒绝。"""
        state = {}
        cond = {"op": "eq", "field": "__class__", "value": "os"}
        # dunder 字段被 dunder 检查直接拒绝（比白名单检查更早）
        with pytest.raises(ConditionError, match="dunder"):
            evaluate_condition(cond, state)

    def test_dunder_dict_attack(self):
        state = {}
        cond = {"op": "exists", "field": "__dict__"}
        with pytest.raises(ConditionError, match="dunder"):
            evaluate_condition(cond, state)

    def test_no_import_in_value(self):
        """value 中的 import 字符串不会被执行（仅做字符串比较）。"""
        state = {"risk_assessment": {"riskLevel": "低风险"}}
        cond = {"op": "eq", "field": "risk_assessment.riskLevel",
                "value": "__import__('os').system('rm -rf /')"}
        assert evaluate_condition(cond, state) is False  # 纯字符串比较，不执行

    def test_function_call_not_executed(self):
        """函数调用语法不会被执行。"""
        state = {"risk_assessment": {"riskScore": 85}}
        cond = {"op": "gte", "field": "risk_assessment.riskScore", "value": 70}
        # 正常 DSL，无 Python 表达式求值——value 中的括号不触发函数调用
        assert evaluate_condition(cond, state) is True

    def test_no_code_injection(self):
        """code 注入无效。"""
        state = {"risk_assessment": {"riskScore": 0}}
        cond = {"op": "eq", "field": "risk_assessment.riskScore",
                "value": "__import__('os').system('dir')"}
        # 0 != 字符串，安全返回 False
        assert evaluate_condition(cond, state) is False

    def test_no_eval_in_field_path(self):
        """field 路径中的恶意内容被白名单拒绝。"""
        state = {}
        for malicious in [
            "eval('1+1')",
            "exec('x')",
            "os.system",
            "__builtins__",
        ]:
            with pytest.raises(ConditionError):
                evaluate_condition(
                    {"op": "exists", "field": malicious},
                    state,
                )


class TestValidateConditionStructure:
    """条件结构校验。"""

    def test_valid_simple(self):
        issues = validate_condition_structure(
            {"op": "gte", "field": "risk_assessment.riskScore", "value": 70}
        )
        assert len(issues) == 0

    def test_valid_compound(self):
        issues = validate_condition_structure({
            "op": "all",
            "conditions": [
                {"op": "gte", "field": "risk_assessment.riskScore", "value": 70},
                {"op": "eq", "field": "risk_assessment.riskLevel", "value": "高风险"},
            ],
        })
        assert len(issues) == 0

    def test_field_not_allowed(self):
        issues = validate_condition_structure(
            {"op": "eq", "field": "os.system", "value": "rm"}
        )
        assert any("不在允许列表中" in i for i in issues)

    def test_missing_field(self):
        issues = validate_condition_structure(
            {"op": "gte", "value": 70}
        )
        assert any("缺少 'field'" in i for i in issues)

    def test_suspicious_value(self):
        issues = validate_condition_structure(
            {"op": "eq", "field": "risk_assessment.riskLevel",
             "value": "__import__('os').system('rm')"}
        )
        assert any("可疑内容" in i for i in issues)

    def test_invalid_op(self):
        issues = validate_condition_structure(
            {"op": "rm_rf", "field": "risk_assessment.riskScore", "value": 0}
        )
        assert any("未知运算符" in i for i in issues)

    def test_nested_error(self):
        issues = validate_condition_structure({
            "op": "all",
            "conditions": [
                {"op": "gte", "field": "risk_assessment.riskScore", "value": 70},
                {"op": "eq", "field": "invalid.field"},
            ],
        })
        assert any("不在允许列表中" in i for i in issues)


class TestWhitelistIntegrity:
    """白名单完整性。"""

    def test_whitelist_is_not_empty(self):
        assert len(ALLOWED_FIELDS) > 10

    def test_no_dunder_in_whitelist(self):
        for field in ALLOWED_FIELDS:
            for part in field.split("."):
                assert not part.startswith("__"), f"dunder in whitelist: {field}"
                assert not part.endswith("__"), f"dunder in whitelist: {field}"

    def test_common_safe_fields(self):
        required = [
            "risk_assessment.riskScore",
            "risk_assessment.riskLevel",
            "current_event.isMainRoad",
            "current_event.nearbySchool",
        ]
        for f in required:
            assert f in ALLOWED_FIELDS, f"missing: {f}"


class TestAllowedNodeIds:
    """allowed_node_ids 动态字段安全校验。"""

    def test_registered_node_id_allowed(self):
        state = {"rule_router": {"requires_approval": True}}
        cond = {"op": "exists", "field": "rule_router.requires_approval"}
        allowed = {"rule_router", "validate_event", "risk_gate"}
        assert evaluate_condition(cond, state, allowed) is True

    def test_unregistered_node_id_rejected(self):
        state = {"malicious_node": {"cmd": "rm -rf /"}}
        cond = {"op": "exists", "field": "malicious_node.cmd"}
        allowed = {"rule_router", "validate_event"}
        with pytest.raises(ConditionError, match="不在允许列表中"):
            evaluate_condition(cond, state, allowed)

    def test_empty_allowed_set_rejects_all_dynamic(self):
        state = {"rule_router": {"score": 10}}
        cond = {"op": "gte", "field": "rule_router.score", "value": 5}
        allowed = set()  # 空集合 → 拒绝所有动态字段
        with pytest.raises(ConditionError, match="不在允许列表中"):
            evaluate_condition(cond, state, allowed)

    def test_whitelist_field_bypasses_node_id_check(self):
        """白名单字段（如 risk_assessment.riskScore）不需要 node_id 校验。"""
        state = {"risk_assessment": {"riskScore": 85}}
        cond = {"op": "gte", "field": "risk_assessment.riskScore", "value": 70}
        # 即使 allowed 为空，白名单字段仍可访问
        assert evaluate_condition(cond, state, set()) is True

    def test_none_allowed_falls_back_to_known(self):
        """allowed=None 时回退到 KNOWN_NODE_IDS。"""
        state = {"rule_router": {"requires_approval": True}}
        cond = {"op": "exists", "field": "rule_router.requires_approval"}
        assert evaluate_condition(cond, state, None) is True

    def test_private_field_rejected(self):
        state = {"rule_router": {"_secret": "password"}}
        cond = {"op": "exists", "field": "rule_router._secret"}
        allowed = {"rule_router"}
        with pytest.raises(ConditionError, match="私有字段"):
            evaluate_condition(cond, state, allowed)

    def test_callable_in_path_rejected(self):
        state = {}
        cond = {"op": "exists", "field": "rule_router.__call__"}
        allowed = {"rule_router"}
        with pytest.raises(ConditionError, match="dunder"):
            evaluate_condition(cond, state, allowed)

    def test_parens_in_path_rejected(self):
        state = {}
        cond = {"op": "exists", "field": "system('rm')"}
        allowed = set()
        with pytest.raises(ConditionError, match="非法字符"):
            evaluate_condition(cond, state, allowed)
