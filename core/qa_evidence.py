from __future__ import annotations

from pathlib import Path
from typing import Any

from .image_task_inputs import release_candidate_fingerprint
from .io import file_sha256, read_jsonl, write_jsonl
from .paths import resolve_job_owned_path
from .status import input_revision_id


QA_EVIDENCE_SCHEMA_VERSION = "qa-evidence-v5"
QA_EVIDENCE_ARTIFACT = "qa_evidence_v5.jsonl"
QA_POLICY_VERSION = "observed-facts-three-state-v47-whole-candidate-coverage"


class QaEvidenceError(RuntimeError):
    pass


def qa_policy_id(task: dict[str, Any]) -> str:
    from .image_pixel_evidence import PIXEL_EVIDENCE_VERSION
    from .image_role_ocr import ROLE_OCR_EVIDENCE_CACHE_VERSION
    from .vision_gemini_client import gemini_scope_execution_revision

    return input_revision_id({
        "policy": QA_POLICY_VERSION,
        "observer_execution": gemini_scope_execution_revision("vision_qa"),
        "role": str(task.get("role_family") or task.get("role") or ""),
        "task_policy": task.get("policy_version") or "",
        "task_fingerprint": task.get("task_fingerprint") or "",
        "category_image_policy": task.get("category_image_policy") or {},
        "product_boundary": task.get("product_boundary") or {},
        "measurement_authority": task.get("measurement_authority") or {},
        "ocr_policy": ROLE_OCR_EVIDENCE_CACHE_VERSION,
        "pixel_policy": PIXEL_EVIDENCE_VERSION,
    })


def evidence_fingerprint(evidence: dict[str, Any]) -> str:
    return input_revision_id({
        key: value for key, value in evidence.items()
        if key not in {"evidence_fingerprint", "provider"}
    })


def write_qa_evidence(job_dir: str | Path, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        _validate_row(row)
    write_jsonl(Path(job_dir) / "reports" / QA_EVIDENCE_ARTIFACT, rows)


def read_qa_evidence(job_dir: str | Path) -> list[dict[str, Any]]:
    path = Path(job_dir) / "reports" / QA_EVIDENCE_ARTIFACT
    if not path.is_file():
        raise QaEvidenceError(f"Current {QA_EVIDENCE_SCHEMA_VERSION} is missing: {path}")
    rows = read_jsonl(path)
    for row in rows:
        _validate_row(row)
    return rows


def evidence_is_current(
    evidence: dict[str, Any],
    task: dict[str, Any],
    candidate: dict[str, Any],
    *,
    job_dir: str | Path | None = None,
) -> bool:
    try:
        _validate_row(evidence)
        if evidence["child"] != task["child"] or evidence["role"] != task["role"]:
            return False
        if evidence["release_candidate_fingerprint"] != release_candidate_fingerprint(task, candidate):
            return False
        if evidence["candidate_sha256"] != candidate["candidate_sha256"]:
            return False
        if evidence["qa_policy_id"] != qa_policy_id(task):
            return False
        if evidence["evidence_fingerprint"] != evidence_fingerprint(evidence):
            return False
        if job_dir is not None:
            output = resolve_job_owned_path(job_dir, str(candidate["candidate_path"]))
            evidence_output = resolve_job_owned_path(job_dir, str(evidence["candidate_path"]))
            if evidence_output != output:
                return False
            if not output.is_file() or file_sha256(output) != evidence["candidate_sha256"]:
                return False
        return True
    except Exception:
        return False


def _validate_row(row: Any) -> None:
    if not isinstance(row, dict) or row.get("schema_version") != QA_EVIDENCE_SCHEMA_VERSION:
        raise QaEvidenceError("Invalid current QA evidence row")
    required = (
        "child", "role", "candidate_path", "candidate_sha256",
        "release_candidate_fingerprint", "qa_policy_id", "evidence_fingerprint",
        "automatic_decision", "gates",
    )
    missing = [field for field in required if row.get(field) in (None, "", [])]
    if missing or row.get("automatic_decision") not in {"pass", "fail", "inconclusive"}:
        raise QaEvidenceError(f"Invalid current QA evidence row: missing={missing}")
    if row.get("evidence_fingerprint") != evidence_fingerprint(row):
        raise QaEvidenceError("QA evidence fingerprint changed")
    if not isinstance(row["gates"], list):
        raise QaEvidenceError("QA gates must be a list")
    for gate in row.get("gates") or []:
        if not isinstance(gate, dict) or gate.get("status") not in {"pass", "fail", "inconclusive"}:
            raise QaEvidenceError("QA gate is invalid")
        if not str(gate.get("gate") or "").strip() or not str(gate.get("evidence") or "").strip():
            raise QaEvidenceError("QA gate requires a name and evidence")
    statuses = {gate["status"] for gate in row["gates"]}
    expected = "fail" if "fail" in statuses else "inconclusive" if "inconclusive" in statuses else "pass"
    if row["automatic_decision"] != expected:
        raise QaEvidenceError("QA decision contradicts its factual gates")
