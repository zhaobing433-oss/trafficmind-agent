"""
RAG V2 Query Analyzer — 确定性优先的查询分析。

返回 needsRetrieval, complexity, route, explicitEntities, filters, requiredFacets, subqueries, reason.
路由: no_retrieval | exact_rule | operational_guidance | similar_case | cross_document | multi_hop

LLM decomposition 仅用于复杂问题（multi_hop），不可用时使用确定性交通领域分解。
简单问题禁止调用LLM。
"""
from __future__ import annotations
import re
from typing import Dict, List, Optional, Set

from backend.rag.v2.models import QueryAnalysis, RetrievalRoute
from backend.config import LLM_ENABLED


# ─── Entity detection ──────────────────────────────────────────────────────

ENTITY_PATTERNS = {
    "event_type": [
        ("拥堵", "拥堵"), ("事故", "事故"), ("违停", "违停"),
        ("逆行", "逆行"), ("行人闯入", "行人闯入"), ("信号灯异常", "信号灯异常"),
        ("车辆滞留", "车辆滞留"), ("施工占道", "施工占道"),
    ],
    "risk_level": [
        ("低风险", "低风险"), ("中风险", "中风险"), ("高风险", "高风险"), ("重大风险", "重大风险"),
    ],
    "location": [
        ("学校", "学校"), ("医院", "医院"), ("路口", "路口"),
        ("主干道", "主干道"), ("快速路", "快速路"), ("高速", "高速"),
        ("匝道", "匝道"), ("隧道", "隧道"), ("桥梁", "桥梁"),
    ],
    "time": [
        ("早高峰", "早高峰"), ("晚高峰", "晚高峰"), ("平峰", "平峰"),
        ("雨天", "雨天"), ("雪天", "雪天"), ("雾天", "雾天"),
    ],
    "signal": [
        ("信号灯", "信号灯"), ("信号配时", "信号配时"), ("绿信比", "绿信比"),
        ("相位", "相位"), ("周期", "周期"),
    ],
    "units": [
        ("122", "122"), ("120", "120"), ("119", "119"), ("110", "110"),
        ("交警", "交警"), ("急救", "急救"), ("消防", "消防"),
    ],
    "actions": [
        ("分流", "分流"), ("绕行", "绕行"), ("管制", "管制"),
        ("疏导", "疏导"), ("封闭", "封闭"), ("限流", "限流"),
    ],
}

# ─── Route classification patterns ─────────────────────────────────────────

EXACT_RULE_PATTERNS = [
    r"\d{3,4}",                    # "122", "120" etc.
    r"信号配时", r"绿信比", r"相位",
    r"应急预案", r"响应级别", r"联动机制",
]

SIMILAR_CASE_PATTERNS = [
    r"历史", r"过去", r"以往", r"类似", r"相似",
    r"上次", r"上个月", r"之前.*怎么", r"以前.*怎么",
    r"有没有.*案例", r"参考.*案例",
]

MULTI_HOP_PATTERNS = [
    r"同时.*如何", r"并且.*如何", r"兼顾.*和",
    r"既.*又.*怎么", r"还要.*考虑",
]

NO_RETRIEVAL_PATTERNS = [
    r"^你好", r"^您好", r"^谢谢", r"^再见",
    r"现在几点", r"今天.*日期", r"你是谁",
]


class RagQueryAnalyzer:
    """确定性优先的查询分析器。"""

    def analyze(self, query: str, event_info: Optional[Dict] = None) -> QueryAnalysis:
        """分析查询，返回 QueryAnalysis。"""
        query = query.strip()
        if not query:
            return QueryAnalysis(
                needs_retrieval=False,
                complexity="simple",
                route=RetrievalRoute.NO_RETRIEVAL,
                reason="empty query",
            )

        # Check no_retrieval
        for pat in NO_RETRIEVAL_PATTERNS:
            if re.search(pat, query):
                return QueryAnalysis(
                    needs_retrieval=False,
                    complexity="simple",
                    route=RetrievalRoute.NO_RETRIEVAL,
                    reason="greeting or non-traffic query",
                )

        # Extract entities
        explicit_entities = self._extract_entities(query)
        filters = self._build_filters(query, event_info)
        required_facets = self._determine_facets(query, explicit_entities)
        route = self._classify_route(query)
        complexity = self._assess_complexity(query, route)

        # Multi-hop: decompose
        subqueries: List[str] = []
        if route == RetrievalRoute.MULTI_HOP:
            subqueries = self._decompose(query)
        elif complexity == "complex":
            subqueries = self._decompose(query)

        return QueryAnalysis(
            needs_retrieval=route != RetrievalRoute.NO_RETRIEVAL,
            complexity=complexity,
            route=route,
            explicit_entities=explicit_entities,
            filters=filters,
            required_facets=required_facets,
            subqueries=subqueries,
            reason=f"route={route} complexity={complexity} entities={explicit_entities}",
        )

    def _extract_entities(self, query: str) -> List[str]:
        """从查询中提取显式实体。"""
        entities: Set[str] = set()
        for category, patterns in ENTITY_PATTERNS.items():
            for pat, label in patterns:
                if pat in query:
                    entities.add(f"{category}:{label}")
        return sorted(entities)

    def _build_filters(self, query: str, event_info: Optional[Dict]) -> Dict:
        """构建 Chroma/Python 过滤条件。"""
        filters = {}
        if event_info:
            evt_type = event_info.get("eventTypeCn", event_info.get("eventType", ""))
            if evt_type:
                filters["event_type"] = evt_type
            road = event_info.get("roadName", "")
            if road:
                filters["road_name"] = road

        # Detect explicit filter intent
        for pat, label in ENTITY_PATTERNS["event_type"]:
            if pat in query:
                filters["event_type"] = label
                break
        return filters

    def _determine_facets(self, query: str, entities: List[str]) -> List[str]:
        """确定需要的证据 facet。"""
        facets = []
        entity_categories = {e.split(":")[0] for e in entities}

        if "event_type" in entity_categories:
            facets.append("applicable_rules")
        if any(k in query for k in ["如何处置", "怎么办", "怎么做", "预案", "措施", "建议"]):
            facets.append("dispatch_actions")
        if any(k in query for k in ["类似", "历史", "案例", "过去"]):
            facets.append("similar_cases")
        if any(k in query for k in ["信号", "配时", "周期", "相位"]):
            facets.append("signal_config")
        if any(k in query for k in ["统计", "报告", "趋势"]):
            facets.append("statistics")
        if any(k in query for k in ["法规", "规定", "标准"]):
            facets.append("regulations")
        if any(k in query for k in ["部门", "联动", "谁负责"]):
            facets.append("responsible_units")

        if not facets:
            facets.append("general_guidance")
        return facets

    def _classify_route(self, query: str) -> RetrievalRoute:
        """分类路由。"""
        # Check exact_rule first
        for pat in EXACT_RULE_PATTERNS:
            if re.search(pat, query):
                return RetrievalRoute.EXACT_RULE

        # Similar case
        for pat in SIMILAR_CASE_PATTERNS:
            if re.search(pat, query):
                return RetrievalRoute.SIMILAR_CASE

        # Multi-hop
        for pat in MULTI_HOP_PATTERNS:
            if re.search(pat, query):
                return RetrievalRoute.MULTI_HOP

        # Operational guidance
        if any(k in query for k in ["处置", "怎么办", "建议", "预案", "疏导"]):
            return RetrievalRoute.OPERATIONAL_GUIDANCE

        # Cross-document
        if any(k in query for k in ["规则", "标准", "法规", "规定", "联动", "综合"]):
            return RetrievalRoute.CROSS_DOCUMENT

        return RetrievalRoute.CROSS_DOCUMENT

    def _assess_complexity(self, query: str, route: RetrievalRoute) -> str:
        """评估复杂度。"""
        if route == RetrievalRoute.MULTI_HOP:
            return "complex"
        if route == RetrievalRoute.CROSS_DOCUMENT:
            return "moderate"
        if len(query) > 60:
            return "moderate"
        return "simple"

    def _decompose(self, query: str) -> List[str]:
        """确定性分解复杂查询。最多3个子查询。"""
        # Try LLM decomposition only for truly complex queries
        if LLM_ENABLED and len(query) > 40 and self._has_conjunction(query):
            llm_subs = self._llm_decompose(query)
            if llm_subs:
                return llm_subs[:3]

        # Deterministic decomposition
        return self._deterministic_decompose(query)

    def _has_conjunction(self, query: str) -> bool:
        """检测是否包含连接词（多问题）。"""
        conjunctions = ["同时", "并且", "还有", "以及", "兼顾", "另外", "此外"]
        return any(c in query for c in conjunctions)

    def _deterministic_decompose(self, query: str) -> List[str]:
        """确定性交通领域分解。"""
        subs = []

        # Split by conjunctions
        parts = re.split(r'[，；,;。同时|并且|兼顾|还要]', query)
        parts = [p.strip() for p in parts if len(p.strip()) > 5]

        if len(parts) >= 2:
            for i, part in enumerate(parts[:3]):
                subs.append(part)
        elif len(parts) == 1:
            subs.append(parts[0])

        # Limit to 3
        return subs[:3]

    def _llm_decompose(self, query: str) -> List[str]:
        """LLM 辅助分解（可选）。"""
        try:
            from backend.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
            from openai import OpenAI
            client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{
                    "role": "system",
                    "content": "将复杂交通问题分解为2-3个独立子问题。每行一个，不要编号，不要解释。"
                }, {
                    "role": "user",
                    "content": query,
                }],
                temperature=0.1, max_tokens=200, timeout=15,
            )
            lines = [l.strip() for l in resp.choices[0].message.content.strip().split("\n") if l.strip()]
            return lines[:3]
        except Exception:
            return []
