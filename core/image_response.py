"""Durable transport receipts, not candidate or job authority."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import uuid
import json
from datetime import datetime, timezone, timedelta

from .process_lock import process_file_lock

from .io import file_sha256, read_json, write_bytes_atomic, write_json
from .paths import resolve_job_owned_path
from .status import input_revision_id
from .image_provider_common import CandidateCommitError, ProviderTransportError, ReceiptDispositionRequired
from .imagegen_artifacts import IMAGE_RESPONSE_MAX_BYTES, IMAGE_OUTPUT_MAX_BYTES
from .provider_policy import load_provider_policy
from .image_reference_context import reference_semantics

RESPONSE_SCHEMA = 'image-response-v1'


def response_binding(task: dict[str, Any]) -> str:
    return input_revision_id({**{key: task.get(key) for key in (
        'logical_task_id', 'task_fingerprint', 'candidate_revision', 'prompt')},
        'attachments': [{key: row.get(key) for key in ('kind', 'source_id', 'sha256', 'protected_mask')}
                        for row in task.get('generation_references', [])]})


def response_directory(task: dict[str, Any]) -> Path:
    return resolve_job_owned_path(task['job_dir'], 'reports/image_responses/' + response_binding(task))


def _pending_responses(directory: Path, logical_id: str, *, reconcile: bool = True) -> list[tuple[Path, dict[str, Any]]]:
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
            records.append((path, _reconcile_saved_bytes(path, row) if reconcile else row))
    # The submitted replacement is the single durable authority. A crash before
    # this record is written leaves the old authorization active.
    identities = {(path.parent.name, path.name): row for path, row in records}
    replaced = set()
    for path, row in records:
        if row['status'] == 'prepared':
            continue
        origin_binding = row.get('replaces_binding', path.parent.name)
        for name in row.get('replaces', []):
            origin = identities.get((origin_binding, name))
            if origin_binding != path.parent.name and (not origin or not logical_id
                    or origin.get('request_audit', {}).get('logical_task_id') != logical_id
                    or row.get('request_audit', {}).get('logical_task_id') != logical_id):
                raise CandidateCommitError(f'Cross-binding replacement identity is invalid: {path}')
            replaced.add((directory.parent / origin_binding, name))
    submitted = {(path.parent, path.name) for path, row in records
                 if row['status'] in {'submitted', 'received', 'finalized', 'rejected_content', 'output_rejected', 'resend_authorized'}
                 or (row['status'] == 'superseded' and row.get('resolution', {}).get('action') == 'approve_one_resend')
                 or (row['status'] == 'known_failure' and row.get('request_audit', {}).get('endpoint'))}
    replaced.update((path.parent, path.name) for path, row in records
                    if (path.parent, row.get('replacement_receipt')) in submitted)
    records = [(path, {**row, 'status': 'resend_authorized' if row.get('resolution', {}).get('action') == 'approve_one_resend'
                       else 'submitted'} if row['status'] == 'superseded' and (path.parent, path.name) not in replaced
                else row) for path, row in records]
    records = [(path, {**row, 'status': 'superseded'} if (path.parent, path.name) in replaced
                and row['status'] == 'resend_authorized' else row) for path, row in records]
    return records


def _reconcile_saved_bytes(path: Path, row: dict[str, Any]) -> dict[str, Any]:
    if row.get('schema') != RESPONSE_SCHEMA or row.get('binding') != path.parent.name:
        raise CandidateCommitError(f'Response receipt identity is invalid: {path}')
    if row['status'] not in {'submitted', 'received', 'resend_authorized', 'superseded'}:
        return row
    if (row.get('output_rejection') and row['status'] in {'resend_authorized', 'superseded'}
            and (row.get('resolution') or {}).get('action') == 'approve_one_resend'):
        return row  # Explicitly disposed rejected bytes remain evidence, not a recoverable output.
    if (row.get('resolution') or {}).get('result_unavailable_confirmed'):
        body = path.with_suffix('.http')
        if (not body.is_file() or file_sha256(body) != row.get('body_sha256')
                or row['resolution'].get('evidence_body_sha256') != row.get('body_sha256')):
            raise CandidateCommitError('Disposed unavailable-result evidence changed; replacement is not authorized')
    changed = False
    for suffix, field in (('.http', 'body'), ('.bin', 'raw')):
        raw = path.with_suffix(suffix)
        maximum = IMAGE_RESPONSE_MAX_BYTES if suffix == '.http' else IMAGE_OUTPUT_MAX_BYTES
        if raw.is_file() and raw.stat().st_size > maximum:
            row.update(status='output_rejected', output_rejection=f'Saved {suffix} exceeds {maximum} bytes')
            write_json(path, row)
            return row
        if not raw.is_file() or row.get(field + '_sha256'):
            continue
        try:
            if suffix == '.bin':
                from PIL import Image
                with Image.open(raw) as image:
                    image.verify()
            else:
                payload = json.loads(raw.read_text(encoding='utf-8'))
                if not isinstance(payload, (dict, list)) or not payload:
                    raise ValueError('Empty/non-object response')
        except (OSError, ValueError) as exc:
            raise CandidateCommitError(f'Saved response bytes need reconciliation: {path.name}: {type(exc).__name__}') from exc
        row.update({field + '_sha256': file_sha256(raw), field + '_bytes': raw.stat().st_size})
        row['status'] = 'received' if suffix == '.bin' else 'submitted'
        changed = True
    if changed:
        write_json(path, row)
    return row


def _resend_authorizations(records: list[tuple[Path, dict[str, Any]]], active: Path) -> int:
    bindings = {active.parent.name}
    while True:
        ancestors = {row.get('replaces_binding', path.parent.name) for path, row in records
                     if path.parent.name in bindings and row['status'] != 'prepared' and row.get('replaces')}
        if ancestors <= bindings:
            break
        bindings.update(ancestors)
    return sum((row.get('resolution') or {}).get('action') == 'approve_one_resend'
               for path, row in records if path.parent.name in bindings)


def _authorization_current(row: dict) -> bool:
    resolution = row.get('resolution') or {}
    if resolution.get('action') != 'approve_one_resend' or resolution.get('duplicate_charge_risk_accepted') is not True:
        return False
    try:
        expires=datetime.fromisoformat(resolution['expires_at'])
        return bool(resolution.get('authorization_source') == 'operator' and resolution.get('authorization_id')
            and resolution.get('binding') == row.get('binding') and expires.tzinfo is not None
            and expires > datetime.now(timezone.utc))
    except (KeyError, TypeError, ValueError):
        return False


def _check_pending_responses(directory: Path, records: list[tuple[Path, dict[str, Any]]], provider: str,
                             logical_id: str = '') -> None:
    pending = [(path, row) for path, row in records if row['status'] in {'submitted', 'resend_authorized'}]
    for path, row in records:
        if row['status'] == 'output_rejected':
            raise ReceiptDispositionRequired(f'Rejected output requires explicit receipt disposition before another POST: {path}')
        if row['status'] == 'received' or (row['status'] == 'submitted' and row.get('body_sha256')):
            raise CandidateCommitError(f'Saved response must be recovered under its original binding: {path}')
        resolution = row.get('resolution') or {}
        if row['status'] == 'resend_authorized' and not _authorization_current(row):
            raise ProviderTransportError(provider or row['provider'], 'Resend authorization is no longer current; explicit disposition required', ambiguous=True)
        authorized_cross_binding = (bool(logical_id) and len(pending) == 1
            and row.get('request_audit', {}).get('logical_task_id') == logical_id
            and resolution.get('action') == 'approve_one_resend'
            and resolution.get('duplicate_charge_risk_accepted') is True
            and 0 < _resend_authorizations(records, path) <= unknown_result_resend_limit())
        if row['status'] == 'submitted' or (path.parent != directory and row['status'] == 'resend_authorized'
                                            and not authorized_cross_binding):
            raise ProviderTransportError(provider or row['provider'],
                f'Unresolved request or original-binding resend requires reconciliation before another request: {path}', ambiguous=True)


def begin_response(directory: Path, *, provider: str, audit: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    with process_file_lock(directory.parent / '.receipt.lock'):
        records = _pending_responses(directory, str(audit.get('logical_task_id') or ''))
        _check_pending_responses(directory, records, provider, str(audit.get('logical_task_id') or ''))
        path = directory / (uuid.uuid4().hex + '.json')
        write_json(path, {'schema': RESPONSE_SCHEMA, 'binding': audit['response_binding'], 'provider': provider,
                         'status': 'prepared', 'submitted_at': None, 'request_audit': dict(audit)})
        return path


def submit_response(path: Path, audit: dict[str, Any]) -> None:
    """Record the POST boundary once; this is not proof of remote acceptance or billing."""
    with process_file_lock(path.parent.parent / '.receipt.lock'):
        row = read_json(path)
        if row.get('status') != 'prepared' or row.get('submitted_at'):
            raise ProviderTransportError(row['provider'], 'Submission already recorded; recover the original receipt, never repeat POST', ambiguous=True)
        records = _pending_responses(path.parent, str(audit.get('logical_task_id') or ''))
        _check_pending_responses(path.parent, [(p, r) for p, r in records if p != path], row['provider'],
                                 str(audit.get('logical_task_id') or ''))
        authorized = [(p, r) for p, r in records if r['status'] == 'resend_authorized']
        replaces = list(row.get('replaces', [])) if row.get('submitted_at') else [p.name for p, _ in authorized]
        origin = {'replaces_binding': authorized[0][0].parent.name} if authorized and authorized[0][0].parent != path.parent else {}
        write_json(path, {**row, **origin, 'status': 'submitted', 'request_audit': dict(audit), 'replaces': replaces,
                         'submitted_at': row.get('submitted_at') or datetime.now(timezone.utc).isoformat()})


def response_inventory(job: Path) -> dict:
    """Presence-only diagnostic projection; never reconcile, settle or authorize requests."""
    roles={};unreadable=0
    for path in (Path(job)/'reports/image_responses').glob('*/*.json'):
        try:
            row=read_json(path);logical=str(row.get('request_audit',{}).get('logical_task_id') or '').split(':')
            if row.get('schema')!=RESPONSE_SCHEMA or row.get('binding')!=path.parent.name or len(logical)!=3 or logical[0]!='generate':
                raise ValueError('Unbound receipt inventory')
            item=roles.setdefault(tuple(logical[1:]),{'native_files':0,'unresolved_requests':0,'remote_unknown_requests':0,'request_records':0})
            item['request_records']+=1
            item['native_files']+=int(bool(row.get('raw_sha256')) and path.with_suffix('.bin').is_file())
            item['unresolved_requests']+=int(row.get('status') in {'prepared','submitted','resend_authorized','output_rejected'})
            item['remote_unknown_requests']+=int(row.get('status') in {'submitted','resend_authorized'} and not row.get('body_sha256') and not row.get('raw_sha256'))
        except (OSError,ValueError,TypeError,KeyError,AttributeError):unreadable+=1
    return {'roles':roles,'unreadable':unreadable}


def response_submission_metrics(job: Path) -> dict[str, Any]:
    """Count current-job receipt boundaries only; never infer missing historical markers."""
    submitted, unrecorded, seen = 0, 0, set()
    records = {}; replaced = set()
    try:
        root = (Path(job) / 'reports/image_responses').resolve()
        for path in root.glob('*/*.json'):
            try:
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                if not resolved.is_relative_to(root):
                    raise ValueError('Receipt outside current job')
                row = read_json(path)
                if not isinstance(row, dict) or row.get('schema') != RESPONSE_SCHEMA \
                        or row.get('binding') != path.parent.name or 'submitted_at' not in row:
                    raise ValueError('Submission boundary not recorded')
                marker = row['submitted_at']
                if not isinstance(row.get('status'),str) or not isinstance(row.get('replaces',[]),list):
                    raise ValueError('Receipt disposition not recorded')
                if marker is not None:
                    if not isinstance(marker, str) or datetime.fromisoformat(marker).tzinfo is None:
                        raise ValueError('Invalid submission boundary')
                    submitted += 1
                records[(path.parent.name, path.name)] = row
                if row['status'] != 'prepared':
                    replaced.update((row.get('replaces_binding', path.parent.name), name) for name in row.get('replaces', []) if isinstance(name,str))
            except (OSError, ValueError, TypeError, RuntimeError):
                unrecorded += 1
    except (OSError, ValueError, RuntimeError):
        unrecorded += 1
    unresolved = [row for key, row in records.items() if key not in replaced]
    return {'image_provider_submission_count': submitted,
            'image_remote_unknown_receipt_count': sum(r['status'] in {'submitted','resend_authorized'} and not r.get('body_sha256') for r in unresolved),
            'image_saved_response_receipt_count': sum(r['status']=='received' or r['status']=='submitted' and bool(r.get('body_sha256')) for r in unresolved),
            'image_provider_submission_count_status': 'not_recorded' if unrecorded else 'complete',
            'image_provider_submission_unrecorded_count': unrecorded}


def resolve_response(job: Path, receipt: str, *, action: str, reason: str) -> dict[str, Any]:
    """Explicit operator disposition, not an automatic retry or a new controller."""
    path = resolve_job_owned_path(job, receipt)
    root = (job / 'reports' / 'image_responses').resolve()
    if path.suffix != '.json' or path.parent.parent != root:
        raise ValueError('Response receipt must belong to this job image_responses directory')
    unavailable = action == 'approve_unavailable_result_resend'
    if action not in {'confirmed_not_generated', 'approve_one_resend', 'approve_unavailable_result_resend'} or not reason.strip():
        raise ValueError('Receipt resolution requires an explicit action and evidence/reason')
    action = 'approve_one_resend' if unavailable else action
    with process_file_lock(root / '.receipt.lock'):
        row = _reconcile_saved_bytes(path, read_json(path))
        if row.get('schema') != RESPONSE_SCHEMA or row.get('binding') != path.parent.name:
            raise ValueError('Response receipt identity is invalid')
        rejected = row.get('status') == 'output_rejected'
        if unavailable:
            failure = row.get('download_failure') or {}
            body = path.with_suffix('.http')
            if (row.get('status') != 'submitted' or path.with_suffix('.bin').exists()
                    or failure.get('http_status') not in {404, 410} or not row.get('body_sha256')
                    or failure.get('body_sha256') != row['body_sha256'] or not body.is_file()
                    or file_sha256(body) != row['body_sha256']):
                raise ValueError('Unavailable result requires a bound 404/410 download failure, retained envelope, no native bytes and operator confirmation')
        records = _pending_responses(path.parent, str(row.get('request_audit', {}).get('logical_task_id') or ''))
        renew = row.get('status') == 'resend_authorized' and not _authorization_current(row)
        if renew and (action != 'approve_one_resend' or not any(p == path and r['status'] == 'resend_authorized' for p,r in records)):
            raise ValueError('Only an unconsumed resend authorization may be explicitly renewed')
        if rejected and action != 'approve_one_resend':
            raise ValueError('Rejected output does not prove no remote generation; only explicit resend authorization is applicable')
        if not rejected and not renew and not unavailable and (row.get('status') != 'submitted' or row.get('body_sha256')):
            raise ValueError('Only unresolved submitted or explicitly rejected output can be resolved; valid saved responses must be recovered locally')
        if any(r.get('status') == 'received' or (r.get('status') == 'submitted' and r.get('body_sha256'))
               for p, r in records if not (unavailable and p == path)):
            raise ValueError('A saved result exists; recover it without paying for a replacement')
        limit = max(1, unknown_result_resend_limit())
        if action == 'approve_one_resend' and not renew and _resend_authorizations(records, path) >= limit:
            raise ValueError(f'Unknown-result replacement limit ({limit}) reached for this logical replacement chain')
        if renew:
            row.setdefault('resolution_history', []).append(row['resolution'])
        now=datetime.now(timezone.utc)
        row.update(status='resend_authorized' if action == 'approve_one_resend' else 'known_failure',
                   resolution={'action': action, 'reason': reason.strip(), 'authorization_source': 'operator',
                               'authorization_id': uuid.uuid4().hex, 'binding': row['binding'],
                               'expires_at': (now + timedelta(hours=1)).isoformat(), 'recorded_at': now.isoformat(),
                               'duplicate_charge_risk_accepted': action == 'approve_one_resend',
                               **({'result_unavailable_confirmed': True, 'evidence_body_sha256': row['body_sha256']} if unavailable else {})})
        write_json(path, row)
    return {'receipt': str(path), 'status': row['status'], 'resolution': row['resolution'], 'requests_sent': 0}


def unknown_result_resend_limit() -> int:
    policy = load_provider_policy().get('image_generation', {})
    return min(3, max(0, int((policy.get('unknown_result_policy') or {}).get('max_replacements') or 0)))


def authorize_unknown_resend(task: dict[str, Any]) -> bool:
    """Only an unconsumed, current operator grant may allow a replacement."""
    directory = response_directory(task)
    records = _pending_responses(directory, str(task.get('logical_task_id') or ''))
    if any(row['status'] == 'received' or (row['status'] == 'submitted' and row.get('body_sha256')) for _, row in records):
        return False
    pending = [(path, row) for path, row in records if row['status'] in {'submitted', 'resend_authorized'}]
    if len(pending) != 1:
        return False
    path, row = pending[0]
    limit = unknown_result_resend_limit()
    used = _resend_authorizations(records, path)
    if row['status'] == 'resend_authorized':
        if not _authorization_current(row):
            return False
        resolution = row.get('resolution') or {}
        return path.parent == directory or (0 < used <= limit
            and resolution.get('action') == 'approve_one_resend'
            and resolution.get('duplicate_charge_risk_accepted') is True)
    return False


def save_response(path: Path, data: bytes, audit: dict[str, Any]) -> None:
    record = read_json(path)
    from .image_provider_transport import _validate_output_bytes
    _validate_output_bytes(data)
    raw = path.with_suffix('.bin')
    write_bytes_atomic(raw, data)
    write_json(path, {**record, 'status': 'received', 'raw_sha256': file_sha256(raw),
                     'raw_bytes': raw.stat().st_size, 'request_audit': audit})


def save_transport_response(path: Path, phase: str, data: bytes, audit: dict[str, Any]) -> None:
    record = read_json(path)
    if phase in {'body', 'partial'}:
        if len(data) > IMAGE_RESPONSE_MAX_BYTES:
            from .image_provider_common import ImageOutputRejected
            raise ImageOutputRejected('Transport receipt bytes exceed envelope limit')
        raw = path.with_suffix('.http' if phase == 'body' else '.partial')
        write_bytes_atomic(raw, data)
        record.update({phase + '_sha256': file_sha256(raw), phase + '_bytes': len(data)})
    write_json(path, {**record, 'request_audit': dict(audit)})


def recover_response(task: dict[str, Any], *, check_pending: bool = True) -> dict[str, Any]:
    directory = response_directory(task)
    received = []
    for path in sorted(directory.glob('*.json')):
        try:
            record = _reconcile_saved_bytes(path, read_json(path))
            if record['schema'] != RESPONSE_SCHEMA or record['binding'] != response_binding(task):
                raise ValueError('Response binding mismatch')
            if record['status'] == 'output_rejected':
                raise ReceiptDispositionRequired(f"Rejected generated output retained; explicit disposition required: {path}: {record.get('output_rejection')}")
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
    if check_pending:
        _check_pending_responses(directory, _pending_responses(directory, str(task.get('logical_task_id') or '')), '',
                                 str(task.get('logical_task_id') or ''))
    return {}


def finalized_native_response(job: Path,candidate: dict,*,require_settled_role=False) -> dict:
    """Resolve existing paid bytes for local publication work; never fetch or resend."""
    if candidate.get('contract_adoption'):
        from .candidate_state import _adoption_original
        candidate=_adoption_original(job,candidate['contract_adoption']['proof']['request']['candidate'])
    audit=candidate['request_audit'];prompt_path=resolve_job_owned_path(job,candidate['prompt_path'])
    if file_sha256(prompt_path)!=candidate['request_prompt_fingerprint']:raise CandidateCommitError('Native request prompt changed')
    task={**candidate,'job_dir':str(job),'prompt':prompt_path.read_text(encoding='utf-8')}
    binding=response_binding(task)
    if not audit.get('response_binding') or binding!=audit['response_binding']:
        raise CandidateCommitError('Native request binding differs from the selected candidate')
    directory=response_directory(task)
    if require_settled_role:
        pending=_pending_responses(directory,candidate['logical_task_id'],reconcile=False)
        if any(r['status'] in {'prepared','submitted','received','resend_authorized','output_rejected'} for _,r in pending):
            raise ReceiptDispositionRequired('Unsettled image request must be resolved before publication-only derivation')
    recorded_path=Path(str(audit.get('receipt_path') or ''))
    attempt=audit.get('attempt_id') or recorded_path.stem
    if not isinstance(attempt,str) or len(attempt)!=32 or any(c not in '0123456789abcdef' for c in attempt):
        raise CandidateCommitError('Selected native receipt has no valid attempt identity')
    path=directory/(attempt+'.json')
    if (not path.is_file() or recorded_path.name and
            (recorded_path.name!=path.name or recorded_path.parent.name!=binding)):
        raise CandidateCommitError('Selected native receipt is missing')
    row=read_json(path);origin=row.get('request_audit',{})
    if (row.get('schema')!=RESPONSE_SCHEMA or row.get('binding')!=binding or row.get('status')!='finalized'
            or row.get('provider')!=candidate['provider_name'] or not audit.get('request_id')
            or any(origin.get(k)!=audit.get(k) for k in ('request_id','attempt_id','provider','model','endpoint','inputs'))
            or row.get('raw_sha256')!=candidate['native_image']['sha256']):
        raise CandidateCommitError('Selected native receipt is not finalized or its provenance changed')
    raw=path.with_suffix('.bin')
    if not raw.is_file() or raw.stat().st_size>IMAGE_OUTPUT_MAX_BYTES or file_sha256(raw)!=row['raw_sha256']:
        raise CandidateCommitError('Saved native image is missing or changed; no new request is authorized')
    return {'native_receipt_path':path.relative_to(job).as_posix(),'native_receipt_sha256':file_sha256(path),
            'native_path':raw.relative_to(job).as_posix()}


def _received_result_material(job,request):
    """Reconstruct only cryptographically proven original transport input, not a canonical plan."""
    from copy import deepcopy
    from .io import read_jsonl
    from .run_scope import read_run_scope
    from .final_source_intents import read_final_source_intents
    from .imagegen_artifacts import assert_native_image
    import re,hashlib
    if (not isinstance(request,dict) or set(request)!={'child','role','task_fingerprint','receipt','prompt','source'}
            or request['child'] not in read_run_scope(job)['selected_children']
            or not re.fullmatch('[0-9a-f]{64}',str(request['task_fingerprint']))
            or not re.fullmatch(r'(main|scene|func|size)(?:_\d{2,})?',str(request['role']))):
        raise ValueError('Explicit same-child received-result references required')
    inventory=read_jsonl(job/'reports/image_tasks_v13.jsonl')
    if not any((r.get('child'),r.get('role'))==(request['child'],request['role']) for r in inventory):
        raise ValueError('Local result must belong to the existing role inventory')
    ref=request['receipt'];path=resolve_job_owned_path(job,ref['path'])
    if path.parent.parent!=(job/'reports/image_responses').resolve() or path.suffix!='.json':raise ValueError('Foreign response receipt')
    record=read_json(path);local=record.get('local_finalization');backup=path.with_suffix('.local-before')
    original_bytes=backup.read_bytes() if local else path.read_bytes()
    if hashlib.sha256(original_bytes).hexdigest()!=ref['sha256']:raise ValueError('Original received receipt changed')
    original=json.loads(original_bytes.decode('utf-8-sig'));audit=original.get('request_audit') or {}
    if local and (local.get('schema')!='received-local-finalization-v1' or local.get('status') not in {'prepared','completed'}
                  or local.get('request')!=request or record!={**original,'local_finalization':local,'status':record['status']}
                  or record['status'] not in {'received','finalized'}):raise ValueError('Unfinished local receipt transaction changed')
    if (original.get('schema')!=RESPONSE_SCHEMA or original.get('status')!='received' or original.get('binding')!=path.parent.name
            or audit.get('logical_task_id')!=f"generate:{request['child']}:{request['role']}"
            or audit.get('provider')!=original.get('provider') or audit.get('provider') in {'copy','mock'}
            or any(not isinstance(audit.get(k),str) or not audit[k].strip() for k in ('provider','model','endpoint','request_id','independent_authorization'))):
        raise ValueError('Select an independently authorized original received result, not a new generation')
    source=request['source']
    if (not isinstance(source,dict) or set(source)!={'path','sha256','source_id'}
            or not isinstance(source['source_id'],str) or not source['source_id'].strip()):raise ValueError('Exact original source reference required')
    source_path=resolve_job_owned_path(job,source['path'])
    if file_sha256(source_path)!=source['sha256']:raise ValueError('Original source bytes changed')
    sources=read_final_source_intents(job,require_current=False)
    if not any(s['child']==request['child'] and s['source_sha256']==source['sha256'] and
               resolve_job_owned_path(job,s['source_path'])==source_path for s in sources):raise ValueError('Original input is not this child source')
    prompt_path=resolve_job_owned_path(job,request['prompt']['path'])
    if file_sha256(prompt_path)!=request['prompt']['sha256']:raise ValueError('Original prompt changed')
    prompt=prompt_path.read_text(encoding='utf-8')
    refs=[{'kind':'edit_base','source_id':source['source_id'],'sha256':source['sha256'],'path':source_path.relative_to(job).as_posix(),
        'child':request['child'],'purpose':'Original independently authorized edit input; no new factual claims','evidence_ids':[]}]
    task={'job_dir':str(job),'child':request['child'],'role':request['role'],'logical_task_id':audit['logical_task_id'],
        'task_fingerprint':request['task_fingerprint'],'candidate_revision':0,'prompt':prompt,'generation_references':refs}
    if response_binding(task)!=original['binding'] or audit.get('response_binding')!=original['binding']:
        raise ValueError('Original prompt, task identity, revision or attachment binding differs')
    sent=audit.get('inputs',[])
    if (not isinstance(sent,list) or len(sent)!=1 or not isinstance(sent[0],dict)
            or sent[0].get('original_sha256')!=source['sha256'] or not re.fullmatch('[0-9a-f]{64}',str(sent[0].get('sent_sha256')))):
        raise ValueError('Original actual-input evidence is missing or differs')
    native=path.with_suffix('.bin');body=path.with_suffix('.http')
    for artifact,key in ((native,'raw_sha256'),(body,'body_sha256')):
        if not original.get(key) or not artifact.is_file() or file_sha256(artifact)!=original[key]:raise ValueError('Saved native/envelope evidence changed')
    if native.stat().st_size>IMAGE_OUTPUT_MAX_BYTES or body.stat().st_size>IMAGE_RESPONSE_MAX_BYTES:raise ValueError('Saved response exceeds local limits')
    assert_native_image(native.read_bytes())
    proof={'request':request,'native_sha256':original['raw_sha256'],'body_sha256':original['body_sha256'],'binding':original['binding']}
    output=resolve_job_owned_path(job,f"images/generated/{request['child']}/{request['role']}/{request['task_fingerprint']}.candidate0.png")
    task.update(input_revision_id=input_revision_id({'local_received_derivation':proof}),provider=original['provider'],
        revision_mode='initial',edit_parent_candidate_sha256='',source_path=refs[0]['path'],source_sha256=source['sha256'],edit_base_sha256=source['sha256'],
        prompt_path=prompt_path.relative_to(job).as_posix(),task_prompt_fingerprint=request['prompt']['sha256'],
        request_prompt_fingerprint=request['prompt']['sha256'],request_audit=deepcopy(audit),output_path=str(output),candidate_path=str(output))
    return path,original_bytes,record,task,proof


def finalize_received_result(job_dir,request,*,apply=False,proposal_sha256='',decision_id='',reason=''):
    """Local-only native normalization/commit under original transport; never adopts a current role."""
    from .status import job_run_lock
    from .candidate_state import current_candidate,commit_candidate_output,_manifest_path
    import re
    job=Path(job_dir).resolve()
    if not apply:
        _,_,_,_,proof=_received_result_material(job,request)
        return {'status':'preview','proposal_sha256':input_revision_id(proof),'requests_sent':0,'quality_changed':False,
            'next_action':'local_processing_only_then_explicit_current_contract_adoption'}
    if (not isinstance(decision_id,str) or not 1<=len(decision_id.strip())<=128
            or not isinstance(reason,str) or not 1<=len(reason.strip())<=2000
            or not isinstance(proposal_sha256,str) or not re.fullmatch('[0-9a-f]{64}',proposal_sha256)):
        raise ValueError('Local finalization needs preview SHA, decision ID and reason')
    with job_run_lock(job):
        path,before,record,task,proof=_received_result_material(job,request);digest=input_revision_id(proof)
        fingerprint=input_revision_id({'request':request,'proposal_sha256':proposal_sha256,'decision_id':decision_id,'reason':reason})
        local=record.get('local_finalization')
        if local and local.get('decision_fingerprint')!=fingerprint:raise ValueError('Resume the original local finalization decision')
        if digest!=proposal_sha256:raise ValueError('Received-result proposal changed')
        if local and local['status']=='completed':return {**local['result'],'status':'already_applied','currentness_not_reasserted':True}
        backup=path.with_suffix('.local-before')
        if not local:
            if backup.is_file() and backup.read_bytes()!=before:raise ValueError('Original receipt backup conflict')
            if not backup.is_file():write_bytes_atomic(backup,before)
            local={'schema':'received-local-finalization-v1','status':'prepared','request':request,'proposal_sha256':digest,'decision_id':decision_id,'reason':reason,
                'decision_fingerprint':fingerprint,'prepared_at':datetime.now(timezone.utc).isoformat()}
            write_json(path,{**record,'local_finalization':local})
        # A crash after manifest commit resumes the exact local output, never POSTs or repeats enhancement.
        import time
        task['deadline_monotonic']=time.monotonic()+180
        candidate=current_candidate(job,task,revision=0)
        if not candidate:commit_candidate_output(job,task,path.with_suffix('.bin').read_bytes())
        manifest_path=_manifest_path(job,task,0)
        finish_response(path,'finalized')
        result={'status':'applied','requests_sent':0,'quality_changed':False,
            'candidate':{'path':manifest_path.relative_to(job).as_posix(),'sha256':file_sha256(manifest_path)},
            'original_receipt_backup':backup.relative_to(job).as_posix()}
        current=read_json(path);write_json(path,{**current,'local_finalization':{**local,'status':'completed','result':result,
            'completed_at':datetime.now(timezone.utc).isoformat()}})
        return result


def materialize_response(path: Path, *, deadline: float | None = None) -> Path:
    """Decode/download a saved response only under the existing local resource lease."""
    record = read_json(path)
    if record['status'] == 'submitted' and record.get('body_sha256'):
        from .image_provider_transport import _decode_image_response
        try:
            if file_sha256(path.with_suffix('.http')) != record['body_sha256']:
                raise CandidateCommitError('Saved response envelope changed')
            if path.with_suffix('.http').stat().st_size > IMAGE_RESPONSE_MAX_BYTES:
                from .image_provider_common import ImageOutputRejected
                raise ImageOutputRejected('Saved HTTP response exceeds envelope limit')
            save_response(path, _decode_image_response(path.with_suffix('.http').read_text(encoding='utf-8'), deadline=deadline), record['request_audit'])
        except Exception as exc:
            from .image_provider_common import ImageOutputRejected
            if isinstance(exc, ImageOutputRejected):
                reject_response_output(path, str(exc))
            else:
                error, status, seen = exc, None, set()
                while error is not None and id(error) not in seen:
                    seen.add(id(error))
                    status = getattr(error, 'code', None) or getattr(getattr(error, 'response', None), 'status_code', None) or status
                    error = error.__cause__ or error.__context__
                with process_file_lock(path.parent.parent / '.receipt.lock'):
                    current = read_json(path)
                    if current['status'] == 'submitted' and current.get('body_sha256') == record['body_sha256']:
                        current['download_failure'] = {'body_sha256': record['body_sha256'], 'http_status': status,
                            'error_type': type(exc).__name__, 'attempts': int((current.get('download_failure') or {}).get('attempts') or 0) + 1,
                            'recorded_at': datetime.now(timezone.utc).isoformat()}
                        write_json(path, current)
            raise CandidateCommitError(f'Saved response decode/download needs local recovery: {type(exc).__name__}: {exc}') from exc
    return path.with_suffix('.bin')


def reject_response_output(path: Path, reason: str) -> None:
    """Keep bounded paid evidence; neither recovery nor standing unknown policy may resend it."""
    try:
        with process_file_lock(path.parent.parent / '.receipt.lock'):
            row = read_json(path)
            write_json(path, {**row, 'status': 'output_rejected', 'output_rejection': reason[:1200]})
    except Exception as exc:
        raise CandidateCommitError(f'Output rejection needs local receipt reconciliation, no resend: {exc}') from exc


def finish_response(path: Path, status: str) -> None:
    record = read_json(path)
    write_json(path, {**record, 'status': status})
    if status in {'finalized', 'rejected_content'} and not record.get('local_finalization'):
        path.with_suffix('.http').unlink(missing_ok=True)
        path.with_suffix('.partial').unlink(missing_ok=True)


def settle_candidate_response(job: Path, candidate: dict[str, Any]) -> None:
    """Settle only the response bound to an already validated current manifest."""
    audit = candidate.get('request_audit') or {}
    if not audit.get('response_binding'):
        return
    prompt = resolve_job_owned_path(job, candidate['prompt_path']).read_text(encoding='utf-8')
    task = {**candidate, 'job_dir': str(job), 'prompt': prompt}
    if response_binding(task) != audit['response_binding']:
        task = _saved_candidate_request_task(job, candidate, audit, prompt)
        if response_binding(task) != audit['response_binding']:
            raise CandidateCommitError('Committed candidate response binding disagrees with its task and saved origin')
    output = resolve_job_owned_path(job, candidate['candidate_path'])
    if file_sha256(output) != candidate['candidate_sha256']:
        raise CandidateCommitError('Committed candidate bytes changed before receipt settlement')
    directory = response_directory(task)
    with process_file_lock(directory.parent / '.receipt.lock'):
        matching = [(p, r) for p, r in _pending_responses(directory, str(audit.get('logical_task_id') or ''),reconcile=False)
                    if p.parent == directory and r['request_audit'].get('request_id') == audit.get('request_id')
                    and r['request_audit'].get('provider') == audit.get('provider')
                    and r['status'] in {'submitted', 'received', 'finalized'}]
        if len(matching) > 1:
            raise CandidateCommitError('Candidate matches more than one receipt')
        for path, row in matching:
            if row['request_audit'].get('model') != audit.get('model') or row['request_audit'].get('endpoint') != audit.get('endpoint'):
                raise CandidateCommitError('Candidate receipt request identity differs')
            if row['status'] != 'finalized' or (not row.get('local_finalization') and any(path.with_suffix(s).exists() for s in ('.http', '.partial'))):
                finish_response(path, 'finalized')


def _saved_candidate_request_task(job: Path, candidate: dict[str, Any], audit: dict[str, Any], current_prompt: str) -> dict[str, Any]:
    """Resolve a reused image to its exact earlier CandidateManifest request."""
    directory=job/'reports'/'candidate_manifests'/str(candidate.get('child') or '')/str(candidate.get('role') or '')
    matches=[]
    if not directory.is_dir():raise CandidateCommitError('Saved candidate origin is missing for response recovery')
    for path in directory.glob('*/candidate*.json'):
        try:
            prior=read_json(path)
            if (prior.get('task_fingerprint')==candidate.get('task_fingerprint')
                    or prior.get('status')!='candidate_ready'
                    or prior.get('candidate_sha256')!=candidate.get('candidate_sha256')
                    or prior.get('logical_task_id')!=candidate.get('logical_task_id')
                    or prior.get('source_sha256')!=candidate.get('source_sha256')
                    or prior.get('edit_base_sha256')!=candidate.get('edit_base_sha256')
                    or prior.get('request_prompt_fingerprint')!=candidate.get('request_prompt_fingerprint')
                    or prior.get('request_audit')!=audit):
                continue
            prior_prompt_path=resolve_job_owned_path(job,prior['prompt_path'])
            prior_prompt=prior_prompt_path.read_text(encoding='utf-8')
            if (file_sha256(prior_prompt_path)!=prior.get('request_prompt_fingerprint')
                    or prior_prompt!=current_prompt):
                continue
            if [reference_semantics(r) for r in prior.get('generation_references',[])] != [
                    reference_semantics(r) for r in candidate.get('generation_references',[])]:
                continue
            prior_output=resolve_job_owned_path(job,prior['candidate_path'])
            if not prior_output.is_file() or file_sha256(prior_output)!=prior.get('candidate_sha256'):
                continue
            original={**prior,'job_dir':str(job),'prompt':prior_prompt}
            if response_binding(original)!=audit.get('response_binding'):
                continue
            matches.append(original)
        except (OSError,ValueError,KeyError,TypeError):
            continue
    if len(matches)!=1:
        raise CandidateCommitError('Saved candidate origin is missing or ambiguous for response recovery')
    return matches[0]
