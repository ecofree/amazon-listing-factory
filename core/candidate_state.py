from __future__ import annotations

import re
import json
import hashlib
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from .api_registry import image_provider_identity_key, image_provider_physical_identity
from .imagegen_artifacts import (
    assert_image_output, assert_native_image, normalize_native_image, NATIVE_IMAGE_POLICY,
    NATIVE_IMAGE_MIN_DIMENSION, IMAGE_OUTPUT_MAX_DIMENSION,
    imagegen_output_marker,
    publish_staged_imagegen_output,
    replace_output,
    staged_imagegen_output,
)
from .image_upscale import (
    MODEL_BACKEND,
    PUBLIC_IMAGE_SIZE,
    UPSCALE_BACKEND,
    POSTPROCESS_POLICY, ImageUpscaleError, upscale_for_publication,
)
from .image_provider_common import CandidateCommitError
from .io import file_sha256, read_json, write_json
from .paths import resolve_job_owned_path
from .image_reference_context import reference_semantics, validate_reference_set, generation_reference_region_map_bytes, canonical_selection_text


class CandidateStateError(CandidateCommitError):
    pass


CANDIDATE_MANIFEST_SCHEMA_VERSION = "candidate-manifest-v9-processing-provenance"
_CANDIDATE_MANIFEST_FIELDS = {
    "schema_version", "child", "role", "logical_task_id", "input_revision_id",
    "task_fingerprint", "candidate_revision", "candidate_sha256", "candidate_path",
    "output_path", "staging_path", "output_width", "output_height", "provider_name",
    "provider_model", "provider_identity", "provider_physical", "provider_duration_seconds",
    "attempted_providers", "attempted_provider_failures", "fallback_reason", "upscale_backend",
    "task_prompt_fingerprint", "request_prompt_fingerprint", "prompt_path", "source_path",
    "source_sha256", "transport_attempt", "provider_attempts", "status",
    "generation_references", "edit_base_sha256", "edit_parent_candidate_sha256", "revision_mode", "request_audit", "native_image", "postprocess",
}


def candidate_inventory(job_dir, rows=()):
    """Persisted revisions vs the evaluated snapshot; no approval or receipt writes."""
    current={(r.get('child'),r.get('role'),r.get('candidate_sha256')) for r in rows if r.get('candidate_sha256')}
    from .io import read_jsonl
    tasks_path=Path(job_dir)/'reports/image_tasks_v13.jsonl'
    try:tasks={(r['child'],r['role'],r['task_fingerprint']) for r in read_jsonl(tasks_path) if r.get('formation_status')=='ready'} if tasks_path.is_file() else None
    except (OSError,ValueError,KeyError,TypeError,AttributeError):tasks=None
    from .image_response import response_inventory
    receipts=response_inventory(Path(job_dir));roles=receipts['roles']
    total=matched=task_bound=unreadable=0
    for path in (Path(job_dir)/'reports/candidate_manifests').glob('*/*/*/candidate*.json'):
        try:
            row=read_json(path)
            if not isinstance(row,dict) or row.get('schema_version') != CANDIDATE_MANIFEST_SCHEMA_VERSION:
                raise ValueError('Unknown manifest')
            matched+=int((row['child'],row['role'],row['candidate_sha256']) in current)
            task_bound+=int(tasks is not None and (row['child'],row['role'],row['task_fingerprint']) in tasks)
            item=roles.setdefault((row['child'],row['role']),{})
            output=resolve_job_owned_path(job_dir,row['candidate_path'])
            item['candidate_files']=item.get('candidate_files',0)+int(output.is_file())
            total+=1
        except (OSError,ValueError,KeyError,TypeError):unreadable+=1
    return {'asset_inventory_validation':'presence_only_not_currentness_or_quality',
            'asset_roles':[{'child':child,'role':role,**value} for (child,role),value in sorted(roles.items())],
            'receipt_inventory_unreadable_count':receipts['unreadable'],'candidate_manifest_count':total,'candidate_snapshot_matched_count':matched,
            'candidate_saved_task_bound_count':task_bound if tasks is not None else None,
            'candidate_revalidation_count':total-task_bound if tasks is not None else None,
            'candidate_outside_snapshot_count':total-matched,'candidate_manifest_unreadable_count':unreadable}


def production_candidate_error(candidate: dict[str, Any]) -> str:
    provider=str(candidate.get('provider_name') or '')
    if not provider or provider in {'copy','mock'}:
        return 'Diagnostic or unproven candidate is not a provider-generated delivery image'
    return ''


def current_candidate(job_dir: str | Path, task: dict[str, Any], *, required: bool = False, revision: int | None = None) -> dict[str, Any]:
    job_path = Path(job_dir).resolve()
    candidate = _recover_candidate_from_manifest(job_path, task, revision=revision)
    if candidate:
        if revision is not None and (candidate['output_path'] != _job_owned_path(job_path, str(task.get('candidate_path') or task['output_path']))
                                    or candidate['request_prompt_fingerprint'] != task.get('request_prompt_fingerprint')):
            raise CandidateStateError('Committed candidate does not match the exact request path or prompt')
        return candidate
    if revision is None and any(_manifest_path(job_path,task,0).parent.parent.glob('*/candidate*.json')):
        raise CandidateStateError('Stored candidate exists but has no current binding; reconcile it or explicitly revise, never automatically regenerate')
    if required:
        raise CandidateStateError(f"Current CandidateManifest is missing or stale: {task['child']}/{task['role']}")
    return {}


def candidate_current(job_dir: str | Path, task: dict[str, Any]) -> bool:
    return bool(_recover_candidate_from_manifest(Path(job_dir).resolve(), task, commit=False))


def candidate_prompt_current(*, task: dict, candidate: dict, prompt: dict | None) -> bool:
    """One handoff rule for validated candidates; immutable request history is never rewritten."""
    if (not candidate or not isinstance(prompt, dict) or prompt.get('status') != 'ready'
            or prompt.get('task_fingerprint') != task.get('task_fingerprint') or not prompt.get('prompt_sha256')):
        return False
    if candidate.get('task_prompt_fingerprint') == prompt['prompt_sha256']:
        return True
    reuse = candidate.get('reuse_evidence')
    return bool(isinstance(reuse, dict) and reuse.get('original_task_fingerprint')
        and reuse.get('basis') in {'same_edit_instructions_and_attachment_bytes','explicit_current_contract_adoption'}
        and reuse.get('candidate_sha256') == candidate.get('candidate_sha256')
        and candidate.get('candidate_sha256')
        and reuse.get('current_task_fingerprint') == task.get('task_fingerprint')
        and reuse.get('current_prompt_sha256') == prompt['prompt_sha256'])


def candidate_by_sha(job_dir: str | Path, task: dict[str, Any], candidate_sha256: str) -> dict[str, Any]:
    """Resolve an explicit choice within this task; never silently fall back."""
    job = Path(job_dir).resolve()
    directory = _manifest_path(job, task, 0).parent
    for path in sorted(directory.parent.glob("*/candidate*.json"), key=lambda p: (p.parent != directory, str(p))):
        match = re.fullmatch(r"candidate(0|[1-9]\d*)\.json", path.name)
        if not match:
            continue
        try:
            row = read_json(path)
        except (ValueError, OSError):
            continue
        if not isinstance(row, dict):
            continue
        if row.get("candidate_sha256") == candidate_sha256:
            if row.get("candidate_revision") != int(match[1]):
                raise CandidateStateError("Explicit candidate manifest revision disagrees with its filename")
            equivalent = _equivalent_request(job, row, task)
            if path.parent != directory and not equivalent:
                continue
            return _recover_bound_manifest(job, row, task, equivalent=equivalent)
    raise CandidateStateError("Explicit candidate SHA is not in the current task")


def write_candidate_manifest(
    job_dir: str | Path, task: dict[str, Any], *, candidate_bytes_path: Path | None = None,
    postprocess: dict[str, Any], native_image: dict[str, Any],
) -> dict[str, Any]:
    job_path = Path(job_dir).resolve()
    output = _job_owned_path(job_path, str(task.get("candidate_path") or task.get("output_path") or ""))
    candidate_bytes = _job_owned_path(job_path, str(candidate_bytes_path or output))
    source = _job_owned_path(job_path, str(task.get("source_path") or ""))
    sha = file_sha256(candidate_bytes)
    output_width, output_height = _image_dimensions(candidate_bytes)
    revision = int(task.get("candidate_revision") or _candidate_revision_from_name(output.name, f"{task.get('task_fingerprint')}.candidate"))
    provider_name = str(task.get("provider") or "")
    audit = dict(task.get('request_audit') or {})
    provider_identity = (image_provider_physical_identity(provider_name) if provider_name in {'copy', 'mock'}
                         else {'url': audit.get('endpoint'), 'model': audit.get('model')})
    source_sha = str(task.get("source_sha256") or "")
    references = [{**row, "path": _job_owned_path(job_path, row["path"]).relative_to(job_path).as_posix()}
                  for row in task.get("generation_references", [])]
    manifest = {
        "schema_version": CANDIDATE_MANIFEST_SCHEMA_VERSION,
        "child": str(task.get("child") or ""),
        "role": str(task.get("role") or ""),
        "logical_task_id": str(task.get("logical_task_id") or ""),
        "input_revision_id": str(task.get("input_revision_id") or ""),
        "task_fingerprint": str(task.get("task_fingerprint") or ""),
        "candidate_revision": revision,
        "candidate_sha256": sha,
        "candidate_path": output.relative_to(job_path).as_posix(),
        "output_path": output.relative_to(job_path).as_posix(),
        "staging_path": candidate_bytes.relative_to(job_path).as_posix() if candidate_bytes != output else "",
        'native_image': native_image,
        "output_width": output_width,
        "output_height": output_height,
        "provider_name": provider_name,
        "provider_model": provider_name if provider_name in {'copy', 'mock'} else audit.get('model'),
        "provider_identity": provider_identity,
        "provider_physical": image_provider_identity_key(provider_identity),
        "provider_duration_seconds": _rounded_optional_float(task.get("provider_duration_seconds")),
        "attempted_providers": [str(value) for value in task.get("attempted_providers") or [] if str(value or "").strip()],
        "attempted_provider_failures": [
            dict(value) for value in task.get("attempted_provider_failures") or [] if isinstance(value, dict)
        ],
        "fallback_reason": str(task.get("fallback_reason") or ""),
        "upscale_backend": postprocess['backend'],
        "postprocess": deepcopy(postprocess),
        "task_prompt_fingerprint": str(task.get("task_prompt_fingerprint") or ""),
        "request_prompt_fingerprint": str(task.get("request_prompt_fingerprint") or ""),
        "prompt_path": str(task.get("prompt_path") or ""),
        "source_path": source.relative_to(job_path).as_posix(),
        "source_sha256": source_sha,
        "generation_references": references,
        "edit_base_sha256": str(task.get("edit_base_sha256") or ""),
        "edit_parent_candidate_sha256": str(task.get("edit_parent_candidate_sha256") or ""),
        "revision_mode": str(task.get("revision_mode") or "initial"),
        "request_audit": dict(task.get("request_audit") or {}),
        "transport_attempt": int(task.get("transport_attempt") or 0),
        "provider_attempts": dict(task.get("provider_attempts") or {}),
        "status": "candidate_ready",
    }
    if task.get('publication_reprocess'):
        manifest['publication_reprocess']=deepcopy(task['publication_reprocess'])
    _validate_manifest_binding(job_path, manifest, task)
    write_json(_manifest_path(job_path, task, revision), manifest)
    return manifest


def commit_candidate_output(job_dir: str | Path, task: dict[str, Any], data: bytes) -> dict[str, Any]:
    """Commit bytes through CandidateManifest before atomically publishing the final path."""
    deadline = float(task.get('deadline_monotonic') or float('inf'))
    if time.monotonic() >= deadline:
        raise CandidateStateError('Local finalization deadline exhausted; native receipt retained')
    job_path = Path(job_dir).resolve()
    output = _job_owned_path(job_path, str(task.get("candidate_path") or task.get("output_path") or ""))
    _job_owned_path(job_path, str(task.get("source_path") or ""))
    staging = staged_imagegen_output(output)
    _job_owned_path(job_path, str(staging))
    if output.exists():
        raise CandidateStateError(f"Immutable candidate already exists: {output}")
    if staging.exists():
        staging.unlink()
    # Providers commonly return 1024x1024.  Size the bytes before the
    # CandidateManifest is written so candidate, QA, publish and template all
    # refer to the exact same 1600x1600 publication artifact.
    native_image = assert_native_image(data)
    normalized = normalize_native_image(data)
    upscale_started = time.monotonic()
    try:
        final_data, postprocess = upscale_for_publication(normalized,
            artifact_confirmation=task.get('publication_reprocess'), deadline=deadline)
    except ImageUpscaleError as exc:
        if exc.partial_output:
            diagnostic = staging.with_name(staging.stem + '.upscale_failed.' + hashlib.sha256(exc.partial_output).hexdigest()[:16] + '.png')
            if not diagnostic.exists(): replace_output(diagnostic, exc.partial_output)
        raise
    if postprocess.get('input_sha256') != hashlib.sha256(normalized).hexdigest():
        raise CandidateStateError('Post-processing record does not bind the actual execution input')
    if isinstance(task.get("request_audit"), dict) and not task.get('publication_reprocess'):
        task["request_audit"]["upscale_seconds"] = round(time.monotonic() - upscale_started, 3)
    if time.monotonic() >= deadline:
        raise CandidateStateError('Local finalization deadline exhausted before candidate commit; native receipt retained')
    replace_output(staging, final_data)
    assert_image_output(staging)
    manifest = write_candidate_manifest(
        job_path, task, candidate_bytes_path=staging, postprocess=postprocess, native_image=native_image,
    )
    publish_staged_imagegen_output(staging, output)
    if file_sha256(output) != manifest["candidate_sha256"]:
        raise CandidateStateError("Candidate commit changed output bytes")
    write_json(imagegen_output_marker(output), _marker_from_manifest(manifest))
    return manifest


def _image_dimensions(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as image:
        return int(image.width), int(image.height)


def _recover_candidate_from_manifest(job_path: Path, task: dict[str, Any], *, revision: int | None = None, commit: bool = True) -> dict[str, Any]:
    try:
        selected = _select_candidate_manifest(job_path, task, revision=revision)
        return _recover_bound_manifest(job_path, selected[0], task, equivalent=selected[1], commit=commit) if selected else {}
    except CandidateStateError:
        raise
    except Exception as exc:
        raise CandidateStateError(f"Current CandidateManifest recovery failed: {task['child']}/{task['role']}: {exc}") from exc


def saved_candidate_matches_task(job_path: Path, task: dict[str, Any], *, candidate_ref=None) -> bool:
    """Read-only recovery admission: an exact saved request, not any same-source image."""
    if candidate_ref is not None:
        inspect_saved_candidate(job_path,task,candidate_ref)
        return True
    selected = _select_candidate_manifest(job_path, task)
    if not selected or not _equivalent_request(job_path, selected[0], task):
        return False
    manifest = selected[0]
    _validate_manifest_binding(job_path, manifest, task, equivalent=True)
    output = _job_owned_path(job_path, manifest['candidate_path'])
    return output.is_file() and file_sha256(output) == manifest['candidate_sha256']


def _select_candidate_manifest(job_path: Path, task: dict[str, Any], *, revision: int | None = None):
    manifest_dir = _job_owned_path(
        job_path,
        str(
            Path("reports") / "candidate_manifests" / str(task.get("child") or "")
            / str(task.get("role") or "") / str(task.get("task_fingerprint") or "")
        ),
    )
    if not manifest_dir.is_dir() or not any(manifest_dir.glob('candidate*.json')):
        if revision is not None:
            return {}
        # Recheck only this job's exact child/role; original manifests and receipts
        # remain immutable. A revised observation is not a new paid image request.
        choices = []
        for directory in manifest_dir.parent.iterdir() if manifest_dir.parent.is_dir() else ():
            rows = list(directory.glob('candidate*.json')) if directory.is_dir() else []
            rows = [p for p in rows if re.fullmatch(r'candidate(?:0|[1-9]\d*)\.json', p.name)]
            if rows:
                choices.append(max(rows, key=lambda p: int(p.stem[9:])))
        for path in sorted(choices, key=lambda p: p.stat().st_mtime_ns, reverse=True):
            manifest = read_json(path)
            if _equivalent_request(job_path, manifest, task):
                return manifest, True
        return {}
    if revision is None:
        candidates = list(manifest_dir.glob('candidate*.json'))
    else:
        selected = manifest_dir / f'candidate{revision}.json'
        candidates = [selected] if selected.is_file() else []
    invalid = [path for path in candidates if not re.fullmatch(r"candidate(?:0|[1-9]\d*)\.json", path.name)]
    if invalid:
        raise CandidateStateError(f"CandidateManifest filename is invalid: {invalid[0]}")
    manifests = sorted(
        candidates,
        key=lambda path: _candidate_revision_from_name(path.name, "candidate"),
        reverse=True,
    )
    if not manifests:
        return {}
    # General readers use the highest revision; finalization resolves its exact request.
    # A corrupt selected revision must never silently resurrect an older image.
    highest = manifests[0]
    expected_revision = _candidate_revision_from_name(highest.name, "candidate")
    try:
        manifest = read_json(highest)
        if int(manifest.get("candidate_revision") or 0) != expected_revision:
            raise CandidateStateError("CandidateManifest filename revision disagrees with its content")
        return manifest, revision is None and _equivalent_request(job_path, manifest, task)
    except CandidateStateError:
        raise
    except Exception as exc:
        raise CandidateStateError(f"Current CandidateManifest is corrupt: {highest}") from exc


def _equivalent_request(job_path, manifest, task):
    """Exact output instructions and attachment bytes; no fuzzy semantic matching."""
    if (manifest.get('contract_adoption') or task.get('formation_status') != 'ready' or manifest.get('revision_mode') != 'initial'
            or any(manifest.get(k) != task.get(k) for k in ('child', 'role', 'logical_task_id', 'source_sha256', 'edit_base_sha256'))
            or manifest.get('schema_version') != CANDIDATE_MANIFEST_SCHEMA_VERSION):
        return False
    if [reference_semantics(r, execution=True) for r in manifest.get('generation_references', [])] != [reference_semantics(r, execution=True) for r in task.get('generation_references', [])]:
        return False
    from .image_prompt_compiler import compile_task_prompt
    path = _job_owned_path(job_path, str(manifest.get('prompt_path') or ''))
    if not path.is_file() or not _prompt_trace_current(job_path, manifest):
        return False
    return canonical_selection_text(path.read_text(encoding='utf-8')) == compile_task_prompt(task=task)


def _validated_candidate_output(job_path: Path, manifest: dict[str, Any], task: dict[str, Any], *, equivalent=False):
    _validate_manifest_binding(job_path, manifest, task, equivalent=equivalent)
    output = _job_owned_path(job_path, str(manifest.get("candidate_path") or manifest.get("output_path") or ""))
    staging = _job_owned_path(job_path, str(manifest.get("staging_path") or "")) if manifest.get("staging_path") else None
    candidate_bytes = output if output.is_file() else staging
    if candidate_bytes is None or not candidate_bytes.is_file():
        raise CandidateStateError("CandidateManifest bytes are missing")
    assert_image_output(candidate_bytes)
    sha = file_sha256(candidate_bytes)
    if sha != manifest.get("candidate_sha256"):
        raise CandidateStateError("CandidateManifest bytes changed")
    dimensions = _image_dimensions(candidate_bytes)
    if (int(manifest.get("output_width") or 0), int(manifest.get("output_height") or 0)) != dimensions:
        raise CandidateStateError("CandidateManifest image dimensions changed")
    upscale_backend = str(manifest.get("upscale_backend") or "")
    if dimensions != (PUBLIC_IMAGE_SIZE, PUBLIC_IMAGE_SIZE) or not (
        # Preserve historical error-fallback records; new execution failures never use that fallback.
        upscale_backend in {UPSCALE_BACKEND, MODEL_BACKEND, 'realesrgan-x4plus'}
        or upscale_backend.startswith(f"{UPSCALE_BACKEND}:fallback_from_realesrgan:")
    ):
        raise CandidateStateError(
            f"CandidateManifest image is not the current {PUBLIC_IMAGE_SIZE}x{PUBLIC_IMAGE_SIZE} publication artifact"
        )
    return output,candidate_bytes,sha


def _adoption_contract(job,request):
    from .image_tasks import read_image_tasks
    from .image_prompt_compiler import read_image_prompts,compile_task_prompt
    from .status import input_revision_id
    rows=read_image_tasks(job)['tasks'];prompts=read_image_prompts(job)['prompts']
    matches=[t for t in rows if (t['child'],t['role'])==(request['child'],request['role'])]
    selected=[p for p in prompts if (p['child'],p['role'])==(request['child'],request['role'])]
    if (len(matches)!=1 or len(selected)!=1 or matches[0]['formation_status']!='ready'
            or matches[0]['task_fingerprint']!=request['expected_task_fingerprint']):
        raise ValueError('Existing output adoption requires one accepted current ready role, not a pending historical draft')
    task,prompt=matches[0],selected[0]
    sha=hashlib.sha256(compile_task_prompt(task=task).encode('utf-8')).hexdigest()
    if prompt.get('status')!='ready' or prompt['task_fingerprint']!=task['task_fingerprint'] or prompt['prompt_sha256']!=sha:
        raise ValueError('Current prompt is not bound to the accepted task')
    for ref in task['generation_references']:
        if file_sha256(_job_owned_path(job,ref['path']))!=ref['sha256']:raise ValueError('Current adoption source changed')
    return task,{'task_identity':input_revision_id(task),'current_prompt_sha256':sha}


def _adoption_original(job,reference):
    if not isinstance(reference,dict) or set(reference)!={'path','sha256'}:raise ValueError('Exact original candidate path/SHA required')
    path=_job_owned_path(job,reference['path'])
    if file_sha256(path)!=reference['sha256']:raise ValueError('Original candidate manifest changed')
    original=read_json(path)
    if (original.get('contract_adoption') or original.get('publication_reprocess') or production_candidate_error(original)
            or original.get('revision_mode')!='initial'
            or path!=_manifest_path(job,original,original['candidate_revision'])):
        raise ValueError('Select the original provider candidate, not a diagnostic or derived adoption')
    output,available,_=_validated_candidate_output(job,original,original)
    if output!=available:raise ValueError('Original candidate needs local finalization first')
    from .image_response import finalized_native_response
    finalized_native_response(job,original)
    return original


def _adoption_mapping(original,task,mapping):
    if (not isinstance(mapping,list) or any(not isinstance(r,dict) or set(r)!={'original','current','sha256'} for r in mapping)
            or len({r['original'] for r in mapping})!=len(mapping) or len({r['current'] for r in mapping})!=len(mapping)
            or len(mapping)!=len(original['generation_references']) or len(mapping)!=len(task['generation_references'])):
        raise ValueError('Provide one explicit bijective source-ID/SHA mapping for all original attachments')
    by_id={r['original']:r for r in mapping};projected=[]
    for ref in original['generation_references']:
        binding=by_id.get(ref['source_id'])
        if not binding or binding['sha256']!=ref['sha256']:raise ValueError('Original attachment mapping changed')
        projected.append(reference_semantics({**ref,'source_id':binding['current']},execution=True))
    if projected!=[reference_semantics(r,execution=True) for r in task['generation_references']]:
        raise ValueError('Adoption cannot change attachment bytes, order, kinds, extents or masks')
    if any(original[k]!=task[k] for k in ('child','role','logical_task_id','source_sha256','edit_base_sha256')):
        raise ValueError('Adoption cannot change child, role or original edit base')


def _validate_contract_adoption(job,manifest,task):
    from .status import input_revision_id
    try:
        record=manifest['contract_adoption'];request=record['proof']['request']
        current,proof=_adoption_contract(job,request);original=_adoption_original(job,request['candidate'])
        _adoption_mapping(original,current,request['source_mapping'])
        proof.update(request=request,candidate_sha256=original['candidate_sha256'])
        if (proof!=record['proof'] or input_revision_id(proof)!=record['proposal_sha256']
                or input_revision_id({'proposal_sha256':record['proposal_sha256'],'decision_id':record['decision_id'],'reason':record['reason']})!=record['decision_fingerprint']
                or record['schema']!='candidate-contract-adoption-v1' or not record['decision_id'] or not record['reason'].strip()
                or request['confirmation']!='adopt_existing_output_for_current_contract'
                or any(task.get(k)!=current[k] for k in ('child','role','task_fingerprint','input_revision_id'))):
            raise ValueError('Current adoption decision or contract changed')
        expected={**original,'task_fingerprint':current['task_fingerprint'],'input_revision_id':current['input_revision_id'],
            'candidate_revision':0,'contract_adoption':record}
        if manifest!=expected:raise ValueError('Adoption changed original execution or processing provenance')
    except Exception as exc:raise CandidateStateError('Explicit candidate adoption invalid: '+str(exc)) from exc


def adopt_saved_candidate(job_dir,plugin,request,*,apply=False,proposal_sha256='',decision_id='',reason=''):
    """Explicit new contract binding, NOT claimed prompt equivalence or image quality approval."""
    from .status import input_revision_id,job_run_lock
    from .image_tasks import image_tasks_current
    from .planning_journal import PlanningJournal,journal_path
    from .image_response import finalized_native_response
    job=Path(job_dir).resolve()
    if (not isinstance(request,dict) or set(request)!={'child','role','expected_task_fingerprint','candidate','source_mapping','confirmation'}
            or request['confirmation']!='adopt_existing_output_for_current_contract'):
        raise ValueError('Explicit current-contract adoption confirmation required')
    def prepare():
        if not image_tasks_current(job,plugin,include_optional=True):raise ValueError('Reproject stale tasks with the existing owner and confirm the current role first')
        task,proof=_adoption_contract(job,request);original=_adoption_original(job,request['candidate'])
        if task['task_fingerprint']==original['task_fingerprint']:raise ValueError('Candidate already has this task binding; use normal candidate inspection')
        state=read_json(journal_path(job,task['child']))
        if PlanningJournal.pending_request_ids(state,[task['role']]):raise ValueError('Original role planning requests remain unresolved')
        finalized_native_response(job,original,require_settled_role=True)
        _adoption_mapping(original,task,request['source_mapping'])
        proof.update(request=deepcopy(request),candidate_sha256=original['candidate_sha256'])
        return task,original,proof,input_revision_id(proof)
    if not apply:
        _,original,_,digest=prepare()
        return {'status':'preview','proposal_sha256':digest,'candidate_sha256':original['candidate_sha256'],
            'requests_sent':0,'quality_changed':False,'prompt_equivalence_claimed':False}
    if (not isinstance(decision_id,str) or not 1<=len(decision_id.strip())<=128
            or not isinstance(reason,str) or not 1<=len(reason.strip())<=2000
            or not isinstance(proposal_sha256,str) or not re.fullmatch('[0-9a-f]{64}',proposal_sha256)):
        raise ValueError('Adoption needs preview SHA, decision ID and reason')
    with job_run_lock(job):
        fingerprint=input_revision_id({'proposal_sha256':proposal_sha256,'decision_id':decision_id,'reason':reason})
        path=_manifest_path(job,{'child':request['child'],'role':request['role'],'task_fingerprint':request['expected_task_fingerprint']},0)
        if path.is_file():
            existing=read_json(path);record=existing.get('contract_adoption') or {}
            if record.get('decision_fingerprint')!=fingerprint or record['proof']['request']!=request:
                raise ValueError('Current candidate binding already exists; never overwrite it')
            return {'status':'already_applied','requests_sent':0,'quality_changed':False,'currentness_not_reasserted':True}
        task,original,proof,digest=prepare()
        if digest!=proposal_sha256:raise ValueError('Adoption proposal changed')
        from .io import utc_now
        record={'schema':'candidate-contract-adoption-v1','proof':proof,'proposal_sha256':digest,'at':utc_now(),
            'decision_id':decision_id,'reason':reason,'decision_fingerprint':fingerprint}
        manifest={**original,'task_fingerprint':task['task_fingerprint'],'input_revision_id':task['input_revision_id'],
            'candidate_revision':0,'contract_adoption':record}
        _validate_contract_adoption(job,manifest,task);write_json(path,manifest)
        return {'status':'applied','candidate_sha256':original['candidate_sha256'],'requests_sent':0,'quality_changed':False}


def inspect_saved_candidate(job_dir,task,reference):
    """Exact immutable selection, no sidecar/receipt writes or staged-output publication."""
    job=Path(job_dir).resolve()
    if not isinstance(reference,dict) or set(reference)!={'path','sha256'}:
        raise CandidateStateError('Saved candidate needs an immutable manifest reference')
    path=_job_owned_path(job,str(reference['path']));raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=reference['sha256']:raise CandidateStateError('Saved candidate manifest changed')
    manifest=json.loads(raw.decode('utf-8-sig'))
    if path!=_manifest_path(job,manifest,manifest['candidate_revision']):raise CandidateStateError('Saved candidate is outside its canonical role directory')
    if not _equivalent_request(job,manifest,task):raise CandidateStateError('Saved candidate request differs from this role contract')
    output,available,sha=_validated_candidate_output(job,manifest,task,equivalent=True)
    if output!=available:raise CandidateStateError('Saved candidate needs local output finalization first')
    if file_sha256(path)!=reference['sha256']:raise CandidateStateError('Saved candidate provenance changed during inspection')
    return {'manifest':deepcopy(reference),'candidate_sha256':sha,'candidate_path':output.relative_to(job).as_posix(),
        'candidate_revision':manifest['candidate_revision'],'provider_name':manifest['provider_name'],
        'original_task_fingerprint':manifest['task_fingerprint'],'current_task_fingerprint':task['task_fingerprint']}


def _recover_bound_manifest(job_path: Path, manifest: dict[str, Any], task: dict[str, Any], *, equivalent=False, commit=True) -> dict[str, Any]:
    output,candidate_bytes,sha=_validated_candidate_output(job_path,manifest,task,equivalent=equivalent)
    if not output.is_file():
        if not commit:return {}
        publish_staged_imagegen_output(candidate_bytes, output)
    if file_sha256(output) != sha:
        raise CandidateStateError("Published candidate bytes changed")
    from .image_response import settle_candidate_response
    if commit and not manifest.get('publication_reprocess') and not manifest.get('contract_adoption'):
        settle_candidate_response(job_path, manifest)
    # The sidecar is a reconstructable transaction receipt only. CandidateManifest
    # is the sole currentness/provenance authority and a stale receipt can never
    # veto a valid committed candidate.
    receipt = _marker_from_manifest(manifest)
    marker_path = imagegen_output_marker(output)
    try:
        current_receipt = read_json(marker_path) if marker_path.is_file() else {}
    except Exception:
        current_receipt = {}
    if commit and current_receipt != receipt and not manifest.get('contract_adoption'):
        write_json(marker_path, receipt)
    origins=[];origin=manifest
    while True:
        path=_manifest_path(job_path,origin,origin['candidate_revision'])
        raw=path.read_bytes()
        if json.loads(raw.decode('utf-8-sig'))!=origin:raise CandidateStateError('Candidate provenance changed during read')
        origins.append({'path':path.relative_to(job_path).as_posix(),'sha256':hashlib.sha256(raw).hexdigest()})
        if origin.get('contract_adoption'):
            origin=_adoption_original(job_path,origin['contract_adoption']['proof']['request']['candidate'])
            continue
        if not origin.get('publication_reprocess'):break
        parent=_manifest_path(job_path,origin,origin['publication_reprocess']['parent_revision'])
        if file_sha256(parent)!=origin['publication_reprocess']['parent_manifest_sha256']:
            raise CandidateStateError('Publication origin changed during read')
        origin=read_json(parent)
    return {
        'provenance_manifests':origins,
        "candidate_sha256": sha,
        "candidate_path": str(manifest.get("candidate_path") or output.relative_to(job_path)),
        "candidate_revision": int(manifest.get("candidate_revision") or 0),
        "revision_mode": manifest['revision_mode'],
        "edit_parent_candidate_sha256": manifest['edit_parent_candidate_sha256'],
        "provider_physical": str(manifest.get("provider_physical") or ""),
        "provider_name": str(manifest.get("provider_name") or ""),
        "task_prompt_fingerprint": str(manifest.get("task_prompt_fingerprint") or ""),
        "request_prompt_fingerprint": str(manifest.get("request_prompt_fingerprint") or ""),
        "prompt_path": str(manifest.get("prompt_path") or ""),
        "transport_attempt": int(manifest.get("transport_attempt") or 0),
        "provider_attempts": dict(manifest.get("provider_attempts") or {}),
        "state": "manifest_recovered",
        **({'reuse_evidence': {'original_task_fingerprint': manifest['task_fingerprint'],
            'current_task_fingerprint': task['task_fingerprint'], 'candidate_sha256': sha, 'basis': 'same_edit_instructions_and_attachment_bytes',
            'current_prompt_sha256': hashlib.sha256(canonical_selection_text(_job_owned_path(job_path, manifest['prompt_path']).read_text(encoding='utf-8')).encode('utf-8')).hexdigest()}}
           if equivalent else {'reuse_evidence':{'original_task_fingerprint':read_json(_job_owned_path(job_path,manifest['contract_adoption']['proof']['request']['candidate']['path']))['task_fingerprint'],
               'current_task_fingerprint':task['task_fingerprint'],'candidate_sha256':sha,'basis':'explicit_current_contract_adoption',
               'current_prompt_sha256':manifest['contract_adoption']['proof']['current_prompt_sha256']}}
           if manifest.get('contract_adoption') else {}),
        'postprocess': deepcopy(manifest['postprocess']),
        **({'publication_reprocess':deepcopy(manifest['publication_reprocess'])} if manifest.get('publication_reprocess') else {}),
        "output_path": output,
    }


def _validate_manifest_binding(job_path: Path, manifest: dict[str, Any], task: dict[str, Any], *, equivalent=False) -> None:
    if isinstance(manifest,dict) and manifest.get('contract_adoption'):
        _validate_contract_adoption(job_path,manifest,task)
        return
    if task.get("revision_mode") == "targeted_edit":
        from .image_tasks import read_image_tasks

        bound = [row for row in read_image_tasks(job_path)["tasks"]
                 if row["task_fingerprint"] == task["task_fingerprint"] and row["logical_task_id"] == task["logical_task_id"]]
        if len(bound) != 1:
            raise CandidateStateError("Targeted edit has no unique canonical ImageTask")
        task = bound[0]
    if not isinstance(manifest, dict) or manifest.get('schema_version') != CANDIDATE_MANIFEST_SCHEMA_VERSION:
        raise CandidateStateError('CandidateManifest schema is stale')
    expected_fields=_CANDIDATE_MANIFEST_FIELDS | ({'publication_reprocess'} if 'publication_reprocess' in manifest else set())
    if set(manifest) != expected_fields:
        raise CandidateStateError("CandidateManifest fields do not match the current contract")
    native = manifest['native_image']
    if (not isinstance(native, dict) or set(native) != {'policy', 'sha256', 'size'}
            or native['policy'] != NATIVE_IMAGE_POLICY or not re.fullmatch('[0-9a-f]{64}', str(native['sha256']))
            or not isinstance(native['size'], list) or len(native['size']) != 2
            or any(type(n) is not int or not NATIVE_IMAGE_MIN_DIMENSION <= n <= IMAGE_OUTPUT_MAX_DIMENSION for n in native['size'])
            or native['size'][0] != native['size'][1]):
        raise CandidateStateError('CandidateManifest has no valid native integrity evidence')
    _validate_postprocess(manifest)
    expected = {
        "child": str(task.get("child") or ""),
        "role": str(task.get("role") or ""),
        "logical_task_id": str(task.get("logical_task_id") or ""),
        "input_revision_id": str(task.get("input_revision_id") or ""),
        "task_fingerprint": str(task.get("task_fingerprint") or ""),
    }
    if equivalent:
        if not _equivalent_request(job_path, manifest, task):
            raise CandidateStateError('Candidate execution equivalence is not established')
        expected = {k:v for k,v in expected.items() if k not in {'task_fingerprint', 'input_revision_id'}}
    if any(str(manifest.get(key) or "") != value for key, value in expected.items()):
        raise CandidateStateError("CandidateManifest does not match current ImageTask")
    sha = str(manifest.get("candidate_sha256") or "")
    if len(sha) != 64 or not str(manifest.get("candidate_path") or ""):
        raise CandidateStateError("CandidateManifest has no committed candidate identity")
    if manifest.get("status") != "candidate_ready":
        raise CandidateStateError("CandidateManifest status is not current")
    candidate = _job_owned_path(job_path, str(manifest["candidate_path"]))
    output = _job_owned_path(job_path, str(manifest.get("output_path") or ""))
    if candidate != output:
        raise CandidateStateError("CandidateManifest output paths disagree")
    revision = int(manifest.get("candidate_revision") or 0)
    expected_name = f"{manifest.get('task_fingerprint')}.candidate{revision}.png"
    if candidate.name != expected_name:
        raise CandidateStateError("CandidateManifest revision does not match its output filename")
    if manifest.get("staging_path"):
        _job_owned_path(job_path, str(manifest["staging_path"]))
    # Historical request provenance stays immutable; current paths have their own byte checks.
    for record in (manifest, task):
        source = _job_owned_path(job_path, str(record.get("source_path") or ""))
        if not source.is_file() or file_sha256(source) != record.get('source_sha256'):
            raise CandidateStateError("Candidate source evidence is missing or changed")
    references = manifest["generation_references"]
    expected_refs = task["generation_references"]
    try:
        validate_reference_set(references, child=manifest["child"], edit_base_sha256=manifest["edit_base_sha256"])
        validate_reference_set(expected_refs, child=task['child'], edit_base_sha256=task['edit_base_sha256'])
    except ValueError as exc:
        raise CandidateStateError(str(exc)) from exc
    for ref in [*references, *expected_refs]:
        inputs = [('reference', ref['path'], ref['sha256'])]
        if ref.get('protected_mask'):
            inputs.append(('mask', ref['protected_mask'].get('path'), ref['protected_mask'].get('sha256')))
        for kind, value, expected_sha in inputs:
            path = _job_owned_path(job_path, value)
            if not path.is_file() or file_sha256(path) != expected_sha:
                raise CandidateStateError(f"Candidate input {kind} is missing or changed")
    mode = manifest["revision_mode"]
    if mode not in {"initial", "targeted_edit", "full_redraw"}:
        raise CandidateStateError("Candidate revision mode is invalid")
    parent = manifest["edit_parent_candidate_sha256"]
    if mode == "targeted_edit":
        if len(parent) != 64 or parent != manifest["edit_base_sha256"]:
            raise CandidateStateError("Targeted edit is not bound to its parent candidate")
    elif parent or manifest["edit_base_sha256"] != task["edit_base_sha256"]:
        raise CandidateStateError("Initial/full-redraw base must be the task's observed edit view")
    if mode == "targeted_edit":
        original = {**expected_refs[0], "kind": "product_evidence", "purpose": "Original product structure and state evidence"}
        original.pop("protected_mask", None)
        if [reference_semantics(ref) for ref in references[1:]] != [reference_semantics(ref) for ref in [original, *expected_refs[1:]]]:
            raise CandidateStateError("Targeted edit auxiliary evidence differs from the task")
        match = re.fullmatch(r"candidate_(\d+)", references[0]["source_id"])
        if not match or int(match[1]) >= revision:
            raise CandidateStateError("Targeted edit parent is not an earlier candidate")
        parent_manifest = read_json(_manifest_path(job_path, task, int(match[1])))
        if parent_manifest.get("candidate_sha256") != parent or _job_owned_path(job_path, str(parent_manifest.get("candidate_path") or "")) != _job_owned_path(job_path, references[0]["path"]):
            raise CandidateStateError("Targeted edit parent manifest does not match its pixels")
        _validate_manifest_binding(job_path, parent_manifest, task)
    elif [reference_semantics(ref, execution=equivalent) for ref in references] != [reference_semantics(ref, execution=equivalent) for ref in expected_refs]:
        raise CandidateStateError("Candidate references differ from the task reference contract")
    audit = manifest["request_audit"]
    if not isinstance(audit, dict):
        raise CandidateStateError("Candidate request audit is malformed")
    sent = audit.get("inputs", [])
    if manifest.get("provider_name") not in {"copy", "mock"}:
        if audit.get("provider") != manifest["provider_name"] or audit.get("model") != manifest["provider_model"] or not audit.get("request_id"):
            raise CandidateStateError("Candidate request identity is inconsistent")
        if not isinstance(sent, list) or any(not isinstance(row, dict) for row in sent):
            raise CandidateStateError("Candidate actual-input evidence is malformed")
        expected_inputs = [row['sha256'] for row in references]
        if audit.get('region_guidance_mode') == 'opaque_reference':
            region_map = generation_reference_region_map_bytes({
                'job_dir': str(job_path), 'child': manifest['child'],
                'edit_base_sha256': manifest['edit_base_sha256'], 'generation_references': references,
            }, plugin=None)
            if region_map is None or audit.get('region_map_attachment') != len(references) + 1 or mode == 'targeted_edit':
                raise CandidateStateError('Candidate region map is not bound to its original edit base')
            expected_inputs.append(hashlib.sha256(region_map).hexdigest())
        if [row.get("original_sha256") for row in sent] != expected_inputs or any(not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sent_sha256") or "")) for row in sent):
            raise CandidateStateError("Candidate has no matching actual-input transport evidence")
    identity = manifest.get("provider_identity") if isinstance(manifest.get("provider_identity"), dict) else {}
    if not identity or image_provider_identity_key(identity) != str(manifest.get("provider_physical") or ""):
        raise CandidateStateError("CandidateManifest provider identity is invalid")
    identity_model = str(identity.get("model") or identity.get("builtin") or "")
    if manifest.get('provider_name') not in {'copy', 'mock'} and (not audit.get('endpoint') or identity.get('url') != audit['endpoint']):
        raise CandidateStateError('Candidate endpoint differs from its actual request snapshot')
    if not str(manifest.get("provider_name") or "") or str(manifest.get("provider_model") or "") != identity_model:
        raise CandidateStateError("CandidateManifest provider provenance is inconsistent")
    if not _prompt_trace_current(job_path, manifest):
        raise CandidateStateError("CandidateManifest prompt trace is missing or changed")
    if 'publication_reprocess' in manifest:_validate_publication_derivation(job_path,manifest,task)


def _validate_postprocess(manifest):
    row = manifest['postprocess']
    branches = {'model_enlargement', 'downsample', 'passthrough', 'format_conversion', 'explicit_artifact_recovery'}
    base = {'policy', 'branch', 'backend', 'input_sha256', 'output_sha256', 'input_size', 'output_size',
            'pillow_version', 'algorithm', 'duration_seconds'}
    if not isinstance(row, dict) or row.get('policy') != POSTPROCESS_POLICY or row.get('branch') not in branches:
        raise CandidateStateError('Candidate has no actual post-processing execution record')
    model = row['branch'] == 'model_enlargement'; recovery = row['branch'] == 'explicit_artifact_recovery'
    fields = base | ({'model_execution'} if model else set()) | ({'artifact_confirmation'} if recovery else set())
    if (set(row) != fields or row['backend'] != manifest['upscale_backend']
            or row['backend'] != (MODEL_BACKEND if model else UPSCALE_BACKEND)
            or row['output_sha256'] != manifest['candidate_sha256']
            or not re.fullmatch('[0-9a-f]{64}', str(row['input_sha256']))
            or row['input_size'] != manifest['native_image']['size']
            or row['output_size'] != [manifest['output_width'], manifest['output_height']]
            or not isinstance(row['pillow_version'], str) or not row['pillow_version']
            or row['algorithm'] != ('unchanged' if row['branch'] == 'passthrough' else 'LANCZOS')
            or type(row['duration_seconds']) not in {int, float} or not 0 <= row['duration_seconds'] < float('inf')):
        raise CandidateStateError('Post-processing identity does not bind the candidate bytes')
    width, target = row['input_size'][0], row['output_size'][0]
    if ((model and width >= target) or (row['branch'] == 'downsample' and width <= target)
            or (row['branch'] in {'passthrough', 'format_conversion'} and width != target)):
        raise CandidateStateError('Post-processing branch disagrees with actual dimensions')
    if row['branch'] == 'passthrough' and row['input_sha256'] != row['output_sha256']:
        raise CandidateStateError('Passthrough processing changed the recorded image identity')
    if recovery:
        binding = manifest.get('publication_reprocess', {})
        if row['artifact_confirmation'] != {key: binding.get(key) for key in ('parent_candidate_sha256', 'reason')}:
            raise CandidateStateError('Artifact recovery confirmation is not bound to the selected candidate')
    if model:
        execution = row['model_execution']
        if (not isinstance(execution, dict) or set(execution) != {'model','assets','gpu_id','gpu_name','tile','threads',
                'scale','timeout_seconds','output_format','enhanced_size','execution_seconds'}
                or execution['model'] != MODEL_BACKEND or execution['threads'] != '1:1:1' or execution['scale'] != 4
                or execution['output_format'] != 'png' or execution['enhanced_size'] != [width*4,width*4]
                or type(execution['gpu_id']) is not int or not 0 <= execution['gpu_id'] <= 31
                or not isinstance(execution['gpu_name'], str) or not execution['gpu_name']
                or type(execution['tile']) is not int or not 32 <= execution['tile'] <= 512 or execution['tile'] % 32
                or type(execution['timeout_seconds']) is not int or not 10 <= execution['timeout_seconds'] <= 300
                or type(execution['execution_seconds']) not in {int,float} or not 0 <= execution['execution_seconds'] < float('inf')
                or not isinstance(execution['assets'],dict) or set(execution['assets']) != {'exe','bin','param'}):
            raise CandidateStateError('Model execution assets or parameters are incomplete')
        for asset in execution['assets'].values():
            if (not isinstance(asset,dict) or set(asset) != {'path','sha256'} or not isinstance(asset['path'],str)
                    or not Path(asset['path']).is_absolute() or not re.fullmatch('[0-9a-f]{64}',str(asset['sha256']))):
                raise CandidateStateError('Model execution asset identity is invalid')


_PUBLICATION_SCHEMA='publication-reprocess-v1'
_PUBLICATION_FIELDS={'schema','operation_id','parent_revision','parent_candidate_sha256','parent_manifest_sha256',
    'native_receipt_path','native_receipt_sha256','native_path','backend','target_size','reason'}


def _publication_operation(task,parent_sha,native_sha):
    from .status import input_revision_id
    return input_revision_id({'task':task['task_fingerprint'],'parent':parent_sha,'native':native_sha,
        'backend':UPSCALE_BACKEND,'size':PUBLIC_IMAGE_SIZE})


def _validate_publication_derivation(job,manifest,task):
    from .image_response import finalized_native_response
    record=manifest['publication_reprocess']
    if (not isinstance(record,dict) or set(record)!=_PUBLICATION_FIELDS or record['schema']!=_PUBLICATION_SCHEMA
            or type(record['parent_revision']) is not int or not 0<=record['parent_revision']<manifest['candidate_revision']
            or record['backend']!=UPSCALE_BACKEND or record['target_size']!=PUBLIC_IMAGE_SIZE
            or manifest['upscale_backend']!=record['backend'] or not isinstance(record['reason'],str) or not record['reason'].strip()):
        raise CandidateStateError('Invalid publication-only derivation')
    path=_manifest_path(job,task,record['parent_revision'])
    if not path.is_file() or file_sha256(path)!=record['parent_manifest_sha256']:raise CandidateStateError('Publication parent manifest changed')
    parent=read_json(path);_validate_manifest_binding(job,parent,task)
    if parent['candidate_sha256']!=record['parent_candidate_sha256'] or file_sha256(_job_owned_path(job,parent['candidate_path']))!=parent['candidate_sha256']:
        raise CandidateStateError('Publication parent bytes changed')
    changed={'schema_version','postprocess','candidate_revision','candidate_sha256','candidate_path','output_path','staging_path','output_width','output_height','upscale_backend'}
    if any(manifest[k]!=parent[k] for k in _CANDIDATE_MANIFEST_FIELDS-changed):
        raise CandidateStateError('Publication processing cannot rewrite native generation provenance')
    native=finalized_native_response(job,parent)
    if any(record[k]!=v for k,v in native.items()):raise CandidateStateError('Publication native receipt binding changed')
    if record['operation_id']!=_publication_operation(task,parent['candidate_sha256'],parent['native_image']['sha256']):
        raise CandidateStateError('Publication operation identity changed')


def next_candidate_revision(job_path,task,start,*,skip_existing=False):
    revision=max(0,int(start))
    while True:
        output=_job_owned_path(job_path,f"{str(task['output_dir']).rstrip('/')}/{task['task_fingerprint']}.candidate{revision}.png")
        manifest=_manifest_path(job_path,task,revision)
        if not output.exists() and not manifest.exists():return revision
        if not skip_existing:raise CandidateStateError(f"Unowned candidate output blocks immutable revision {revision}: {task.get('child')}/{task.get('role')}")
        revision+=1


def reprocess_candidate_publication(job_dir,task,*,candidate_sha256,reason,task_prompt_fingerprint,upscale_artifact_confirmed=False):
    """Confirmed artifact recovery only, through the normal immutable commit authority."""
    if upscale_artifact_confirmed is not True:
        raise CandidateStateError('Lanczos recovery requires confirmation of an upscale artifact on the selected candidate')
    from .process_lock import process_file_lock
    from .image_response import finalized_native_response
    job=Path(job_dir).resolve()
    if not re.fullmatch('[0-9a-f]{64}',str(candidate_sha256)) or not str(reason).strip():
        raise CandidateStateError('Publication reprocess requires an explicit parent SHA and reason')
    directory=_manifest_path(job,task,0).parent
    with process_file_lock(directory/'.publication.lock'):
        parent_candidate=candidate_by_sha(job,task,candidate_sha256)
        parent_path=_manifest_path(job,task,parent_candidate['candidate_revision']);parent=read_json(parent_path)
        if parent['task_prompt_fingerprint']!=task_prompt_fingerprint:raise CandidateStateError('Selected candidate task prompt is stale')
        if parent['upscale_backend']==UPSCALE_BACKEND:
            origin=parent
            while origin.get('publication_reprocess'):
                origin=read_json(_manifest_path(job,task,origin['publication_reprocess']['parent_revision']))
            finalized_native_response(job,origin,require_settled_role=True)
            return parent_candidate
        native=finalized_native_response(job,parent,require_settled_role=True)
        operation=_publication_operation(task,parent['candidate_sha256'],parent['native_image']['sha256'])
        receipt=directory/('publication-'+operation+'.json')
        binding={'schema':_PUBLICATION_SCHEMA,'operation_id':operation,'parent_revision':parent['candidate_revision'],
            'parent_candidate_sha256':parent['candidate_sha256'],'parent_manifest_sha256':file_sha256(parent_path),
            **native,'backend':UPSCALE_BACKEND,'target_size':PUBLIC_IMAGE_SIZE,'reason':str(reason).strip()}
        if receipt.is_file():
            saved=read_json(receipt)
            if saved.get('schema')!=_PUBLICATION_SCHEMA or any(saved.get('binding',{}).get(k)!=v for k,v in binding.items() if k!='reason'):
                raise CandidateStateError('Reserved publication operation changed')
            binding=saved['binding'];revision=saved['candidate_revision']
        else:
            highest=current_candidate(job,task,required=True)
            revision=next_candidate_revision(job,task,highest['candidate_revision']+1)
            saved={'schema':_PUBLICATION_SCHEMA,'binding':binding,'candidate_revision':revision,'status':'prepared'}
            write_json(receipt,saved)
        relative=f"{str(task['output_dir']).rstrip('/')}/{task['task_fingerprint']}.candidate{revision}.png"
        output=_job_owned_path(job,relative);manifest_path=_manifest_path(job,task,revision)
        if manifest_path.is_file():
            committed=read_json(manifest_path)
            if committed.get('publication_reprocess')!=binding:raise CandidateStateError('Reserved revision belongs to another publication operation')
            result=_recover_bound_manifest(job,committed,task)
        else:
            if output.exists():raise CandidateStateError('Unowned bytes occupy the reserved publication revision')
            raw=_job_owned_path(job,binding['native_path']).read_bytes()
            if assert_native_image(raw)!=parent['native_image']:raise CandidateStateError('Native bytes differ from the selected model result')
            runtime={**task,**{k:deepcopy(parent[k]) for k in _CANDIDATE_MANIFEST_FIELDS if k not in {
                'schema_version','postprocess','candidate_revision','candidate_sha256','candidate_path','output_path','staging_path','output_width','output_height','upscale_backend','status'}},
                'provider':parent['provider_name'],'candidate_revision':revision,'candidate_path':relative,'output_path':str(output),
                'publication_reprocess':binding}
            commit_candidate_output(job,runtime,raw)
            result=_recover_bound_manifest(job,read_json(manifest_path),task)
        completed={**saved,'status':'committed','candidate_sha256':result['candidate_sha256']}
        if saved!=completed:write_json(receipt,completed)
        return result


def _marker_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    from .imagegen_artifacts import IMAGEGEN_OUTPUT_CACHE_VERSION

    return {
        "version": IMAGEGEN_OUTPUT_CACHE_VERSION,
        "output_sha256": str(manifest["candidate_sha256"]),
        "source_path": str(manifest.get("source_path") or ""),
        "source_sha256": str(manifest.get("source_sha256") or ""),
        "task_prompt_sha256": str(manifest.get("task_prompt_fingerprint") or ""),
        "request_prompt_sha256": str(manifest.get("request_prompt_fingerprint") or ""),
        "prompt_path": str(manifest.get("prompt_path") or ""),
        "provider": str(manifest.get("provider_name") or ""),
        "provider_model": str(manifest.get("provider_model") or ""),
        "provider_identity": dict(manifest.get("provider_identity") or {}),
        "task_fingerprint": str(manifest.get("task_fingerprint") or ""),
        "input_revision_id": str(manifest.get("input_revision_id") or ""),
        "upscale_backend": str(manifest.get("upscale_backend") or "legacy"),
    }


def _prompt_trace_current(job_path: Path, marker: dict[str, Any]) -> bool:
    raw = str(marker.get("prompt_path") or "").strip()
    expected = str(
        marker.get("request_prompt_sha256")
        or marker.get("request_prompt_fingerprint")
        or ""
    ).strip()
    if not raw or not expected:
        return False
    try:
        path = resolve_job_owned_path(job_path, raw)
    except ValueError:
        return False
    return path.is_file() and file_sha256(path) == expected


def _job_owned_path(job_path: Path, value: str) -> Path:
    if not str(value or "").strip():
        raise CandidateStateError("CandidateManifest path is empty")
    try:
        return resolve_job_owned_path(job_path, value)
    except ValueError as exc:
        raise CandidateStateError("CandidateManifest path escapes the job directory") from exc


def _manifest_path(job_path: Path, task: dict[str, Any], revision: int) -> Path:
    path = (
        job_path
        / "reports"
        / "candidate_manifests"
        / str(task.get("child") or "")
        / str(task.get("role") or "")
        / str(task.get("task_fingerprint") or "")
        / f"candidate{int(revision)}.json"
    )
    return _job_owned_path(job_path, str(path))




def _candidate_revision_from_name(name: str, prefix: str) -> int:
    tail = name.removeprefix(prefix)
    for suffix in (".png", ".json"):
        tail = tail.removesuffix(suffix)
    try:
        return max(0, int(tail))
    except ValueError:
        return 0


def _rounded_optional_float(value: Any) -> float | None:
    try:
        return round(max(0.0, float(value)), 3)
    except (TypeError, ValueError):
        return None
