# CLAUDE.md — TrafficMind Agent 项目文档

## 项目背景

**TrafficMind Agent** 是一个面向智慧交通的事件研判与多 Agent 协同处置工作台。支持从自然语言事件解析、风险评分、预案匹配，到多 Agent DAG 编排、冲突检测仲裁、SSE 流式融合，再到大屏 Dashboard 展示的完整链路。

项目核心设计理念：
- **确定性为主、智能增强为辅**：风险评分、规则匹配、状态流转全部由确定性规则保证可解释性；DeepSeek 大模型用于润色、融合和 RAG，不可用时自动降级。
- **Pydantic 标准协议**：Agent 间通信基于 14 种消息类型的 Pydantic 模型，全局唯一 ID，完整审计追踪。
- **DAG 编排 + 动态仲裁**：5 层 TaskGraph DAG，检测到冲突时动态插入仲裁层，安全优先原则。
- **零依赖降级**：不配置任何外部 API Key 也能完整运行所有核心功能。
- **当前阶段：Phase 10（结构化 Memory V2）已完成**，469 个 pytest 全部通过，TypeScript 0 errors。
  Memory V2 实现 Event Thread 隔离、确定性意图分类、结构化抽取写入、用户纠正 Supersede 链、
  可解释过滤排序、按 Agent 最小权限注入、Memory Trace 追踪和前端可观测面板。

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| Web 框架 | FastAPI + Uvicorn | 异步高性能 API + SSE 流式 |
| 工作流引擎 | LangGraph 0.2.x | 8 节点流水线 + 多 Agent 协同 |
| LLM（可选） | DeepSeek API | OpenAI-compatible，stream=true |
| 数据库 | SQLite | 9 张表（chat 4 + collaboration 5） |
| 向量检索 | Chroma + DeepSeek Embedding | RAG 检索增强生成 |
| 规则库 | 本地 Markdown | 无需外部数据库 |
| 前端 | React 18 + TypeScript + Ant Design 5 + ECharts 5 + Vite | 浅色现代工作台 |
| 消息推送 | 企业微信/钉钉 Webhook + SMTP 邮件 | 高风险事件自动告警 |
| 测试 | pytest + FastAPI TestClient | 283 个用例 |

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
├── CLAUDE.md                         # 本文件 — 项目文档
├── README.md                         # 面向用户的项目说明
├── .gitignore
├── backend/
│   ├── app.py                        # FastAPI 主应用（20+ 个接口）
│   ├── config.py                     # 集中配置
│   ├── requirements.txt              # Python 依赖
│   ├── .env.example                  # 环境变量模板
│   ├── agent/
│   │   ├── graph.py                  # LangGraph 8 节点工作流
│   │   ├── nodes.py                  # 节点实现 + LLM 调用封装
│   │   ├── prompts.py                # LLM 提示词
│   │   ├── multi_agent.py            # 多 Agent 分析（CongestionAgent 等）
│   │   ├── router.py                 # 动态 Agent 路由
│   │   ├── collaboration/            # [Phase 9] 协同编排引擎
│   │   │   ├── protocol.py           # Pydantic 标准消息协议（14 种类型）
│   │   │   ├── roles.py              # Agent 角色能力注册表
│   │   │   ├── state.py              # 11 状态运行状态机
│   │   │   ├── task_graph.py         # DAG 任务图（拓扑+循环检测+动态插入）
│   │   │   ├── orchestrator.py       # 编排器（构建→执行→持久化→SSE）
│   │   │   ├── executor.py           # 执行适配器（预算+裁剪+校验+重试）
│   │   │   ├── budget.py             # 执行预算控制
│   │   │   ├── context_projection.py # 上下文裁剪（最小权限）
│   │   │   ├── event_bus.py          # 内存事件总线（幂等去重）
│   │   │   ├── event_parser.py       # NL 事件解析 + currentEvent 构建
│   │   │   ├── agents.py             # 系统 Agent（dispatch/conflict/arbiter/fusion）
│   │   │   ├── db_repository.py      # SQLite 5 表持久化
│   │   │   └── repository.py         # 内存存储（测试用）
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
│   ├── chat/
│   │   ├── chat_db.py                # Chat 会话持久化（4 张表 + CRUD）
│   │   └── memory_manager.py         # 上下文记忆管理
│   ├── rag/                          # RAG 向量检索模块
│   ├── data/
│   │   ├── rules/traffic_rules.md    # 8 类事件处置预案
│   │   └── trafficmind.db            # SQLite 数据库（自动创建）
│   └── tests/
│       ├── test_sample_request.py    # Phase 1-8 测试
│       └── test_phase9_multi_run.py  # Phase 9 专项测试
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx                  # 入口 + Ant Design 浅色主题
│       ├── App.tsx                   # 主应用（路由/状态/SSE）
│       ├── types/
│       │   ├── index.ts              # 核心类型定义
│       │   └── collaboration.ts      # [Phase 9] 协作类型定义
│       ├── api/
│       │   ├── index.ts              # REST API 封装
│       │   ├── chatApi.ts            # Chat API
│       │   ├── collaborationApi.ts   # [Phase 9] 协作 API
│       │   └── streamApi.ts          # [Phase 9] SSE 流式 API
│       ├── utils/
│       │   ├── format.ts
│       │   ├── stream.ts
│       │   ├── conversation.ts
│       │   ├── answerFormatter.ts
│       │   └── collaborationEventReducer.ts  # [Phase 9] SSE 事件归约器
│       └── components/
│           ├── LayoutShell.tsx       # 布局壳
│           ├── Sidebar.tsx           # 侧边栏（会话列表+mode标签）
│           ├── Dashboard.tsx         # 大屏 Dashboard
│           ├── HomeHero.tsx          # 首页 Heroes
│           ├── ChatWorkspace.tsx     # 对话工作区
│           ├── ChatInputBar.tsx      # 输入栏
│           ├── CollaborationRunView.tsx  # [Phase 9] Run 详情视图
│           └── collaboration/        # [Phase 9] 协同组件
│               ├── CollaborationDagView.tsx
│               ├── AgentExecutionCard.tsx
│               ├── ConflictPanel.tsx
│               ├── FusionDecisionView.tsx
│               ├── BudgetUsagePanel.tsx
│               └── ErrorBoundary.tsx
└── docs/
    ├── api_examples.md               # API 调用示例
    ├── PHASE8_SSE_AGENT_STREAMING.md # Phase 8 文档
    └── PHASE9_MULTI_AGENT_COLLABORATION.md  # Phase 9 技术文档
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
backend\.venv\Scripts\python.exe -m pytest backend\tests -q
# 预期：283 passed
```

## API 接口速览

### Chat 接口（Phase 6-8）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat/stream` | SSE 流式对话（6 种 mode） |
| GET | `/chat/sessions` | 会话列表 |
| GET | `/chat/sessions/{id}` | 会话详情 + 消息 |
| PATCH | `/chat/sessions/{id}/title` | 修改标题 |
| DELETE | `/chat/sessions/{id}` | 删除会话（级联清理协作数据） |

### Collaboration 接口（Phase 9）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/agent/routed_analyze/stream` | 多 Agent 协同分析 SSE 流式 |
| GET | `/collaboration/sessions/{id}/runs` | 查询会话的 Run 列表 |
| GET | `/collaboration/runs/{run_id}` | 查询 Run 完整审计记录 |

### 第一阶段（6 个）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/analyze_event` | 分析交通事件，返回完整研判结果 |
| GET | `/history?limit=50` | 查询历史记录 |
| GET | `/event/{event_id}` | 查询单条事件详情 |
| POST | `/event/{event_id}/status` | 更新事件状态 |
| GET | `/health` | 健康检查（含 Phase 9 状态） |
| GET | `/stats` | 仪表盘聚合统计 |

### 第二/三/四阶段新增

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/similar_cases/{event_id}` | 历史相似案例检索 |
| GET | `/reports/daily` | 交通事件日报 |
| GET | `/reports/weekly` | 交通事件周报 |
| GET | `/alerts/unclosed` | 未闭环事件提醒 |
| GET | `/stats/high_risk_roads` | 高风险路口 TopN |
| POST | `/agent/react_diagnose` | 受控 ReAct 诊断 |
| POST | `/agent/routed_analyze` | 动态路由协同研判（REST） |

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

## 已完成阶段总览

### Phase 1：交通事件分析 MVP
- 8 种事件类型、9 项加权风险评分规则、8 节点 LangGraph 流水线

### Phase 2：相似案例、日报周报、未闭环提醒、高风险路口
- 5 个新增 API，规则相似度检索，前端 Dashboard 增强

### Phase 3：RAG 向量检索、混合检索、多 Agent 分析
- Chroma 向量数据库，DeepSeek Embedding，语义级检索，多 Agent 分析框架

### Phase 4：受控 ReAct、动态路由、冲突检测、链式协同
- ReAct 诊断 Agent，动态 Agent 路由，Agent 建议冲突检测

### Phase 5：AI 对话式工作台
- 浅色主题工作台，Sidebar 导航，ChatWorkspace，场景卡片入口

### Phase 6：会话持久化、可信 RAG、上下文管理
- SQLite 4 张表，5 个 Chat API，4 级置信度，长期摘要记忆

### Phase 7：产品工作台、LLM 环境加载、标题与模式隔离
- 标题自动生成，mode 标签，入口统一，模式隔离

### Phase 8：真实 SSE 流式、统一会话历史
- DeepSeek stream=true 真流式，统一 chat_sessions 写入

### Phase 9：多 Agent 协同编排与审计
详见 [docs/PHASE9_MULTI_AGENT_COLLABORATION.md](docs/PHASE9_MULTI_AGENT_COLLABORATION.md)

### Phase 10：结构化 Memory V2（当前阶段）
详见 [docs/PHASE10_MEMORY_V2.md](docs/PHASE10_MEMORY_V2.md)

核心能力：
- **MemoryItem 数据模型** — 21 字段，9 种类型，6 种状态，7 种来源，UTC 时间，dedupKey 幂等
- **MemoryStore 抽象** — ABC 接口 + SQLite 实现，PostgreSQL 预留，JSON 边界
- **Event Thread** — Session 内多事件隔离，自动创建/关闭/切换
- **结构化抽取** — 9 种抽取规则，全部确定性，动态字段黑名单
- **Write Gate** — 来源权限矩阵，authority 冲突检测，Proposal 确认绑定
- **User Correction** — 6 种纠正模式，Supersede 链，4 步原子事务
- **Recall Decision** — 6 种 intent 分类，确定性优先级，entity conflict 检测
- **过滤与排序** — 12 种过滤规则，5 维确定性评分
- **Per-Agent 注入** — 7 个 Agent 白名单，currentEvent/routingContext/agentContext 严格隔离
- **Memory Trace** — 完整 recall + write 追踪，merge 语义
- **8 种 SSE 事件** — recall_started/planned/completed/injection_ready/write_started/completed/failed
- **后端 Memory API** — 4 个端点（Session/Trace/Item/Threads）
- **前端 MemoryTracePanel** — 4 Tab（召回/注入/写入/拒绝），旧 Run 兼容
- **Session 删除级联** — 12 张表同步清理

### 测试覆盖
- **469 passed** / TypeScript 0 errors
- 测试文件：`test_sample_request.py` + `test_phase9_multi_run.py` + `test_phase10_memory_store.py` + `test_phase10_memory_write.py` + `test_phase10_memory_recall.py`

## 后续计划（Phase 10+）

### 近期
- **Memory V2**：跨 Session 结构化长期摘要，渐进式知识积累
- **Evaluation**：路由准确率、冲突召回率、RAG groundedness 评测集
- **Observability**：OpenTelemetry trace、延迟分位统计、失败率监控

### 中期
- **并行 Agent 执行**：同层 Agent 使用 `asyncio.gather` 并发
- **Auth/RBAC**：JWT + 用户角色 + 数据隔离
- **LLM 辅助仲裁**：关键词匹配漏检时调用 LLM

### 远期
- **Production**：PostgreSQL + Redis + Docker Compose + Nginx
- **Reliability**：取消/恢复/幂等/并发压力测试
- **SUMO 仿真**：信号配时方案仿真验证
- **WebSocket 大屏推送**：实时指挥中心态势更新

---

> **文档维护说明**：本文件供 Claude Code 等 AI 工具在新会话中快速理解项目上下文。
> 修改重要设计决策或目录结构后请同步更新此文件。
