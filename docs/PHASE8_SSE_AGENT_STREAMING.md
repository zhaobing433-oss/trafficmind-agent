# Phase 8：SSE 真流式 Agent 执行与统一会话历史

## 1. 阶段目标

Phase 8 的核心目标是将 TrafficMind Agent 从前端伪流式升级为**后端 SSE（Server-Sent Events）真流式**，并将普通问答、知识库问答、事件研判、报告生成、相似案例和协同分析**统一纳入 chat_sessions / chat_messages 会话体系**，实现所有工作区共享一套会话历史中心。

## 2. 核心交付

- `POST /chat/stream` — 通用对话 SSE 流式端点（支持 react/rag/routed/hybrid/report/collaboration）
- `POST /agent/routed_analyze/stream` — 协同分析 SSE 流式端点（动态 Agent 路由 + 冲突检测 + 融合总结）
- `backend/agent/streaming.py` — SSE 事件格式化工具
- `backend/agent/chat_stream.py` — Chat SSE 流式生成器（mode 分发 + DeepSeek stream=true 转发 delta + LLM 标题生成）
- `frontend/src/api/streamApi.ts` — 前端 SSE 消费者（ReadableStream + TextDecoder）
- ChatWorkspace SSE 优先 + REST 降级策略
- 协同分析 SSE 流式执行（agent_start → agent_result → fusion_delta）
- LLM 标题自动生成（首轮 user+assistant 后调用 DeepSeek 生成 8-15 字中文标题）
- 标题锁定机制（只在 title=="新对话" 时生成一次，后续追问不修改，手动重命名后不被覆盖）
- mode 路由严格隔离（只有 collaboration 才输出多 Agent 报告）
- 动态 Agent 路由（根据事件类型/风险等级/周边环境选择参与 Agent）
- 知识库 VS 协同分析进入统一会话历史 + 最近分析 mode 标签
- SSE 中文不乱码（ensure_ascii=False + UTF-8）
- 测试演进：61 → 70 → 79 → 83 passed

## 3. 新增接口说明

### POST /chat/stream

通用对话 SSE 流式端点，支持所有分析模式。

**请求体**：

```json
{
  "sessionId": "可选，首条消息为空",
  "content": "用户问题",
  "mode": "react | rag | routed | hybrid | report | collaboration"
}
```

**SSE 事件序列**：

| 事件 | 说明 | data 示例 |
|------|------|-----------|
| `session_created` | 首条消息自动创建 session | `{"sessionId":"sess_xxx"}` |
| `message_saved` | 用户消息已保存 | `{"userMessageId":"msg_xxx"}` |
| `step` | 中间步骤状态 | `{"stage":"retrieval","text":"正在检索交通知识库..."}` |
| `evidence` | RAG 检索证据 | `{"items":[...]}` |
| `delta` | LLM 生成文本片段 | `{"text":"根据检索到的交通处置经验，"}` |
| `done` | 对话完成 | `{"sessionId":"sess_xxx","assistantMessageId":"msg_xxx","title":"雨天拥堵处置原则","titleUpdated":true}` |
| `error` | 错误 | `{"message":"错误说明"}` |

**mode 路由**：

| mode | 行为 |
|------|------|
| `react` | 受控 ReAct 诊断 — 不输出多 Agent 报告 |
| `rag` | RAG 知识库检索 + LLM/模板生成回答 |
| `routed` | 结构化事件研判（风险评分+规则+调度话术） |
| `hybrid` | 混合相似度案例检索 |
| `report` | 日报/周报生成 |
| `collaboration` | 多 Agent 协同分析（只有此 mode 输出 Agent 报告） |

### POST /agent/routed_analyze/stream

多 Agent 协同分析 SSE 流式端点。

**请求体**：

```json
{
  "sessionId": "可选",
  "eventType": "congestion",
  "roadName": "人民路-解放路路口",
  "direction": "东向西",
  "avgSpeed": 8.0,
  "queueLength": 300,
  "duration": 900,
  "weather": "rain",
  "timePeriod": "morning_peak",
  "isMainRoad": true,
  "nearbyHospital": true
}
```

**SSE 事件序列**：

| 事件 | 说明 |
|------|------|
| `session_created` | 自动创建 collaboration session |
| `event_parse_start` | 开始解析事件信息 |
| `event_parse_done` | 事件解析完成 |
| `agent_route_done` | 返回选中的 Agent 和路由原因 |
| `agent_start` | 某个 Agent 开始分析 |
| `agent_result` | Agent 分析结果（findings/urgency/suggestion） |
| `conflict_check_start` | 开始冲突检测 |
| `conflict_check_done` | 返回检测到的冲突 |
| `fusion_start` | 开始融合总结 |
| `fusion_delta` | 融合总结文本片段 |
| `fusion_done` | 融合总结完成 |
| `done` | 全部完成 |

## 4. Chat 流式链路

```
用户发送问题
  → flushSync 立即渲染 user message + assistant skeleton
  → rAF 让浏览器绘制
  → 如果 sessionId 为空: POST /chat/sessions 创建 session
  → 保存 user message (chat_messages)
  → 根据 mode 分发:
      rag:    意图识别 → 语义检索 → docType加权 → rerank → evidence → LLM delta
      react:  受控ReAct诊断 → delta
      routed: 事件风险研判 → 规则匹配 → 调度话术 → delta
      hybrid: 相似度计算 → delta
      report: 日报生成 → delta
      collaboration: → /agent/routed_analyze/stream
  → LLM stream=true delta 逐 token 转发前端
  → 保存 assistant message
  → 首轮: LLM 生成标题 (8-15字中文)
  → done event 返回 title/titleUpdated
  → 前端刷新最近分析
```

## 5. 协同分析流式链路

```
用户输入交通事件
  → 创建或复用 collaboration session
  → 保存 user message
  → 解析事件信息 → event_parse_start/done
  → 动态路由 Agent (route_agents):
      普通 congestion: CongestionAgent + SignalAgent + DispatchAgent + ReportAgent
      含医院/学校: + PublicSafetyAgent
      signal_abnormal: SignalAgent + DispatchAgent + ReportAgent
      accident: AccidentAgent + PublicSafetyAgent + DispatchAgent + ReportAgent
  → 依次 agent_start / agent_result
  → 冲突检测 → conflict_check_start/done
  → 融合总结 fusion_delta 流式输出
  → 保存 assistant message + agentResults/routingReasons/fusionSummary metadata
  → done 返回 sessionId / title / agentResults
```

注意：**不是所有 Agent 每次都参与**，由 `route_agents(info)` 根据事件类型、风险等级、道路环境、关键词和上下文动态选择。

## 6. mode 路由设计

| mode | 名称 | 输入框标签 | 最近分析标签 |
|------|------|-----------|-------------|
| `react` | 智能诊断 | 🤖 智能诊断 | [诊断] |
| `rag` | 知识库问答 | 📖 知识问答 | [知识库] |
| `routed` | 事件研判 | 🔍 事件研判 | [研判] |
| `hybrid` | 相似案例 | 📊 相似案例 | [相似] |
| `report` | 报告生成 | 📋 报告生成 | [报告] |
| `collaboration` | 协同分析 | 🤝 协同分析 | [协同] |

**严格隔离**：只有 `collaboration` mode 才输出多 Agent 协同分析报告。`react`/`routed`/`rag`/`hybrid`/`report` 不会误输出多 Agent 报告。

## 7. 统一会话历史设计

所有工作区（首页对话、知识库、事件研判、相似案例、统计报告、协同分析）的输出都写入统一的两张表：

- `chat_sessions` — 会话元信息（id/title/mode/summary/created_at/updated_at）
- `chat_messages` — 消息记录（id/session_id/role/content/mode/result_summary/created_at）

最近分析不再只是普通聊天历史，而是**多工作区统一任务历史中心**。

## 8. 标题生成机制

1. session 创建时临时 title = "新对话"
2. 第一轮 user + assistant 完成后调用 LLM 生成标题
3. LLM prompt：`"请根据用户问题和助手回答，生成一个 8 到 15 个中文字符的简洁标题。只输出标题，不要标点，不要解释，不要引号。"`
4. LLM 不可用时规则降级（关键词提取：学校/医院/拥堵/事故/信号/匝道/高峰/风险）
5. **只在 title == "新对话" 时自动生成**
6. 后续追问不修改标题
7. 用户手动 PATCH `/chat/sessions/{id}/title` 重命名后，永远不被自动覆盖

## 9. SSE 降级策略

当前端调用 SSE 接口失败、返回 error event 或前端解析失败时，会自动降级到同一后端中的非流式 REST 接口。**该降级要求后端服务仍然可用**；如果后端完全停止，SSE 和 REST 都不可用。

前端实现：`doSubmit` 中先 `try { await streamChat(...) }`，catch 后 fallback 到 `chatApi.sendMessage(...)`。

## 10. 关键问题修复记录

| 问题 | 根因 | 修复 |
|------|------|------|
| 首条消息卡顿 | `key={activeSessionId}` 导致组件卸载重建 | 引入稳定 `workspaceKey`，sessionId 变化不触发 remount |
| 新对话回答中途消失 | `useEffect([sessionId])` 中 getSession 覆盖 streaming messages | 增加 `if streaming return` 保护 |
| 标题后续追问被修改 | 每次 message 都调 update_session_title | 只在 title=="新对话" 时设置一次 |
| 智能诊断输出多 Agent 报告 | `mode=routed` 调了 multi_agent_analyze | 拆分 mode：react/routed 各自独立处理 |
| 知识库/协同分析不进入最近分析 | onSessionCreated 回调忽略 sessionId | 后端 SSE done 返回 sessionId + title；前端正确追踪 |
| 协同分析固定全部 Agent | 硬编码 agents_order | 改用 route_agents(info) 动态选择 |
| 最近分析恢复后 mode 变成 react | handleRecentClick 写死 view='home' | 根据 session.mode 路由到对应工作区视图 |

## 11. 测试结果

| 阶段 | 测试数 |
|------|--------|
| Phase 6 | 50 passed |
| Phase 7 | 61 passed |
| Phase 8.2 | 70 passed |
| Phase 8.4 | 83 passed / 0 failed |

新增测试覆盖：

- 首轮 LLM 标题生成（title 不是 "新对话"）
- 追问不改标题
- 手动 PATCH 重命名不覆盖
- rag session 统一化写入 chat_sessions
- collaboration session 统一化写入 chat_sessions
- collaboration 结果写入 chat_messages
- 动态 Agent 路由（普通拥堵不触发全部 Agent）
- nearbyHospital 触发 PublicSafetyAgent
- 追问不创建新 session
- collaboration 追问 mode 保持
- rag 追问 mode 保持
- mode 标签映射
- SSE 中文不乱码

## 12. 启动与手工验收

### 启动

```powershell
# 终端 1：后端
cd C:\Users\25442\trafficmind-agent
backend\.venv\Scripts\python -m uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000

# 终端 2：前端
cd C:\Users\25442\trafficmind-agent\frontend
npm run dev
```

浏览器打开 `http://localhost:5173`（或终端提示的其他端口）。

### 验收项

- [ ] 新对话发首条消息，消息不消失，完整流式展示
- [ ] Network 看到 `/chat/stream`（Content-Type: text/event-stream）
- [ ] 知识库发问题 → 最近分析新增 [知识库] 会话
- [ ] 协同分析启动 → 最近分析新增 [协同] 会话
- [ ] 协同分析 Network 看到 `/agent/routed_analyze/stream`
- [ ] 标题是 LLM 总结（如"学校周边拥堵分析"），不是"新对话"
- [ ] 追问后标题不变
- [ ] PATCH 重命名后追问不覆盖
- [ ] 点击 [协同] 最近分析 → 进入协同分析视图，追问 mode 仍是 collaboration
- [ ] 点击 [知识库] 最近分析 → 进入知识库视图，追问 mode 仍是 rag
- [ ] 普通拥堵协同分析不触发全部 Agent，nearbyHospital 时才触发 PublicSafetyAgent

## 13. 已知限制与 Phase 9 建议

- 协同分析历史恢复后，结构化 Agent 卡片展示可继续增强（目前解析 agentResults/findings 在消息气泡中展示）。
- 从最近分析恢复不同 mode 会话后的工作区切换和追问模式保持已基本完成，边缘 case 可在 Phase 9 继续打磨。
- 当前 SSE 已支持 step/delta/agent_result/fusion_delta，DeepSeek 的 `stream=true` token streaming 已接入；其他 LLM provider 的兼容性可继续增强。
- **Phase 9 建议方向**：评测体系搭建、审计追踪与运行日志、部署交付与运维文档、结构化 Agent 卡片恢复增强。
