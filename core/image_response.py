"""Durable transport receipts, not candidate or job authority."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import uuid

from .io import file_sha256, read_json, write_bytes_atomic, write_json
from .paths import resolve_job_owned_path
from .status import input_revision_id
from .image_provider_common import CandidateCommitError, ProviderTransportError

RESPONSE_SCHEMA = 'image-response-v1'


def response_binding(task: dict[str, Any]) -> str:
    return input_revision_id({key: task.get(key) for key in (
        'logical_task_id', 'task_fingerprint', 'candidate_revision', 'prompt', 'generation_references')})


def response_directory(task: dict[str, Any]) -> Path:
    return resolve_job_owned_path(task['job_dir'], 'reports/image_responses/' + response_binding(task))


def new_response_path(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return directory / (uuid.uuid4().hex + '.json')


def save_response(path: Path, data: bytes, audit: dict[str, Any]) -> None:
    record = read_json(path)
    raw = path.with_suffix('.bin')
    write_bytes_atomic(raw, data)
    write_json(path, {**record, 'status': 'received', 'raw_sha256': file_sha256(raw),
                     'raw_bytes': raw.stat().st_size, 'request_audit': audit})


def save_transport_response(path: Path, phase: str, data: bytes, audit: dict[str, Any]) -> None:
    record = read_json(path)
    if phase in {'body', 'partial'}:
        raw = path.with_suffix('.http' if phase == 'body' else '.partial')
        write_bytes_atomic(raw, data)
        record.update({phase + '_sha256': file_sha256(raw), phase + '_bytes': len(data)})
    write_json(path, {**record, 'request_audit': dict(audit)})


def recover_response(task: dict[str, Any]) -> dict[str, Any]:
    directory = response_directory(task)
    received = []
    unknown = []
    for path in sorted(directory.glob('*.json')):
        try:
            record = read_json(path)
            if record['schema'] != RESPONSE_SCHEMA or record['binding'] != response_binding(task):
                raise ValueError('Response binding mismatch')
            if record['status'] == 'submitted' and record.get('body_sha256'):
                envelope = path.with_suffix('.http')
                if not envelope.is_file() or file_sha256(envelope) != record['body_sha256']:
                    raise ValueError('Saved HTTP response missing or changed')
                received.append({**record, 'receipt_path': str(path), 'raw_path': str(envelope)})
            elif record['status'] == 'received':
                raw = path.with_suffix('.bin')
                if not raw.is_file() or file_sha256(raw) != record['raw_sha256']:
                    raise ValueError('Saved paid response missing or changed')
                received.append({**record, 'receipt_path': str(path), 'raw_path': str(raw)})
            elif record['status'] == 'submitted':
                unknown.append(record)
        except (KeyError, OSError, ValueError) as exc:
            raise CandidateCommitError(f'Paid response requires local reconciliation: {path}: {exc}') from exc
    if unknown:
        raise ProviderTransportError(unknown[0]['provider'], 'Submitted response has no durable outcome; do not resubmit', ambiguous=True)
    if len(received) > 1:
        raise CandidateCommitError('Multiple paid responses require explicit selection')
    return received[0] if received else {}


def materialize_response(path: Path) -> Path:
    """Decode/download a saved response only under the existing local resource lease."""
    record = read_json(path)
    if record['status'] == 'submitted' and record.get('body_sha256'):
        from .image_provider_transport import _decode_image_response
        try:
            save_response(path, _decode_image_response(path.with_suffix('.http').read_text(encoding='utf-8')), record['request_audit'])
        except Exception as exc:
            raise CandidateCommitError(f'Saved response decode/download needs local recovery: {type(exc).__name__}: {exc}') from exc
    return path.with_suffix('.bin')


def finish_response(path: Path, status: str) -> None:
    record = read_json(path)
    write_json(path, {**record, 'status': status})
    if status in {'finalized', 'rejected_content'}:
        path.with_suffix('.bin').unlink(missing_ok=True)
        path.with_suffix('.http').unlink(missing_ok=True)
        path.with_suffix('.partial').unlink(missing_ok=True)
