"""相似度权重配置 — 可解释启发式权重，后续基于专家标注校准"""

DEFAULT_WEIGHTS = {"rule": 0.6, "vector": 0.4}

INTENT_WEIGHTS = {
    "signal_abnormal": {"rule": 0.7, "vector": 0.3},
    "congestion": {"rule": 0.55, "vector": 0.45},
    "accident": {"rule": 0.7, "vector": 0.3},
    "illegal_parking": {"rule": 0.7, "vector": 0.3},
    "unclosed_risk": {"rule": 0.5, "vector": 0.5},
    "high_risk_road": {"rule": 0.5, "vector": 0.5},
    "report": {"rule": 0.4, "vector": 0.6},
    "similar_case": {"rule": 0.4, "vector": 0.6},
    "general_qa": {"rule": 0.4, "vector": 0.6},
}

WEIGHT_REASONS = {
    "signal_abnormal": "信号异常类事件字段特征明确，规则匹配更可靠",
    "congestion": "拥堵需兼顾字段相似和语义相似，规则略高",
    "accident": "事故事件字段特征强烈，规则权重更高",
    "default": "默认启发式权重，基于规则稳定性与向量泛化能力的平衡",
}


def get_weights(intent: str) -> dict:
    return INTENT_WEIGHTS.get(intent, DEFAULT_WEIGHTS)


def get_weight_reason(intent: str) -> str:
    return WEIGHT_REASONS.get(intent, WEIGHT_REASONS["default"])
