from __future__ import annotations

import re
from typing import Any

from core.amazon_image_urls import same_amazon_image_exists
from core.text_evidence import extract_measurements, dimension_axes, measurement_values_match, normalize_text


FieldLabels = dict[str, tuple[str, ...]]
MATERIAL_OWNERS = {'material': 'product', 'leaf_material': 'leaf', 'trunk_material': 'trunk',
                   'pot_material': 'pot', 'frame_material': 'frame', 'top_material': 'top', 'fabric_type': 'fabric'}


def clean_text(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def norm_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def usage_environment(value: str) -> str:
    """Positive use locations, not arbitrary recommended-use/category names."""
    places = set()
    for clause in re.split(r'[,.;\n]|\b(?:but|however)\b', clean_text(value), flags=re.I):
        clause = re.sub(r'\bnot only\b', '', clause, flags=re.I)
        for match in re.finditer(r'\b(indoor|outdoor)s?\b', clause, re.I):
            before, after = clause[:match.start()], clause[match.end():]
            if (re.search(r'\b(?:not|no|never|without|avoid|unsuitable)\s+(?:(?:recommended|intended|suitable|rated|use|for|in|an?)\s+)*(?:(?:indoor|outdoor)s?\s+(?:and|or)\s+)?$', before, re.I)
                    or re.match(r'(?:\s+(?:and|or)\s+(?:indoor|outdoor)s?)?\s+(?:use\s+)?(?:is\s+)?(?:not|prohibited|unsuitable)\b', after, re.I)):
                continue
            places.add(match[1].capitalize())
    return ', '.join(place for place in ('Indoor', 'Outdoor') if place in places)


def detail_rows(raw: dict[str, Any]):
    """Keep every structured observation, including contradictory source groups."""
    for source in ('productDetails', 'product_details', 'attributes', 'manufacturerAttributes', 'productOverview'):
        group = raw.get(source)
        entries = group.items() if isinstance(group, dict) else [
            (item.get('key'), item.get('value')) for item in group if isinstance(item, dict)
        ] if isinstance(group, list) else []
        for label, value in entries:
            if isinstance(value, list):
                value = ', '.join(clean_text(item) for item in value if clean_text(item))
            if label and clean_text(value):
                yield source, str(label), clean_text(value)


def parse_quantity_unit(value: str) -> tuple[str, str] | None:
    rows = extract_measurements(value)
    if len(rows) != 1:
        return None
    row = rows[0]
    unit = {'lb': 'Pounds', 'ft': 'Feet', 'in': 'Inches', 'cm': 'Centimeters',
            'mm': 'Millimeters', 'm': 'Meters', 'kg': 'Kilograms', 'g': 'Grams', 'oz': 'Ounces'}[row['unit']]
    return row['number'], unit


def product_pack_counts(value: str, *, title: str = "", display: bool = False) -> set[int]:
    """Explicit primary-unit claims; display counts are distinct from pack quantities."""
    numbers = {word: str(i) for i, word in enumerate('zero one two three four five six seven eight nine ten'.split())}
    text = re.sub(r'\b(' + '|'.join(numbers) + r')\b', lambda m: numbers[m[0].lower()], str(value or ''), flags=re.I)
    objects = r"trees?|plants?|cabinets?|chairs?|tables?|beds?|frames?|mirrors?"
    if title:
        primary = re.split(r"\b(?:with|includes?|including|for)\b", title, maxsplit=1, flags=re.I)[0]
        nouns = {word.lower().rstrip('s') for word in re.findall(r'\b(?:' + objects + r')\b', primary, re.I)}
        if not nouns:
            return set()
        objects = '|'.join(re.escape(word) + 's?' for word in sorted(nouns))
    modifiers = r"artificial|faux|fake|wooden|wood|metal|wall|mounted|storage|bathroom|medicine|bed|floor|standing|potted|topiary|cedar|olive|ficus|boxwood|indoor|outdoor|tall|white|black|green|purple|natural|\d+(?:\.\d+)?\s*(?:ft|feet|inch|inches|in)"
    if title and (display or re.search(r'\b(?:package|box)\s+(?:includes?|contains?|contents)\s*:', text, re.I)):
        # Use the actual catalog name's modifiers, not an expanding species/color dictionary.
        head=re.search(r'\b(?:'+objects+r')\b',primary,re.I)
        words=re.findall(r'[A-Za-z][A-Za-z-]*',primary[:head.start()] if head else '')[-5:]
        named=[w for w in words if w.casefold() not in {'a','an','the','of','set','pack','package','bundle','with','and','for','in','on',*numbers}]
        if named:modifiers+='|'+'|'.join(re.escape(w) for w in named)
    descriptors=rf'(?:(?:{modifiers})\s+){{0,5}}'
    product = rf"{descriptors}(?:{objects})\b"
    # The count belongs to the product noun, never to a following part noun.
    product += r'(?!\s+(?:doors?|drawers?|shelves|panels?|handles?|legs?|rails?|leaves|branches?|tips?|trunks?|spikes?|parts?|sections?|segments?|stands?|skirts?|covers?|bags?|ornaments?|views?|angles?|photos?|images?)\b)'
    count = r"(-?\d{1,3})"
    patterns = (
        rf"\b(?:set|pack|package|bundle)\s+of\s+{count}\s+{product}",
        rf"\b{count}\s*[- ]?(?:packs?|count|ct|pieces?|pcs)\s+(?:of\s+)?{product}",
        rf"\b{count}\s*x\s+{product}",
        rf"\b{product}\s*[,(-]?\s*(?:set|pack|package|bundle)\s+of\s+{count}\b",
        rf"\b{product}\s*[,(-]?\s*{count}\s*[- ]?(?:packs?|count|ct|pieces?|pcs)\b",
        rf"\b(?:each|every|the)\s+(?:package|pack|set|bundle)\s+(?:includes?|contains?|holds?|has|comes\s+with)\s+{count}\s+{product}",
        rf"\b{count}\s+{product}\s+(?:(?:arrives?|comes?|is\s+included|are\s+included)\s+)?(?:per|in\s+each|in\s+every)\s+(?:package|pack|set|bundle)\b",
    )
    if display:
        # Do not count cabinet doors / tree branches as additional whole units.
        text = re.sub(r'\b(?:(?:a\s+)?pair\s+of|both)\s+(?=' + product + ')', '2 ', text, flags=re.I)
        patterns = (rf'\b{count}\s+{product}',)
    counts = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            before, after = text[:match.start()], text[match.end():]
            clause = re.split(r'[,;:.!?\n]|\b(?:but|however|instead(?!\s+of\b))\b', before, flags=re.I)[-1]
            if (re.search(r"\b(?:not|no|never|without|rather than|instead of)\s+(?:(?:sold|offered|supplied|available|as|a|an|the|include|includes|contain|contains|in)\s+)*$", clause, re.I)
                    or re.match(r"\s+(?:(?:is|are)\s+)?(?:not included|not supplied|sold separately)\b", after, re.I)):
                continue
            if display and (re.search(r'\b(?:not(?!\s+only\b)|no|never|without|avoid(?:ing)?|rather\s+than|instead\s+of)\b', clause, re.I)
                    or re.search(r'\b(?:set|pack|package|bundle)\s+of\s*$', before, re.I)
                    or re.match(r'\s+(?:per|in\s+(?:each|every|the))\s+(?:package|pack|set|bundle)\b', after, re.I)):
                continue
            counts.add(int(match[1]))
    return counts


_TREE_SIZE = r'\d+(?:\.\d+)?\s*[- ]?\s*(?:feet|foot|ft|inches|inch|in|cm|meters?|metres?|m)\b'
_TIP_COUNT = r'\d+(?:,\d{3})*'
_TIP_LABEL = r'\b(?:number of (?:branch )?tips|(?:branch )?tip count)\s*:'


def _size_key(value):
    text = normalize_text(value).strip().casefold()
    measured = extract_measurements(text)
    if len(measured) == 1 and measured[0]['kind'] == 'length_mm':
        m = measured[0]
        return (m['canonical_value'], text.replace(m['raw_text'].casefold(), '', 1).strip())
    return (None, text)


def _size_sections(text):
    parts = re.split(rf'(?<![\w.])({_TREE_SIZE})\s*:', text, flags=re.I)
    return parts[0], list(zip(parts[1::2], parts[2::2]))


def _variant_tip_evidence(raw: dict[str, Any]) -> tuple[list[dict], set[str]]:
    """Bind count(size), size-headed specifications and explicit tree/count pairs to this child."""
    sizes = [a['value'] for a in raw.get('variantAttributes') or []
             if isinstance(a, dict) and norm_key(a.get('key')) == 'size' and a.get('value')]
    own = {_size_key(size) for size in sizes}
    if not own:
        return [], set()
    table = []
    aplus = raw.get('aPlusContent') or {}
    if isinstance(aplus, dict):
        for text in re.findall(_TIP_LABEL + r'([^;\n]+)', str(aplus.get('rawText') or ''), re.I):
            for count, size in re.findall(rf'({_TIP_COUNT})\s*\(([^()]+)\)', text):
                table.append((size, count, 'aPlusContent.rawText'))
    description = clean_text(raw.get('description') or raw.get('productDescription'))
    _, sections = _size_sections(description)
    for size, section in sections:
        for count in re.findall(_TIP_LABEL + rf'\s*({_TIP_COUNT})\b', section, re.I):
            table.append((size, count, 'description'))
    bullets = raw.get('bulletPoints') or raw.get('features') or raw.get('bullet_points') or []
    for text in [bullets] if isinstance(bullets, str) else bullets:
        for size, count in re.findall(rf'\b({_TREE_SIZE})\s+tree\s+(?:with|having|containing|has|contains)\s+({_TIP_COUNT})\s+(?:branch\s+)?tips\b', str(text), re.I):
            table.append((size, count, 'bullets'))
    if not table:
        return [], set()
    title = clean_text(raw.get('title') or raw.get('productTitle'))
    title_size = re.search(rf'(?<![\w.])({_TREE_SIZE})\s+(?=(?:(?:tall|artificial|christmas|xmas|pine|spruce|fir|flocked)\s+){{0,5}}(?:tree|pine|spruce|fir)\b)', title, re.I)
    if title_size and all(key[0] is not None and key[0] != _size_key(title_size[1])[0] for key in own):
        own.add(_size_key(title_size[1]))
    rows, others, matched = [], set(), set()
    for size, count, source in table:
        key, count = _size_key(size), count.replace(',', '')
        if key in own:
            matched.add(key)
            rows.append({'key':'tip_count', 'owner':'product', 'field':'Number of Tips', 'source':source,
                         'variant_size':size, 'value':count})
        else:
            others.add(count)
    if rows or title_size and _size_key(title_size[1]) in {_size_key(size) for size in sizes}:
        for count in re.findall(rf'\b({_TIP_COUNT})\s+(?:PVC\s+)?(?:branch\s+)?tips\b', title, re.I):
            rows.append({'key':'tip_count','owner':'product','field':'Number of Tips','source':'title','value':count.replace(',', '')})
        if len(own) > 1 and (matched != own or len({r['value'] for r in rows}) > 1):
            for row in rows:
                row['scope_conflict'] = 'child size and title disagree'
    if len(own) > 1 and title_size:
        rows.extend({'key':'size', 'owner':'product', 'field':'Size', 'source':source,'value':value}
                    for source,value in [('title',title_size[1]), *(('variantAttributes.Size',s) for s in sizes)])
    return rows, others


def _scope_dimension_evidence(rows: list[dict], raw: dict) -> list[dict]:
    """Split only a tuple whose projection also names an explicitly measured part."""
    if not any(r['key'] == 'dimensions' for r in rows):
        return rows
    owners = r'blade|leaf|needle|branch|slat|rail|leg|door|shelf|drawer|handle|panel|pot|stand|overall|product|item'
    for noun in ('tree', 'cabinet', 'bed frame'):
        if re.search(r'\b' + noun + r'\b', str(raw.get('title') or ''), re.I):
            owners += '|' + noun
    label = re.compile(rf'\b({owners})\s+(width|height|length|depth)\s*:\s*', re.I)
    amounts = {}
    def record(source, text):
        for m in label.finditer(text):
            tail = text[m.end():m.end()+40]
            first = next(iter(extract_measurements(tail)), None)
            if first and first['kind'] == 'length_mm' and tail.startswith(first['raw_text']):
                owner, axis = m[1].lower(), m[2].lower()
                axis = 'item_depth' if axis == 'depth' else axis
                if owner in {'overall', 'product', 'item', 'tree', 'cabinet', 'bed frame'}:
                    owner = 'product'
                key = axis if owner == 'product' else owner + '_' + axis
                amounts[(key,first['text'],source)] = {'key':key,'owner':owner,'source':source,
                                                       'field':m[0].rstrip(': '),'value':first['text']}
    for source, name, value in detail_rows(raw):
        if label.fullmatch(name + ':'):
            record(source, name + ': ' + value)
    sizes = {_size_key(row['value']) for row in raw.get('variantAttributes') or []
             if isinstance(row, dict) and norm_key(row.get('key')) == 'size' and row.get('value')}
    if any(r.get('scope_conflict') for r in rows if r['key'] == 'tip_count'):
        sizes.clear()
    for source in ('description','productDescription','features','bulletPoints','bullet_points'):
        values = raw.get(source) or []
        for value in values if isinstance(values,list) else [values]:
            common, sections = _size_sections(normalize_text(clean_text(value)))
            record(source, common)
            for size, section in sections:
                if _size_key(size) in sizes:
                    record(source, section)
    parts = [r for r in amounts.values() if r['owner'] != 'product']
    if not parts:
        return rows
    result = []
    for row in rows:
        axes = dimension_axes(row['value'], source_field=row['field']) if row['key'] == 'dimensions' else {}
        overlaps = {axis: [p for p in parts if p['key'] == p['owner']+'_'+axis and measurement_values_match(p['value'],value)]
                    for axis,value in axes.items()}
        if not any(overlaps.values()):
            result.append(row)
            continue
        for axis, value in axes.items():
            if overlaps[axis]:
                direct = [r for r in (*rows, *amounts.values()) if r['key'] == axis and r['owner'] == 'product']
                result.extend(overlaps[axis])
                if direct:
                    result.extend(direct)
                    continue
            projection = {**row,'key':axis,'value':value}
            if overlaps[axis]:
                projection['scope_conflict'] = 'tuple axis also labels a measured part'
            result.append(projection)
    return result


def extract_specs_by_fields(raw: dict[str, Any], field_labels: FieldLabels) -> dict[str, Any]:
    specs: dict[str, Any] = {}
    observations = []
    for source, label, value in detail_rows(raw):
        for key, labels in field_labels.items():
            if norm_key(label) in {norm_key(name) for name in labels}:
                observed_value = usage_environment(value) if key == 'indoor_outdoor' else value
                if not observed_value:
                    continue
                observations.append({'key': key, 'owner': MATERIAL_OWNERS.get(key, 'product'),
                                     'field': label, 'source': source, 'value': observed_value})
    if 'indoor_outdoor' in field_labels and not any(r['key'] == 'indoor_outdoor' for r in observations):
        bullets = raw.get('bulletPoints') or raw.get('features') or raw.get('bullet_points') or []
        for value in [bullets] if isinstance(bullets, str) else bullets:
            environment = usage_environment(value)
            if environment:
                observations.append({'key':'indoor_outdoor','owner':'product','field':'Use environment',
                                     'source':'bullets','value':environment})
    title = clean_text(raw.get('title') or raw.get('productTitle') or '')
    if 'tree_type' in field_labels:
        sizes = list(re.finditer(r'\b\d+(?:\.\d+)?\s*(?:ft|feet|foot)\b', title, re.I))
        if len(sizes) == 1 and re.search(r'\btree\b', title, re.I) and not re.search(r'\d\s*[-/–]\s*$', title[:sizes[0].start()]):
            observations.append({'key':'size','owner':'product','field':'Nominal sales size',
                                 'source':'title_nominal_size','value':sizes[0][0]})
    if 'light_count' in field_labels:
        for match in re.finditer(r'\b(?:with|includes?)\s+(\d+(?:,\d{3})*)\s+(?:(?:LED|warm|white|colored|yellow)\s+)*lights\b', title, re.I):
            observations.append({'key':'light_count','owner':'product','field':'Included lights',
                                 'source':'title','value':match[1].replace(',', '')})
        for pattern, value in ((r'\bpre[- ]?lit\b|\bwith (?:\d+ )?(?:LED )?lights\b', 'true'),
                               (r'\bunlit\b|\bwithout (?:LED )?lights\b|\bno lights\b', 'false')):
            if re.search(pattern, title, re.I):
                observations.append({'key':'light_included','owner':'product','field':'Lighting inclusion','source':'title','value':value})
    if 'tip_count' in field_labels:
        bound, other_sizes = _variant_tip_evidence(raw)
        if any(r['key'] == 'tip_count' for r in bound):
            observations = [row for row in observations if row['key'] != 'tip_count'
                            or row['value'].replace(',', '') not in other_sizes]
        elif other_sizes:
            for row in observations:
                if row['key'] == 'tip_count' and row['value'].replace(',', '') in other_sizes:
                    row['scope_conflict'] = 'count is attributed to a different variant in the size table'
        observations.extend(bound)
    observations = _scope_dimension_evidence(observations, raw)
    if observations:
        specs['source_fact_evidence'] = observations
        for key in dict.fromkeys(r['key'] for r in observations):
            values = {row['value'].casefold(): row['value'] for row in observations if row['key'] == key}
            if len(values) == 1 and not any(r.get('scope_conflict') for r in observations if r['key'] == key):
                specs[key] = next(iter(values.values()))
    title = raw.get("title") or raw.get("productTitle") or ""
    if title:
        specs["source_title"] = clean_text(title)
    bullets = raw.get("bulletPoints") or raw.get("features") or raw.get("bullet_points") or []
    if isinstance(bullets, str):
        bullets = [bullets]
    if isinstance(bullets, list):
        specs["source_bullets"] = [clean_text(item) for item in bullets if clean_text(item)][:5]
    dimensions = specs.get('dimensions','')
    projections=[dimension_axes(dimensions,source_field=row['field']) for row in observations
                 if row['key']=='dimensions' and row['value']==dimensions]
    projected={}
    for axes in projections:
        for key,value in axes.items():
            if key in projected and projected[key]!=value:raise ValueError('Conflicting source dimension axes')
            projected[key]=value
    for key,value in projected.items():
        if key in specs and specs[key]!=value:
            from core.text_evidence import measurement_values_match
            if not measurement_values_match(str(specs[key]),value):raise ValueError('Conflicting explicit dimension: '+key)
        specs.setdefault(key,value)
    for key, unit_key in (
        ("height", "height_unit"),
        ("item_weight", "item_weight_unit"),
        ("weight_capacity", "weight_capacity_unit"),
        ("load_capacity", "load_capacity_unit"),
    ):
        parsed_unit = parse_quantity_unit(specs.get(key, ""))
        if parsed_unit:
            specs[key], specs[unit_key] = parsed_unit
    return {key: value for key, value in specs.items() if value not in (None, "", [])}


def searchable_text(raw: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "productTitle", "description", "productDescription"):
        value = raw.get(key)
        if value not in (None, ""):
            parts.append(clean_text(value))
    bullets = raw.get("bulletPoints") or raw.get("features") or raw.get("bullet_points") or []
    if isinstance(bullets, str):
        parts.append(clean_text(bullets))
    elif isinstance(bullets, list):
        parts.extend(clean_text(item) for item in bullets if clean_text(item))
    return " ".join(parts)


def explicit_item_counts(raw: dict[str, Any]) -> set[int]:
    counts = set()
    unit_counts = set()
    component_counts = set()
    for _, label, value in detail_rows(raw):
        field = norm_key(label)
        if field in {'tipcount', 'numberoftips', 'branchtipcount', 'numberofbranchtips', 'lightcount', 'numberoflights'}:
            count = _explicit_count_value(value, label=label, strict=False)
            if count is not None: component_counts.add(count)
        if field not in {'numberofitems', 'unitcount'}:
            continue
        count = _explicit_count_value(value, label=label, strict=field == 'numberofitems')
        if count is not None:
            (counts if field == 'numberofitems' else unit_counts).add(count)
    bullets = raw.get('bulletPoints') or raw.get('features') or raw.get('bullet_points') or []
    if isinstance(bullets, str):
        bullets = [bullets]
    for text in [raw.get('title') or raw.get('productTitle') or '',
                 raw.get('description') or raw.get('productDescription') or '', *bullets]:
        counts.update(product_pack_counts(str(text), title=str(raw.get('title') or raw.get('productTitle') or '')))
    # Exclude only Unit Count values evidenced as component counts. All other
    # contradictory sale counts remain visible to the existing fact resolver.
    if unit_counts - component_counts:
        bound, _ = _variant_tip_evidence(raw)
        component_counts.update(int(r['value']) for r in bound if r['key'] == 'tip_count')
    counts.update(unit_counts - component_counts)
    if any(count <= 0 for count in counts):
        raise ValueError('Invalid explicit product bundle count')
    return counts


def _explicit_count_value(value: str, *, label: str, strict: bool) -> int | None:
    if not value:
        return None
    match = re.fullmatch(r"([1-9]\d*)(?:\.0+)?(?:\s*(?:count|items?|pieces?))?", value, flags=re.I)
    if not match:
        if strict:
            raise ValueError(f"invalid explicit {label}: {value!r}")
        return None
    return int(match.group(1))


def explicit_package_quantity(raw: dict[str, Any]) -> int | None:
    values = {value for _, label, value in detail_rows(raw)
              if norm_key(label) in {'packagequantity', 'itempackagequantity'}}
    if not values:
        return None
    counts = set()
    for value in values:
        match = re.fullmatch(r"([1-9]\d*)(?:\.0+)?(?:\s*(?:count|packages?))?", value, flags=re.I)
        if not match:
            raise ValueError(f"invalid explicit Package Quantity: {value!r}")
        counts.add(int(match.group(1)))
    if len(counts) != 1:
        raise ValueError('Conflicting explicit Package Quantity observations')
    return next(iter(counts))


def image_urls(raw: dict[str, Any]) -> list[str]:
    images = raw.get("highResolutionImages") or raw.get("images") or raw.get("imageUrls") or []
    out: list[str] = []
    if isinstance(images, list):
        for item in images:
            url = item.get("url") if isinstance(item, dict) else item
            if isinstance(url, str) and url.startswith("http") and url not in out:
                out.append(url)
    main = raw.get("mainImage") or raw.get("main_image") or raw.get("thumbnailImage")
    if isinstance(main, str) and main.startswith("http") and main not in out and not same_amazon_image_exists(out, main):
        out.insert(0, main)
    return out


def variant_value(item: dict[str, Any], *keys: str) -> str:
    candidates = dict(item)
    dims = item.get("dimensions")
    if isinstance(dims, dict):
        candidates.update(dims)
    attrs = item.get("attributes")
    if isinstance(attrs, list):
        for attr in attrs:
            if isinstance(attr, dict) and attr.get("key"):
                candidates[str(attr["key"])] = attr.get("value")
    index = {norm_key(key): value for key, value in candidates.items()}
    for key in keys:
        value = index.get(norm_key(key))
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value if item not in (None, ""))
        if value not in (None, ""):
            return clean_text(value)
    return ""


def extract_variations(raw: dict[str, Any], seed_asin: str, dimensions_default: list[str]) -> dict[str, Any]:
    parent_asin = str(raw.get("parentAsin") or raw.get("parent_asin") or raw.get("parentASIN") or "").strip().upper()
    from core.product_family import fact_key, identity_values_equal
    dimensions = [fact_key(v) for v in raw['dimensions'] if isinstance(v,str) and fact_key(v)] if isinstance(raw.get('dimensions'),list) else []
    own = {fact_key(item['key']): clean_text(item['value']) for item in (raw.get('variantAttributes') or [])
           if isinstance(item,dict) and item.get('key') and item.get('value') not in (None,'')}
    if not dimensions and own:
        dimensions = list(own)
    keys=list(dict.fromkeys([*dimensions,*dimensions_default]))
    display_rows, detail_members, listed = {}, {}, {}
    display = raw.get("dimensionValuesDisplayData")
    if isinstance(display, dict):
        for asin, values in display.items():
            row = {"asin": str(asin).strip().upper()}
            if isinstance(values, list):
                for dim, value in zip(dimensions, values):
                    if clean_text(value):
                        row[str(dim)] = clean_text(value)
            display_rows[row['asin']] = row
    variants = raw.get("variantDetails") or raw.get("variants") or []
    if isinstance(variants, list):
        for item in variants:
            if not isinstance(item, dict):
                continue
            asin = variant_value(item, "asin", "ASIN", "variantAsin", "variant_asin")
            if not asin:
                continue
            row = {"asin": asin.strip().upper()}
            for key in keys:
                value = variant_value(item, key, f"{key}_name", f"{key}Name", key.title())
                if value:
                    row[key] = value
            if not any(key in row for key in keys) and item.get("name") and len(dimensions) == 1:
                row[dimensions[0]] = clean_text(item["name"])
            detail_members[row['asin']] = row
    variant_asins = raw.get("variantAsins") or raw.get("variant_asins") or raw.get("variationAsins") or []
    if isinstance(variant_asins, list):
        for item in variant_asins:
            asin = item.get("asin") if isinstance(item, dict) else item
            if asin:
                listed[str(asin).strip().upper()] = True
    sources = [group for group in (display_rows, detail_members, listed) if group]
    members = set().union(*sources)
    confirmed = {a for a in members if sum(a in group for group in sources) >= min(2, len(sources))}
    unconfirmed = members - confirmed - {seed_asin, parent_asin}
    if display_rows and display_rows.keys() == detail_members.keys():
        unconfirmed.difference_update(listed)  # Two attributed rosters agree; an isolated ID has no membership evidence.
    if seed_asin != parent_asin:
        confirmed.add(seed_asin)
    rows = []
    for asin in sorted(confirmed - {parent_asin, ''}):
        detail, displayed = detail_members.get(asin, {}), display_rows.get(asin, {})
        row = {**detail, **displayed, 'asin':asin}
        for key in (detail.keys() & displayed.keys()) - {'asin'}:
            if not identity_values_equal(detail[key], displayed[key]):
                row.pop(key)
        if asin == seed_asin:
            row.update(own)
        rows.append(row)
    observed = set().union(*(set(row) for row in rows)) if rows else set()
    if not dimensions:
        dimensions = [key for key in keys if key in observed]
    rows = sorted(rows, key=lambda row: tuple(row.get(key, "") for key in dimensions_default) + (row["asin"],))
    return {
        "parent_asin": str(parent_asin),
        "dimensions": dimensions,
        "variation_theme": theme_from_dimensions(dimensions),
        "variants": rows,
        "unconfirmed_variant_asins": sorted(unconfirmed),
    }


def theme_from_dimensions(dimensions: list[str], allowed: list[str] | None = None) -> str:
    from core.product_family import fact_key
    parts = [fact_key(dim).upper() for dim in dimensions]
    theme = '/'.join(dict.fromkeys('STYLE_NAME' if key == 'STYLE' else key for key in parts))
    if allowed is None or theme in allowed:
        return theme
    # Some masters prescribe a different order or the explicit alias SIZE_NAME.
    def axes(value):
        return sorted(fact_key(axis) for axis in value.split('/'))
    return next((value for value in allowed if axes(value) == axes(theme)), '')


def contains(raw: dict[str, Any], needle: str) -> bool:
    text = " ".join(
        str(part)
        for part in [
            raw.get("title"),
            raw.get("productTitle"),
            raw.get("bulletPoints"),
            raw.get("features"),
            raw.get("productDetails"),
        ]
        if part not in (None, "")
    ).lower()
    return needle.lower() in text
