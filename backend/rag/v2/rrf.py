"""
Reciprocal Rank Fusion (RRF) — 多通道检索结果融合。

Uses reciprocal rank formula: score = 1 / (k + rank)
Never uses uncalibrated linear combination like denseScore*0.6 + sparseScore*0.4.
"""
from __future__ import annotations
from typing import Dict, List


def reciprocal_rank_fusion(
    result_sets: List[List[Dict]],
    k: int = 60,
    window: int = 40,
    key: str = "chunk_id",
) -> List[Dict]:
    """RRF 融合多通道检索结果。

    Args:
        result_sets: 多通道结果列表 e.g. [dense_results, sparse_results, structured_results]
        k: RRF 常数（默认 60）
        window: 每个通道取前 N 条参与融合
        key: 用于合并去重的字段

    Returns:
        融合后的候选列表，按 rrf_score 降序，包含 retrieval_channels
    """
    if not result_sets:
        return []

    # Build RRF scores
    rrf_scores: Dict[str, Dict] = {}
    channel_names = ["dense", "sparse", "structured"]

    for ch_idx, results in enumerate(result_sets):
        ch_name = channel_names[ch_idx] if ch_idx < len(channel_names) else f"channel_{ch_idx}"
        for rank, item in enumerate(results[:window]):
            item_key = item.get(key, "")
            if not item_key:
                continue

            rrf_contrib = 1.0 / (k + rank + 1)

            if item_key not in rrf_scores:
                rrf_scores[item_key] = {
                    **item,
                    "rrf_score": 0.0,
                    "retrieval_channels": [],
                    "dense_rank": None,
                    "sparse_rank": None,
                    "structured_rank": None,
                }

            entry = rrf_scores[item_key]
            entry["rrf_score"] = round(entry["rrf_score"] + rrf_contrib, 6)
            if ch_name not in entry["retrieval_channels"]:
                entry["retrieval_channels"].append(ch_name)

            # CRITICAL: merge in any fields that exist in the new item but are None/missing in existing entry
            # This preserves metadata like effective_to that only appears in one channel
            for field in ("effective_from", "effective_to", "status", "version",
                          "authority_level", "doc_type", "title", "section_path",
                          "document_id", "parent_chunk_id", "event_type", "road_name",
                          "risk_level", "source_uri"):
                if item.get(field) is not None and entry.get(field) is None:
                    entry[field] = item[field]
            # Also merge metadata sub-dict fields
            for field in ("effective_from", "effective_to", "status", "version", "authority_level"):
                item_meta = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
                entry_meta = entry.get("metadata", {}) if isinstance(entry.get("metadata"), dict) else {}
                if item_meta.get(field) is not None and entry_meta.get(field) is None:
                    if not isinstance(entry.get("metadata"), dict) or not entry.get("metadata"):
                        entry["metadata"] = {}
                    entry["metadata"][field] = item_meta[field]

            # Store channel-specific ranks
            if ch_name == "dense":
                entry["dense_rank"] = rank + 1
                entry["dense_score"] = item.get("score")
            elif ch_name == "sparse":
                entry["sparse_rank"] = rank + 1
                entry["sparse_score"] = item.get("score")
            elif ch_name == "structured":
                entry["structured_rank"] = rank + 1
                entry["structured_score"] = item.get("score")

    # Sort by RRF score descending
    merged = sorted(rrf_scores.values(), key=lambda x: x["rrf_score"], reverse=True)
    return merged
