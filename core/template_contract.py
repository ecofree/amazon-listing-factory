from __future__ import annotations

from pathlib import Path
from typing import Any

from .copy_polish import copy_artifact_current
from .io import file_sha256, read_json
from .job import load_job
from .paths import FACTORY_ROOT
from .plugin import ProductPlugin
from .product_family import read_product_family
from .status import input_revision_id
from .template_runtime import (
    load_template_env,
    resolve_template_path,
    safe_component,
    template_job_with_defaults,
    template_mode,
)


TEMPLATE_INPUT_POLICY_VERSION = "template-input-v8-field-plan-readiness-authority"
_TEMPLATE_JOB_FIELDS = (
    "seed_asin",
    "category_id",
    "brand",
    "sku_prefix",
    "marketplace",
    "template_path",
    "condition",
    "manufacturer",
    "quantity",
    "fulfillment",
    "inventory_available",
    "product_id",
    "product_id_type",
    "gtin_exempt",
    "country",
    "dangerous_goods",
    "list_price",
    "shipping_template",
    "batteries_required",
    "batteries_included",
    "contains_battery",
    "is_fragile",
)


def template_input_fingerprint(
    *,
    job_path: Path,
    template_path: Path,
    output_path: Path,
    mode: str,
    write_excel: bool,
    job: dict[str, Any],
    plugin_config: dict[str, Any],
) -> str:
    return input_revision_id(
        {
            "policy": TEMPLATE_INPUT_POLICY_VERSION,
            "mode": str(mode),
            "write_excel": bool(write_excel),
            "output_path": str(output_path.resolve()),
            "template_path": str(template_path.resolve()),
            "template_sha256": file_sha256(template_path),
            "family_sha256": _optional_sha(job_path / "source" / "product_family_v3.json"),
            "copy_sha256": _optional_sha(job_path / "reports" / "copy_v1.json"),
            "release_sha256": _optional_sha(job_path / "reports" / "release_manifest_v5.json"),
            "publish_sha256": _optional_sha(job_path / "images" / "_r2_image_urls.csv"),
            "partial_publish_sha256": _optional_sha(job_path / "images" / "_r2_image_urls.partial.csv"),
            "job": {
                key: job.get(key)
                for key in _TEMPLATE_JOB_FIELDS
                if key in job
            },
            "plugin_config": {
                key: plugin_config.get(key)
                for key in (
                    "product_type",
                    "amazon_product_type",
                    "template",
                    "item_type_keyword",
                    "competitor_keywords",
                    "backend_search_terms",
                )
                if key in plugin_config
            },
        }
    )


def template_plan_current(
    *,
    job_dir: str | Path,
    plugin: ProductPlugin,
    config_path: str = "",
    mode: str = "submit_ready",
    write_excel: bool = True,
) -> bool:
    job_path = Path(job_dir).resolve()
    if not copy_artifact_current(
        job_dir=job_path,
        plugin=plugin,
        config_path=config_path,
        mode=mode,
    ):
        return False
    plan_path = job_path / "template" / "plan.json"
    if not plan_path.is_file():
        return False
    plan = read_json(plan_path)
    if not isinstance(plan, dict):
        return False
    job = load_job(job_path)
    env = load_template_env(
        str(FACTORY_ROOT / "config.env"),
        str(FACTORY_ROOT / "config.local.env"),
        config_path,
        job.get("config_path", ""),
    )
    family = read_product_family(job_path)
    job = template_job_with_defaults(job, env=env)
    resolved_mode = template_mode(env, mode)
    template_path = resolve_template_path(
        plugin,
        job,
        factory_root=FACTORY_ROOT,
    )
    output_path = job_path / "template" / f"filled_{plugin.product_type}_{job['seed_asin']}.xlsm"
    expected = template_input_fingerprint(
        job_path=job_path,
        template_path=template_path,
        output_path=output_path,
        mode=resolved_mode,
        write_excel=write_excel,
        job=job,
        plugin_config=plugin.merged_config(),
    )
    if str(plan.get("template_input_fingerprint") or "") != expected:
        return False
    if Path(str(plan.get("template_path") or "")).resolve() != template_path.resolve():
        return False
    if Path(str(plan.get("output_path") or "")).resolve() != output_path.resolve():
        return False
    if str(plan.get("template_mode") or "") != resolved_mode:
        return False
    allowed_states = (
        {"submit_ready"}
        if resolved_mode == "submit_ready"
        else {"draft", "draft_with_blockers"}
    )
    if str(plan.get("artifact_state") or "") not in allowed_states:
        return False
    if not write_excel:
        return True
    if not _matches_receipt(output_path.resolve(), str(plan.get("workbook_sha256") or "")):
        return False
    if resolved_mode == "submit_ready":
        final_path = Path(str(plan.get("final_template_path") or "")).resolve()
        parent = str(family["family"].get("parent_asin") or "")
        expected_dir = (
            FACTORY_ROOT / "Final_templates" / safe_component(parent)
        ).resolve()
        expected_stem = f"{output_path.stem}_{safe_component(job_path.name)}"
        if final_path.parent != expected_dir or not final_path.stem.startswith(expected_stem):
            return False
        if final_path.suffix.casefold() != output_path.suffix.casefold():
            return False
        if not _matches_receipt(final_path, str(plan.get("final_template_sha256") or "")):
            return False
    return True


def _matches_receipt(path: Path, expected_sha256: str) -> bool:
    return bool(expected_sha256 and path.is_file() and file_sha256(path) == expected_sha256)


def _optional_sha(path: Path) -> str:
    return file_sha256(path) if path.is_file() else ""
