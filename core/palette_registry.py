from __future__ import annotations

import math
import re
import warnings
from typing import Any

def _hex_rgb(value: Any) -> tuple[float, float, float]:
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", text):
        raise ValueError(f"Invalid palette color: {value}")
    return tuple(int(text[index:index + 2], 16) / 255.0 for index in (0, 2, 4))


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


def planned_palette_diagnostics(direction: dict[str, Any]) -> dict[str, Any]:
    """Measure the actual Gemini choices for audit only; never select or veto design."""
    colors, alpha, unresolved = {}, {}, []
    for section in ("palette_direction", "graphic_direction"):
        for role, value in direction.get(section, {}).items():
            matches = re.findall(r"#(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{6})\b", str(value))
            if len(matches) == 1:
                name, token = f"{section}.{role}", matches[0]
                colors[name] = _hex_rgb(token[:7])
                alpha[name] = int(token[7:9], 16) / 255 if len(token) == 9 else 1.0
            elif section == "palette_direction" or role.endswith("_color"):
                unresolved.append(f"{section}.{role}")
    def compare(first: str, second: str, *, underlay: str = "") -> dict[str, Any]:
        background = colors[second]
        if underlay:
            background = tuple(alpha[second] * c + (1 - alpha[second]) * b
                               for c, b in zip(background, colors[underlay]))
        foreground = tuple(alpha[first] * c + (1 - alpha[first]) * b for c, b in zip(colors[first], background))
        return {"first": first, "second": second, "underlay": underlay,
                "contrast": round(_contrast_ratio(foreground, background), 3),
                "delta_e_2000": round(_delta_e(foreground, background)[0], 3)}

    # Report plausible presentation pairings, not every mathematically possible color pair.
    backgrounds = [key for key in colors if key.startswith("palette_direction.") and alpha[key] == 1]
    pairs = [compare(key, background) for key in colors
             if key in {"graphic_direction.text_color", "graphic_direction.line_color", "graphic_direction.icon_color"}
             for background in backgrounds]
    backing = "graphic_direction.backing_color"
    if backing in colors:
        for key in ("graphic_direction.text_color", "graphic_direction.backed_symbol_color"):
            if key in colors:
                pairs.extend(compare(key, backing, underlay=base) for base in (backgrounds if alpha[backing] < 1 else [""]))
        if alpha[backing] < 1 and not backgrounds:
            unresolved.append(backing + ": no opaque underlay")
    return {
        "authority": "diagnostics_only_no_design_or_qa_decision",
        "colors": {role: {"luminance": round(_relative_luminance(rgb), 4), "alpha": alpha[role]}
                   for role, rgb in colors.items()},
        "pairs": pairs, "unresolved": unresolved,
        "pairing_scope": "possible_surfaces_not_observed_image_pixels",
    }
