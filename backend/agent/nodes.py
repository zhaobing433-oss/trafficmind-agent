"""
Agent 工作流节点
---------------
每个节点负责一个步骤，接收 state dict，返回更新后的 state dict。
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

# 导入各个工具模块
from backend.tools.event_tools import validate_event, standardize_event
from backend.tools.risk_tools import calculate_risk_score
from backend.tools.rule_tools import retrieve_rule
from backend.tools.dispatch_tools import generate_dispatch_message, generate_public_message
from backend.tools.report_tools import generate_event_report
from backend.tools.db_tools import save_event_analysis

# 导入 LLM 相关
from backend.config import LLM_ENABLED, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from backend.agent.prompts import SUGGESTIONS_PROMPT, REPORT_POLISH_PROMPT


# ==================== 确定性工具函数生成的建议模板 ====================

def _generate_local_suggestions(event: Dict[str, Any], matched_rule: Dict[str, Any]) -> List[str]:
    """
    基于规则模板生成处置建议（无 LLM 时的降级方案）。
    """
    event_type_cn = event.get("eventTypeCn", "")
    road = event.get("roadName", "")
    direction = event.get("direction", "")
    dir_text = f"{direction}方向" if direction else ""

    rule_sections = matched_rule.get("ruleSections", {})
    actions = rule_sections.get("处置建议", "")
    department = rule_sections.get("联动部门", "指挥中心")

    suggestions = [
        f"通知{department}，{road}{dir_text}发生{event_type_cn}事件，请立即派员前往现场处置。",
    ]

    if actions:
        suggestions.append(actions.strip())

    if event.get("queueLength", 0) > 100:
        suggestions.append(f"建议在{road}上游路口实施分流，引导车辆绕行，缓解排队压力。")

    if event.get("avgSpeed", 30) < 15:
        suggestions.append(f"建议通过交通广播、诱导屏发布实时路况信息，告知驾驶员提前绕行。")

    suggestions.append("做好事件处置记录，拍照留存，处置完成后及时反馈指挥中心。")

    return suggestions


# ==================== LLM 调用封装 ====================

def _call_llm(prompt: str, system_role: str = "你是智慧交通系统的AI助手。") -> Optional[str]:
    """
    调用 DeepSeek API（OpenAI-compatible 方式）。

    Args:
        prompt: 用户提示词
        system_role: 系统角色描述

    Returns:
        LLM 返回文本；失败或未配置时返回 None
    """
    if not LLM_ENABLED:
        return None

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )

        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system_role},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=2048,
            timeout=30,
        )

        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[LLM] 调用失败: {e}")
        return None


# ==================== 工作流节点 ====================

def parse_event_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    节点1：事件解析
    - 校验必填字段
    - 标准化事件对象
    """
    raw_event = state.get("raw_event", {})

    is_valid, error_msg = validate_event(raw_event)
    if not is_valid:
        return {**state, "error": error_msg, "step": "parse_event"}

    standard_event = standardize_event(raw_event)
    return {
        **state,
        "standard_event": standard_event,
        "step": "parse_event",
        "error": None,
    }


def calculate_risk_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    节点2：风险评分
    - 使用确定性规则计算风险分数和等级
    """
    standard_event = state.get("standard_event", {})
    if not standard_event:
        return {**state, "error": "无标准化事件数据", "step": "calculate_risk"}

    risk_result = calculate_risk_score(standard_event)
    return {
        **state,
        "risk_result": risk_result,
        "step": "calculate_risk",
    }


def retrieve_rule_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    节点3：规则检索
    - 按事件类型从本地规则库匹配预案
    """
    standard_event = state.get("standard_event", {})
    event_type_cn = standard_event.get("eventTypeCn", "")

    matched_rule = retrieve_rule(event_type_cn)
    return {
        **state,
        "matched_rule": matched_rule,
        "step": "retrieve_rule",
    }


def generate_suggestions_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    节点4：生成处置建议
    - 优先使用 LLM 生成; 未配置 LLM 时降级为模板
    """
    standard_event = state.get("standard_event", {})
    risk_result = state.get("risk_result", {})
    matched_rule = state.get("matched_rule", {})

    if LLM_ENABLED:
        prompt = SUGGESTIONS_PROMPT.format(
            event_type=standard_event.get("eventTypeCn", ""),
            road=standard_event.get("roadName", ""),
            direction=standard_event.get("direction", ""),
            speed=standard_event.get("avgSpeed", 0),
            queue=standard_event.get("queueLength", 0),
            duration=int(float(standard_event.get("duration", 0)) / 60),
            weather=standard_event.get("weather", ""),
            period=standard_event.get("timePeriod", ""),
            risk_level=risk_result.get("riskLevel", ""),
            risk_score=risk_result.get("riskScore", 0),
            rule=matched_rule.get("rule", ""),
        )

        llm_output = _call_llm(prompt, "你是智慧交通系统的AI调度员，负责生成交通事件处置建议。")
        if llm_output:
            # 解析 LLM 返回的 "- xxx" 格式列表
            suggestions = [
                line.strip("- ").strip()
                for line in llm_output.split("\n")
                if line.strip().startswith("-")
            ]
            if suggestions:
                return {**state, "suggestions": suggestions, "step": "generate_suggestions"}

    # 降级：使用本地模板
    suggestions = _generate_local_suggestions(standard_event, matched_rule)
    return {**state, "suggestions": suggestions, "step": "generate_suggestions"}


def generate_dispatch_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    节点5：生成调度话术
    - 调度指令（面向指挥中心/交警）
    - 公众提示（面向诱导屏）
    """
    standard_event = state.get("standard_event", {})
    risk_result = state.get("risk_result", {})
    matched_rule = state.get("matched_rule", {})

    dispatch_message = generate_dispatch_message(standard_event, risk_result, matched_rule)
    public_message = generate_public_message(standard_event, risk_result)

    return {
        **state,
        "dispatch_message": dispatch_message,
        "public_message": public_message,
        "step": "generate_dispatch",
    }


def generate_report_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    节点6：生成事件报告
    - 先生成结构化报告，再用 LLM 润色（如可用）
    """
    standard_event = state.get("standard_event", {})
    risk_result = state.get("risk_result", {})
    matched_rule = state.get("matched_rule", {})
    suggestions = state.get("suggestions", [])
    dispatch_message = state.get("dispatch_message", "")

    # 生成基础报告
    raw_report = generate_event_report(
        standard_event, risk_result, matched_rule, suggestions, dispatch_message
    )

    # 尝试 LLM 润色
    if LLM_ENABLED:
        polished = _call_llm(
            REPORT_POLISH_PROMPT.format(raw_report=raw_report),
            "你是智慧交通系统的报告分析员。",
        )
        if polished:
            return {**state, "report": polished, "step": "generate_report"}

    # 降级：使用原始报告
    return {**state, "report": raw_report, "step": "generate_report"}


def save_result_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    节点7：保存结果到 SQLite
    """
    event_id = state.get("standard_event", {}).get("eventId", "")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    result = {
        "eventId": event_id,
        "standardEvent": state.get("standard_event", {}),
        "riskScore": state.get("risk_result", {}).get("riskScore", 0),
        "riskLevel": state.get("risk_result", {}).get("riskLevel", ""),
        "riskReasons": state.get("risk_result", {}).get("riskReasons", []),
        "matchedRule": state.get("matched_rule", {}).get("rule", ""),
        "suggestions": state.get("suggestions", []),
        "dispatchMessage": state.get("dispatch_message", ""),
        "publicMessage": state.get("public_message", ""),
        "report": state.get("report", ""),
        "status": "待派单",
        "saved": False,
        "analyzedAt": now,
    }

    # 写入数据库
    saved = save_event_analysis(result)
    result["saved"] = saved

    return {
        **state,
        "result": result,
        "step": "save_result",
    }


def send_notification_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    节点8：高风险事件消息推送（非阻塞）。
    仅当配置了通知渠道且风险等级 >= HIGH_RISK_THRESHOLD 时才推送。
    使用 daemon 线程发送，不阻塞 API 响应。
    """
    from backend.config import NOTIFY_ENABLED, HIGH_RISK_THRESHOLD

    result = state.get("result", {})
    risk_level = result.get("riskLevel", "")
    risk_score = result.get("riskScore", 0)

    # 风险等级 → 最低分数映射
    level_scores = {"低风险": 30, "中风险": 60, "高风险": 80, "重大风险": 100}
    threshold_score = level_scores.get(HIGH_RISK_THRESHOLD, 80)

    if NOTIFY_ENABLED and result and risk_score >= threshold_score:
        import threading
        from backend.tools.notify_tools import notify_high_risk_event

        thread = threading.Thread(
            target=notify_high_risk_event,
            args=(result,),
            daemon=True,
        )
        thread.start()
        print(f"[Agent] 高风险事件 {result.get('eventId', '')} 已触发消息推送（{risk_level}）")

    return {**state, "step": "send_notification"}

