# TrafficMind 最终验收摘要

本摘要记录 Phase 21 backend Pilot 与 Phase 22 frontend productization 的最终本地验收证据。结果对应 checkpoint `c005ecc117198d276df2766a50d6ae403e47f088`，不等同于 CI、生产部署或外部效果认证。

## Product Acceptance

| 验收域 | 结果 |
|---|---|
| One-command Qiantang Demo | PASS |
| Runtime identity: frontend `5174` -> backend `8011` -> isolated stores | PASS |
| Traffic default real-event workbench | PASS |
| Modern MapLibre map and attribution | PASS |
| 8 current Pilot events / 6 event types | PASS |
| Legacy test event/filter values | 0 |
| Fake event markers | 0 |
| Multi-Agent presentation | PASS |
| Regional / History / Knowledge / Case Grounding | PASS |
| Public vs synthetic history labeling | PASS |
| Plan / Workflow / Approval navigation | PASS |
| Workflow terminal outcome honesty | PASS |
| Closed-loop persisted source chain mismatch | 0 |
| Map/workbench selection synchronization | PASS |
| Provider failure fallback | PASS |
| Sidebar, cross-page navigation and responsive smoke | PASS |
| Production Traffic/RAG/vector stores unchanged | PASS |

## Automated Verification

| Suite | Result |
|---|---|
| Phase 21/22 backend targeted matrix | `95 passed, 1 skipped, 0 failed, 0 errors` |
| Phase 21 case-seed focused test | `2 passed` |
| Frontend Node contract suite | `81/81 PASS` |
| TypeScript + Vite production build | PASS |
| Git whitespace validation | PASS |

Backend 的 1 个 skip 是已确认的 environment-gated provider case，不是 required-path failure。浏览器验收使用 isolated Pilot runtime，没有创建或修改 production Traffic、RAG 或 vector data。

## G3-C Holdout / Ablation

G3-C 包含 8 个 frozen holdout events、4 个 ablation groups 和 32 个 deterministic evaluation runs。

| Group | Context | Evidence refs | Traceable refs | Leakage | Source diversity |
|---|---|---:|---:|---:|---:|
| A | Current event only | 0 | 0 | 0 | 1 |
| B | + Regional | 8 | 8 | 0 | 2 |
| C | + Strict-past history and eligible knowledge | 32 | 32 | 0 | 4 |
| D | + Strict-past Case Memory | 43 | 43 | 0 | 5 |

这些指标证明 Grounding context coverage、来源多样性和 traceability 随上下文增加而提升，并证明本评测中的 wrong-region/future/current-target/ineligible leakage 为 0。它们不证明真实交通准确率、真实处置效果或线上 LLM 质量提升。

## Runtime Safety

最终 backend matrix 前后：

- production `trafficmind.db` SHA 不变；
- production WAL/SHM 状态不变；
- production RAG v2 manifest 不变；
- production Chroma/vector manifest 不变；
- Demo runtime 位于独立 ignored directory。

Case-seed DB safety guard 使用动态 before/after comparison，而不是绑定某个历史 production SHA。

## Screenshot Index

截图来自最终代码启动的 isolated Qiantang Pilot runtime，未使用临时页面或伪造关系。

| Screenshot | Coverage |
|---|---|
| [Traffic / Map](images/qiantang-traffic-workbench.jpg) | 公开地图、canonical marker、风险优先事件队列 |
| [Multi-Agent + Grounding](images/qiantang-grounded-judgment.jpg) | persisted 研判、人工审核边界、Grounding 引用 |
| [Plan / Workflow / Approval](images/qiantang-plan-workflow-approval.jpg) | 方案来源、审批要求、terminal rejection 与后续停止 |

截图中的事件属于验证数据环境。它们不表示实时交通 feed 或真实部门处置。

## Known Non-blocking Limitations

1. Isolated sparse FTS 缺少表时使用显式 Python BM25 fallback。
2. Ant Design 仍有 static-context warning。
3. Map vendor chunk 仍有 size warning；无 circular/runtime blocker。
4. `eventWorkbenchState` 存在异步 side-effect 技术债。
5. Persistent component 的 stale-refresh 场景仍缺少专门前端测试。
6. Case Memory 部分内部类型和英文摘要仍可继续做用户文案 polish。

这些项未阻断当前 Pilot Demo，但不应被改写为已经解决。
