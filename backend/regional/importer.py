"""Deterministic Pilot Region Context Pack import helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from backend.regional.repository import SQLiteRegionalRepository


def load_context_pack_from_directory(package_dir: str | Path) -> Dict[str, Any]:
    """Load a human-maintained context pack directory.

    Expected files:
      region.json
      roads.json
      intersections.json
      road_relations.json
      pois.json

    An optional package.json may provide packageVersion/provenance defaults.
    """

    root = Path(package_dir)
    base: Dict[str, Any] = {}
    manifest = root / "package.json"
    if manifest.exists():
        with manifest.open("r", encoding="utf-8") as f:
            base = json.load(f)
    base.setdefault("packageVersion", 1)
    with (root / "region.json").open("r", encoding="utf-8") as f:
        base["region"] = json.load(f)
    for key, filename in [
        ("roads", "roads.json"),
        ("intersections", "intersections.json"),
        ("roadRelations", "road_relations.json"),
        ("pois", "pois.json"),
    ]:
        path = root / filename
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                base[key] = json.load(f)
        else:
            base.setdefault(key, [])
    return base


def import_context_pack(
    package: Dict[str, Any],
    *,
    repository: Optional[SQLiteRegionalRepository] = None,
) -> Dict[str, Any]:
    """Import a context pack using the regional repository transaction."""

    repo = repository or SQLiteRegionalRepository()
    return repo.import_context_pack(package)
