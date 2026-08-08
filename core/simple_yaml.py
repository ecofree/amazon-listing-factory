from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def load_yaml(path: str | Path) -> Any:
    text = Path(path).read_text(encoding="utf-8-sig")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except ModuleNotFoundError:
        pass
    stripped = text.strip()
    if not stripped:
        return {}
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(stripped)
    lines = _clean_lines(text)
    if not lines:
        return {}
    value, index = _parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise ValueError(f"Could not parse YAML subset at line: {lines[index][1]}")
    return value


def _clean_lines(text: str) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        without_comment = _strip_comment(raw.rstrip())
        if not without_comment.strip():
            continue
        indent = len(without_comment) - len(without_comment.lstrip(" "))
        rows.append((indent, without_comment.strip()))
    return rows


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double and (index == 0 or line[index - 1].isspace()):
            return line[:index].rstrip()
    return line


def _parse_block(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    current_indent, text = lines[index]
    if current_indent < indent:
        return {}, index
    if text.startswith("- "):
        return _parse_list(lines, index, current_indent)
    return _parse_mapping(lines, index, current_indent)


def _parse_mapping(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    while index < len(lines):
        current_indent, text = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise ValueError(f"Unexpected indent before: {text}")
        if text.startswith("- "):
            break
        key, value = _split_key_value(text)
        index += 1
        if value == "":
            if index < len(lines) and lines[index][0] > current_indent:
                nested, index = _parse_block(lines, index, lines[index][0])
                out[key] = nested
            else:
                out[key] = None
        else:
            out[key] = _parse_scalar(value)
    return out, index


def _parse_list(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[list[Any], int]:
    out: list[Any] = []
    while index < len(lines):
        current_indent, text = lines[index]
        if current_indent < indent:
            break
        if current_indent != indent or not text.startswith("- "):
            break
        item_text = text[2:].strip()
        index += 1
        if not item_text:
            if index < len(lines) and lines[index][0] > current_indent:
                item, index = _parse_block(lines, index, lines[index][0])
            else:
                item = None
        elif _looks_like_mapping_item(item_text):
            key, value = _split_key_value(item_text)
            item = {key: _parse_scalar(value) if value else {}}
            if index < len(lines) and lines[index][0] > current_indent:
                nested, index = _parse_block(lines, index, lines[index][0])
                if isinstance(nested, dict):
                    item.update(nested)
                else:
                    item[key] = nested
        else:
            item = _parse_scalar(item_text)
        out.append(item)
    return out, index


def _split_key_value(text: str) -> tuple[str, str]:
    if ":" not in text:
        raise ValueError(f"Expected key/value pair: {text}")
    key, value = text.split(":", 1)
    return key.strip(), value.strip()


def _looks_like_mapping_item(text: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9_.-]+\s*:", text))


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "Null", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part.strip()) for part in inner.split(",")]
    if re.match(r"^-?\d+$", value):
        try:
            return int(value)
        except ValueError:
            pass
    if re.match(r"^-?\d+\.\d+$", value):
        try:
            return float(value)
        except ValueError:
            pass
    return value
