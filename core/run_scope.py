from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_json, write_json
from .product_family import read_product_family
from .status import input_revision_id


RUN_SCOPE_SCHEMA_VERSION = "run-scope-v5"
RUN_SCOPE_ARTIFACT = "run_scope_v5.json"


class RunScopeError(RuntimeError):
    pass


def ensure_run_scope(
    *, job_dir: str | Path, limit: int = 0, production: bool = False, child_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    job_path = Path(job_dir).resolve()
    reports = job_path / "reports"
    path = reports / RUN_SCOPE_ARTIFACT
    legacy = reports / "run_scope_v4.json"
    if not path.is_file() and legacy.is_file():
        raise RunScopeError("RunScopeV4 is retired; explicitly revalidate the original task scope under RunScopeV5")
    family = read_product_family(job_path)
    if child_ids and (production or limit):
        raise RunScopeError('Explicit child selection cannot be combined with production or limit')
    if path.is_file():
        scope = read_run_scope(job_path, allow_source_arrival=True)
        if child_ids and set(child_ids) != set(scope['selected_children']):
            raise RunScopeError('selected_children differs from the original frozen scope; explicit scope revalidation is required')
        if production and scope.get("mode") != "production":
            raise RunScopeError("mode is debug; production requires explicit full-family revalidation of the original frozen scope")
        by_child = {row['asin']: row for row in family['family']['children']}
        arrivals = {child: _reference_source_indexes(by_child[child]) for child, indexes in scope['selected_sources'].items()
                    if not indexes and child in by_child and _reference_source_indexes(by_child[child])}
        if arrivals:
            scope['selected_sources'].update(arrivals)
            scope['family_inventory_fingerprint'] = input_revision_id(_family_inventory(family, selected_children=set(scope['selected_children'])))
            scope['scope_fingerprint'] = _scope_identity(scope)
            write_json(path, scope)
        return scope
    children = target_children(family)
    if len(child_ids) != len(set(child_ids)) or set(child_ids) - set(children):
        raise RunScopeError('Selected child IDs must be unique members of this product family')
    selected = list(child_ids) if child_ids else children if production or limit <= 0 else children[:limit]
    if not selected:
        raise RunScopeError("RunScopeV5 has no selected children")
    inventory = _family_inventory(family, selected_children=set(selected))
    inventory_fingerprint = input_revision_id(inventory)
    by_child = {row['asin']: row for row in family['family']['children']}
    selected_sources = {child: _reference_source_indexes(by_child.get(child, {})) for child in selected}
    scope = {
        "schema_version": RUN_SCOPE_SCHEMA_VERSION,
        "mode": "production" if production else "debug",
        "selected_children": selected,
        "selected_sources": selected_sources,
        "family_child_count": len(children),
        "family_inventory_fingerprint": inventory_fingerprint,
        "family_complete_required": bool(production),
    }
    scope["scope_fingerprint"] = _scope_identity(scope)
    write_json(path, scope)
    return scope


def promote_run_scope(job_dir: str | Path, *, decision_id: str, reason: str) -> dict[str, Any]:
    """Explicit target expansion in this job; no new order, allowance or fact."""
    from .status import job_run_lock
    from .io import file_sha256
    if not decision_id or not reason.strip():raise RunScopeError('Scope promotion requires an explicit decision and reason')
    job=Path(job_dir).resolve();path=job/'reports'/RUN_SCOPE_ARTIFACT
    journal=job/'reports/scope_promotions'/(input_revision_id(decision_id)+'.json')
    with job_run_lock(job):
        previous=read_json(journal) if journal.is_file() else None
        if previous:
            if previous['reason']!=reason:raise RunScopeError('Scope decision ID reused')
            if previous['status']=='completed':return previous
            if file_sha256(path) not in {previous['before_sha256'],previous['after_sha256']}:
                raise RunScopeError('Scope promotion cannot overwrite unrelated changes')
            target=previous['scope']
        else:
            before=read_run_scope(job);family=read_product_family(job);children=target_children(family)
            by_child={row['asin']:row for row in family['family']['children']}
            target={**before,'mode':'production','family_complete_required':True,'selected_children':children,
                'selected_sources':{child:_reference_source_indexes(by_child.get(child,{})) for child in children},
                'family_child_count':len(children),'family_inventory_fingerprint':input_revision_id(_family_inventory(family))}
            target['scope_fingerprint']=_scope_identity(target)
            from .io import utc_now
            import hashlib,json,os
            after=hashlib.sha256((json.dumps(target,indent=2,ensure_ascii=False)+'\n').replace('\n',os.linesep).encode()).hexdigest()
            previous={'schema':'scope-promotion-v1','decision_id':decision_id,'reason':reason,'status':'prepared',
                      'before_sha256':file_sha256(path),'after_sha256':after,'scope':target,'prepared_at':utc_now()}
            write_json(journal,previous)
        if file_sha256(path)!=previous['after_sha256']:write_json(path,target)
        read_run_scope(job)
        result={**previous,'status':'completed','requests_sent':0,'budget_changed':False}
        write_json(journal,result);return result


def read_run_scope(job_dir: str | Path, *, allow_source_arrival: bool = False) -> dict[str, Any]:
    path = Path(job_dir) / "reports" / RUN_SCOPE_ARTIFACT
    if not path.is_file():
        raise RunScopeError(f"RunScopeV5 is missing: {path}")
    return _validate_scope(read_json(path), read_product_family(job_dir), allow_source_arrival=allow_source_arrival)


def _validate_scope(data, family, *, allow_source_arrival=False):
    if not isinstance(data, dict) or data.get("schema_version") != RUN_SCOPE_SCHEMA_VERSION:
        raise RunScopeError("Unsupported RunScopeV5 schema_version; explicitly revalidate the original task scope")
    fields={'schema_version','mode','selected_children','selected_sources','family_child_count',
            'family_inventory_fingerprint','family_complete_required','scope_fingerprint'}
    if set(data) != fields:
        raise RunScopeError('RunScopeV5 fields differ: missing ' + str(sorted(fields-set(data)))
                            + '; unexpected ' + str(sorted(set(data)-fields)))
    children = data.get("selected_children")
    if (not isinstance(children, list) or not children
            or any(not isinstance(child, str) or not child.strip() or child != child.strip() for child in children)
            or len(children) != len(set(children))):
        raise RunScopeError("RunScopeV5 has invalid selected_children")
    sources = data.get("selected_sources")
    if not isinstance(sources, dict):
        raise RunScopeError("RunScopeV5 has invalid selected_sources")
    if set(children) != set(sources):
        raise RunScopeError("RunScopeV5 selected_sources must match selected_children")
    mode = data.get('mode')
    count = data.get('family_child_count')
    if mode not in {'production', 'debug'} or type(data.get('family_complete_required')) is not bool:
        raise RunScopeError('RunScopeV5 has invalid mode/family_complete_required')
    if data['family_complete_required'] != (mode == 'production'):
        raise RunScopeError('RunScopeV5 family_complete_required contradicts mode')
    if type(count) is not int or count < len(children):
        raise RunScopeError('RunScopeV5 has invalid family_child_count')
    if data.get('scope_fingerprint') != _scope_identity(data):
        raise RunScopeError('RunScopeV5 scope_fingerprint does not match frozen content')
    selected = set(children)
    if mode == 'production':
        targets = target_children(family)
        if selected != set(targets) or count != len(targets):
            raise RunScopeError('Production RunScopeV5 selected_children/family_child_count must cover the full family')
    expected_inventory = input_revision_id(_family_inventory(family, selected_children=selected))
    previous_inventory = input_revision_id(_family_inventory(family, selected_children=selected,
        empty_children={child for child, indexes in sources.items() if not indexes}))
    if data.get('family_inventory_fingerprint') != expected_inventory and not (
        allow_source_arrival and data.get('family_inventory_fingerprint') == previous_inventory
    ):
        raise RunScopeError(
            "RunScopeV5 family_inventory_fingerprint no longer matches ProductFamily membership/reference inventory; explicitly revalidate the original frozen scope"
        )
    family_by_asin = {
        str(row.get("asin") or ""): row
        for row in family.get("family", {}).get("children") or []
        if isinstance(row, dict)
    }
    for child in selected:
        row = family_by_asin.get(child)
        if row is None and (child not in target_children(family) or sources.get(child) != []):
            raise RunScopeError(f"RunScopeV5 child is no longer present: {child}")
        indexes = sources.get(child)
        if (not isinstance(indexes, list) or any(type(value) is not int for value in indexes)
                or len(indexes) != len(set(indexes))):
            raise RunScopeError(f"RunScopeV5 selected_sources is invalid for {child}")
        available = set(_reference_source_indexes(row or {}))
        requested = set(indexes)
        if not requested.issubset(available):
            raise RunScopeError(f"RunScopeV5 references a missing source index for {child}")
        if mode == 'production' and requested != available and not (allow_source_arrival and not requested):
            raise RunScopeError(f'Production RunScopeV5 selected_sources must cover all indexes for {child}: missing {sorted(available-requested)}')
    return data


def reconcile_verified_inventory(job: Path, before: dict, after: dict) -> None:
    """Carry an existing, validated selection across local reinterpretation of its raw evidence."""
    path = job / 'reports' / RUN_SCOPE_ARTIFACT
    old_targets, new_targets = target_children(before), target_children(after)
    if not path.is_file() or (set(old_targets) == set(new_targets) and
                              _family_inventory(before)['parent_asin'] == _family_inventory(after)['parent_asin']):
        return
    if not set(old_targets).issubset(new_targets):
        raise RunScopeError('Source reconciliation cannot remove frozen members')
    scope = read_json(path)
    try:
        _validate_scope(scope, before, allow_source_arrival=True)
    except RunScopeError:
        # A restart may see the updated scope before the atomic family write.
        _validate_scope(scope, after)
        return
    selected = list(scope['selected_children'])
    sources = dict(scope['selected_sources'])
    before_rows = {c['asin']:c for c in before['family']['children']}
    by_child = {c['asin']:c for c in after['family']['children']}
    for child, indexes in sources.items():
        original = _reference_source_inventory(before_rows.get(child, {}))
        current = _reference_source_inventory(by_child.get(child, {}))
        if any(i >= len(current) or original[i] != current[i] for i in indexes):
            raise RunScopeError('Source reconciliation cannot replace a frozen reference image')
    if scope['mode'] == 'production':
        selected.extend(child for child in new_targets if child not in selected)
        sources = {child:_reference_source_indexes(by_child.get(child,{})) for child in selected}
    target = {**scope,'selected_children':selected,'selected_sources':sources,'family_child_count':len(new_targets),
              'family_inventory_fingerprint':input_revision_id(_family_inventory(after,selected_children=set(selected)))}
    target['scope_fingerprint'] = _scope_identity(target)
    _validate_scope(target, after)
    write_json(path, target)


def _scope_identity(scope: dict[str, Any]) -> str:
    return input_revision_id({
        'schema': scope['schema_version'], 'mode': scope['mode'],
        'selected_children': scope['selected_children'], 'selected_sources': scope['selected_sources'],
        'family_child_count': scope['family_child_count'],
        'family_inventory_fingerprint': scope.get('family_inventory_fingerprint'),
    })


def execution_children(job_dir: str | Path, work_children=()) -> set[str]:
    """An invocation subset of the frozen goal, never a replacement RunScope."""
    goal=set(read_run_scope(job_dir)['selected_children'])
    if not work_children:return goal
    if len(work_children)!=len(set(work_children)) or set(work_children)-goal:
        raise RunScopeError('Work unit must select unique members of the original target')
    return set(work_children)


def scoped_children(job_dir: str | Path) -> list[str]:
    return [str(child) for child in read_run_scope(job_dir)["selected_children"]]


def scoped_child_set(job_dir: str | Path) -> set[str]:
    return set(scoped_children(job_dir))


def scoped_family_children(family: dict[str, Any], job_dir: str | Path) -> list[dict[str, Any]]:
    selected = scoped_child_set(job_dir)
    return [row for row in family["family"]["children"] if str(row.get("asin") or "") in selected]


def row_in_scope(job_dir: str | Path, row: dict[str, Any], *, scope: dict[str, Any] | None = None) -> bool:
    scope = read_run_scope(job_dir) if scope is None else scope
    child = str(row.get("child") or "")
    if child not in set(str(value) for value in scope["selected_children"]):
        return False
    indexes = scope.get("selected_sources", {}).get(child)
    if not indexes:
        return False
    index = row.get("index", row.get("source_index"))
    return type(index) is int and index in indexes


def scope_input_revision(job_dir: str | Path) -> str:
    scope = read_run_scope(job_dir)
    return input_revision_id({
        "schema": scope.get("schema_version"),
        "fingerprint": scope.get("scope_fingerprint"),
        "selected_children": scope.get("selected_children"),
        "selected_sources": scope.get("selected_sources"),
        "mode": scope.get("mode"),
    })


def _reference_source_indexes(child: dict[str, Any]) -> list[int]:
    rows = child.get("reference_images") if isinstance(child.get("reference_images"), list) else []
    return list(range(len(rows)))


def target_children(family: dict[str, Any]) -> list[str]:
    """Confirmed target membership includes fetch failures, never invented facts."""
    import re
    ready = [str(row['asin']) for row in family['family']['children']]
    errors=family.get('source',{}).get('child_fetch_errors',[])
    if not isinstance(errors,list) or any(not isinstance(row,dict) for row in errors):
        raise RunScopeError('Invalid child_fetch_errors: target identities must be explicit')
    failed = [str(row.get('asin') or '') for row in errors]
    targets = ready + failed
    expected = family.get('source', {}).get('expected_child_count', len(targets))
    if len(set(targets)) != len(targets) or expected != len(targets) or any(not re.fullmatch('[A-Z0-9]{10}', child) for child in failed):
        raise RunScopeError('Family target membership is ambiguous; do not claim a complete production scope')
    return targets


def _family_inventory(family: dict[str, Any], *, selected_children: set[str] | None = None, empty_children=()) -> dict[str, Any]:
    by_child = {row['asin']: row for row in family['family']['children']}
    return {
        'parent_asin': str(family['family'].get('parent_asin') or family.get('source',{}).get('seed_asin') or ''),
        'children': [{'asin': child, 'reference_sources': [] if child in empty_children else
                      _reference_source_inventory(by_child.get(child, {}))}
                     for child in sorted(target_children(family)) if selected_children is None or child in selected_children],
    }


def _reference_source_inventory(child: dict[str, Any]) -> list[str]:
    rows = child.get("reference_images") if isinstance(child.get("reference_images"), list) else []
    inventory: list[str] = []
    for item in rows:
        if isinstance(item, dict):
            inventory.append(str(item.get("url") or item.get("media_location") or ""))
        else:
            inventory.append(str(item or ""))
    return inventory
