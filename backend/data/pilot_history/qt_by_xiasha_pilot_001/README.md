# Qiantang Synthetic Historical Grounding Pool

This directory contains the Phase21 G3-A synthetic historical grounding pool for `QT_BY_XIASHA_PILOT_001`.

Dataset: `QT_BY_XIASHA_SYNTH_HISTORY_001@1.0.0`
History range: `2024-08-05T18:30:00Z` to `2026-07-21T12:30:00Z`
Geography source: `QT_BY_XIASHA_PILOT_001@1.0.0`

## Reality Boundary

- `datasetReality = synthetic_validation_history`.
- The geography is real G1 pilot geography; the traffic events are project synthetic validation history.
- This is not real Qiantang historical traffic data, not a realtime traffic feed, not an official historical dataset, and not a government feed.
- Event frequency, risk, status, weather, duration, speed, queue length, and time-of-day distribution are validation-oriented synthetic values.
- Formal events intentionally omit `isMainRoad`, `nearbySchool`, and `nearbyHospital`; G3-A does not convert G1 road/POI geography into event-level synthetic facts.
- The pool is a Grounding Pool / Historical Validation Pool, not a training set.

## Scope Boundary

G3-A contains only historical event facts needed by `HistoricalTrafficService` tests. It does not contain Agent outputs, plans, workflow runs, approvals, case memories, hold-out events, expected recommendations, expected actions, or answer labels.

The G3-C hold-out timestamp is not precommitted here. It must be frozen after G3-B case seed execution, and must be greater than both the latest historical event timestamp and the latest case completion timestamp.

G3-C evaluation harnesses and reports must explicitly label this pool as
`historyReality = synthetic_validation`. Runtime grounding provenance currently
identifies the source as `event_records`; final reports must not describe these
synthetic records as real Qiantang historical traffic statistics.

## Import Boundary

Tests import this pack into temporary SQLite state through the existing `save_event_analysis` event write path and resolve locations through `EventLocationBindingService` / `EventLocationResolver`. Expected canonical locations under `validation` are for pack validation only and must not be used to write bindings directly.

The public `/events/import` endpoint is still a real-event deterministic batch import path, but it intentionally stamps current time, forces the initial event status, and drops non-event provenance fields. G3-A therefore uses the existing lower-level event write path for stable historical validation data.

## Inventory

- Synthetic events: 144
- Intersection-bound events: 108
- Road-bound events: 36
- Covered event types: accident, congestion, illegal_parking, pedestrian_intrusion, signal_fault, vehicle_stopped
- Duration finite/null: 144 / 0

G3-A keeps duration values finite so the static pack round-trips through the
existing event repository write path without changing business meaning. NULL
duration semantics are validated separately by the Wave C historical context
tests and are not encoded in this formal pack.

## Safety

All timestamps are inside the G2 safe evaluation range (`>= 2024-08-01T00:00:00Z`) and before `2026-09-01`. The formal pack is data only and must not be imported into `backend/data/trafficmind.db` during tests.
