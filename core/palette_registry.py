from __future__ import annotations

import colorsys
import hashlib
import math
import re
import warnings
from pathlib import Path
from typing import Any

from .paths import CONFIGS_ROOT
from .simple_yaml import load_yaml

PALETTE_REGISTRY_PATH = CONFIGS_ROOT / "palette_registry.yaml"
PALETTE_REGISTRY_SCHEMA_VERSION = "palette-registry-v2"
PALETTE_SELECTION_POLICY_VERSION = "dynamic-palette-selection-v8-consistent-ciede2000"


def _read_registry() -> dict[str, Any]:
    if not PALETTE_REGISTRY_PATH.is_file():
        raise RuntimeError(f"Palette registry is missing: {PALETTE_REGISTRY_PATH}")
    data = load_yaml(PALETTE_REGISTRY_PATH)
    if not isinstance(data, dict) or data.get("schema_version") != PALETTE_REGISTRY_SCHEMA_VERSION:
        raise RuntimeError("Palette registry schema is invalid")
    profiles = data.get("style_profiles")
    rules = data.get("role_rules")
    if not isinstance(profiles, list) or not profiles:
        raise RuntimeError("Palette registry has no dynamic style profiles")
    if not isinstance(rules, dict) or not rules:
        raise RuntimeError("Palette registry has no role rules")
    for profile in profiles:
        if not isinstance(profile, dict) or not str(profile.get("profile_id") or "").strip():
            raise RuntimeError("Palette registry contains a malformed style profile")
    if isinstance(data.get("routes"), list):
        raise RuntimeError("Palette registry still contains retired fixed routes")
    return data


_REGISTRY = _read_registry()


def palette_registry_version() -> str:
    return f"{PALETTE_REGISTRY_SCHEMA_VERSION}-{hashlib.sha256(PALETTE_REGISTRY_PATH.read_bytes()).hexdigest()[:12]}"


def palette_registry_policy_version() -> str:
    return f"{PALETTE_SELECTION_POLICY_VERSION}-{palette_registry_version()}"


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _color_family(product_color: Any) -> str:
    text = _normalized(product_color)
    families = (
        ("white", ("white", "ivory", "off-white", "cream")),
        ("black", ("black", "ebony")),
        ("charcoal", ("charcoal", "graphite")),
        ("gray", ("gray", "grey", "greige", "silver")),
        ("natural", ("natural", "wood")),
        ("wood", ("oak", "walnut", "chestnut", "cedar", "pine")),
        ("brown", ("brown", "chocolate", "mocha", "espresso")),
        ("blue", ("blue", "teal", "slate")),
        ("navy", ("navy", "indigo")),
        ("green", ("green", "forest")),
        ("sage", ("sage",)),
        ("olive", ("olive",)),
        ("pink", ("pink",)),
        ("blush", ("blush",)),
        ("mauve", ("mauve", "plum")),
        ("beige", ("beige",)),
        ("tan", ("tan",)),
        ("khaki", ("khaki",)),
        ("red", ("red", "crimson")),
        ("orange", ("orange", "coral")),
        ("yellow", ("yellow", "mustard")),
        ("purple", ("purple", "violet")),
        ("chromatic", ("red", "orange", "yellow", "gold", "purple", "violet")),
        ("dark", ("dark",)),
    )
    for family, tokens in families:
        if any(re.search(rf"(?<![a-z]){re.escape(token)}(?![a-z])", text) for token in tokens):
            if family in {"charcoal", "dark"}:
                return "black"
            if family == "navy":
                return "blue"
            if family in {"sage", "olive"}:
                return "green"
            if family in {"pink", "blush", "mauve"}:
                return "pink"
            if family in {"tan", "khaki", "cream"}:
                return "beige"
            if family == "wood":
                return "natural"
            return family
    return "unclassified"


def _hex_rgb(value: Any) -> tuple[float, float, float]:
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", text):
        raise ValueError(f"Invalid palette color: {value}")
    return tuple(int(text[index:index + 2], 16) / 255.0 for index in (0, 2, 4))


def _rgb_hex(rgb: tuple[float, float, float]) -> str:
    channels = [max(0, min(255, round(value * 255))) for value in rgb]
    return "#" + "".join(f"{channel:02X}" for channel in channels)


def _hsl_hex(hue: float, saturation: float, lightness: float) -> str:
    rgb = colorsys.hls_to_rgb((hue % 360.0) / 360.0, max(0.0, min(1.0, lightness)), max(0.0, min(1.0, saturation)))
    return _rgb_hex(rgb)


def _relative_luminance(rgb: tuple[float, float, float]) -> float:
    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
    high, low = sorted((_relative_luminance(first), _relative_luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _srgb_lab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in rgb)
    x = (0.4124 * red + 0.3576 * green + 0.1805 * blue) / (0.3127 / 0.3290)
    y = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 1.0
    z = (0.0193 * red + 0.1192 * green + 0.9505 * blue) / ((1 - 0.3127 - 0.3290) / 0.3290)

    def lab_component(value: float) -> float:
        return value ** (1 / 3) if value > (6 / 29) ** 3 else value / (3 * (6 / 29) ** 2) + (4 / 29)

    fx, fy, fz = (lab_component(value) for value in (x, y, z))
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _delta_e(first: tuple[float, float, float], second: tuple[float, float, float]) -> tuple[float, str]:
    first_lab, second_lab = _srgb_lab(first), _srgb_lab(second)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import colour  # type: ignore

        return float(colour.delta_E(first_lab, second_lab, method="CIE 2000")), "colour-science-ciede2000"
    except (ImportError, KeyError, TypeError, ValueError, AttributeError):
        return _ciede2000(first_lab, second_lab), "local-ciede2000"


def _ciede2000(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
    """CIEDE2000, kL=kC=kH=1; identical metric when optional colour is absent."""
    l1, a1, b1 = first
    l2, a2, b2 = second
    cbar = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    g = (1 - math.sqrt(cbar ** 7 / (cbar ** 7 + 25 ** 7))) / 2
    ap1, ap2 = (1 + g) * a1, (1 + g) * a2
    c1, c2 = math.hypot(ap1, b1), math.hypot(ap2, b2)
    h1 = math.degrees(math.atan2(b1, ap1)) % 360 if c1 else 0.0
    h2 = math.degrees(math.atan2(b2, ap2)) % 360 if c2 else 0.0
    dh = h2 - h1
    if not c1 * c2:
        dh = 0.0
    elif dh > 180:
        dh -= 360
    elif dh < -180:
        dh += 360
    dl, dc = l2 - l1, c2 - c1
    dH = 2 * math.sqrt(c1 * c2) * math.sin(math.radians(dh / 2))
    lm, cm = (l1 + l2) / 2, (c1 + c2) / 2
    if not c1 * c2:
        hm = h1 + h2
    elif abs(h1 - h2) <= 180:
        hm = (h1 + h2) / 2
    else:
        hm = (h1 + h2 + (360 if h1 + h2 < 360 else -360)) / 2
    t = (1 - .17 * math.cos(math.radians(hm - 30)) + .24 * math.cos(math.radians(2 * hm))
         + .32 * math.cos(math.radians(3 * hm + 6)) - .20 * math.cos(math.radians(4 * hm - 63)))
    sl = 1 + .015 * (lm - 50) ** 2 / math.sqrt(20 + (lm - 50) ** 2)
    sc, sh = 1 + .045 * cm, 1 + .015 * cm * t
    rt = -2 * math.sqrt(cm ** 7 / (cm ** 7 + 25 ** 7)) * math.sin(
        math.radians(60 * math.exp(-((hm - 275) / 25) ** 2)))
    return math.sqrt(max(0.0, (dl / sl) ** 2 + (dc / sc) ** 2 + (dH / sh) ** 2 + rt * dc / sc * dH / sh))


def _stable_unit(seed: str, suffix: str) -> float:
    digest = hashlib.sha256(f"{seed}:{suffix}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16) / float(16 ** 12 - 1)


def _hue_family_count(values: list[tuple[float, float, float]]) -> int:
    hues = sorted(
        (hue * 360.0 for hue, _, saturation in (colorsys.rgb_to_hls(*rgb) for rgb in values) if saturation >= 0.16),
    )
    if not hues:
        return 0
    groups: list[float] = []
    for hue in hues:
        if not groups or min(abs(hue - groups[-1]), 360.0 - abs(hue - groups[-1])) > 38.0:
            groups.append(hue)
        else:
            groups[-1] = (groups[-1] + hue) / 2.0
    if len(groups) > 1 and min(abs(groups[0] - groups[-1]), 360.0 - abs(groups[0] - groups[-1])) <= 38.0:
        groups = groups[1:]
    return len(groups)


def _circular_hue_span(hues: list[float]) -> float:
    """Return the smallest hue arc containing all active hues."""
    if len(hues) < 2:
        return 0.0
    ordered = sorted(value % 360.0 for value in hues)
    gaps = [
        ordered[index + 1] - ordered[index]
        for index in range(len(ordered) - 1)
    ]
    gaps.append((ordered[0] + 360.0) - ordered[-1])
    return max(0.0, 360.0 - max(gaps))


def _hue_in_range(hue: float, value: Any) -> bool:
    if not isinstance(value, list) or len(value) < 2:
        return False
    try:
        low, high = float(value[0]) % 360.0, float(value[1]) % 360.0
    except (TypeError, ValueError):
        return False
    hue = hue % 360.0
    return low <= hue <= high if low <= high else hue >= low or hue <= high


def _range_value(value: Any, default: tuple[float, float], seed: str, suffix: str) -> float:
    values = value if isinstance(value, (list, tuple)) and len(value) >= 2 else list(default)
    try:
        low, high = float(values[0]), float(values[1])
    except (TypeError, ValueError):
        low, high = default
    return low + (high - low) * _stable_unit(seed, suffix)


def _range_options(value: Any, default: tuple[float, float]) -> list[tuple[float, float]]:
    """Normalize curated hue options without making YAML a second engine."""
    if not isinstance(value, list):
        return [default]
    options: list[tuple[float, float]] = []
    for item in value:
        if isinstance(item, list) and len(item) >= 2:
            raw = item[:2]
        else:
            text = str(item or "").strip()
            match = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)", text)
            raw = match.groups() if match else ()
        try:
            low, high = float(raw[0]), float(raw[1])
        except (IndexError, TypeError, ValueError):
            continue
        if 0.0 <= low <= 360.0 and 0.0 <= high <= 360.0:
            options.append((low, high))
    return options or [default]


def _select_range(value: Any, default: tuple[float, float], seed: str, suffix: str) -> tuple[float, float]:
    options = _range_options(value, default)
    index = min(len(options) - 1, int(_stable_unit(seed, suffix) * len(options)))
    return options[index]


def _circular_mix(first: float, second: float, weight: float) -> float:
    first_rad, second_rad = math.radians(first), math.radians(second)
    x = math.cos(first_rad) * weight + math.cos(second_rad) * (1.0 - weight)
    y = math.sin(first_rad) * weight + math.sin(second_rad) * (1.0 - weight)
    return math.degrees(math.atan2(y, x)) % 360.0


def _product_anchor(product_color: Any) -> dict[str, Any]:
    text = _normalized(product_color)
    match = re.search(r"#?([0-9a-f]{6})", text)
    if match:
        rgb = _hex_rgb(match.group(1))
        hue, lightness, saturation = colorsys.rgb_to_hls(*rgb)
        return {"family": "explicit", "hue": hue * 360.0, "lightness": lightness, "saturation": saturation, "rgb": rgb}
    family = _color_family(product_color)
    values = {
        "white": (0.0, 0.94, 0.03),
        "black": (220.0, 0.16, 0.08),
        "gray": (90.0, 0.52, 0.08),
        "natural": (30.0, 0.48, 0.34),
        "brown": (28.0, 0.26, 0.38),
        "blue": (210.0, 0.46, 0.48),
        "green": (135.0, 0.46, 0.30),
        "pink": (345.0, 0.68, 0.28),
        "beige": (38.0, 0.72, 0.22),
        "red": (0.0, 0.52, 0.52),
        "orange": (24.0, 0.52, 0.56),
        "yellow": (52.0, 0.56, 0.62),
        "purple": (285.0, 0.52, 0.42),
        "chromatic": (12.0, 0.52, 0.52),
        "unclassified": (35.0, 0.55, 0.10),
    }
    hue, lightness, saturation = values.get(family, values["unclassified"])
    rgb = colorsys.hls_to_rgb(hue / 360.0, lightness, saturation)
    return {"family": family, "hue": hue, "lightness": lightness, "saturation": saturation, "rgb": rgb}


def _role_rules(role: str, key: str, default: tuple[float, float]) -> tuple[float, float]:
    rules = _REGISTRY.get("role_rules") if isinstance(_REGISTRY.get("role_rules"), dict) else {}
    row = rules.get(role) if isinstance(rules.get(role), dict) else {}
    return tuple(row.get(key) or default)  # type: ignore[return-value]


def _style_profiles() -> list[dict[str, Any]]:
    return [row for row in _REGISTRY.get("style_profiles", []) if isinstance(row, dict)]


def _selection_policy() -> dict[str, Any]:
    policy = _REGISTRY.get("selection_policy")
    return policy if isinstance(policy, dict) else {}


def _harmony_modes() -> dict[str, dict[str, Any]]:
    configured = _selection_policy().get("accent_harmony_modes")
    if isinstance(configured, dict):
        return {
            str(key): value
            for key, value in configured.items()
            if isinstance(value, dict)
        }
    return {
        "analogous": {"hue_offset_deg": [-28, 28], "saturation": [0.10, 0.28], "lightness": [0.44, 0.62]},
        "mineral_neutral": {"hue_offset_deg": [-8, 18], "saturation": [0.06, 0.16], "lightness": [0.46, 0.64]},
        "softened_complement": {"hue_offset_deg": [148, 205], "saturation": [0.10, 0.26], "lightness": [0.44, 0.60]},
    }


def _harmony_order(category_id: str) -> list[str]:
    configured = _selection_policy().get("category_harmony_preferences")
    preferred = configured.get(category_id) if isinstance(configured, dict) else None
    names = list(_harmony_modes())
    ordered = [str(value) for value in preferred or [] if str(value) in names]
    return ordered + [name for name in names if name not in ordered]


def _candidate_palette(
    *, profile: dict[str, Any], anchor: dict[str, Any], seed: str, harmony_mode: str,
) -> dict[str, Any]:
    profile_id = str(profile.get("profile_id") or "style")
    anchor_hue = float(anchor["hue"])
    seed_hue = float(profile.get("seed_hue_deg") or 0.0)
    product_weight = float(profile.get("product_hue_weight") or 0.0)
    if float(anchor.get("saturation") or 0.0) < 0.08:
        product_weight = 0.0
    base_hue = _circular_mix(anchor_hue, seed_hue, product_weight)
    scale = float(profile.get("saturation_scale") or 1.0)
    dark_product = float(anchor["lightness"]) < 0.38
    light_product = float(anchor["lightness"]) > 0.72

    def color(role: str, hue_offset_key: str, saturation_default: tuple[float, float], lightness_default: tuple[float, float], suffix: str) -> str:
        hue = base_hue + float(profile.get(hue_offset_key) or 0.0)
        saturation = _range_value(_role_rules(role, "saturation", saturation_default), saturation_default, seed, f"{profile_id}:{suffix}:s") * scale
        lightness = _range_value(_role_rules(role, "lightness", lightness_default), lightness_default, seed, f"{profile_id}:{suffix}:l")
        return _hsl_hex(hue, saturation, lightness)

    wall_lightness = (0.82, 0.94) if dark_product else (0.82, 0.94) if light_product else (0.80, 0.92)
    wall_saturation = (0.10, 0.28) if light_product else (0.06, 0.18)
    textile_lightness = (0.46, 0.68) if dark_product else (0.42, 0.64)
    warm_textile_families = {
        str(value).strip().casefold()
        for value in ("natural", "beige", "brown")
        if str(value).strip()
    }
    warm_textile_range = _selection_policy().get("warm_textile_hue_range_deg")
    staging_textile_range = _selection_policy().get("staging_textile_hue_options") or _selection_policy().get("staging_textile_hue_range_deg") or warm_textile_range
    if str(anchor.get("family") or "").casefold() in {"yellow", "orange", "natural", "beige", "brown"} and harmony_mode != "softened_complement":
        # A cool textile is valid as an intentional complement, but must not
        # appear as an unrelated accent on a warm product.
        staging_textile_range = [value for value in _range_options(staging_textile_range, (24.0, 48.0)) if value[1] <= 180.0]
        staging_textile_range = staging_textile_range or (24.0, 48.0)
    staging_textile_range = _select_range(
        staging_textile_range,
        (24.0, 48.0),
        seed,
        f"{profile_id}:{harmony_mode}:textile-hue-family",
    )
    staging_floor_range = _selection_policy().get("staging_floor_hue_range_deg") or warm_textile_range
    staging_floor_saturation = _selection_policy().get("staging_floor_saturation") or (0.06, 0.18)
    wood_textile_saturation = _selection_policy().get("wood_textile_saturation") or (0.10, 0.26)
    wood_textile_lightness = _selection_policy().get("wood_textile_lightness") or (0.54, 0.72)
    textile_primary_saturation = wood_textile_saturation if str(anchor.get("family") or "").casefold() in warm_textile_families else _role_rules("textile_primary", "saturation", (0.16, 0.42))
    textile_primary_lightness = wood_textile_lightness if str(anchor.get("family") or "").casefold() in warm_textile_families else _role_rules("textile_primary", "lightness", textile_lightness)
    harmony = _harmony_modes().get(harmony_mode) or _harmony_modes()[next(iter(_harmony_modes()))]
    accent_base_hue = float(anchor["hue"]) if float(anchor.get("saturation") or 0.0) >= 0.08 else base_hue
    accent_hue = accent_base_hue + _range_value(
        harmony.get("hue_offset_deg"), (0.0, 24.0), seed, f"{profile_id}:{harmony_mode}:accent:h",
    )
    accent_saturation = _range_value(
        harmony.get("saturation"), (0.08, 0.22), seed, f"{profile_id}:{harmony_mode}:accent:s",
    ) * scale
    accent_lightness = _range_value(
        harmony.get("lightness"), (0.44, 0.62), seed, f"{profile_id}:{harmony_mode}:accent:l",
    )
    palette = {
        "room_primary": color("wall", "wall_hue_offset_deg", wall_saturation, wall_lightness, "room_primary"),
        "room_secondary": color("wall_secondary", "secondary_hue_offset_deg", (0.04, 0.16), (0.78, 0.93), "room_secondary"),
        "textile_primary": _hsl_hex(
            _range_value(staging_textile_range, (24.0, 48.0), seed, f"{profile_id}:textile_primary:h"),
            _range_value(textile_primary_saturation, textile_primary_saturation, seed, f"{profile_id}:textile_primary:s") * scale,
            _range_value(textile_primary_lightness, textile_primary_lightness, seed, f"{profile_id}:textile_primary:l"),
        ),
        "textile_secondary": _hsl_hex(
            _range_value(staging_textile_range, (24.0, 48.0), seed, f"{profile_id}:textile_secondary:h"),
            _range_value(_role_rules("textile_secondary", "saturation", (0.05, 0.20)), (0.05, 0.20), seed, f"{profile_id}:textile_secondary:s") * scale,
            _range_value(_role_rules("textile_secondary", "lightness", (0.72, 0.92)), (0.72, 0.92), seed, f"{profile_id}:textile_secondary:l"),
        ),
        "accent": _hsl_hex(accent_hue, accent_saturation, accent_lightness),
        "floor": _hsl_hex(
            _range_value(staging_floor_range, (24.0, 48.0), seed, f"{profile_id}:floor:h"),
            _range_value(_role_rules("floor", "saturation", staging_floor_saturation), staging_floor_saturation, seed, f"{profile_id}:floor:s") * scale,
            _range_value(_role_rules("floor", "lightness", (0.38, 0.60)), (0.38, 0.60), seed, f"{profile_id}:floor:l"),
        ),
    }
    graphic_ink = _hsl_hex(205.0, 0.24, float((_REGISTRY.get("role_rules", {}).get("graphic", {}) or {}).get("ink_lightness") or 0.18))
    graphic_surface = _hsl_hex(36.0, 0.14, float((_REGISTRY.get("role_rules", {}).get("graphic", {}) or {}).get("surface_lightness") or 0.94))
    graphic_line = _hsl_hex(205.0, 0.10, float((_REGISTRY.get("role_rules", {}).get("graphic", {}) or {}).get("line_lightness") or 0.56))
    accent_hue, accent_lightness, accent_saturation = colorsys.rgb_to_hls(*_hex_rgb(palette["accent"]))
    graphic_rules = _REGISTRY.get("role_rules", {}).get("graphic", {})
    graphic_accent_saturation = min(
        accent_saturation,
        max(0.0, float(graphic_rules.get("accent_saturation_max") or 0.32)),
    )
    palette.update({
        "graphic_ink": graphic_ink,
        "graphic_surface": graphic_surface,
        "graphic_line": graphic_line,
        # Graphic accents stay in the child palette but are calmer than loose
        # props, so badges and arrows do not become the loudest element.
        "graphic_accent": _hsl_hex(
            accent_hue * 360.0,
            graphic_accent_saturation,
            min(max(accent_lightness, 0.42), 0.60),
        ),
    })
    return palette


def palette_metrics(candidate: dict[str, Any], *, product_rgb: tuple[float, float, float] | None = None) -> dict[str, Any]:
    palette = candidate.get("palette") if isinstance(candidate.get("palette"), dict) else candidate
    color_keys = ("room_primary", "room_secondary", "textile_primary", "textile_secondary", "accent", "floor")
    values = [_hex_rgb(palette[key]) for key in color_keys if palette.get(key)]
    if product_rgb:
        values.append(product_rgb)
    if not values:
        raise ValueError("Dynamic palette has no staging colors")
    hls = [colorsys.rgb_to_hls(*rgb) for rgb in values]
    luminances = [_relative_luminance(rgb) for rgb in values]
    delta_values = [
        _delta_e(values[index], values[other])[0]
        for index in range(len(values))
        for other in range(index + 1, len(values))
    ]
    hue_values = [hue * 360.0 for hue, _, saturation in hls if saturation >= 0.16]
    return {
        "engine": _delta_e(values[0], values[1])[1] if len(values) > 1 else "local-ciede2000",
        "hue_span_deg": round(_circular_hue_span(hue_values), 1),
        "hue_count": _hue_family_count(values),
        "lightness_range": [round(min(light for _, light, _ in hls), 3), round(max(light for _, light, _ in hls), 3)],
        "contrast_ratio_max": round(max(_contrast_ratio(values[index], values[other]) for index in range(len(values)) for other in range(index + 1, len(values))), 2) if len(values) > 1 else 1.0,
        "delta_e_max": round(max(delta_values), 1) if delta_values else 0.0,
        "graphic_text_contrast": round(_contrast_ratio(_hex_rgb(palette["graphic_ink"]), _hex_rgb(palette["graphic_surface"])), 2),
    }


def _distance_fit(value: float, low: float, high: float) -> float:
    if low <= value <= high:
        return 1.0
    if value < low:
        return max(0.0, value / low) if low else 0.0
    span = max(1.0, high - low)
    return max(0.0, 1.0 - ((value - high) / span))


def _market_fit(profile: dict[str, Any], category_id: str) -> float:
    policy = _selection_policy()
    category_cues = policy.get("market_cues") if isinstance(policy.get("market_cues"), dict) else {}
    ordered = category_cues.get(category_id) or category_cues.get("default") or []
    profile_cues = {str(item) for item in profile.get("market_fit") or []}
    positions = [index for index, cue in enumerate(ordered) if str(cue) in profile_cues]
    return min(1.0, sum((len(ordered) - index) / max(1, len(ordered)) for index in positions) / max(1, len(positions))) if positions else 0.35


def _quality_issues(candidate: dict[str, Any], *, product_rgb: tuple[float, float, float]) -> list[str]:
    """Describe palette risks without turning aesthetics into a runtime blocker."""
    palette = candidate["palette"]
    metrics = candidate["metrics"]
    policy = _selection_policy()
    issues: list[str] = []
    max_hues = int(float(policy.get("max_competing_hues") or 3.0))
    if int(float(metrics.get("hue_count") or 0.0)) > max_hues:
        issues.append("too_many_competing_hues")
    graphic_rules = _REGISTRY.get("role_rules", {}).get("graphic", {})
    if float(metrics.get("graphic_text_contrast") or 0.0) < float(graphic_rules.get("min_text_contrast") or 4.5):
        issues.append("weak_graphic_contrast")

    guardrails = policy.get("residential_guardrails") if isinstance(policy.get("residential_guardrails"), dict) else {}
    staging_roles = tuple(str(role) for role in (guardrails.get("avoid_hue_roles") or ("room_primary", "textile_primary", "floor", "accent")))
    avoid_hue_range = guardrails.get("avoid_hue_range") or [265, 360]
    avoid_saturation_min = float(guardrails.get("avoid_hue_saturation_min") or 0.12)
    staging_hsl = {
        role: colorsys.rgb_to_hls(*_hex_rgb(palette[role]))
        for role in staging_roles
        if palette.get(role)
    }
    if any(
        _hue_in_range(hls[0] * 360.0, avoid_hue_range) and hls[2] >= avoid_saturation_min
        for hls in staging_hsl.values()
    ):
        issues.append("purple_magenta_staging")
    max_room_saturation = float(guardrails.get("max_room_saturation") or 0.18)
    max_textile_saturation = float(guardrails.get("max_textile_saturation") or 0.34)
    max_accent_saturation = float(guardrails.get("max_accent_saturation") or 0.42)
    if colorsys.rgb_to_hls(*_hex_rgb(palette["room_primary"]))[2] > max_room_saturation:
        issues.append("over_saturated_room")
    if colorsys.rgb_to_hls(*_hex_rgb(palette["textile_primary"]))[2] > max_textile_saturation:
        issues.append("over_saturated_textile")
    if colorsys.rgb_to_hls(*_hex_rgb(palette["accent"]))[2] > max_accent_saturation:
        issues.append("over_saturated_accent")

    product_hue, product_lightness, product_saturation = colorsys.rgb_to_hls(*product_rgb)
    textile_rgb = _hex_rgb(palette["textile_primary"])
    if product_saturation >= 0.16 and _delta_e(product_rgb, textile_rgb)[0] < 12.0:
        issues.append("product_color_repeated_as_textile")

    active_saturation = [
        colorsys.rgb_to_hls(*_hex_rgb(palette[key]))[2]
        for key in ("textile_primary", "textile_secondary", "accent")
        if palette.get(key)
    ]
    if sum(value >= 0.45 for value in active_saturation) > 1:
        issues.append("more_than_one_high_chroma_accent")

    accent_hue, _, _ = colorsys.rgb_to_hls(*_hex_rgb(palette["graphic_accent"]))
    accent_degrees = accent_hue * 360.0
    if product_lightness < 0.35 and 24.0 <= accent_degrees <= 58.0:
        issues.append("gold_accent_on_dark_product")
    return issues


def _reference_fit(candidate: dict[str, Any], *, category_id: str) -> float:
    """Score curated offline residential priors; this never blocks a task."""
    policy = _selection_policy()
    configured = policy.get("reference_priors") if isinstance(policy.get("reference_priors"), dict) else {}
    prior = configured.get(category_id) if isinstance(configured.get(category_id), dict) else configured.get("default")
    if not isinstance(prior, dict):
        return 0.5
    palette = candidate.get("palette") if isinstance(candidate.get("palette"), dict) else {}
    ranges = prior.get("role_hue_ranges") if isinstance(prior.get("role_hue_ranges"), dict) else {}
    limits = prior.get("saturation_limits") if isinstance(prior.get("saturation_limits"), dict) else {}
    role_scores: list[float] = []
    for role in ("room_primary", "textile_primary", "accent"):
        value = palette.get(role)
        if not value:
            continue
        hue, _lightness, saturation = colorsys.rgb_to_hls(*_hex_rgb(value))
        options = _range_options(ranges.get(role), (0.0, 360.0))
        hue_score = 1.0 if any(_hue_in_range(hue * 360.0, list(item)) for item in options) else 0.35
        limit = float(limits.get(role) or 1.0)
        saturation_score = _distance_fit(saturation, 0.0, limit)
        role_scores.append((hue_score + saturation_score) / 2.0)
    profile_ids = {str(value) for value in prior.get("preferred_profile_ids") or []}
    profile_score = 1.0 if str(candidate.get("profile_id") or "") in profile_ids else 0.45
    return round((sum(role_scores) / len(role_scores) if role_scores else 0.5) * 0.8 + profile_score * 0.2, 3)


def _selection_weights() -> dict[str, float]:
    defaults = {
        "product_background_separation": 0.25,
        "textile_separation": 0.18,
        "hue_balance": 0.15,
        "market_fit": 0.15,
        "variation_diversity": 0.05,
        "graphic_readability": 0.12,
        "exposure_fit": 0.08,
        "harmony_fit": 0.14,
        "reference_fit": 0.12,
    }
    configured = _selection_policy().get("weights")
    if isinstance(configured, dict):
        for key in defaults:
            try:
                defaults[key] = max(0.0, float(configured.get(key, defaults[key])))
            except (TypeError, ValueError):
                continue
    total = sum(defaults.values()) or 1.0
    return {key: value / total for key, value in defaults.items()}


def _palette_score(candidate: dict[str, Any], *, product_rgb: tuple[float, float, float], profile: dict[str, Any], category_id: str) -> tuple[float, dict[str, float]]:
    palette = candidate["palette"]
    room = _hex_rgb(palette["room_primary"])
    secondary_room = _hex_rgb(palette["room_secondary"])
    primary = _hex_rgb(palette["textile_primary"])
    secondary = _hex_rgb(palette["textile_secondary"])
    floor = _hex_rgb(palette["floor"])
    accent = _hex_rgb(palette["accent"])
    product_lightness = colorsys.rgb_to_hls(*product_rgb)[1]
    if product_lightness >= 0.70:
        room_target, textile_target = (8.0, 35.0), (15.0, 58.0)
    elif product_lightness <= 0.35:
        room_target, textile_target = (20.0, 70.0), (14.0, 58.0)
    else:
        room_target, textile_target = (12.0, 52.0), (12.0, 48.0)
    room_separation = _distance_fit(_delta_e(product_rgb, room)[0], *room_target)
    textile_separation = _distance_fit(_delta_e(product_rgb, primary)[0], *textile_target)
    textile_layering = _distance_fit(_delta_e(primary, secondary)[0], 8.0, 42.0)
    accent_separation = _distance_fit(_delta_e(primary, accent)[0], 16.0, 58.0)
    metrics = candidate["metrics"]
    hue_count = float(metrics.get("hue_count") or 0.0)
    hue_balance = _distance_fit(float(metrics.get("hue_span_deg") or 0.0), 28.0, 210.0) * _distance_fit(hue_count, 1.0, 2.0)
    max_competing_hues = float(_selection_policy().get("max_competing_hues") or 3.0)
    if hue_count > max_competing_hues:
        hue_balance *= 0.20
    market_fit = _market_fit(profile, category_id)
    graphic_readability = _distance_fit(float(metrics.get("graphic_text_contrast") or 0.0), 4.5, 18.0)
    room_lightness = colorsys.rgb_to_hls(*room)[1]
    secondary_lightness = colorsys.rgb_to_hls(*secondary_room)[1]
    floor_lightness = colorsys.rgb_to_hls(*floor)[1]
    exposure_fit = (
        _distance_fit(room_lightness, 0.86, 0.95)
        + _distance_fit(secondary_lightness, 0.84, 0.94)
        + _distance_fit(floor_lightness, 0.58, 0.78)
    ) / 3.0
    harmony_rank = _harmony_order(category_id)
    harmony_mode = str(candidate.get("harmony_mode") or "")
    harmony_fit = (
        (len(harmony_rank) - harmony_rank.index(harmony_mode)) / max(1, len(harmony_rank))
        if harmony_mode in harmony_rank else 0.35
    )
    reference_fit = _reference_fit(candidate, category_id=category_id)
    weights = _selection_weights()
    score = (
        room_separation * weights["product_background_separation"]
        + ((textile_separation + textile_layering) / 2.0) * weights["textile_separation"]
        + hue_balance * weights["hue_balance"]
        + market_fit * weights["market_fit"]
        + accent_separation * weights["variation_diversity"]
        + graphic_readability * weights["graphic_readability"]
        + exposure_fit * weights["exposure_fit"]
        + harmony_fit * weights["harmony_fit"]
        + reference_fit * weights["reference_fit"]
    )
    return round(score * 100.0, 2), {
        "product_background_separation": round(room_separation, 3),
        "textile_separation": round((textile_separation + textile_layering) / 2.0, 3),
        "hue_balance": round(hue_balance, 3),
        "market_fit": round(market_fit, 3),
        "variation_diversity": round(accent_separation, 3),
        "graphic_readability": round(graphic_readability, 3),
        "exposure_fit": round(exposure_fit, 3),
        "harmony_fit": round(harmony_fit, 3),
        "reference_fit": round(reference_fit, 3),
    }


def palette_recipe(route: dict[str, Any]) -> dict[str, str]:
    palette = route.get("palette") if isinstance(route.get("palette"), dict) else {}
    return {str(key): str(value) for key, value in palette.items() if value not in (None, "")}


def _background_anchor(palette: dict[str, Any]) -> dict[str, str]:
    return {
        "wall": str(palette.get("room_primary") or "#D9D6D7"),
        "secondary": str(palette.get("room_secondary") or "#E0DFDC"),
        "floor": str(palette.get("floor") or "#7B606A"),
    }


def _semantic_roles() -> dict[str, list[str]]:
    value = _REGISTRY.get("semantic_roles")
    if not isinstance(value, dict):
        return {
            "staging_primary": ["textile_primary"],
            "staging_secondary": ["textile_secondary"],
            "props": ["accent", "textile_secondary"],
            "primary_graphics": ["graphic_ink"],
            "secondary_graphics": ["graphic_line"],
        }
    return {
        str(key): [str(item) for item in items if str(item).strip()]
        for key, items in value.items()
        if isinstance(items, list) and items
    }


def select_palette_route(*, category_id: str, product_color: Any, route_key: Any, size: Any = "", variation: Any = None) -> dict[str, Any]:
    family = _color_family(product_color)
    anchor = _product_anchor(product_color)
    variation_payload = variation if isinstance(variation, dict) else {}
    seed = "|".join((str(category_id or ""), _normalized(product_color), _normalized(route_key), _normalized(size), repr(sorted(variation_payload.items()))))
    generated: list[dict[str, Any]] = []
    for profile in _style_profiles():
        for harmony_mode in _harmony_order(str(category_id or "")):
            candidate = {
                "profile_id": str(profile.get("profile_id") or "style"),
                "harmony_mode": harmony_mode,
                "color_family": family,
                "product_identity": _normalized(product_color),
                "palette": _candidate_palette(
                    profile=profile,
                    anchor=anchor,
                    seed=seed,
                    harmony_mode=harmony_mode,
                ),
            }
            candidate["metrics"] = palette_metrics(candidate, product_rgb=anchor["rgb"])
            candidate["quality_issues"] = _quality_issues(candidate, product_rgb=anchor["rgb"])
            score, components = _palette_score(candidate, product_rgb=anchor["rgb"], profile=profile, category_id=str(category_id or ""))
            candidate["selection_score"] = score
            candidate["selection_components"] = components
            generated.append(candidate)
    if not generated:
        raise RuntimeError("Palette registry has no dynamic style profiles")
    generated.sort(
        key=lambda row: (
            len(row.get("quality_issues") or []),
            -float(row["selection_score"]),
            str(row["profile_id"]),
        )
    )
    selection_policy = _selection_policy()
    spatial_limits = {
        "max_competing_hues": int(float(selection_policy.get("max_competing_hues") or 3.0)),
        "accent_max_area_ratio": float(selection_policy.get("accent_max_area_ratio") or 0.08),
        "graphic_accent_max_area_ratio": float(selection_policy.get("graphic_accent_max_area_ratio") or 0.05),
    }
    # Child-specific variation still comes from the child seed while the
    # selected route is the best coherent candidate, never a broad score-tie
    # lottery between unrelated style systems.
    selected = dict(generated[0])
    selected["selection_basis"] = {
        "category": str(category_id or ""),
        "product_color": _normalized(product_color),
        "product_anchor": {key: value for key, value in anchor.items() if key != "rgb"},
        "size": _normalized(size),
        "variation": variation_payload,
        "route_key": str(route_key or "").strip(),
        "policy": PALETTE_SELECTION_POLICY_VERSION,
        "harmony_mode": str(selected.get("harmony_mode") or ""),
        "spatial_limits": spatial_limits,
        "background_anchor": _background_anchor(selected["palette"]),
        "semantic_roles": _semantic_roles(),
        "candidate_profiles": [str(row["profile_id"]) for row in generated],
        "candidate_count": len(generated),
        "quality_issues": list(selected.get("quality_issues") or []),
    }
    selected["route_id"] = f"dynamic:{selected['profile_id']}:{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:10]}"
    selected["recipe"] = palette_recipe(selected)
    selected.pop("product_identity", None)
    return selected


def palette_registry_snapshot() -> dict[str, Any]:
    return {
        "schema_version": PALETTE_REGISTRY_SCHEMA_VERSION,
        "policy_version": palette_registry_policy_version(),
        "path": PALETTE_REGISTRY_PATH.as_posix(),
        "profile_count": len(_style_profiles()),
        "reference_source_count": sum(
            len(group) for group in (_REGISTRY.get("reference_sources") or {}).values() if isinstance(group, list)
        ),
        "fixed_routes_retired": True,
    }
