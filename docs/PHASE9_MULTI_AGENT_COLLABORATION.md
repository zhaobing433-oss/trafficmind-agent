# Phase 9 — 多 Agent 协作通信、动态冲突仲裁与历史审计

> **状态**: 已完成  
> **测试**: 191 passed / TypeScript 0 errors  
> **日期**: 2026-07-21  
> **分支**: `feature/stage-9-multi-agent-collaboration`

---

## 1. 背景与目标

### 1.1 问题

前序阶段（Phase 4–8）已实现多 Agent 独立分析，但存在以下结构性缺陷：

| 问题 | 影响 |
|------|------|
| Agent 之间无标准通信协议 | 消息格式不一致，无法做审计追踪 |
| 无显式 DAG 编排 | 执行顺序硬编码，不支持动态插入中间节点 |
| 冲突检测后无仲裁层 | 检测到 high-severity 冲突后直接进入 FusionAgent，缺少仲裁决议 |
| 无协作运行状态机 | 无法追踪一次运行的生命周期（routing → running → arbitrating → fusing → completed） |
| 无持久化审计 | 历史运行无法恢复，不能追溯 Agent 的输入/输出快照 |
| 无上下文裁剪 | 每个 Agent 接收完整状态，违反最小权限原则 |
| 前端无多 Run 隔离 | 同一会话内多次协同分析的 DAG 和结果混在一起 |

### 1.2 目标

1. **标准消息协议** — Pydantic 定义 Agent 间通信的所有消息类型
2. **DAG 任务图** — 显式声明任务依赖，拓扑排序执行
3. **协作运行状态机** — 11 种状态、合法转换校验
4. **动态冲突仲裁** — ConflictArbiter 在检测到 high/critical 冲突时动态插入 DAG
5. **最小权限上下文** — 每个 Agent 只接收角色允许的字段子集
6. **SQLite 持久化** — 5 张协作专用表，完整审计追踪
7. **SSE 真流式** — 每个生命周期事件实时推送到前端
8. **多 Run 隔离** — 前端 runsById + activeRunId，历史恢复完整 DAG 和仲裁结果
9. **会话类型标签** — 6 种 mode → 中文标签映射

---

## 2. 原有多 Agent 链路的问题

### 2.1 Phase 4–8 的链路

```
route_agents() → [agent.analyze() for agent in selected] → detect_conflicts() → resolve_conflicts() → fusion
```

问题：

- **线性执行**：所有 Agent 串行调用，无并行能力
- **无任务 DAG**：依赖关系隐式编码在代码中
- **无冲突仲裁**：`resolve_conflicts()` 直接融合，不产生独立的仲裁记录
- **无持久化**：运行结果只在内存中，刷新即丢失
- **消息无协议**：Agent 间传 dict，字段不统一

### 2.2 Phase 9 的改进

```
route_agents() → build DAG → execute tasks topologically → ConflictDetector → [ConflictArbiter if high] → FusionAgent → persist
```

- DAG 显式声明任务和依赖
- 拓扑排序保证执行顺序
- ConflictArbiter 按需动态插入
- 每个 task 有完整的 input_snapshot / output_snapshot
- 所有生命周期事件通过 SSE 实时推送

---

## 3. 角色边界设计

每个 Agent 有明确的能力边界，在 `REGISTERED_AGENTS` 中注册：

| Agent | 角色 | 职责 | 禁止 |
|-------|------|------|------|
| CongestionAgent | 拥堵分析 | 分析 avgSpeed / queueLength / 拥堵扩散 | 不得给出信号配时秒数 |
| SignalAgent | 信号控制 | 分析绿信比 / 周期 / 协调控制 | 不得直接控制信号灯 |
| PublicSafetyAgent | 公共安全 | 分析学校 / 医院 / 行人风险 | 不得代替 DispatchAgent |
| DispatchAgent | 调度处置 | 读取领域结果，生成分流/警力方案 | 不得在领域 Agent 前自行分析 |
| ConflictDetector | 冲突检测 | 比较 proposals，检测冲突 | 不得修改 Agent 结论 |
| ConflictArbiter | 冲突仲裁 | 规则仲裁 high/critical 冲突 | 不得重新分析业务 |
| FusionAgent | 融合总结 | 融合已确认结果，不编造新事实 | 不得跳过仲裁层 |

每个 Agent 还定义了：
- `accepted_message_types` / `produced_message_types` — 通信协议
- `allowed_input_fields` — 最小权限字段集
- `required_input_fields` — 必要字段校验
- `max_calls` / `max_retries` / `timeout_seconds` — 执行预算
- `dependencies` — 上游依赖声明

---

## 4. 标准消息协议

所有 Agent 间通信使用 `AgentMessage`（Pydantic BaseModel）：

```python
class AgentMessage(BaseModel):
    protocol_version: str       # "1.0"
    message_id: str             # 全局唯一
    run_id: str                 # 运行实例 ID
    session_id: str
    trace_id: str               # 追踪 ID
    task_id: str
    parent_message_id: Optional[str]
    sender: str                 # 发送方 Agent 名称
    receiver: str               # 接收方 Agent 名称
    message_type: str           # 14 种标准类型
    phase: str                  # 当前阶段
    priority: int               # 1-10
    attempt: int                # 重试次数
    deadline: Optional[str]     # ISO 格式截止时间
    payload: Dict[str, Any]     # 业务负载
    context_refs: List[str]     # 上下文引用
    evidence_refs: List[str]    # 证据引用
    created_at: str             # ISO 时间戳
```

支持的 14 种消息类型：
`task.assign`, `task.started`, `task.result`, `task.failed`, `tool.request`, `tool.result`, `conflict.detected`, `arbitration.request`, `arbitration.result`, `fusion.request`, `run.completed`, `run.failed`, `heartbeat`

---

## 5. CollaborationRunState 状态机

### 5.1 状态定义（11 种）

```
created → routing → running → arbitrating → fusing → completed
                                      ↓            ↓       ↓
                              requires_human_review  partial_success
                                                           ↓
                                                        failed
```

可中断状态：`routing`, `running`, `arbitrating`, `fusing`  
终止状态：`completed`, `partial_success`, `failed`, `requires_human_review`, `interrupted`

### 5.2 合法转换表

```python
VALID_TRANSITIONS = {
    "created":      {"routing"},
    "routing":      {"running", "failed", "interrupted"},
    "running":      {"arbitrating", "fusing", "partial_success", "failed", "interrupted", "completed"},
    "arbitrating":  {"fusing", "requires_human_review", "failed", "interrupted"},
    "fusing":       {"completed", "partial_success", "failed", "interrupted"},
}
```

### 5.3 关键字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `run_id` | str | 全局唯一运行 ID |
| `status` | str | 当前状态 |
| `selected_agents` | List[str] | 路由选中的 Agent |
| `task_results` | Dict[str, Any] | 各 Agent 分析结果 |
| `conflicts` | List[Dict] | 检测到的冲突列表 |
| `arbitration_results` | List[Dict] | 仲裁结果列表 |
| `final_decision` | Dict | 融合最终决策 |
| `failed_agents` | List[str] | 失败 Agent 列表 |
| `budget_usage` | Dict | 预算消耗统计 |

---

## 6. 上下文裁剪策略

每个 Agent 只接收其角色允许的字段子集，不接收完整状态（最小权限原则）。

```python
def project_context_for_agent(state, agent_name):
    cap = get_agent_capability(agent_name)
    allowed = cap["allowed_input_fields"]
    # 只投影允许的字段
    return {field: event[field] for field in allowed if field in event}
```

特殊处理：
- **DispatchAgent**：额外接收 `domain_results`（领域 Agent 的结构化输出）
- **ConflictArbiter**：只接收 `conflicts` 数据
- **FusionAgent**：接收 `completed_results` + `arbitration_results`

同时执行 `validate_required_fields()` — 缺少必要字段时抛出 `ValidationError`。

---

## 7. EventBus

本地内存事件总线，设计为后续可替换为 Redis Streams / RabbitMQ。

```python
class InMemoryEventBus:
    _history: List[Dict]          # 完整消息历史
    _subscribers: Dict[str, List] # 消息类型 → 处理器列表
    _idempotency_keys: set        # 幂等保护（message_id 去重）
```

核心方法：
- `publish(message)` — 发布消息，幂等保护
- `subscribe(message_type, handler)` — 订阅消息类型
- `get_history(run_id)` — 按 run_id 过滤历史

全局单例通过 `get_event_bus()` 获取。

---

## 8. TaskGraph DAG

### 8.1 AgentTaskNode

```python
class AgentTaskNode:
    task_id: str          # 全局唯一
    agent_name: str       # Agent 名称
    task_type: str        # analyze / dispatch / conflict_detect / arbitrate / fusion
    depends_on: List[str] # 依赖的 task_id 列表
    status: str           # pending → running → succeeded / failed
    priority: int         # 1-10
    attempt: int          # 当前尝试次数
    input_snapshot: Dict  # 输入快照（用于审计）
    output_snapshot: Dict # 输出快照（用于审计）
```

### 8.2 CollaborationTaskGraph

```python
class CollaborationTaskGraph:
    add_task(task)              # 添加任务节点
    validate_dependencies()     # 校验依赖 + 检测循环
    get_ready_tasks()           # 返回依赖已满足的 pending 任务
    mark_running/succeeded/failed/skipped(task_id)
    topological_order()         # 拓扑排序
    is_completed()              # 所有任务终态
```

循环检测使用 DFS + recursion stack。

### 8.3 正确 DAG 拓扑

**无冲突场景**（如普通拥堵）：
```
第1层: CongestionAgent
第2层: DispatchAgent
第3层: ConflictDetector
第4层: FusionAgent
```

**有冲突场景**（如学校门口信号 vs 安全）：
```
第1层: CongestionAgent, SignalAgent, PublicSafetyAgent
第2层: DispatchAgent
第3层: ConflictDetector
第4层: ConflictArbiter    ← 动态插入
第5层: FusionAgent
```

---

## 9. Orchestrator

`CollaborationOrchestrator` 是编排核心，职责：

1. 创建 `CollaborationRunState`
2. 解析 NL → 标准化事件
3. 构建初始 DAG（domain agents → Dispatch → ConflictDetector → FusionAgent）
4. 发射 `task_ready` 事件
5. 循环执行：
   a. `get_ready_tasks()` → 获取就绪任务
   b. 领域 Agent：通过 `execute_single_agent()` 调用
   c. 系统 Agent（ConflictDetector / ConflictArbiter / FusionAgent）：内联执行
6. ConflictDetector 完成后，如果检测到 high/critical 冲突 → **动态插入 ConflictArbiter**
7. 重布线 FusionAgent 依赖：`depends_on = ["task_arbiter"]`
8. 所有任务完成后 → 状态转换 → 持久化 → 发射完成事件

关键代码路径：

```
execute()
  ├── parse_content_to_event()           # NL → 标准化事件
  ├── build DAG                          # 初始 4 层
  ├── for layer in range(6):
  │     ├── get_ready_tasks()
  │     ├── if domain agent:
  │     │     execute_single_agent()
  │     ├── if ConflictDetector:
  │     │     _detect_simple_conflicts()
  │     │     if has_high → insert ConflictArbiter
  │     ├── if ConflictArbiter:
  │     │     conflict_arbiter() × N
  │     │     emit arbitration_result
  │     └── if FusionAgent:
  │           DeepSeek stream → fusion_delta
  │           build final_decision with arbitration
  └── save all state → run_completed
```

---

## 10. Executor、Budget、重试、超时

### 10.1 Executor

```python
async def execute_single_agent(task, state, budget):
    for attempt in range(1, task.max_retries + 2):
        budget.can_call_agent(name)         # 预算检查
        budget.record_agent_call(name)      # 记录调用
        ctx = project_context_for_agent()   # 上下文裁剪
        validate_required_fields()          # 字段校验
        result = await _call_agent_function() # 执行 Agent
        return AgentExecutionResult(success=True, result=...)
```

重试策略：
- 可重试错误：timeout、临时错误
- 不可重试错误：ValidationError、缺少字段、未注册 Agent
- 重试延迟：`retry_delay * attempt`（指数退避）

### 10.2 Budget

```python
class ExecutionBudget:
    max_agents: int = 6
    max_agent_calls: int = 2      # 每个 Agent 最大调用次数
    max_retries: int = 2
    max_total_seconds: int = 120
    used_agent_calls: Dict[str, int]
    used_retries: Dict[str, int]
```

超时设置：
- 领域 Agent：30 秒（`asyncio.wait_for`）
- ConflictDetector：10 秒
- ConflictArbiter：30 秒
- FusionAgent：30 秒（含 LLM 调用）

真实 budget_usage 示例：
```json
{
  "used_agent_calls": {
    "CongestionAgent": 1,
    "DispatchAgent": 1,
    "ConflictDetector": 1,
    "ConflictArbiter": 1,
    "FusionAgent": 1
  }
}
```

---

## 11. SQLite 表结构

5 张协作专用表：

```sql
-- 运行实例
CREATE TABLE collaboration_runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT, trace_id TEXT,
    status TEXT, protocol_version TEXT DEFAULT '1.0',
    normalized_event TEXT DEFAULT '{}',
    selected_agents TEXT DEFAULT '[]',
    skipped_agents TEXT DEFAULT '[]',
    failed_agents TEXT DEFAULT '[]',
    budget_usage TEXT DEFAULT '{}',
    final_decision TEXT DEFAULT '',
    started_at TEXT, updated_at TEXT, completed_at TEXT
);

-- 任务节点（含 input/output 快照）
CREATE TABLE collaboration_tasks (
    task_id TEXT NOT NULL, run_id TEXT NOT NULL,
    agent_name TEXT, task_type TEXT, status TEXT DEFAULT 'pending',
    depends_on TEXT DEFAULT '[]',
    input_snapshot TEXT DEFAULT '{}',
    output_snapshot TEXT DEFAULT '{}',
    error_code TEXT, error_message TEXT,
    started_at TEXT, completed_at TEXT,
    PRIMARY KEY (run_id, task_id)
);

-- 通信消息（审计追踪）
CREATE TABLE collaboration_messages (
    message_id TEXT PRIMARY KEY,
    run_id TEXT, sender TEXT, receiver TEXT,
    message_type TEXT, payload TEXT DEFAULT '{}',
    created_at TEXT
);

-- 冲突与仲裁
CREATE TABLE collaboration_conflicts (
    conflict_id TEXT NOT NULL, run_id TEXT NOT NULL,
    conflict_type TEXT, severity TEXT,
    participants TEXT DEFAULT '[]',
    resolution TEXT, resolved_by TEXT,
    requires_human_review INTEGER DEFAULT 0,
    PRIMARY KEY (run_id, conflict_id)
);

-- 事件流
CREATE TABLE collaboration_events (
    event_id TEXT NOT NULL, run_id TEXT NOT NULL,
    event_type TEXT, payload TEXT DEFAULT '{}',
    sequence_number INTEGER DEFAULT 0,
    PRIMARY KEY (run_id, event_id)
);
```

---

## 12. SSE 事件协议

### 12.1 完整事件流

```
event: session_created        { sessionId }
event: event_parse_done       { normalizedEvent }
event: run_created            { runId, traceId, userQuery, selectedAgents }
event: agent_route_done       { selectedAgents, routingReasons }
event: task_graph_created     { tasks: [...] }
event: task_ready             { runId, taskId, agentName, status }
event: task_started           { runId, taskId, agentName, status, attempt }
event: budget_updated         { runId, maxAgents, usedAgentCalls, ... }
event: agent_result           { agentName, taskId, status, result: {...} }
event: task_succeeded         { runId, taskId, agentName, status }
event: conflict_check_done    { runId, conflicts, conflictCount }
event: arbitration_result     { runId, conflictId, requiresHumanReview, safetyFirstRule, resolution, limitations }
event: fusion_start           { runId, text }
event: fusion_delta           { runId, text, executionMode }
event: fusion_done            { runId, fusionSummary, generationMode }
event: run_completed          { runId, status }
```

### 12.2 冲突场景特有事件

当检测到 high/critical 冲突时，额外出现：

```
event: task_ready             ConflictArbiter    ← 动态插入
event: task_started           ConflictArbiter
event: arbitration_result     { requiresHumanReview: true, safetyFirstRule: "...", ... }
event: task_succeeded         ConflictArbiter
```

### 12.3 降级事件

```
event: fallback_started       { reason, fallbackFrom }
```

---

## 13. 动态 Agent 路由

`route_agents()` 是确定性规则引擎，不使用 LLM：

| 规则 | 条件 | 触发 Agent |
|------|------|------------|
| 事件类型 | 拥堵 | CongestionAgent |
| 事件类型 | 信号关键词 | +SignalAgent |
| 事件类型 | 事故 | AccidentAgent + CongestionAgent |
| 事件类型 | 行人闯入 | PublicSafetyAgent + DispatchAgent |
| 风险等级 | 高风险/重大风险 | +DispatchAgent |
| 环境因素 | 邻近学校/医院 | +PublicSafetyAgent |
| 环境因素 | 行人风险=high | +PublicSafetyAgent |
| 时间段 | 高峰 | +CongestionAgent |
| 始终包含 | — | DispatchAgent, FusionAgent |

---

## 14. ConflictDetector 规则

`_detect_simple_conflicts()` 检测三类冲突：

### 14.1 strategy_conflict（策略冲突）
触发条件：SignalAgent 结论含"信号/配时/绿/周期" AND PublicSafetyAgent 结论含"学校/医院/行人/过街/安全"
- severity: high
- 示例：机动车通行效率优化 vs 行人安全需求

### 14.2 priority_conflict（优先级冲突）
触发条件：同上（同一对 Agent 间）
- severity: high
- 示例：通行效率优先级 vs 学生过街安全优先级

### 14.3 resource_conflict（资源冲突）
触发条件：同上
- severity: high
- 示例：同一信号周期内机动车绿灯 vs 行人过街相位争抢

### 14.4 safety_conflict（安全冲突）
触发条件：CongestionAgent 结论含"分流/放行/通行" AND PublicSafetyAgent 结论含"学校/行人/过街/安全"
- severity: medium
- 示例：分流方案可能增加行人安全风险

---

## 15. ConflictArbiter 动态插入

### 15.1 触发条件

```python
has_high = conflicts and any(c.get("severity") in ("high", "critical") for c in conflicts)
```

### 15.2 插入流程

```
ConflictDetector 完成
  ├── _detect_simple_conflicts(state)
  ├── if has_high:
  │     ├── arbiter_task = AgentTaskNode("task_arbiter", ..., depends_on=["task_conflict_detect"])
  │     ├── graph.add_task(arbiter_task)
  │     ├── graph.tasks["task_fusion"].depends_on = ["task_arbiter"]  # 重布线
  │     ├── graph.validate_dependencies()  # 重新校验
  │     ├── emit task_ready ConflictArbiter
  │     └── save_task(arbiter_task)
  └── 继续循环
```

### 15.3 执行

```python
for c in state.conflicts:
    arb = conflict_arbiter(c)              # 调用规则仲裁
    arb["safety_first_rule"] = safety_first  # 补充安全原则
    arb["limitations"] = [...]               # 补充限制说明
    yield sse_event("arbitration_result", {
        "runId": run_id,
        "conflictId": arb["conflict_id"],
        "requiresHumanReview": arb["requires_human_review"],
        "safetyFirstRule": safety_first,
        "resolution": arb["resolution"],
        "limitations": arb["limitations"],
    })
```

### 15.4 学校场景仲裁结果示例

```json
{
  "conflictId": "arb_0",
  "resolved": false,
  "resolution": "高风险冲突需要人工研判",
  "requiresHumanReview": true,
  "safetyFirstRule": "在学生过街安全与机动车通行效率冲突时，学生生命安全绝对优先。行人相位保障是第一原则；机动车绿灯延长必须在确保行人安全过街时间充足后方可实施。",
  "limitations": [
    "信号配时精确值需现场勘查确认",
    "学生过街流量需学校提供统计数据"
  ]
}
```

---

## 16. FusionAgent 如何消费仲裁结果

### 16.1 LLM Prompt 增强

当存在仲裁结果时，FusionAgent 的 prompt 会追加仲裁上下文：

```python
if state.arbitration_results:
    arb_text = "；".join(
        f"仲裁{ar.get('conflict_id','')}: {ar.get('resolution','')}"
        for ar in state.arbitration_results
    )
    agent_text += f"\n\n仲裁结果: {arb_text}"
```

### 16.2 final_decision 结构

```python
final = {
    "fusionSummary": fusion,            # 自然语言融合总结
    "generationMode": "llm|template_fallback",
    "requiresHumanReview": bool,        # 由仲裁结果驱动
    "actionPlan": [...],
    "monitoringIndicators": [],
    "limitations": [],
    "confidence": 0.8,
    "arbitration": {                    # ← 新增
        "results": state.arbitration_results,
        "totalConflicts": len(state.conflicts),
        "resolvedCount": N,
        "unresolvedCount": M,
    },
}
```

### 16.3 模板降级 (_build_fusion)

LLM 不可用时，模板函数也消费仲裁结果：
- 显示仲裁原则 (`safety_first_rule`)
- 区分已解决 / 未解决冲突
- 标注需要人工审核

---

## 17. requiresHumanReview 设计

### 17.1 触发条件

| 来源 | 条件 | 值 |
|------|------|-----|
| ConflictArbiter | severity = high/critical | `requires_human_review = True` |
| ConflictArbiter | severity = low/medium | `requires_human_review = False` |
| FusionAgent | 存在未解决冲突 | `requiresHumanReview = True` |
| FusionAgent | 全部已解决 | `requiresHumanReview = False` |

### 17.2 前端展示

```tsx
// FusionDecisionView.tsx
if (run.requiresHumanReview) {
  return { bg: '#FEF2F2', color: '#991B1B',
    text: '⚠ 需要人工审核 — 以上建议不能作为确定执行命令' };
}
```

```tsx
// ConflictPanel.tsx
{c.requiresHumanReview && (
  <div style={{ color: '#EF4444', fontWeight: 700 }}>
    ⚠ 需要人工审核 — 当前建议不能作为确定执行命令
  </div>
)}
```

---

## 18. 前端 runsById/activeRunId

### 18.1 数据模型

```typescript
// App.tsx
const [runsById, setRunsById] = useState<Record<string, CollaborationRun>>({});
const [activeRunId, setActiveRunId] = useState<string>('');
```

### 18.2 多 Run 隔离策略

- 每次协同分析创建一个新的 `CollaborationRun`，存入 `runsById[runId]`
- `activeRunId` 追踪当前活跃运行
- SSE 事件携带 `runId`，前端通过 `runId` 路由到正确的 Run
- 历史恢复：点击侧边栏会话 → `GET /collaboration/sessions/{id}/runs` → `GET /collaboration/runs/{runId}` 获取详情

### 18.3 Run 生命周期

```
createEmptyRun()
  → SSE: run_created → setRunsById
  → SSE: task_ready × N → update task in run.tasks
  → SSE: task_started → update task status
  → SSE: agent_result → update run.agentResults
  → SSE: conflict_check_done → update run.conflicts
  → SSE: arbitration_result → update run.conflicts with resolution
  → SSE: fusion_delta → append to run.fusionSummary
  → SSE: fusion_done → finalize run
  → SSE: run_completed → mark complete
```

---

## 19. DAG、Agent 卡片、冲突面板、预算、融合结果

### 19.1 CollaborationDagView

5 层 DAG 可视化：
```
const LAYERS = {
  CongestionAgent: 0, SignalAgent: 0, PublicSafetyAgent: 0, AccidentAgent: 0,
  DispatchAgent: 1,
  ConflictDetector: 2,
  ConflictArbiter: 3,
  FusionAgent: 4,
};
```

每个节点显示：Agent 名称、状态（颜色编码）、尝试次数、错误信息。

### 19.2 AgentExecutionCard

展示单个 Agent 的分析结果：
- 角色描述
- 紧急度标签（high/critical 红色，medium 黄色）
- 置信度百分比
- 发现列表
- 建议

### 19.3 ConflictPanel

展示冲突列表：
- 按 severity 着色（high: 红色背景，medium: 黄色背景）
- 显示参与方、冲突描述
- **如果有 resolution**：绿色显示仲裁决议
- **如果 requiresHumanReview**：红色警告

### 19.4 BudgetUsagePanel

显示预算使用：
- Agent 调用次数 / 最大限制
- 重试次数 / 最大限制
- 失败 Agent 列表

### 19.5 FusionDecisionView

展示最终融合决策：
- 状态横幅（failed / interrupted / partial_success / requiresHumanReview）
- 融合总结文本
- 失败 Agent、限制说明
- requiresHumanReview 红色警告

---

## 20. 多轮协同与历史恢复

### 20.1 多轮协同

同一会话内可以发起多次协同分析：
- 每次创建新的 `runId`
- 使用相同的 `sessionId`
- 不同的 `runsById` 条目
- `activeRunId` 切换到最新 Run

### 20.2 历史恢复

通过审计 API 恢复完整运行：

```
GET /collaboration/sessions/{sessionId}/runs
  → 返回该会话所有运行的摘要列表

GET /collaboration/runs/{runId}
  → 返回完整运行详情：
    {
      "run": { status, selectedAgents, finalDecision, budgetUsage, ... },
      "tasks": [{ taskId, agentName, status, inputSnapshot, outputSnapshot, ... }],
      "messages": [{ sender, receiver, messageType, payload, ... }],
      "conflicts": [{ type, severity, resolution, requiresHumanReview, ... }],
      "events": [{ eventType, payload, sequenceNumber, ... }]
    }
```

前端恢复后：
- DAG 显示完整任务图（包括 ConflictArbiter）
- 冲突面板显示仲裁结果
- 融合决策显示 final_decision
- 预算面板显示预算消耗
- Agent 卡片显示各 Agent 输入/输出快照

---

## 21. 最近分析 mode 标签

侧边栏每个会话右侧显示 `Tag` 组件：

```typescript
const MODE_LABELS: Record<string, string> = {
  react: '诊断',
  routed: '研判',
  rag: '知识库',
  hybrid: '相似',
  report: '报告',
  collaboration: '协同',
};
```

每条 "最近分析" 条目格式：
```
[会话标题] [协同]
```

Tag 样式：灰色背景、圆角、9px 字号，不换行。

---

## 22. 降级与 Feature Flag

### 22.1 Feature Flag

```python
COLLABORATION_ORCHESTRATOR_ENABLED = os.getenv("COLLABORATION_ORCHESTRATOR_ENABLED", "true").lower() == "true"
```

- `true`（默认）：使用 `CollaborationOrchestrator` 执行
- `false`：降级到旧 `_legacy_analyze_stream` 实现

### 22.2 运行时降级

在 `_orchestrated_analyze_stream()` 中：

```python
try:
    orchestrator = CollaborationOrchestrator()
    async for event_str in orchestrator.execute(...):
        yield event_str
except Exception as e:
    # 不可重试错误（ValidationError 等）→ 直接报错
    if any(kw in str(e) for kw in ["ValidationError", "缺少", "未注册", "非法"]):
        yield sse_error(str(e))
        return
    # 系统错误 → 降级到旧实现
    yield sse_event("fallback_started", {"reason": str(e)})
    async for ev in _legacy_analyze_stream_inner(body, sid):
        yield ev
```

### 22.3 LLM 降级

DeepSeek 不可用时，自动降级到模板方案：
- `_build_fusion()` 生成结构化融合文本
- `_chunk_text()` 模拟流式输出
- `generationMode = "template_fallback"` 标记降级

---

## 23. 审计 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/collaboration/runs/{run_id}` | 查询单次运行完整审计记录 |
| GET | `/collaboration/sessions/{session_id}/runs` | 查询会话的所有运行摘要 |

### 审计记录包含

- **run**：状态、选中 Agent、预算消耗、最终决策
- **tasks**：每个任务的输入/输出快照、状态、重试次数
- **messages**：所有 Agent 间通信消息（sender/receiver/messageType/payload）
- **conflicts**：冲突类型、严重度、仲裁决议、是否需要人工审核
- **events**：按 sequenceNumber 排序的完整事件流

---

## 24. 自动化测试列表

### 24.1 测试概览

- **总测试数**: 191 passed
- **TypeScript**: 0 errors
- **测试文件**: `backend/tests/test_sample_request.py`（130 个）+ `backend/tests/test_phase9_multi_run.py`（61 个）

### 24.2 Phase 9 专项测试（test_phase9_multi_run.py, 61 个）

| 测试类 | 测试数 | 覆盖内容 |
|--------|--------|----------|
| TestMultiRunIsolation | 4 | 多 Run 输入隔离、学校场景 avgSpeed=None |
| TestSchoolScenarioRouting | 3 | 学校触发 PublicSafety、信号触发 SignalAgent、普通拥堵不触发 |
| TestConflictDetection | 5 | 冲突检测、无冲突跳过、仲裁创建、人工审核、低冲突自动解决 |
| TestAgentProposals | 2 | 缺失字段处理、结构化 proposal |
| TestParserFields | 4 | 学校关键词、信号关键词、冲突意图、缺失字段追踪 |
| TestRunDedup | 2 | Run 去重、run_id 唯一性 |
| TestTwoRoundFinal | 2 | 双轮 Run 隔离、标题不覆盖 |
| TestDetailHydration | 3 | Run 详情返回 tasks、摘要不含 tasks、budget 持久化 |
| TestFusionPersistence | 6 | assistant message 非占位、final_decision 结构化、fusion_delta 含 runId、fusion_done、budget 非空、budget_updated 事件 |
| TestSidebarLabels | 1 | 会话 mode 字段正确 |
| TestConflictScenarioFinal | 3 | 3 类冲突类型、high 冲突人工审核、纯拥堵无冲突 |
| **TestConflictArbiterDagInsertion** | 4 | 动态插入、无冲突跳过、拓扑层序、依赖就绪 |
| **TestArbitrationResultContent** | 6 | requiresHumanReview、safety_first_rule、resolution、limitations、资源冲突、优先级冲突 |
| **TestFinalDecisionWithArbitration** | 3 | arbitration key、未解决触发人工审核、全部解决 |
| **TestSessionModeLabels** | 5 | 全部 mode 标签、创建会话 mode 保存、rag/react 标签 |
| **TestSchoolConflictFullScenario** | 6 | 端到端 SSE 事件链、冲突检测、仲裁结果、fusion_done、task_ready、run_completed |
| **TestHistoryRecoveryWithArbitration** | 2 | Run 详情含仲裁、持久化 tasks 含 ConflictArbiter |

### 24.3 其他 Phase 9 相关测试（test_sample_request.py 中）

| 测试类 | 覆盖内容 |
|--------|----------|
| TestStateMachine | 合法转换、非法转换拒绝、终止态不可转换 |
| TestTaskGraph | DAG 校验、循环检测、依赖缺失、重复 task_id、未注册 Agent、就绪判定、失败阻塞 |
| TestBudget | 预算耗尽、重试计数 |
| TestOrchestrator | 创建 Run、拥堵场景执行 |
| TestSqliteRepository | 保存/读取 Run、消息幂等、冲突保存 |
| TestCollaborationAgents | Dispatch 读取领域结果、冲突检测、仲裁 medium/high、融合总结、失败 Agent |
| TestErrorCodes | 9 种错误码定义 |
| TestAuditAPI | 审计端点存在 |
| TestOrchestratorE2E | 编排器完整流程 |
| TestPhase94Integration | Feature Flag、路由存在、interrupted 状态、降级流 |

---

## 25. 手工验收场景

### 25.1 普通拥堵（无冲突）

**输入**: "主干道平均车速8km/h，排队400米，请协同研判。"

**期望 SSE 事件链**:
```
session_created → run_created → agent_route_done → task_graph_created
→ task_ready CongestionAgent → task_started → agent_result → task_succeeded
→ task_ready DispatchAgent → task_started → agent_result → task_succeeded
→ task_ready ConflictDetector → task_started → conflict_check_done(conflicts=[]) → task_succeeded
→ task_ready FusionAgent → task_started → fusion_start → fusion_delta×N → fusion_done → task_succeeded
→ run_completed
```

**期望 budget_usage**:
```json
{
  "used_agent_calls": {
    "CongestionAgent": 1,
    "DispatchAgent": 1,
    "ConflictDetector": 1,
    "FusionAgent": 1
  }
}
```

### 25.2 学校门口冲突（有冲突 → 仲裁）

**输入**: "人民路小学门口早高峰严重拥堵，大量学生正在集中横穿道路。为缓解机动车拥堵，拟将机动车主方向绿灯延长20秒；但为保障学生过街安全，又需要延长行人过街相位并限制机动车放行。请评估通行效率、学生安全和信号周期资源之间的冲突并协同研判。"

**期望 SSE 事件链**:
```
session_created → run_created → agent_route_done → task_graph_created
→ task_ready CongestionAgent, SignalAgent, PublicSafetyAgent
→ (3 agents execute in parallel)
→ task_ready DispatchAgent → ... → task_succeeded
→ task_ready ConflictDetector → conflict_check_done(3 conflicts, all high)
→ task_ready ConflictArbiter     ← 动态插入
→ task_started ConflictArbiter
→ arbitration_result × 3          ← requiresHumanReview=true
→ task_succeeded ConflictArbiter
→ task_ready FusionAgent → fusion_start → fusion_delta×N → fusion_done → task_succeeded
→ run_completed
```

**期望 final_decision.arbitration**:
```json
{
  "results": [
    {
      "conflict_id": "arb_0",
      "resolved": false,
      "resolution": "高风险冲突需要人工研判",
      "requires_human_review": true,
      "safety_first_rule": "在学生过街安全与机动车通行效率冲突时...",
      "limitations": ["信号配时精确值需现场勘查确认", ...]
    }
  ],
  "totalConflicts": 3,
  "resolvedCount": 0,
  "unresolvedCount": 3
}
```

### 25.3 历史恢复

1. 发送协同分析请求 → 记录 runId
2. 刷新页面
3. 点击侧边栏对应会话
4. 验证：DAG 显示完整 5 层、冲突面板显示仲裁结果、融合决策显示 final_decision
5. `GET /collaboration/runs/{runId}` 返回完整审计记录

### 25.4 侧边栏标签

1. 创建不同类型会话（collaboration / rag / react / routed / hybrid / report）
2. 验证侧边栏 "最近分析" 中每条会话右侧显示对应 Tag（协同 / 知识库 / 诊断 / 研判 / 相似 / 报告）

---

## 26. 已知限制和 Phase 10 建议

### 26.1 已知限制

| 限制 | 说明 | 影响 |
|------|------|------|
| EventBus 仅内存实现 | 单进程内有效，重启丢失 | 不能跨进程/跨服务通信 |
| 无真正并行执行 | 领域 Agent 在 `get_ready_tasks()` 同一批次内串行执行 | 3 个领域 Agent 无法真正并行 |
| ConflictDetector 仅关键词匹配 | 不包含语义理解 | 可能漏检/误检 |
| ConflictArbiter 仅规则引擎 | 不支持 LLM 辅助仲裁 | 复杂冲突缺少深度分析 |
| SQLite 单机存储 | 不支持分布式 | 高并发场景有瓶颈 |
| 无消息队列 | EventBus 不能解耦为异步消息 | Agent 间松耦合受限 |

### 26.2 Phase 10 建议

1. **并行 Agent 执行** — 使用 `asyncio.gather()` 并行执行同层领域 Agent
2. **Redis EventBus** — 替换 InMemoryEventBus 为 Redis Streams
3. **PostgreSQL 迁移** — 替换 SQLite 支持高并发
4. **LLM 辅助仲裁** — ConflictArbiter 在规则不足时调用 LLM 深度分析
5. **信号灯策略模拟** — 对接 SUMO 交通仿真验证配时方案
6. **知识图谱** — 构建交通事件因果推理图谱
7. **消息队列解耦** — 引入 Kafka/RabbitMQ 实现 Agent 间异步通信
8. **Docker 容器化** — Docker Compose 一键部署
9. **API 鉴权** — JWT/OAuth2 保护审计 API
10. **实时大屏** — WebSocket 推送协作运行状态到指挥中心大屏

---

## 附录 A：文件清单

### 新增/修改文件

```
backend/agent/collaboration/
├── __init__.py
├── agents.py              # DispatchAgent / ConflictDetector / ConflictArbiter / FusionAgent
├── budget.py              # ExecutionBudget
├── context_projection.py  # 上下文裁剪（最小权限）
├── db_repository.py       # SQLite 5 表持久化
├── event_bus.py           # 内存 EventBus（幂等、订阅）
├── event_parser.py        # NL → 标准化事件解析
├── executor.py            # Agent 执行适配器（重试、超时、预算）
├── orchestrator.py        # 编排核心（DAG 构建、动态插入、SSE 事件流）
├── protocol.py            # Pydantic 消息协议（AgentMessage 等）
├── repository.py          # 抽象仓库接口
├── roles.py               # Agent 角色能力注册
├── state.py               # CollaborationRunState（11 状态机）
└── task_graph.py          # DAG 任务图（拓扑排序、循环检测）

backend/app.py              # +Phase 9 协作审计 API 端点
backend/tests/test_phase9_multi_run.py  # 61 个专项测试

frontend/src/api/collaborationApi.ts                 # 协作 API（SSE 流式、归一化）
frontend/src/types/collaboration.ts                  # TypeScript 类型定义
frontend/src/components/collaboration/
├── CollaborationDagView.tsx        # DAG 5 层可视化
├── CollaborationRunView.tsx        # 运行总览容器
├── AgentExecutionCard.tsx          # Agent 结果卡片
├── ConflictPanel.tsx               # 冲突 + 仲裁面板
├── BudgetUsagePanel.tsx            # 预算使用面板
└── FusionDecisionView.tsx          # 融合决策视图
frontend/src/components/Sidebar.tsx  # +mode 标签
```

### 文档文件

```
docs/PHASE9_MULTI_AGENT_COLLABORATION.md  # 本文档
```

---

## 附录 B：环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `COLLABORATION_ORCHESTRATOR_ENABLED` | `true` | 启用 Orchestrator 编排 |
| `DEEPSEEK_API_KEY` | — | DeepSeek API Key（可选） |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek API 地址 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 使用模型 |

---

> **文档维护说明**：本文件记录 Phase 9 的完整设计和实现。修改协作核心逻辑后请同步更新此文件。
