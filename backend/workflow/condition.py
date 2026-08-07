"""
Workflow 安全条件引擎 — Phase 12

替换 eval() 为结构化 DSL，禁止任意 Python 表达式执行。

支持的运算符:
  eq, ne, gt, gte, lt, lte, in, not_in, contains, exists
  all, any (逻辑组合)

限制:
  - field 只能读取 TrafficWorkflowState 白名单字段
  - 禁止 dunder 字段 (__class__, __dict__, ...)
  - 禁止函数调用
  - 类型不匹配返回明确错误
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ── 已知节点 ID（其输出可以作为 state dict 的 top-level key）──
KNOWN_NODE_IDS = {
    "trigger", "validate_event", "rule_router", "rag_retrieve",
    "memory_context", "agent_task", "agent_congestion", "agent_signal",
    "agent_safety", "agent_accident",
    "parallel", "join", "evidence_evaluate", "risk_gate",
    "human_approval", "action", "action_notify", "wait", "monitor", "close",
}

# ── 允许读取的字段路径白名单 ─────────────────────────────────────────────
ALLOWED_FIELDS = {
    # risk_assessment
    "risk_assessment.riskScore",
    "risk_assessment.riskLevel",
    "risk_assessment.riskReasons",
    # current_event
    "current_event.eventType",
    "current_event.eventTypeCn",
    "current_event.roadName",
    "current_event.direction",
    "current_event.avgSpeed",
    "current_event.queueLength",
    "current_event.duration",
    "current_event.weather",
    "current_event.timePeriod",
    "current_event.isMainRoad",
    "current_event.nearbySchool",
    "current_event.nearbyHospital",
    "current_event.confidence",
    "current_event.vehicleCount",
    # rule_router results
    "rule_router.route",
    "rule_router.priority",
    "rule_router.requires_approval",
    # evidence_evaluate
    "evidence_evaluate.quality",
    "evidence_evaluate.avg_confidence",
    "evidence_evaluate.requires_human_review",
    # workflow control
    "status",
    "current_node",
}

SIMPLE_OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "contains", "exists"}
COMPOUND_OPS = {"all", "any"}
VALID_OPS = SIMPLE_OPS | COMPOUND_OPS


# ── 字段路径解析 ────────────────────────────────────────────────────────

def _resolve_field(
    state: Dict[str, Any],
    field_path: str,
    allowed_node_ids: set = None,
) -> Any:
    """从 state dict 中安全解析字段路径。

    仅允许白名单字段，拒绝 dunder 字段。动态节点输出 key 需通过
    allowed_node_ids 校验（若提供）。
    """
    if not field_path:
        raise ConditionError(f"字段路径为空")

    # 拒绝 dunder / callable / special attrs
    for part in field_path.split("."):
        if part.startswith("__") or part.endswith("__"):
            raise ConditionError(f"禁止访问 dunder 字段: '{field_path}'")
        if part.startswith("_") and len(part) > 1 and part[1] != "_":
            raise ConditionError(f"禁止访问私有字段: '{field_path}'")
        if '(' in part or ')' in part:
            raise ConditionError(f"字段路径含非法字符: '{field_path}'")

    # 检查白名单（node 输出字段也允许，但需通过 allowed_node_ids 校验）
    if field_path not in ALLOWED_FIELDS:
        top_key = field_path.split(".")[0] if "." in field_path else field_path
        # 如果提供了 allowed_node_ids，必须匹配
        if allowed_node_ids is not None:
            if top_key not in allowed_node_ids:
                raise ConditionError(
                    f"字段 '{field_path}' 不在允许列表中。"
                    f"允许的 node 输出: {sorted(allowed_node_ids) if allowed_node_ids else 'none'}"
                )
        elif top_key not in KNOWN_NODE_IDS:
            raise ConditionError(
                f"字段 '{field_path}' 不在允许列表中。"
            )

    # 逐级解析
    parts = field_path.split(".")
    current = state
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                return _MISSING
            current = current[part]
        else:
            return _MISSING
    return current


class _Missing:
    """表示字段不存在的哨兵值。"""
    def __repr__(self):
        return "<MISSING>"


_MISSING = _Missing()


class ConditionError(Exception):
    """条件求值错误。"""
    pass


# ── 单条件求值 ──────────────────────────────────────────────────────────

def _eval_simple(op: str, field: str, value: Any, state: Dict[str, Any],
                 allowed_node_ids: set = None) -> bool:
    """求值单个简单条件。"""
    actual = _resolve_field(state, field, allowed_node_ids)

    if op == "exists":
        return actual is not _MISSING

    if actual is _MISSING:
        raise ConditionError(f"字段 '{field}' 不存在，无法执行 '{op}' 比较")

    if op == "eq":
        return actual == value
    elif op == "ne":
        return actual != value
    elif op in ("gt", "gte", "lt", "lte"):
        if not isinstance(actual, (int, float)) or not isinstance(value, (int, float)):
            raise ConditionError(
                f"'{op}' 要求数值类型，got actual={type(actual).__name__}, "
                f"value={type(value).__name__}"
            )
        if op == "gt":
            return actual > value
        elif op == "gte":
            return actual >= value
        elif op == "lt":
            return actual < value
        elif op == "lte":
            return actual <= value
    elif op == "in":
        if not isinstance(value, (list, tuple, str)):
            raise ConditionError(f"'in' 要求 value 为 list/str，got {type(value).__name__}")
        return actual in value
    elif op == "not_in":
        if not isinstance(value, (list, tuple, str)):
            raise ConditionError(f"'not_in' 要求 value 为 list/str，got {type(value).__name__}")
        return actual not in value
    elif op == "contains":
        if isinstance(actual, (list, tuple, str)):
            return value in actual
        raise ConditionError(f"'contains' 要求 field 为 list/str，got {type(actual).__name__}")

    raise ConditionError(f"未知运算符: '{op}'")


# ── 顶层求值入口 ────────────────────────────────────────────────────────

def evaluate_condition(
    condition: Dict[str, Any],
    state: Dict[str, Any],
    allowed_node_ids: set = None,
) -> bool:
    """求值条件 DSL。

    Args:
        condition: 条件 DSL dict
        state: TrafficWorkflowState.to_dict()
        allowed_node_ids: 允许的节点 ID 集合（动态字段安全校验）

    Returns:
        条件结果

    Raises:
        ConditionError: 条件非法时
    """
    if not isinstance(condition, dict):
        raise ConditionError(f"条件必须是 dict，got {type(condition).__name__}")

    op = condition.get("op", "")
    if op not in VALID_OPS:
        raise ConditionError(f"未知运算符 '{op}'。允许: {sorted(VALID_OPS)}")

    if op in SIMPLE_OPS:
        field = condition.get("field", "")
        if not field:
            raise ConditionError("简单条件必须指定 'field'")
        value = condition.get("value")
        return _eval_simple(op, field, value, state, allowed_node_ids)

    elif op in COMPOUND_OPS:
        sub_conditions = condition.get("conditions", [])
        if not isinstance(sub_conditions, list) or not sub_conditions:
            raise ConditionError(f"'{op}' 必须包含非空 'conditions' 列表")

        results = []
        for i, sub in enumerate(sub_conditions):
            try:
                results.append(evaluate_condition(sub, state, allowed_node_ids))
            except ConditionError as e:
                raise ConditionError(f"'{op}' 的第 {i} 个子条件失败: {e}")

        if op == "all":
            return all(results)
        else:  # "any"
            return any(results)

    return False


def validate_condition_structure(condition: Dict[str, Any]) -> List[str]:
    """校验条件 DSL 结构合法性（Definition 加载时调用）。

    返回问题列表，空列表表示合法。
    """
    issues: List[str] = []

    if not isinstance(condition, dict):
        return ["条件必须是 dict"]

    op = condition.get("op", "")
    if op not in VALID_OPS:
        return [f"未知运算符 '{op}'。允许: {sorted(VALID_OPS)}"]

    if op in SIMPLE_OPS:
        field = condition.get("field", "")
        if not field:
            issues.append(f"'{op}' 条件缺少 'field'")
        elif field not in ALLOWED_FIELDS:
            top_key = field.split(".")[0] if "." in field else field
            if top_key not in KNOWN_NODE_IDS:
                issues.append(
                    f"字段 '{field}' 不在允许列表中。"
                )

        # 检查禁止的 value（如函数调用字符串）
        value = condition.get("value")
        if isinstance(value, str):
            if "(" in value or "__" in value or "import" in value.lower():
                issues.append(f"value 包含可疑内容: '{value[:50]}'")

    elif op in COMPOUND_OPS:
        sub = condition.get("conditions")
        if not isinstance(sub, list) or not sub:
            issues.append(f"'{op}' 必须包含非空 'conditions' 列表")
        else:
            for i, s in enumerate(sub):
                sub_issues = validate_condition_structure(s)
                for si in sub_issues:
                    issues.append(f"conditions[{i}]: {si}")

    return issues


def condition_from_expr(expr: str) -> Dict[str, Any]:
    """将旧版简单条件表达式迁移为 DSL 格式。

    支持的旧格式:
      "requires_approval"                    → {"op": "exists", "field": "rule_router.requires_approval"}
      "risk_score >= 70"                     → 未实现（手工迁移）
      "risk_level == '高风险'"               → 未实现（手工迁移）

    此转换器仅支持最简单的命名条件。
    复杂表达式需直接编写 DSL。
    """
    expr = expr.strip()
    # 简单命名条件
    name_map = {
        "requires_approval": {"op": "exists", "field": "rule_router.requires_approval"},
        "evidence_sufficient": {"op": "eq", "field": "evidence_evaluate.quality", "value": "sufficient"},
        "high_risk": {"op": "gte", "field": "risk_assessment.riskScore", "value": 61},
    }
    if expr in name_map:
        return name_map[expr]

    # 默认：把表达式作为 "all" DSL 的短路求值
    # 不解析 Python 表达式，返回 requires_approval 检查
    raise ConditionError(
        f"无法将表达式 '{expr}' 自动转换为 DSL。"
        f"请直接提供 DSL 格式条件。"
        f"支持的命名条件: {list(name_map.keys())}"
    )
