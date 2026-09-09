# Qiantang G3-B Case Seed Recipe

This directory defines the Phase21 G3-B system-closure recipe for the
`QT_BY_XIASHA_PILOT_001` pilot region.

The recipe uses eight frozen synthetic validation events from
`QT_BY_XIASHA_SYNTH_HISTORY_001@1.0.0` and runs them through the existing
TrafficMind production path in isolated test storage:

Event -> Grounded Agent -> Plan -> Workflow -> Approval -> terminal workflow -> TrafficCaseMemoryBuilder.

## Reality Boundary

- `datasetReality = synthetic_system_closure_recipe`.
- `sourceEventReality = synthetic_validation`.
- `historyReality = synthetic_validation`.
- `regionalGeographyReality = real_public_verified`.
- `knowledgeReality = real_public_source_grounded`.
- `agentOutputReality = deterministic_validation`.
- `caseReality = synthetic_event_system_closure`.
- The generated case memories are not real Qiantang traffic cases, not real large-model cases, and not government case data.

## Scope Boundary

This recipe contains seed event identifiers, coverage metadata, and deterministic
approve/reject orchestration only. It intentionally contains no expected Agent
answer, no expected plan, no expected recommendation, no expected action, no
expected case lesson, no expected business outcome, and no holdout scenario.

G3-C holdout data is not created here. Its recommended T0 is computed only after
G3-B case completion and must be strictly after every generated case completion
timestamp.
