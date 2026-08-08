from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .io import read_json, safe_path_component, utc_now, write_json
from .paths import JOBS_ROOT
from .plugin import ProductPlugin


class JobError(RuntimeError):
    pass


_MAX_JOB_COLLISIONS = 1000
JOB_PROTOCOL_VERSION = "6.0"

_REQUIRED_JOB_FIELDS = ("category_id", "product_type", "seed_asin", "brand", "sku_prefix", "image_root", "r2_prefix")


def slug(value: str) -> str:
    return safe_path_component(value, fallback="job")


def create_job(
    *,
    plugin: ProductPlugin,
    seed_asin: str,
    brand: str,
    sku_prefix: str,
    template_path: str = "",
    marketplace: str = "US",
    config_path: str = "",
    manufacturer: str = "",
    country: str = "",
    condition: str = "",
    quantity: str = "",
    fulfillment: str = "",
    list_price: str = "",
    shipping_template: str = "",
    gtin_exempt: bool | None = None,
    product_id_type: str = "",
    product_id: str = "",
    out_root: str | Path = JOBS_ROOT,
    timestamp: str | None = None,
) -> Path:
    stamp = timestamp or _timestamp_slug()
    safe_seed = slug(seed_asin)
    job_name = f"{safe_seed}_{stamp}"
    job_dir = Path(out_root) / job_name
    if job_dir.exists():
        base_name = job_name
        counter = 2
        while job_dir.exists():
            if counter > _MAX_JOB_COLLISIONS:
                raise JobError(f"Unable to allocate unique job directory after {_MAX_JOB_COLLISIONS} attempts: {base_name}")
            job_name = f"{base_name}_{counter}"
            job_dir = Path(out_root) / job_name
            counter += 1
    for child in ("source", "source/apify_raw", "images", "template", "reports"):
        (job_dir / child).mkdir(parents=True, exist_ok=True)
    job = {
        "protocol_version": JOB_PROTOCOL_VERSION,
        "category_id": plugin.category_id,
        "product_type": plugin.product_type,
        "seed_asin": seed_asin,
        "brand": brand,
        "manufacturer": manufacturer,
        "sku_prefix": sku_prefix,
        "marketplace": marketplace,
        "template_path": str(Path(template_path).resolve()) if template_path else "",
        "config_path": str(Path(config_path).resolve()) if config_path else "",
        "child_sku_source": "generated",
        "gtin_exempt": gtin_exempt,
        "product_id_type": product_id_type,
        "product_id": product_id,
        "country": country,
        "condition": condition,
        "quantity": quantity,
        "fulfillment": fulfillment,
        "shipping_template": shipping_template,
        "list_price": list_price,
        "image_root": str(job_dir / "images"),
        "r2_prefix": f"amazon-listing/generated/original/{plugin.category_id}/{job_name}",
        "created_at": utc_now(),
        "plugin_root": str(plugin.root),
    }
    write_json(job_dir / "job.json", job)
    status = {
        "schema_version": 7,
        "job_id": job_name,
        "stage": "created",
        "status": "pending",
        "updated_at": job["created_at"],
        "errors": [],
        "invalidated_errors": [],
        "warnings": [],
        "artifacts": {"job": str(job_dir / "job.json")},
        "stages": {},
        "tasks": {},
        "task_history": [],
    }
    status_path = job_dir / "job_state.json"
    write_json(status_path, status)
    return job_dir


def load_job(job_dir: str | Path) -> dict[str, Any]:
    path = Path(job_dir) / "job.json"
    data = read_json(path)
    if not isinstance(data, dict):
        raise JobError(f"Job file is not an object: {path}")
    if str(data.get("protocol_version") or "") != JOB_PROTOCOL_VERSION:
        raise JobError(f"Unsupported job protocol in {path}. Create a new job; historical jobs are not migrated.")
    required = _REQUIRED_JOB_FIELDS
    missing = [key for key in required if not str(data.get(key) or "").strip()]
    if missing:
        raise JobError(f"Job file is missing required field(s): {', '.join(missing)} ({path})")
    return data


def _timestamp_slug() -> str:
    return re.sub(r"[^0-9A-Za-z]+", "", utc_now())[:21]
