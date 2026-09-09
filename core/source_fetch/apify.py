from __future__ import annotations

import html
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from ..io import load_env, read_json, safe_path_component, utc_now, write_json
from ..price import normalize_price_value
from ..job import load_job
from ..paths import FACTORY_ROOT
from ..plugin import ProductPlugin
from ..product_family import PRODUCT_FAMILY_POLICY_VERSION
from ..schema import validate_data
from ..text_evidence import clean_evidence_text, extract_measurements, has_bad_encoding
from .apify_client import ApifyClient
from products.generic_extractors import explicit_item_count, explicit_package_quantity, parse_pack_count


def env_any(values: dict[str, str], *names: str, required: bool = False, default: str = "") -> str:
    for name in names:
        value = values.get(name)
        if value:
            return value
    if required:
        raise RuntimeError(f"Missing environment variable; expected one of: {', '.join(names)}")
    return default


def _apify_tokens_from_env(values: dict[str, str], *, required: bool = False) -> list[str]:
    for name in ("APIFY_TOKENS", "APIFY_TOKEN"):
        raw_value = values.get(name, "")
        tokens = [token.strip() for token in raw_value.split(",") if token.strip()]
        if tokens:
            return tokens
    if required:
        raise RuntimeError("Missing environment variable; expected APIFY_TOKENS or APIFY_TOKEN")
    return []


def fetch_family(
    *,
    job_dir: str | Path,
    plugin: ProductPlugin,
    config_path: str = "",
    limit_children: int = 0,
    refresh: bool = False,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    job_path = Path(job_dir)
    job = load_job(job_path)
    config = config_path or job.get("config_path") or _default_config_path()
    # Process-level secrets/config override file defaults; this matches the
    # production controller and prevents a stale local env from replacing a
    # deliberately injected runtime credential.
    env = {**load_env(config), **os.environ}
    client = ApifyClient(
        tokens=_apify_tokens_from_env(env, required=True),
        actor_id=env_any(env, "APIFY_ACTOR_ID", required=True),
        marketplace=job.get("marketplace") or env_any(env, "AMAZON_MARKETPLACE", default="US"),
        deadline_monotonic=deadline_monotonic,
    )
    extractors = plugin.load_extractors()
    seed_asin = job["seed_asin"]
    raw_dir = job_path / "source" / "apify_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    seed_raw = _fetch_validated_raw(
        client, raw_dir, seed_asin, refresh, extractors=extractors, require_variations=True
    )
    variation = extractors.extract_variations(seed_raw, seed_asin)
    variants = _dedupe_variants(
        variation.get("variants", []),
        seed_asin,
        parent_asin=str(
            seed_raw.get("parentAsin")
            or seed_raw.get("parent_asin")
            or seed_raw.get("parentASIN")
            or ""
        ),
    )
    if limit_children:
        variants = variants[:limit_children]

    v3_by_index: dict[int, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []

    def fetch_variant(index: int, variant: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        asin = variant["asin"]
        if asin == seed_asin:
            raw = seed_raw
        else:
            raw = _fetch_validated_raw(
                client, raw_dir, asin, refresh, extractors=extractors, require_variations=False
            )
        specs = extractors.extract_specs(raw)
        images = extractors.image_urls(raw)
        specific = extractors.product_specific(raw) if hasattr(extractors, "product_specific") else specs
        sold_unit_count, sold_unit_count_source, sold_unit_conflict = _source_sold_unit_count(raw, specs, specific)
        explicit_package_count = explicit_package_quantity(raw)
        package_quantity = explicit_package_count or 1
        package_quantity_source = (
            "apify_explicit_package_quantity"
            if explicit_package_count is not None
            else "amazon_single_package_policy"
        )
        for facts in (specs, specific):
            facts.pop("number_of_items", None)
            facts.pop("item_package_quantity", None)
        variation_values = _variation_values(variant)
        if not variation_values:
            child_variations = extractors.extract_variations(raw, asin)
            own = next(
                (
                    row for row in child_variations.get("variants") or []
                    if isinstance(row, dict) and str(row.get("asin") or "") == asin
                ),
                {},
            )
            variation_values = _variation_values(own)
        if not variation_values:
            variation_values = {
                str(dimension): _clean_variation_value(str(dimension), specs[str(dimension)])
                for dimension in variation.get("dimensions") or []
                if str(dimension) in specs and _clean_variation_value(str(dimension), specs[str(dimension)])
            }
        if not variation_values:
            variation_values = _fallback_variation_values(specs, title=_source_title(raw))
        variation_missing = not variation_values
        description = _source_description(raw)
        title = _source_title(raw)
        bullets = _source_bullets(raw)
        review_summary = _source_review_summary(raw)
        offer = _source_offer(raw)
        normalized_facts = _normalized_child_facts(
            variation_values=variation_values,
            specs=specs,
            specific=specific,
            offer=offer,
            sold_unit_count=sold_unit_count,
            package_quantity=package_quantity,
            title=title,
            bullets=bullets,
            description=description,
        )
        if sold_unit_conflict:
            normalized_facts["sold_unit_count_status"] = "conflicted"
            normalized_facts["sold_unit_count_candidates"] = sold_unit_conflict
        v3_child = (
            {
                "asin": asin,
                "variation_values": variation_values,
                "title": title,
                "bullets": bullets,
                "review_summary": review_summary,
                "description": description,
                "specs": specs,
                "normalized_facts": normalized_facts,
                **({"offer": offer} if offer else {}),
                "sold_unit_count": sold_unit_count,
                "sold_unit_count_source": sold_unit_count_source,
                **({"sold_unit_count_status": "conflicted", "sold_unit_count_candidates": sold_unit_conflict} if sold_unit_conflict else {}),
                "package_quantity": package_quantity,
                "package_quantity_source": package_quantity_source,
                "reference_images": [{"url": url, "source": "apify"} for url in images],
                "risk_flags": ["variation_values_missing"] if variation_missing else [],
                "product_specific": {plugin.category_id: specific},
                "status": "ok",
            }
        )
        return index, v3_child

    indexed_variants = list(enumerate(variants))
    child_workers = _apify_child_workers(env, len(indexed_variants))
    if child_workers > 1:
        with ThreadPoolExecutor(max_workers=child_workers) as executor:
            futures = {executor.submit(fetch_variant, index, variant): variant for index, variant in indexed_variants}
            for future in as_completed(futures):
                variant = futures[future]
                try:
                    index, v3_child = future.result()
                    v3_by_index[index] = v3_child
                except Exception as exc:
                    errors.append({"asin": str(variant.get("asin") or ""), "error": f"{type(exc).__name__}: {exc}"})
    else:
        for index, variant in indexed_variants:
            try:
                item_index, v3_child = fetch_variant(index, variant)
                v3_by_index[item_index] = v3_child
            except Exception as exc:
                errors.append({"asin": str(variant.get("asin") or ""), "error": f"{type(exc).__name__}: {exc}"})

    v3_children = [v3_by_index[index] for index in sorted(v3_by_index)]
    _reconcile_child_template_facts(v3_children)

    fetched_at = utc_now()
    v3_family = {
        "protocol_version": "3.0",
        "product_type": plugin.product_type,
        "category_id": plugin.category_id,
        "source": {
            "type": "apify",
            "seed_asin": seed_asin,
            "fetched_at": fetched_at,
            "policy_version": PRODUCT_FAMILY_POLICY_VERSION,
            "raw_dir": str(raw_dir),
            "raw_dirs": {"apify": str(raw_dir)},
            "child_fetch_errors": errors,
            "expected_child_count": len(variants),
        },
        "family": {
            "parent_asin": variation["parent_asin"],
            "brand": job["brand"],
            "sku_prefix": job["sku_prefix"],
            "marketplace": job.get("marketplace", "US"),
            "variation_theme": variation["variation_theme"],
            "variation_dimensions": variation["dimensions"],
            "children": v3_children,
        },
        "product_specific": {plugin.category_id: {"extractor": "products/generic_extractors.py", "mapping": "manifest.extractors"}},
    }
    if not v3_children:
        raise RuntimeError("No child ASINs were fetched successfully; refusing to write an empty product family")
    validate_data(v3_family, "product_family.schema.json", label="product_family_v3")
    v3_path = job_path / "source" / "product_family_v3.json"
    write_json(v3_path, v3_family)
    _write_audit(job_path / "source" / "apify_audit.md", v3_family, errors)
    return v3_family


def _source_sold_unit_count(
    raw: dict[str, Any], specs: dict[str, Any], specific: dict[str, Any]
) -> tuple[int, str, list[int]]:
    raw_count = explicit_item_count(raw)
    if raw_count is not None:
        return raw_count, "apify_explicit_pack_count", []
    explicit: set[int] = set()
    invalid_explicit = False
    for facts in (specs, specific):
        for field in ("number_of_items",):
            value = facts.get(field)
            if value in (None, ""):
                continue
            text = str(value).strip()
            if not re.fullmatch(r"[1-9]\d*", text):
                invalid_explicit = True
                continue
            explicit.add(int(text))
    if len(explicit) > 1:
        return 1, "apify_conflicted_pack_count", sorted(explicit)
    if explicit:
        return explicit.pop(), "apify_explicit_pack_count", []
    if invalid_explicit:
        return 1, "apify_invalid_pack_count_default", []
    return 1, "amazon_single_unit_listing_policy", []


def _reconcile_child_template_facts(children: list[dict[str, Any]]) -> None:
    """Normalize template-critical facts that are directly evidenced by each child."""
    for child in children:
        if not isinstance(child, dict):
            continue
        variation = child.setdefault("variation_values", {})
        normalized = child.setdefault("normalized_facts", {})
        normalized_variation = normalized.setdefault("variation", {})
        if not str(normalized.get("color") or "").strip():
            color = _infer_color_from_child_source(child)
            if color:
                normalized["color"] = color
                normalized_variation.setdefault("color", color)
                variation.setdefault("color", color)


def _infer_color_from_child_source(child: dict[str, Any]) -> str:
    specs = child.get("specs") if isinstance(child.get("specs"), dict) else {}
    specific = child.get("product_specific") if isinstance(child.get("product_specific"), dict) else {}
    for container in (specs, specific):
        value = _explicit_fact_value(container, {"color", "colour", "color_name", "colour_name"})
        cleaned = _clean_variation_value("color", value)
        if cleaned:
            return cleaned
    return ""


def _explicit_fact_value(value: Any, keys: set[str]) -> Any:
    if not isinstance(value, dict):
        return ""
    for key, item in value.items():
        normalized = _normal_variation_key(str(key))
        if normalized in keys and item not in (None, "", [], {}):
            return item
    for item in value.values():
        nested = _explicit_fact_value(item, keys)
        if nested not in (None, "", [], {}):
            return nested
    return ""


def _dedupe_variants(
    variants: list[dict[str, Any]], seed_asin: str, *, parent_asin: str
) -> list[dict[str, Any]]:
    by_asin: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        asin = str(variant.get("asin") or "").strip()
        if not asin or (parent_asin and asin == parent_asin):
            continue
        if asin not in by_asin:
            order.append(asin)
            by_asin[asin] = dict(variant)
        else:
            for key, value in variant.items():
                if by_asin[asin].get(key) in (None, "") and value not in (None, ""):
                    by_asin[asin][key] = value
    if seed_asin and seed_asin != parent_asin and seed_asin not in by_asin:
        by_asin[seed_asin] = {"asin": seed_asin}
    ordered_asins = [seed_asin] if seed_asin in by_asin else []
    ordered_asins.extend(asin for asin in order if asin != seed_asin)
    return [by_asin[asin] for asin in ordered_asins]


def _fetch_validated_raw(
    client: ApifyClient,
    raw_dir: Path,
    asin: str,
    refresh: bool,
    *,
    extractors: Any,
    require_variations: bool,
) -> dict[str, Any]:
    path = raw_dir / f"{safe_path_component(asin, fallback='asin')}.json"
    if path.exists() and not refresh:
        cached = read_json(path)
        if not _raw_quality_issues(
            cached, extractors=extractors, seed_asin=asin, require_variations=require_variations
        ):
            return cached
    raw = client.fetch_product(asin)
    issues = _raw_quality_issues(
        raw, extractors=extractors, seed_asin=asin, require_variations=require_variations
    )
    if issues:
        raise RuntimeError(f"Apify result for {asin} is incomplete: {', '.join(issues)}")
    write_json(path, raw)
    return raw


def _raw_quality_issues(
    raw: dict[str, Any], *, extractors: Any, seed_asin: str, require_variations: bool
) -> list[str]:
    issues: list[str] = []
    if not isinstance(raw, dict) or not raw:
        return ["empty raw data"]
    if not _source_title(raw):
        issues.append("missing title")
    try:
        images = extractors.image_urls(raw)
    except Exception:
        images = []
    if not images:
        issues.append("missing image urls")
    if require_variations:
        try:
            variations = extractors.extract_variations(raw, seed_asin)
        except Exception:
            variations = {}
        if not variations.get("variants"):
            issues.append("missing variations")
    bullets = raw.get("bulletPoints") or raw.get("features") or []
    description = _source_description(raw)
    if not bullets and not str(description or "").strip():
        issues.append("missing bullets and description")
    return issues


def _apify_child_workers(env: dict[str, str], task_count: int) -> int:
    if task_count <= 1:
        return 1
    raw = env.get("AMAZON_FACTORY_APIFY_CHILD_WORKERS") or env.get("AMAZON_FACTORY_FETCH_WORKERS") or "4"
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        value = 4
    return max(1, min(8, value, task_count))


def _default_config_path() -> str:
    candidate = FACTORY_ROOT / "config.local.env"
    return str(candidate) if candidate.exists() else ""


def _variation_values(variant: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in variant.items():
        if key == "asin" or value in (None, ""):
            continue
        normalized = _normal_variation_key(str(key).replace("_name", ""))
        cleaned = _clean_variation_value(normalized, value)
        if cleaned:
            out[normalized] = cleaned
    return out


def _fallback_variation_values(specs: dict[str, Any], *, title: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("color", "colour", "size", "height", "dimensions", "style", "material"):
        value = _spec_lookup(specs, key)
        cleaned = _clean_variation_value(key, value)
        if cleaned:
            out[_normal_variation_key(key)] = cleaned
    pack = parse_pack_count(title)
    if pack:
        out.setdefault("pack", pack)
    return out


def _spec_lookup(specs: dict[str, Any], wanted: str) -> Any:
    target = _normal_variation_key(wanted)
    for key, value in specs.items():
        if _normal_variation_key(str(key)) == target and value not in (None, ""):
            return value
    return ""


def _normal_variation_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", str(value).strip().casefold()).strip("_")
    aliases = {"colour": "color", "colour_name": "color", "color_name": "color"}
    return aliases.get(key, key)


def _clean_variation_value(key: str, value: Any) -> str:
    text = _clean_source_text(value)
    if not text or _has_bad_encoding(text):
        return ""
    normalized_key = _normal_variation_key(key)
    if normalized_key == "color" and (_looks_like_measurement_or_pack(text) or not _looks_like_color_value(text)):
        return ""
    return text[:80]


def _has_bad_encoding(value: str) -> bool:
    return has_bad_encoding(value)


def _looks_like_measurement_or_pack(value: str) -> bool:
    text = value.casefold()
    return bool(
        re.search(r"\d", text)
        and re.search(r"\b(?:in|inch|ft|feet|cm|mm|pack|pcs?|pieces?)\b|[\"']", text)
    )


def _looks_like_color_value(value: str) -> bool:
    text = value.strip()
    if len(text) > 40:
        return False
    # Numeric shade names such as "3-Tone Brown" are legitimate color
    # variation values; measurements, pack counts, and dimensions are filtered
    # by _looks_like_measurement_or_pack before this predicate is used.
    if re.search(r"\d", text) and not re.search(r"\b\d+\s*[- ]?tone\b", text, re.I):
        return False
    return bool(re.search(r"[A-Za-z]", text))


def _normalized_child_facts(
    *,
    variation_values: dict[str, Any],
    specs: dict[str, Any],
    specific: dict[str, Any],
    offer: dict[str, str],
    sold_unit_count: int,
    package_quantity: int,
    title: str = "",
    bullets: list[Any] | None = None,
    description: str = "",
) -> dict[str, Any]:
    variation = {
        str(key): clean_evidence_text(value)
        for key, value in variation_values.items()
        if clean_evidence_text(value) and not has_bad_encoding(value)
    }
    color = _first_clean(variation, specs, specific, keys=("color", "colour", "color_name"))
    if color and (_looks_like_measurement_or_pack(color) or not _looks_like_color_value(color)):
        color = ""
    size = (
        _first_clean_by_key_priority(variation, keys=("size", "size_name", "size_class", "height"))
        or _first_clean_by_key_priority(specs, specific, keys=("size", "size_name", "size_class"))
    )
    physical_dimensions = _first_clean_by_key_priority(
        specs,
        specific,
        keys=("dimensions", "item_dimensions", "product_dimensions"),
    )
    style = _first_clean(variation, specs, specific, keys=("style", "style_name"))
    spec_measurements: list[str] = []
    spec_measurement_records: list[dict[str, str]] = []
    for facts in (specs, specific):
        for key, value in sorted(facts.items()):
            normalized_key = re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")
            if any(word in normalized_key for word in ("package", "shipping", "carton", "box_dimension")):
                continue
            if not any(word in normalized_key for word in (
                "item_dimension", "product_dimension", "overall_dimension", "height", "width", "depth", "length",
                "weight", "capacity", "load",
            )):
                continue
            text = f"{key}: {_plain_value(value)}"
            for item in extract_measurements(text):
                if item.get("kind") not in {"length_mm", "weight_g"}:
                    continue
                cleaned = str(item.get("text") or "").strip()
                if cleaned and cleaned not in spec_measurements:
                    spec_measurements.append(cleaned)
                    spec_measurement_records.append({"field": normalized_key, "text": cleaned})
    return {
        "variation": variation,
        "color": color,
        "size": size,
        "physical_dimensions": physical_dimensions,
        "style": style,
        "package": f"{package_quantity} count" if package_quantity else "",
        "list_price": str(offer.get("list_price") or ""),
        "currency": str(offer.get("currency") or ""),
        "sold_unit_count": int(sold_unit_count),
        "package_quantity": int(package_quantity),
        "spec_measurements": spec_measurements[:12],
        "spec_measurement_records": spec_measurement_records[:12],
        "resolved_facts": _resolve_structured_facts(
            title=title,
            bullets=bullets or [],
            description=description,
            specs=specs,
            specific=specific,
            variation=variation,
        ),
        "evidence": {
            "variation": "apify_variation_or_specs",
            "price": "apify_offer" if offer.get("list_price") else "",
            "measurements": "apify_specs",
        },
    }


def _resolve_structured_facts(
    *, title: str, bullets: list[Any], description: str,
    specs: dict[str, Any], specific: dict[str, Any], variation: dict[str, Any],
) -> dict[str, Any]:
    """Resolve repeatable structural facts once, with provenance.

    Downstream copy/template/image code must consume this result instead of
    independently choosing between a title, a spec field, and OCR-like text.
    The resolver is intentionally conservative: only facts with a clear
    numeric/product-part vocabulary are included here.
    """
    text = " ".join([str(title or ""), *(str(value or "") for value in bullets), str(description or "")])
    fact_patterns = {
        "number_of_drawers": r"(?<!\d)(\d{1,2})\s*(?:deep\s+)?drawers?\b",
        "number_of_doors": r"(?<!\d)(\d{1,2})\s*doors?\b",
        "number_of_shelves": r"(?<!\d)(\d{1,2})\s*(?:adjustable\s+|fixed\s+)?shelves?\b",
    }
    resolved: dict[str, Any] = {}
    for fact_name, pattern in fact_patterns.items():
        candidates: list[dict[str, Any]] = []
        for container_name, container in (("variation", variation), ("spec", specs), ("specific", specific)):
            if not isinstance(container, dict):
                continue
            for key, value in container.items():
                normalized_key = re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")
                if fact_name not in normalized_key and not (
                    fact_name == "number_of_shelves" and "shelf" in normalized_key
                ):
                    continue
                match = re.search(r"(?<!\d)(\d{1,2})(?!\d)", str(value or ""))
                if match:
                    candidates.append({"value": int(match.group(1)), "source": container_name, "field": str(key)})
        text_values = sorted({int(match.group(1)) for match in re.finditer(pattern, text, flags=re.I)})
        if text_values:
            for value in text_values:
                candidates.append({"value": value, "source": "listing_text", "field": "title_bullets_description"})
        if not candidates:
            continue
        # Structured fields (variation/spec/specific) outweigh listing prose, and
        # repeated prose mentions of the same value still count as one vote.
        weights = {"variation": 2, "spec": 2, "specific": 2, "listing_text": 1}
        counts: dict[int, int] = {}
        for candidate in candidates:
            source = str(candidate["source"])
            counts[int(candidate["value"])] = counts.get(int(candidate["value"]), 0) + weights.get(source, 1)
        best_count = max(counts.values())
        leaders = sorted(value for value, count in counts.items() if count == best_count)
        status = "confirmed" if len(leaders) == 1 and (best_count >= 2 or len(counts) == 1) else "conflicted"
        best_value = leaders[0] if status == "confirmed" else ""
        resolved[fact_name] = {
            "value": best_value,
            "status": status,
            "candidates": sorted(counts),
            "evidence": [item for item in candidates if best_value != "" and int(item["value"]) == best_value],
        }
    return resolved


def _first_clean(*sources: dict[str, Any], keys: tuple[str, ...]) -> str:
    wanted = {_normal_variation_key(key) for key in keys}
    for source in sources:
        for key, value in source.items():
            if _normal_variation_key(str(key)) not in wanted:
                continue
            text = clean_evidence_text(value)
            if text and not has_bad_encoding(text):
                return text[:120]
    return ""


def _first_clean_by_key_priority(*sources: dict[str, Any], keys: tuple[str, ...]) -> str:
    for wanted in keys:
        normalized_wanted = _normal_variation_key(wanted)
        for source in sources:
            for key, value in source.items():
                if _normal_variation_key(str(key)) != normalized_wanted:
                    continue
                text = clean_evidence_text(value)
                if text and not has_bad_encoding(text):
                    return text[:120]
    return ""


def _plain_value(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_plain_value(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_plain_value(item) for item in value)
    return str(value or "")


def _source_description(raw: dict[str, Any]) -> str:
    for key in ("description", "productDescription"):
        text = _clean_source_text(raw.get(key))
        if text:
            return text
    aplus = raw.get("aPlusContent")
    if not isinstance(aplus, dict):
        return ""
    raw_text = _clean_source_text(aplus.get("rawText"))
    if _meaningful_aplus_text(raw_text):
        return raw_text
    return ""


def _source_title(raw: dict[str, Any]) -> str:
    return _clean_source_text(raw.get("title") or raw.get("productTitle") or "")


def _source_bullets(raw: dict[str, Any]) -> list[str]:
    values = raw.get("bulletPoints") or raw.get("features") or []
    if isinstance(values, str):
        values = [values]
    return list(dict.fromkeys(
        text for text in (_clean_source_text(value) for value in values if value is not None) if text
    ))[:12]


def _source_review_summary(raw: dict[str, Any]) -> str:
    for key in ("reviewSummary", "reviewsSummary", "customerReviewSummary", "aiReviewsSummary"):
        value = raw.get(key)
        if isinstance(value, dict):
            text = _clean_source_text(value.get("text") or value.get("summary") or value.get("body") or "")
        else:
            text = _clean_source_text(value)
        if text:
            return text
    snippets: list[str] = []
    for key in ("reviews", "customerReviews", "topReviews"):
        value = raw.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                title = _clean_source_text(item.get("title") or item.get("summary") or "")
                body = _clean_source_text(item.get("text") or item.get("body") or item.get("content") or "")
                text = ". ".join(part for part in (title, body) if part)
            else:
                text = _clean_source_text(item)
            if text:
                snippets.append(text)
            if len(snippets) >= 6:
                break
        if snippets:
            break
    return " ".join(snippets)


def _source_offer(raw: dict[str, Any]) -> dict[str, str]:
    price = _source_price(raw)
    if not price:
        return {}
    currency = _clean_source_text(
        raw.get("currency")
        or raw.get("priceCurrency")
        or raw.get("currencyCode")
        or _deep_first(raw, ("currency", "priceCurrency", "currencyCode"))
    )
    return {"list_price": price, "currency": currency or "USD", "source": "apify"}


def _source_price(raw: dict[str, Any]) -> str:
    for key in (
        "salePrice",
        "currentPrice",
        "buyBoxPrice",
        "price",
        "priceValue",
        "amount",
        "listPrice",
    ):
        price = normalize_price_value(raw.get(key))
        if price:
            return price
    return normalize_price_value(_deep_first(raw, ("salePrice", "currentPrice", "buyBoxPrice", "price", "priceValue", "amount", "listPrice")))


def _deep_first(value: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if value.get(key) not in (None, "", [], {}):
                return value.get(key)
        for item in value.values():
            found = _deep_first(item, keys)
            if found not in (None, "", [], {}):
                return found
    if isinstance(value, list):
        for item in value:
            found = _deep_first(item, keys)
            if found not in (None, "", [], {}):
                return found
    return None


def _clean_source_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\b(Description|Product description)(?=[A-Z])", r"\1 ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:product\s+description|description)\s*", "", text, flags=re.IGNORECASE).strip()
    return clean_evidence_text(text)


def _meaningful_aplus_text(text: str) -> bool:
    if len(text) < 60:
        return False
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    boilerplate = {
        "product description previous page next page",
        "product description",
        "previous page next page",
    }
    return normalized not in boilerplate


def _write_audit(path: Path, family: dict[str, Any], errors: list[dict[str, str]]) -> None:
    children = family["family"]["children"]
    lines = [
        "# Apify Family Fetch Audit",
        "",
        f"- Protocol: `{family['protocol_version']}`",
        f"- Product Type: `{family['product_type']}`",
        f"- Seed ASIN: `{family['source']['seed_asin']}`",
        f"- Parent ASIN: `{family['family']['parent_asin']}`",
        f"- Children: {len(children)}",
        f"- Variation Theme: `{family['family']['variation_theme']}`",
        "",
        "| ASIN | Variation | Images | Status | Image Source |",
        "|---|---|---:|---|---|",
    ]
    for child in children:
        variation = ", ".join(f"{k}={v}" for k, v in child.get("variation_values", {}).items())
        image_sources = sorted({str(item.get("source") or "") for item in child.get("reference_images", []) if isinstance(item, dict)})
        lines.append(
            f"| `{child['asin']}` | {variation} | {len(child.get('reference_images', []))} | "
            f"{child.get('status', 'ok')} | {', '.join(image_sources) or '-'} |"
        )
    if errors:
        lines.extend(["", "## Errors", ""])
        for item in errors:
            lines.append(f"- `{item.get('asin')}`: {item.get('error')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
