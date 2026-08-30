"""Shared helpers for real-event identity and authoritative snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from backend.config import EVENT_STATUSES
from backend.tools.alert_tools import UNCLOSED_STATUSES
from backend.tools.db_tools import get_event_by_id


class EventIdentityError(ValueError):
    """Raised when a real-event identity cannot be resolved safely."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def extract_event_id(payload: Optional[Dict[str, Any]]) -> str:
    """Extract the canonical event id from a request/event-shaped payload."""
    if not isinstance(payload, dict):
        return ""
    candidates = [
        payload.get("eventId"),
        payload.get("event_id"),
    ]
    standard = payload.get("standardEvent")
    if isinstance(standard, dict):
        candidates.extend([standard.get("eventId"), standard.get("event_id")])
    full = payload.get("fullResult")
    if isinstance(full, dict):
        full_standard = full.get("standardEvent")
        if isinstance(full_standard, dict):
            candidates.extend([full_standard.get("eventId"), full_standard.get("event_id")])
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def event_snapshot_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Build an immutable runtime snapshot from the authoritative event row."""
    snapshot = {k: v for k, v in dict(record).items() if k != "id"}
    raw = snapshot.get("rawEvent")
    if isinstance(raw, dict):
        for field in (
            "vehicleCount",
            "confidence",
            "weather",
            "timePeriod",
            "isMainRoad",
            "nearbySchool",
            "nearbyHospital",
        ):
            if snapshot.get(field) in (None, "") and raw.get(field) is not None:
                snapshot[field] = raw.get(field)
    snapshot["eventId"] = extract_event_id(snapshot)
    snapshot["snapshotSource"] = "event_records"
    snapshot["capturedAt"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return snapshot


def compact_event_context(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Project an authoritative snapshot into runtime event context fields."""
    raw = snapshot.get("rawEvent") if isinstance(snapshot, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    full = snapshot.get("fullResult") if isinstance(snapshot, dict) else {}
    if not isinstance(full, dict):
        full = {}
    standard = full.get("standardEvent")
    if not isinstance(standard, dict):
        standard = {}

    def pick(field: str, default: Any = "") -> Any:
        for source in (snapshot, raw, standard):
            value = source.get(field) if isinstance(source, dict) else None
            if value not in (None, ""):
                return value
        return default

    return {
        "eventId": pick("eventId"),
        "eventType": pick("eventType"),
        "eventTypeCn": pick("eventTypeCn"),
        "roadName": pick("roadName"),
        "direction": pick("direction"),
        "avgSpeed": pick("avgSpeed", None),
        "queueLength": pick("queueLength", None),
        "duration": pick("duration", None),
        "vehicleCount": pick("vehicleCount", None),
        "riskScore": pick("riskScore", None),
        "riskLevel": pick("riskLevel"),
        "status": pick("status"),
        "weather": pick("weather", "clear"),
        "timePeriod": pick("timePeriod", "off_peak"),
        "isMainRoad": bool(pick("isMainRoad", False)),
        "nearbySchool": bool(pick("nearbySchool", False)),
        "nearbyHospital": bool(pick("nearbyHospital", False)),
        "snapshotSource": snapshot.get("snapshotSource", ""),
        "capturedAt": snapshot.get("capturedAt", ""),
    }


def hydrate_authoritative_event(
    event_id: str,
    client_event: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve event_id through event_records; client snapshots never win."""
    canonical = str(event_id or "").strip()
    if not canonical:
        raise EventIdentityError("missing_event_id", "eventId 不能为空")

    client_event_id = extract_event_id(client_event)
    if client_event_id and client_event_id != canonical:
        raise EventIdentityError(
            "event_id_mismatch",
            f"请求 eventId '{client_event_id}' 与目标 eventId '{canonical}' 不一致",
        )

    record = get_event_by_id(canonical)
    if record is None:
        raise EventIdentityError("event_not_found", f"事件 {canonical} 不存在")
    return event_snapshot_from_record(record)


def is_terminal_event_status(status: str) -> bool:
    """Use the existing unclosed-status semantics for execution blocking."""
    text = str(status or "").strip()
    return bool(text) and text in EVENT_STATUSES and text not in UNCLOSED_STATUSES


def ensure_event_open_for_execution(snapshot: Dict[str, Any]) -> None:
    """Reject new workflow execution for already closed/terminal events."""
    status = str((snapshot or {}).get("status") or "").strip()
    if is_terminal_event_status(status):
        event_id = extract_event_id(snapshot)
        raise EventIdentityError(
            "event_terminal",
            f"事件 {event_id or ''} 当前状态为「{status}」，不能启动新的执行",
        )
