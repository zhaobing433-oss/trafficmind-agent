# TrafficMind Agent

**面向智慧交通的事件研判与闭环处置 Agent**

TrafficMind Agent 是一个智能交通事件分析系统。当摄像头和算法上报交通事件 JSON 后，Agent 自动完成事件解析、风险分级、预案匹配、调度话术生成、公众提示生成、事件报告生成，并通过深色主题大屏 Dashboard 实时展示指挥中心态势，支持企业微信/钉钉/邮件自动推送高风险事件告警，形成"感知→研判→派单→处置→复盘→归档"的完整闭环处置链路。

---

## 项目亮点

- **确定性 + AI 双引擎**：风险评分、规则匹配、状态流转由确定性规则保证可解释性；DeepSeek 大模型仅用于润色建议和报告，LLM 不可用时自动降级
- **LangGraph 流水线**：8 节点线性工作流（含消息推送），职责清晰，易扩展
- **深色大屏 Dashboard**：React + Ant Design + ECharts 实时指挥中心看板，含统计卡片、风险饼图、类型柱状图、趋势折线图、事件列表、相似案例检索、未闭环提醒、高风险路口 TopN、日报/周报生成
- **多渠道消息推送**：高风险事件自动通过企业微信机器人 / 钉钉机器人 / 邮件告警
- **历史相似案例检索**：基于 9 项规则相似度匹配历史案例，预留向量检索扩展接口（计划引入 Chroma/FAISS + RAG）
- **日报/周报自动生成**：7 段式结构化管理报告，支持 LLM 润色
- **未闭环事件自动提醒**：含提醒原因生成和处置建议
- **高风险路口 TopN**：按路口聚合统计高风险事件，自动生成管理建议
- **本地规则库**：Markdown 格式维护，无需向量数据库
- **零依赖降级运行**：不配任何外部 API Key 也能完整运行所有核心功能

---

## 技术栈

| 层级 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| 工作流引擎 | LangGraph 0.2.x |
| LLM（可选） | DeepSeek API（OpenAI-compatible） |
| 数据库 | SQLite（含自动兼容迁移） |
| 规则库 | 本地 Markdown |
| 相似检索 | 规则相似度（9 项加权），预留 Chroma/FAISS 扩展 |
| 前端 | React 18 + Ant Design 5 + ECharts 5 + Vite |
| 消息推送 | 企业微信 / 钉钉 Webhook + SMTP 邮件 |
| 测试 | pytest + FastAPI TestClient（27 个用例） |

---

## 目录结构

```
trafficmind-agent
├── CLAUDE.md                         # 项目文档（AI 新会话上下文）
├── README.md                         # 本文件
├── .gitignore
├── backend/
│   ├── app.py                        # FastAPI 主应用（12 个接口）
│   ├── config.py                     # 集中配置
│   ├── requirements.txt              # Python 依赖
│   ├── .env.example                  # 环境变量模板
│   ├── agent/
│   │   ├── graph.py                  # LangGraph 8 节点工作流
│   │   ├── nodes.py                  # 节点实现 + LLM 调用封装
│   │   └── prompts.py                # LLM 提示词
│   ├── tools/
│   │   ├── event_tools.py            # 事件校验与标准化
│   │   ├── risk_tools.py             # 风险评分
│   │   ├── rule_tools.py             # Markdown 规则库检索
│   │   ├── dispatch_tools.py         # 调度话术
│   │   ├── report_tools.py           # 八段式报告
│   │   ├── db_tools.py               # SQLite CRUD + 统计聚合
│   │   ├── notify_tools.py           # 消息推送（企微/钉钉/邮件）
│   │   ├── similarity_tools.py       # [Phase 2] 相似案例检索
│   │   ├── report_summary_tools.py   # [Phase 2] 日报/周报生成
│   │   ├── alert_tools.py            # [Phase 2] 未闭环提醒
│   │   └── stat_tools.py             # [Phase 2] 高风险路口 TopN
│   ├── data/
│   │   ├── rules/traffic_rules.md    # 8 类事件处置预案
│   │   └── trafficmind.db            # SQLite 数据库（自动创建）
│   └── tests/
│       └── test_sample_request.py    # 27 个测试用例
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx                  # 入口 + Ant Design 深色主题
│       ├── App.tsx
│       ├── types/index.ts            # TypeScript 类型定义
│       ├── api/index.ts              # API 调用封装（12 个接口）
│       ├── hooks/useDashboardData.ts  # 数据轮询 Hook
│       └── components/
│           ├── Dashboard.tsx         # 主布局（含 Phase 2 面板）
│           ├── Header.tsx            # 标题栏 + 时钟
│           ├── StatisticsCards.tsx    # 统计卡片
│           ├── RiskPieChart.tsx      # 风险饼图
│           ├── EventTypeBarChart.tsx # 事件类型柱状图
│           ├── TrendLineChart.tsx    # 趋势折线图
│           ├── EventList.tsx         # 事件列表
│           ├── EventFeed.tsx         # 高风险推送
│           ├── EventDetailModal.tsx  # 事件详情弹窗
│           ├── EventFormModal.tsx    # 新建事件弹窗
│           ├── StatusBadge.tsx       # 状态标签
│           ├── SimilarCasesPanel.tsx # [Phase 2] 相似案例面板
│           ├── UnclosedAlertsPanel.tsx # [Phase 2] 未闭环提醒面板
│           ├── HighRiskRoadsPanel.tsx # [Phase 2] 高风险路口面板
│           └── ReportPanel.tsx       # [Phase 2] 报告生成面板
└── docs/
    └── api_examples.md               # API 调用示例
```

---

## 安装与启动

### 后端

```bash
cd trafficmind-agent/backend

# 创建虚拟环境
python -m venv .venv

# 激活（Windows）
.venv\Scripts\activate
# 激活（macOS/Linux）
# source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 可选：配置环境变量
copy .env.example .env

# 启动（默认 8000 端口）
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

启动后访问：
- **Swagger API 文档**: http://localhost:8000/docs
- **健康检查**: http://localhost:8000/health

### 前端 Dashboard

```bash
cd trafficmind-agent/frontend
npm install
npm run dev
```

Vite 开发服务器默认启动在 `http://localhost:5173`，通过 Vite proxy 将 `/api/*` 自动转发到后端 `localhost:8000`。

> **注意**：前端和后端需要在**两个终端**同时运行。

### 运行测试

```bash
cd trafficmind-agent
pytest backend/tests/test_sample_request.py -v
# 预期：27 passed
```

---

## API 接口速览

### 第一阶段（6 个）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/analyze_event` | 分析交通事件，返回完整研判结果 |
| GET | `/history?limit=50` | 查询历史记录 |
| GET | `/event/{event_id}` | 查询单条事件详情 |
| POST | `/event/{event_id}/status` | 更新事件状态（6 种流转） |
| GET | `/health` | 健康检查 |
| GET | `/stats` | 仪表盘聚合统计 |

### 第二阶段新增（5 个）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/similar_cases/{event_id}` | 历史相似案例检索（规则相似度） |
| GET | `/reports/daily` | 交通事件日报 |
| GET | `/reports/weekly` | 交通事件周报 |
| GET | `/alerts/unclosed` | 未闭环事件提醒 |
| GET | `/stats/high_risk_roads` | 高风险路口 TopN 统计 |

### 第三阶段新增（6 个）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/rag/rebuild_index` | 重建 RAG 知识库向量索引 |
| GET | `/rag/search` | 语义检索交通知识库 |
| POST | `/rag/ask` | RAG 交通知识库问答 |
| GET | `/rag/status` | 查看向量库状态 |
| GET | `/similar_cases_hybrid/{event_id}` | 混合相似案例检索（规则+向量） |
| POST | `/agent/multi_analyze` | 多 Agent 协同研判 |

### 前端 Dashboard 面板（对应后端数据）

| 面板 | 数据来源 | 说明 |
|------|---------|------|
| 统计卡片 | `/stats` | 总事件数 / 高风险数 / 均分 / 待派单 |
| 图表区 | `/stats` | 风险饼图 / 类型柱状图 / 趋势折线图 |
| 事件分析 | `/analyze_event` + `/event/{id}` | 新建事件 + 查看研判结果 |
| 相似案例 | `/similar_cases/{id}` | 历史相似案例检索 |
| 未闭环提醒 | `/alerts/unclosed` | 自动刷新未闭环事件 |
| 高风险路口 | `/stats/high_risk_roads` | 路口 TopN + 管理建议 |
| 报告生成 | `/reports/daily` + `/reports/weekly` | 日报/周报一键生成 |
| 事件列表 | `/history` | 可排序、可点击查看详情 |
| 状态管理 | `/event/{id}/status` | 6 种状态流转 |

---

## 接口示例

### 分析交通事件

```bash
curl -X POST http://localhost:8000/analyze_event \
  -H "Content-Type: application/json" \
  -d '{
    "eventId": "E202606290001",
    "eventType": "congestion",
    "roadName": "人民路-解放路路口",
    "direction": "东向西",
    "avgSpeed": 8.5,
    "queueLength": 180,
    "duration": 601,
    "vehicleCount": 96,
    "weather": "rain",
    "timePeriod": "morning_peak",
    "isMainRoad": true,
    "nearbyHospital": true,
    "confidence": 0.91
  }'
```

### 更多示例

详见 [docs/api_examples.md](docs/api_examples.md)，包含全部 11 个接口的 curl 示例和响应格式。

---

## 事件类型与状态

**8 种事件类型**：拥堵 / 事故 / 违停 / 逆行 / 行人闯入 / 信号灯异常 / 车辆滞留 / 施工占道

**6 种状态流转**：待研判 → 待派单 → 处置中 → 已处置 → 待复盘 → 已归档

**4 个风险等级**：低风险(0-30) / 中风险(31-60) / 高风险(61-80) / 重大风险(81-100)

---

## 完整演示流程

在 `README.md` 同级目录下打开两个终端，按以下顺序操作：

### 终端 1：启动后端

```bash
cd backend
.venv\Scripts\activate
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

看到 `TrafficMind Agent 启动完成` 即就绪。

### 终端 2：启动前端

```bash
cd frontend
npm install   # 仅首次
npm run dev
```

看到 `Local: http://localhost:5173/` 即就绪。

### 演示步骤

| 步骤 | 操作 | 预期结果 |
|------|------|---------|
| 1 | 浏览器打开 `http://localhost:5173` | 看到深色大屏，统计卡片显示数据 |
| 2 | 点击「新建事件」按钮 | 弹出事件表单 |
| 3 | 填写表单（或点击预设示例数据），点击「提交分析」 | 弹出分析结果：风险等级、分数、处置建议 |
| 4 | 关闭弹窗，在「历史相似案例」面板点击「检索」 | 展示 5 个相似案例及相似度百分比 |
| 5 | 查看「未闭环提醒」面板 | 列出未闭环事件及告警原因 |
| 6 | 查看「高风险路口 TopN」面板 | 展示重点路口及管理建议 |
| 7 | 在「报告生成」面板点击「日报」，再点击「周报」 | 分别生成并展示报告全文 |
| 8 | 在底部「事件列表」中点击某条事件 | 弹出详情弹窗 |
| 9 | 在详情弹窗中可将状态更新为「处置中」或「已归档」 | 状态即时更新，未闭环提醒相应变化 |
| 10 | 打开 `http://localhost:8000/docs` 查看 Swagger | 11 个接口全部可用 |

---

## 项目截图说明

| 截图 | 位置 | 内容 |
|------|------|------|
| 大屏全貌 | 前端 `localhost:5173` | 统计卡片 + 图表 + 6 个功能面板 |
| API 文档 | 后端 `localhost:8000/docs` | 11 个接口的 Swagger 页面 |
| 分析结果 | 前端弹窗 | 风险评分、处置建议、调度话术 |
| 相似案例 | 前端面板 | 相似度百分比 + 相似原因 |
| 日报生成 | 前端面板 | 7 段式结构化报告全文 |
| Swagger 新增接口 | 后端 `/docs` | Phase 2 5 个 GET 接口 |

---

## 适合写进简历的项目描述

### 一句话版本

> 独立设计并实现 TrafficMind Agent — 基于 LangGraph + FastAPI + React 的智慧交通事件研判与闭环处置系统，支持 8 种交通事件类型的自动分析、风险评分、相似案例检索、日报生成和深色大屏可视化。

### 要点版本（适合技能列表）

- 后端使用 **FastAPI + LangGraph** 构建 8 节点工作流流水线
- 实现**确定性风险评分引擎**（基础分 + 9 项加权规则，上限 100 分）
- 基于**规则相似度**实现历史案例检索（9 维特征匹配），预留 Chroma/FAISS 向量检索扩展
- 自动生成**7 段式交通事件日报/周报**，支持 DeepSeek 大模型润色
- 前端使用 **React 18 + Ant Design 5 + ECharts 5 + Vite**，深色主题指挥中心大屏
- **27 个 pytest 测试用例**全部通过，覆盖端到端功能验证

### STAR 版本（适合面试详细讲述）

**S (Situation)**：城市交通指挥中心每天面对大量摄像头和算法上报的交通事件，缺乏自动化的分析研判工具。

**T (Task)**：设计并实现一套智能交通事件研判与闭环处置系统，支持事件自动分析、风险评级、预案匹配、报告生成和大屏可视化。

**A (Action)**：
- 使用 FastAPI 构建 12 个 RESTful API 接口
- 使用 LangGraph 编排 8 节点确定性工作流（解析→评分→规则→建议→话术→报告→存储→通知）
- 设计 9 项加权规则的风险评分引擎（基础分 + 动态加分，上限 100 分），保证 100% 可解释
- 基于规则相似度实现历史案例检索（9 维特征），预留向量数据库扩展接口
- 本地 Markdown 维护 8 类事件处置预案，无需外部数据库
- 使用 React + Ant Design + ECharts 构建深色大屏 Dashboard
- 编写 27 个端到端测试用例，覆盖所有接口的正常和异常场景
- DeepSeek 大模型作为可选增强，未配置时自动降级为本地模板

**R (Result)**：
- 11 个 API 接口完整可运行，27 个测试用例全部通过
- 大屏支持统计概览、事件分析、相似案例检索、未闭环提醒、日报/周报生成
- 零外部依赖可降级运行，不配任何 API Key 也能使用全部核心功能

---

## 面试讲解话术

### 项目介绍（30 秒版本）

> TrafficMind Agent 是一个智慧交通事件研判系统。摄像头和算法上报交通事件后，系统自动完成事件解析、风险评分、预案匹配，生成调度话术和处置报告。后端用 FastAPI + LangGraph，前端是 React 深色大屏。最大的亮点是风险评分完全由确定性规则驱动，100% 可解释；DeepSeek 大模型只用于润色，不配置也能跑。

### 技术亮点（回答"你做了什么技术选型"）

> 我选 LangGraph 做工作流引擎而不是自己写 if-else，因为 8 个节点职责清晰，每个节点独立 try/except，一个失败不影响后续。风险评分用确定性规则而不是直接调大模型，因为交通场景需要可解释性——每个加分项都能追溯原因。相似案例检索第一阶段用规则相似度（9 维加权），但预留了 vector_based_similarity 接口，第三阶段计划接 Chroma + embedding 做语义检索和 RAG。

### 难点攻克（回答"遇到什么困难"）

> 一是数据库兼容迁移——第二阶段新增了 8 个字段，用户已有数据不能丢。我用 ALTER TABLE + try/except 做增量迁移，旧数据库直接兼容。二是 httpx 0.28 改了传输层 API，原来的 ASGITransport 不兼容同步 Client，我换成了 FastAPI 的 TestClient 统一管理。三是 LLM 降级设计——每个调用 LLM 的地方都要考虑降级，LLM 失败时自动回退到本地模板，保证系统不崩。

### 扩展思考（回答"如果继续做你会加什么"）

> 第三阶段计划三个方向。一是向量检索：引入 Chroma/FAISS + embedding 模型把历史事件文本向量化，做语义级相似案例检索和 RAG，让大模型能基于历史处置经验直接生成建议。二是多 Agent 协同：用 LangGraph 的 SubGraph 机制让拥堵 Agent、事故 Agent、信号 Agent 并行分析，再由协调 Agent 汇总决策。三是信号灯策略模拟：对接 SUMO 仿真，让 Agent 生成的信号配时方案先在仿真中验证再下发。

---

## 消息推送配置

在 `.env` 中配置以下变量（可选，不影响核心功能）：

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
SMTP_TO=dispatch@example.com

# 触发推送的最低风险等级
HIGH_RISK_THRESHOLD=高风险
```

---

## 第三阶段新增功能

### 1. RAG 知识库 + 向量检索

引入 ChromaDB 作为本地向量数据库，将交通规则、历史事件报告、日报周报、调度经验等文本向量化存储，支持语义检索和 RAG 问答。

**三种检索方式对比：**

| 方式 | 原理 | 优点 | 缺点 |
|------|------|------|------|
| 规则检索 | 字段匹配（9维加权） | 可解释、稳定 | 不同路段但相似特征的案例检索不到 |
| 向量检索 | embedding 语义相似度 | 能发现语义相似案例 | 可解释性弱 |
| 混合检索 | 规则(0.6) + 向量(0.4) | 兼顾稳定性和召回 | 计算开销稍大 |

### 2. 交通知识库问答

基于 RAG 架构，用户可以用自然语言提问交通管理问题，系统检索相关知识后生成回答（含证据来源）。

### 3. 多 Agent 协同研判

5 个子 Agent（拥堵/事故/信号/调度/报告）独立分析同一事件，综合研判给出 finalDecision。

### 4. 向量库索引重建

```bash
# 重建索引（将规则、历史报告、经验写入向量库）
curl -X POST http://localhost:8000/rag/rebuild_index

# 查看向量库状态
curl http://localhost:8000/rag/status
```

### 5. 前端新增面板

- **RAG 知识库面板** — 向量库状态 + 语义检索
- **交通知识问答面板** — 自然语言提问 + RAG 回答
- **混合相似检索面板** — 规则相似度 + 向量相似度 + 最终相似度
- **多 Agent 协同面板** — 各子 Agent 研判结果 + dispatchPlan

---

## 第三阶段演示流程

1. 启动后端：`cd backend && uvicorn app:app --reload --host 0.0.0.0 --port 8000`
2. 启动前端：`cd frontend && npm run dev`
3. 重建 RAG 索引：`curl -X POST http://localhost:8000/rag/rebuild_index`
4. 前端「RAG 知识库」面板搜索"拥堵处置"查看检索结果
5. 前端「交通知识问答」输入"雨天早高峰主干道拥堵如何处置？"查看回答
6. 分析一个事件后，在「混合相似检索」面板查看规则+向量双路结果
7. 在「多 Agent 协同研判」面板点击运行，查看各 Agent 判断
8. 查看 Swagger：`http://localhost:8000/docs` 确认 17 个接口全部可用

---

## 后续计划

### 第三阶段：智能检索与协同（当前阶段）
- [x] ChromaDB 向量数据库
- [x] RAG 知识库问答
- [x] 混合相似检索（规则+向量）
- [x] 多 Agent 协同研判框架

### 第四阶段：预测与预防

- **向量数据库 + RAG**：引入 Chroma 或 FAISS，实现 `vector_based_similarity()` 接口，将历史事件文本通过 embedding 模型向量化，做语义级相似案例检索。结合 DeepSeek 大模型实现 RAG（检索增强生成），让 Agent 基于历史处置经验直接生成上下文化的处置建议
- **多 Agent 协同**：基于 LangGraph SubGraph 机制，拥堵 Agent + 事故 Agent + 信号 Agent 并行分析，协调 Agent 汇总决策，处理跨类型复合事件
- **信号灯策略模拟**：对接 SUMO 交通仿真，Agent 生成的信号配时调整方案先在仿真中验证效果（排队长度、平均延误等指标），确认有效后再推送给人工作为参考
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
