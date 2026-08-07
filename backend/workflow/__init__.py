"""
TrafficMind Workflow V1 — Phase 12

受控、版本化、可审计的交通事件 Workflow 引擎。

核心设计：
  - Workflow 控制节点顺序、条件分支、并行与汇合、人工审批、暂停与恢复
  - Agent 只负责节点内复杂研判
  - RAG / Memory / Tool 负责检索、上下文和实际能力调用
"""

__version__ = "1.0.0"
