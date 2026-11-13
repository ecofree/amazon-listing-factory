from __future__ import annotations

import re
from typing import Any

from .text_evidence import normalize_text, extract_measurements, us_measurement_text, dimension_axes


def sourced_template_attributes(job, family, child):
    """Read listing-only fields from the child's original, hash-bound product specifications."""
    from .io import file_sha256, read_json
    from .source_fetch.apify import raw_source_directory
    from .source_fetch.apify_client import returned_asin
    from products.generic_extractors import detail_rows, norm_key
    from .template_field_plan import _known_enum_value

    asin = child['asin']
    expected = family.get('source', {}).get('raw_sha256', {}).get(asin)
    if not expected:
        return {}
    path = raw_source_directory(job, family['family']['marketplace']) / (asin + '.json')
    if not path.is_file() or file_sha256(path) != expected:
        return {}
    raw = read_json(path)
    if returned_asin(raw) != asin:
        return {}
    fields = {
        'model_name': ['Model Name'], 'model_number': ['Model Number', 'Item Model Number'],
        'occasion_type': ['Occasion', 'Occasion Type'], 'recommended_uses': ['Recommended Uses For Product'],
        'included_components': ['Included Components', 'Included Accessories'],
        'batteries_required': ['Batteries Required', 'Batteries Required?'],
        'required_product_compliance_certificate': ['Product Compliance Certificate'],
    }
    labels = {norm_key(label): key for key, names in fields.items() for label in names}
    found = {}
    for _, label, value in detail_rows(raw):
        key = labels.get(norm_key(label))
        if key and value:
            if key == 'batteries_required':
                value = _known_enum_value(key, value, ['Yes','No']) or value
            found.setdefault(key, {})[value.casefold()] = value
    result = {key: next(iter(values.values())) for key, values in found.items() if len(values) == 1}
    if family.get('category_id') == 'artificial_tree':
        from .product_family import effective_product_facts
        from products.generic_extractors import usage_environment
        facts = effective_product_facts(child)
        result.pop('recommended_uses', None)
        environment = usage_environment(facts.get('indoor_outdoor', ''))
        if environment:
            result['recommended_uses'] = environment
        # This template column asks about CARB, not general electrical certification.
        materials = [part.strip() for part in re.split(r'[,;/&]|\band\b', str(facts.get('material', '')).casefold()) if part.strip()]
        if (materials and set(materials) <= {'pvc','polyvinyl chloride','pe','polyethylene','metal','iron','steel','plastic'}
                and not result.get('required_product_compliance_certificate')):
            result['required_product_compliance_certificate'] = 'Not Applicable'
    conflicts = {key:list(values.values()) for key,values in found.items() if len(values) > 1}
    if conflicts:
        result['_source_field_conflicts'] = conflicts
    return result


def template_dimensions_from_facts(facts: dict[str, Any], *, category_id: str = "") -> dict[str, str]:
    dimensions: dict[str, str] = {}
    keys_by_alias = {
        "length": ("length", "item_length"),
        "width": ("width", "item_width"),
        "height": ("height", "item_height"),
        "item_depth": ("item_depth", "depth"),
        "item_weight": ("item_weight", "weight"),
    }
    # Length is never silently renamed depth because the product is a cabinet.
    axes=dimension_axes(_first(facts,'dimensions','product_dimensions','item_dimensions','overall_dimensions'))
    for alias, keys in keys_by_alias.items():
        value = _first(facts, *keys) or axes.get(alias,'')
        if value:
            unit = _first(facts, *(f"{key}_unit" for key in keys))
            parsed = extract_measurements(value)
            if not parsed and not unit and alias in axes:
                measured=extract_measurements(axes[alias])
                if len(measured)==1 and _clean_dimension_number(value)==_clean_dimension_number(measured[0]['number']):
                    value=axes[alias];parsed=measured
            separate = extract_measurements('1 ' + unit) if unit else []
            if parsed and separate and parsed[0]['unit'] != separate[0]['unit']:
                raise ValueError(f'Conflicting explicit units for {alias}: {parsed[0]["unit"]} and {separate[0]["unit"]}')
            display = us_measurement_text(value if parsed else f"{value} {unit}")
            parsed = extract_measurements(display)
            if len(parsed) == 1:
                row = parsed[0]
                number, label = row['number'], row['unit']
                if label == 'ft':
                    number, label = str(float(row['canonical_value']) / 25.4), 'in'
                elif label == 'in' and '/' in number:
                    number = str(float(row['canonical_value']) / 25.4)
                dimensions[alias] = _clean_dimension_number(number)
                dimensions[f"{alias}_unit"] = {'in': 'Inches', 'lb': 'Pounds', 'oz': 'Ounces'}.get(label, label)
            else:
                dimensions[alias] = str(value)
    return dimensions


def color_map_value(color: Any, *, category_id: str = "", allowed=()) -> str:
    text = normalize_text(color).casefold()
    if not text:
        return ""
    for value in allowed:
        if value.casefold() == text or text == 'gray' and value.casefold() == 'grey':
            return value
    colors=[]
    for token, value in (
        ("black", "Black"),
        ("white", "White"),
        ("gray", "Gray"),
        ("grey", "Gray"),
        ("brown", "Brown"),
        ("caramel", "Brown"),
        ("green", "Green"),
        ("blue", "Blue"),
        ("red", "Red"),
        ("pink", "Pink"),
        ("beige", "Beige"),
        ("natural", "Natural"),
        ("gold", "Gold"),
        ("silver", "Silver"),
        ("clear", "Clear"),
    ):
        if re.search(r'\b'+re.escape(token)+r'\b',text) and value not in colors:
            colors.append(value)
    return 'Multicolor' if len(colors)>1 else colors[0] if colors else ''


def repeated_attribute_values(value, allowed, alias):
    """Tile each complete positive phrase with the current column's vocabulary."""
    if not value or not allowed:
        return [value] if value else []
    text = ', '.join(map(str, value)) if isinstance(value, (list,tuple)) else str(value)
    if re.search(r"\b(?:no|not|without|excluding|except|pending|free|or)\b", text, re.I):
        return [text]
    names = {s.casefold():s for s in allowed}
    equivalents = {
        'included_component': {'gloves':'Protective Glove','protective gloves':'Protective Glove',
                               'user guide':'Instruction Manual','user manual':'Instruction Manual'},
        'material': {'pvc':'Polyvinyl Chloride','pe':'Polyethylene'},
        'recommended_uses': {'indoor use':'Indoor','outdoor use':'Outdoor'},
    }
    names.update({key:val for key,val in equivalents.get(alias,{}).items() if val in allowed})
    pattern = re.compile('(?:'+'|'.join(re.escape(key) for key in sorted(names,key=len,reverse=True))+r')(?=\s|$)')
    accepted, unmatched = [], []
    for chunk in re.split(r'\s*(?:[,;/&]|\band\b)\s*', text, flags=re.I):
        part = chunk.strip().casefold()
        if alias == 'included_component':
            part = re.sub(r'^\d+\s*(?:x\s+|pairs? of\s+)?', '', part)
        matches = []
        while part:
            match = pattern.match(part)
            if not match:
                break
            matches.append(names[match.group()])
            part = part[match.end():].strip()
        if part:
            unmatched.append(chunk)
        else:
            accepted.extend(matches)
    return list(dict.fromkeys([*accepted,*unmatched]))


def light_color_value(category_id: str, attributes: dict[str, Any]) -> str:
    for key in ("light_color", "lighting_color", "light_colour"):
        value = attributes.get(key)
        if value:
            return str(value)
    return ""  # Missing lighting evidence is not proof of non-applicability.


def _first(values: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = values.get(key)
        if value not in (None, "", [], {}):
            return str(value)
    return ""


def _clean_dimension_number(value: Any) -> str:
    text = str(value or "").strip()
    return text[:-2] if text.endswith(".0") else text
