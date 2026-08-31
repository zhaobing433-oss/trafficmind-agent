"""Shared constants and errors for Phase21 regional core data."""

from __future__ import annotations

from typing import Any, Dict, List


VALID_ENTITY_TYPES = {"road", "intersection"}
VALID_RELATION_TYPES = {"connects", "upstream", "downstream", "adjacent", "alternate"}
VALID_POI_TYPES = {
    "school",
    "hospital",
    "station",
    "commercial_area",
    "government",
    "construction",
    "other_critical",
}
VALID_VERIFICATION_STATUSES = {"verified", "unverified", "synthetic"}


class RegionalValidationError(ValueError):
    """Raised when a context pack or regional write fails product validation."""

    def __init__(self, errors: List[Dict[str, Any]]):
        self.errors = errors
        super().__init__("regional validation failed")


def validation_error(path: str, message: str, code: str = "invalid") -> Dict[str, str]:
    return {"path": path, "message": message, "code": code}
