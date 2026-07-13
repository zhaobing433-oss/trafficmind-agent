"""交通指挥意图识别器"""
from typing import Dict, List

INTENT_RULES = [
    ("signal_abnormal", ["信号灯", "信号异常", "信号故障", "红绿灯", "灯控"]),
    ("congestion", ["拥堵", "堵车", "排队", "缓行", "堵了", "通行缓慢"]),
    ("accident", ["事故", "碰撞", "追尾", "剐蹭", "撞车", "车祸"]),
    ("illegal_parking", ["违停", "乱停", "占道停车"]),
    ("unclosed_risk", ["未闭环", "没处理完", "还没处理", "没归档"]),
    ("high_risk_road", ["高风险路口", "重点路口", "哪个路口", "多发路段"]),
    ("report", ["日报", "周报", "报告", "统计"]),
    ("similar_case", ["相似", "类似", "以往", "过去", "历史案例"]),
]

INTENT_DOC_PRIORITY: Dict[str, List[str]] = {
    "signal_abnormal": ["rule", "dispatch_experience", "event_report"],
    "congestion": ["rule", "dispatch_experience", "event_report"],
    "accident": ["dispatch_experience", "rule", "event_report"],
    "illegal_parking": ["rule", "dispatch_experience"],
    "unclosed_risk": ["event_report", "dispatch_experience"],
    "high_risk_road": ["event_report", "weekly_report", "daily_report"],
    "report": ["daily_report", "weekly_report", "event_report"],
    "similar_case": ["event_report", "dispatch_experience"],
    "general_qa": ["dispatch_experience", "rule", "event_report"],
}


def classify_traffic_intent(question: str) -> str:
    """基于关键词规则识别交通问题意图。"""
    q = question.lower()
    for intent, keywords in INTENT_RULES:
        for kw in keywords:
            if kw in q:
                return intent
    return "general_qa"


def get_doc_priority(intent: str) -> List[str]:
    """获取特定意图的 docType 优先级列表。"""
    return INTENT_DOC_PRIORITY.get(intent, INTENT_DOC_PRIORITY["general_qa"])


def score_by_intent(intent: str, doc_type: str) -> float:
    """根据意图和 docType 计算加权分（0~0.15）。"""
    priority = get_doc_priority(intent)
    if doc_type in priority:
        idx = priority.index(doc_type)
        return max(0.15 - idx * 0.04, 0.01)
    return 0.0
