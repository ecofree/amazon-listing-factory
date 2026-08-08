from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_json
from .schema import validate_data


PRODUCT_FAMILY_POLICY_VERSION = "product-family-v3-resolved-facts-v10-child-scoped"


class ProductFamilyError(RuntimeError):
    pass


def read_product_family(job_dir: str | Path) -> dict[str, Any]:
    job_path = Path(job_dir)
    path = job_path if job_path.name == "product_family_v3.json" else job_path / "source" / "product_family_v3.json"
    data = read_json(path)
    try:
        validate_data(data, "product_family.schema.json", label="ProductFamilyV3")
    except Exception as exc:
        raise ProductFamilyError(f"Unsupported ProductFamilyV3; create a new job or rerun fetch: {exc}") from exc
    policy = str((data.get("source") or {}).get("policy_version") or "")
    if policy != PRODUCT_FAMILY_POLICY_VERSION:
        raise ProductFamilyError(
            f"Unsupported ProductFamilyV3 extraction policy {policy or 'missing'}; create a new job or rerun fetch"
        )
    asins = [str(row.get("asin") or "") for row in data["family"]["children"]]
    if len(asins) != len(set(asins)):
        raise ProductFamilyError("ProductFamilyV3 contains duplicate child ASINs")
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    errors = source.get("child_fetch_errors") if isinstance(source.get("child_fetch_errors"), list) else []
    failed_asins = [str(row.get("asin") or "") for row in errors if isinstance(row, dict)]
    if len(failed_asins) != len(set(failed_asins)):
        raise ProductFamilyError("ProductFamilyV3 contains duplicate child fetch errors")
    if set(asins) & set(failed_asins):
        raise ProductFamilyError("ProductFamilyV3 child cannot be both successful and failed")
    if len(asins) + len(failed_asins) != int(source.get("expected_child_count") or 0):
        raise ProductFamilyError(
            "ProductFamilyV3 successful and failed child inventory does not match expected_child_count"
        )
    return data
