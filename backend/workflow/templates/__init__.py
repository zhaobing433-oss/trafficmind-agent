"""
Workflow V1 内置模板 — Phase 12 + Phase 13

提供的预置 Workflow：
  1. ramp_congestion: 高速匝道拥堵分流与闭环（完整实现）
  2. school_hospital_congestion: 学校/医院周边拥堵协同（基础 Definition）
  3. accident_122_120: 道路交通事故122/120联动（基础 Definition）
  4. simulation_bridge: Phase 13 仿真事件研判桥接
"""

from backend.workflow.templates.ramp_congestion import build_ramp_congestion_definition
from backend.workflow.templates.school_hospital_congestion import build_school_hospital_congestion_definition
from backend.workflow.templates.accident_122_120 import build_accident_122_120_definition
from backend.workflow.templates.simulation_bridge import build_simulation_bridge_definition


def get_all_templates() -> list:
    """获取所有内置模板的构建函数。"""
    return [
        build_ramp_congestion_definition,
        build_school_hospital_congestion_definition,
        build_accident_122_120_definition,
        build_simulation_bridge_definition,
    ]
