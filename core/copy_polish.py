from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .copy_writer import (
    BULLET_AUDIT_MAX_CHARS,
    BULLET_MODEL_MAX_CHARS,
    DESCRIPTION_MAX_CHARS,
    ITEM_HIGHLIGHT_MAX_COUNT,
    ITEM_HIGHLIGHT_MAX_WORDS,
    ITEM_HIGHLIGHT_MIN_COUNT,
    ITEM_HIGHLIGHT_SEPARATOR,
    ITEM_HIGHLIGHT_TOTAL_LIMIT_CHARS,
    TITLE_MAX_CHARS,
    CopyWriterError,
    _normalize_item_highlights,
    copy_request_identity,
    listing_copy_request_fingerprint,
    configured as copy_provider_configured,
    load_copy_writer_config,
    rewrite_listing_copy,
)
from .io import file_sha256, read_json, write_json
from .job import load_job
from .paths import FACTORY_ROOT
from .plugin import ProductPlugin
from .product_family import read_product_family
from .status import input_revision_id, logical_task_id
from .template_runtime import child_sku, load_template_env, normalize_template_mode


COPY_SCHEMA_VERSION = "copy-v1"
COPY_ARTIFACT = "copy_v1.json"
COPY_GROUP_POLICY_VERSION = "copy-group-v5-retryable-ai-output"
COPY_VALIDATION_POLICY_VERSION = "copy-validation-v10-parent-highlight-contract"
PARENT_COPY_KEY = "__parent__"
COPY_IGNORED_FACT_KEYS = {"fabric_type"}


class CopyPolishError(RuntimeError):
    pass


def run_copy_polish(
    *,
    job_dir: str | Path,
    plugin: ProductPlugin,
    config_path: str = "",
    limit: int = 0,
    mode: str = "",
    retry_blocked: bool = False,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    job_path = Path(job_dir)
    job = load_job(job_path)
    env = load_template_env(
        str(FACTORY_ROOT / "config.env"),
        str(FACTORY_ROOT / "config.local.env"),
        config_path,
        str(job.get("config_path") or ""),
    )
    resolved_mode = normalize_template_mode(mode or env.get("AMAZON_FACTORY_TEMPLATE_MODE") or "draft")
    family_path = job_path / "source" / "product_family_v3.json"
    family = read_product_family(family_path)
    children = _children(family, limit=limit, job_dir=job_path)
    if not copy_provider_configured(env):
        raise CopyPolishError("CopyV1 requires a configured AI copy provider")
    request_fingerprint = copy_request_fingerprint(
        env,
        mode=resolved_mode,
        children=children,
        plugin=plugin,
        job=job,
    )
    current = _current_artifact(
        job_path,
        fingerprint=request_fingerprint,
        children=children,
        job=job,
    )
    if current is not None:
        return current
    # Terminal copy failures are not retried implicitly.  An operator must
    # explicitly request a retry so a resume cannot burn tokens on the same
    # deterministic input revision.
    previous_failures = {} if retry_blocked else _previous_blocked_failures(job_path)

    groups = _copy_groups(children)
    rows: dict[str, dict[str, Any]] = {}
    child_map: dict[str, str] = {}
    group_rows: list[dict[str, Any]] = []
    tasks: list[dict[str, str]] = []
    failures: list[dict[str, Any]] = []
    for group_key, members in groups.items():
        source = _group_source(members)
        group_facts = _family_common_specific(members)
        model_request_fingerprint = _model_request_fingerprint(
            env=env, plugin=plugin, job=job, source=source,
            facts=group_facts, row_type="Child",
        )
        group_fingerprint = _group_request_fingerprint(
            env=env,
            plugin=plugin,
            job=job,
            group_key=group_key,
            source=source,
            facts=group_facts,
            row_type="Child",
            model_request_fingerprint=model_request_fingerprint,
        )
        source_asin = str(source.get("asin") or "")
        member_skus = [
            child_sku(job, child, children.index(child) + 1)
            for child in members
        ]
        group_rows.append({
            "group_key": group_key,
            "source_asin": source_asin,
            "children": [str(row.get("asin") or "") for row in members],
            "skus": member_skus,
            "request_fingerprint": group_fingerprint,
            "model_request_fingerprint": model_request_fingerprint,
        })
        prior = [
            previous_failures.get(_task_success(str(member.get("asin") or ""), group_fingerprint)["input_revision_id"])
            for member in members
        ]
        if prior and all(prior):
            failures.extend(dict(row) for row in prior if row)
            continue
        fragment = _load_fragment(job_path, group_fingerprint)
        if fragment is None:
            try:
                fragment = _rewrite_group(
                    env=env,
                    plugin=plugin,
                    job=job,
                    source=source,
                    facts=group_facts,
                    fingerprint=group_fingerprint,
                    row_type="Child",
                    expected_request_fingerprint=model_request_fingerprint,
                    deadline_monotonic=deadline_monotonic,
                )
                _write_fragment(job_path, group_fingerprint, fragment)
            except (CopyWriterError, CopyPolishError) as exc:
                for member in members:
                    asin = str(member.get("asin") or "")
                    failures.append(
                        _task_failure(
                            asin,
                            group_fingerprint,
                            str(exc),
                            retryable=bool(getattr(exc, "retryable", False)),
                        )
                    )
                continue
        for child, sku in zip(members, member_skus):
            asin = str(child.get("asin") or "")
            rows[sku] = {
                **fragment,
                "row_type": "Child",
                "sku": sku,
                "asin": asin,
                "copy_group_key": group_key,
                "copy_group_source_asin": source_asin,
                "copy_reused_from": "" if asin == source_asin else source_asin,
            }
            child_map[asin] = sku
            tasks.append(_task_success(asin, group_fingerprint))

    parent_fingerprint = ""
    if rows:
        parent_source = _parent_source(children, plugin=plugin, job=job)
        parent_facts = _family_common_specific(children)
        parent_model_fingerprint = _model_request_fingerprint(
            env=env, plugin=plugin, job=job, source=parent_source,
            facts=parent_facts, row_type="Parent",
        )
        parent_fingerprint = _group_request_fingerprint(
            env=env, plugin=plugin, job=job,
            group_key=PARENT_COPY_KEY, source=parent_source, facts=parent_facts,
            row_type="Parent",
            model_request_fingerprint=parent_model_fingerprint,
        )
        parent_revision = _task_success(PARENT_COPY_KEY, parent_fingerprint)["input_revision_id"]
        prior_parent_failure = previous_failures.get(parent_revision)
        parent_fragment = None if prior_parent_failure else _load_fragment(job_path, parent_fingerprint)
        if prior_parent_failure:
            failures.append(dict(prior_parent_failure))
        if parent_fragment is None:
            try:
                if prior_parent_failure:
                    raise CopyPolishError("terminal copy failure already recorded for this input revision")
                parent_fragment = _rewrite_group(
                    env=env, plugin=plugin, job=job, source=parent_source,
                    facts=parent_facts, fingerprint=parent_fingerprint,
                    row_type="Parent",
                    expected_request_fingerprint=parent_model_fingerprint,
                    deadline_monotonic=deadline_monotonic,
                )
                _write_fragment(job_path, parent_fingerprint, parent_fragment)
            except (CopyWriterError, CopyPolishError) as exc:
                parent_fragment = None
                if not prior_parent_failure:
                    failures.append(
                        _task_failure(
                            PARENT_COPY_KEY,
                            parent_fingerprint,
                            str(exc),
                            retryable=bool(getattr(exc, "retryable", False)),
                        )
                    )
        parent_reused_from = ""
    else:
        parent_fragment = None
        parent_reused_from = ""
        parent_model_fingerprint = ""
    if parent_fragment is not None:
        rows[PARENT_COPY_KEY] = {
            **parent_fragment,
            "row_type": "Parent",
            "sku": PARENT_COPY_KEY,
            "asin": str(family.get("family", {}).get("parent_asin") or ""),
            "copy_group_key": PARENT_COPY_KEY,
            "copy_reused_from": parent_reused_from,
        }
        tasks.append(_task_success(PARENT_COPY_KEY, parent_fingerprint))

    payload = {
        "schema_version": COPY_SCHEMA_VERSION,
        "job_id": job_path.name,
        "category_id": plugin.category_id,
        "mode": resolved_mode,
        "product_family_sha256": file_sha256(family_path),
        "copy_request_fingerprint": request_fingerprint,
        "copy_group_policy_version": COPY_GROUP_POLICY_VERSION,
        "constraints": {
            "title_max_chars": TITLE_MAX_CHARS,
            "bullet_count": 5,
            "bullet_target_chars": BULLET_MODEL_MAX_CHARS,
            "bullet_max_chars": BULLET_AUDIT_MAX_CHARS,
            "description_max_chars": DESCRIPTION_MAX_CHARS,
        },
        "groups": group_rows,
        "child_map": child_map,
        "parent_request_fingerprint": parent_fingerprint,
        "parent_model_request_fingerprint": parent_model_fingerprint,
        "rows": rows,
        "failures": failures,
    }
    path = job_path / "reports" / COPY_ARTIFACT
    write_json(path, payload)
    return {
        "output_path": str(path),
        "row_count": len(rows),
        "group_count": len(group_rows),
        "tasks": tasks,
        "failures": failures,
    }


def copy_request_fingerprint(
    env: dict[str, str],
    *,
    mode: str,
    children: list[Any],
    plugin: ProductPlugin,
    job: dict[str, Any],
) -> str:
    del mode
    config = load_copy_writer_config(env)
    payload = {
        "schema": COPY_SCHEMA_VERSION,
        "group_policy": COPY_GROUP_POLICY_VERSION,
        "writer_request": copy_request_identity(config),
        "validation_policy": COPY_VALIDATION_POLICY_VERSION,
        "category": plugin.category_id,
        "brand": str(job.get("brand") or ""),
        "groups": [
            {
                "key": key,
                "request": _group_request_fingerprint(
                    env=env,
                    plugin=plugin,
                    job=job,
                    group_key=key,
                    source=_group_source(members),
                    facts=_family_common_specific(members),
                    row_type="Child",
                ),
            }
            for key, members in _copy_groups([row for row in children if isinstance(row, dict)]).items()
        ],
        "parent": {
            "request": _group_request_fingerprint(
                env=env,
                plugin=plugin,
                job=job,
                group_key=PARENT_COPY_KEY,
                source=_parent_source(children, plugin=plugin, job=job),
                facts=_family_common_specific([row for row in children if isinstance(row, dict)]),
                row_type="Parent",
            ),
        },
    }
    return _fingerprint(payload)


def copy_artifact_current(
    *,
    job_dir: str | Path,
    plugin: ProductPlugin,
    config_path: str = "",
    limit: int = 0,
    mode: str = "",
) -> bool:
    job_path = Path(job_dir)
    family_path = job_path / "source" / "product_family_v3.json"
    if not family_path.is_file():
        return False
    job = load_job(job_path)
    env = load_template_env(
        str(FACTORY_ROOT / "config.env"),
        str(FACTORY_ROOT / "config.local.env"),
        config_path,
        str(job.get("config_path") or ""),
    )
    family = read_product_family(family_path)
    children = _children(family, limit=limit, job_dir=job_path)
    fingerprint = copy_request_fingerprint(
        env,
        mode=normalize_template_mode(mode or "draft"),
        children=children,
        plugin=plugin,
        job=job,
    )
    return _current_artifact(
        job_path,
        fingerprint=fingerprint,
        children=children,
        job=job,
    ) is not None


def read_copy_artifact(job_dir: str | Path, *, require_complete: bool = True) -> dict[str, Any]:
    path = Path(job_dir) / "reports" / COPY_ARTIFACT
    if not path.is_file():
        raise CopyPolishError(f"CopyV1 is missing: {path}")
    data = read_json(path)
    if not isinstance(data, dict) or data.get("schema_version") != COPY_SCHEMA_VERSION:
        raise CopyPolishError("Unsupported CopyV1 artifact")
    if require_complete and data.get("failures"):
        raise CopyPolishError("CopyV1 contains failed copy groups")
    _validate_artifact_provenance(data)
    return data


def _validate_artifact_provenance(data: dict[str, Any]) -> None:
    rows = data.get("rows") if isinstance(data.get("rows"), dict) else {}
    group_requests = {
        str(group.get("group_key") or ""): str(group.get("model_request_fingerprint") or "")
        for group in data.get("groups") or [] if isinstance(group, dict)
    }
    for key, row in rows.items():
        _validate_copy_row(row, row_type="parent" if key == PARENT_COPY_KEY else "child")
        expected = (
            str(data.get("parent_model_request_fingerprint") or "")
            if key == PARENT_COPY_KEY
            else group_requests.get(str(row.get("copy_group_key") or ""), "")
        )
        if not expected or row.get("request_fingerprint") != expected:
            raise CopyPolishError(f"CopyV1 request provenance mismatch: {key}")


def _children(family: dict[str, Any], *, limit: int, job_dir: str | Path | None = None) -> list[dict[str, Any]]:
    rows = family.get("family", {}).get("children") if isinstance(family.get("family"), dict) else None
    if not isinstance(rows, list) or not rows:
        raise CopyPolishError("ProductFamilyV3 requires at least one child")
    children = [row for row in rows if isinstance(row, dict) and str(row.get("asin") or "")]
    if limit > 0:
        return children[:limit]
    if job_dir is not None:
        from .run_scope import read_run_scope

        selected = set(str(asin) for asin in read_run_scope(job_dir)["selected_children"])
        scoped = [row for row in children if str(row.get("asin") or "") in selected]
        if not scoped:
            raise CopyPolishError("RunScopeV5 selected no ProductFamilyV3 children for CopyV1")
        return scoped
    return children


def _copy_groups(children: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for child in children:
        groups.setdefault(_copy_group_key(child), []).append(child)
    return dict(sorted(groups.items()))


def _copy_group_key(child: dict[str, Any], **_: Any) -> str:
    return _fingerprint({"policy": COPY_GROUP_POLICY_VERSION, "source": _source_copy(child)})


def _source_copy(child: dict[str, Any]) -> dict[str, Any]:
    item_highlights = child.get("item_highlights") or child.get("bullets") or child.get("features") or []
    return {
        "title": _normalize_text(child.get("title")),
        "item_highlights": _normalize_item_highlights(item_highlights),
        "description": _normalize_text(child.get("description")),
    }


def _group_source(members: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a copy source with variation-specific tokens removed before AI sees it."""
    if not members:
        return {"title": "", "item_highlights": [], "description": ""}
    source = _source_copy(members[0])
    variation_terms: set[str] = set()
    for member in members:
        variation = member.get("variation_values") if isinstance(member.get("variation_values"), dict) else {}
        normalized = member.get("normalized_facts") if isinstance(member.get("normalized_facts"), dict) else {}
        nested = normalized.get("variation") if isinstance(normalized.get("variation"), dict) else {}
        for value in [*variation.values(), *nested.values()]:
            text = _normalize_text(value)
            if text and len(text) >= 2:
                variation_terms.add(text)
        for key in ("color", "size", "style", "package_quantity", "item_count"):
            text = _normalize_text(normalized.get(key))
            if text and len(text) >= 2:
                variation_terms.add(text)
    def redact(value: str) -> str:
        out = str(value or "")
        for term in sorted(variation_terms, key=len, reverse=True):
            out = re.sub(rf"\b{re.escape(term)}\b", "", out, flags=re.I)
        return re.sub(r"\s+", " ", out).strip(" ,;:-")
    return {
        "title": redact(source.get("title", "")),
        "item_highlights": [redact(value) for value in source.get("item_highlights") or [] if redact(value)],
        "description": redact(source.get("description", "")),
    }


def _parent_source(children: list[Any], *, plugin: ProductPlugin, job: dict[str, Any]) -> dict[str, Any]:
    rows = [row for row in children if isinstance(row, dict)]
    highlight_sets = [set(_source_copy(row)["item_highlights"]) for row in rows]
    common_highlights = [
        value for value in (_source_copy(rows[0])["item_highlights"] if rows else [])
        if all(value in values for values in highlight_sets[1:])
    ]
    descriptions = [_source_copy(row)["description"] for row in rows]
    common_description = descriptions[0] if descriptions and all(value == descriptions[0] for value in descriptions[1:]) else ""
    return {
        "title": plugin.display_name,
        "item_highlights": common_highlights,
        "description": common_description,
        "specs": {},
        "product_specific": {},
    }


def _family_common_specific(children: list[dict[str, Any]], *_: Any) -> dict[str, Any]:
    mappings = [_copy_facts(child) for child in children]
    if not mappings:
        return {}
    common: dict[str, Any] = {}
    for key, value in mappings[0].items():
        if all(key in row and _stable(row[key]) == _stable(value) for row in mappings[1:]):
            common[key] = value
    return common


def _copy_facts(child: dict[str, Any]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    specs = child.get("specs") if isinstance(child.get("specs"), dict) else {}
    for key, value in specs.items():
        normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
        if normalized not in {"source_title", "source_bullets", "source_description", *COPY_IGNORED_FACT_KEYS} and value not in (None, "", [], {}):
            facts[normalized] = value
    specific = child.get("product_specific") if isinstance(child.get("product_specific"), dict) else {}
    for category, values in specific.items():
        if isinstance(values, dict):
            cleaned = {key: value for key, value in values.items() if str(key) not in COPY_IGNORED_FACT_KEYS}
            if cleaned:
                facts[str(category)] = cleaned
    return facts


def _rewrite_group(
    *,
    env: dict[str, str],
    plugin: ProductPlugin,
    job: dict[str, Any],
    source: dict[str, Any],
    facts: dict[str, Any],
    fingerprint: str,
    row_type: str,
    expected_request_fingerprint: str,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    source_copy = _source_copy(source)
    result = rewrite_listing_copy(
        env=env,
        category=plugin.display_name,
        brand=str(job.get("brand") or ""),
        row_type=row_type,
        source_title=source_copy["title"],
        source_bullets=list(source_copy["item_highlights"]),
        source_description=source_copy["description"],
        product_specific=facts,
        deadline_monotonic=deadline_monotonic,
    )
    config = load_copy_writer_config(env)
    if str(result.get("_request_fingerprint") or "") != expected_request_fingerprint:
        raise CopyPolishError("Copy provider request fingerprint does not match the current group request")
    row = {
        "title": _normalize_text(result.get("title")),
        "item_highlights": _normalize_item_highlights(result.get("item_highlights") or []),
        "bullets": [_normalize_text(value) for value in result.get("bullets") or [] if _normalize_text(value)],
        "description": _normalize_text(result.get("description")),
        "evidence": _copy_evidence_catalog(source_copy, facts),
        "provider": str(result.get("_provider") or config.base_url or ""),
        "model": str(result.get("_model") or config.model or ""),
        "request_fingerprint": str(result.get("_request_fingerprint") or fingerprint),
    }
    _validate_copy_row(row, row_type=row_type)
    return row


def _validate_copy_row(row: dict[str, Any], *, row_type: str = "child") -> None:
    title = str(row.get("title") or "")
    bullets = row.get("bullets") if isinstance(row.get("bullets"), list) else []
    item_highlights = row.get("item_highlights") if isinstance(row.get("item_highlights"), list) else []
    description = str(row.get("description") or "")
    if not title or len(title) > TITLE_MAX_CHARS:
        raise CopyPolishError(f"Copy title must be 1..{TITLE_MAX_CHARS} characters")
    if "|" in title:
        raise CopyPolishError("Copy title must not contain vertical bars")
    if re.search(r"(?:&|\band|\bwith|\bfor|\bof|\||[,;:])\s*$", title, flags=re.I):
        raise CopyPolishError("Copy title ends with an incomplete phrase")
    optional_parent_highlights = str(row_type or "").strip().casefold() == "parent" and not item_highlights
    if not optional_parent_highlights and not ITEM_HIGHLIGHT_MIN_COUNT <= len(item_highlights) <= ITEM_HIGHLIGHT_MAX_COUNT:
        raise CopyPolishError(f"Copy item_highlights must contain {ITEM_HIGHLIGHT_MIN_COUNT}-{ITEM_HIGHLIGHT_MAX_COUNT} phrases")
    if not optional_parent_highlights and any(not isinstance(value, str) or not 2 <= len(value.split()) <= ITEM_HIGHLIGHT_MAX_WORDS for value in item_highlights):
        raise CopyPolishError(f"Copy item_highlights must contain 2-{ITEM_HIGHLIGHT_MAX_WORDS} words per phrase")
    if not optional_parent_highlights and len(ITEM_HIGHLIGHT_SEPARATOR.join(item_highlights)) >= ITEM_HIGHLIGHT_TOTAL_LIMIT_CHARS:
        raise CopyPolishError(f"Copy item_highlights joined text must be under {ITEM_HIGHLIGHT_TOTAL_LIMIT_CHARS} characters")
    if not optional_parent_highlights and len({_normalize_text(value).casefold() for value in item_highlights}) != len(item_highlights):
        raise CopyPolishError("Copy item_highlights must be distinct")
    if len(bullets) != 5 or any(not value or len(value) > BULLET_AUDIT_MAX_CHARS for value in bullets):
        raise CopyPolishError(f"Copy requires five bullets of at most {BULLET_AUDIT_MAX_CHARS} characters")
    if len({_normalize_text(value).casefold() for value in bullets}) != 5:
        raise CopyPolishError("Copy bullets must be distinct")
    if not description or len(description) > DESCRIPTION_MAX_CHARS:
        raise CopyPolishError(f"Copy description must be 1..{DESCRIPTION_MAX_CHARS} characters")
    if not str(row.get("provider") or "") or not str(row.get("model") or "") or not str(row.get("request_fingerprint") or ""):
        raise CopyPolishError("Copy provider provenance is incomplete")


def _copy_evidence_catalog(source: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    """Persist source provenance without treating model output as new product facts."""
    return {
        "title": ["source:title"],
        "item_highlights": ["source:item_highlights"],
        "bullets": [
            [f"source:item_highlight:{index + 1}"]
            for index, _ in enumerate(source.get("item_highlights") or [])
        ],
        "description": ["source:description"],
        "facts": [f"spec:{key}" for key in sorted(facts)[:80]],
    }


def _group_request_fingerprint(
    *,
    env: dict[str, str],
    plugin: ProductPlugin,
    job: dict[str, Any],
    group_key: str,
    source: dict[str, Any],
    facts: dict[str, Any],
    row_type: str,
    model_request_fingerprint: str = "",
) -> str:
    config = load_copy_writer_config(env)
    return _fingerprint({
        "schema": COPY_SCHEMA_VERSION,
        "writer_request": copy_request_identity(config),
        "category": plugin.category_id,
        "brand": str(job.get("brand") or ""),
        "group_key": group_key,
        "model_request": model_request_fingerprint or _model_request_fingerprint(
            env=env, plugin=plugin, job=job, source=source,
            facts=facts, row_type=row_type,
        ),
        "common_facts": facts,
    })


def _model_request_fingerprint(
    *,
    env: dict[str, str],
    plugin: ProductPlugin,
    job: dict[str, Any],
    source: dict[str, Any],
    facts: dict[str, Any],
    row_type: str,
) -> str:
    source_copy = _source_copy(source)
    return listing_copy_request_fingerprint(
        env=env,
        category=plugin.display_name,
        brand=str(job.get("brand") or ""),
        row_type=row_type,
        source_title=source_copy["title"],
        source_bullets=list(source_copy["item_highlights"]),
        source_description=source_copy["description"],
        product_specific=facts,
    )


def _current_artifact(
    job_path: Path,
    *,
    fingerprint: str,
    children: list[dict[str, Any]],
    job: dict[str, Any],
) -> dict[str, Any] | None:
    path = job_path / "reports" / COPY_ARTIFACT
    if not path.is_file():
        return None
    try:
        data = read_json(path)
        if (
            data.get("schema_version") != COPY_SCHEMA_VERSION
            or data.get("copy_request_fingerprint") != fingerprint
            or data.get("failures")
        ):
            return None
        rows = data.get("rows") if isinstance(data.get("rows"), dict) else {}
        expected = {child_sku(job, child, index) for index, child in enumerate(children, start=1)} | {PARENT_COPY_KEY}
        if set(rows) != expected:
            return None
        _validate_artifact_provenance(data)
    except Exception:
        return None
    tasks = [
        _task_success(str(asin), str(group.get("request_fingerprint") or ""))
        for group in data.get("groups") or []
        if isinstance(group, dict)
        for asin in group.get("children") or []
    ]
    if PARENT_COPY_KEY in data["rows"]:
        tasks.append(
            _task_success(PARENT_COPY_KEY, str(data.get("parent_request_fingerprint") or ""))
        )
    return {
        "output_path": str(path),
        "row_count": len(data["rows"]),
        "group_count": len(data.get("groups") or []),
        "tasks": tasks,
        "failures": [],
        "reused": True,
    }


def _previous_blocked_failures(job_path: Path) -> dict[str, dict[str, Any]]:
    path = job_path / "reports" / COPY_ARTIFACT
    if not path.is_file():
        return {}
    try:
        data = read_json(path)
    except Exception:
        return {}
    if data.get("schema_version") != COPY_SCHEMA_VERSION:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for failure in data.get("failures") or []:
        task = failure.get("task") if isinstance(failure, dict) and isinstance(failure.get("task"), dict) else {}
        revision = str(task.get("input_revision_id") or "")
        if revision and failure.get("task_status") == "blocked":
            result[revision] = failure
    return result


def _fragment_path(job_path: Path, fingerprint: str) -> Path:
    return job_path / "cache" / "copy_fragments" / f"{fingerprint}.json"


def _load_fragment(job_path: Path, fingerprint: str) -> dict[str, Any] | None:
    path = _fragment_path(job_path, fingerprint)
    if not path.is_file():
        return None
    try:
        row = read_json(path)
        if row.get("schema_version") != COPY_SCHEMA_VERSION or row.get("fingerprint") != fingerprint:
            return None
        copy = row.get("copy") if isinstance(row.get("copy"), dict) else {}
        _validate_copy_row(copy)
        return copy
    except Exception:
        return None


def _write_fragment(job_path: Path, fingerprint: str, row: dict[str, Any]) -> None:
    write_json(_fragment_path(job_path, fingerprint), {
        "schema_version": COPY_SCHEMA_VERSION,
        "fingerprint": fingerprint,
        "copy": row,
    })


def _task_success(key: str, fingerprint: str) -> dict[str, str]:
    return {
        "logical_task_id": logical_task_id("copy", child=key),
        "input_revision_id": input_revision_id({"key": key, "fingerprint": fingerprint, "validation": COPY_VALIDATION_POLICY_VERSION}),
        "child": key,
        "status": "success",
    }


def _task_failure(
    key: str, fingerprint: str, error: str, *, retryable: bool = False
) -> dict[str, Any]:
    task = _task_success(key, fingerprint)
    task["status"] = "retryable" if retryable else "blocked"
    return {
        "task": task,
        "failure_owner": "copy",
        "task_status": "retryable" if retryable else "blocked",
        "error": error,
    }


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_stable(value).encode("utf-8")).hexdigest()
