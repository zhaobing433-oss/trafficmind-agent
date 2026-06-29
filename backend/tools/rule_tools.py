"""
规则检索工具模块
--------------
从本地 Markdown 规则库中按事件类型检索对应处置预案。
第一阶段不使用向量数据库，直接解析 Markdown 结构。
"""

import re
from typing import Dict, Any, Optional
from backend.config import RULES_PATH


def load_rules(filepath: str = None) -> Dict[str, Dict[str, str]]:
    """
    加载并解析 Markdown 规则文件。

    规则文件中每类事件以 `## <事件名称>` 开头，
    后续为键值对格式的规则内容。

    Args:
        filepath: 规则文件路径，默认使用 config.RULES_PATH

    Returns:
        {
            "拥堵": {
                "判断条件": "...",
                "处置建议": "...",
                "联动部门": "...",
                "后续跟踪": "..."
            },
            ...
        }
    """
    path = filepath or RULES_PATH
    rules: Dict[str, Dict[str, str]] = {}
    current_event: Optional[str] = None
    current_section: Optional[str] = None
    current_lines: list = []

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return rules

    def commit_section():
        """将当前收集的行写入 rules 字典。"""
        nonlocal current_event, current_section, current_lines
        if current_event and current_section:
            rules.setdefault(current_event, {})[current_section] = "".join(current_lines).strip()
        current_section = None
        current_lines = []

    for line in lines:
        # ## 开头 -> 新的事件类型
        if line.startswith("## ") and not line.startswith("### "):
            commit_section()
            current_event = line.strip("# ").strip()
            rules.setdefault(current_event, {})

        # ### 开头 -> 新的小节（判断条件 / 处置建议 …）
        elif line.startswith("### "):
            commit_section()
            current_section = line.strip("# ").strip()

        # 内容行
        elif current_section:
            current_lines.append(line)

    # 文件末尾最后一个小节
    commit_section()

    return rules


def retrieve_rule(event_type: str) -> Dict[str, Any]:
    """
    按事件类型检索处置预案。

    Args:
        event_type: 事件类型（中文名称，如 "拥堵"）

    Returns:
        {
            "rule": str,            # 完整规则文本
            "ruleSections": dict,   # 分节规则
            "matched": bool,        # 是否匹配到
        }
    """
    rules = load_rules()
    rule_sections = rules.get(event_type, {})

    if not rule_sections:
        return {
            "rule": f"未找到「{event_type}」的处置预案，请按通用突发事件流程处置。",
            "ruleSections": {},
            "matched": False,
        }

    # 组装完整规则文本
    parts = [f"**{event_type}事件处置预案**\n"]
    for section, content in rule_sections.items():
        parts.append(f"### {section}\n{content}")

    return {
        "rule": "\n".join(parts),
        "ruleSections": rule_sections,
        "matched": True,
    }
