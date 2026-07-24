# TrafficMind Agent API 示例文档

## 启动服务

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate    # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

启动后访问：
- API 文档（Swagger）：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

---

## 1. POST /analyze_event — 分析交通事件

### 请求示例

```bash
curl -X POST http://localhost:8000/analyze_event \
  -H "Content-Type: application/json" \
  -d '{
    "eventId": "E202606290001",
    "eventType": "congestion",
    "cameraId": "CAM_001",
    "roadName": "人民路-解放路路口",
    "direction": "东向西",
    "lane": "直行车道",
    "avgSpeed": 8.5,
    "queueLength": 180,
    "duration": 601,
    "vehicleCount": 96,
    "weather": "rain",
    "timePeriod": "morning_peak",
    "isMainRoad": true,
    "nearbySchool": false,
    "nearbyHospital": true,
    "confidence": 0.91
  }'
```

### 成功响应示例

```json
{
  "eventId": "E202606290001",
  "standardEvent": {
    "eventId": "E202606290001",
    "eventType": "congestion",
    "eventTypeCn": "拥堵",
    "cameraId": "CAM_001",
    "roadName": "人民路-解放路路口",
    "direction": "东向西",
    "lane": "直行车道",
    "avgSpeed": 8.5,
    "queueLength": 180.0,
    "duration": 601.0,
    "vehicleCount": 96,
    "confidence": 0.91,
    "weather": "rain",
    "timePeriod": "morning_peak",
    "isMainRoad": true,
    "nearbySchool": false,
    "nearbyHospital": true
  },
  "riskScore": 100,
  "riskLevel": "重大风险",
  "riskReasons": [
    "事件类型为「拥堵」，基础风险分 +20",
    "平均车速 8.5 km/h < 10 km/h，严重缓行，+15",
    "排队长度 180.0 米 > 150 米，拥堵范围大，+15",
    "持续 601 秒 > 600 秒，事件未快速消散，+10",
    "天气为雨，影响通行安全，+10",
    "当前为早高峰时段，交通压力大，+10",
    "事发路段为主干道，影响范围广，+10",
    "事发路段邻近医院，需保障急救通道，+10"
  ],
  "matchedRule": "**拥堵事件处置预案**\n### 判断条件\n...",
  "suggestions": [
    "通知交警大队，人民路-解放路路口东向西方向发生拥堵事件，请立即派员前往现场处置。",
    "通知辖区交警大队派员前往现场疏导。",
    "若为主干道拥堵，协调上游路口信号灯临时调整配时，加大绿信比。",
    "建议在人民路-解放路路口上游路口实施分流，引导车辆绕行，缓解排队压力。",
    "建议通过交通广播、诱导屏发布实时路况信息，告知驾驶员提前绕行。",
    "做好事件处置记录，拍照留存，处置完成后及时反馈指挥中心。"
  ],
  "dispatchMessage": "【调度指令】\n事件编号：E202606290001\n...",
  "publicMessage": "【注意】人民路-解放路路口东向西方向通行缓慢，请过往车辆提前绕行。",
  "report": "==================================================\n...",
  "status": "待派单",
  "saved": true,
  "analyzedAt": "2026-06-29 12:00:00"
}
```

### 错误响应示例（缺少字段）

```json
{
  "detail": "缺少核心字段: eventType, avgSpeed, queueLength, duration"
}
```

---

## 2. GET /history — 查询历史记录

### 请求示例

```bash
curl -X GET "http://localhost:8000/history?limit=10"
```

### 响应示例

```json
{
  "total": 1,
  "records": [
    {
      "eventId": "E202606290001",
      "eventType": "congestion",
      "eventTypeCn": "拥堵",
      "roadName": "人民路-解放路路口",
      "riskScore": 100,
      "riskLevel": "重大风险",
      "status": "处置中",
      "createdAt": "2026-06-29 12:00:00",
      "updatedAt": "2026-06-29 12:05:00"
    }
  ]
}
```

---

## 3. GET /event/{event_id} — 查询单条事件详情

### 请求示例

```bash
curl -X GET http://localhost:8000/event/E202606290001
```

### 响应示例

返回完整的分析记录，包括 `rawEvent`、`fullResult` 等全部字段。

### 错误响应

```json
{
  "detail": "事件 E999999999999 不存在"
}
```

---

## 4. POST /event/{event_id}/status — 更新事件状态

### 请求示例

```bash
# 更新为"处置中"
curl -X POST http://localhost:8000/event/E202606290001/status \
  -H "Content-Type: application/json" \
  -d '{"status": "处置中"}'

# 更新为"已处置"
curl -X POST http://localhost:8000/event/E202606290001/status \
  -H "Content-Type: application/json" \
  -d '{"status": "已处置"}'

# 更新为"已归档"
curl -X POST http://localhost:8000/event/E202606290001/status \
  -H "Content-Type: application/json" \
  -d '{"status": "已归档"}'
```

### 有效状态值

| 状态 | 含义 |
|------|------|
| 待研判 | 事件已接收，等待系统分析 |
| 待派单 | 分析完毕，等待下发处置 |
| 处置中 | 已派单，正在现场处置 |
| 已处置 | 现场处置完毕 |
| 待复盘 | 等待事后复盘分析 |
| 已归档 | 已复盘，归档保存 |

### 响应示例

```json
{
  "eventId": "E202606290001",
  "status": "处置中",
  "message": "事件状态已更新为「处置中」"
}
```

---

## 完整生命周期测试流程

```bash
# 1. 分析一个新事件
curl -X POST http://localhost:8000/analyze_event \
  -H "Content-Type: application/json" \
  -d @- << 'EOF'
{
  "eventId": "E202606290002",
  "eventType": "accident",
  "cameraId": "CAM_005",
  "roadName": "中山路-南京路路口",
  "direction": "南向北",
  "lane": "左转车道",
  "avgSpeed": 2.0,
  "queueLength": 320,
  "duration": 900,
  "vehicleCount": 45,
  "weather": "fog",
  "timePeriod": "evening_peak",
  "isMainRoad": true,
  "nearbySchool": true,
  "nearbyHospital": false,
  "confidence": 0.88
}
EOF

# 2. 查看历史
curl http://localhost:8000/history

# 3. 查看详情
curl http://localhost:8000/event/E202606290002

# 4. 更新状态
curl -X POST http://localhost:8000/event/E202606290002/status \
  -H "Content-Type: application/json" \
  -d '{"status": "处置中"}'

# 5. 再次查看——状态已变
curl http://localhost:8000/event/E202606290002
```

---

## 第二阶段新增接口

### 5. GET /similar_cases/{event_id} — 历史相似案例检索

基于规则相似度（9 维特征匹配）检索历史相似案例。第一阶段使用规则相似度；第三阶段计划引入 Chroma/FAISS 做语义检索和 RAG。

```bash
# 查找与 E202606290002 相似的历史案例
curl "http://localhost:8000/similar_cases/E202606290002?limit=5&min_score=0.3"
```

**响应示例：**

```json
{
  "currentEvent": {
    "eventId": "E202606290002",
    "eventType": "事故",
    "roadName": "中山路-南京路路口",
    "direction": "南向北",
    "riskScore": 100,
    "riskLevel": "重大风险",
    "status": "待派单",
    "createdAt": "2026-06-30 14:30:00"
  },
  "similarCases": [
    {
      "eventId": "E202606300005",
      "eventType": "事故",
      "roadName": "人民路-解放路路口",
      "direction": "东向西",
      "riskScore": 95,
      "riskLevel": "重大风险",
      "status": "待派单",
      "similarityScore": 0.65,
      "similarityReasons": [
        "事件类型相同：事故",
        "天气状况相同：雨",
        "均发生在早高峰"
      ],
      "report": "前半部分报告内容...",
      "createdAt": "2026-06-30 15:00:00"
    }
  ]
}
```

### 6. GET /reports/daily — 交通事件日报

生成某一天的交通事件日报，包含总体概况、高风险事件、高发路口、类型分布、状态分析、未闭环提醒、管理建议。

```bash
# 生成今天的日报
curl http://localhost:8000/reports/daily

# 指定日期
curl "http://localhost:8000/reports/daily?date=2026-06-30"
```

**响应示例：**

```json
{
  "date": "2026-06-30",
  "totalEvents": 9,
  "highRiskEvents": 6,
  "majorRiskEvents": 3,
  "unclosedEvents": 9,
  "topRoads": [
    { "roadName": "人民路-解放路路口", "count": 5 },
    { "roadName": "中山路-南京路路口", "count": 3 }
  ],
  "eventTypeDistribution": [
    { "type": "拥堵", "count": 4 },
    { "type": "事故", "count": 3 }
  ],
  "riskLevelDistribution": [
    { "level": "重大风险", "count": 3 },
    { "level": "高风险", "count": 3 }
  ],
  "statusDistribution": [
    { "status": "待派单", "count": 9 }
  ],
  "keyFindings": [
    "报告期内共发生 6 起高风险及以上事件，需重点关注。",
    "其中 3 起为重大风险事件，建议立即核查处置进度。"
  ],
  "suggestions": [
    "对高风险事件涉及的信号配时、道路设施进行专项排查。",
    "督促未闭环事件责任单位加快处置进度，确保按时归档。"
  ],
  "reportText": "==================================================\n   TrafficMind Agent 交通事件日报\n   ... (完整报告全文)",
  "trendSummary": "2026-06-30 共发生 9 起交通事件"
}
```

### 7. GET /reports/weekly — 交通事件周报

生成最近 7 天的交通事件周报，包含日趋势、汇总统计和管理建议。

```bash
# 生成最近 7 天周报
curl http://localhost:8000/reports/weekly

# 指定日期范围
curl "http://localhost:8000/reports/weekly?start_date=2026-06-01&end_date=2026-06-30"
```

**响应示例：**

```json
{
  "startDate": "2026-06-23",
  "endDate": "2026-06-30",
  "totalEvents": 9,
  "highRiskEvents": 6,
  "majorRiskEvents": 3,
  "unclosedEvents": 9,
  "topRoads": [
    { "roadName": "人民路-解放路路口", "count": 5 }
  ],
  "eventTypeDistribution": [{ "type": "拥堵", "count": 4 }],
  "riskLevelDistribution": [{ "level": "重大风险", "count": 3 }],
  "statusDistribution": [{ "status": "待派单", "count": 9 }],
  "keyFindings": [
    "报告期内共发生 6 起高风险及以上事件，需重点关注。"
  ],
  "suggestions": [
    "对高风险事件涉及的信号配时、道路设施进行专项排查。"
  ],
  "reportText": "==================================================\n   TrafficMind Agent 交通事件周报\n   ... (完整报告全文)",
  "trendSummary": [
    { "date": "2026-06-30", "count": 9 }
  ]
}
```

### 8. GET /alerts/unclosed — 未闭环事件提醒

查询未完成闭环处置的事件，自动生成提醒原因和处置建议。

提醒规则：
- 高风险/重大风险且状态为待派单或处置中：优先提醒
- 事件超过 30 分钟仍未闭环：提醒
- 重大风险事件超过 10 分钟未闭环：强提醒
- 待复盘事件超过 24 小时未归档：提醒

```bash
# 查询最近 24 小时未闭环事件
curl "http://localhost:8000/alerts/unclosed?hours=24&min_risk=%E4%B8%AD%E9%A3%8E%E9%99%A9"

# 查询所有未闭环（放宽时间到 720 小时）
curl "http://localhost:8000/alerts/unclosed?hours=720&min_risk=%E4%BD%8E%E9%A3%8E%E9%99%A9"
```

**响应示例：**

```json
{
  "count": 3,
  "alerts": [
    {
      "eventId": "E202606300004",
      "eventType": "事故",
      "roadName": "中山路-南京路路口",
      "direction": "南向北",
      "riskLevel": "重大风险",
      "riskScore": 100,
      "status": "待派单",
      "createdAt": "2026-06-30 14:30:00",
      "durationSinceCreated": "3 小时 37 分钟",
      "alertReason": "重大风险事件已持续 217 分钟未闭环，需要紧急介入！；重大风险事件尚未派单（100分），请优先关注。",
      "recommendedAction": "立即启动应急预案，通知相关单位负责人，优先调配资源处置。"
    }
  ]
}
```

### 9. GET /stats/high_risk_roads — 高风险路口 TopN 统计

按路口聚合统计高风险事件，自动生成管理建议。

统计逻辑：
- 按 roadName 聚合最近 N 天的事件
- 高风险和重大风险事件计入重点统计
- suggestedAction 根据风险情况自动生成

```bash
# 最近 7 天高风险路口 Top10
curl "http://localhost:8000/stats/high_risk_roads?limit=10&days=7&min_risk=%E9%AB%98%E9%A3%8E%E9%99%A9"

# 最近 30 天所有风险等级路口统计
curl "http://localhost:8000/stats/high_risk_roads?limit=5&days=30&min_risk=%E4%BD%8E%E9%A3%8E%E9%99%A9"
```

**响应示例：**

```json
{
  "range": "最近 30 天",
  "topRoads": [
    {
      "roadName": "人民路-解放路路口",
      "totalEvents": 5,
      "highRiskCount": 2,
      "majorRiskCount": 3,
      "avgRiskScore": 88.0,
      "mostCommonEventType": "拥堵",
      "unclosedCount": 5,
      "suggestedAction": "建议纳入重点巡查路口，优先安排交警值守。；建议复核信号配时方案，排查交通组织隐患。；仍有 5 起事件未闭环，请跟踪处置。"
    },
    {
      "roadName": "中山路-南京路路口",
      "totalEvents": 3,
      "highRiskCount": 1,
      "majorRiskCount": 1,
      "avgRiskScore": 73.3,
      "mostCommonEventType": "拥堵",
      "unclosedCount": 3,
      "suggestedAction": "建议纳入重点巡查路口，优先安排交警值守。；仍有 3 起事件未闭环，请跟踪处置。"
    }
  ]
}
```

---

## Phase 9 新增 API

### 10. POST /agent/routed_analyze/stream — 多 Agent 协同分析 SSE 流式

使用自然语言描述交通事件，系统自动解析、路由 Agent、构建 DAG、执行协同分析，SSE 实时推送全生命周期事件。

```bash
# 普通拥堵协同分析
curl -X POST http://localhost:8000/agent/routed_analyze/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "content": "主干道平均车速8km/h，排队400米，请协同研判。",
    "contextPolicy": "fresh_event"
  }'

# 学校冲突协同分析（第二/三轮追加 sessionId 和 contextPolicy）
curl -X POST http://localhost:8000/agent/routed_analyze/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "content": "人民路小学门口早高峰严重拥堵，机动车需绿灯，学生需过街相位。",
    "contextPolicy": "fresh_event",
    "sessionId": "sess_20260724..."
  }'

# 继续上一轮研判
curl -X POST http://localhost:8000/agent/routed_analyze/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "content": "继续上述分析，考虑增加公交优先策略。",
    "contextPolicy": "continue_event",
    "sessionId": "sess_20260724..."
  }'
```

**SSE 事件流示例：**

```
data: {"eventType":"session_created","sessionId":"sess_20260724..."}

data: {"eventType":"run_created","runId":"run_1710000000000","sessionId":"sess_...","userQuery":"...","contextPolicy":"fresh_event","fieldSources":{"avgSpeed":"current_message","queueLength":"current_message",...},"selectedAgents":["CongestionAgent","SignalAgent","PublicSafetyAgent"]}

data: {"eventType":"agent_route_done","selectedAgents":["CongestionAgent","SignalAgent","PublicSafetyAgent","DispatchAgent","ConflictDetector","FusionAgent"],"routingReasons":["学校周边触发公共安全Agent","拥堵触发CongestionAgent"]}

data: {"eventType":"task_graph_created","tasks":[...]}

data: {"eventType":"task_ready","taskId":"task_0_CongestionAgent",...}

data: {"eventType":"task_started","taskId":"task_0_CongestionAgent","agentName":"CongestionAgent",...}

data: {"eventType":"agent_result","agentName":"CongestionAgent","result":{"findings":["平均车速仅 8.0 km/h，严重拥堵"，"排队 400m，建议上游分流"],"urgency":"high","recommendation":"通知交警+信号中心，上游分流","confidence":0.7,...}}

data: {"eventType":"task_succeeded","taskId":"task_0_CongestionAgent",...}

... (SignalAgent, PublicSafetyAgent, DispatchAgent)

data: {"eventType":"conflict_check_done","conflicts":[{"type":"strategy_conflict","severity":"high","agents":["SignalAgent","PublicSafetyAgent"],...}],"conflictCount":3}

data: {"eventType":"task_ready","taskId":"task_arbiter","agentName":"ConflictArbiter",...}

data: {"eventType":"task_started","taskId":"task_arbiter","agentName":"ConflictArbiter",...}

data: {"eventType":"arbitration_result","conflictId":"arb_0","requiresHumanReview":true,"safetyFirstRule":"在学生过街安全与机动车通行效率冲突时...","resolution":"高风险冲突需要人工研判",...}

data: {"eventType":"task_succeeded","taskId":"task_arbiter",...}

data: {"eventType":"fusion_start","runId":"run_...",...}

data: {"eventType":"fusion_delta","text":"综合","executionMode":"llm"}
data: {"eventType":"fusion_delta","text":" 3 个 Agent 的分析",...}
... (多次 fusion_delta)

data: {"eventType":"fusion_done","fusionSummary":"综合 3 个 Agent 的分析结果，检测到 3 个建议冲突...","generationMode":"llm"}

data: {"eventType":"run_completed","runId":"run_...","sessionId":"sess_...","status":"completed"}

data: [DONE]
```

### 11. GET /collaboration/sessions/{session_id}/runs — 查询会话的 Run 列表

```bash
curl "http://localhost:8000/collaboration/sessions/sess_20260724.../runs"
```

**响应示例：**

```json
{
  "runs": [
    {
      "run_id": "run_1710000001000",
      "session_id": "sess_20260724...",
      "status": "completed",
      "started_at": "2026-07-24T10:00:00",
      "updated_at": "2026-07-24T10:00:15"
    },
    {
      "run_id": "run_1710000002000",
      "session_id": "sess_20260724...",
      "status": "completed",
      "started_at": "2026-07-24T10:05:00",
      "updated_at": "2026-07-24T10:05:18"
    }
  ]
}
```

### 12. GET /collaboration/runs/{run_id} — 查询 Run 完整审计记录

```bash
curl "http://localhost:8000/collaboration/runs/run_1710000001000"
```

**响应示例：**

```json
{
  "run": {
    "run_id": "run_1710000001000",
    "session_id": "sess_20260724...",
    "status": "completed",
    "normalized_event": {
      "avgSpeed": 8.0, "queueLength": 400,
      "roadName": "人民路", "nearbySchool": true,
      "fieldSources": {"avgSpeed": "current_message", ...}
    },
    "selected_agents": ["CongestionAgent", "SignalAgent", "PublicSafetyAgent", "DispatchAgent", "ConflictDetector", "ConflictArbiter", "FusionAgent"],
    "previous_run_context": null,
    "budget_usage": {"max_agents": 4, "max_agent_calls": 2, "used_agent_calls": {...}},
    "final_decision": {"fusionSummary": "...", "requiresHumanReview": true, "arbitration": {...}}
  },
  "tasks": [
    {"task_id": "task_0_CongestionAgent", "agent_name": "CongestionAgent", "status": "succeeded", "output_snapshot": {...}},
    ...
  ],
  "messages": [...],
  "conflicts": [
    {"conflict_id": "arb_0", "type": "strategy_conflict", "severity": "high", "resolution": "高风险冲突需要人工研判", "requires_human_review": 1}
  ],
  "events": [...]
}
```

### 13. POST /chat/stream — Chat SSE 流式对话

```bash
curl -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "content": "人民路早高峰拥堵严重，请分析。",
    "mode": "collaboration",
    "sessionId": null
  }'
```

### 14. DELETE /chat/sessions/{session_id} — 删除会话及全部关联数据

```bash
curl -X DELETE "http://localhost:8000/chat/sessions/sess_20260724..."
```

> **注意**：删除会话时会级联清理全部关联数据（chat_messages、memory_summaries、evidence_logs、collaboration_runs、collaboration_tasks、collaboration_messages、collaboration_conflicts、collaboration_events）。
