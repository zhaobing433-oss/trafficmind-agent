# 钱塘 Pilot Demo 指南

## Pilot 定位

钱塘 Pilot 是 TrafficMind 的隔离验证环境，范围限定为杭州市钱塘区白杨、金沙湖、下沙高教园片区。它验证真实地理上的事件研判、Grounding、Plan、Workflow、人工审批、执行追踪和 Case Memory 链路，但不是生产交通部署。

页面统一显示“钱塘 Pilot · 验证数据环境”。当前 Pilot 事件为合成 holdout；公开历史事件只提供可核验的事件级事实。

## 一条命令启动

从仓库根目录执行：

```bash
./scripts/start-qiantang-demo.sh
```

启动摘要出现后访问：

- Frontend: <http://127.0.0.1:5174>
- Backend: <http://127.0.0.1:8011>
- Backend health: <http://127.0.0.1:8011/health>

按 `Ctrl+C` 停止该命令创建的前后端进程。

### 前置条件

```bash
# backend virtual environment and dependencies
backend/.venv/bin/python -V

# frontend dependencies
test -x frontend/node_modules/.bin/vite
```

脚本在任一端口被占用时会停止，不会接入一个无法确认身份的已有服务。

## Runtime 隔离

Demo stores 位于：

```text
backend/data/pilot_demo/qt_by_xiasha_pilot_001/runtime/
```

该目录包含隔离的 Traffic DB、RAG DB、FTS 和 Chroma vector store。生成文件不纳入 Git，默认开发数据库 `backend/data/trafficmind.db` 不会被替换或迁移。

脚本会对输入 pack 和 materializer 计算 source digest：

- digest 与 business snapshot 均匹配时复用 runtime；
- 输入变化、snapshot 不一致或显式 reset 时重建隔离 runtime；
- embedding 必须解析为 `Qwen/Qwen3-Embedding-0.6B`、1024 维，不能静默使用 fake/hash provider。

需要明确重建时执行：

```bash
QIANTANG_DEMO_RESET=1 ./scripts/start-qiantang-demo.sh
```

## Demo 数据构成

| 内容 | 数量 | Reality |
|---|---:|---|
| 当前验证事件 | 8 | `synthetic_validation_holdout` |
| 当前事件类型 | 6 | 事故、拥堵、违停、行人风险、信号故障、车辆停驶 |
| 公开历史事件 | 4 | `real_public_reported_incident_history` |
| 合成历史池 | 144 | `synthetic_validation_history` |
| 合成事件闭环 Case | 8 | `synthetic_event_system_closure` |
| 公开事件回放 Case | 2 | `public_incident_replay_system_closure` |
| Grounding knowledge documents | 7 | public-source grounded summaries |

公开事件回放中的 Agent、Plan、Workflow、Approval 和 Case 是 TrafficMind deterministic 系统回放，不是历史交通部门的真实处置记录。业务效果没有外部证据时显示为未记录。

## 推荐走查

1. 打开“交通态势”，确认默认是事件工作台和公开地图，而不是 simulation topology。
2. 从风险优先事件队列选择事件，查看事件事实、关注原因和当前闭环阶段。
3. 打开最近研判，查看 role results、Grounding blocks 和 persisted evidence refs。
4. 从来源研判进入处置方案，核对 event/session/run/plan 的真实关联。
5. 从方案进入 Workflow，查看审批、执行事件和 terminal 状态。
6. 在知识库检查 Pilot 文档和索引状态。
7. 查看 Public History 与 Synthetic History 标签，确认两者没有混写。

当前事件可能没有可靠的精确坐标。此时事件仍可研判，但地图不会生成假 Marker。

## 地图

- Renderer: MapLibre GL JS。
- Default style: OpenFreeMap Positron。
- Fallback: OpenStreetMap Standard raster。
- Attribution: OpenFreeMap / OpenMapTiles / OpenStreetMap contributors。
- Canonical identity: `event_location_bindings`，不是地图点击或坐标猜测。

Public basemap 只用于本地 Demo/Pilot 可视化，不提供 production SLA。生产部署应配置具备许可、容量和可用性保障的 provider 或自托管 style/tile service。

## 日志与故障

运行日志写入 `${TMPDIR:-/tmp}/trafficmind-qiantang-demo/`，不写入仓库文档目录。

- 端口冲突：释放 `5174`/`8011`，或通过 `QIANTANG_DEMO_FRONTEND_PORT`、`QIANTANG_DEMO_BACKEND_PORT` 显式指定端口。
- Python venv 缺失：先建立 `backend/.venv` 并安装 `backend/requirements.txt`。
- Frontend dependencies 缺失：在 `frontend/` 执行 `npm install`。
- Public basemap 失败：事件工作台仍可用，地图按配置回退；地图失败不能改变事件 identity 或 Grounding。
- Isolated FTS table 不可用：当前检索会显式记录并使用 Python BM25 fallback；这是已知非阻断限制。

## 禁止的演示表述

不要将本 Demo 描述为：

- 真实实时钱塘交通或生产事件流；
- 钱塘区完整官方 GIS；
- 真实交通部门历史处置方案；
- 已证实的交通效果提升；
- 在线 LLM benchmark。
