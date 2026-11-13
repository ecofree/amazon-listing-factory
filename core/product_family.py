from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .io import read_json
from .schema import validate_data


MEASUREMENT_FACTS = {'height', 'item_weight', 'weight_capacity', 'load_capacity', 'item_depth'}


def physical_fact_field(path: str) -> bool:
    """Keep unfamiliar product facts; exclude only named operational metadata.

    Planning separately includes any excluded field actually cited by the design.
    """
    return path.startswith(('product.specs.', 'product.product_specific.', 'product.fact_resolutions.')) and not (
        {'shipping_box_code', 'best_sellers_rank', 'sales_rank', 'availability', 'price'} & set(path.split('.')))

PRODUCT_FAMILY_POLICY_VERSION = "product-family-v3-resolved-facts-v21-semantic-fields-and-nominal-size"


def fact_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")
    return {'colour': 'color', 'colour_name': 'color', 'color_name': 'color', 'size_name': 'size',
            'size_class': 'size', 'style_name': 'style'}.get(key, key)


def identity_values_equal(left: str, right: str) -> bool:
    """Known lexical aliases or an equivalent whole variation measurement; never vote away a conflict."""
    normalize = lambda text: re.sub(r'[-_\s]+', ' ', str(text).casefold()).strip()
    a, b = normalize(left), normalize(right)
    aliases = {'twin extra long': 'twin xl', 'twinxl': 'twin xl', 'cal king': 'california king'}
    if aliases.get(a, a) == aliases.get(b, b):
        return True
    from .text_evidence import extract_measurements, measurement_values_match, normalize_text
    first, second = extract_measurements(left), extract_measurements(right)
    if len(first) != 1 or len(second) != 1:
        return False
    remaining = lambda text, measurement: re.sub(r'[^a-z0-9]+', ' ', normalize_text(text).casefold().replace(measurement['raw_text'].casefold(), '')).strip()
    return remaining(left, first[0]) == remaining(right, second[0]) and measurement_values_match(left, right)


def fact_resolutions(child: dict[str, Any]) -> dict[str, dict[str, Any]]:
    normalized = child.get('normalized_facts') or {}
    rows = {fact_key(key): dict(row) for key, row in (normalized.get('resolved_facts') or {}).items()
            if isinstance(row, dict) and row.get('status') in {'confirmed', 'conflicted', 'unconfirmed'}}
    count_status = normalized.get('sold_unit_count_status') or child.get('sold_unit_count_status')
    if child.get('sold_unit_count_source') in {'apify_invalid_pack_count','apify_missing_pack_count'}:
        count_status = 'unconfirmed'
    count = normalized.get('sold_unit_count', child.get('sold_unit_count'))
    if count_status in {'conflicted', 'unconfirmed'}:
        rows['sold_unit_count'] = {'status': count_status, 'value': None,
                                  'candidates': normalized.get('sold_unit_count_candidates') or child.get('sold_unit_count_candidates') or []}
    elif child.get('sold_unit_count_source') == 'apify_explicit_pack_count' and count is not None:
        rows['sold_unit_count'] = {'status': 'confirmed', 'value': count}
    if child.get('package_quantity_source') == 'apify_missing_package_quantity':
        rows['package_quantity'] = {'status':'unconfirmed','value':None}
    for key, row in rows.items():
        candidates = list(row.get('candidates') or [])
        for container in [child.get('specs') or {}, *(child.get('product_specific') or {}).values()]:
            if isinstance(container, dict):
                for name, value in container.items():
                    if fact_key(name) == key and value not in (None, '', [], {}):
                        if key in MEASUREMENT_FACTS and container.get(name + '_unit'):
                            value = f"{value} {container[name + '_unit']}"
                        candidates.append(value)
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
        source = {fact_key(key): value for key, value in source.items()}
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
        if row['status'] != 'confirmed':
            facts.pop(key + '_unit', None)
            if key == 'dimensions':
                for derived in ('physical_dimensions', 'product_dimensions', 'length', 'width', 'height', 'item_depth'):
                    facts.pop(derived, None)
                    facts.pop(derived + '_unit', None)
        if key == 'sold_unit_count':
            facts.pop('number_of_items', None)
            facts.pop('item_count', None)
        if row['status'] == 'confirmed' and row.get('value') not in (None, '', [], {}):
            facts[key] = row['value']
            if key in MEASUREMENT_FACTS:
                from products.generic_extractors import parse_quantity_unit
                quantity = parse_quantity_unit(str(row['value']))
                if quantity:
                    facts[key], facts[key + '_unit'] = quantity
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
                        if matcher.search(name.replace('_', ' ')) and record.get('status') != 'confirmed':
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
    local = r'upper|lower|top|bottom|left|right|sides?|internal|interior|adjustable|fixed|base(?=\s+(?:cabinet|compartment|section)\b)'
    local_owner = r'upper|lower|top|bottom|left|right|sides?|internal|interior|base(?=\s+(?:cabinet|compartment|section)\b)'
    owner_prefix = (r'\b(?:' + local_owner + r')(?:\s+(?:cabinet|compartment|section))?'
                    r'\s*(?:[: -]\s*|(?:holds?|contains?|includes?|has|have|adds?|features?)'
                    r'\s+(?:a\s+total\s+of\s+)?)?$')
    values = []
    for match in re.finditer(r'\b(\d+)\s*[- ]?(?:(?:' + local + r'|deep)\s+)*' + part + r'\b', normalized, re.I):
        before, after = normalized[:match.start()], normalized[match.end():]
        if (re.search(r'\b(?:' + local + r')\b', match[0], re.I)
                or re.search(owner_prefix, before, re.I)
                or re.match(r'\s+(?:(?:in|inside|within|for|of|at)\s+(?:the\s+)?)?(?:' + local + r')\b', after, re.I)):
            continue
        values.append(match[1])
    return values


def fact_statement_issues(text: str, resolutions: dict[str, dict[str, Any]], *, product_title: str = '') -> list[str]:
    """Reject statements about the same scope as a resolved fact."""
    issues = []
    count_objects = {'number_of_doors': 'doors?', 'number_of_drawers': 'drawers?', 'number_of_shelves': 'shel(?:f|ves)'}
    from products.generic_extractors import MATERIAL_OWNERS
    for key, row in resolutions.items():
        values = []
        if key in count_objects:
            values = whole_part_counts(text, count_objects[key])
        elif key == 'sold_unit_count':
            from products.generic_extractors import product_pack_counts
            values = [str(value) for value in product_pack_counts(text, title=product_title)]
        elif key == 'tip_count':
            for claim in re.finditer(r'\b(\d+(?:,\d{3})*)[ -]+((?:(?:dense|lush|pine|PVC|branch)[ -]+)*)tips?\b', text, re.I):
                if (claim[2] or re.match(r'[ -]+(?:artificial|pine|tree|branches|build|create|provide)\b',text[claim.end():],re.I)
                        or re.search(r'\b(?:tree|trees)\s+(?:contains?|containing|has|having|with)\s*$',text[:claim.start()],re.I)):
                    values.append(claim[1].replace(',', ''))
            values.extend(n.replace(',', '') for n in re.findall(r'\b(?:number of (?:branch )?tips|(?:branch )?tip count)\s*:\s*(\d+(?:,\d{3})*)',text,re.I))
        elif key in {'width','length','height','item_depth'} and any(r.get('scope_conflict') for r in row.get('evidence', [])):
            from .copy_measurements import _records
            axis = 'depth' if key == 'item_depth' else key
            values = [r['text'] for r in _records(text) if r['owner'] == 'product' and r['axis'] == axis]
        else:
            for value in row.get('candidates') or []:
                if not isinstance(value, str) or len(value) < 3:
                    continue
                for match in re.finditer(r'\b' + re.escape(value) + r'\b', text, re.I):
                    if key in MATERIAL_OWNERS:
                        before, after = text[max(0, match.start()-45):match.start()], text[match.end():match.end()+45]
                        owner = _material_claim_owner(before, after)
                        if owner != MATERIAL_OWNERS[key]:
                            whole = resolutions.get('material') or {}
                            if (owner == 'product' and key != 'material' and
                                    (re.search(r'\b(?:entirely|wholly|entire|whole)\s+(?:made\s+)?(?:of\s+)?$', before, re.I)
                                     or re.match(r'\s+(?:trees?|cabinets?|chairs?)\b', after, re.I))
                                    and not (whole.get('status') == 'confirmed' and str(whole.get('value')).casefold() == value.casefold())):
                                issues.append(key)
                            continue
                    values.append(value)
        def matches(value):
            expected = str(row.get('value'))
            if key == 'tip_count':
                return str(value).replace(',', '') == expected.replace(',', '')
            if key == 'size' or key in MEASUREMENT_FACTS:
                return identity_values_equal(str(value), expected)
            return str(value).casefold() == expected.casefold()
        if values and (row.get('status') != 'confirmed' or any(not matches(value) for value in values)):
            issues.append(key)
    return list(dict.fromkeys(issues))


def _material_claim_owner(before: str, after: str) -> str:
    for owner, noun in (('leaf', r'leaves|leaf'), ('trunk', r'trunk'), ('pot', r'pot|planter'),
                        ('frame', r'(?:bed\s+)?frame'), ('top', r'top|tabletop|countertop'), ('fabric', r'fabric')):
        if (re.match(r'\s+(?:' + noun + r')\b', after, re.I)
                or re.search(r'\b(?:' + noun + r')\s+(?:material\s+)?(?:(?:is|are|made|constructed)\s+)*(?:of|from)?\s*$', before, re.I)):
            return owner
    return 'product'


def family_variation_issues(family: dict[str, Any], *, allowed_themes: list[str] | None = None) -> list[str]:
    """Validate the evidenced relation once, for production admission and templates."""
    dimensions = family.get('variation_dimensions') or []
    theme = str(family.get('variation_theme') or '')
    issues = []
    if family.get('unconfirmed_variant_asins'):
        issues.append('Source lists disagree on variant membership: ' + ', '.join(family['unconfirmed_variant_asins']))
    if not dimensions or not theme:
        return [*issues, 'Source variation dimensions/theme are missing for parent/child output']
    from products.generic_extractors import theme_from_dimensions
    if sorted(fact_key(v) for v in theme.split('/')) != sorted(fact_key(v) for v in dimensions):
        issues.append('Variation theme does not describe the evidenced source axes')
    if allowed_themes is not None and not theme_from_dimensions(dimensions, allowed_themes):
        issues.append(f'Source variation theme {theme} has no approved category template mapping')
    previous = []
    for child in family.get('children') or []:
        values = {fact_key(k): str(v).strip() for k,v in (child.get('variation_values') or {}).items()}
        current = [values.get(fact_key(d), '') for d in dimensions]
        if 'number_of_items' in dimensions:
            count = fact_resolutions(child).get('sold_unit_count') or {}
            if count.get('status') != 'confirmed' or values.get('number_of_items') != str(count.get('value')):
                issues.append(f"Variation quantity lacks a matching confirmed sold count: {child.get('asin')}")
        if not all(current):
            issues.append(f"Missing source variation values for {child.get('asin')}")
            continue
        for asin, prior in previous:
            if all(identity_values_equal(a,b) for a,b in zip(prior,current)):
                issues.append(f"Duplicate variation tuple: {asin} and {child.get('asin')}")
        previous.append((child.get('asin'), current))
    return issues


class ProductFamilyError(RuntimeError):
    pass


def read_product_family(job_dir: str | Path, *, allow_metadata_stale: bool = False) -> dict[str, Any]:
    job_path = Path(job_dir)
    path = job_path if job_path.name == "product_family_v3.json" else job_path / "source" / "product_family_v3.json"
    data = read_json(path)
    try:
        validate_data(data, "product_family.schema.json", label="ProductFamilyV3")
    except Exception as exc:
        raise ProductFamilyError(f"Unsupported ProductFamilyV3; preserve this job and explicitly revalidate its sources under the current fact contract; do not relabel old evidence: {exc}") from exc
    policy = str((data.get("source") or {}).get("policy_version") or "")
    if policy != PRODUCT_FAMILY_POLICY_VERSION:
        raise ProductFamilyError(
            f"Unsupported ProductFamilyV3 extraction policy {policy or 'missing'}; preserve this job and explicitly revalidate its sources, without resetting unresolved receipts"
        )
    identity = data['source']['request_identity']
    if (identity['seed_asin'] != data['source']['seed_asin'] or identity['marketplace'] != data['family']['marketplace']
            or identity['category_id'] != data['category_id']):
        raise ProductFamilyError('ProductFamily source identity disagrees with its own projection')
    root = path.parent.parent
    if (root / 'job.json').is_file():
        from .job import load_job
        job = load_job(root)
        if any(identity[k] != str(job.get(k) or ('US' if k == 'marketplace' else '')).upper() for k in ('seed_asin', 'marketplace')) or identity['category_id'] != job['category_id']:
            raise ProductFamilyError('ProductFamily belongs to another requested source identity; explicit reconciliation required')
        if not allow_metadata_stale and any(data['family'][k] != job[k] for k in ('brand', 'sku_prefix')):
            raise ProductFamilyError('ProductFamily operator metadata is stale; rerun fetch for local reprojection without a new source request')
    asins = [str(row.get("asin") or "") for row in data["family"]["children"]]
    if len(asins) != len(set(asins)):
        raise ProductFamilyError("ProductFamilyV3 contains duplicate child ASINs")
    for child in data['family']['children']:
        for field, source, explicit in (('sold_unit_count','sold_unit_count_source','apify_explicit_pack_count'),
                                        ('package_quantity','package_quantity_source','apify_explicit_package_quantity')):
            value=child[field]
            if child[source]==explicit:
                if type(value) is not int or value<1:raise ProductFamilyError(f'Explicit {field} needs a positive integer')
            elif value is not None:
                raise ProductFamilyError(f'Unconfirmed {field} must stay null, not a business default')
            normalized=child.get('normalized_facts') or {}
            if field in normalized and normalized[field]!=value:
                raise ProductFamilyError(f'{field} projection differs from its source decision')
        if child.get('offer') and child['offer'].get('owner_asin') != child['asin']:
            raise ProductFamilyError('ProductFamily offer is not owned by this child')
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
