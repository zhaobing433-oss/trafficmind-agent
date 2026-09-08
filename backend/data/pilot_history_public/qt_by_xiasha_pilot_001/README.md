# 钱塘 Pilot 公开历史交通事件包

本包仅保存公开来源能够直接支持的交通事件级事实，`datasetReality` 为
`real_public_reported_incident_history`。原始裁判文书网页不会缓存进仓库；姓名、车牌、
医院、医疗与赔偿金额、住址等个人信息均不保存。

## 现实边界

- 历史事件事实来自公开来源，不等于 TrafficMind 获得了实时生产事件流。
- 对事件执行的 Agent、Plan、Workflow、Approval 与 Case 是系统验证回放，不是当年的真实处置。
- `exact_intersection` 只用于来源地点与 G1 路口完全匹配的记录。
- `road_bound` 只表示来源明确提到一条 G1 道路，不推测未纳入 G1 的交叉道路位置。
- 未通过来源、日期或 canonical location gate 的候选保留在 `excluded_candidates.json`。
