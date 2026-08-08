from __future__ import annotations

import os
import posixpath
import re
import struct
import zipfile
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from typing import Any, Callable


class TemplatePackageError(RuntimeError):
    pass


_ZIP_LOCAL_FILE_HEADER = struct.Struct("<IHHHHHIIIHH")
_ZIP_CENTRAL_DIRECTORY_HEADER = struct.Struct("<IHHHHHHIIIHHHHHII")
_ZIP_END_CENTRAL_DIRECTORY = struct.Struct("<IHHHHIIH")


def write_plan_package(
    plan: dict[str, Any], output_path: str | Path,
    *, value_transform: Callable[[str, Any], Any] | None = None,
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    template = Path(str(plan.get("template_path") or ""))
    if not template.is_file():
        raise TemplatePackageError(f"Template package is missing: {template}")
    metadata = plan.get("template") if isinstance(plan.get("template"), dict) else {}
    sheet_name = str(metadata.get("sheet") or "Template")
    try:
        data_start_row = int(metadata["data_start_row"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TemplatePackageError("Template plan requires a detected data_start_row") from exc
    if not 7 <= data_start_row <= 100:
        raise TemplatePackageError(f"Template data_start_row is outside the supported range: {data_start_row}")
    sheet_path = worksheet_xml_path(template, sheet_name)
    with zipfile.ZipFile(template) as workbook_zip:
        original_xml = workbook_zip.read(sheet_path)
        fields = _worksheet_fields_from_xml(original_xml, _shared_strings(workbook_zip), header_row=5)
        rows = list(plan.get("rows") or [])
        rewritten = _worksheet_xml_with_plan_values(
            original_xml, fields=fields, rows=rows, data_start_row=data_start_row,
            value_transform=value_transform or (lambda _field, value: value),
        )
    temporary = output.with_name(f".{output.name}.{os.getpid()}.xml.tmp")
    try:
        if not _copy_zip_replacing_entry_raw(template, temporary, sheet_path, rewritten):
            raise TemplatePackageError(f"Could not replace worksheet XML for {sheet_name} in {template}")
        validate_package_integrity(
            original_package=template, generated_package=temporary, sheet_name=sheet_name,
            mutable_cells=mapped_output_cells(fields, rows, data_start_row),
        )
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass
    return output


def worksheet_xml_path(package: Path, sheet_name: str) -> str:
    rel_id_attr = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    with zipfile.ZipFile(package) as workbook_zip:
        workbook = ET.fromstring(workbook_zip.read("xl/workbook.xml"))
        namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        relation_id = next(
            (
                sheet.attrib.get(rel_id_attr, "")
                for sheet in workbook.findall("m:sheets/m:sheet", namespace)
                if sheet.attrib.get("name") == sheet_name
            ),
            "",
        )
        if not relation_id:
            raise TemplatePackageError(f"Worksheet not found in package: {sheet_name}")
        relationships = ET.fromstring(workbook_zip.read("xl/_rels/workbook.xml.rels"))
        for relation in relationships:
            if relation.attrib.get("Id") != relation_id:
                continue
            target = relation.attrib.get("Target", "")
            if not target:
                break
            path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
            return path.replace("\\", "/")
    raise TemplatePackageError(f"Worksheet relationship not found for {sheet_name} in {package}")


def mapped_output_cells(fields: dict[str, int], rows: list[Any], data_start_row: int) -> set[str]:
    cells = {
        f"{_column_letters(fields[str(field)])}{data_start_row + offset}"
        for offset, row in enumerate(rows)
        if isinstance(row, dict) and isinstance(row.get("field_values"), dict)
        for field in row["field_values"]
        if str(field) in fields
    }
    if data_start_row > 7:
        cells.update(f"{_column_letters(col)}{data_start_row - 1}" for col in fields.values())
    return cells


def validate_package_integrity(
    *,
    original_package: Path,
    generated_package: Path,
    sheet_name: str,
    mutable_cells: set[str],
) -> None:
    original_sheet = worksheet_xml_path(original_package, sheet_name)
    generated_sheet = worksheet_xml_path(generated_package, sheet_name)
    with zipfile.ZipFile(original_package) as original_zip, zipfile.ZipFile(generated_package) as generated_zip:
        original_infos = {item.filename: item for item in original_zip.infolist()}
        generated_infos = {item.filename: item for item in generated_zip.infolist()}
        missing = sorted(set(original_infos) - set(generated_infos))
        extra = sorted(set(generated_infos) - set(original_infos))
        if missing or extra:
            raise TemplatePackageError(
                "Generated template package does not preserve Amazon template entries; "
                f"missing={missing[:10]} extra={extra[:10]}"
            )
        if original_sheet != generated_sheet:
            raise TemplatePackageError(f"Generated template worksheet path drifted: {original_sheet} -> {generated_sheet}")
        changed = [
            name
            for name in sorted(original_infos)
            if name != original_sheet
            and (
                original_infos[name].CRC != generated_infos[name].CRC
                or original_infos[name].file_size != generated_infos[name].file_size
                or original_infos[name].compress_size != generated_infos[name].compress_size
            )
        ]
        if changed:
            raise TemplatePackageError(f"Generated template package changed non-data workbook parts; changed={changed[:10]}")
        original_xml = original_zip.read(original_sheet)
        generated_xml = generated_zip.read(generated_sheet)
        if _non_data_signature(original_xml) != _non_data_signature(generated_xml):
            raise TemplatePackageError(f"Generated template changed worksheet structure outside sheetData/dimension: {sheet_name}")
        original_cells = _immutable_cells(original_xml, mutable_cells)
        generated_cells = _immutable_cells(generated_xml, mutable_cells)
        if original_cells != generated_cells:
            changed_cells = sorted(set(original_cells) ^ set(generated_cells))
            changed_cells.extend(
                ref
                for ref in original_cells.keys() & generated_cells.keys()
                if original_cells[ref] != generated_cells[ref]
            )
            raise TemplatePackageError(
                f"Generated template changed cells outside mapped output fields: {sorted(set(changed_cells))[:10]}"
            )


def _non_data_signature(xml: bytes) -> bytes:
    root = ET.fromstring(xml)
    for child in list(root):
        if child.tag.rsplit("}", 1)[-1] in {"sheetData", "dimension"}:
            root.remove(child)
    return ET.tostring(root, encoding="utf-8")


def _immutable_cells(xml: bytes, mutable_cells: set[str]) -> dict[str, tuple[Any, ...]]:
    root = ET.fromstring(xml)
    return {
        ref: _element_signature(node)
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "c"
        and (ref := str(node.attrib.get("r") or ""))
        and ref not in mutable_cells
    }


def _element_signature(node: ET.Element) -> tuple[Any, ...]:
    return (
        node.tag,
        tuple(sorted(node.attrib.items())),
        node.text or "",
        tuple(_element_signature(child) for child in list(node)),
    )


def _column_letters(col: int) -> str:
    letters = ""
    value = int(col)
    while value:
        value, remainder = divmod(value - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _copy_zip_replacing_entry_raw(source: Path, output: Path, replace_name: str, replacement: bytes) -> bool:
    replaced = False
    with zipfile.ZipFile(source) as source_zip, source.open("rb") as source_file, output.open("wb") as output_file:
        central_records: list[bytes] = []
        infos = source_zip.infolist()
        local_ends = [
            infos[index + 1].header_offset if index + 1 < len(infos) else source_zip.start_dir
            for index in range(len(infos))
        ]
        for info, local_end in zip(infos, local_ends):
            local_offset = output_file.tell()
            if info.filename == replace_name:
                replaced = True
                local, central = _zip_replacement_records(info, replacement, local_offset)
                output_file.write(local)
                central_records.append(central)
            else:
                output_file.write(_zip_raw_local_record(source_file, info, local_end))
                central_records.append(_zip_central_directory_record(info, local_offset))
        central_offset = output_file.tell()
        for record in central_records:
            output_file.write(record)
        central_size = output_file.tell() - central_offset
        comment = source_zip.comment or b""
        if len(infos) > 0xFFFF or central_size > 0xFFFFFFFF or central_offset > 0xFFFFFFFF:
            raise TemplatePackageError("Zip64 Amazon templates are not supported")
        output_file.write(_ZIP_END_CENTRAL_DIRECTORY.pack(
            0x06054B50, 0, 0, len(infos), len(infos), central_size, central_offset, len(comment)
        ))
        output_file.write(comment)
    return replaced


def _zip_raw_local_record(source_file: Any, info: zipfile.ZipInfo, local_end: int) -> bytes:
    source_file.seek(info.header_offset)
    length = int(local_end) - int(info.header_offset)
    if length <= 0:
        raise TemplatePackageError(f"Invalid raw zip entry bounds for {info.filename}")
    record = source_file.read(length)
    signature = struct.unpack("<I", record[:4])[0] if len(record) >= 4 else 0
    if len(record) != length or signature != 0x04034B50:
        raise TemplatePackageError(f"Invalid local zip record for {info.filename}")
    return record


def _zip_replacement_records(info: zipfile.ZipInfo, data: bytes, local_offset: int) -> tuple[bytes, bytes]:
    compressed = _zip_compress(data, info.compress_type)
    crc = zlib.crc32(data) & 0xFFFFFFFF
    if max(len(data), len(compressed), local_offset) > 0xFFFFFFFF:
        raise TemplatePackageError("Zip64 worksheet replacements are not supported")
    flags = info.flag_bits & ~0x0008
    name, extra, comment = _zip_name_bytes(info), info.extra or b"", info.comment or b""
    dostime, dosdate = _zip_dos_time_date(info)
    local = _ZIP_LOCAL_FILE_HEADER.pack(
        0x04034B50, info.extract_version, flags, info.compress_type, dostime, dosdate,
        crc, len(compressed), len(data), len(name), len(extra),
    ) + name + extra + compressed
    central = _ZIP_CENTRAL_DIRECTORY_HEADER.pack(
        0x02014B50, info.create_version, info.extract_version, flags, info.compress_type,
        dostime, dosdate, crc, len(compressed), len(data), len(name), len(extra), len(comment),
        0, info.internal_attr, info.external_attr, local_offset,
    ) + name + extra + comment
    return local, central


def _zip_central_directory_record(info: zipfile.ZipInfo, local_offset: int) -> bytes:
    if local_offset > 0xFFFFFFFF:
        raise TemplatePackageError("Zip64 Amazon templates are not supported")
    name, extra, comment = _zip_name_bytes(info), info.extra or b"", info.comment or b""
    dostime, dosdate = _zip_dos_time_date(info)
    return _ZIP_CENTRAL_DIRECTORY_HEADER.pack(
        0x02014B50, info.create_version, info.extract_version, info.flag_bits, info.compress_type,
        dostime, dosdate, info.CRC, info.compress_size, info.file_size, len(name), len(extra),
        len(comment), 0, info.internal_attr, info.external_attr, local_offset,
    ) + name + extra + comment


def _zip_compress(data: bytes, compress_type: int) -> bytes:
    if compress_type == zipfile.ZIP_STORED:
        return data
    if compress_type != zipfile.ZIP_DEFLATED:
        raise TemplatePackageError(f"Unsupported Amazon template compression type: {compress_type}")
    compressor = zlib.compressobj(level=6, method=zlib.DEFLATED, wbits=-15)
    return compressor.compress(data) + compressor.flush()


def _zip_name_bytes(info: zipfile.ZipInfo) -> bytes:
    return info.filename.encode("utf-8" if info.flag_bits & 0x0800 else "cp437")


def _zip_dos_time_date(info: zipfile.ZipInfo) -> tuple[int, int]:
    year, month, day, hour, minute, second = info.date_time
    year = max(1980, min(2107, int(year)))
    return (int(hour) << 11) | (int(minute) << 5) | (int(second) // 2), ((year - 1980) << 9) | (int(month) << 5) | int(day)


def _shared_strings(workbook_zip: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook_zip.namelist():
        return []
    root = ET.fromstring(workbook_zip.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.iter() if node.tag.rsplit("}", 1)[-1] == "t") for item in list(root)]


def _worksheet_fields_from_xml(xml: bytes, shared_strings: list[str], *, header_row: int) -> dict[str, int]:
    root = ET.fromstring(xml)
    sheet_data = root.find("m:sheetData", {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"})
    if sheet_data is None:
        return {}
    fields: dict[str, int] = {}
    for row in list(sheet_data):
        if _xml_row_index(row) != header_row:
            continue
        for cell in list(row):
            _row, col = _cell_ref_to_row_col(_cell_ref(cell))
            value = _cell_xml_text(cell, shared_strings)
            if col and value:
                fields[value] = col
        break
    return fields


def _cell_xml_text(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = str(cell.attrib.get("t") or "")
    if cell_type == "s":
        node = next((child for child in list(cell) if child.tag.rsplit("}", 1)[-1] == "v"), None)
        try:
            index = int(node.text or "") if node is not None else -1
        except ValueError:
            index = -1
        return shared_strings[index] if 0 <= index < len(shared_strings) else ""
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter() if node.tag.rsplit("}", 1)[-1] == "t")
    node = next((child for child in list(cell) if child.tag.rsplit("}", 1)[-1] == "v"), None)
    return str(node.text or "") if node is not None else ""


def _worksheet_xml_with_plan_values(
    original_xml: bytes, *, fields: dict[str, int], rows: list[Any], data_start_row: int,
    value_transform: Callable[[str, Any], Any],
) -> bytes:
    _register_worksheet_namespaces()
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    root = ET.fromstring(original_xml)
    sheet_data = root.find("m:sheetData", ns)
    if sheet_data is None:
        raise TemplatePackageError("Template worksheet has no sheetData")
    original_rows = {_xml_row_index(row): row for row in list(sheet_data)}
    max_original_row = max(original_rows) if original_rows else 1
    generated_end_row = data_start_row + max(len(rows), 1) - 1
    styles = _template_style_by_column(sheet_data, data_start_row)
    if data_start_row > 7:
        _clear_mapped_cells(original_rows.get(data_start_row - 1), fields)
    for row_index in range(data_start_row, generated_end_row + 1):
        row = original_rows.get(row_index)
        if row is None:
            row = _new_row(row_index)
            _insert_row_sorted(sheet_data, row)
            original_rows[row_index] = row
        existing_cells = {_cell_ref(cell): cell for cell in list(row)}
        payload = rows[row_index - data_start_row] if row_index - data_start_row < len(rows) else {}
        values = payload.get("field_values", {}) if isinstance(payload, dict) else {}
        for field, raw_value in values.items() if isinstance(values, dict) else []:
            col = fields.get(str(field))
            if not col:
                continue
            value = value_transform(str(field), raw_value)
            ref = f"{_column_letters(col)}{row_index}"
            cell = existing_cells.get(ref)
            if value in (None, ""):
                if cell is not None:
                    for child in list(cell):
                        cell.remove(child)
                    cell.attrib.pop("t", None)
                continue
            if cell is None:
                cell = _new_cell(ref, styles.get(col))
                _insert_cell_sorted(row, cell)
            _set_cell_xml_value(cell, value)
    dimension = root.find("m:dimension", ns)
    if dimension is not None and fields:
        dimension.attrib["ref"] = f"A1:{_column_letters(max(fields.values()))}{max(max_original_row, generated_end_row, 5)}"
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return _ensure_worksheet_ignorable_namespaces(xml)


def _clear_mapped_cells(row: ET.Element | None, fields: dict[str, int]) -> None:
    if row is None:
        return
    mapped_refs = {f"{_column_letters(col)}{_xml_row_index(row)}" for col in fields.values()}
    for cell in list(row):
        if _cell_ref(cell) not in mapped_refs:
            continue
        for child in list(cell):
            cell.remove(child)
        cell.attrib.pop("t", None)


def _set_cell_xml_value(cell: ET.Element, value: Any) -> None:
    for child in list(cell):
        cell.remove(child)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        cell.attrib.pop("t", None)
        node = ET.Element("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
        node.text = str(value)
        cell.append(node)
        return
    cell.attrib["t"] = "inlineStr"
    inline = ET.Element("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}is")
    node = ET.Element("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
    text = str(value)
    if text != text.strip():
        node.attrib["{http://www.w3.org/XML/1998/namespace}space"] = "preserve"
    node.text = text
    inline.append(node)
    cell.append(inline)


def _register_worksheet_namespaces() -> None:
    namespaces = {
        "": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
        "x14": "http://schemas.microsoft.com/office/spreadsheetml/2009/9/main",
        "x14ac": "http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac",
        "xr": "http://schemas.microsoft.com/office/spreadsheetml/2014/revision",
        "xr2": "http://schemas.microsoft.com/office/spreadsheetml/2015/revision2",
        "xr3": "http://schemas.microsoft.com/office/spreadsheetml/2016/revision3",
        "xm": "http://schemas.microsoft.com/office/excel/2006/main",
        "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    }
    for prefix, uri in namespaces.items():
        ET.register_namespace(prefix, uri)


_WORKSHEET_NAMESPACE_URIS = {
    "x14ac": "http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac",
    "xr": "http://schemas.microsoft.com/office/spreadsheetml/2014/revision",
    "xr2": "http://schemas.microsoft.com/office/spreadsheetml/2015/revision2",
    "xr3": "http://schemas.microsoft.com/office/spreadsheetml/2016/revision3",
}


def _ensure_worksheet_ignorable_namespaces(xml: bytes) -> bytes:
    text = xml.decode("utf-8")
    match = re.search(r"<worksheet\b[^>]*>", text)
    if not match:
        return xml
    root_tag = match.group(0)
    ignorable = re.search(r'\bmc:Ignorable="([^"]+)"', root_tag)
    if not ignorable:
        return xml
    additions = [
        f' xmlns:{prefix}="{_WORKSHEET_NAMESPACE_URIS[prefix]}"'
        for prefix in ignorable.group(1).split()
        if prefix in _WORKSHEET_NAMESPACE_URIS and f"xmlns:{prefix}=" not in root_tag
    ]
    if not additions:
        return xml
    patched = root_tag[:-1] + "".join(additions) + ">"
    return (text[:match.start()] + patched + text[match.end():]).encode("utf-8")


def _xml_row_index(row: ET.Element) -> int:
    try:
        return int(str(row.attrib.get("r") or "0"))
    except ValueError:
        return 0


def _cell_ref(cell: ET.Element) -> str:
    return str(cell.attrib.get("r") or "")


def _cell_ref_to_row_col(ref: str) -> tuple[int, int]:
    match = re.match(r"^([A-Z]+)([0-9]+)$", str(ref or ""))
    if not match:
        return 0, 0
    col = 0
    for char in match.group(1):
        col = col * 26 + ord(char) - ord("A") + 1
    return int(match.group(2)), col


def _template_style_by_column(sheet_data: ET.Element, data_start_row: int) -> dict[int, dict[str, str]]:
    styles: dict[int, dict[str, str]] = {}
    rows = {_xml_row_index(row): row for row in list(sheet_data)}
    for row_index in (data_start_row, data_start_row + 1, data_start_row - 1):
        row = rows.get(row_index)
        if row is None:
            continue
        for cell in list(row):
            _row, col = _cell_ref_to_row_col(_cell_ref(cell))
            if col and col not in styles:
                kept = {key: value for key, value in cell.attrib.items() if key in {"s", "cm", "vm", "ph"}}
                if kept:
                    styles[col] = kept
    return styles


def _new_row(row_index: int) -> ET.Element:
    return ET.Element("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row", {"r": str(row_index)})


def _new_cell(ref: str, style: dict[str, str] | None) -> ET.Element:
    return ET.Element("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c", {"r": ref, **(style or {})})


def _insert_row_sorted(sheet_data: ET.Element, row: ET.Element) -> None:
    index = _xml_row_index(row)
    for position, existing in enumerate(list(sheet_data)):
        if _xml_row_index(existing) > index:
            sheet_data.insert(position, row)
            return
    sheet_data.append(row)


def _insert_cell_sorted(row: ET.Element, cell: ET.Element) -> None:
    _row, col = _cell_ref_to_row_col(_cell_ref(cell))
    for position, existing in enumerate(list(row)):
        _existing_row, existing_col = _cell_ref_to_row_col(_cell_ref(existing))
        if existing_col > col:
            row.insert(position, cell)
            return
    row.append(cell)
