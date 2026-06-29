# TrafficMind Agent

**面向智慧交通的事件研判与闭环处置 Agent**

TrafficMind Agent 是一个智能交通事件分析系统。当摄像头和算法上报交通事件 JSON 后，Agent 自动完成事件解析、风险分级、预案匹配、调度建议生成、调度话术和事件报告生成，并通过深色主题大屏 Dashboard 实时展示指挥中心态势，支持企业微信/钉钉/邮件自动推送高风险事件告警，形成完整的闭环处置链路。

---

## 项目亮点

- **确定性 + 智能双引擎**：风险评分、规则匹配、状态流转由确定性规则保证可解释性；处置建议和报告生成可选接入 DeepSeek 大模型提升质量，LLM 不可用时自动降级
- **LangGraph 流水线**：8 节点线性工作流（含消息推送），职责清晰，易扩展
- **深色大屏 Dashboard**：React + Ant Design + ECharts 实时指挥中心看板，统计卡片 + 风险饼图 + 类型柱状图 + 趋势折线图 + 事件列表 + 高风险推送
- **多渠道消息推送**：高风险事件自动通过企业微信机器人 / 钉钉机器人 / 邮件告警，非阻塞 daemon 线程发送
- **本地规则库**：Markdown 格式维护，无需向量数据库，第一阶段即可落地
- **完整的闭环处置**：从事件接报 → 研判 → 派单 → 处置 → 复盘 → 归档，覆盖交通事件全生命周期
- **零依赖降级运行**：不配 API Key 照样能跑，所有功能通过模板兜底

---

## 技术栈

| 层级 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| 工作流引擎 | LangGraph |
| LLM（可选） | DeepSeek API（OpenAI-compatible） |
| 数据库 | SQLite |
| 规则库 | 本地 Markdown |
| 前端 | React 18 + Ant Design 5 + ECharts 5 + Vite |
| 消息推送 | 企业微信 / 钉钉 Webhook + SMTP 邮件 |
| 测试 | pytest + httpx |

---

## 目录结构

```
trafficmind-agent
├── backend
│   ├── app.py                  # FastAPI 主应用（6 个接口）
│   ├── config.py               # 集中配置（含推送渠道）
│   ├── requirements.txt        # Python 依赖
│   ├── .env.example            # 环境变量模板
│   ├── agent
│   │   ├── __init__.py
│   │   ├── graph.py            # LangGraph 8 节点工作流
│   │   ├── nodes.py            # 工作流节点实现
│   │   └── prompts.py          # LLM 提示词
│   ├── tools
│   │   ├── __init__.py
│   │   ├── event_tools.py      # 事件解析与标准化
│   │   ├── risk_tools.py       # 风险评分
│   │   ├── rule_tools.py       # 规则检索
│   │   ├── dispatch_tools.py   # 调度话术
│   │   ├── report_tools.py     # 报告生成
│   │   ├── db_tools.py         # 数据库 + 统计聚合
│   │   └── notify_tools.py     # 消息推送（企微/钉钉/邮件）
│   ├── data
│   │   ├── rules
│   │   │   └── traffic_rules.md  # 本地规则库
│   │   └── trafficmind.db        # SQLite 数据库（自动生成）
│   └── tests
│       └── test_sample_request.py # 测试用例
├── frontend                    # NEW - React 大屏 Dashboard
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx            # 入口 + AntD 深色主题
│       ├── App.tsx             # 根组件
│       ├── types/index.ts      # TypeScript 类型
│       ├── api/index.ts        # API 调用封装
│       ├── utils/format.ts     # 格式化工具
│       ├── hooks/useDashboardData.ts  # 轮询 Hook
│       └── components/
│           ├── Dashboard.tsx           # 主大屏布局
│           ├── Header.tsx              # 标题栏 + 时钟
│           ├── StatisticsCards.tsx      # 统计卡片
│           ├── RiskPieChart.tsx        # 风险饼图
│           ├── EventTypeBarChart.tsx   # 类型柱状图
│           ├── TrendLineChart.tsx      # 趋势折线图
│           ├── EventList.tsx           # 事件列表
│           ├── EventFeed.tsx           # 高风险推送面板
│           ├── EventDetailModal.tsx    # 事件详情弹窗
│           ├── EventFormModal.tsx      # 新建事件弹窗
│           └── StatusBadge.tsx         # 状态标签
├── docs
│   └── api_examples.md         # API 调用示例
└── README.md                   # 本文件
```

---

## 安装依赖

```bash
# 1. 进入后端目录
cd trafficmind-agent/backend

# 2. 创建虚拟环境
python -m venv .venv

# 3. 激活虚拟环境
# Windows:
.venv\Scripts\activate
# macOS / Linux:
# source .venv/bin/activate

# 4. 安装依赖
pip install -r requirements.txt

# 5.（可选）配置环境变量
# 复制 .env.example 为 .env，可按需填入 DeepSeek API Key 和推送渠道
# 不配置也可以运行，系统自动降级为本地模板
copy .env.example .env   # Windows
# cp .env.example .env    # macOS/Linux
```

---

## 启动命令

### 后端

```bash
cd trafficmind-agent/backend
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

启动后打开浏览器访问：
- **Swagger API 文档**: http://localhost:8000/docs
- **健康检查**: http://localhost:8000/health
- **仪表盘统计**: http://localhost:8000/stats

### 前端 Dashboard

```bash
cd trafficmind-agent/frontend
npm install
npm run dev
```

Vite 开发服务器启动在 `http://localhost:5173`，自动代理 `/api/*` 到后端 8000 端口。
打开浏览器访问 **http://localhost:5173** 即可看到指挥中心大屏。

> **提示**: 前端和后端需要同时运行。建议开两个终端分别启动。

---

## 接口示例

### 1. 分析交通事件

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

### 2. 查询历史记录

```bash
curl http://localhost:8000/history
```

### 3. 查询事件详情

```bash
curl http://localhost:8000/event/E202606290001
```

### 4. 更新事件状态

```bash
curl -X POST http://localhost:8000/event/E202606290001/status \
  -H "Content-Type: application/json" \
  -d '{"status": "处置中"}'
```

更多示例请见 [docs/api_examples.md](docs/api_examples.md)。

---

## 示例请求 JSON

```json
{
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
}
```

## 示例返回结果

```json
{
  "eventId": "E202606290001",
  "standardEvent": { "... 标准化事件对象 ..." },
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
  "matchedRule": "... 拥堵事件完整处置预案 ...",
  "suggestions": [ "... 5条具体处置建议 ..." ],
  "dispatchMessage": "... 面向指挥中心的调度指令 ...",
  "publicMessage": "【注意】人民路-解放路路口东向西方向通行缓慢，请过往车辆提前绕行。",
  "report": "... 八段式结构化报告 ...",
  "status": "待派单",
  "saved": true
}
```

---

## 消息推送配置

在 `.env` 中配置以下变量即可启用高风险事件自动推送（可选，不影响核心功能）：

```ini
# 企业微信机器人 Webhook
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx

# 钉钉机器人 Webhook
DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=xxx

# 邮件告警
SMTP_HOST=smtp.example.com
SMTP_PORT=465
SMTP_USER=alert@example.com
SMTP_PASSWORD=your_password
SMTP_FROM=alert@example.com
SMTP_TO=dispatch@example.com

# 触发推送的最低风险等级
HIGH_RISK_THRESHOLD=高风险
```

---

## 后续扩展方向

### 第二阶段：数据增强与可视化
- 接入真实摄像头视频流，对接目标检测 / 轨迹追踪算法
- 前端增强：实时事件地图（Leaflet/Cesium）、风险热力图、处置进度甘特图
- 对接信号灯控制接口，实现信号配时自动调整

### 第三阶段：智能调度与协同
- 多 Agent 协同：拥堵 Agent + 事故 Agent + 信号 Agent 协同决策
- 引入强化学习优化信号灯配时和分流策略
- 接入公安交管平台、122 接处警系统

### 第四阶段：预测与预防
- 基于历史数据训练事件预测模型（时空预测）
- 主动巡检：在高峰来临前预判高风险路段
- 知识图谱：构建交通事件因果推理图谱

### 工程化增强
- 引入 Redis 做事件缓存和实时状态
- PostgreSQL 替代 SQLite 支持高并发
- Docker 容器化部署 + K8s 编排
- CI/CD 流水线 + 自动化测试覆盖
- 对接消息队列（Kafka）实现事件流式处理
