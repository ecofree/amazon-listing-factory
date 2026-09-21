"""Durable transport receipts, not candidate or job authority."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import uuid
from datetime import datetime, timezone

from .process_lock import process_file_lock

from .io import file_sha256, read_json, write_bytes_atomic, write_json
from .paths import resolve_job_owned_path
from .status import input_revision_id
from .image_provider_common import CandidateCommitError, ProviderTransportError
from .provider_policy import load_provider_policy

RESPONSE_SCHEMA = 'image-response-v1'


def response_binding(task: dict[str, Any]) -> str:
    return input_revision_id({**{key: task.get(key) for key in (
        'logical_task_id', 'task_fingerprint', 'candidate_revision', 'prompt')},
        'attachments': [{key: row.get(key) for key in ('kind', 'source_id', 'sha256', 'protected_mask')}
                        for row in task.get('generation_references', [])]})


def response_directory(task: dict[str, Any]) -> Path:
    return resolve_job_owned_path(task['job_dir'], 'reports/image_responses/' + response_binding(task))


def _pending_responses(directory: Path, logical_id: str) -> list[tuple[Path, dict[str, Any]]]:
    records = []
    for path in sorted(directory.parent.glob('*/*.json')):
        try:
            row = read_json(path)
        except (OSError, ValueError) as exc:
            if path.parent == directory:
                raise CandidateCommitError(f'Response receipt cannot be read: {path}: {exc}') from exc
            continue
        if path.parent == directory or (logical_id and row.get('request_audit', {}).get('logical_task_id') == logical_id):
            if row.get('schema') != RESPONSE_SCHEMA or row.get('binding') != path.parent.name:
                raise CandidateCommitError(f'Response receipt identity is invalid: {path}')
            records.append((path, row))
    return records


def _check_pending_responses(directory: Path, records: list[tuple[Path, dict[str, Any]]], provider: str) -> None:
    for path, row in records:
        if row['status'] == 'received' or (row['status'] == 'submitted' and row.get('body_sha256')):
            raise CandidateCommitError(f'Saved response must be recovered under its original binding: {path}')
        if row['status'] == 'submitted' or (path.parent != directory and row['status'] == 'resend_authorized'):
            raise ProviderTransportError(provider or row['provider'],
                f'Unresolved request or original-binding resend requires reconciliation before another request: {path}', ambiguous=True)


def begin_response(directory: Path, *, provider: str, audit: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    with process_file_lock(directory.parent / '.receipt.lock'):
        records = _pending_responses(directory, str(audit.get('logical_task_id') or ''))
        _check_pending_responses(directory, records, provider)
        authorized = [(path, row) for path, row in records if path.parent == directory and row['status'] == 'resend_authorized']
        path = directory / (uuid.uuid4().hex + '.json')
        write_json(path, {'schema': RESPONSE_SCHEMA, 'binding': audit['response_binding'], 'provider': provider,
                         'status': 'prepared', 'request_audit': dict(audit)})
        for previous_path, previous in authorized:
            write_json(previous_path, {**previous, 'status': 'superseded', 'replacement_receipt': path.name})
        return path


def submit_response(path: Path, audit: dict[str, Any]) -> None:
    """Recheck at transport submission; abandoned local preparation is not a paid request."""
    with process_file_lock(path.parent.parent / '.receipt.lock'):
        row = read_json(path)
        records = _pending_responses(path.parent, str(audit.get('logical_task_id') or ''))
        _check_pending_responses(path.parent, [(p, r) for p, r in records if p != path], row['provider'])
        write_json(path, {**row, 'status': 'submitted', 'request_audit': dict(audit)})


def resolve_response(job: Path, receipt: str, *, action: str, reason: str) -> dict[str, Any]:
    """Explicit operator disposition, not an automatic retry or a new controller."""
    path = resolve_job_owned_path(job, receipt)
    root = (job / 'reports' / 'image_responses').resolve()
    if path.suffix != '.json' or path.parent.parent != root:
        raise ValueError('Response receipt must belong to this job image_responses directory')
    if action not in {'confirmed_not_generated', 'approve_one_resend'} or not reason.strip():
        raise ValueError('Receipt resolution requires an explicit action and evidence/reason')
    with process_file_lock(root / '.receipt.lock'):
        row = read_json(path)
        if row.get('schema') != RESPONSE_SCHEMA or row.get('binding') != path.parent.name:
            raise ValueError('Response receipt identity is invalid')
        if row.get('status') != 'submitted' or row.get('body_sha256'):
            raise ValueError('Only an unresolved submitted receipt can be resolved; saved responses must be recovered locally')
        records = [read_json(p) for p in path.parent.glob('*.json')]
        if any(r.get('status') == 'received' or (r.get('status') == 'submitted' and r.get('body_sha256')) for r in records):
            raise ValueError('A saved result exists; recover it without paying for a replacement')
        limit = max(1, unknown_result_resend_limit())
        if action == 'approve_one_resend' and sum(r.get('resolution', {}).get('action') == action for r in records) >= limit:
            raise ValueError(f'Unknown-result replacement limit ({limit}) reached for this task/prompt binding')
        row.update(status='resend_authorized' if action == 'approve_one_resend' else 'known_failure',
                   resolution={'action': action, 'reason': reason.strip(),
                               'recorded_at': datetime.now(timezone.utc).isoformat(),
                               'duplicate_charge_risk_accepted': action == 'approve_one_resend'})
        write_json(path, row)
    return {'receipt': str(path), 'status': row['status'], 'resolution': row['resolution'], 'requests_sent': 0}


def unknown_result_resend_limit() -> int:
    policy = load_provider_policy().get('image_generation', {})
    return min(3, max(0, int(policy.get('unknown_result_resends') or 0))) if policy.get('unknown_result_resend_authorization') else 0


def authorize_unknown_resend(task: dict[str, Any]) -> bool:
    """Apply the user's standing authorization to the original binding only."""
    directory = response_directory(task)
    records = _pending_responses(directory, str(task.get('logical_task_id') or ''))
    if any(row['status'] == 'received' or (row['status'] == 'submitted' and row.get('body_sha256')) for _, row in records):
        return False
    pending = [(path, row) for path, row in records if row['status'] in {'submitted', 'resend_authorized'}]
    if len(pending) != 1 or pending[0][0].parent != directory:
        return False
    path, row = pending[0]
    if row['status'] == 'resend_authorized':
        return True
    limit = unknown_result_resend_limit()
    used = sum(r.get('resolution', {}).get('action') == 'approve_one_resend' for p, r in records if p.parent == directory)
    if used >= limit:
        return False
    reason = load_provider_policy()['image_generation']['unknown_result_resend_authorization']
    resolve_response(Path(task['job_dir']), str(path), action='approve_one_resend', reason=reason)
    return True


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
    for path in sorted(directory.glob('*.json')):
        try:
            record = read_json(path)
            if record['schema'] != RESPONSE_SCHEMA or record['binding'] != response_binding(task):
                raise ValueError('Response binding mismatch')
            if record['status'] not in {'prepared', 'submitted', 'received', 'known_failure',
                                        'finalized', 'rejected_content', 'resend_authorized', 'superseded'}:
                raise ValueError('Unknown response disposition')
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
        except (KeyError, OSError, ValueError) as exc:
            raise CandidateCommitError(f'Paid response requires local reconciliation: {path}: {exc}') from exc
    if len(received) > 1:
        raise CandidateCommitError('Multiple paid responses require explicit selection')
    if received:
        return received[0]
    _check_pending_responses(directory, _pending_responses(directory, str(task.get('logical_task_id') or '')), '')
    return {}


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
