# Phase 9 — 多 Agent 协作通信、动态冲突仲裁与多轮会话恢复

> **状态**: 已完成  
> **测试**: 251 passed / TypeScript 0 errors  
> **日期**: 2026-07-22  
> **分支**: `feature/stage-9-multi-agent-collaboration`

---

## 1. 背景与目标

前序阶段已实现多 Agent 独立分析，但存在结构性缺陷：无标准通信协议、无显式 DAG 编排、冲突检测后无仲裁层、无持久化审计、无上下文裁剪、前端无多 Run 隔离。

Phase 9 实现：

| 能力 | 说明 |
|------|------|
| Pydantic 标准消息协议 | 14 种消息类型，AgentMessage/AgentResult/ToolRequest 等 |
| 5 层 DAG 任务图 | 拓扑排序 + 循环检测 + 动态节点插入 |
| ConflictArbiter 动态仲裁 | high/critical 冲突时自动创建仲裁层 |
| currentEvent / previousRunContext | 严格分离，永不合并 |
| contextPolicy / fieldSources | fresh_event/continue_event/follow_up + 字段来源追踪 |
| 11 状态协作运行状态机 | created→routing→running→arbitrating→fusing→completed |
| 上下文裁剪 | 每个 Agent 只接收角色允许的字段子集 |
| SQLite 5 表持久化 | runs/tasks/messages/conflicts/events 完整审计 |
| SSE 真流式 | 20+ 种事件类型实时推送 |
| 一 Session 多 Run | 同一会话多次协同分析独立隔离 |
| 历史完整恢复 | DAG/Agent/Conflict/Arbiter/Budget/FusionDecision |
| Sidebar mode 标签 | 协同/知识库/诊断/研判/相似/报告 |
| React ErrorBoundary | 渲染异常降级 UI，不黑屏 |
| 多轮字段污染修复 | 动态测量值不静默继承 |

---

## 2. 角色边界与标准协议

### 2.1 注册 Agent

| Agent | 角色 | 禁止 |
|-------|------|------|
| CongestionAgent | 拥堵分析（avgSpeed/queueLength/扩散） | 不得给出信号配时秒数 |
| SignalAgent | 信号控制（绿信比/周期/协调） | 不得直接控制信号灯 |
| PublicSafetyAgent | 公共安全（学校/医院/行人） | 不得代替 DispatchAgent |
| DispatchAgent | 调度处置（读取领域结果） | 不得在领域 Agent 前自行分析 |
| ConflictDetector | 冲突检测（比较 proposals） | 不得修改 Agent 结论 |
| ConflictArbiter | 冲突仲裁（规则引擎） | 不得重新分析业务 |
| FusionAgent | 融合总结 | 不得跳过仲裁层 |

每个 Agent 注册了 `allowed_input_fields`、`required_input_fields`、`max_calls`、`max_retries`、`timeout_seconds`、`dependencies`。

### 2.2 AgentMessage

```python
class AgentMessage(BaseModel):
    protocol_version: str = "1.0"
    message_id: str
    run_id: str
    session_id: str
    sender: str
    receiver: str
    message_type: str  # 14 种标准类型
    priority: int = 5
    attempt: int = 1
    payload: Dict[str, Any]
    context_refs: List[str]
    evidence_refs: List[str]
    created_at: str
```

---

## 3. currentEvent / previousRunContext

### 3.1 严格分离

```
currentEvent = build_current_event(parsedCurrentMessage)    # 仅当前消息
previousRunContext = load_previous_run_context(session_id)   # 独立加载
```

**禁止**: `currentEvent = {**previousEvent, **parsedCurrentMessage}`

### 3.2 数据结构

```json
{
  "currentEvent": {
    "avgSpeed": null,
    "queueLength": null,
    "nearbySchool": true,
    "fieldSources": { "avgSpeed": "missing", "nearbySchool": "current_message" }
  },
  "previousRunContext": {
    "runId": "run_1710000000",
    "summary": "上一轮为人民路主干道拥堵研判",
    "event": { "avgSpeed": 8, "queueLength": 400 }
  }
}
```

### 3.3 contextPolicy

| 策略 | 动态字段 | 稳定字段 | 触发条件 |
|------|----------|----------|----------|
| `fresh_event` | None | NL 解析 | 默认 / 重新描述事件 |
| `continue_event` | None（除非明确引用） | 可继承 | "继续"/"上述" 且无新数字 |
| `follow_up` | None | NL 解析 | 普通追问 |

### 3.4 fieldSources

每个字段追踪来源：`current_message` / `missing` / `explicit_value` / `explicit_previous_reference`。

---

## 4. CollaborationRunState

### 4.1 11 状态

```
created → routing → running → arbitrating → fusing → completed
                              ↓            ↓       ↓
                      requires_human_review  partial_success
                                                   ↓
                                                failed
```

### 4.2 关键字段

| 字段 | 说明 |
|------|------|
| `run_id` / `session_id` / `trace_id` | 运行标识 |
| `status` | 当前状态 |
| `normalized_event` | = currentEvent（不含上一轮数据） |
| `previous_run_context` | 独立的上一次运行上下文 |
| `task_results` | 各 Agent 分析结果 |
| `conflicts` | 冲突列表 |
| `arbitration_results` | 仲裁结果列表 |
| `final_decision` | 融合最终决策 |
| `budget_usage` | 预算消耗统计 |

---

## 5. EventBus

内存事件总线，后续可替换为 Redis Streams：

- `publish(message)` — 幂等（message_id 去重）
- `subscribe(message_type, handler)` — 按类型订阅
- `get_history(run_id)` — 按运行过滤

---

## 6. TaskGraph DAG

### 6.1 5 层拓扑

**无冲突场景**:
```
第1层: CongestionAgent
第2层: DispatchAgent
第3层: ConflictDetector
第4层: FusionAgent
```

**有冲突场景**:
```
第1层: CongestionAgent, SignalAgent, PublicSafetyAgent
第2层: DispatchAgent
第3层: ConflictDetector
第4层: ConflictArbiter    ← 动态插入
第5层: FusionAgent
```

### 6.2 循环检测

DFS + recursion stack 检测依赖循环。

### 6.3 动态插入

```python
has_high = conflicts and any(c.get("severity") in ("high", "critical") for c in conflicts)
if has_high:
    arbiter_task = AgentTaskNode("task_arbiter", run_id, "ConflictArbiter",
                                  "arbitrate", depends_on=["task_conflict_detect"])
    graph.add_task(arbiter_task)
    graph.tasks["task_fusion"].depends_on = ["task_arbiter"]  # 重布线
```

---

## 7. Orchestrator / Executor / Budget

### 7.1 Orchestrator

- 创建 state
- 构建初始 DAG
- 循环执行：get_ready_tasks() → execute
- 领域 Agent：通过 `execute_single_agent()` 调用
- 系统 Agent：内联执行
- ConflictDetector 后条件插入 ConflictArbiter
- 完成 → 持久化 → SSE 事件

### 7.2 Executor

- 预算检查 → 上下文裁剪 → 字段校验 → 执行 → 重试
- 可重试：timeout / 临时错误
- 不可重试：ValidationError / 缺少字段

### 7.3 Budget

```python
class ExecutionBudget:
    max_agents: int = 6
    max_agent_calls: int = 2
    max_retries: int = 2
    max_total_seconds: int = 120
```

真实 budget_usage:
```json
{"used_agent_calls": {"CongestionAgent": 1, "DispatchAgent": 1, "ConflictDetector": 1, "ConflictArbiter": 1, "FusionAgent": 1}}
```

---

## 8. SQLite 表结构

5 张表：`collaboration_runs` / `collaboration_tasks` / `collaboration_messages` / `collaboration_conflicts` / `collaboration_events`。

`collaboration_runs` 包含 `previous_run_context` 列（非破坏性 ALTER TABLE 迁移）。

---

## 9. SSE 真流式

### 9.1 完整事件链

```
session_created → run_created → agent_route_done → task_graph_created
→ task_ready × N → task_started × N
→ budget_updated + agent_result + task_succeeded (per domain agent)
→ conflict_check_done → [task_ready ConflictArbiter] (动态)
→ task_started ConflictArbiter → arbitration_result × N → task_succeeded ConflictArbiter
→ fusion_start → fusion_delta × N → fusion_done → run_completed
```

### 9.2 关键事件格式

`run_created`:
```json
{"runId": "...", "sessionId": "...", "userQuery": "...", "contextPolicy": "fresh_event", "fieldSources": {...}, "previousRunContext": {...}}
```

`arbitration_result`:
```json
{"runId": "...", "conflictId": "arb_0", "requiresHumanReview": true, "safetyFirstRule": "...", "resolution": "...", "limitations": [...]}
```

---

## 10. ConflictDetector / ConflictArbiter

### 10.1 ConflictDetector

关键词匹配检测 4 类冲突：

| 类型 | severity | 条件 |
|------|----------|------|
| strategy_conflict | high | Signal(信号/配时) vs Safety(学校/行人) |
| priority_conflict | high | 通行效率 vs 学生安全 |
| resource_conflict | high | 信号周期资源争抢 |
| safety_conflict | medium | 分流 vs 行人保护 |

### 10.2 ConflictArbiter

规则引擎仲裁：
- severity=low/medium → 自动解决，`resolved=True`
- severity=high → `requiresHumanReview=True`，`resolved=False`

输出包含 `safetyFirstRule`、`resolution`、`limitations`。

---

## 11. final_decision

```python
final = {
    "fusionSummary": "...",       # DeepSeek LLM 或模板
    "generationMode": "llm",
    "requiresHumanReview": bool,  # 仲裁驱动
    "actionPlan": [...],
    "arbitration": {
        "results": [...],
        "totalConflicts": N,
        "resolvedCount": M,
        "unresolvedCount": K,
    },
}
```

FusionAgent prompt 注入仲裁结果上下文，模板降级时也消费仲裁。

---

## 12. 一 Session 多 Run

### 12.1 生命周期

```
POST /agent/routed_analyze/stream (sessionId=null)
  → 创建 chat_session sess_A
  → 创建 collaboration_run run_1
  → session_created(sess_A)

POST /agent/routed_analyze/stream (sessionId=sess_A)
  → 复用 sess_A
  → 创建 collaboration_run run_2
  → 无 session_created
```

### 12.2 前端 sessionIdRef

使用 `useRef` 防止闭包过期：
- `session_created` 到达时：`sessionIdRef.current = sid`
- `handleAnalyze`：`sessionId: sessionIdRef.current`
- 新对话入口：`sessionIdRef.current = null`

### 12.3 正确结果

- session_created 仅 1 次
- chat_sessions 新增 1 条
- collaboration_runs 新增 N 条
- Sidebar 1 条记录

---

## 13. 历史恢复

### 13.1 恢复链路

```
点击 Sidebar session (mode=collaboration)
  → setView("multi")
  → GET /chat/sessions/{sid}
  → GET /collaboration/sessions/{sid}/runs
  → 默认选最新 runId
  → GET /collaboration/runs/{runId}
  → normalizeRunAuditResponse
  → 渲染 CollaborationRunView（含 DAG/Agent/Conflict/Arbiter/Budget/Fusion）
```

### 13.2 RunSummary 不覆盖 RunDetail

列表接口返回摘要（仅 status/时间），不包含 tasks/agentResults/conflicts。详细数据通过独立 GET 获取。

---

## 14. Sidebar mode 标签

```typescript
const MODE_LABELS: Record<string, string> = {
  react: '诊断', routed: '研判', rag: '知识库',
  hybrid: '相似', report: '报告', collaboration: '协同',
};
```

每条"最近分析"条目右侧显示 Tag。

---

## 15. React ErrorBoundary

`CollaborationErrorBoundary` 捕获渲染异常：

- 显示："协同分析页面渲染失败" + 错误信息
- 开发环境显示完整 stack
- 提供"重新加载本轮详情"和"返回协同分析首页"按钮
- Sidebar 保持可用

---

## 16. 自动化测试

### 16.1 总览

- **251 passed** / TypeScript 0 errors
- 测试文件：`test_sample_request.py`（130）+ `test_phase9_multi_run.py`（121）

### 16.2 Phase 9 专项测试类别

| 测试类 | 数量 | 覆盖 |
|--------|------|------|
| TestMultiRunIsolation | 4 | 多 Run 输入隔离 |
| TestSchoolScenarioRouting | 3 | 学校触发路由 |
| TestConflictDetection | 5 | 冲突检测与仲裁 |
| TestAgentProposals | 2 | 结构化 proposal |
| TestParserFields | 4 | NL 解析字段 |
| TestRunDedup | 2 | Run 去重 |
| TestTwoRoundFinal | 2 | 双轮隔离 |
| TestDetailHydration | 3 | Run 详情水合 |
| TestFusionPersistence | 6 | 融合持久化 |
| TestSidebarLabels | 1 | 会话标签 |
| TestConflictScenarioFinal | 3 | 冲突场景回归 |
| TestConflictArbiterDagInsertion | 4 | 动态 DAG 插入 |
| TestArbitrationResultContent | 6 | 仲裁结果内容 |
| TestFinalDecisionWithArbitration | 3 | final_decision 仲裁 |
| TestSessionModeLabels | 5 | 会话标签映射 |
| TestSchoolConflictFullScenario | 6 | 冲突端到端 |
| TestHistoryRecoveryWithArbitration | 2 | 历史含仲裁 |
| TestFieldIsolation | 16 | 字段隔离 |
| TestCurrentEventSeparation | 7 | currentEvent 分离 |
| TestFieldSourcesExplicitPrevious | 3 | fieldSources 标记 |
| TestAllScenariosStillPass | 3 | 全部回归 |
| TestE2EContamination | 1 | 10 项端到端污染验证 |
| TestFrontendResilience | 14 | 前端韧性 |
| TestSessionLifecycle | 16 | 会话生命周期 |

### 16.3 手工验收场景

**普通拥堵**："主干道平均车速8km/h，排队400米，请协同研判。" → DAG 4 层，无仲裁。

**学校冲突**："人民路小学门口早高峰严重拥堵，机动车需绿灯，学生需过街相位。" → DAG 5 层（含 ConflictArbiter），3 个仲裁结果，requiresHumanReview=true。

**多轮隔离**：第 1 轮 avgSpeed=8 → 第 2 轮"学校门口拥堵" → 第 2 轮 avgSpeed=None。

**历史恢复**：刷新 → 点击 session → 完整恢复 DAG/冲突/仲裁/融合。

---

## 17. 已知限制及 Phase 10 方向

### 17.1 已知限制

| 限制 | 影响 |
|------|------|
| EventBus 仅内存实现 | 不能跨进程通信 |
| 领域 Agent 同层串行执行 | 未用 asyncio.gather |
| ConflictDetector 仅关键词匹配 | 可能漏检/误检 |
| ConflictArbiter 仅规则引擎 | 复杂冲突缺深度分析 |
| SQLite 单机存储 | 不支持分布式 |

### 17.2 Phase 10 建议

1. 并行 Agent 执行（asyncio.gather）
2. Redis EventBus 替换
3. PostgreSQL 迁移
4. LLM 辅助仲裁（规则不足时调用）
5. SUMO 交通仿真验证配时方案
6. Docker 容器化部署
7. JWT/OAuth2 API 鉴权
8. WebSocket 实时大屏推送

---

> **文档维护说明**：修改协作核心逻辑后请同步更新此文件。
