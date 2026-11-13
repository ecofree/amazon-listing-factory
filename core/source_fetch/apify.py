from __future__ import annotations

import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import cache
from pathlib import Path
from typing import Any

from ..io import file_sha256, load_env, read_json, safe_path_component, utc_now, write_json
from ..price import normalize_price_value
from ..job import load_job
from ..paths import FACTORY_ROOT, resolve_job_owned_path
from ..plugin import ProductPlugin
from ..product_family import PRODUCT_FAMILY_POLICY_VERSION, fact_key, whole_part_counts, read_product_family, identity_values_equal
from ..schema import validate_data
from ..text_evidence import clean_evidence_text, extract_measurements, has_bad_encoding
from .apify_client import ApifyClient, returned_asin
from products.generic_extractors import explicit_item_counts, explicit_package_quantity, theme_from_dimensions


def env_any(values: dict[str, str], *names: str, required: bool = False, default: str = "") -> str:
    for name in names:
        value = values.get(name)
        if value:
            return value
    if required:
        raise RuntimeError(f"Missing environment variable; expected one of: {', '.join(names)}")
    return default


def _apify_tokens_from_env(values: dict[str, str], *, required: bool = False) -> list[str]:
    for name in ("APIFY_TOKENS", "APIFY_TOKEN"):
        raw_value = values.get(name, "")
        tokens = [token.strip() for token in raw_value.split(",") if token.strip()]
        if tokens:
            return tokens
    if required:
        raise RuntimeError("Missing environment variable; expected APIFY_TOKENS or APIFY_TOKEN")
    return []


@cache
def _interpretation_files():
    return {name:file_sha256(FACTORY_ROOT/name) for name in (
        'products/generic_extractors.py', 'core/plugin.py', 'core/product_family.py',
        'core/text_evidence.py', 'core/price.py', 'core/source_fetch/apify.py')}


def fetch_identity(job: dict[str, Any], plugin: ProductPlugin) -> dict[str, str]:
    from ..status import input_revision_id
    return {'seed_asin': str(job['seed_asin']).upper(), 'marketplace': str(job.get('marketplace') or 'US').upper(),
            'category_id': plugin.category_id, 'extractor_sha256': input_revision_id(
                {'mapping': plugin.load_extractors().contract, 'rules': _interpretation_files()})}


def raw_source_directory(job_path: Path, marketplace: str) -> Path:
    """Canonical source location; raw_dir metadata is not an executable path selector."""
    market=str(marketplace or 'US').upper()
    if not re.fullmatch('[A-Z]{2}',market):raise ValueError('Invalid raw-source marketplace')
    return resolve_job_owned_path(job_path,Path('source/apify_raw')/market)


class FamilySelectionExceeded(ValueError):
    """Terminal selection result for this candidate; its seed response remains reusable."""


def check_family_size(job: dict, member_count: int) -> None:
    limit = job.get('max_family_members')
    if limit is not None and member_count > limit:
        raise FamilySelectionExceeded(f"{job['seed_asin']}: {member_count} confirmed family members exceed selection limit {limit}")


def family_current(job_path: Path, plugin: ProductPlugin, *, include_metadata: bool = True, require_complete: bool = True) -> bool:
    """One source-currentness contract for controller and fetch reuse; missing is not corrupt."""
    if not (job_path / 'source/product_family_v3.json').is_file():
        return False
    family = read_product_family(job_path, allow_metadata_stale=True)
    job = load_job(job_path)
    identity = fetch_identity(job, plugin)
    stored = family['source']['request_identity']
    if any(stored[key] != identity[key] for key in ('seed_asin', 'marketplace', 'category_id')):
        raise RuntimeError('Fetch source identity changed; explicit source reconciliation is required')
    if stored['extractor_sha256'] != identity['extractor_sha256']:
        return False
    if family['category_id'] != plugin.category_id or require_complete and family['source']['child_fetch_errors']:
        return False
    raw_dir = raw_source_directory(job_path, identity['marketplace'])
    expected = {family['source']['seed_asin'], *(c['asin'] for c in family['family']['children'])}
    if set(family['source']['raw_sha256']) != expected:
        return False
    for asin, sha in family['source']['raw_sha256'].items():
        path = raw_dir / f'{asin}.json'
        if not path.is_file() or file_sha256(path) != sha or returned_asin(read_json(path)) != asin:
            return False
    check_family_size(job, family['source']['expected_child_count'])
    return not include_metadata or all(family['family'][key] == job[key] for key in ('brand', 'sku_prefix'))


def fetch_family(
    *,
    job_dir: str | Path,
    plugin: ProductPlugin,
    config_path: str = "",
    limit_children: int = 0,
    work_children: tuple[str, ...] = (),
    refresh: bool = False,
    revalidate: bool = False,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    job_path = Path(job_dir)
    job = load_job(job_path)
    if revalidate and refresh:
        raise ValueError('Local source revalidation and remote refresh are different operations')
    path = job_path / 'source/product_family_v3.json'
    prior = read_json(path) if path.is_file() and not refresh else None
    identity = fetch_identity(job, plugin)
    saved = prior if prior and (revalidate or prior['source']['request_identity']['extractor_sha256'] != identity['extractor_sha256']) else None
    if len(work_children)!=len(set(work_children)):raise ValueError('Source work selection must be unique')
    if work_children and (limit_children or refresh or revalidate):
        raise ValueError('A work selection cannot also refresh/revalidate or truncate source execution')
    base=None
    if (work_children or limit_children) and prior and saved is None:
        if not family_current(job_path,plugin,include_metadata=False,require_complete=False):
            raise ValueError('Existing source facts/provenance changed; revalidate before continuing a work unit')
        base=read_product_family(job_path,allow_metadata_stale=True)
        if work_children and set(work_children)<={row['asin'] for row in base['family']['children']}:
            base['family'].update({key:job[key] for key in ('brand','sku_prefix')})
            write_json(path,base);return base
    raw_dir = raw_source_directory(job_path, identity['marketplace'])
    if saved is not None:
        # The saved family supplies provenance/inventory only; facts are rebuilt from original bytes.
        if not isinstance(saved, dict):
            raise ValueError('Saved source revalidation envelope is invalid; preserve the original family')
        source = saved.get('source')
        family = saved.get('family') if isinstance(saved, dict) else None
        children = family.get('children') if isinstance(family, dict) else None
        raw_hashes = source.get('raw_sha256') if isinstance(source, dict) else None
        if (saved.get('protocol_version') != '3.0' or saved.get('category_id') != plugin.category_id
                or not isinstance(source, dict) or source.get('type') != 'apify'
                or not isinstance(family, dict) or not isinstance(children, list) or not children
                or not isinstance(raw_hashes, dict)):
            raise ValueError('Saved source revalidation envelope is incomplete; preserve the original family')
        child_asins = [str(child.get('asin') or '').strip().upper()
                       for child in children if isinstance(child, dict)]
        errors=source.get('child_fetch_errors',[])
        failed_asins=[str(row.get('asin') or '') for row in errors if isinstance(row,dict)] if isinstance(errors,list) else []
        if (len(child_asins) != len(children) or len(set(child_asins)) != len(child_asins)
                or not isinstance(errors,list) or len(failed_asins)!=len(errors) or len(set(failed_asins))!=len(failed_asins)
                or set(failed_asins)&set(child_asins)
                or any(not re.fullmatch(r'[A-Z0-9]{10}', asin) for asin in child_asins+failed_asins)
                or source.get('expected_child_count') != len(children)+len(failed_asins)
                or not isinstance(source.get('request_identity'), dict)):
            raise ValueError('Saved source revalidation inventory is invalid; preserve the original family')
        expected = {job['seed_asin'], *(c['asin'] for c in saved['family']['children'])}
        # Explicit local revalidation applies the current extractor to the same
        # verified source bytes; a mapping revision is its purpose, not a refetch.
        if (any(saved['source']['request_identity'].get(key) != identity[key]
                for key in ('seed_asin', 'marketplace', 'category_id'))
                or saved['source']['seed_asin'] != job['seed_asin'] or saved['category_id'] != plugin.category_id
                or saved['family']['marketplace'] != str(job.get('marketplace') or 'US').upper()
                or set(raw_hashes) != expected
                or any(not re.fullmatch(r'[0-9a-f]{64}', str(sha)) for sha in raw_hashes.values())):
            raise ValueError('Saved source identity/inventory differs from the requested revalidation')
        for asin, sha in raw_hashes.items():
            if not (raw_dir / f'{asin}.json').is_file() or file_sha256(raw_dir / f'{asin}.json') != sha:
                raise ValueError(f'Saved raw source bytes changed or are missing: {asin}')
    elif not refresh and family_current(job_path, plugin, include_metadata=False):
        family = read_product_family(job_path, allow_metadata_stale=True)
        if any(family['family'][key] != job[key] for key in ('brand', 'sku_prefix')):
            family['family'].update({key: job[key] for key in ('brand', 'sku_prefix')})
            write_json(job_path / 'source/product_family_v3.json', family)
        return family
    config = config_path or job.get("config_path") or _default_config_path()
    # Process-level secrets/config override file defaults; this matches the
    # production controller and prevents a stale local env from replacing a
    # deliberately injected runtime credential.
    env = {} if saved is not None else {**load_env(config), **os.environ}
    client = None if saved is not None else ApifyClient(
        tokens=_apify_tokens_from_env(env, required=True),
        actor_id=env_any(env, "APIFY_ACTOR_ID", required=True),
        marketplace=job.get("marketplace") or env_any(env, "AMAZON_MARKETPLACE", default="US"),
        deadline_monotonic=deadline_monotonic,
        receipt_root=job_path / 'source/apify_requests', refresh_received=refresh,
    )
    extractors = plugin.load_extractors()
    seed_asin = str(job["seed_asin"]).strip().upper()
    raw_dir.mkdir(parents=True, exist_ok=True)
    seed_raw = _fetch_validated_raw(
        client, raw_dir, seed_asin, refresh, extractors=extractors, require_variations=True
    )
    variation = extractors.extract_variations(seed_raw, seed_asin)
    # A lone secondary ID cannot enroll an unrelated listing. A child's own
    # cached response can corroborate membership without another fetch.
    unresolved = []
    for asin in variation.get('unconfirmed_variant_asins', []):
        if not re.fullmatch(r'[A-Z0-9]{10}', asin):
            continue
        path_to_raw = raw_dir / f'{safe_path_component(asin)}.json'
        try:
            child_raw = read_json(path_to_raw) if path_to_raw.is_file() else {}
        except (OSError, ValueError):
            unresolved.append(asin)
            continue
        if returned_asin(child_raw) != asin:
            unresolved.append(asin)
            continue
        child_family = extractors.extract_variations(child_raw, asin)
        if variation['parent_asin'] and child_family['parent_asin']:
            if child_family['parent_asin'] != variation['parent_asin']:
                continue
        elif seed_asin not in {row['asin'] for row in child_family['variants']}:
            unresolved.append(asin)
            continue
        variation['variants'].append(next((r for r in child_family['variants'] if r['asin'] == asin), {'asin':asin}))
    variation['unconfirmed_variant_asins'] = unresolved
    variants = _dedupe_variants(
        variation.get("variants", []),
        seed_asin,
        parent_asin=variation['parent_asin'],
    )
    check_family_size(job, len(variants))
    if saved is not None:
        frozen_child_order = [c['asin'] for c in saved['family']['children']]
        frozen_children = set(frozen_child_order)
        variants_by_asin = {str(v.get('asin') or ''): v for v in variants}
        if not frozen_children.issubset(variants_by_asin):
            raise ValueError('Saved raw data must revalidate the complete original child inventory')
        variants = [variants_by_asin[a] for a in frozen_child_order] + [v for v in variants if v['asin'] not in frozen_children]
    if len(work_children)!=len(set(work_children)) or set(work_children)-{v['asin'] for v in variants}:
        raise ValueError('Source work selection must name unique confirmed target members')
    preferred=sorted(variants,key=lambda row:row['asin']!=seed_asin) if limit_children else variants
    selected=set(work_children) if work_children else {v['asin'] for v in (preferred[:limit_children] if limit_children else variants)}
    if saved is not None:
        # Existing failed/unknown requests retain their original receipts; newly proven members
        # can use a locally available source, or remain deferred to their own work unit.
        selected = frozen_children | {v['asin'] for v in variants if v['asin'] not in failed_asins
                                      and (raw_dir / f"{v['asin']}.json").is_file()}

    v3_by_index: dict[int, dict[str, Any]] = {}
    errors: list[dict[str, str]] = list(saved['source']['child_fetch_errors']) if saved is not None else []
    carried={row['asin']:row for row in (base or {}).get('family',{}).get('children',[])}
    previous_errors={row['asin']:row for row in (base or {}).get('source',{}).get('child_fetch_errors',[])}
    for index,variant in enumerate(variants):
        asin=variant['asin']
        if asin in selected or saved is not None and asin in failed_asins:continue
        if asin in carried:v3_by_index[index]=carried[asin]
        else:errors.append(previous_errors.get(asin,{'asin':asin,'status':'deferred','error':'Work-unit execution deferred; no child fetch requested'}))

    observed_parents = {variation['parent_asin']} if variation['parent_asin'] else set()
    def fetch_variant(index: int, variant: dict[str, Any]) -> tuple[int, dict[str, Any], str]:
        asin = variant["asin"]
        if asin == seed_asin:
            raw = seed_raw
        else:
            raw = _fetch_validated_raw(
                client, raw_dir, asin, refresh, extractors=extractors, require_variations=False
            )
        child_variations = extractors.extract_variations(raw, asin)
        if variation['parent_asin'] and child_variations['parent_asin'] and variation['parent_asin'] != child_variations['parent_asin']:
            raise ValueError('Child source identifies a different variation parent')
        specs = extractors.extract_specs(raw)
        images = extractors.image_urls(raw)
        specific = extractors.product_specific(raw) if hasattr(extractors, "product_specific") else specs
        sold_unit_count, sold_unit_count_source, sold_unit_conflict = _source_sold_unit_count(raw, specs, specific)
        explicit_package_count = explicit_package_quantity(raw)
        package_quantity = explicit_package_count
        package_quantity_source = (
            "apify_explicit_package_quantity"
            if explicit_package_count is not None
            else "apify_missing_package_quantity"
        )
        for facts in (specs, specific):
            facts.pop("number_of_items", None)
            facts.pop("item_package_quantity", None)
        variation_values = _variation_values(variant)
        own = next((row for row in child_variations.get("variants") or []
                    if isinstance(row, dict) and str(row.get("asin") or "") == asin), {})
        variation_values.update(_variation_values(own))
        variation_missing = not variation_values
        description = _source_description(raw)
        title = _source_title(raw)
        bullets = _source_bullets(raw)
        review_summary = _source_review_summary(raw)
        offer = _source_offer(raw, marketplace=str(job.get('marketplace') or 'US'))
        normalized_facts = _normalized_child_facts(
            variation_values=variation_values,
            specs=specs,
            specific=specific,
            offer=offer,
            sold_unit_count=sold_unit_count,
            package_quantity=package_quantity,
            title=title,
            bullets=bullets,
            description=description,
        )
        if sold_unit_conflict:
            normalized_facts["sold_unit_count_status"] = "conflicted"
            normalized_facts["sold_unit_count_candidates"] = sold_unit_conflict
        elif sold_unit_count_source in {'apify_invalid_pack_count','apify_missing_pack_count'}:
            normalized_facts['sold_unit_count_status'] = 'unconfirmed'
        v3_child = (
            {
                "asin": asin,
                "variation_values": variation_values,
                "title": title,
                "bullets": bullets,
                "review_summary": review_summary,
                "description": description,
                "specs": specs,
                "normalized_facts": normalized_facts,
                **({"offer": offer} if offer else {}),
                "sold_unit_count": sold_unit_count,
                "sold_unit_count_source": sold_unit_count_source,
                **({"sold_unit_count_status": "conflicted", "sold_unit_count_candidates": sold_unit_conflict} if sold_unit_conflict else {}),
                "package_quantity": package_quantity,
                "package_quantity_source": package_quantity_source,
                "reference_images": [{"url": url, "source": "apify"} for url in images],
                "risk_flags": ["variation_values_missing"] if variation_missing else [],
                "product_specific": {plugin.category_id: specific},
                "status": "ok",
            }
        )
        return index, v3_child, child_variations['parent_asin']

    indexed_variants = [(index,variant) for index,variant in enumerate(variants) if variant['asin'] in selected]
    child_workers = _apify_child_workers(env, len(indexed_variants))
    if child_workers > 1:
        with ThreadPoolExecutor(max_workers=child_workers) as executor:
            futures = {executor.submit(fetch_variant, index, variant): variant for index, variant in indexed_variants}
            for future in as_completed(futures):
                variant = futures[future]
                try:
                    index, v3_child, parent = future.result()
                    v3_by_index[index] = v3_child
                    if parent: observed_parents.add(parent)
                except Exception as exc:
                    errors.append({"asin": str(variant.get("asin") or ""), "error": f"{type(exc).__name__}: {exc}"})
    else:
        for index, variant in indexed_variants:
            try:
                item_index, v3_child, parent = fetch_variant(index, variant)
                v3_by_index[item_index] = v3_child
                if parent: observed_parents.add(parent)
            except Exception as exc:
                errors.append({"asin": str(variant.get("asin") or ""), "error": f"{type(exc).__name__}: {exc}"})

    v3_children = [v3_by_index[index] for index in sorted(v3_by_index)]
    if saved is not None and not frozen_children.issubset(c['asin'] for c in v3_children):
        raise ValueError('Original source revalidation did not rebuild every child; preserve the saved family')
    _reconcile_child_template_facts(v3_children)
    if base and base['family']['parent_asin']:
        observed_parents.add(base['family']['parent_asin'])
    parent_asin = next(iter(observed_parents)) if len(observed_parents) == 1 else ''
    if parent_asin in {v['asin'] for v in variants}:
        parent_asin = ''
    # A source package axis may use Amazon's NUMBER_OF_ITEMS only when every
    # child independently confirms that exact sold-unit count. Keep original
    # source values alongside the projection; package count alone proves nothing.
    variation_mapping = {}
    if 'item_package_quantity' in variation['dimensions'] and len(v3_children) == len(variants) and v3_children and all(
        c.get('sold_unit_count_source') == 'apify_explicit_pack_count'
        and not c.get('sold_unit_count_status')
        and str(c['variation_values'].get('item_package_quantity')) == str(c['sold_unit_count'])
        for c in v3_children
    ):
        for child in v3_children:
            child['variation_values']['number_of_items'] = str(child['sold_unit_count'])
        variation['dimensions'] = ['number_of_items' if k == 'item_package_quantity' else k for k in variation['dimensions']]
        variation_mapping = {'item_package_quantity':'number_of_items'}
    variation['variation_theme'] = theme_from_dimensions(variation['dimensions'])

    fetched_at = saved['source']['fetched_at'] if saved is not None else utc_now()
    v3_family = {
        "protocol_version": "3.0",
        "product_type": plugin.product_type,
        "category_id": plugin.category_id,
        "source": {
            "type": "apify",
            "seed_asin": seed_asin,
            "fetched_at": fetched_at,
            "policy_version": PRODUCT_FAMILY_POLICY_VERSION,
            "request_identity": identity,
            "variation_mapping": variation_mapping,
            "raw_sha256": {asin: file_sha256(raw_dir / f'{asin}.json') for asin in {seed_asin, *(c['asin'] for c in v3_children)}},
            "raw_dir": raw_dir.relative_to(job_path.resolve()).as_posix(),
            "raw_dirs": {"apify": raw_dir.relative_to(job_path.resolve()).as_posix()},
            "child_fetch_errors": errors,
            "expected_child_count": len({v['asin'] for v in variants} | set(failed_asins if saved is not None else [])),
        },
        "family": {
            "parent_asin": parent_asin,
            **({'unconfirmed_variant_asins':variation['unconfirmed_variant_asins']} if variation.get('unconfirmed_variant_asins') else {}),
            "brand": job["brand"],
            "sku_prefix": job["sku_prefix"],
            "marketplace": str(job.get("marketplace") or "US").upper(),
            "variation_theme": variation["variation_theme"],
            "variation_dimensions": variation["dimensions"],
            "children": v3_children,
        },
        "product_specific": {plugin.category_id: {"extractor": "products/generic_extractors.py", "mapping": "manifest.extractors"}},
    }
    if not v3_children:
        raise RuntimeError("No child ASINs were fetched successfully; refusing to write an empty product family")
    validate_data(v3_family, "product_family.schema.json", label="product_family_v3")
    v3_path = job_path / "source" / "product_family_v3.json"
    if saved is not None or base is not None:
        from ..run_scope import reconcile_verified_inventory
        reconcile_verified_inventory(job_path, saved or base, v3_family)
    write_json(v3_path, v3_family)
    _write_audit(job_path / "source" / "apify_audit.md", v3_family, errors)
    return v3_family


def _source_sold_unit_count(
    raw: dict[str, Any], specs: dict[str, Any], specific: dict[str, Any]
) -> tuple[int | None, str, list[int]]:
    try:
        explicit = explicit_item_counts(raw)
        invalid_explicit = False
    except ValueError:
        explicit, invalid_explicit = set(), True
    for facts in (specs, specific):
        for field in ("number_of_items",):
            value = facts.get(field)
            if value in (None, ""):
                continue
            text = str(value).strip()
            if not re.fullmatch(r"[1-9]\d*", text):
                invalid_explicit = True
                continue
            explicit.add(int(text))
    if len(explicit) > 1:
        return None, "apify_conflicted_pack_count", sorted(explicit)
    if invalid_explicit:
        return None, "apify_invalid_pack_count", []
    if explicit:
        return explicit.pop(), "apify_explicit_pack_count", []
    return None, "apify_missing_pack_count", []


def _reconcile_child_template_facts(children: list[dict[str, Any]]) -> None:
    """Normalize template-critical facts that are directly evidenced by each child."""
    for child in children:
        if not isinstance(child, dict):
            continue
        normalized = child.setdefault("normalized_facts", {})
        normalized_variation = normalized.setdefault("variation", {})
        if not str(normalized.get("color") or "").strip():
            color = _infer_color_from_child_source(child)
            if color:
                normalized["color"] = color
                normalized_variation.setdefault("color", color)


def _infer_color_from_child_source(child: dict[str, Any]) -> str:
    specs = child.get("specs") if isinstance(child.get("specs"), dict) else {}
    specific = child.get("product_specific") if isinstance(child.get("product_specific"), dict) else {}
    for container in (specs, specific):
        value = _explicit_fact_value(container, {"color", "colour", "color_name", "colour_name"})
        cleaned = _clean_variation_value("color", value)
        if cleaned:
            return cleaned
    return ""


def _explicit_fact_value(value: Any, keys: set[str]) -> Any:
    if not isinstance(value, dict):
        return ""
    for key, item in value.items():
        normalized = fact_key(str(key))
        if normalized in keys and item not in (None, "", [], {}):
            return item
    for item in value.values():
        nested = _explicit_fact_value(item, keys)
        if nested not in (None, "", [], {}):
            return nested
    return ""


def _dedupe_variants(
    variants: list[dict[str, Any]], seed_asin: str, *, parent_asin: str
) -> list[dict[str, Any]]:
    by_asin: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        asin = str(variant.get("asin") or "").strip()
        if not asin or (parent_asin and asin == parent_asin):
            continue
        if asin not in by_asin:
            order.append(asin)
            by_asin[asin] = dict(variant)
        else:
            for key, value in variant.items():
                if by_asin[asin].get(key) in (None, "") and value not in (None, ""):
                    by_asin[asin][key] = value
    if seed_asin and seed_asin != parent_asin and seed_asin not in by_asin:
        by_asin[seed_asin] = {"asin": seed_asin}
    ordered_asins = [seed_asin] if seed_asin in by_asin else []
    ordered_asins.extend(asin for asin in order if asin != seed_asin)
    return [by_asin[asin] for asin in ordered_asins]


def _fetch_validated_raw(
    client: ApifyClient | None,
    raw_dir: Path,
    asin: str,
    refresh: bool,
    *,
    extractors: Any,
    require_variations: bool,
) -> dict[str, Any]:
    path = raw_dir / f"{safe_path_component(asin, fallback='asin')}.json"
    if path.exists() and not refresh:
        cached = read_json(path)
        if not _raw_quality_issues(
            cached, extractors=extractors, seed_asin=asin, require_variations=require_variations
        ):
            return cached
    if client is None:
        raise ValueError(f'Saved raw source is missing or incomplete for local revalidation: {asin}')
    raw = client.fetch_product(asin)
    issues = _raw_quality_issues(
        raw, extractors=extractors, seed_asin=asin, require_variations=require_variations
    )
    if issues:
        raise RuntimeError(f"Apify result for {asin} is incomplete: {', '.join(issues)}")
    write_json(path, raw)
    return raw


def _raw_quality_issues(
    raw: dict[str, Any], *, extractors: Any, seed_asin: str, require_variations: bool
) -> list[str]:
    issues: list[str] = []
    if not isinstance(raw, dict) or not raw:
        return ["empty raw data"]
    if returned_asin(raw) != str(seed_asin).upper():
        issues.append('returned ASIN is missing, ambiguous or differs from the requested product')
    if not _source_title(raw):
        issues.append("missing title")
    try:
        images = extractors.image_urls(raw)
    except Exception:
        images = []
    if not images:
        issues.append("missing image urls")
    if require_variations:
        try:
            variations = extractors.extract_variations(raw, seed_asin)
        except Exception:
            variations = {}
        if not variations.get("variants"):
            issues.append("missing variations")
    bullets = raw.get("bulletPoints") or raw.get("features") or []
    description = _source_description(raw)
    if not bullets and not str(description or "").strip():
        issues.append("missing bullets and description")
    return issues


def _apify_child_workers(env: dict[str, str], task_count: int) -> int:
    if task_count <= 1:
        return 1
    raw = env.get("AMAZON_FACTORY_APIFY_CHILD_WORKERS") or env.get("AMAZON_FACTORY_FETCH_WORKERS") or "4"
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        value = 4
    return max(1, min(8, value, task_count))


def _default_config_path() -> str:
    candidate = FACTORY_ROOT / "config.local.env"
    return str(candidate) if candidate.exists() else ""


def _variation_values(variant: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in variant.items():
        if key == "asin" or value in (None, ""):
            continue
        normalized = fact_key(str(key))
        cleaned = _clean_variation_value(normalized, value)
        if cleaned:
            out[normalized] = cleaned
    return out


def _clean_variation_value(key: str, value: Any) -> str:
    text = _clean_source_text(value)
    if not text or _has_bad_encoding(text):
        return ""
    normalized_key = fact_key(key)
    if normalized_key == "color" and (_looks_like_measurement_or_pack(text) or not _looks_like_color_value(text)):
        return ""
    return text[:80]


def _has_bad_encoding(value: str) -> bool:
    return has_bad_encoding(value)


def _looks_like_measurement_or_pack(value: str) -> bool:
    text = value.casefold()
    return bool(
        re.search(r"\d", text)
        and re.search(r"\b(?:in|inch|ft|feet|cm|mm|pack|pcs?|pieces?)\b|[\"']", text)
    )


def _looks_like_color_value(value: str) -> bool:
    text = value.strip()
    if len(text) > 40:
        return False
    # Numeric shade names such as "3-Tone Brown" are legitimate color
    # variation values; measurements, pack counts, and dimensions are filtered
    # by _looks_like_measurement_or_pack before this predicate is used.
    if re.search(r"\d", text) and not re.search(r"\b\d+\s*[- ]?tone\b", text, re.I):
        return False
    return bool(re.search(r"[A-Za-z]", text))


def _normalized_child_facts(
    *,
    variation_values: dict[str, Any],
    specs: dict[str, Any],
    specific: dict[str, Any],
    offer: dict[str, str],
    sold_unit_count: int | None,
    package_quantity: int | None,
    title: str = "",
    bullets: list[Any] | None = None,
    description: str = "",
) -> dict[str, Any]:
    variation = {
        str(key): clean_evidence_text(value)
        for key, value in variation_values.items()
        if clean_evidence_text(value) and not has_bad_encoding(value)
    }
    color = _first_clean(variation, specs, specific, keys=("color", "colour", "color_name"))
    if color and (_looks_like_measurement_or_pack(color) or not _looks_like_color_value(color)):
        color = ""
    size = (
        _first_clean_by_key_priority(variation, keys=("size", "size_name", "size_class", "height"))
        or _first_clean_by_key_priority(specs, specific, keys=("size", "size_name", "size_class"))
    )
    physical_dimensions = _first_clean_by_key_priority(
        specs,
        specific,
        keys=("dimensions", "item_dimensions", "product_dimensions"),
    )
    style = _first_clean(variation, specs, specific, keys=("style", "style_name"))
    spec_measurements: list[str] = []
    spec_measurement_records: list[dict[str, str]] = []
    for facts in (specs, specific):
        for key, value in sorted(facts.items()):
            normalized_key = re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")
            if any(word in normalized_key for word in ("package", "shipping", "carton", "box_dimension")):
                continue
            if not any(word in normalized_key for word in (
                "item_dimension", "product_dimension", "overall_dimension", "height", "width", "depth", "length",
                "weight", "capacity", "load",
            )):
                continue
            text = f"{key}: {_plain_value(value)}"
            for item in extract_measurements(text):
                if item.get("kind") not in {"length_mm", "weight_g"}:
                    continue
                cleaned = str(item.get("text") or "").strip()
                if cleaned and cleaned not in spec_measurements:
                    spec_measurements.append(cleaned)
                    spec_measurement_records.append({"field": normalized_key, "text": cleaned})
    return {
        "variation": variation,
        "color": color,
        "size": size,
        "physical_dimensions": physical_dimensions,
        "style": style,
        "package": f"{package_quantity} count" if package_quantity else "",
        "list_price": str(offer.get("list_price") or ""),
        "currency": str(offer.get("currency") or ""),
        "sold_unit_count": sold_unit_count,
        "package_quantity": package_quantity,
        "spec_measurements": spec_measurements[:12],
        "spec_measurement_records": spec_measurement_records[:12],
        "resolved_facts": _resolve_structured_facts(
            title=title,
            bullets=bullets or [],
            description=description,
            specs=specs,
            specific=specific,
            variation=variation,
        ),
        "evidence": {
            "variation": "apify_variation_with_explicit_count_projection",
            "price": "apify_offer" if offer.get("list_price") else "",
            "measurements": "apify_specs",
        },
    }


def _resolve_structured_facts(
    *, title: str, bullets: list[Any], description: str,
    specs: dict[str, Any], specific: dict[str, Any], variation: dict[str, Any],
) -> dict[str, Any]:
    """Resolve structured child identity and whole-product counts once, with provenance."""
    text = " ".join([str(title or ""), *(str(value or "") for value in bullets), str(description or "")])
    fact_patterns = {
        "number_of_drawers": r"drawers?",
        "number_of_doors": r"doors?",
        "number_of_shelves": r"shel(?:f|ves)",
    }
    from products.generic_extractors import MATERIAL_OWNERS
    from core.product_family import fact_key
    observations: dict[str, list[dict[str, Any]]] = {}
    for origin, container in (('variation', variation), ('spec', specs), ('specific', specific)):
        rows = [dict(row) for row in container.get('source_fact_evidence', []) if isinstance(row, dict)]
        covered = {row['key'] for row in rows}
        for key, value in container.items():
            key = fact_key(key)
            if key in covered or value in (None, '', [], {}) or key.startswith('source_'):
                continue
            if key in MATERIAL_OWNERS or key in {'color', 'size', *fact_patterns}:
                rows.append({'key': key, 'owner': MATERIAL_OWNERS.get(key, 'product'),
                             'field': key, 'source': origin, 'value': clean_evidence_text(value)})
        for row in rows:
            key = row['key']
            if key in fact_patterns:
                match = re.fullmatch(r'([0-9]+)(?:\.0+)?', str(row['value']).strip())
                if not match:
                    raise ValueError(f'Invalid whole-product count in {row["field"]}')
                row['value'] = int(match[1])
            observations.setdefault(key, []).append(row)
    for key, pattern in fact_patterns.items():
        for value in sorted(set(whole_part_counts(text, pattern))):
            observations.setdefault(key, []).append({'key': key, 'owner': 'product', 'value': int(value),
                'source': 'listing_text', 'field': 'title_bullets_description'})
    resolved = {}
    for key, rows in observations.items():
        rows = list({json.dumps(row, sort_keys=True): row for row in rows}.values())
        choices = []
        for row in rows:
            value = row['value']
            equal = identity_values_equal if key == 'size' else lambda a, b: str(a).casefold() == str(b).casefold()
            if not any(equal(value, previous) for previous in choices):
                choices.append(value)
        scoped_conflict = any(row.get('scope_conflict') for row in rows)
        confirmed = len(choices) == 1 and not scoped_conflict
        value = choices[0] if confirmed else ''
        nominal = [row['value'] for row in rows if key == 'size' and row.get('source') == 'title_nominal_size']
        if nominal and len(set(nominal)) == 1:
            confirmed, value = True, nominal[0]
        resolved[key] = {'status': 'confirmed' if confirmed else 'conflicted', 'value': value,
                         'candidates': choices, 'evidence': rows, 'owner': rows[0].get('owner', MATERIAL_OWNERS.get(key,'product'))}
        if nominal:
            resolved[key]['selection_basis'] = 'same_child_title_nominal_size; physical dimensions remain separate'
    if any(key in MATERIAL_OWNERS for key in resolved) and 'material' not in resolved:
        resolved['material'] = {'status': 'unconfirmed', 'value': '', 'candidates': [], 'evidence': [], 'owner': 'product'}
    return resolved


def _first_clean(*sources: dict[str, Any], keys: tuple[str, ...]) -> str:
    wanted = {fact_key(key) for key in keys}
    for source in sources:
        for key, value in source.items():
            if fact_key(str(key)) not in wanted:
                continue
            text = clean_evidence_text(value)
            if text and not has_bad_encoding(text):
                return text[:120]
    return ""


def _first_clean_by_key_priority(*sources: dict[str, Any], keys: tuple[str, ...]) -> str:
    for wanted in keys:
        normalized_wanted = fact_key(wanted)
        for source in sources:
            for key, value in source.items():
                if fact_key(str(key)) != normalized_wanted:
                    continue
                text = clean_evidence_text(value)
                if text and not has_bad_encoding(text):
                    return text[:120]
    return ""


def _plain_value(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_plain_value(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_plain_value(item) for item in value)
    return str(value or "")


def _source_description(raw: dict[str, Any]) -> str:
    for key in ("description", "productDescription"):
        text = _clean_source_text(raw.get(key))
        if text:
            return text
    aplus = raw.get("aPlusContent")
    if not isinstance(aplus, dict):
        return ""
    raw_text = _clean_source_text(aplus.get("rawText"))
    if _meaningful_aplus_text(raw_text):
        return raw_text
    return ""


def _source_title(raw: dict[str, Any]) -> str:
    return _clean_source_text(raw.get("title") or raw.get("productTitle") or "")


def _source_bullets(raw: dict[str, Any]) -> list[str]:
    values = raw.get("bulletPoints") or raw.get("features") or []
    if isinstance(values, str):
        values = [values]
    return list(dict.fromkeys(
        text for text in (_clean_source_text(value) for value in values if value is not None) if text
    ))[:12]


def _source_review_summary(raw: dict[str, Any]) -> str:
    for key in ("reviewSummary", "reviewsSummary", "customerReviewSummary", "aiReviewsSummary"):
        value = raw.get(key)
        if isinstance(value, dict):
            text = _clean_source_text(value.get("text") or value.get("summary") or value.get("body") or "")
        else:
            text = _clean_source_text(value)
        if text:
            return text
    snippets: list[str] = []
    for key in ("reviews", "customerReviews", "topReviews"):
        value = raw.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                title = _clean_source_text(item.get("title") or item.get("summary") or "")
                body = _clean_source_text(item.get("text") or item.get("body") or item.get("content") or "")
                text = ". ".join(part for part in (title, body) if part)
            else:
                text = _clean_source_text(item)
            if text:
                snippets.append(text)
            if len(snippets) >= 6:
                break
        if snippets:
            break
    return " ".join(snippets)


def _source_offer(raw: dict[str, Any], *, marketplace: str = '') -> dict[str, str]:
    owner = returned_asin(raw)
    if not owner:
        return {}
    offer = {}
    for field in ('listPrice', 'salePrice', 'currentPrice', 'buyBoxPrice', 'price', 'priceValue', 'amount'):
        kind = 'list_price' if field == 'listPrice' else 'current_price'
        if kind in offer:
            continue
        value = raw.get(field)
        if isinstance(value, dict) and value.get('asin') and returned_asin(value) != owner:
            continue
        price = normalize_price_value(value)
        if not price:
            continue
        container = {**raw, **value} if isinstance(value, dict) else raw
        currency_field = next((key for key in ('currency', 'priceCurrency', 'currencyCode') if container.get(key)), '')
        currency = _clean_source_text(container.get(currency_field) or '').upper()
        if not currency:
            currency = {'US': 'USD', 'CA': 'CAD', 'MX': 'MXN', 'UK': 'GBP', 'DE': 'EUR', 'FR': 'EUR',
                        'IT': 'EUR', 'ES': 'EUR', 'JP': 'JPY', 'AU': 'AUD'}.get(marketplace.upper(), '')
            currency_field = 'request.marketplace' if currency else ''
        prefix = '' if kind == 'list_price' else 'current_'
        offer.update({kind:price, prefix+'price_field':field, prefix+'currency':currency,
                      prefix+'currency_field':currency_field})
    return {**offer, 'source':'apify', 'owner_asin':owner} if offer else {}


def _clean_source_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\b(Description|Product description)(?=[A-Z])", r"\1 ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:product\s+description|description)\s*", "", text, flags=re.IGNORECASE).strip()
    return clean_evidence_text(text)


def _meaningful_aplus_text(text: str) -> bool:
    if len(text) < 60:
        return False
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    boilerplate = {
        "product description previous page next page",
        "product description",
        "previous page next page",
    }
    return normalized not in boilerplate


def _write_audit(path: Path, family: dict[str, Any], errors: list[dict[str, str]]) -> None:
    children = family["family"]["children"]
    lines = [
        "# Apify Family Fetch Audit",
        "",
        f"- Protocol: `{family['protocol_version']}`",
        f"- Product Type: `{family['product_type']}`",
        f"- Seed ASIN: `{family['source']['seed_asin']}`",
        f"- Parent ASIN: `{family['family']['parent_asin']}`",
        f"- Children: {len(children)}",
        f"- Variation Theme: `{family['family']['variation_theme']}`",
        "",
        "| ASIN | Variation | Images | Status | Image Source |",
        "|---|---|---:|---|---|",
    ]
    for child in children:
        variation = ", ".join(f"{k}={v}" for k, v in child.get("variation_values", {}).items())
        image_sources = sorted({str(item.get("source") or "") for item in child.get("reference_images", []) if isinstance(item, dict)})
        lines.append(
            f"| `{child['asin']}` | {variation} | {len(child.get('reference_images', []))} | "
            f"{child.get('status', 'ok')} | {', '.join(image_sources) or '-'} |"
        )
    if errors:
        lines.extend(["", "## Errors", ""])
        for item in errors:
            lines.append(f"- `{item.get('asin')}`: {item.get('error')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
