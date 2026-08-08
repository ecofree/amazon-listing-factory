from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


DEFAULT_TEMPLATE_BRAND = "safeplus"
DEFAULT_TEMPLATE_MANUFACTURER = "safeplus"
DEFAULT_TEMPLATE_COUNTRY = "China"
DEFAULT_TEMPLATE_CONDITION = "New"
DEFAULT_TEMPLATE_QUANTITY = "200"
DEFAULT_TEMPLATE_FULFILLMENT = "Fulfillment by Merchant (Default)"
DEFAULT_TEMPLATE_PRODUCT_ID_TYPE = "GTIN Exempt"
DEFAULT_TEMPLATE_DANGEROUS_GOODS = "Not Applicable"
DEFAULT_TEMPLATE_INVENTORY_AVAILABLE = "true"


def load_template_env(*paths: str | Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in paths:
        if path:
            values.update(read_env_file(path))
    for key, value in os.environ.items():
        if not (
            key.startswith("DEFAULT_")
            or key.startswith("AMAZON_FACTORY_")
            or key.startswith("COPY_AI_")
            or key.startswith("DEEPSEEK_")
        ):
            continue
        if str(value or "").strip() == "":
            continue
        values[key] = value
    return values


def read_env_file(path: str | Path) -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def normalize_template_mode(value: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if text in {"", "draft", "debug"}:
        return "draft"
    if text in {"final", "submit", "submit_ready", "production"}:
        return "submit_ready"
    raise ValueError("Template mode must be draft or submit_ready")


def template_mode(env: dict[str, str], explicit: str = "") -> str:
    return normalize_template_mode(
        explicit or env.get("AMAZON_FACTORY_TEMPLATE_MODE") or env.get("TEMPLATE_MODE") or "draft"
    )


def resolve_template_path(
    plugin: Any,
    job: dict[str, Any],
    *,
    factory_root: str | Path,
    explicit: str = "",
) -> Path:
    value = explicit or str(job.get("template_path") or "")
    template_cfg = plugin.merged_config().get("template")
    if not value and isinstance(template_cfg, dict):
        env_key = str(template_cfg.get("path_env") or "").strip()
        if env_key:
            value = os.environ.get(env_key, "")
        value = value or str(template_cfg.get("default_path") or "")
    if not value:
        raise ValueError(
            "Template path is required; set job.template_path or products/<category>/manifest.yaml template.default_path"
        )
    path = Path(os.path.expandvars(value))
    if not path.is_absolute():
        path = (Path(factory_root) / path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Template file not found: {path}")
    return path


def template_job_with_defaults(job: dict[str, Any], *, env: dict[str, str]) -> dict[str, Any]:
    updated = dict(job)
    overrides = {
        "brand": _first_env_value(
            env, "AMAZON_FACTORY_TEMPLATE_BRAND", "AMAZON_FACTORY_BRAND", "DEFAULT_BRAND"
        ),
        "manufacturer": _first_env_value(
            env,
            "AMAZON_FACTORY_TEMPLATE_MANUFACTURER",
            "AMAZON_FACTORY_MANUFACTURER",
            "DEFAULT_MANUFACTURER",
        ),
        "country": _first_env_value(
            env,
            "AMAZON_FACTORY_TEMPLATE_COUNTRY_OF_ORIGIN",
            "AMAZON_FACTORY_COUNTRY_OF_ORIGIN",
            "DEFAULT_COUNTRY_OF_ORIGIN",
        ),
    }
    for field, value in overrides.items():
        if value and not str(updated.get(field) or "").strip():
            updated[field] = value
    defaults = {
        "brand": DEFAULT_TEMPLATE_BRAND,
        "manufacturer": DEFAULT_TEMPLATE_MANUFACTURER,
        "country": DEFAULT_TEMPLATE_COUNTRY,
        "condition": DEFAULT_TEMPLATE_CONDITION,
        "quantity": DEFAULT_TEMPLATE_QUANTITY,
        "fulfillment": DEFAULT_TEMPLATE_FULFILLMENT,
        "inventory_available": DEFAULT_TEMPLATE_INVENTORY_AVAILABLE,
        "dangerous_goods": DEFAULT_TEMPLATE_DANGEROUS_GOODS,
        "product_id_type": DEFAULT_TEMPLATE_PRODUCT_ID_TYPE,
    }
    for field, value in defaults.items():
        updated[field] = str(updated.get(field) or value)
    if updated.get("gtin_exempt") is None:
        updated["gtin_exempt"] = True
    return updated


def _first_env_value(env: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = str(env.get(key) or "").strip()
        if value:
            return value
    return ""


def safe_component(value: str, fallback: str = "unknown") -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._")
    return text[:80] or fallback


def child_sku(job: dict[str, Any], child: dict[str, Any], index: int) -> str:
    asin = str(child.get("asin") or index)
    prefix = safe_component(str(job.get("sku_prefix") or ""), fallback="")
    return f"{prefix}-{asin}" if prefix else asin


def parent_sku(job: dict[str, Any], parent_asin: str, child_skus: list[str]) -> str:
    prefix = safe_component(str(job.get("sku_prefix") or ""), fallback="")
    base_asin = str(parent_asin or "PARENT").strip() or "PARENT"
    base = f"{prefix}-PARENT-{base_asin}" if prefix else base_asin
    used = {str(item or "").strip() for item in child_skus}
    if base not in used:
        return base
    candidate = f"{base}-PARENT"
    counter = 2
    while candidate in used:
        candidate = f"{base}-PARENT-{counter}"
        counter += 1
    return candidate
