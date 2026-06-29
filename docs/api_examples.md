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
