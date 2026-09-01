# 钱塘区白杨-金沙湖-下沙高教园试点区 Knowledge Pack

This directory contains the Phase21 G2 pilot Knowledge pack for `QT_BY_XIASHA_PILOT_001`.

Source snapshot date: `2026-09-01`. This date means the TrafficMind project verified the cited public sources on that date; it is not a source publication date and not a policy effective date.

## Reality Boundary

- Knowledge sources are public official or official-republication pages listed in `source_register.json`.
- Knowledge document content is a compact TrafficMind project-derived source-grounded summary.
- The pack does not copy full legal texts, standards, or planning pages.
- Citations point to original public source pages through `sourceUri`.
- The pack is not an official government knowledge base.
- The pack is not a realtime policy feed.
- `status=active` for an ingested document means "enabled in the TrafficMind corpus" only; it is not an independent assertion that a law, regulation, standard, or planning item is legally current.
- Event applicability metadata is a TrafficMind retrieval filter and does not represent an official incident classification.
- `GLOBAL` means non-region-specific retrieval inside the current China pilot product boundary; it does not mean worldwide legal applicability, and each document still preserves its `jurisdiction`.
- `REGIONAL` means the bounded internal G1 pilot retrieval scope. For this pack, the Baiyang planning note is only a Baiyang-unit public planning context inside the broader internal pilot, not a whole-region operational rule.
- `LEGACY_UNSCOPED` documents must remain distinct from explicit `GLOBAL` knowledge and must not be silently treated as globally applicable.
- `QT_BY_XIASHA_PILOT_001` is a bounded internal pilot region from the G1 regional context pack, not an official administrative code.
- `effectiveFrom=null` means the current Wave D filter has no lower-bound for that document. It does not mean the cited current-version summary applied before the source's publication, amendment, or page date.
- Safe G3 pilot evaluation range for this formal pack: use event timestamps on or after `2024-08-01T00:00:00Z`, unless a test explicitly creates synthetic temporal eligibility fixtures. This avoids applying current-source summaries to older historical events.

## Architecture Boundary

G2 reuses the existing RAG V2 Knowledge architecture:

`Knowledge create_document` -> `RagDocument` -> `TrafficKnowledgeChunker` -> SQLite chunks -> dense index -> sparse index -> event-bound structured eligibility.

The formal pack is data only. Tests ingest it into temporary SQLite/RAG/Chroma/FTS stores and must not mutate the production RAG database, production traffic database, or active Qwen collection.

## Scope

The first G2 corpus intentionally stays small: 7 source-grounded documents covering accident, congestion, illegal parking, pedestrian intrusion, vehicle stopped, signal fault, and one regional planning context note.

The regional planning context note is useful only as public local context for Baiyang-unit planning. It must not be rendered as a Qiantang-wide traffic dispatch SOP, an official TrafficMind/government partnership dataset, or a real-time local policy feed.

## Not Claimed

This pack is not a full Qiantang District knowledge corpus, not a complete legal database, not a local dispatch SOP, not realtime traffic data, not a government partnership dataset, and not a source of historical case memories. G3 event evaluation will still use synthetic events with explicit provenance labels.
