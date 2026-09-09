"""Deterministic alias normalization for regional identities.

NORMALIZED_NAME_MATCH means exact equality after this safe normalization. It is
not fuzzy search and never chooses the nearest road/intersection automatically.
"""

from __future__ import annotations

import re
import unicodedata


_SEPARATORS = {
    "与": "-",
    "和": "-",
    "/": "-",
    "\\": "-",
    "／": "-",
    "、": "-",
    "_": "-",
    "－": "-",
    "—": "-",
    "–": "-",
}


def normalize_alias(value: str) -> str:
    """Return a conservative deterministic alias key.

    The helper handles whitespace, full/half-width forms, common separators, and
    the safe intersection suffix pair "交叉口"/"路口". It deliberately avoids edit
    distance, token guessing, or LLM-based normalization.
    """

    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    text = re.sub(r"\s+", "", text)
    for source, replacement in _SEPARATORS.items():
        text = text.replace(source, replacement)
    text = text.replace("十字路口", "路口")
    text = text.replace("交叉口", "路口")
    text = re.sub(r"-+", "-", text).strip("-")
    if text.endswith("路口") and "-" in text:
        text = text[:-2]
    return text
