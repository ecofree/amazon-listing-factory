from __future__ import annotations

import re
from typing import Any


_BED_ENTITY_RE = re.compile(
    r"\b(?:bunk\s+beds?|loft\s+bed|platform\s+bed|daybed|bed\s+frame|trundle\s+bed|house\s+bed)\b",
    re.I,
)
_BROKEN_COMPOUND_COLONS = (
    re.compile(r"\bFull\s*:\s*Length\b", re.I),
    re.compile(r"\bHouse\s*:\s*Shaped\b", re.I),
    re.compile(r"\bLow\s*:\s*Profile\b", re.I),
    re.compile(r"\bSpace\s*:\s*Saving\b", re.I),
    re.compile(r"\bNoise\s*:\s*Free\b", re.I),
)
_TRAILING_UNATTACHED_MEASUREMENT = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*(?:\"|\u2033|in(?:ches?)?|ft|feet|foot|cm|mm|lb|lbs|pounds?|kg)\s*)$",
    re.I,
)
_REPEAT_EXCEPTIONS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into",
    "no", "of", "on", "or", "over", "the", "to", "under", "with",
}


def listing_title_quality_issues(title: Any, *, category: str = "") -> list[str]:
    text = re.sub(r"\s+", " ", str(title or "")).strip()
    if not text:
        return []
    issues: list[str] = []
    if any(pattern.search(text) for pattern in _BROKEN_COMPOUND_COLONS):
        issues.append("broken_hyphen_compound")
    if _TRAILING_UNATTACHED_MEASUREMENT.search(text):
        issues.append("title_ends_with_unattached_measurement")
    counts: dict[str, int] = {}
    for token in re.findall(r"[A-Za-z0-9]+", text.casefold()):
        if len(token) > 1 and token not in _REPEAT_EXCEPTIONS:
            counts[token] = counts.get(token, 0) + 1
    issues.extend(
        f"repeated_title_word:{word}" for word, count in sorted(counts.items()) if count > 2
    )
    category_key = re.sub(r"[^a-z0-9]+", "_", str(category).casefold()).strip("_")
    if category_key == "bed_frame" or _BED_ENTITY_RE.search(text):
        if len(re.findall(r"\bbunk\s+beds?\b", text, flags=re.I)) > 1:
            issues.append("duplicate_bunk_bed_entity")
        if re.search(r"\bintegrated\s+ladder\s*(?:&|and)\s+kits?\b", text, re.I):
            issues.append("unclear_integrated_ladder_kits")
        if re.search(r"\b(?:anti[- ]?tip(?:ping|pling)?|hardware)\s+kits?\b", text, re.I):
            issues.append("low_signal_kit_title_term")
    return list(dict.fromkeys(issues))
