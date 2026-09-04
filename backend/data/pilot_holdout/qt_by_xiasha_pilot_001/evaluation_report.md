# Phase21 G3-C Hold-out Ablation Evaluation Report

- Pack: `QT_BY_XIASHA_HOLDOUT_G3C`
- Region: `QT_BY_XIASHA_PILOT_001`
- Frozen T0: `2026-09-04T13:10:55Z`
- Hold-out reality: `synthetic_validation`
- Agent provider: `deterministic_validation`
- Production traffic evaluation: `false`

## Aggregate Metrics

| Metric | A_CURRENT | B_REGIONAL | C_REGION_HISTORY_KNOWLEDGE | D_FULL |
| --- | ---: | ---: | ---: | ---: |
| groundingBlockCoverage | 8 | 16 | 32 | 40 |
| evidenceRefCount | 0 | 8 | 32 | 43 |
| traceableRefCount | 0 | 8 | 32 | 43 |
| eligibleContextItemCount | 8 | 29 | 79 | 90 |
| leakageCount | 0 | 0 | 0 | 0 |
| groundedRecommendationCoverage | 0 | 20 | 20 | 20 |
| planGroundingTraceability | 8 | 8 | 8 | 8 |
| sourceDiversity | 1.0 | 2.0 | 4.0 | 5.0 |

## Interpretation

- Regional context adds canonical location and nearby regional facts when the binding resolves.
- History and knowledge add strict-past event summaries and eligible source-grounded evidence.
- Case memory adds traceable prior system-closure experience in the full grounding group.
- Leakage guards are evaluated for wrong-region, future, current-target, and ineligible evidence.

## Limitations

- No real traffic outcome labels are present.
- LLM_ENABLED=false; this is not a live model quality benchmark.
- Synthetic history is not official Hangzhou traffic history.
- The report measures grounding, traceability, and leakage guards, not production accuracy.
