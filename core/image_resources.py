"""Host reservations for the existing image executor, shared across processes."""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

import psutil

from .image_provider_common import ProviderQueueUnavailable, _system_memory_bytes
from .image_response import response_binding, response_directory
from .io import read_json, write_json
from .process_lock import process_file_lock

_LOCK = threading.RLock()
_LEDGER = Path(__file__).resolve().parents[1] / 'runtime/image_reservations.json'
_GIB = 1024**3


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


def reserve_image(task: dict[str, Any], *, local: bool = False) -> None:
    key = response_binding(task)
    with _LOCK, process_file_lock(_LEDGER.with_suffix('.lock')):
        rows = read_json(_LEDGER) if _LEDGER.exists() else {}
        for identity, row in list(rows.items()):
            if not _process(row):
                # Orphaned paid bytes stay accounted for, without retaining dead RAM promises.
                files = list(Path(row['directory']).glob('*.bin'))
                if files:
                    row.update(peak=0, disk=sum(path.stat().st_size for path in files), pid=0)
                else:
                    rows.pop(identity)
        current = rows.get(key)
        if current and _process(current) and not (local and current['pid'] == os.getpid()):
            raise ProviderQueueUnavailable('host_image_memory', 'This image request is already in flight')
        total, available = _system_memory_bytes()
        floor = max(4 * _GIB, int(total * .2))
        input_bytes = sum(Path(row['path']).stat().st_size for row in task.get('generation_references', [])
                          if Path(row['path']).is_file())
        peak = max(1536 * 1024**2, input_bytes * 12)
        per_process = {}
        for identity, row in rows.items():
            if identity == key or not row['peak']:
                continue
            process = _process(row)
            if process:
                group = per_process.setdefault(row['pid'], {'peak': 0, 'baseline': row['rss'], 'rss': _rss(process)})
                group['peak'] += row['peak']
                group['baseline'] = min(group['baseline'], row['rss'])
        promised = sum(max(0, row['peak'] - max(0, row['rss'] - row['baseline'])) for row in per_process.values())
        headroom = 0 if local else 1536 * 1024**2
        if available - promised - floor - headroom < peak:
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
            files = list(response_directory(task).glob('*.bin'))
            if files:
                rows[key]['peak'] = 0
                rows[key]['disk'] = sum(path.stat().st_size for path in files)
                if not buffered:
                    rows[key]['pid'] = 0
            else:
                rows.pop(key)
            write_json(_LEDGER, rows)
