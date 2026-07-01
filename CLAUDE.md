# CLAUDE.md — TrafficMind Agent 项目文档

## 项目背景

**TrafficMind Agent** 是一个面向智慧交通的事件研判与闭环处置 Agent。当摄像头和算法上报交通事件 JSON 后，Agent 自动完成事件解析、风险分级、预案匹配、调度话术生成、公众提示生成、事件报告生成，并通过大屏 Dashboard 实时展示指挥中心态势。

项目核心设计理念：
- **确定性为主、智能增强为辅**：风险评分、规则匹配、状态流转全部由确定性规则保证可解释性；DeepSeek 大模型仅用于润色建议和报告，不可用时自动降级。
- **LangGraph 流水线**：8 节点线性工作流，职责清晰，易于扩展和调试。
- **零依赖降级**：不配置任何外部 API Key 也能完整运行所有核心功能。

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| Web 框架 | FastAPI + Uvicorn | 异步高性能 API |
| 工作流引擎 | LangGraph 0.2.x | 8 节点流水线编排 |
| LLM（可选） | DeepSeek API | OpenAI-compatible，可选接入 |
| 数据库 | SQLite | 轻量级，零配置 |
| 规则库 | 本地 Markdown | 无需向量数据库 |
| 前端 | React 18 + Ant Design 5 + ECharts 5 + Vite | 深色主题大屏 Dashboard（含 Phase 2 面板） |
| 相似检索 | 规则相似度（9 维特征） | 预留 Chroma/FAISS 向量扩展接口 |
| 消息推送 | 企业微信/钉钉 Webhook + SMTP 邮件 | 高风险事件自动告警 |
| 测试 | pytest + httpx | 端到端测试 |

## 第一阶段目标（MVP）

- [x] POST `/analyze_event` — 输入交通事件 JSON，完成全链路分析
- [x] GET `/history` — 查询历史分析记录
- [x] GET `/event/{event_id}` — 查询单条事件详情
- [x] POST `/event/{event_id}/status` — 更新事件处置状态（支持 6 种状态流转）
- [x] GET `/health` — 健康检查
- [x] GET `/stats` — 仪表盘聚合统计
- [x] 8 种事件类型支持：拥堵、事故、违停、逆行、行人闯入、信号灯异常、车辆滞留、施工占道
- [x] 风险评分引擎（基础分 + 9 项加权规则，上限 100 分）
- [x] 本地 Markdown 规则库（按事件类型组织）
- [x] SQLite 持久化存储
- [x] 消息推送（企业微信/钉钉/邮件，高风险事件自动触发）
- [x] React 深色主题大屏 Dashboard（统计卡片、图表、事件列表）
- [x] LLM 可选接入，未配置时自动降级

**不在第一阶段范围：** 视频识别、真实摄像头接入、地图集成、SUMO 仿真、多 Agent 协同、预测模型。

## 目录结构

```
trafficmind-agent/
├── CLAUDE.md                       # 本文件 — 项目文档
├── README.md                       # 面向用户的项目说明
├── backend/
│   ├── app.py                      # FastAPI 主应用（12 个接口）
│   ├── config.py                   # 集中配置（API、路径、评分、推送）
│   ├── requirements.txt            # Python 依赖
│   ├── .env.example                # 环境变量模板（含注释）
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── graph.py                # LangGraph 工作流定义（8 节点）
│   │   ├── nodes.py                # 工作流节点实现 + LLM 调用封装
│   │   └── prompts.py              # LLM 提示词模板
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── event_tools.py          # 事件校验 + 标准化 + 中英类型映射
│   │   ├── risk_tools.py           # 风险评分 + 等级判定（确定性规则）
│   │   ├── rule_tools.py           # Markdown 规则库解析 + 检索
│   │   ├── dispatch_tools.py       # 调度话术 + 公众提示生成
│   │   ├── report_tools.py         # 八段式结构化报告生成
│   │   ├── db_tools.py             # SQLite CRUD + 统计聚合
│   │   ├── notify_tools.py         # 消息推送（企微/钉钉/邮件）
│   │   ├── similarity_tools.py     # [Phase 2] 相似案例检索
│   │   ├── report_summary_tools.py # [Phase 2] 日报/周报生成
│   │   ├── alert_tools.py          # [Phase 2] 未闭环提醒
│   │   └── stat_tools.py           # [Phase 2] 高风险路口 TopN
│   ├── data/
│   │   ├── rules/
│   │   │   └── traffic_rules.md    # 8 类事件的本地处置预案
│   │   └── trafficmind.db          # SQLite 数据库（自动创建）
│   └── tests/
│       └── test_sample_request.py  # pytest 测试用例（含全生命周期测试）
├── frontend/                       # React 大屏 Dashboard
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx                # 入口 + AntD ConfigProvider 深色主题
│       ├── App.tsx
│       ├── types/index.ts          # TypeScript 类型定义
│       ├── api/index.ts            # Axios API 封装（含 mock 降级）
│       ├── utils/format.ts
│       ├── hooks/useDashboardData.ts
│       └── components/
│           ├── Dashboard.tsx       # 主布局（Grid 响应式）
│           ├── Header.tsx          # 标题栏 + 实时时钟
│           ├── StatisticsCards.tsx  # 4 个统计卡片
│           ├── RiskPieChart.tsx    # 风险等级饼图
│           ├── EventTypeBarChart.tsx # 事件类型柱状图
│           ├── TrendLineChart.tsx  # 近 7 天趋势折线图
│           ├── EventList.tsx       # 事件列表（可排序）
│           ├── EventFeed.tsx       # 高风险推送面板
│           ├── EventDetailModal.tsx # 事件详情弹窗
│           ├── EventFormModal.tsx  # 新建事件弹窗
│           ├── StatusBadge.tsx     # 状态标签组件
│           ├── SimilarCasesPanel.tsx  # [Phase 2] 相似案例面板
│           ├── UnclosedAlertsPanel.tsx # [Phase 2] 未闭环提醒面板
│           ├── HighRiskRoadsPanel.tsx  # [Phase 2] 高风险路口面板
│           └── ReportPanel.tsx        # [Phase 2] 报告生成面板
└── docs/
    └── api_examples.md             # API 调用示例（含完整生命周期测试流程）
```

## 开发规范

### Python 后端规范

1. **导入顺序**：标准库 → 第三方 → 本地模块，中间空行分隔。
2. **类型注解**：所有函数参数和返回值使用类型注解（`Dict[str, Any]` 等）。
3. **docstring**：所有公开函数必须有三引号 docstring，用 Args/Returns 格式。
4. **注释语言**：关键函数用中文注释说明逻辑，复杂算法逐行注释。
5. **错误处理**：每个节点独立 try/except，一个节点失败不影响后续节点。
6. **命名规范**：
   - 模块：`snake_case`（如 `event_tools.py`）
   - 函数：`snake_case`（如 `calculate_risk_score`）
   - 常量：`UPPER_SNAKE_CASE`（如 `EVENT_BASE_SCORES`）
7. **配置管理**：所有可配置项集中在 `config.py`，通过环境变量覆盖。
8. **确定性优先**：核心逻辑（评分、匹配、状态）必须是确定性的，不依赖 LLM。
9. **降级策略**：LLM 调用失败时自动回退到模板方案，不影响整体流程。

### API 设计规范

1. 请求/响应使用 Pydantic BaseModel 定义。
2. 接口返回统一使用 JSON，中文不转义（`ensure_ascii=False`）。
3. 错误响应用 `HTTPException` + `detail` 字段。
4. FastAPI 自动生成 OpenAPI 文档，访问 `/docs` 查看。

### 测试规范

1. 使用 pytest + httpx 进行端到端测试。
2. 测试类按接口划分（TestAnalyzeEvent、TestHistory 等）。
3. 每个接口至少覆盖正常场景和异常场景。
4. 启动测试命令：`pytest backend/tests/test_sample_request.py -v`（需在项目根目录执行）。

### 前端规范

1. 使用 React 18 + TypeScript，严格模式。
2. 组件按功能拆分，保持单一职责。
3. Ant Design 深色主题通过 `ConfigProvider` 全局注入。
4. ECharts 图表组件独立封装，通过 ref 响应窗口 resize。

## 启动方式

### 后端

```bash
cd trafficmind-agent/backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# 可选：copy .env.example .env 并填入配置
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

### 前端（可选）

```bash
cd trafficmind-agent/frontend
npm install
npm run dev
```

### 测试

```bash
cd trafficmind-agent
pytest backend/tests/test_sample_request.py -v
```

## API 接口速览

### 第一阶段（6 个）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/analyze_event` | 分析交通事件，返回完整研判结果 |
| GET | `/history?limit=50` | 查询历史记录 |
| GET | `/event/{event_id}` | 查询单条事件详情 |
| POST | `/event/{event_id}/status` | 更新事件状态 |
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

## 事件类型与状态

**支持的事件类型（8种）：**
拥堵、事故、违停、逆行、行人闯入、信号灯异常、车辆滞留、施工占道

**事件状态流转（6种）：**
待研判 → 待派单 → 处置中 → 已处置 → 待复盘 → 已归档

## 风险评分规则概要

基础分按事件类型从 20-45 分不等，叠加以下加权项：

| 条件 | 加分 |
|------|------|
| avgSpeed < 10 km/h | +15 |
| queueLength > 150 米 | +15 |
| duration > 600 秒 | +10 |
| duration > 900 秒 | 额外 +10 |
| weather ∈ {rain, snow, fog} | +10 |
| timePeriod ∈ {morning_peak, evening_peak} | +10 |
| isMainRoad = true | +10 |
| nearbySchool = true | +10 |
| nearbyHospital = true | +10 |

风险等级：0-30 低风险 / 31-60 中风险 / 61-80 高风险 / 81-100 重大风险

## 第二阶段（已完成）

### 新增功能
- [x] 历史相似案例检索（规则相似度，预留向量检索扩展接口）
- [x] 交通事件日报/周报生成（本地模板 + LLM 可选润色）
- [x] 未闭环事件提醒（含提醒原因和处置建议）
- [x] 高风险路口 TopN 统计（含管理建议）
- [x] 前端大屏 Dashboard 增强（4 个新功能面板）

### 新增文件
- [backend/tools/similarity_tools.py](backend/tools/similarity_tools.py) — 相似度计算 + 案例检索 + 向量检索预留接口
- [backend/tools/report_summary_tools.py](backend/tools/report_summary_tools.py) — 日报/周报生成
- [backend/tools/alert_tools.py](backend/tools/alert_tools.py) — 未闭环事件检测与提醒
- [backend/tools/stat_tools.py](backend/tools/stat_tools.py) — 高风险路口 TopN 统计
- 前端新增组件：SimilarCasesPanel / UnclosedAlertsPanel / HighRiskRoadsPanel / ReportPanel

### 新增 API 接口
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/similar_cases/{event_id}` | 历史相似案例检索 |
| GET | `/reports/daily` | 交通事件日报 |
| GET | `/reports/weekly` | 交通事件周报 |
| GET | `/alerts/unclosed` | 未闭环事件提醒 |
| GET | `/stats/high_risk_roads` | 高风险路口 TopN |

### 数据库变更
- event_records 表新增 8 个字段用于相似检索（avgSpeed / queueLength / duration / weather / timePeriod / isMainRoad / nearbySchool / nearbyHospital）
- 通过 ALTER TABLE 兼容迁移，旧数据库不崩溃

### 测试覆盖
- 27 个测试用例全部通过（第一阶段 12 + 第二阶段 15）

## 第三阶段（已完成）

### 新增功能
- [x] ChromaDB 向量数据库 + 本地 sentence-transformers embedding
- [x] RAG 知识库（规则、报告、经验）+ 语义检索
- [x] RAG 交通知识库问答（LLM 可选降级模板）
- [x] 混合相似检索（规则 0.6 + 向量 0.4）
- [x] 多 Agent 协同研判（4 个子 Agent + ReportAgent）
- [x] 前端 4 个新面板（RAG、问答、混合检索、多Agent）

### 新增文件
- [backend/rag/__init__.py](backend/rag/__init__.py)
- [backend/rag/vector_store.py](backend/rag/vector_store.py) — ChromaDB 封装
- [backend/rag/embedding_tools.py](backend/rag/embedding_tools.py) — 本地 embedding（哈希降级）
- [backend/rag/knowledge_indexer.py](backend/rag/knowledge_indexer.py) — 知识索引构建
- [backend/rag/semantic_retriever.py](backend/rag/semantic_retriever.py) — 语义检索
- [backend/rag/rag_service.py](backend/rag/rag_service.py) — RAG 问答服务
- [backend/agent/multi_agent.py](backend/agent/multi_agent.py) — 多 Agent 协同
- 前端：RagPanel / AskPanel / HybridSimilarityPanel / MultiAgentPanel

### 新增 API
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/rag/rebuild_index` | 重建向量索引 |
| GET | `/rag/search` | 语义检索 |
| POST | `/rag/ask` | RAG 问答 |
| GET | `/rag/status` | 向量库状态 |
| GET | `/similar_cases_hybrid/{event_id}` | 混合检索 |
| POST | `/agent/multi_analyze` | 多Agent研判 |

### 新增依赖
- chromadb>=0.5.0
- sentence-transformers>=3.0.0

### 测试覆盖
- 39 个测试用例全部通过（Phase1:12 + Phase2:15 + Phase3:12）

## 后续计划

### 第四阶段：预测与预防
   - 引入 Chroma 或 FAISS 向量数据库
   - 实现 `vector_based_similarity()` — 对历史事件文本做 embedding 后向量化存储
   - 语义级相似案例检索（比规则相似度更准确，能发现不同路段但特征相似的案例）
   - RAG（检索增强生成）：检索出的相似案例上下文注入 LLM prompt，让 Agent 基于历史处置经验生成上下文化的建议
   - 参考技术栈：Chroma / FAISS + text2vec 或 DeepSeek Embedding

2. **多 Agent 协同**
   - 基于 LangGraph SubGraph 机制
   - 拥堵 Agent + 事故 Agent + 信号 Agent 并行分析
   - 协调 Agent 汇总决策，处理跨类型复合事件
   - 每个子 Agent 有独立的工具集（拥堵 Agent 侧重信号配时，事故 Agent 侧重救援调度）

3. **信号灯策略模拟**
   - 对接 SUMO 交通仿真
   - Agent 生成的信号配时调整方案先在仿真中验证
   - 评估指标：排队长度变化、平均延误时间、通行量
   - 仿真通过后推送给人工作为参考方案

4. **外部系统对接**
   - 接入公安交管平台、122 接处警系统
   - 对接信号灯控制接口，实现配时自动调整

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

---

> **文档维护说明**：本文件供 Claude Code 等 AI 工具在新会话中快速理解项目上下文。
> 修改重要设计决策或目录结构后请同步更新此文件。
