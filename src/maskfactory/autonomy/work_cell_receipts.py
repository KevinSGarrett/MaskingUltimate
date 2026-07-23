"""Hash-bound receipt adapters for RunPod autonomous work-cell stages.

The work-cell controller intentionally knows only durable stage receipts, while
the RunPod masking lane writes richer stage-specific artifacts.  This module is
the narrow bridge between the two: it accepts an exact artifact JSON object (or
bytes hashed by the caller), extracts the closed detail fields required by the
mission state machine, and emits one work-cell receipt.

It does not author masks, review pixels, repair outputs, freeze packages, or
issue certificates.  Missing fields fail closed before a mission can advance.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .work_cell import ALLOWED_ACTORS, STAGES


class WorkCellReceiptError(ValueError):
    """A RunPod stage artifact cannot be converted into an authoritative receipt."""


SHA256_HEX_LENGTH = 64

DEFAULT_STAGE_ACTORS = {
    "source_decode": "deterministic_qa",
    "detection_ownership": "deterministic_qa",
    "provider_tournament": "segmentation_provider",
    "hard_qc": "deterministic_qa",
    "primary_visual_review": "visual_critic",
    "independent_visual_review": "visual_critic",
    "repair_planning": "deterministic_qa",
    "repair_execution": "segmentation_provider",
    "package_freeze": "deterministic_qa",
    "certification": "certificate_service",
}

STATUS_VALUES = frozenset({"pass", "repairable", "abstain", "quarantine", "reject"})

REQUIRED_DETAIL_FIELDS = {
    "source_decode": {
        "decoded_pixel_sha256",
        "alpha_policy",
        "width",
        "height",
    },
    "detection_ownership": {
        "target_contract_sha256",
        "person_count",
        "ownership_status",
    },
    "provider_tournament": {
        "tournament_report_sha256",
        "family_count",
        "candidate_count",
    },
    "hard_qc": {
        "qa_vector_sha256",
        "hard_veto_count",
    },
    "primary_visual_review": {
        "panel_sha256",
        "critic_report_sha256",
        "verdict",
    },
    "independent_visual_review": {
        "panel_sha256",
        "critic_report_sha256",
        "verdict",
    },
    "repair_planning": {
        "defect_hypothesis_sha256",
        "roi_sha256",
        "operation",
    },
    "repair_execution": {
        "parent_mask_sha256",
        "new_mask_sha256",
        "changed_pixel_fraction",
    },
    "package_freeze": {
        "package_sha256",
        "active_label_count",
    },
    "certification": {
        "certificate_sha256",
        "authority_tier",
    },
}


def canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json_artifact(path: Path) -> tuple[dict[str, Any], str]:
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkCellReceiptError("stage artifact is not json") from exc
    if not isinstance(artifact, dict):
        raise WorkCellReceiptError("stage artifact must be a json object")
    return artifact, file_sha256(path)


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != SHA256_HEX_LENGTH:
        raise WorkCellReceiptError(f"{field} sha256 required")
    try:
        int(value, 16)
    except ValueError as exc:
        raise WorkCellReceiptError(f"{field} sha256 required") from exc
    return value


def _int(value: Any, field: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise WorkCellReceiptError(f"{field} integer required")
    return value


def _float(value: Any, field: str, *, minimum: float = 0.0) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or float(value) < minimum:
        raise WorkCellReceiptError(f"{field} number required")
    return float(value)


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkCellReceiptError(f"{field} string required")
    return value


def _artifact_detail(artifact: Mapping[str, Any]) -> Mapping[str, Any]:
    detail = artifact.get("work_cell_detail", artifact.get("detail"))
    if not isinstance(detail, Mapping):
        return artifact
    return detail


def _extract_detail(stage: str, artifact: Mapping[str, Any]) -> dict[str, Any]:
    source = _artifact_detail(artifact)
    missing = REQUIRED_DETAIL_FIELDS[stage] - set(source)
    if missing:
        raise WorkCellReceiptError(
            f"{stage} artifact missing receipt detail fields: {', '.join(sorted(missing))}"
        )

    if stage == "source_decode":
        return {
            "decoded_pixel_sha256": _sha(source["decoded_pixel_sha256"], "decoded_pixel_sha256"),
            "alpha_policy": _string(source["alpha_policy"], "alpha_policy"),
            "width": _int(source["width"], "width", minimum=1),
            "height": _int(source["height"], "height", minimum=1),
        }
    if stage == "detection_ownership":
        return {
            "target_contract_sha256": _sha(
                source["target_contract_sha256"], "target_contract_sha256"
            ),
            "person_count": _int(source["person_count"], "person_count", minimum=1),
            "ownership_status": _string(source["ownership_status"], "ownership_status"),
        }
    if stage == "provider_tournament":
        detail = {
            "tournament_report_sha256": _sha(
                source["tournament_report_sha256"], "tournament_report_sha256"
            ),
            "family_count": _int(source["family_count"], "family_count", minimum=1),
            "candidate_count": _int(source["candidate_count"], "candidate_count", minimum=1),
        }
        if "winner_mask_sha256" in source:
            detail["winner_mask_sha256"] = _sha(source["winner_mask_sha256"], "winner_mask_sha256")
        return detail
    if stage == "hard_qc":
        return {
            "qa_vector_sha256": _sha(source["qa_vector_sha256"], "qa_vector_sha256"),
            "hard_veto_count": _int(source["hard_veto_count"], "hard_veto_count"),
        }
    if stage in {"primary_visual_review", "independent_visual_review"}:
        return {
            "panel_sha256": _sha(source["panel_sha256"], "panel_sha256"),
            "critic_report_sha256": _sha(source["critic_report_sha256"], "critic_report_sha256"),
            "verdict": _string(source["verdict"], "verdict"),
        }
    if stage == "repair_planning":
        return {
            "defect_hypothesis_sha256": _sha(
                source["defect_hypothesis_sha256"], "defect_hypothesis_sha256"
            ),
            "roi_sha256": _sha(source["roi_sha256"], "roi_sha256"),
            "operation": _string(source["operation"], "operation"),
        }
    if stage == "repair_execution":
        return {
            "parent_mask_sha256": _sha(source["parent_mask_sha256"], "parent_mask_sha256"),
            "new_mask_sha256": _sha(source["new_mask_sha256"], "new_mask_sha256"),
            "changed_pixel_fraction": _float(
                source["changed_pixel_fraction"], "changed_pixel_fraction"
            ),
        }
    if stage == "package_freeze":
        return {
            "package_sha256": _sha(source["package_sha256"], "package_sha256"),
            "active_label_count": _int(
                source["active_label_count"], "active_label_count", minimum=1
            ),
        }
    if stage == "certification":
        return {
            "certificate_sha256": _sha(source["certificate_sha256"], "certificate_sha256"),
            "authority_tier": _string(source["authority_tier"], "authority_tier"),
        }
    raise WorkCellReceiptError(f"unsupported work-cell stage: {stage}")


def receipt_from_stage_artifact(
    *,
    stage: str,
    status: str,
    artifact: Mapping[str, Any],
    evidence_sha256: str,
    actor_kind: str | None = None,
) -> dict[str, Any]:
    if stage not in STAGES:
        raise WorkCellReceiptError(f"unsupported work-cell stage: {stage}")
    if status not in STATUS_VALUES:
        raise WorkCellReceiptError(f"unsupported work-cell status: {status}")
    actor = actor_kind or str(artifact.get("actor_kind") or DEFAULT_STAGE_ACTORS[stage])
    if actor not in ALLOWED_ACTORS[stage]:
        raise WorkCellReceiptError(f"actor {actor} cannot execute {stage}")
    return {
        "stage": stage,
        "status": status,
        "actor_kind": actor,
        "evidence_sha256": _sha(evidence_sha256, "evidence_sha256"),
        "detail": _extract_detail(stage, artifact),
    }


__all__ = [
    "DEFAULT_STAGE_ACTORS",
    "WorkCellReceiptError",
    "canonical_sha256",
    "file_sha256",
    "load_json_artifact",
    "receipt_from_stage_artifact",
]
