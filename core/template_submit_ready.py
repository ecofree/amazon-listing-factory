from __future__ import annotations

from typing import Any

from .price import normalize_price_value


class TemplateSubmitReadyError(RuntimeError):
    pass


def assert_submit_ready_price_current(
    listing_rows: list[dict[str, Any]],
    source_children: list[dict[str, Any]],
    *,
    mode: str,
) -> None:
    if mode != "submit_ready":
        return
    source_by_asin = {
        str(child.get("asin") or ""): child
        for child in source_children
        if isinstance(child, dict) and str(child.get("asin") or "").strip()
    }
    missing: list[str] = []
    for row in listing_rows:
        if not isinstance(row, dict) or row.get("row_type") != "Child":
            continue
        asin = str(row.get("asin") or "")
        offer = row.get("offer") if isinstance(row.get("offer"), dict) else {}
        row_price = normalize_price_value(offer.get("list_price"))
        source_child = source_by_asin.get(asin, {})
        normalized = source_child.get("normalized_facts") if isinstance(source_child.get("normalized_facts"), dict) else {}
        source_offer = source_child.get("offer") if isinstance(source_child.get("offer"), dict) else {}
        source_price = normalize_price_value(normalized.get("list_price")) or normalize_price_value(source_offer.get("list_price"))
        label = asin or row.get("sku") or "*"
        # A source may legitimately omit price.  Keep the cell blank in that
        # case; when a source price exists, the compiled row must still carry
        # the same value so real prices cannot silently drift.
        if source_price and not row_price:
            missing.append(f"{label} source_price={source_price} row_price=missing")
        elif source_price and _price_number(row_price) != _price_number(source_price):
            missing.append(f"{label} source_price={source_price} row_price={row_price}")
    if missing:
        raise TemplateSubmitReadyError(
            "submit_ready template price differs from the Apify source: " + "; ".join(missing)
        )


def _price_number(value: Any) -> str:
    text = normalize_price_value(value)
    try:
        return f"{float(text):.2f}" if text else ""
    except ValueError:
        return ""
