from __future__ import annotations

import html
import re
from typing import Any


_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d{1,7})(?:\.\d{1,2})?"
_PRICE = re.compile(rf"^(?:US\$|\$|USD\s*)?\s*({_NUMBER})\s*(?:USD)?$", re.IGNORECASE)


def normalize_price_value(value: Any) -> str:
    """Normalize one Apify/template price value or return an empty value.

    Only one standalone amount is accepted.  Ranges, prose such as ``Was
    $12.00``, decimal-comma values and embedded field text are intentionally
    rejected instead of being silently converted to a wrong price.
    """

    if isinstance(value, dict):
        for key in ("value", "amount", "salePrice", "currentPrice", "price", "raw", "list_price"):
            normalized = normalize_price_value(value.get(key))
            if normalized:
                return normalized
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return ""
        return f"{amount:.2f}" if amount > 0 else ""
    text = html.unescape(str(value or "")).strip()
    if not text:
        return ""
    match = _PRICE.fullmatch(text)
    if not match:
        return ""
    try:
        amount = float(match.group(1).replace(",", ""))
    except ValueError:
        return ""
    return f"{amount:.2f}" if amount > 0 else ""
