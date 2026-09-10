from __future__ import annotations

import re
import unicodedata
from collections import Counter
from fractions import Fraction
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR
from typing import Any

_QUOTE_MAP = str.maketrans({
    "\u201c": '"',
    "\u201d": '"',
    "\u2033": '"',
    "\uff02": '"',
    "\u2018": "'",
    "\u2019": "'",
    "\u2032": "'",
    "\u00d7": "x",
    "\u2715": "x",
    "\u2716": "x",
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
})
_NUMBER_RE = r"[+-]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
_UNIT_RE = (
    r"feet|foot|ft|inches|inch|in|centimeters|centimeter|cm|millimeters|millimeter|mm|"
    r"meters|meter|m|lbs|lb|pounds|pound|kilograms|kilogram|kg|grams|gram|g|ounces|ounce|oz|[\"']"
)
_MEASURE_RE = re.compile(rf"(?<![\w./])({_NUMBER_RE})\s*-?\s*({_UNIT_RE})(?![A-Za-z])", re.I)
_QUOTE_MEASURE_RE = re.compile(rf"\b({_NUMBER_RE})\s*([\"'])(?!\s*[,:\]\}}\n\r])", re.I)
_DIMENSION_CHAIN_RE = re.compile(
    rf"\b({_NUMBER_RE}(?:\s*(?:x|\*)\s*{_NUMBER_RE}){{1,5}})\s*-?\s*({_UNIT_RE})\b",
    re.I,
)
_LABELLED_DIMENSION_CHAIN_RE = re.compile(
    rf"\b((?:{_NUMBER_RE}\s*(?:L|W|H|D|length|width|height|depth)\s*(?:x|\*)\s*)+"
    rf"{_NUMBER_RE}\s*(?:L|W|H|D|length|width|height|depth))\s*-?\s*({_UNIT_RE})\b",
    re.I,
)
_LABELLED_DIMENSION_ITEM_RE = re.compile(
    rf"({_NUMBER_RE})\s*(L|W|H|D|length|width|height|depth)\b", re.I,
)
_UNIT_ALIASES = {
    "feet": ("length_mm", 304.8, "ft"),
    "foot": ("length_mm", 304.8, "ft"),
    "ft": ("length_mm", 304.8, "ft"),
    "'": ("length_mm", 304.8, "ft"),
    "inches": ("length_mm", 25.4, "in"),
    "inch": ("length_mm", 25.4, "in"),
    "in": ("length_mm", 25.4, "in"),
    '"': ("length_mm", 25.4, "in"),
    "centimeters": ("length_mm", 10.0, "cm"),
    "centimeter": ("length_mm", 10.0, "cm"),
    "cm": ("length_mm", 10.0, "cm"),
    "millimeters": ("length_mm", 1.0, "mm"),
    "millimeter": ("length_mm", 1.0, "mm"),
    "mm": ("length_mm", 1.0, "mm"),
    "meters": ("length_mm", 1000.0, "m"),
    "meter": ("length_mm", 1000.0, "m"),
    "m": ("length_mm", 1000.0, "m"),
    "pounds": ("weight_g", 453.59237, "lb"),
    "pound": ("weight_g", 453.59237, "lb"),
    "lbs": ("weight_g", 453.59237, "lb"),
    "lb": ("weight_g", 453.59237, "lb"),
    "kilograms": ("weight_g", 1000.0, "kg"),
    "kilogram": ("weight_g", 1000.0, "kg"),
    "kg": ("weight_g", 1000.0, "kg"),
    "grams": ("weight_g", 1.0, "g"),
    "gram": ("weight_g", 1.0, "g"),
    "g": ("weight_g", 1.0, "g"),
    "ounces": ("weight_g", 28.349523125, "oz"),
    "ounce": ("weight_g", 28.349523125, "oz"),
    "oz": ("weight_g", 28.349523125, "oz"),
}
_MOJIBAKE_MARKERS = (
    "\ufffd",
    "\u00c3",
    "\u00c2",
    "\ufffd",
    "\u951f",
    "\u951b",
    "\u9225",
    "\u95bf",
    "\u95c1",
    "\u95b3",
    "\u6d94",
)


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).translate(_QUOTE_MAP)
    text = re.sub(r"(?<=\d)\s*\u00a1[\u00e5\u00b1]", '"', text)
    text = re.sub(r"(?<=\d)\s*'{2,}", '"', text)
    text = re.sub(r"(?<=\d)\s+([\"'])", r"\1", text)
    text = re.sub(r"(?<=\d)\s+[Ii]bs\b", " lbs", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def has_bad_encoding(value: Any) -> bool:
    text = normalize_text(value)
    if not text:
        return False
    return any(marker in text for marker in _MOJIBAKE_MARKERS)


def clean_evidence_text(value: Any) -> str:
    text = normalize_text(value)
    for marker in _MOJIBAKE_MARKERS:
        text = text.replace(marker, " ")
    return re.sub(r"\s+", " ", text).strip(" ,;:-")


_LABEL_STOP_WORDS = {
    "a", "an", "the", "for", "with", "and", "or", "to", "of", "on",
    "is", "are", "be", "can", "your", "our",
}
_BARE_UNIT_WORDS = {
    "in", "inch", "inches", "ft", "feet", "foot", "cm", "mm", "meter",
    "meters", "m", "lb", "lbs", "pound", "pounds", "kg", "kilogram",
    "kilograms",
}


def renderable_label_text(value: Any, *, max_words: int = 5) -> str:
    """Return concise text safe to render in generated infographics.

    OCR/VLM/source snippets are evidence, not final label copy. This function
    is the cleanup gate before evidence can be considered by a render-text
    contract. It never authorizes text on its own.
    """
    text = clean_evidence_text(value)
    if not text or has_bad_encoding(text):
        return ""
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    text = re.sub(r"\bdurablethickened\b", "durable thickened", text, flags=re.I)
    text = re.sub(r"\bcan\s+be\s+removed\s+for\b", "removable", text, flags=re.I)
    text = re.sub(r"\bbuilt\s*[- ]\s*in\b", "built-in", text, flags=re.I)
    text = re.sub(r"\bfull\s*[- ]\s*length\b", "full-length", text, flags=re.I)
    text = re.sub(r"\banti\s*[- ]\s*tipping\b", "anti-tipping", text, flags=re.I)
    text = re.sub(r"\bunder\s*[- ]\s*bed\b", "under-bed", text, flags=re.I)
    text = re.sub(r"\b(\d+(?:\.\d+)?)\s*(?:inches|inch)\b", r"\1 in", text, flags=re.I)
    text = re.sub(r"\b(\d+(?:\.\d+)?)\s*(?:pounds|pound|lbs)\b", r"\1 lb", text, flags=re.I)
    text = re.split(r"[;|]|(?<!\d)\.(?!\d)", text, maxsplit=1)[0]
    tokens = re.findall(r"\d+(?:\.\d+)?|[A-Za-z]+(?:-[A-Za-z]+)?", text)
    if not tokens:
        return ""
    # ``in`` is both an imperial unit and a normal English preposition.  It is
    # a unit only when it follows a number; otherwise it is harmless grammar
    # and must not invalidate a buyer-facing phrase such as "Ready in Style".
    if tokens[0].casefold() in _BARE_UNIT_WORDS and tokens[0].casefold() != "in":
        return ""
    kept: list[str] = []
    for token in tokens:
        lower = token.casefold()
        if lower == "in" and not (kept and re.fullmatch(_NUMBER_RE, kept[-1])):
            continue
        if lower in _BARE_UNIT_WORDS and not (kept and re.fullmatch(_NUMBER_RE, kept[-1])):
            return ""
        if lower in _LABEL_STOP_WORDS:
            continue
        kept.append(token)
    if not kept:
        return ""
    if len([token for token in kept if not re.fullmatch(_NUMBER_RE, token)]) == 0:
        return ""
    return " ".join(_format_label_token(token) for token in kept[:max_words]).strip()


def _format_label_token(token: str) -> str:
    lower = token.casefold()
    compounds = {
        "built-in": "Built-In",
        "anti-tipping": "Anti-Tipping",
        "full-length": "Full-Length",
        "under-bed": "Under-Bed",
    }
    if lower in compounds:
        return compounds[lower]
    if re.fullmatch(_NUMBER_RE, token):
        return token
    if lower in {"in", "ft", "cm", "mm", "lb", "kg", "oz"}:
        return lower
    if token.isupper() and len(token) <= 4:
        return token
    if "-" in token:
        return "-".join(_format_label_token(part) for part in token.split("-") if part)
    return token[:1].upper() + token[1:].lower()


def qa_text_key(value: str) -> str:
    return re.sub(r"[\W_]+", " ", normalize_text(value).casefold(), flags=re.UNICODE).strip()


def number_tokens(value: str) -> set[str]:
    return {_clean_number(match) for match in re.findall(_NUMBER_RE, normalize_text(value))}


def numeric_signature(value: str) -> tuple[float, ...]:
    return tuple(_number_value(m[0]) for m in re.finditer(rf"(?<![A-Za-z0-9]){_NUMBER_RE}", normalize_text(value)))


def extract_measurements(value: Any) -> list[dict[str, Any]]:
    text = normalize_text(value)
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    occupied: list[range] = []
    for match in re.finditer(rf"(?<![\w./])({_NUMBER_RE})\s*(?:to|-)\s*({_NUMBER_RE})\s*({_UNIT_RE})(?![A-Za-z])", text, re.I):
        for number in (match[1], match[2]):
            _append_measurement(results, seen, number, _UNIT_ALIASES[match[3].casefold()], match[0], allow_duplicate=True)
        occupied.append(range(match.start(), match.end()))
    for match in re.finditer(rf"\b({_NUMBER_RE})\s*(?:ft|feet|foot|')\s*({_NUMBER_RE})\s*(?:inches|inch|in|\")", text, re.I):
        inches = _number_value(match[1]) * 12 + _number_value(match[2])
        _append_measurement(results, seen, str(inches), _UNIT_ALIASES['in'], match[0], allow_duplicate=True)
        occupied.append(range(match.start(), match.end()))
    for match in _LABELLED_DIMENSION_CHAIN_RE.finditer(text):
        unit = _unit(match.group(2))
        if unit is None:
            continue
        occupied.append(range(match.start(), match.end()))
        for number, axis in _LABELLED_DIMENSION_ITEM_RE.findall(match.group(1)):
            _append_measurement(
                results, seen, number, unit, match.group(0),
                allow_duplicate=True, axis_hint=axis.casefold(),
            )
    for match in _DIMENSION_CHAIN_RE.finditer(text):
        if any(match.start() in span and match.end() - 1 in span for span in occupied):
            continue
        unit = _unit(match.group(2))
        if unit is None:
            continue
        occupied.append(range(match.start(), match.end()))
        for number in re.findall(_NUMBER_RE, match.group(1)):
            _append_measurement(results, seen, number, unit, match.group(0), allow_duplicate=True)
    for match in _MEASURE_RE.finditer(text):
        if any(match.start() in span and match.end() - 1 in span for span in occupied):
            continue
        unit = _unit(match.group(2))
        if unit is not None:
            _append_measurement(results, seen, match.group(1), unit, match.group(0), allow_duplicate=True)
            occupied.append(range(match.start(), match.end()))
    for match in _QUOTE_MEASURE_RE.finditer(text):
        if any(match.start() in span and match.end() - 1 in span for span in occupied):
            continue
        unit = _quote_unit(match.group(1), match.group(2))
        if unit is not None:
            _append_measurement(results, seen, match.group(1), unit, match.group(0))
    return results


def us_measurement_text(value: Any, *, upper_bound: bool = False, length_unit: str = '') -> str:
    """Convert explicit metric quantities only; preserve source wording and axes."""
    text = normalize_text(value)
    metric = r"centimeters?|cm|millimeters?|mm|meters?|m|kilograms?|kg|grams?|g"
    if length_unit == 'in':
        metric += r"|feet|foot|ft"
    axis = r"(?:\s*(?:L|W|H|D|length|width|height|depth)\b)?"
    pattern = re.compile(rf"(?<![\w./])({_NUMBER_RE}{axis}(?:\s*(?:[x*]|to|-)\s*{_NUMBER_RE}{axis})*)\s*({metric})(?![A-Za-z])", re.I)
    bound = upper_bound or bool(re.search(r"\b(capacity|supports up to|holds up to|maximum load)\b", text, re.I))

    def convert(match: re.Match[str]) -> str:
        kind, factor, _ = _UNIT_ALIASES[match[2].casefold()]
        target, divisor = ('in', Decimal('25.4')) if kind == 'length_mm' else ('lb', Decimal('453.59237'))
        mode = ROUND_FLOOR if bound and kind == 'weight_g' else ROUND_HALF_UP
        def number(m: re.Match[str]) -> str:
            n = Decimal(str(_number_value(m[0]))) * Decimal(str(factor)) / divisor
            places = Decimal('0.01')
            while n and abs(n) < places:
                places /= 10
            return format(n.quantize(places, rounding=mode), 'f').rstrip('0').rstrip('.') if places < 1 else str(n)
        return re.sub(rf"(?<![\d/]){_NUMBER_RE}", number, match[1]) + ' ' + target

    return pattern.sub(convert, text)


def measurement_values_match(source: str, candidate: str) -> bool:
    """Allow exact physical equivalence or the single approved US display value."""
    original, actual = extract_measurements(source), extract_measurements(candidate)
    approved = extract_measurements(us_measurement_text(source))
    if not original or len(original) != len(actual) or len(approved) != len(actual):
        return False
    return all(a['canonical_pair'] in {s['canonical_pair'], d['canonical_pair']}
               for s, d, a in zip(original, approved, actual))


def has_measurement_text(value: Any) -> bool:
    return bool(extract_measurements(value))


def measurement_tokens(value: str) -> set[tuple[str, str]]:
    tokens: set[tuple[str, str]] = set()
    for item in extract_measurements(value):
        tokens.add((str(item["canonical_pair"]), str(item["number"])))
    return tokens


def clean_measurement_text(value: str) -> str:
    rows: list[str] = []
    for item in extract_measurements(value):
        text = str(item["text"])
        if text not in rows:
            rows.append(text)
    return "; ".join(rows)


def measurement_pairs(value: str) -> list[str]:
    pairs: list[str] = []
    for item in extract_measurements(value):
        pair = f"{item['number']}:{item['unit']}"
        if pair not in pairs:
            pairs.append(pair)
    return pairs


def measurement_counts(lines: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for line in lines:
        counts.update(measurement_pairs(line))
    return counts


def complete_ocr_phrases(source: dict[str, Any], phrases: list[str]) -> list[str]:
    lines = _ocr_phrase_lines(source)
    completed: list[str] = []
    for phrase in phrases:
        wanted = set(qa_text_key(phrase).split())
        best = str(phrase).strip()
        for line in lines:
            line_key = qa_text_key(line)
            if wanted and wanted.issubset(set(line_key.split())) and len(line) <= 80 and len(line_key) > len(qa_text_key(best)):
                best = line
        if best and best not in completed:
            completed.append(best)
    return completed


def _append_measurement(
    results: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    raw_number: str,
    unit_info: tuple[str, float, str],
    raw_text: str,
    *, allow_duplicate: bool = False, axis_hint: str = "",
) -> None:
    kind, multiplier, display_unit = unit_info
    number = _clean_number(raw_number)
    numeric = _number_value(raw_number)
    canonical_value = format(Decimal(str(numeric)) * Decimal(str(multiplier)), 'f')
    if '.' in canonical_value:
        canonical_value = canonical_value.rstrip('0').rstrip('.')
    key = (kind, canonical_value, number)
    if not allow_duplicate and key in seen:
        return
    seen.add(key)
    row = {
        "raw_text": normalize_text(raw_text),
        "text": f"{number} {display_unit}",
        "number": number,
        "unit": display_unit,
        "kind": kind,
        "canonical_value": canonical_value,
        "canonical_pair": f"{kind}:{canonical_value}",
        "confidence": "confirmed",
    }
    if axis_hint:
        row["axis_hint"] = axis_hint
    results.append(row)


def _unit(value: str) -> tuple[str, float, str] | None:
    return _UNIT_ALIASES.get(normalize_text(value).casefold())


def _quote_unit(number: str, quote: str) -> tuple[str, float, str] | None:
    return _unit(normalize_text(quote))


def _clean_number(value: str) -> str:
    text = normalize_text(value).replace(',', '')
    if "/" in text and "." not in text:
        return text.lstrip("0") or "0"
    return text.rstrip("0").rstrip(".") if "." in text else (text.lstrip("0") or "0")


def _number_value(value: str) -> float:
    text = normalize_text(value).replace(',', '')
    if re.fullmatch(r"\d+\s+\d+/\d+", text):
        whole, fraction = text.split()
        return float(int(whole) + Fraction(fraction))
    if "/" in text and "." not in text:
        return float(Fraction(text))
    return float(text)


def _ocr_phrase_lines(source: dict[str, Any]) -> list[str]:
    ocr = source.get("ocr_evidence") if isinstance(source.get("ocr_evidence"), dict) else {}
    rows: list[tuple[float, float, str]] = []
    for row in ocr.get("lines") or []:
        if not isinstance(row, dict) or float(row.get("confidence") or 0) < 0.8:
            continue
        text = normalize_text(row.get("text"))
        box = row.get("box")
        if not text:
            continue
        if isinstance(box, list) and box and isinstance(box[0], list):
            points = [point for point in box if isinstance(point, list) and len(point) >= 2]
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            rows.append(((sum(ys) / len(ys)) if ys else 0.0, min(xs) if xs else 0.0, text))
        else:
            rows.append((0.0, float(len(rows)), text))
    groups: list[tuple[float, list[tuple[float, str]]]] = []
    for y, x, text in sorted(rows):
        for idx, (gy, values) in enumerate(groups):
            if abs(gy - y) <= 18:
                values.append((x, text))
                groups[idx] = ((gy + y) / 2.0, values)
                break
        else:
            groups.append((y, [(x, text)]))
    merged = [" ".join(text for _, text in sorted(values)) for _, values in groups if len(values) > 1]
    return [text for _, _, text in rows] + merged
