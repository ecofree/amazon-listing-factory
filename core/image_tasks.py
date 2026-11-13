from __future__ import annotations

from pathlib import Path
from typing import Any

from .final_source_intents import planning_source_intents, selected_task_source_intents
from .image_prompt_compiler import PROMPT_CONTRACT_VERSION, compile_task_prompt
from .image_reference_context import validate_reference_set, resolve_edit_references, reference_semantics
from .image_task_inputs import (
    build_display_copy_contract,
    build_renderable_text_contract,
    execution_profile,
    task_specs,
    task_facts,
)
from .io import read_jsonl, write_jsonl
from .plugin import ProductPlugin
from .product_family import read_product_family
from .required_role_policy import compiled_image_policy, required_role_policy, scope_image_policy
from .measurement_sources import measurement_authority
from .run_scope import read_run_scope
from .status import input_revision_id, logical_task_id
from .visual_design_kit import read_visual_design_kits, current_visual_role_bases


IMAGE_TASK_SCHEMA_VERSION = "image-task-v13"
IMAGE_TASK_POLICY_VERSION = "output-evidence-child-direction-v57-bound-design-selection"
IMAGE_TASK_ARTIFACT = "image_tasks_v13.jsonl"
_TASK_BASE_FIELDS = {"schema_version", "policy_version", "category_id", "child", "role", "role_family", "logical_task_id", "output_dir", "prompt_contract_version", "category_image_policy", "formation_status", "formation_reason", "source_path", "source_sha256", "task_fingerprint", "input_revision_id"}
_TASK_READY_FIELDS = _TASK_BASE_FIELDS | {"family_design_id", "family_art_direction", "source_intent_revision_id", "source_index", "generation_references", "edit_base_sha256", "reference_mode", "product_facts", "measurement_authority", "display_copy_contract", "renderable_text_contract", "image_direction", "edit_contract", "execution_profile"}
_TASK_BLOCKED_FIELDS = _TASK_BASE_FIELDS | {"formation_reason_code", "formation_failure_owner"}


class ImageTaskError(RuntimeError):
    pass


def build_image_tasks(
    *, job_dir: str | Path, plugin: ProductPlugin, workers: int = 0,
    include_optional: bool = False, work_children: tuple[str, ...] = (),
) -> dict[str, Any]:
    del workers
    job = Path(job_dir).resolve()
    require_settled_image_projection(job)
    from .run_scope import execution_children
    selected=execution_children(job,work_children)
    rows = _expected_rows(job, plugin, include_optional=include_optional,selected_children=selected if work_children else None)
    for row in rows:
        validate_image_task(row)
    preserved=[]
    if work_children and (job/'reports'/IMAGE_TASK_ARTIFACT).is_file():
        preserved=[row for row in read_image_tasks(job,category_id=plugin.category_id)['tasks'] if row['child'] not in selected]
    write_jsonl(job/'reports'/IMAGE_TASK_ARTIFACT,sorted([*preserved,*rows],key=lambda r:(r['child'],_role_sort_key(r['role']))))
    failures = [_task_failure(row, job) for row in rows if row["formation_status"] == "blocked"]
    scope = read_run_scope(job)
    coverage = executable_coverage(rows, list(scope["selected_children"]), required_role_policy(plugin).counts)
    selected_sources = {
        (str(row.get("child") or ""), str(row.get("source_path") or ""))
        for row in rows
        if row.get("source_path")
    }
    not_selected = [
        {
            "child": str(source.get("child") or ""),
            "source_index": int(source.get("source_index") or 0),
            "role": str(source.get("role") or ""),
            "status": "classified_not_selected",
        }
        for source in planning_source_intents(job, plugin=plugin,children=selected if work_children else None)
        if (str(source.get("child") or ""), str(source.get("source_path") or "")) not in selected_sources
    ]
    return {
        "schema_version": IMAGE_TASK_SCHEMA_VERSION,
        "tasks": rows,
        "failures": failures,
        "executable_coverage": coverage,
        "source_selection_audit": not_selected,
    }


def require_settled_image_projection(job,*,active=None):
    from .io import read_json
    for path in (Path(job)/'reports/image_contract_reprojection').glob('*/decision.json'):
        record=read_json(path)
        if (record.get('schema')!='image-contract-projection-v1' or record.get('status') not in {'prepared','completed','cancelled'}
                or input_revision_id({'decision_id':record['decision_id']})!=path.parent.name):
            raise ImageTaskError('Invalid image contract projection decision; explicit reconciliation required')
        if record['status']=='prepared' and path.parent.name!=active:
            raise ImageTaskError('Unfinished image contract projection; resume the same explicit decision')


def resume_image_contract_projection(job_dir,plugin):
    """Normal local continuation; changed inputs safely cancel only owned writes."""
    from .io import read_json,write_json,file_sha256,write_bytes_atomic,utc_now
    job=Path(job_dir).resolve()
    from .image_prompt_compiler import IMAGE_PROMPT_ARTIFACT
    from .final_source_intents import FinalSourceIntentError
    paths={'tasks':job/'reports'/IMAGE_TASK_ARTIFACT,'prompts':job/'reports'/IMAGE_PROMPT_ARTIFACT}
    for path in (job/'reports/image_contract_reprojection').glob('*/decision.json'):
        record=read_json(path)
        if record.get('status')!='prepared':continue
        try:
            reproject_image_contracts(job,plugin,record['proof']['request'],apply=True,
                proposal_sha256=input_revision_id(record['proof']),decision_id=record['decision_id'],reason=record['reason'])
        except (ValueError,FinalSourceIntentError) as exc:
            if not isinstance(exc,FinalSourceIntentError) and str(exc)!='Projection inputs changed':raise
            # Verify every before/after image before touching either canonical file.
            before={kind:(path.parent/('before.'+kind)).read_bytes() for kind in paths}
            import hashlib
            for kind,target in paths.items():
                expected=record['proof']['request'][kind+'_sha256']
                if hashlib.sha256(before[kind]).hexdigest()!=expected or file_sha256(target) not in {expected,record['after'][kind]}:
                    raise ImageTaskError('Projection has unrelated later writes; only this transaction remains pending')
            for kind,target in paths.items():
                if file_sha256(target)!=record['proof']['request'][kind+'_sha256']:write_bytes_atomic(target,before[kind])
            write_json(path,{**record,'status':'cancelled','reason_for_cancellation':'Current inputs changed; before-images restored without overwriting unrelated work','cancelled_at':utc_now()})


def reproject_image_contracts(job_dir,plugin,request,*,apply=False,proposal_sha256='',decision_id='',reason=''):
    """Rebuild derived contracts with current owners; never interpret old staging permissions."""
    import json,re,hashlib,os
    from .io import file_sha256,read_json,write_json,write_bytes_atomic,utc_now
    from .status import job_run_lock
    from .visual_design_kit import require_current_plan_contract
    from .image_prompt_compiler import compile_image_prompts,IMAGE_PROMPT_ARTIFACT
    job=Path(job_dir).resolve();paths={'tasks':job/'reports'/IMAGE_TASK_ARTIFACT,'prompts':job/'reports'/IMAGE_PROMPT_ARTIFACT}
    if not isinstance(request,dict) or set(request)!={'tasks_sha256','prompts_sha256'} or any(not re.fullmatch('[0-9a-f]{64}',str(v)) for v in request.values()):
        raise ValueError('Explicit original task/prompt SHA values required')
    def prepare(originals,active=None):
        require_current_plan_contract(job,active_projection=active)
        for kind,data in originals.items():
            if hashlib.sha256(data).hexdigest()!=request[kind+'_sha256']:raise ValueError('Original projection bytes changed')
        old=[json.loads(line) for line in originals['tasks'].decode('utf-8-sig').splitlines() if line.strip()]
        tasks=_expected_rows(job,plugin,include_optional=True)
        if len(old)!=len(tasks) or {(r['child'],r['role']) for r in old}!={(r['child'],r['role']) for r in tasks}:
            raise ValueError('Reprojection cannot add/drop frozen roles; resolve the current plan inventory first')
        for task in tasks:validate_image_task(task)
        prompts=compile_image_prompts(job,tasks)
        proof={'request':request,'tasks':input_revision_id(tasks),'prompts':input_revision_id(prompts)}
        after={k:hashlib.sha256(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows).replace('\n',os.linesep).encode('utf-8')).hexdigest()
            for k,rows in (('tasks',tasks),('prompts',prompts))}
        return tasks,prompts,proof,input_revision_id(proof),after
    if not apply:
        rows,_,_,digest,_=prepare({k:p.read_bytes() for k,p in paths.items()})
        return {'status':'preview','proposal_sha256':digest,'role_count':len(rows),
            'ready_count':sum(t['formation_status']=='ready' for t in rows),'requests_sent':0,'quality_changed':False}
    if (not isinstance(decision_id,str) or not 1<=len(decision_id.strip())<=128
            or not isinstance(reason,str) or not 1<=len(reason.strip())<=2000
            or not isinstance(proposal_sha256,str) or not re.fullmatch('[0-9a-f]{64}',proposal_sha256)):
        raise ValueError('Reprojection needs preview SHA, decision ID and reason')
    identity=input_revision_id({'decision_id':decision_id});directory=job/'reports/image_contract_reprojection'/identity;event_path=directory/'decision.json'
    with job_run_lock(job):
        fingerprint=input_revision_id({'request':request,'proposal_sha256':proposal_sha256,'reason':reason})
        prior=read_json(event_path) if event_path.is_file() else None
        if prior:
            if prior.get('request_fingerprint')!=fingerprint:raise ValueError('Projection decision ID reused')
            if prior['status']=='completed':return {**prior['result'],'status':'already_applied','currentness_not_reasserted':True}
            if prior['status']=='cancelled':raise ValueError('Cancelled projection needs a new decision')
        originals={k:(directory/('before.'+k)).read_bytes() if prior else p.read_bytes() for k,p in paths.items()}
        tasks,prompts,proof,digest,after=prepare(originals,identity)
        if digest!=proposal_sha256 or prior and prior['proof']!=proof:raise ValueError('Projection inputs changed')
        for kind,path in paths.items():
            if file_sha256(path) not in {request[kind+'_sha256'],after[kind]}:raise ValueError('Projection cannot overwrite unrelated canonical changes')
        if not prior:
            for kind,data in originals.items():
                backup=directory/('before.'+kind)
                if backup.is_file() and backup.read_bytes()!=data:raise ValueError('Projection backup conflict')
                if not backup.is_file():write_bytes_atomic(backup,data)
            prior={'schema':'image-contract-projection-v1','status':'prepared','proof':proof,'after':after,'request_fingerprint':fingerprint,'decision_id':decision_id,'reason':reason,'prepared_at':utc_now()}
            write_json(event_path,prior)
        if file_sha256(paths['tasks'])!=after['tasks']:write_jsonl(paths['tasks'],tasks)
        if file_sha256(paths['prompts'])!=after['prompts']:compile_image_prompts(job,tasks,write=True)
        if any(file_sha256(p)!=after[k] for k,p in paths.items()):raise ValueError('Committed projection differs from preview')
        result={'status':'applied','requests_sent':0,'quality_changed':False,'role_count':len(tasks),
            'backup_tasks':(directory/'before.tasks').relative_to(job).as_posix(),'backup_prompts':(directory/'before.prompts').relative_to(job).as_posix()}
        write_json(event_path,{**prior,'status':'completed','result':result,'completed_at':utc_now()});return result


def read_image_tasks(job_dir: str | Path, *, category_id: str = "") -> dict[str, Any]:
    require_settled_image_projection(job_dir)
    path = Path(job_dir) / "reports" / IMAGE_TASK_ARTIFACT
    if not path.is_file():
        raise ImageTaskError(f"ImageTask is missing: {path}")
    rows = read_jsonl(path)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        validate_image_task(row)
        if category_id and row["category_id"] != category_id:
            raise ImageTaskError("ImageTask category does not match the active plugin")
        key = (str(row["child"]), str(row["role"]))
        if key in seen:
            raise ImageTaskError(f"ImageTask has a duplicate row: {key[0]}/{key[1]}")
        seen.add(key)
    return {"schema_version": IMAGE_TASK_SCHEMA_VERSION, "task_count": len(rows), "tasks": rows,
            "failures": [_task_failure(row, Path(job_dir)) for row in rows if row['formation_status'] == 'blocked']}


def image_tasks_current(
    job_dir: str | Path, plugin: ProductPlugin, limit: int = 0,
    *, include_optional: bool = False, task_keys: set[tuple[str,str]] | None = None, source_keys=None,
) -> bool:
    del limit
    try:
        actual = read_image_tasks(job_dir, category_id=plugin.category_id)["tasks"]
        expected = _expected_rows(Path(job_dir).resolve(), plugin, include_optional=include_optional,
                                  selected_children={key[0] for key in task_keys} if task_keys is not None else None,
                                  task_keys=task_keys, source_keys=source_keys)
        if task_keys is not None:
            actual = [row for row in actual if (row['child'],row['role']) in task_keys]
            expected = [row for row in expected if (row['child'],row['role']) in task_keys]
        # Candidate reuse is semantic; artifact currentness also refreshes paths and approvals.
        return {
            (row["child"], row["role"]): row for row in actual
        } == {
            (row["child"], row["role"]): row for row in expected
        }
    except Exception:
        return False


def role_prefix(role: Any) -> str:
    value = str(role or "").split("_", 1)[0]
    return value if value in {"main", "scene", "func", "size"} else ""


def validate_task_inventory(tasks: list[dict[str, Any]], expected_children: list[str], required: dict[str, int]) -> None:
    expected = set(map(str, expected_children))
    seen: set[tuple[str, str]] = set()
    for task in tasks:
        key = (str(task.get("child") or ""), str(task.get("role") or ""))
        if key in seen or key[0] not in expected or role_prefix(key[1]) not in required:
            raise ImageTaskError(f"Invalid ImageTask inventory row: {key}")
        seen.add(key)


def executable_coverage(
    tasks: list[dict[str, Any]], expected_children: list[str], required: dict[str, int],
) -> dict[str, Any]:
    children: dict[str, dict[str, Any]] = {}
    for child in map(str, expected_children):
        ready_counts = {
            family: sum(
                1 for task in tasks
                if task.get("child") == child
                and role_prefix(task.get("role")) == family
                and task.get("formation_status") == "ready"
            )
            for family in required
        }
        missing = [family for family, count in required.items() if ready_counts[family] < int(count)]
        children[child] = {
            "status": "ready" if not missing else "partial",
            "ready_counts": ready_counts,
            "missing_required_roles": missing,
        }
    return {
        "status": "ready" if children and all(row["status"] == "ready" for row in children.values()) else "partial",
        "children": children,
    }


def validate_image_task(row: Any) -> None:
    if not isinstance(row, dict) or row.get("schema_version") != IMAGE_TASK_SCHEMA_VERSION:
        raise ImageTaskError("Invalid ImageTask")
    expected = _TASK_READY_FIELDS if row.get("formation_status") == "ready" else _TASK_BLOCKED_FIELDS
    if set(row) != expected:
        raise ImageTaskError(f"ImageTask has unknown or missing fields: {sorted(set(row) ^ expected)}")
    required = (
        "policy_version", "category_id", "child", "role", "role_family",
        "formation_status", "logical_task_id", "input_revision_id", "task_fingerprint",
        "output_dir", "prompt_contract_version",
    )
    missing = [key for key in required if row.get(key) in (None, "", [], {})]
    if missing or row.get("policy_version") != IMAGE_TASK_POLICY_VERSION:
        mismatch = ""
        if row.get("policy_version") != IMAGE_TASK_POLICY_VERSION:
            mismatch = (
                f" policy_version found={row.get('policy_version')!r} "
                f"expected={IMAGE_TASK_POLICY_VERSION!r}; task_fingerprint={row.get('task_fingerprint')!r}"
            )
        raise ImageTaskError(
            f"ImageTask is incomplete: missing={missing};{mismatch} "
            "regenerate the current ImageTask artifact from the active brief contract"
        )
    if row["formation_status"] not in {"ready", "blocked"}:
        raise ImageTaskError("ImageTask formation status is invalid")
    if row['formation_status'] == 'blocked' and (
            row['formation_failure_owner'] not in {'brief', 'observation', 'tool'}
            or not row['formation_reason'] or not row['formation_reason_code']):
        raise ImageTaskError('Blocked ImageTask has no valid failure responsibility')
    if row["formation_status"] == "ready":
        needed = (
            "family_design_id", "family_art_direction", "source_path", "source_sha256",
            "source_intent_revision_id", "generation_references",
            "measurement_authority", "display_copy_contract", "renderable_text_contract",
            "edit_contract", "execution_profile",
        )
        if row.get("role_family") in {"main", "scene"}:
            needed += ("image_direction",)
        absent = [key for key in needed if row.get(key) in (None, "", [], {})]
        if absent:
            raise ImageTaskError(f"Ready ImageTask is incomplete: {absent}")
        references = row["generation_references"]
        try:
            validate_reference_set(references, child=row["child"], edit_base_sha256=row["edit_base_sha256"])
        except ValueError as exc:
            raise ImageTaskError(str(exc)) from exc
        expected = build_renderable_text_contract(row["role_family"], row["measurement_authority"], display_copy=row['display_copy_contract'])
        if row["renderable_text_contract"] != expected:
                raise ImageTaskError("ImageTask renderable text changed after formation")
        edit = row.get("edit_contract")
        if not isinstance(edit, dict) or set(edit) != {"create", "reference_authority", "preserve", "replace", "forbid", "reference_completeness", "product_selection", "design_context_id"}:
            raise ImageTaskError("ImageTask edit contract is not canonical")
        import re
        if not re.fullmatch('[0-9a-f]{64}', str(edit['design_context_id'])) or not isinstance(edit['product_selection'], dict):
            raise ImageTaskError('ImageTask design/selection binding is invalid')
        selection = edit['product_selection']
        if selection:
            if (set(selection) != {'source_id', 'selected', 'excluded'} or selection['source_id'] != references[0]['source_id']
                    or not isinstance(selection['selected'], list) or not isinstance(selection['excluded'], list)
                    or any(not isinstance(v, dict) or not v.get('object_id') for v in selection['selected'] + selection['excluded'])):
                raise ImageTaskError('ImageTask product selection is not bound to its edit base')
            selected = [v['object_id'] for v in selection['selected']]
            excluded = [v['object_id'] for v in selection['excluded']]
            if len(set(selected)) != len(selected) or len(set(excluded)) != len(excluded) or set(selected) & set(excluded):
                raise ImageTaskError('ImageTask selected/excluded product IDs conflict')
            sold = row['product_facts'].get('sold_unit_count')
            if row['role_family'] == 'main' and type(sold) is int and sum(v.get('sale_membership') == 'product' for v in selection['selected']) != sold:
                raise ImageTaskError('Main selection differs from confirmed sold quantity')
    if row.get("task_fingerprint") != _task_fingerprint(row):
        raise ImageTaskError("ImageTask content changed")


def _expected_rows(job: Path, plugin: ProductPlugin, *, include_optional: bool = False, selected_children: set[str] | None = None,
                   task_keys=None, source_keys=None) -> list[dict[str, Any]]:
    family = read_product_family(job)
    product_type = str(family["family"].get("product_type") or plugin.product_type)
    children = {str(row["asin"]): row for row in family["family"]["children"]}
    selected = [asin for asin in read_run_scope(job)['selected_children'] if asin in children
                and (selected_children is None or asin in selected_children)]
    sources_by_child: dict[str, list[dict[str, Any]]] = {}
    for row in selected_task_source_intents(job, plugin=plugin, children=selected_children,source_keys=source_keys):
        sources_by_child.setdefault(str(row["child"]), []).append(row)
    all_kits = read_visual_design_kits(job, plugin=plugin).get("children") or {}
    image_policy = compiled_image_policy(plugin)
    kits = {asin:row for asin,row in all_kits.items() if asin in children}
    rows: list[dict[str, Any]] = []
    for asin in selected:
        design_kit = kits.get(asin)
        if not isinstance(design_kit, dict):
            # The brief/design-kit task is the single authority for this
            # failure.  Do not fan one upstream failure out into a blocked
            # ImageTask for every expected role.
            continue
        specs = task_specs(
            children[asin], sources_by_child.get(asin, []), inventory=design_kit['output_inventory'], include_optional=include_optional,
        )
        current=current_visual_role_bases(job,plugin,asin,design_kit,child_row=children[asin],sources=sources_by_child.get(asin,[]),policy=image_policy)
        for spec in specs:
            if task_keys is not None and (asin,spec['role']) not in task_keys:
                continue
            executable=design_kit
            brief=next(b for b in design_kit['image_briefs'] if b['role']==spec['role'])
            if brief['status']=='ready' and brief['role'] not in current:
                # Preserve the historical acceptance; only this current execution
                # projection is pending. Never revoke an unchanged sibling.
                pending={**brief,'status':'pending','source_sha256':(spec['source'] or {}).get('source_sha256',''),
                    'error':'Current role content dependencies changed; planner confirmation required','failure_owner':'brief'}
                executable={**design_kit,'image_briefs':[pending if b['role']==brief['role'] else b for b in design_kit['image_briefs']]}
            recovered=current.get(brief['role'])
            task_spec=spec
            if recovered:
                historical_specs={r['role']:r for r in task_specs(children[asin],recovered['sources'],
                    inventory=design_kit['output_inventory'],include_optional=include_optional)}
                task_spec=historical_specs.get(spec['role'])
                if task_spec is None or task_spec.get('source') is None:
                    raise ImageTaskError('Recovered role no longer has its sealed source allocation')
                executable={**design_kit,'family_art_direction':recovered['art'],'source_references':recovered['sources'],
                    'product_claims':recovered['claims'],'approved_design_references':recovered['design_references'],
                    'main_image_policy':recovered['main_policy'],'family_design_id':input_revision_id(recovered['art']),
                    'image_briefs':[brief]}
            rows.append(_form_task(
                job=job, plugin=plugin, child=children[asin], spec=task_spec,
                design_kit=executable, image_policy=image_policy,
                product_type=product_type,
            ))
    return sorted(rows, key=lambda row: (row["child"], _role_sort_key(row["role"])))


def _form_task(
    *, job: Path, plugin: ProductPlugin, child: dict[str, Any], spec: dict[str, Any],
    design_kit: dict[str, Any], image_policy: dict[str, Any],
    product_type: str,
) -> dict[str, Any]:
    role = str(spec["role"])
    family = role_prefix(role)
    image_policy=scope_image_policy(image_policy,[family])
    source = spec.get("source")
    source_path = str((source or {}).get("source_path") or "")
    source_sha256 = str((source or {}).get("source_sha256") or "")
    base = {
        "schema_version": IMAGE_TASK_SCHEMA_VERSION,
        "policy_version": IMAGE_TASK_POLICY_VERSION,
        "category_id": plugin.category_id,
        "child": str(child["asin"]),
        "role": role,
        "role_family": family,
        "logical_task_id": logical_task_id("generate", child=str(child["asin"]), role=role),
        "output_dir": f"images/generated/{child['asin']}/{role}",
        "prompt_contract_version": PROMPT_CONTRACT_VERSION,
        "category_image_policy": image_policy,
        "source_path": source_path,
        "source_sha256": source_sha256,
    }
    art_direction = design_kit.get("family_art_direction")
    if not isinstance(art_direction, dict):
        return _blocked(base, "visual design kit has no family_art_direction")
    if not source:
        return _blocked(
            base,
            str(spec.get("reason") or "role evidence is missing"),
            # A missing role source is deterministic for the current source
            # inventory.  Mark only this role blocked; it must not be retried
            # indefinitely or invalidate ready roles in the same child/family.
            reason_code="source_evidence_missing" if spec.get("evidence_pending") else "",
        )
    image_brief = _image_brief(design_kit, source, role)
    if image_brief.get("status") != "ready":
        return _blocked(base, str(image_brief.get("error") or "source brief is pending"),
                        reason_code='source_observation_unresolved' if image_brief.get('failure_owner') == 'observation' else '',
                        failure_owner=image_brief.get('failure_owner', 'brief'))
    try:
        image_direction = image_brief["image_direction"]
        measurement = measurement_authority(role, image_direction, design_kit['source_references'],design_kit['product_claims'])
        story = (
            build_display_copy_contract(
                design_kit['source_references'],
                image_brief or {},
                product_claims=design_kit['product_claims'],
            )
            if family in {"func", "size"} else {
                "mode": "none", "title": "", "labels": [], "bindings": [],
            }
        )
        renderable = build_renderable_text_contract(family, measurement, display_copy=story)
        edit_contract = _edit_contract(family, measurement, image_policy,
            reference_completeness=str((source.get('signals') or {}).get('reference_completeness') or ''))
        from .planning_identity import scoped_design_context
        edit_contract['design_context_id'] = input_revision_id(scoped_design_context(design_kit.get('design_context', {}),[family]))
        references = resolve_edit_references(
            image_brief, design_kit['source_references'], job=job, child=str(child["asin"]),
            design_references=design_kit['approved_design_references'], edit_contract=edit_contract,product_claims=design_kit['product_claims'],
        )
        reference = references[0]
        fields = {
            **base,
            "family_design_id": str(design_kit.get("family_design_id") or design_kit.get("input_revision_id") or ""),
            "family_art_direction": art_direction,
            "source_intent_revision_id": str(source.get("input_revision_id") or ""),
            "source_index": int(source.get("source_index") or 0),
            "source_path": source["source_path"],
            "source_sha256": source["source_sha256"],
            "generation_references": references,
            "edit_base_sha256": reference["sha256"],
            "reference_mode": f"{family}_source_edit",
            "product_facts": task_facts(child, product_type=product_type),
            "measurement_authority": measurement,
            "display_copy_contract": story,
            "renderable_text_contract": renderable,
            "image_direction": image_direction,
            "edit_contract": edit_contract,
            "execution_profile": execution_profile(family, measurement),
            "formation_status": "ready",
            "formation_reason": "",
        }
        fields["task_fingerprint"] = _task_fingerprint(fields)
        fields["input_revision_id"] = fields["task_fingerprint"]
    except Exception as exc:
        return _blocked(base, f"{type(exc).__name__}: {exc}")
    return fields


def _image_brief(
    design_kit: dict[str, Any], source: dict[str, Any], role: str,
) -> dict[str, Any]:
    sha = str(source.get("source_sha256") or "")
    matches = [
        row for row in design_kit.get("image_briefs") or []
        if isinstance(row, dict)
        and str(row.get("role") or "") == role
        and str(row.get("source_sha256") or "") == sha
    ]
    if len(matches) == 1:
        return matches[0]
    raise ImageTaskError("source brief is missing or duplicated")


def _edit_contract(
    family: str, measurement: dict[str, Any], policy: dict[str, Any],
    *, reference_completeness: str = "",
) -> dict[str, Any]:
    label = {"main": "main", "scene": "lifestyle", "func": "function", "size": "size"}[family]
    create = f"Edit attachment 1 directly into one square Amazon US {label} image."
    reference = "The first attachment fixes the depicted product view; auxiliary same-child evidence verifies facts, not permission to reconstruct or combine product viewpoints."
    preserve = [
        "Each selected source product instance's visible geometry, part count, spacing, joins, proportions, pose, state, viewpoint, color, material, finish and surface texture",
        "Product retention takes priority over design goals. Work within attachment 1's existing visible product view; "
        "do not reveal or invent product surfaces hidden by graphics, props or the image boundary. "
        "Keep unevidenced areas outside the depicted product view or covered by redesigned non-product layout or staging, "
        "without concealing required target-visible product parts, connections or measurement endpoints. "
        "Normal non-sold staging may cover product parts when the target state allows it, without changing their structure or hiding the demonstrated feature",
    ]
    preserve.extend('Source-visible ' + str(value) for value in policy.get('structure_invariants', []))
    replace: list[str] = []
    if family == "func":
        preserve.append(
            "The planner-selected existing functional views, including their current visible extent and physical relationships"
        )
    if family in {'func', 'size'}:
        preserve.append("Evidenced mounting faces and connections")
    staging = "; ".join(value['physical_scope'] for value in policy.get("replaceable_staging") or [])
    if family == "main":
        if policy.get("main_image_policy") == "white_background":
            replace.append("Replace external environment and source graphics with a uniform pure-white canvas; keep the complete sold product unmistakable")
        else:
            replace.append(
                "Redesign non-sold surroundings and staging: " + staging
            )
    elif family == "scene":
        replace.append(
            "Redesign non-sold surroundings and staging: " + staging
        )
    elif family == "func":
        replace.append(
            "Redesign function text, callouts and permitted non-product surroundings around the photographed product"
        )
    elif family == 'size':
        replace.append('Design declared specification labels and schematic dimension arrows on visible product extents; not calibrated measurements, no rulers, hidden endpoints or pixel-derived values'
            if measurement.get('annotation_mode')=='declared_diagram' else
            'Design standalone declared specification text around the unchanged product photo; no dimension arrows, calibrated endpoints, rulers or inferred pixel measurements'
            if measurement.get('mode')=='product_statement' else
            'Redesign dimension labels, lines and typography around the photographed product; retain the measured objects, quantities and physical endpoint associations')
    replace.append("Use planned non-sold components, including surroundings seen through product gaps and reflections; retain product surfaces and necessary functional demonstrations, not source decor; " + (
        "remove people and reflected people" if family == "main" and policy.get("main_image_policy") == "white_background" else
        "Prefer no people or human reflections; remove incidental source families, playing and posing. Only when the target requires a necessary functional demonstration, replace the source person with a visibly different person, appearance and clothing; preserve the required contact/action and product geometry, not the source actor"
    ))
    allowed_props = [str(value) for value in policy.get("allowed_internal_props") or [] if str(value).strip()]
    if allowed_props and family != "size":
        replace.append(
            "Optional non-sold props, only when appropriate to the planned setting and evidenced compartment, "
            "not a required inventory or a room instruction: " + "; ".join(allowed_props)
        )
    role_rules = [
        str(value) for value in (policy.get("role_specific_rules") or {}).get(family) or []
        if str(value).strip()
    ]
    forbid = [*role_rules, *policy.get('forbidden_additions', [])]
    return {
        "create": create,
        "product_selection": {},
        "design_context_id": input_revision_id({'policy': policy}),
        "reference_authority": reference,
        "preserve": list(dict.fromkeys(str(value).strip() for value in preserve if str(value).strip())),
        "replace": list(dict.fromkeys(str(value).strip() for value in replace if str(value).strip())),
        "forbid": list(dict.fromkeys(str(value).strip() for value in forbid if str(value).strip())),
        "reference_completeness": (
            "located_measurement_views"
            if family == 'size' and measurement.get('mode')=='source_image'
            else 'declared_product_statements' if measurement.get('mode')=='product_statement'
            else reference_completeness or 'partial_feature_view'
        ),
    }


def _blocked(base: dict[str, Any], reason: str, *, reason_code: str = "", failure_owner: str = 'brief') -> dict[str, Any]:
    row = {
        **base, "formation_status": "blocked", "formation_reason": reason,
        "formation_reason_code": reason_code or "deterministic_block",
        "formation_failure_owner": failure_owner,
    }
    row["task_fingerprint"] = _task_fingerprint(row)
    row["input_revision_id"] = row["task_fingerprint"]
    return row


def _task_fingerprint(row: dict[str, Any]) -> str:
    """Bind the actual compiled brief, reference pixels and factual execution inputs."""
    projection = {key: row.get(key) for key in ('category_id', 'child', 'role', 'role_family',
        'formation_status', 'policy_version', 'prompt_contract_version', 'execution_profile')}
    if row.get('formation_status') == 'ready':
        projection['compiled_brief'] = compile_task_prompt(task=row)
        projection['product_facts'] = row['product_facts']
        projection['design_context_id'] = row['edit_contract']['design_context_id']
        projection['product_selection'] = row['edit_contract']['product_selection']
        projection['generation_references'] = [reference_semantics(ref, execution=True) for ref in row['generation_references']]
        projection['measurements'] = [{key: value for key, value in measurement.items() if key != 'confidence'}
                                      for measurement in row['measurement_authority'].get('measurement_groups', [])]
    else:
        projection.update({key: row.get(key) for key in ('formation_reason', 'formation_reason_code', 'formation_failure_owner', 'source_sha256')})
    return input_revision_id(projection)


def _task_failure(row: dict[str, Any], job: Path) -> dict[str, Any]:
    from .visual_design_kit import brief_recovery
    recovery = brief_recovery(job, row['child'], row['role'], row['formation_failure_owner'])
    return {
        "task": {
            "logical_task_id": logical_task_id("brief", child=row["child"], role=row["role"]),
            "input_revision_id": row["input_revision_id"], "child": row["child"], "role": row["role"],
            **{k:v for k,v in recovery.items() if k != 'task_status'},
        },
        "failure_owner": "classify" if row.get('formation_reason_code') in {'source_evidence_missing', 'source_observation_unresolved'} else row['formation_failure_owner'],
        "task_status": recovery['task_status'],
        "error": row.get("formation_reason") or "image task blocked",
    }


def _role_sort_key(role: str) -> tuple[int, str]:
    return ({"main": 0, "scene": 1, "func": 2, "size": 3}.get(role_prefix(role), 9), role)
