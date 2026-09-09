# 数据真实性与来源说明

TrafficMind 将“来源可核验”和“系统验证生成”明确分层。Reality metadata 是产品解释和评测口径的一部分，不能为了演示效果被省略或混写。

## Reality 分类

| 数据层 | Pack / Store | Reality | 边界 |
|---|---|---|---|
| Regional geography | `pilot_regions/qt_by_xiasha_pilot_001` | `real_public_verified` | 有限 Pilot 范围，不是官方全量 GIS |
| Knowledge | `pilot_knowledge/qt_by_xiasha_pilot_001` | `real_public_source_grounded` | 项目摘要，不是官方知识库或实时政策 feed |
| Public incident history | `pilot_history_public/qt_by_xiasha_pilot_001` | `real_public_reported_incident_history` | 公开来源支持的事件级事实，不含真实处置链 |
| Synthetic traffic history | `pilot_history/qt_by_xiasha_pilot_001` | `synthetic_validation_history` | 在真实地理上的 deterministic coverage 数据 |
| Current Pilot events | `pilot_holdout/qt_by_xiasha_pilot_001` | `synthetic_validation_holdout` | 冻结验证事件，不是实时 feed |
| Synthetic closure cases | `pilot_case_seed/qt_by_xiasha_pilot_001` | `synthetic_event_system_closure` | 系统执行合成事件后形成的闭环 |
| Public replay cases | isolated demo runtime | `public_incident_replay_system_closure` | 公开事件事实上的系统回放，不是历史真实处置 |
| Evaluation Agent provider | G3-C | `deterministic_validation` | 可复现链路评测，不是 live LLM quality benchmark |

## Regional Geography

Pilot region 是内部 bounded scope，覆盖白杨、金沙湖和下沙高教园片区的有限道路、路口和 POI。

来源包括：

- 杭州市政府公开行政与规划页面；
- 高校等机构第一方地址页面；
- OpenStreetMap / Overpass 的辅助道路、路口和坐标数据。

OSM way/node ID 只保存在 metadata/provenance 中，不作为业务 canonical ID。Road/intersection relation 可以由公开地理推导，但不声称为官方 GIS topology。

## Knowledge

Pilot Knowledge 包含公开法律、行政法规、国家标准和区域规划来源的短摘要，包括道路交通安全法、实施条例、GB 14886-2016 和钱塘白杨单元规划公开信息。

每个文档保留 source URL、organization、authority level、retrieved date、effective time 和适用 scope。系统只在事件时间、区域和事件类型满足条件时使用证据；来源页面展示的“现行”等状态按 source metadata 记录，项目不自行作超出来源的法律有效性断言。

## Public Incident History 与隐私

公开历史包接受 4 条能够通过来源和 canonical location gate 的交通事件。它只保存：

- 事件类型与发生时间精度；
- 简化地点、道路或路口绑定；
- 参与者类别；
- 事件影响和来源明确记载的责任摘要；
- source ID 与最小 provenance。

它不保存姓名、车牌、住址、医院/医疗明细、保险信息、赔偿金额等个人敏感字段，不缓存原始裁判文书页面，也不在产品截图中展示敏感原文。候选记录未通过来源、日期或 location gate 时进入 excluded list，不伪造绑定。

## Synthetic History 与 Current Events

合成历史池包含 144 条 deterministic validation 事件，覆盖 6 个事件类型、4 个风险等级、6 个状态和多个时间段。它建立在真实 Pilot 地理上，但不是政府 feed、官方历史数据或真实事件日志。

当前 Demo 的 8 条事件来自冻结 G3-C holdout。它们用于测试当前事件到 Grounding、Agent、Plan、Workflow、Approval 和 Trace 的产品链路。界面必须显示验证数据标签。

## Case Reality

Case Memory 记录系统闭环，不自动等同于真实世界处置经验：

- `synthetic_event_system_closure`：由合成验证事件进入真实系统执行链后产生。
- `public_incident_replay_system_closure`：以公开事件事实为输入，由系统 deterministic replay 产生。

Case 保存的 approval 与 terminal status 是系统运行事实；外部业务结果没有证据时保持 unknown/未记录。Case 不推断真实交通效果。

## Grounding 时间与区域门控

Grounding 使用以下最小约束：

- History `createdAt` 必须严格早于 current event。
- Case `completedAt` 必须严格早于 query `asOf`。
- Wrong-region、future 和 current-target records 被排除。
- Knowledge 必须满足 scope 与 effective-time eligibility。
- Event 必须具有 active/resolved canonical location 才能使用区域绑定能力。
- 本次 Grounding snapshot 随 run 持久化，后续数据变化不回写历史判断依据。

## 地图来源

前端使用 MapLibre GL JS 展示 OpenFreeMap / OpenStreetMap public basemap，并显示 attribution。地图不参与事件 identity、Location Resolver、历史关联或 Case 匹配。

坐标只在 G1 source pack 有可核验记录且 canonical binding 精确匹配时使用。道路级、未解析或无来源坐标的事件不生成 Marker；系统不会为了视觉完整性猜测位置。

## 可声明与不可声明

可以声明：

- 公开来源核验的有限区域上下文和规则摘要；
- 公开事件级历史事实；
- synthetic/deterministic 数据上的系统链路、隔离性和 traceability；
- Workflow、Approval 和 Case 的系统运行状态。

不可以声明：

- 真实实时钱塘交通或生产数据接入；
- 真实交通部门历史处置方案；
- 系统已改善真实交通指标；
- G3-C 是线上模型准确率 benchmark；
- public basemap 等于 official GIS。
