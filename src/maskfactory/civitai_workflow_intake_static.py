"""STATIC binders for Civitai workflow intake admission and license/provenance gates.

Binds Plan/CIVITAI_WORKFLOW_INTAKE.md + configs/civitai_classifications.json.
Host-side / tracked artifacts only: never requires Plan/Civitai downloads, paid
Civitai access, Kevin credentials, gold promotion, doctor-green, or live ComfyUI runs.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .validation import validate_document

PROOF_TIER = "STATIC_PASS"
ARTIFACT_TYPE = "civitai_workflow_intake_static_report"
AUTHORITY = (
    "civitai_workflow_intake_static_only_no_gold_paid_download_or_kevin_credential_authority"
)
SCHEMA_VERSION = "1.0.0"

INTAKE_MEMO = Path("Plan/CIVITAI_WORKFLOW_INTAKE.md")
CLASSIFICATIONS = Path("configs/civitai_classifications.json")

EXPECTED_RECORD_COUNT = 79
EXPECTED_CLASSIFICATION_COUNTS = {
    "provider_inference": 31,
    "comfyui_graph_reference": 17,
    "annotation_aid": 6,
    "qa_visualization": 23,
    "reject": 2,
}
EXPECTED_METADATA_ONLY_COUNT = 6
EXPECTED_REJECTED_FILES = frozenset({"rotomakerWith_v3.zip", "breastExpansion_v10.zip"})

# Frozen admission contracts from CIVITAI_WORKFLOW_INTAKE.md (no extracted JSON required).
WORKFLOW_ADMISSIONS = {
    "simpleImageToDWPoseDense_v10.zip": {
        "workflow_json": "imageToOpenPose.json",
        "classification": "comfyui_graph_reference",
        "authority": "proposal_or_reference_only",
        "mask_authority": "none",
        "pose_keypoints_role": "geometry_evidence",
        "densepose_role": "referee",
        "animal_pose_policy": "bypass_not_human_pipeline",
        "direct_gold_promotion": False,
        "requires_paid_download": False,
        "requires_kevin_credentials": False,
    },
    "SegmentMaskMaskAddRemove_v10.zip": {
        "workflow_json": "mask_add_remove_self.json",
        "classification": "annotation_aid",
        "authority": "proposal_or_reference_only",
        "mask_authority": "none",
        "adapter_required_gates": (
            "canonical_label_map_import",
            "png_strict_regeneration",
            "format_and_semantic_qa",
            "provenance_preserved",
        ),
        "direct_gold_promotion": False,
        "requires_paid_download": False,
        "requires_kevin_credentials": False,
    },
}

METADATA_ONLY_REPLACEMENTS = {
    "yoloDatasetAuto_v10.zip": "yoloDatasetAuto_v20.zip",
    "handDetailer_v1b.zip": "handDetailer_v2V9c.zip",
    "handDetailer_v1.zip": "handDetailer_v2V9c.zip",
    "eyeDetailerSegmentation_v1b.zip": "eyeDetailerSegmentation_v2.zip",
    "eyeDetailerSegmentation_v1.zip": "eyeDetailerSegmentation_v2.zip",
    "adetailer2dArmpitYolov8_v10Bbox.zip": "adetailer2dArmpitYolov8_v10Segmentation.zip",
}

MEMO_REQUIRED_MARKERS = (
    "proposal/reference-only",
    "proposal_or_reference_only",
    "license, provenance, consent",
    "imageToOpenPose.json",
    "mask_add_remove_self.json",
    "superseded_by_downloaded_variant",
    "download action is `unnecessary`",
    "No manual browser download is required",
)

LICENSE_PROVENANCE_GATES = (
    "mask_authority_none",
    "proposal_or_reference_only_authority",
    "training_or_gold_requires_separate_license_provenance_consent_review",
    "direct_gold_promotion_forbidden",
    "metadata_only_download_unnecessary",
    "no_paid_download_required_for_static_admission",
    "no_kevin_credentials_required_for_static_admission",
)

HONEST_NON_CLAIMS = (
    "civitai_gold_promotion",
    "paid_civitai_download",
    "kevin_credentials",
    "plan_civitai_extracted_runtime",
    "doctor_green",
    "gold",
    "VISUAL_QA_PASS_BOUNDED",
    "Main-complete",
    "PRODUCTION_EVIDENCE_PASS",
)


class CivitaiWorkflowIntakeStaticError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha(document: Mapping[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def bind_intake_memo(*, memo: Path = INTAKE_MEMO) -> dict[str, Any]:
    """Prove the tracked intake memo exists and carries required admission text."""

    if not memo.is_file():
        raise CivitaiWorkflowIntakeStaticError(f"intake_memo_missing:{memo.as_posix()}")
    text = memo.read_text(encoding="utf-8")
    if len(text.strip()) < 64:
        raise CivitaiWorkflowIntakeStaticError("intake_memo_too_short")
    missing = [marker for marker in MEMO_REQUIRED_MARKERS if marker not in text]
    if missing:
        raise CivitaiWorkflowIntakeStaticError("intake_memo_missing_markers:" + ",".join(missing))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "path": memo.as_posix(),
        "sha256": digest,
        "bytes": len(text.encode("utf-8")),
        "required_markers_present": True,
    }


def load_classifications(*, path: Path = CLASSIFICATIONS) -> dict[str, Any]:
    if not path.is_file():
        raise CivitaiWorkflowIntakeStaticError(f"classifications_missing:{path.as_posix()}")
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_classification_admission(
    classifications: Mapping[str, Any],
) -> dict[str, Any]:
    """Fail-closed admission over the tracked classifications view (no Plan/Civitai tree)."""

    policy = classifications.get("policy")
    if not isinstance(policy, Mapping):
        raise CivitaiWorkflowIntakeStaticError("classifications_policy_missing")
    if policy.get("mask_authority") != "none":
        raise CivitaiWorkflowIntakeStaticError("mask_authority_not_none")
    if (
        policy.get("training_or_gold_requires_separate_license_provenance_consent_review")
        is not True
    ):
        raise CivitaiWorkflowIntakeStaticError("license_provenance_gate_missing")

    records = classifications.get("records")
    if not isinstance(records, list) or len(records) != EXPECTED_RECORD_COUNT:
        raise CivitaiWorkflowIntakeStaticError(
            f"record_count_mismatch:{len(records) if isinstance(records, list) else 'invalid'}"
        )

    identities = {(record.get("id"), record.get("file_name")) for record in records}
    if len(identities) != EXPECTED_RECORD_COUNT:
        raise CivitaiWorkflowIntakeStaticError("duplicate_or_missing_identities")

    counts = Counter(str(record.get("classification")) for record in records)
    if dict(counts) != EXPECTED_CLASSIFICATION_COUNTS:
        raise CivitaiWorkflowIntakeStaticError(f"classification_counts_mismatch:{dict(counts)}")

    for record in records:
        if record.get("authority") != "proposal_or_reference_only":
            raise CivitaiWorkflowIntakeStaticError(
                f"authority_not_proposal_only:{record.get('file_name')}"
            )

    rejected = {
        str(record.get("file_name"))
        for record in records
        if record.get("classification") == "reject"
    }
    if rejected != EXPECTED_REJECTED_FILES:
        raise CivitaiWorkflowIntakeStaticError(f"reject_set_mismatch:{sorted(rejected)}")

    return {
        "record_count": EXPECTED_RECORD_COUNT,
        "classification_counts": dict(EXPECTED_CLASSIFICATION_COUNTS),
        "mask_authority": "none",
        "authority_uniform": "proposal_or_reference_only",
        "license_provenance_gate": True,
        "rejected_files": sorted(EXPECTED_REJECTED_FILES),
    }


def evaluate_metadata_disposition(classifications: Mapping[str, Any]) -> dict[str, Any]:
    """Prove HTTP-401 metadata-only variants need no paid/manual download for STATIC admission."""

    records = classifications["records"]
    metadata_only = [
        record for record in records if record.get("download_status") == "metadata_only"
    ]
    if len(metadata_only) != EXPECTED_METADATA_ONLY_COUNT:
        raise CivitaiWorkflowIntakeStaticError(f"metadata_only_count_mismatch:{len(metadata_only)}")

    for record in metadata_only:
        name = str(record.get("file_name"))
        expected_replacement = METADATA_ONLY_REPLACEMENTS.get(name)
        if expected_replacement is None:
            raise CivitaiWorkflowIntakeStaticError(f"unexpected_metadata_only:{name}")
        if record.get("metadata_only_disposition") != "superseded_by_downloaded_variant":
            raise CivitaiWorkflowIntakeStaticError(f"metadata_disposition_wrong:{name}")
        if record.get("download_action") != "unnecessary":
            raise CivitaiWorkflowIntakeStaticError(f"metadata_download_not_unnecessary:{name}")
        superseded = record.get("superseded_by") or []
        if expected_replacement not in superseded:
            raise CivitaiWorkflowIntakeStaticError(f"metadata_replacement_missing:{name}")

    return {
        "metadata_only_count": EXPECTED_METADATA_ONLY_COUNT,
        "download_action": "unnecessary",
        "disposition": "superseded_by_downloaded_variant",
        "paid_download_required": False,
        "kevin_credentials_required": False,
        "manual_browser_download_required": False,
        "replacements": dict(METADATA_ONLY_REPLACEMENTS),
    }


def evaluate_workflow_admissions(classifications: Mapping[str, Any]) -> dict[str, Any]:
    """Admit documented workflows from tracked classification + frozen intake contracts."""

    by_name = {str(record.get("file_name")): record for record in classifications["records"]}
    results: dict[str, Any] = {}
    for archive_name, contract in WORKFLOW_ADMISSIONS.items():
        record = by_name.get(archive_name)
        if record is None:
            raise CivitaiWorkflowIntakeStaticError(f"workflow_archive_missing:{archive_name}")
        if record.get("classification") != contract["classification"]:
            raise CivitaiWorkflowIntakeStaticError(
                f"workflow_classification_mismatch:{archive_name}"
            )
        if record.get("authority") != contract["authority"]:
            raise CivitaiWorkflowIntakeStaticError(f"workflow_authority_mismatch:{archive_name}")
        if contract["direct_gold_promotion"] is not False:
            raise CivitaiWorkflowIntakeStaticError(f"workflow_gold_allowed:{archive_name}")
        if contract["requires_paid_download"] or contract["requires_kevin_credentials"]:
            raise CivitaiWorkflowIntakeStaticError(
                f"workflow_requires_external_access:{archive_name}"
            )
        results[archive_name] = {
            "workflow_json": contract["workflow_json"],
            "classification": contract["classification"],
            "authority": contract["authority"],
            "mask_authority": contract["mask_authority"],
            "direct_gold_promotion": False,
            "admitted_for_static_reference": True,
            "requires_paid_download": False,
            "requires_kevin_credentials": False,
        }
    return results


def evaluate_license_provenance_gate(
    *,
    claim_direct_gold: bool = False,
    claim_training_without_review: bool = False,
    claim_paid_download_required: bool = False,
    claim_kevin_credentials_required: bool = False,
) -> dict[str, Any]:
    """Executable license/provenance refuse paths for Civitai outputs."""

    if claim_direct_gold:
        raise CivitaiWorkflowIntakeStaticError("direct_gold_promotion_refused")
    if claim_training_without_review:
        raise CivitaiWorkflowIntakeStaticError(
            "training_without_license_provenance_consent_review_refused"
        )
    if claim_paid_download_required:
        raise CivitaiWorkflowIntakeStaticError("paid_download_not_required_for_static_admission")
    if claim_kevin_credentials_required:
        raise CivitaiWorkflowIntakeStaticError(
            "kevin_credentials_not_required_for_static_admission"
        )
    return {
        "gates": list(LICENSE_PROVENANCE_GATES),
        "direct_gold_allowed": False,
        "training_without_review_allowed": False,
        "paid_download_required": False,
        "kevin_credentials_required": False,
    }


def refuse_civitai_intake_overclaim(report: Mapping[str, Any]) -> None:
    forbidden_true = (
        ("direct_gold_promotion_claimed", "gold_overclaim"),
        ("paid_download_claimed", "paid_download_overclaim"),
        ("kevin_credentials_claimed", "kevin_credentials_overclaim"),
        ("plan_civitai_extracted_runtime_claimed", "extracted_runtime_overclaim"),
        ("doctor_green_claimed", "doctor_green_overclaim"),
        ("gold_claimed", "gold_overclaim"),
        ("visual_qa_pass_claimed", "visual_qa_overclaim"),
        ("main_complete_claimed", "main_complete_overclaim"),
        ("production_evidence_pass_claimed", "production_evidence_overclaim"),
    )
    for field, reason in forbidden_true:
        if report.get(field) is True:
            raise CivitaiWorkflowIntakeStaticError(reason)


def run_civitai_workflow_intake_static_suite(
    *,
    memo: Path = INTAKE_MEMO,
    classifications_path: Path = CLASSIFICATIONS,
) -> dict[str, Any]:
    """Execute Civitai workflow intake STATIC binders and seal a schema-valid report."""

    memo_binding = bind_intake_memo(memo=memo)
    classifications = load_classifications(path=classifications_path)
    classification_admission = evaluate_classification_admission(classifications)
    metadata = evaluate_metadata_disposition(classifications)
    workflows = evaluate_workflow_admissions(classifications)
    license_gate = evaluate_license_provenance_gate()

    # Negative fixtures: overclaims must fail closed.
    try:
        evaluate_license_provenance_gate(claim_direct_gold=True)
        raise CivitaiWorkflowIntakeStaticError("direct_gold_negative_fixture_passed")
    except CivitaiWorkflowIntakeStaticError as exc:
        if exc.reason != "direct_gold_promotion_refused":
            raise
        gold_negative_blocked = True

    try:
        evaluate_license_provenance_gate(claim_training_without_review=True)
        raise CivitaiWorkflowIntakeStaticError("training_negative_fixture_passed")
    except CivitaiWorkflowIntakeStaticError as exc:
        if "training_without_license_provenance" not in exc.reason:
            raise
        training_negative_blocked = True

    try:
        evaluate_license_provenance_gate(claim_paid_download_required=True)
        raise CivitaiWorkflowIntakeStaticError("paid_download_negative_fixture_passed")
    except CivitaiWorkflowIntakeStaticError as exc:
        if "paid_download_not_required" not in exc.reason:
            raise
        paid_negative_blocked = True

    try:
        evaluate_license_provenance_gate(claim_kevin_credentials_required=True)
        raise CivitaiWorkflowIntakeStaticError("kevin_credentials_negative_fixture_passed")
    except CivitaiWorkflowIntakeStaticError as exc:
        if "kevin_credentials_not_required" not in exc.reason:
            raise
        kevin_negative_blocked = True

    classifications_digest = hashlib.sha256(classifications_path.read_bytes()).hexdigest()

    draft: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "items": [
            "MF-P0-10.01",
            "MF-P0-10.02",
            "MF-P0-10.03",
            "MF-P0-10.04",
            "MF-P0-14.01",
        ],
        "memo_binding": memo_binding,
        "classifications_binding": {
            "path": classifications_path.as_posix(),
            "sha256": classifications_digest,
            "record_count": classification_admission["record_count"],
        },
        "classification_admission": classification_admission,
        "metadata_disposition": metadata,
        "workflow_admissions": workflows,
        "license_provenance_gate": license_gate,
        "checks": {
            "intake_memo_bound": "pass",
            "classification_admission": "pass",
            "metadata_disposition_unnecessary": "pass",
            "workflow_admissions": "pass",
            "license_provenance_gate": "pass",
            "direct_gold_refused": "pass",
            "training_without_review_refused": "pass",
            "paid_download_not_required": "pass",
            "kevin_credentials_not_required": "pass",
        },
        "direct_gold_negative_fixture_blocked": gold_negative_blocked,
        "training_without_review_negative_fixture_blocked": training_negative_blocked,
        "paid_download_negative_fixture_blocked": paid_negative_blocked,
        "kevin_credentials_negative_fixture_blocked": kevin_negative_blocked,
        "direct_gold_promotion_claimed": False,
        "paid_download_claimed": False,
        "kevin_credentials_claimed": False,
        "plan_civitai_extracted_runtime_claimed": False,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "visual_qa_pass_claimed": False,
        "main_complete_claimed": False,
        "production_evidence_pass_claimed": False,
        "honest_non_claims": list(HONEST_NON_CLAIMS),
    }
    refuse_civitai_intake_overclaim(draft)

    digest = _sha(draft)
    draft["report_id"] = f"cwi_{digest[:24]}"
    draft["seal_sha256"] = digest
    draft["sha256"] = _sha({key: value for key, value in draft.items() if key != "sha256"})

    issues = validate_document(draft, "civitai_workflow_intake_static_report")
    if issues:
        detail = "; ".join(
            f"{getattr(issue, 'pointer', None) or '/'}: {issue.message}" for issue in issues
        )
        raise CivitaiWorkflowIntakeStaticError(f"schema_validation_failed:{detail}")
    return draft


__all__ = [
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "CLASSIFICATIONS",
    "EXPECTED_CLASSIFICATION_COUNTS",
    "EXPECTED_METADATA_ONLY_COUNT",
    "EXPECTED_RECORD_COUNT",
    "HONEST_NON_CLAIMS",
    "INTAKE_MEMO",
    "LICENSE_PROVENANCE_GATES",
    "METADATA_ONLY_REPLACEMENTS",
    "PROOF_TIER",
    "SCHEMA_VERSION",
    "WORKFLOW_ADMISSIONS",
    "CivitaiWorkflowIntakeStaticError",
    "bind_intake_memo",
    "evaluate_classification_admission",
    "evaluate_license_provenance_gate",
    "evaluate_metadata_disposition",
    "evaluate_workflow_admissions",
    "load_classifications",
    "refuse_civitai_intake_overclaim",
    "run_civitai_workflow_intake_static_suite",
]
