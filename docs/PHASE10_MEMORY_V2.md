# Phase 10 Memory V2 — 结构化 Session Memory

## 1. 背景和目标

将多轮交通研判转化为**可追踪、可纠正、可过期、按事件线程隔离、并按 Agent 最小权限注入**的结构化 Session Memory。

Phase 10 是 TrafficMind Agent 的记忆基础设施层，为后续跨 Session 长期记忆和用户画像提供基础。

## 2. Phase 10 范围

**已完成：**
- MemoryItem / MemoryTrace 数据模型
- SQLite 持久化 + 抽象 MemoryStore 接口 (PostgreSQL 预留)
- UTC 时间统一、TTL 过期、dedupKey 幂等
- MemoryExtractor (确定性规则抽取)
- MemoryWriteGate (来源权限 + authority 冲突)
- ConflictResolver + User Correction (Supersede 链)
- Event Thread (Session 内多事件隔离)
- Recall Decision (6 种 intent 分类)
- Recall Plan / Retriever / Reranker / Injector
- Per-Agent 白名单注入
- Memory Trace 完整追踪
- 后端 Memory API (4 个端点)
- 前端 MemoryTracePanel (4 Tab)
- SSE 事件 (8 种 Memory 事件)
- 历史 Run 水合 (含旧 Run 兼容)

**不在本阶段范围：**
- 跨 Session 长期语义 Memory
- 用户画像
- PostgreSQL
- Redis
- Task Resume
- 多租户 / RBAC
- 人工编辑 Memory
- LLM 自动修改 Memory

## 3. 五层 Memory 架构

```
Layer 1: Models    — MemoryItem, MemoryTrace, EventThread, RecallDecision
Layer 2: Store     — MemoryStore (ABC) → SQLiteMemoryRepository
Layer 3: Write     — Extractor → WriteGate → ConflictResolver → Coordinator
Layer 4: Recall    — Classifier → Planner → Retriever → Reranker → Injector
Layer 5: Observe   — SSE Events, Memory API, MemoryTracePanel, Trace Merge
```

## 4. MemoryItem 数据模型

21 个字段：id, memoryType, scopeType, sessionId, memoryKey, value, textContent, status, confidence, authorityLevel, sourceType, sourceId, sourceRunId, sourceMessageId, validFrom, validUntil, supersedesId, dedupKey, eventThreadId, createdAt, updatedAt, lastAccessedAt, accessCount

9 种 memoryType：session_goal, stable_fact, constraint, confirmed_decision, unresolved_issue, user_correction, run_summary, proposal, temporary_fact

6 种 status：candidate, active, confirmed, rejected, superseded, expired

7 种 sourceType：user_explicit, user_correction, event_parser, agent_proposal, agent_fusion, human_review, system_rule

## 5. MemoryStore 抽象和 SQLite 实现

`repository.py` 定义 MemoryStore ABC（19 个抽象方法 + transaction() 上下文管理器）。

`sqlite_repository.py` 实现完整 SQLite 后端，包含 Event Thread 管理和 merge_trace。

`factory.py` 提供 `create_memory_repository()` 读取 `MEMORY_STORAGE_BACKEND` 环境变量。

## 6. PostgreSQL 可迁移设计

- 业务代码依赖 MemoryStore 接口，不 import sqlite3
- Factory 已预留 PostgreSQL 分支（当前抛出 NotImplementedError）
- JSON 编解码仅在 Repository 边界
- 无 INSERT OR REPLACE / REPLACE INTO
- PRAGMA 仅用于连接初始化
- `MEMORY_DATABASE_URL` 配置项已预留

## 7. UTC 和 TTL

- `time_utils.py`: utc_now(), to_iso_utc(), parse_iso_datetime(), is_expired()
- 所有新写入时间带 +00:00 offset
- `_normalize_timestamp` 在写入时自动转换旧格式
- TTL 比较统一为 UTC 字符串比较
- 9 个动态字段黑名单（DYNAMIC_FIELD_BLOCKLIST）

## 8. dedupKey

SHA-256(sessionId|memoryType|memoryKey|canonicalJSON|sourceRunId|sourceMessageId)

canonical JSON: sort_keys=True, ensure_ascii=False, compact separators

相同 dedupKey 的 create_item 返回已有记录，不产生重复。

## 9. Repository 事务

- `repo.transaction()` 上下文管理器
- 线程局部连接注册表
- `_tx_safe_commit` / `_tx_safe_close` 在事务内安全跳过
- 用户纠正 4 步原子性（supersede + create + audit + trace）
- 嵌套事务检测 → RuntimeError

## 10. MemoryExtractor

9 种抽取规则，全部确定性（可选 LLM 增强预留）：

| 抽取类型 | 触发条件 | memoryKey 规范 |
|---------|---------|---------------|
| session_goal | 首轮或明确切换目标 | goal.primary |
| stable_fact | STABLE_FIELD_WHITELIST (7 字段) | road.name, school.nearby, ... |
| constraint | 10 个约束关键词 | constraint.{subject} |
| proposal | Agent 结果 (suggestion) | proposal.{agent}.{runId} |
| confirmed_decision | 8 个确认关键词 | decision.confirmed.{runId} |
| user_correction | 6 个纠正正则 | correction.{field} |
| unresolved_issue | requiresHumanReview / 未解决冲突 | unresolved.{runId}.{n} |
| run_summary | completed / partial_success | run.summary.{runId} |
| temporary_fact | 4 种 TTL 模式 | temporary.{runId}.restriction |

## 11. Write Gate

GateDecision：create / deduplicated / supersede / confirm / reject / expire / no_op

来源权限规则：
- user_explicit → stable_fact, constraint, session_goal
- user_correction → 任何类型 (supersede)
- event_parser → stable_fact (confidence < 0.3 拒绝)
- agent_proposal → proposal (candidate only, 不能 confirmed)
- agent_fusion → run_summary, proposal, unresolved_issue 仅此 3 种
- human_review → 任何类型含 confirmed_decision

## 12. Proposal 与 Confirmed Decision

- Agent 建议只能成为 proposal (status=candidate)
- FusionAgent 输出不能自动成为 confirmed_decision
- 只有用户明确确认才能创建 confirmed_decision
- 多 proposal 下模糊引用 → rejected (ambiguous_proposal_reference)
- 精确引用（含 Agent 名称）→ confirmedProposalId + proposalSourceRunId

## 13. Correction 与 Supersede

识别 6 种纠正正则模式。原子事务：
1. 查询 active 旧事实
2. supersede 旧值
3. 创建 active 新值
4. 创建 user_correction 审计记录
5. 保存 MemoryTrace

## 14. Event Thread

2 张新表：memory_event_threads + memory_session_states

Thread 生命周期：
- 首轮自动创建
- continue/correction/decision_query 沿用当前
- fresh_event 关闭旧 + 创建新
- 同 Session 只有 1 个 active Thread
- 历史 Thread 事实标记 historical_reference=true

## 15. Recall Decision

6 种 intent，确定性优先级：
correction > fresh_event > previous_decision_query > memory_query > ambiguous

Entity conflict 检测：当前 roadName 不在当前 Thread title 中 → fresh_event 倾向

## 16. Recall Plan

按 intent 构建查询计划：
- fresh_event → 0 items
- continue_event → 6 types + run_summaries
- correction → 3 types + targeted keys
- previous_decision_query → 3 types + proposals
- memory_query → run_summaries + historical threads
- ambiguous → 0 items

## 17. 过滤与排序

12 种过滤规则：cross_session, wrong_event_thread, rejected, superseded, expired, invalid_ttl, dynamic_field_blocked, legacy_unscoped_memory, current_input_override, proposal_not_confirmed, intent_not_allowed, token_budget_exceeded

排序公式：scopeMatch(0.25) + authority(0.25) + relevance(0.20) + freshness(0.15) + taskFit(0.15)

## 18. Token 预算

- maxItems 限制选中数量
- maxTokenEstimate 指导召回计划
- 超预算项目记录 token_budget_exceeded
- selected 截断到 maxItems

## 19. currentEvent / routingContext / agentContext 隔离

三个不可变对象：
- currentEvent：仅当前消息解析结果，Memory 不修改
- routingContext：安全稳定字段从 Memory 补充，source=memory_session
- agentContext：按 Agent 筛选的子集

禁止：currentEvent.update(memoryContext)
禁止：{**oldMemory, **currentEvent}

## 20. Agent 白名单注入

| Agent | 允许类型 |
|-------|---------|
| CongestionAgent | session_goal, stable_fact, constraint, confirmed_decision |
| SignalAgent | + user_correction |
| PublicSafetyAgent | + user_correction, unresolved_issue |
| DispatchAgent | + unresolved_issue |
| ConflictDetector | 空（不需要历史记忆） |
| ConflictArbiter | constraint, confirmed_decision |
| FusionAgent | provenance, proposals, confirmed_decision, unresolved_issue |

## 21. Memory Trace

每 Run 一条 memory_traces 记录。merge_trace 支持 recall/write 两个 phase 增量写入，保留已有字段。

## 22. SSE 事件

8 种 Memory SSE 事件：
memory_recall_started → memory_recall_completed → memory_injection_ready
→ memory_write_started → memory_write_completed
(memory_recall_failed / memory_write_failed 在失败时)

## 23. 后端 API

| 端点 | 说明 |
|------|------|
| GET /memory/sessions/{id} | Session 结构化 Memory 视图 |
| GET /memory/runs/{id}/trace | Run Memory Trace (hasTrace 语义) |
| GET /memory/items/{id} | 单条 Memory + 来源链 |
| GET /memory/sessions/{id}/threads | Event Thread 列表 |

## 24. 前端面板

MemoryTracePanel：4 Tab（召回记忆 / 按Agent注入 / 写入结果 / 过滤与拒绝）

集成到 CollaborationRunView。

## 25. 历史水合

- 旧 Phase 9 Run → hasTrace=false + 中文提示
- 最新 Run 默认加载 Trace
- 切换 Session 清理缓存
- 快速切换 Run 防异步串写

## 26. Session 删除级联

DELETE /chat/sessions/{id} 清理 13 张表（同一事务）：
1. chat_sessions, 2. chat_messages, 3. chat_memory_summaries, 4. rag_evidence_logs,
5. collaboration_runs, 6. collaboration_tasks, 7. collaboration_messages,
8. collaboration_conflicts, 9. collaboration_events,
10. memory_items, 11. memory_traces,
12. memory_event_threads, 13. memory_session_states

任一步骤异常 → 全部 rollback。其他 Session 不受影响。

## 27. 五个真实验收场景

1. 稳定事实召回 + 动态字段拒绝
2. 用户纠正 (Supersede 链)
3. 新事件线程 (Fresh Event → 新 Thread)
4. Proposal 确认 (模糊拒绝 + 精确确认)
5. 跨 Session 隔离

## 28. 测试矩阵

| 套件 | 数量 | 说明 |
|------|------|------|
| test_phase10_memory_store | 87 | 数据模型 + 存储 + Trace Merge + API |
| test_phase10_memory_write | 41 | 抽取 + Gate + Correction |
| test_phase10_memory_recall | 58 | Intent + Thread + Filter + Inject |
| Phase 1-9 | 283 | 完整回归 |
| **总计** | **470** | **全部通过** |
| TypeScript | 0 errors | 类型安全 |

## 29. 已知限制

- 跨 Session 长期语义 Memory：未实现
- 用户画像：未实现
- PostgreSQL：未实现 (Phase 11)
- Redis 缓存：未实现
- Task Resume：未实现
- 多租户 / RBAC：未实现
- 人工编辑 Memory：未实现
- LLM 自动修改 Memory：未实现
- 前端 SessionMemoryPanel：预留（仅 MemoryTracePanel 已实现）

## 30. Phase 11 规划

- PostgreSQL 后端实现
- 跨 Session 长期语义 Memory
- 用户画像和偏好学习
- Memory 人工审核和编辑
- LLM 辅助记忆修正和冲突仲裁
- 前端 Session Memory 概览面板
