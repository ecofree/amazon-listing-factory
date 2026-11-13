"""Host reservations for the existing image executor, shared across processes."""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

import psutil
from PIL import Image

from .image_provider_common import ProviderQueueUnavailable, _system_memory_bytes
from .image_response import RESPONSE_SCHEMA, response_directory
from .io import read_json, write_json
from .process_lock import process_file_lock
from .progress_trace import record_progress

_LOCK = threading.RLock()
_LEDGER = Path(__file__).resolve().parents[1] / 'runtime/image_reservations.json'
_GIB = 1024**3
_REMOTE_MIN_PEAK = 512 * 1024**2
_LOCAL_MIN_PEAK = 1536 * 1024**2


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


def _pending_response_bytes(directory: Path) -> int:
    """Measure unfinished receipt payloads; retained terminal originals are archives."""
    size = 0
    for path in directory.iterdir() if directory.is_dir() else []:
        if path.suffix in {'.bin', '.http', '.partial'}:
            try:
                if path.suffix == '.bin':
                    try:
                        receipt = read_json(path.with_suffix('.json'))
                    except (OSError, ValueError):
                        receipt = {}
                    if (isinstance(receipt, dict) and receipt.get('schema') == RESPONSE_SCHEMA
                            and receipt.get('binding') == directory.name
                            and receipt.get('status') in {'finalized', 'rejected_content'}):
                        continue
                size += path.stat().st_size
            except FileNotFoundError:
                pass  # Finalization may remove a drained response during this snapshot.
    return size


def _reservations() -> dict[str, Any]:
    rows = read_json(_LEDGER) if _LEDGER.exists() else {}
    for identity, row in list(rows.items()):
        if not _process(row):
            disk = _pending_response_bytes(Path(row['directory']))
            if disk:
                row.update(peak=0, disk=disk, pid=0)
            else:
                rows.pop(identity)
    return rows


def _input_bytes(task: dict[str, Any]) -> int:
    root = Path(task.get('job_dir') or '.')
    paths = {root / str(row['path']) for row in task.get('generation_references', [])}
    return sum(path.stat().st_size for path in paths if path.is_file())


def _estimated_peak(task: dict[str, Any], *, local: bool = False) -> int:
    decoded = 0
    root = Path(task.get('job_dir') or '.')
    for path in {root / str(row['path']) for row in task.get('generation_references', [])}:
        try:
            with Image.open(path) as image:
                decoded += image.width * image.height * 4
        except OSError:
            continue  # Image validity belongs to the existing reference check, not admission.
    if local:
        return max(_LOCAL_MIN_PEAK, _input_bytes(task) * 12, decoded * 3 + 512 * 1024**2)
    # Bounded HTTP envelopes/copies plus attachment decode/encoding; no local model here.
    mask_pixels = 0
    mask = (task.get("generation_references") or [{}])[0].get("protected_mask")
    if isinstance(mask, dict) and mask.get("path"):
        try:
            with Image.open(root / mask["path"]) as image:mask_pixels = image.width * image.height * 4
        except OSError:pass  # Reference validation still owns missing/invalid masks.
    return max(_REMOTE_MIN_PEAK, _input_bytes(task) * 6 + mask_pixels * 2,
               (decoded + mask_pixels) * 2 + 256 * 1024**2)


def _memory_budget(rows: dict[str, Any], *, exclude: str = '') -> dict[str, int]:
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
    return dict(total=total, available=available, promised=promised, floor=floor,
                usable=max(0, available - promised - floor))


def image_memory_capacity(tasks: list[dict[str, Any]]) -> int:
    """Estimate lanes with exactly the budget used by atomic admission."""
    with _LOCK, process_file_lock(_LEDGER.with_suffix('.lock')):
        rows = _reservations()
        budget = _memory_budget(rows)
        keys = {str(response_directory(task)).casefold() for task in tasks if task.get('job_dir')}
        own = sum(identity in keys and row['peak'] > 0 and row['pid'] == os.getpid() for identity, row in rows.items())
        peak = max([_REMOTE_MIN_PEAK, *(_estimated_peak(task) for task in tasks)])
        return max(0, min(8, budget['total'] // (8 * _GIB), own + budget['usable'] // peak))


def reserve_image(task: dict[str, Any], *, local: bool = False) -> str:
    key = str(response_directory(task)).casefold()
    with _LOCK, process_file_lock(_LEDGER.with_suffix('.lock')):
        rows = _reservations()
        current = rows.get(key)
        if current and current['peak'] and _process(current):
            raise ProviderQueueUnavailable('host_image_memory', 'This image request is already in flight')
        budget = _memory_budget(rows, exclude=key)
        input_bytes = _input_bytes(task)
        peak = _estimated_peak(task, local=local)
        if budget['usable'] < peak:
            raise ProviderQueueUnavailable('host_image_memory',
                'Host memory reserved: ' + ', '.join(f'{name}={value // 1024**2}MiB' for name, value in
                                                    {**budget, 'estimated_peak': peak}.items()))
        directory = response_directory(task)
        directory.mkdir(parents=True, exist_ok=True)
        volume = directory.anchor.casefold()
        disk = max(512 * 1024**2, input_bytes * 4)
        disk_promised = sum(row['disk'] for identity, row in rows.items() if identity != key and row['volume'] == volume and row['peak'])
        if shutil.disk_usage(directory).free - disk_promised < disk + _GIB:
            raise ProviderQueueUnavailable('host_image_storage', 'Insufficient response-volume headroom')
        if local and shutil.disk_usage(tempfile.gettempdir()).free < _GIB:
            raise ProviderQueueUnavailable('host_image_storage', 'Insufficient upscale temporary-volume headroom')
        capacity = max(1, min(8, budget['total'] // (8 * _GIB)))
        active_count = sum(_process(row) is not None for row in rows.values())
        if not local and key not in rows and active_count >= capacity:
            raise ProviderQueueUnavailable('host_image_storage', 'In-flight and saved responses occupy the bounded host backlog')
        process = psutil.Process()
        lease = uuid.uuid4().hex
        rows[key] = {'pid': process.pid, 'process_start': process.create_time(), 'rss': _rss(process),
                     'peak': peak, 'disk': disk, 'volume': volume, 'directory': str(directory), 'lease': lease}
        write_json(_LEDGER, rows)
        try:
            record_progress(task['job_dir'], 'image_memory_admitted', child=task.get('child'), role=task.get('role'),
                            phase='local_finalize' if local else 'remote', estimated_peak=peak, **budget)
        except OSError:
            pass  # Diagnostic output must not invalidate the acquired resource lease.
        return lease


def release_image(task: dict[str, Any], lease: str, *, buffered: bool = False) -> None:
    with _LOCK, process_file_lock(_LEDGER.with_suffix('.lock')):
        rows = read_json(_LEDGER) if _LEDGER.exists() else {}
        key = str(response_directory(task)).casefold()
        row = rows.get(key, {})
        if (lease and row.get('lease') == lease and row.get('pid') == os.getpid()
                and _process(row) and str(row.get('directory', '')).casefold() == key):
            disk = _pending_response_bytes(response_directory(task))
            if disk:
                rows[key]['peak'] = 0
                rows[key]['disk'] = disk
                if not buffered:
                    rows[key]['pid'] = 0
            else:
                rows.pop(key)
            write_json(_LEDGER, rows)
