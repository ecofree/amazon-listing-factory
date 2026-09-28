from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .io import read_json
from .schema import validate_data


PRODUCT_FAMILY_POLICY_VERSION = "product-family-v3-resolved-facts-v12-scoped-counts-color"


def fact_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")


def fact_resolutions(child: dict[str, Any]) -> dict[str, dict[str, Any]]:
    normalized = child.get('normalized_facts') or {}
    rows = {fact_key(key): dict(row) for key, row in (normalized.get('resolved_facts') or {}).items()
            if isinstance(row, dict) and row.get('status') in {'confirmed', 'conflicted'}}
    count_status = normalized.get('sold_unit_count_status') or child.get('sold_unit_count_status')
    count = normalized.get('sold_unit_count', child.get('sold_unit_count'))
    if count_status == 'conflicted':
        rows['sold_unit_count'] = {'status': 'conflicted', 'value': None,
                                  'candidates': normalized.get('sold_unit_count_candidates') or child.get('sold_unit_count_candidates') or []}
    elif child.get('sold_unit_count_source') == 'apify_explicit_pack_count' and count is not None:
        rows['sold_unit_count'] = {'status': 'confirmed', 'value': count}
    for key, row in rows.items():
        candidates = list(row.get('candidates') or [])
        for container in [child.get('specs') or {}, *(child.get('product_specific') or {}).values()]:
            if isinstance(container, dict):
                candidates.extend(value for name, value in container.items() if fact_key(name) == key and value not in (None, '', [], {}))
        if candidates:
            row['candidates'] = list({str(value): value for value in candidates}.values())
    return rows


def effective_product_facts(child: dict[str, Any], category_id: str = '') -> dict[str, Any]:
    """Project existing ProductFamily decisions; never resolve conflicts again."""
    facts = {fact_key(key): value for key, value in (child.get('specs') or {}).items()
             if not fact_key(key).startswith('source_') and value not in (None, '', [], {})}
    for category, values in (child.get('product_specific') or {}).items():
        if isinstance(values, dict) and (not category_id or category == category_id):
            facts.update({fact_key(key): value for key, value in values.items()
                          if not fact_key(key).startswith('source_') and value not in (None, '', [], {})})
    normalized = child.get('normalized_facts') or {}
    for source in (normalized.get('variation') or {}, normalized, child.get('variation_values') or {}):
        for key in ('color', 'size', 'style', 'dimensions', 'product_dimensions', 'physical_dimensions',
                    'length', 'width', 'height', 'item_depth', 'length_unit', 'width_unit', 'height_unit',
                    'item_depth_unit', 'item_weight', 'item_weight_unit', 'weight'):
            if facts.get(key) in (None, '', [], {}) and source.get(key) not in (None, '', [], {}):
                facts[key] = source[key]
    for key in ('sold_unit_count', 'package_quantity'):
        value = normalized.get(key, child.get(key))
        if value not in (None, '', [], {}):
            facts[key] = value
    for key, row in fact_resolutions(child).items():
        facts.pop(key, None)
        if key == 'sold_unit_count':
            facts.pop('number_of_items', None)
            facts.pop('item_count', None)
        if row['status'] == 'confirmed' and row.get('value') not in (None, '', [], {}):
            facts[key] = row['value']
    return facts


def supports_fact(facts: dict[str, Any], pattern: str, *, claim_context: str = "") -> bool:
    """A specific affirmative property, not the presence of its dictionary key."""
    matcher = re.compile(pattern, re.I)
    supported = False
    denied = False
    def owner(text: str) -> str:
        for name, terms in (('packaging', r'packaging|shipping|package'), ('prop', r'props?'),
                            ('shelf', r'shel(?:f|ves)'), ('drawer', r'drawers?'), ('door', r'doors?'),
                            ('coating', r'coating|paint|finish')):
            if re.search(r'\b(?:' + terms + r')\b', text, re.I):
                return name
        return 'product'
    claimed_owner = owner(claim_context)

    def visit(value: Any, context: str = '') -> None:
        nonlocal supported, denied
        if isinstance(value, dict):
            for key, item in value.items():
                if key == '_fact_resolutions':
                    for name, record in item.items():
                        if matcher.search(name.replace('_', ' ')) and record.get('status') == 'conflicted':
                            denied = True
                    continue
                visit(item, f'{context} {key}'.replace('_', ' ').strip())
        elif isinstance(value, list):
            for item in value:
                visit(item, context)
        else:
            for clause in re.split(r'[.;\n]|\bbut\b', str(value), flags=re.I):
                statement = f'{context}: {clause}'
                if owner(statement) != claimed_owner:
                    continue
                for match in matcher.finditer(statement):
                    before, after = statement[:match.start()], statement[match.end():]
                    negative = value is None or value is False or str(value).strip().lower() in {'0', 'no', 'false', 'unknown', 'unconfirmed'}
                    negative = negative or bool(re.search(r"\b(?:not|no|without|isn't|is not)\s+(?:\w+\s+){0,2}$", before, re.I))
                    negative = negative or bool(re.match(r'\s*(?:is|:)?\s*(?:false|no|unknown|unconfirmed|not (?:confirmed|supported|available|applicable))\b', after, re.I))
                    if negative:
                        denied = True
                    elif matcher.search(clause) or str(value).strip().casefold() in {'true', 'yes', '1', 'confirmed', 'supported'}:
                        supported = True
                    elif re.search(r'\bwarranty\b', context, re.I) and re.fullmatch(r'\s*(?:lifetime|\d+[- ](?:years?|months?))\s*', clause, re.I):
                        supported = True
    visit(facts)
    return supported and not denied


def whole_part_counts(text: str, part: str) -> list[str]:
    """Unqualified totals only; local counts still require their own evidence review."""
    words = {'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9', 'ten': '10'}
    normalized = re.sub(r'\b(' + '|'.join(words) + r')\b', lambda m: words[m[0].lower()], text, flags=re.I)
    local = r'upper|lower|top|bottom|left|right|internal|interior|adjustable|fixed'
    values = []
    for match in re.finditer(r'\b(\d+)\s*[- ]?(?:(?:' + local + r'|deep)\s+)*' + part + r'\b', normalized, re.I):
        before, after = normalized[:match.start()], normalized[match.end():]
        if (re.search(r'\b(?:' + local + r')\b', match[0], re.I)
                or re.search(r'\b(?:' + local + r')(?:\s+(?:cabinet|compartment|section))?\s*[: -]?\s*$', before, re.I)
                or re.match(r'\s+(?:(?:in|inside|within|for|of|at)\s+(?:the\s+)?)?(?:' + local + r')\b', after, re.I)):
            continue
        values.append(match[1])
    return values


def fact_statement_issues(text: str, resolutions: dict[str, dict[str, Any]]) -> list[str]:
    """Reject statements about the same scope as a resolved fact."""
    issues = []
    count_objects = {'number_of_doors': 'doors?', 'number_of_drawers': 'drawers?', 'number_of_shelves': 'shel(?:f|ves)'}
    for key, row in resolutions.items():
        values = []
        if key in count_objects:
            values = whole_part_counts(text, count_objects[key])
        elif key == 'sold_unit_count':
            normalized = re.sub(r'\b(one|two|three|four|five|six|seven|eight|nine|ten)\b',
                                lambda m: str(('one two three four five six seven eight nine ten'.split()).index(m[0].lower()) + 1), text, flags=re.I)
            values = re.findall(r'\b(?:set|pack|bundle) of (\d+)\b|\b(\d+)[ -]pack\b', normalized, re.I)
            values = [a or b for a, b in values]
        else:
            for value in row.get('candidates') or []:
                if isinstance(value, str) and len(value) >= 3 and re.search(r'\b' + re.escape(value) + r'\b', text, re.I):
                    values.append(value)
        if values and (row.get('status') == 'conflicted' or any(str(value).casefold() != str(row.get('value')).casefold() for value in values)):
            issues.append(key)
    return issues


class ProductFamilyError(RuntimeError):
    pass


def read_product_family(job_dir: str | Path) -> dict[str, Any]:
    job_path = Path(job_dir)
    path = job_path if job_path.name == "product_family_v3.json" else job_path / "source" / "product_family_v3.json"
    data = read_json(path)
    try:
        validate_data(data, "product_family.schema.json", label="ProductFamilyV3")
    except Exception as exc:
        raise ProductFamilyError(f"Unsupported ProductFamilyV3; create a new job or rerun fetch: {exc}") from exc
    policy = str((data.get("source") or {}).get("policy_version") or "")
    if policy != PRODUCT_FAMILY_POLICY_VERSION:
        raise ProductFamilyError(
            f"Unsupported ProductFamilyV3 extraction policy {policy or 'missing'}; create a new job or rerun fetch"
        )
    asins = [str(row.get("asin") or "") for row in data["family"]["children"]]
    if len(asins) != len(set(asins)):
        raise ProductFamilyError("ProductFamilyV3 contains duplicate child ASINs")
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    errors = source.get("child_fetch_errors") if isinstance(source.get("child_fetch_errors"), list) else []
    failed_asins = [str(row.get("asin") or "") for row in errors if isinstance(row, dict)]
    if len(failed_asins) != len(set(failed_asins)):
        raise ProductFamilyError("ProductFamilyV3 contains duplicate child fetch errors")
    if set(asins) & set(failed_asins):
        raise ProductFamilyError("ProductFamilyV3 child cannot be both successful and failed")
    if len(asins) + len(failed_asins) != int(source.get("expected_child_count") or 0):
        raise ProductFamilyError(
            "ProductFamilyV3 successful and failed child inventory does not match expected_child_count"
        )
    return data
