"""Host reservations for the existing image executor, shared across processes."""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

import psutil
from PIL import Image

from .image_provider_common import ProviderQueueUnavailable, _system_memory_bytes
from .image_response import response_binding, response_directory
from .io import read_json, write_json
from .process_lock import process_file_lock

_LOCK = threading.RLock()
_LEDGER = Path(__file__).resolve().parents[1] / 'runtime/image_reservations.json'
_GIB = 1024**3
_MIN_PEAK = 1536 * 1024**2


def _process(row):
    try:
        process = psutil.Process(row['pid'])
        return process if process.create_time() == row['process_start'] else None
    except (psutil.Error, KeyError):
        return None


def _rss(process):
    total = process.memory_info().rss
    for child in process.children(recursive=True):
        try:
            total += child.memory_info().rss
        except psutil.Error:
            pass
    return total


def _saved_response_bytes(directory: Path) -> int:
    size = 0
    for path in directory.iterdir() if directory.is_dir() else []:
        if path.suffix in {'.bin', '.http', '.partial'}:
            try:
                size += path.stat().st_size
            except FileNotFoundError:
                pass  # Finalization may remove a drained response during this snapshot.
    return size


def _reservations() -> dict[str, Any]:
    rows = read_json(_LEDGER) if _LEDGER.exists() else {}
    for identity, row in list(rows.items()):
        if not _process(row):
            disk = _saved_response_bytes(Path(row['directory']))
            if disk:
                row.update(peak=0, disk=disk, pid=0)
            else:
                rows.pop(identity)
    return rows


def _input_bytes(task: dict[str, Any]) -> int:
    root = Path(task.get('job_dir') or '.')
    paths = {root / str(row['path']) for row in task.get('generation_references', [])}
    return sum(path.stat().st_size for path in paths if path.is_file())


def _estimated_peak(task: dict[str, Any]) -> int:
    decoded = 0
    root = Path(task.get('job_dir') or '.')
    for path in {root / str(row['path']) for row in task.get('generation_references', [])}:
        try:
            with Image.open(path) as image:
                decoded += image.width * image.height * 4
        except OSError:
            continue  # Image validity belongs to the existing reference check, not admission.
    return max(_MIN_PEAK, _input_bytes(task) * 12, decoded * 3 + 512 * 1024**2)


def _memory_budget(rows: dict[str, Any], *, exclude: str = '', local: bool = False) -> tuple[int, int]:
    total, available = _system_memory_bytes()
    per_process: dict[int, dict[str, int]] = {}
    for identity, row in rows.items():
        if identity == exclude or not row['peak']:
            continue
        process = _process(row)
        if process:
            try:
                rss = _rss(process)
            except psutil.Error:
                continue
            group = per_process.setdefault(row['pid'], {'peak': 0, 'baseline': row['rss'], 'rss': rss})
            group['peak'] += row['peak']
            group['baseline'] = min(group['baseline'], row['rss'])
    promised = sum(max(0, row['peak'] - max(0, row['rss'] - row['baseline'])) for row in per_process.values())
    floor = max(4 * _GIB, int(total * .2))
    return total, max(0, available - promised - floor - (0 if local else _MIN_PEAK))


def image_memory_capacity(tasks: list[dict[str, Any]]) -> int:
    """Estimate lanes with exactly the budget used by atomic admission."""
    with _LOCK, process_file_lock(_LEDGER.with_suffix('.lock')):
        rows = _reservations()
        total, usable = _memory_budget(rows)
        keys = {response_binding(task) for task in tasks if task.get('job_dir')}
        own = sum(identity in keys and row['peak'] > 0 and row['pid'] == os.getpid() for identity, row in rows.items())
        peak = max([_MIN_PEAK, *(_estimated_peak(task) for task in tasks)])
        return max(0, min(8, total // (8 * _GIB), own + usable // peak))


def reserve_image(task: dict[str, Any], *, local: bool = False) -> None:
    key = response_binding(task)
    with _LOCK, process_file_lock(_LEDGER.with_suffix('.lock')):
        rows = _reservations()
        current = rows.get(key)
        if current and _process(current) and not (local and current['pid'] == os.getpid()):
            raise ProviderQueueUnavailable('host_image_memory', 'This image request is already in flight')
        total, usable = _memory_budget(rows, exclude=key, local=local)
        input_bytes = _input_bytes(task)
        peak = _estimated_peak(task)
        if usable < peak:
            raise ProviderQueueUnavailable('host_image_memory', 'Host memory reserved for in-flight work and finalization')
        directory = response_directory(task)
        directory.mkdir(parents=True, exist_ok=True)
        volume = directory.anchor.casefold()
        disk = max(512 * 1024**2, input_bytes * 4)
        disk_promised = sum(row['disk'] for identity, row in rows.items() if identity != key and row['volume'] == volume and row['peak'])
        if shutil.disk_usage(directory).free - disk_promised < disk + _GIB:
            raise ProviderQueueUnavailable('host_image_storage', 'Insufficient response-volume headroom')
        if local and shutil.disk_usage(tempfile.gettempdir()).free < _GIB:
            raise ProviderQueueUnavailable('host_image_storage', 'Insufficient upscale temporary-volume headroom')
        capacity = max(1, min(8, total // (8 * _GIB)))
        active_count = sum(_process(row) is not None for row in rows.values())
        if not local and key not in rows and active_count >= capacity:
            raise ProviderQueueUnavailable('host_image_storage', 'In-flight and saved responses occupy the bounded host backlog')
        process = psutil.Process()
        rows[key] = {'pid': process.pid, 'process_start': process.create_time(), 'rss': _rss(process),
                     'peak': peak, 'disk': disk, 'volume': volume, 'directory': str(directory)}
        write_json(_LEDGER, rows)


def release_image(task: dict[str, Any], *, buffered: bool = False) -> None:
    with _LOCK, process_file_lock(_LEDGER.with_suffix('.lock')):
        rows = read_json(_LEDGER) if _LEDGER.exists() else {}
        key = response_binding(task)
        if key in rows:
            disk = _saved_response_bytes(response_directory(task))
            if disk:
                rows[key]['peak'] = 0
                rows[key]['disk'] = disk
                if not buffered:
                    rows[key]['pid'] = 0
            else:
                rows.pop(key)
            write_json(_LEDGER, rows)
