"""Pooled risk-bucket certificates for autonomous mask acceptance."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import NormalDist
from typing import Any, Callable, Mapping, Sequence

import yaml

from ..datasets.authority import require_partition_capability
from ..qa.checks import run_qc001_010
from ..truth_tiers import validate_truth_tier_policy
from ..validation import validate_document
from .risk_buckets import (
    RiskBucketError,
    canonical_sha256,
    load_risk_bucket_policy,
    verify_exchangeability_evidence,
)
from .stability import StabilityError, load_stability_policy, verify_stability_evidence

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class AutonomyCalibrationError(RuntimeError):
    """Audit evidence cannot support an autonomous-acceptance decision."""


GoldAuthorityValidator = Callable[[dict[str, Any], Path], None]
MachineAuthorityValidator = Callable[[dict[str, Any], Path], None]


def build_autonomy_pipeline_fingerprint(
    gate_fingerprint: str,
    *,
    components: Mapping[str, Path],
) -> str:
    """Hash every code/config/model identity input that scopes an autonomy certificate."""
    if not isinstance(gate_fingerprint, str) or not gate_fingerprint.strip():
        raise AutonomyCalibrationError("autonomy gate fingerprint is empty")
    if not components:
        raise AutonomyCalibrationError("autonomy pipeline fingerprint has no components")
    records: list[dict[str, str]] = []
    for name, raw_path in sorted(components.items()):
        if not isinstance(name, str) or not name.strip():
            raise AutonomyCalibrationError("autonomy fingerprint component name is empty")
        path = Path(raw_path)
        if path.is_file():
            records.append({"name": name, "sha256": _sha256_file(path)})
            continue
        if not path.is_dir():
            raise AutonomyCalibrationError(
                f"autonomy fingerprint component is missing: {name}={path}"
            )
        files = [
            candidate
            for candidate in sorted(path.rglob("*"))
            if candidate.is_file()
            and "__pycache__" not in candidate.parts
            and candidate.suffix not in {".pyc", ".pyo"}
        ]
        if not files:
            raise AutonomyCalibrationError(
                f"autonomy fingerprint component directory is empty: {name}={path}"
            )
        records.extend(
            {
                "name": f"{name}/{candidate.relative_to(path).as_posix()}",
                "sha256": _sha256_file(candidate),
            }
            for candidate in files
        )
    payload = {
        "schema_version": "1.0.0",
        "gate_fingerprint": gate_fingerprint,
        "components": records,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_autonomy_config(path: Path = Path("configs/autonomous_masks.yaml")) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "enabled",
        "mode",
        "truth_tiers",
        "operational_targets",
        "reporting",
        "tournament",
        "calibration",
        "operations",
        "repair",
        "retraining",
    }:
        raise AutonomyCalibrationError("autonomy config has the wrong top-level contract")
    if document["schema_version"] != "2.0.0" or document["enabled"] is not True:
        raise AutonomyCalibrationError("autonomy config must be enabled schema 2.0.0")
    if document["mode"] != "autonomous_certified_gold":
        raise AutonomyCalibrationError("autonomy mode is invalid")
    try:
        tier_policy = validate_truth_tier_policy(document["truth_tiers"])
    except ValueError as exc:
        raise AutonomyCalibrationError(f"autonomy truth-tier policy is invalid: {exc}") from exc
    targets = document["operational_targets"]
    if (
        set(targets)
        != {
            "target_zero_touch_fraction",
            "maximum_routine_human_touch_fraction",
            "target_manual_pixel_edit_fraction",
            "target_ordinary_part_mean_iou",
            "target_ordinary_boundary_f1",
            "target_hard_anatomy_mean_iou",
            "maximum_cross_instance_bleed_fraction",
            "maximum_left_right_swap_count",
        }
        or not 0 <= float(targets["target_zero_touch_fraction"]) <= 1
        or not 0 <= float(targets["maximum_routine_human_touch_fraction"]) <= 1
        or not 0 <= float(targets["target_manual_pixel_edit_fraction"]) <= 1
        or not 0 <= float(targets["target_ordinary_part_mean_iou"]) <= 1
        or not 0 <= float(targets["target_ordinary_boundary_f1"]) <= 1
        or not 0 <= float(targets["target_hard_anatomy_mean_iou"]) <= 1
        or float(targets["maximum_cross_instance_bleed_fraction"]) != 0.0
        or int(targets["maximum_left_right_swap_count"]) != 0
        or float(targets["target_zero_touch_fraction"])
        + float(targets["maximum_routine_human_touch_fraction"])
        < 1
    ):
        raise AutonomyCalibrationError("autonomy operational targets are invalid")
    reporting = document["reporting"]
    expected_reporting = {
        "schema_version": "2.0.0",
        "throughput": {
            "field": "zero_touch_fraction",
            "label": "Zero-touch throughput",
            "numerator": "zero_touch_packages",
            "denominator": "eligible_packages",
        },
        "truth_tier_breakdown": {
            "label": "Final truth-tier package counts",
            "denominator": "eligible_packages",
            "fields": [
                "human_anchor_gold_packages",
                "autonomous_certified_gold_packages",
                "machine_candidate_packages",
                "weighted_pseudo_label_packages",
            ],
        },
        "human_workload": {
            "label": "Human intervention workload",
            "metrics": {
                "routine_human_touch_fraction": [
                    "routine_human_touched_packages",
                    "eligible_packages",
                ],
                "audited_fraction": ["audited_packages", "eligible_packages"],
                "residual_review_fraction": [
                    "residual_review_packages",
                    "eligible_packages",
                ],
                "human_touches_per_100_images": [
                    "human_touch_count",
                    "eligible_packages",
                ],
                "manual_changed_pixels_per_100k": [
                    "manually_changed_pixels",
                    "predicted_pixels",
                ],
            },
        },
        "blinded_quality": {
            "label": "Blinded quality against human-anchor holdout",
            "truth_tier": "human_anchor_gold",
            "truth_partition": "holdout",
            "metrics": {
                "mean_mask_iou": ["mask_iou_sum", "evaluated_packages"],
                "mean_boundary_f1": ["boundary_f1_sum", "evaluated_packages"],
            },
        },
        "statistical_confidence": {
            "label": "95% one-sided failure-rate upper bounds",
            "confidence_level": 0.95,
            "denominator": "audited_packages",
            "observed_numerators": ["false_accepts", "serious_false_accepts"],
            "bound_methods": {
                "false_accept_upper_bound": "one_sided_wilson",
                "serious_false_accept_upper_bound": "one_sided_clopper_pearson",
            },
        },
        "prohibited_zero_touch_label_terms": ["accuracy", "confidence", "quality"],
    }
    if not isinstance(reporting, dict) or reporting != expected_reporting:
        raise AutonomyCalibrationError(
            "autonomy reporting must preserve exact denominators and keep throughput, truth "
            "tiers, workload, blinded quality, and confidence separate"
        )
    weights = document["tournament"]["weights"]
    if abs(sum(float(value) for value in weights.values()) - 1.0) > 1e-9:
        raise AutonomyCalibrationError("autonomy tournament weights must sum to one")
    calibration = document["calibration"]
    if not 0.95 <= float(calibration["confidence_level"]) < 1:
        raise AutonomyCalibrationError("autonomy confidence must be at least 95 percent")
    if (
        calibration.get("evidence_scope") != "pooled_risk_bucket"
        or not isinstance(calibration.get("risk_bucket_registry"), str)
        or not isinstance(calibration.get("risk_bucket_registry_sha256"), str)
        or not isinstance(calibration.get("stability_registry"), str)
        or not isinstance(calibration.get("stability_registry_sha256"), str)
        or calibration.get("require_candidate_stability") is not True
        or int(calibration.get("minimum_audits_per_risk_bucket", 0)) < 1
        or calibration.get("aggregate_false_accept_bound_method") != "one_sided_wilson"
        or calibration.get("serious_false_accept_bound_method") != "exact_zero_failure"
    ):
        raise AutonomyCalibrationError("autonomy risk-bucket calibration policy is invalid")
    risk_policy_path = _project_path(calibration["risk_bucket_registry"])
    try:
        risk_policy = load_risk_bucket_policy(risk_policy_path)
    except RiskBucketError as exc:
        raise AutonomyCalibrationError(str(exc)) from exc
    if _sha256_file(risk_policy_path) != calibration["risk_bucket_registry_sha256"]:
        raise AutonomyCalibrationError("autonomy risk-bucket registry hash mismatch")
    if canonical_sha256(risk_policy) == "0" * 64:  # pragma: no cover - defensive invariant
        raise AutonomyCalibrationError("autonomy risk-bucket policy canonical hash is invalid")
    stability_policy_path = _project_path(calibration["stability_registry"])
    try:
        load_stability_policy(stability_policy_path)
    except StabilityError as exc:
        raise AutonomyCalibrationError(str(exc)) from exc
    if _sha256_file(stability_policy_path) != calibration["stability_registry_sha256"]:
        raise AutonomyCalibrationError("autonomy stability registry hash mismatch")
    operations = document["operations"]
    if (
        operations["calibrated_status_is_human_gold"] is not False
        or operations.get("calibrated_truth_tier") != "autonomous_certified_gold"
        or operations.get("uncalibrated_truth_tier") != "machine_candidate"
        or operations.get("residual_truth_tier") != "machine_candidate"
        or operations["holdout_may_use_machine_labels"] is not False
        or float(operations["pseudo_label_loss_weight"])
        >= float(operations["human_gold_loss_weight"])
        or float(operations["autonomous_certified_loss_weight"])
        != tier_policy["autonomous_certified_gold"].training_weight
        or float(operations["pseudo_label_loss_weight"])
        != tier_policy["weighted_pseudo_label"].training_weight
        or not 0 < float(operations.get("random_human_audit_fraction", 0)) <= 1
        or not 0 <= float(operations.get("risk_oversample_fraction", -1)) <= 1
        or int(operations.get("minimum_audits_per_high_risk_bucket", 0)) < 1
    ):
        raise AutonomyCalibrationError("autonomy truth/training authority boundary is invalid")
    repair = document["repair"]
    if (
        not isinstance(repair, dict)
        or repair.get("enabled") is not True
        or repair.get("coordinate_space") != "roi_normalized_0_1000"
        or repair.get("publish_only_to_reversible_review_draft") is not True
        or not 0 <= float(repair.get("maximum_outside_roi_fraction", -1)) <= 0.05
        or not 0 <= float(repair.get("maximum_protected_overlap_fraction", -1)) <= 0.05
        or not 0 < float(repair.get("ordinary_max_changed_fraction", 0)) <= 1
        or float(repair.get("reconstruction_max_changed_fraction", 0)) < 1
        or not 0.95 <= float(repair.get("target_reviewer_pass_confidence", 0)) <= 1
        or not 0.7 <= float(repair.get("minimum_advisory_pass_confidence", 0)) <= 0.95
        or int(repair.get("minimum_independent_pass_reviewers", 0)) < 3
        or not 0 <= float(repair.get("complete_map_score_tolerance", -1)) <= 0.01
        or not 1 <= int(repair.get("maximum_attempts_per_label", 0)) <= 10
        or float(repair.get("maximum_elapsed_seconds_per_label", 0)) <= 0
        or float(repair.get("maximum_resource_units_per_label", 0)) <= 0
        or not 1 <= int(repair.get("maximum_no_progress_attempts", 0)) <= 10
        or not 0 <= int(repair.get("minimum_score_improvement_ppm", -1)) <= 1_000_000
    ):
        raise AutonomyCalibrationError("autonomy repair contract is invalid")
    review_draft = operations.get("review_draft")
    if (
        not isinstance(review_draft, dict)
        or review_draft.get("enabled") is not True
        or review_draft.get("status") != "pre_review_improvement"
        or not 0 <= float(review_draft.get("minimum_score", -1)) <= 1
        or not 0 <= float(review_draft.get("minimum_score_delta", -1)) <= 1
        or not 0 <= float(review_draft.get("minimum_verified_better_confidence", -1)) <= 1
        or review_draft.get("apply_if_baseline_hard_vetoed") is not True
        or review_draft.get("require_incremental_full_map_qa") is not True
        or review_draft.get("require_final_full_map_qa") is not True
    ):
        raise AutonomyCalibrationError("autonomy review-draft safety boundary is invalid")
    retraining = document["retraining"]
    if (
        int(retraining["minimum_new_human_corrections"]) < 1
        or int(retraining["minimum_audit_failures"]) < 1
        or retraining["require_frozen_human_holdout_evaluation"] is not True
    ):
        raise AutonomyCalibrationError("autonomy retraining boundary is invalid")
    return document


def build_autonomy_certificate(
    audit_path: Path,
    *,
    label: str,
    context: str,
    instance_context: str = "solo",
    risk_bucket: str | None = None,
    pooling_evidence: Mapping[str, Any] | None = None,
    risk_bucket_policy_path: Path | None = None,
    stability_evidence: Sequence[Mapping[str, Any]] | None = None,
    stability_policy_path: Path | None = None,
    pipeline_fingerprint: str,
    policy: dict[str, Any],
    now: datetime | None = None,
    gold_packages_root: Path = Path("data/packages"),
    gold_authority_validator: GoldAuthorityValidator | None = None,
    machine_artifacts_root: Path = Path("runs"),
    machine_authority_validator: MachineAuthorityValidator | None = None,
) -> dict[str, Any]:
    """Build a hash-bound pooled certificate from frozen human-anchor audits."""
    explicit_risk_bucket = risk_bucket is not None
    bucket = risk_bucket or context
    if instance_context not in {"solo", "duo", "small_group"}:
        raise AutonomyCalibrationError("autonomy certificate instance context is invalid")
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (label, context, bucket, pipeline_fingerprint)
    ):
        raise AutonomyCalibrationError("autonomy certificate scope is empty")
    raw = Path(audit_path).read_bytes()
    document = json.loads(raw)
    if set(document) != {"schema_version", "frozen", "image_disjoint", "records"}:
        raise AutonomyCalibrationError("autonomy audit corpus has the wrong top-level shape")
    audit_schema = document["schema_version"]
    if audit_schema not in {"1.0.0", "2.0.0"} or document["frozen"] is not True:
        raise AutonomyCalibrationError(
            "autonomy audit corpus must be schema 1.0.0/2.0.0 and frozen"
        )
    if not isinstance(document["records"], list) or any(
        not isinstance(record, dict) for record in document["records"]
    ):
        raise AutonomyCalibrationError("autonomy audit records must be objects")
    if policy["require_image_disjoint_holdout"] is True and document["image_disjoint"] is not True:
        raise AutonomyCalibrationError("autonomy audit corpus is not image-disjoint")
    records = []
    for record in document["records"]:
        record_bucket = record.get("risk_bucket", record.get("context"))
        if record_bucket == bucket and record.get("machine_accepted") is True:
            records.append(record)
    required = {
        "record_id",
        "image_id",
        "label",
        "context",
        "machine_accepted",
        "human_defect",
        "serious_defect",
        "pipeline_fingerprint",
        "audit_authority",
        "auditor",
        "audited_at",
        "gold_package_path",
        "gold_manifest_sha256",
        "gold_freeze_sha256",
        "gold_mask_sha256",
        "machine_lifecycle_path",
        "machine_lifecycle_sha256",
        "machine_mask_path",
        "machine_mask_sha256",
    }
    if audit_schema == "2.0.0":
        required.add("risk_bucket")
    if any(not isinstance(record, dict) or set(record) != required for record in records):
        raise AutonomyCalibrationError("autonomy audit record has the wrong shape")
    if len({record["record_id"] for record in records}) != len(records):
        raise AutonomyCalibrationError("autonomy audit record IDs are not unique")
    if len({record["image_id"] for record in records}) != len(records):
        raise AutonomyCalibrationError("autonomy audit images are not disjoint")
    for record in records:
        if (
            record["audit_authority"] not in {"human_anchor_gold", "human_approved_gold_only"}
            or not isinstance(record["auditor"], str)
            or not record["auditor"].strip()
            or not isinstance(record["human_defect"], bool)
            or not isinstance(record["serious_defect"], bool)
            or record["serious_defect"] is True
            and record["human_defect"] is not True
        ):
            raise AutonomyCalibrationError("autonomy audit human authority is invalid")
        try:
            audited_at = datetime.fromisoformat(str(record["audited_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise AutonomyCalibrationError("autonomy audit timestamp is invalid") from exc
        if audited_at.tzinfo is None:
            raise AutonomyCalibrationError("autonomy audit timestamp must include a timezone")
        if any(
            not isinstance(record[key], str)
            or len(record[key]) != 64
            or any(character not in "0123456789abcdef" for character in record[key])
            for key in (
                "gold_manifest_sha256",
                "gold_freeze_sha256",
                "gold_mask_sha256",
                "machine_lifecycle_sha256",
                "machine_mask_sha256",
            )
        ):
            raise AutonomyCalibrationError("autonomy audit artifact hash is invalid")
    strata = sorted({f"{record['label']}::{record['context']}" for record in records})
    risk_policy_sha256 = None
    pooling_evidence_sha256 = None
    stability_evidence_sha256s: list[str] = []
    if len(strata) > 1 and not explicit_risk_bucket:
        raise AutonomyCalibrationError(
            "cross-stratum pooling requires an explicit registered risk bucket"
        )
    if explicit_risk_bucket:
        configured_policy_path = risk_bucket_policy_path or _project_path(
            str(policy.get("risk_bucket_registry", "configs/autonomy_risk_buckets.yaml"))
        )
        try:
            risk_policy = load_risk_bucket_policy(configured_policy_path)
        except RiskBucketError as exc:
            raise AutonomyCalibrationError(str(exc)) from exc
        expected_policy_file_hash = policy.get("risk_bucket_registry_sha256")
        if (
            not isinstance(expected_policy_file_hash, str)
            or _sha256_file(configured_policy_path) != expected_policy_file_hash
        ):
            raise AutonomyCalibrationError("autonomy risk-bucket registry hash mismatch")
        risk_policy_sha256 = canonical_sha256(risk_policy)
        exchangeability_records = [
            {
                "record_id": record["record_id"],
                "risk_bucket": bucket,
                "stratum": f"{record['label']}::{record['context']}",
                "human_defect": record["human_defect"],
                "serious_defect": record["serious_defect"],
            }
            for record in records
        ]
        if len(strata) > 1 and pooling_evidence is None:
            raise AutonomyCalibrationError(
                "cross-stratum pooling requires empirical exchangeability evidence"
            )
        if pooling_evidence is not None:
            try:
                verify_exchangeability_evidence(
                    pooling_evidence,
                    exchangeability_records,
                    risk_bucket=bucket,
                    policy=risk_policy,
                )
            except RiskBucketError as exc:
                raise AutonomyCalibrationError(str(exc)) from exc
            pooling_evidence_sha256 = str(pooling_evidence["sha256"])
        configured_stability_path = stability_policy_path or _project_path(
            str(policy.get("stability_registry", "configs/autonomy_stability.yaml"))
        )
        try:
            stability_policy = load_stability_policy(configured_stability_path)
        except StabilityError as exc:
            raise AutonomyCalibrationError(str(exc)) from exc
        expected_stability_file_hash = policy.get("stability_registry_sha256")
        if (
            not isinstance(expected_stability_file_hash, str)
            or _sha256_file(configured_stability_path) != expected_stability_file_hash
        ):
            raise AutonomyCalibrationError("autonomy stability registry hash mismatch")
        stability_rows = list(stability_evidence or ())
        expected_labels = {str(record["label"]) for record in records}
        if {str(row.get("label")) for row in stability_rows} != expected_labels:
            raise AutonomyCalibrationError(
                "candidate stability evidence must cover every certified label exactly"
            )
        for row in stability_rows:
            try:
                verify_stability_evidence(
                    row,
                    pipeline_fingerprint=pipeline_fingerprint,
                    risk_bucket=bucket,
                    policy=stability_policy,
                )
            except StabilityError as exc:
                raise AutonomyCalibrationError(str(exc)) from exc
            stability_evidence_sha256s.append(str(row["sha256"]))
        stability_evidence_sha256s.sort()
    if policy["require_exact_pipeline_fingerprint"] is True and any(
        record["pipeline_fingerprint"] != pipeline_fingerprint for record in records
    ):
        raise AutonomyCalibrationError("autonomy audit pipeline fingerprint mismatch")
    validate_gold = gold_authority_validator or verify_human_gold_audit_record
    validate_machine = machine_authority_validator or verify_machine_audit_record
    for record in records:
        validate_gold(record, Path(gold_packages_root))
        validate_machine(record, Path(machine_artifacts_root))
    sample_count = len(records)
    false_accepts = sum(record["human_defect"] is True for record in records)
    serious_false_accepts = sum(record["serious_defect"] is True for record in records)
    confidence = float(policy["confidence_level"])
    false_upper = _wilson_upper(false_accepts, sample_count, confidence)
    serious_upper = _exact_zero_failure_upper(serious_false_accepts, sample_count, confidence)
    failures = []
    minimum_floor = int(policy["minimum_audits_per_risk_bucket"])
    if sample_count < minimum_floor:
        failures.append("insufficient_risk_bucket_audits")
    if false_upper > float(policy["maximum_false_accept_upper_bound"]):
        failures.append("false_accept_upper_bound_exceeded")
    if serious_upper > float(policy["maximum_serious_false_accept_upper_bound"]):
        failures.append("serious_false_accept_upper_bound_exceeded")
    issued = (now or datetime.now(UTC)).astimezone(UTC)
    expires = issued + timedelta(days=int(policy["maximum_certificate_age_days"]))
    certificate = {
        "schema_version": "2.0.0",
        "audit_authority": "human_anchor_gold",
        "certificate_id": hashlib.sha256(
            f"{bucket}\0{instance_context}\0{pipeline_fingerprint}\0"
            f"{hashlib.sha256(raw).hexdigest()}".encode()
        ).hexdigest()[:24],
        "risk_bucket": bucket,
        "instance_context": instance_context,
        "covered_labels": sorted({str(record["label"]) for record in records}),
        "covered_contexts": sorted({str(record["context"]) for record in records}),
        "pipeline_fingerprint": pipeline_fingerprint,
        "audit_sha256": hashlib.sha256(raw).hexdigest(),
        "risk_bucket_policy_sha256": risk_policy_sha256,
        "pooling_evidence_sha256": pooling_evidence_sha256,
        "stability_evidence_sha256s": stability_evidence_sha256s,
        "sample_count": sample_count,
        "false_accept_count": false_accepts,
        "serious_false_accept_count": serious_false_accepts,
        "confidence_level": confidence,
        "minimum_audits_per_risk_bucket": minimum_floor,
        "aggregate_false_accept_bound_method": "one_sided_wilson",
        "serious_false_accept_bound_method": "exact_zero_failure",
        "zero_failure_sample_requirement": {
            "false_accept": _minimum_zero_failure_sample(
                float(policy["maximum_false_accept_upper_bound"]), confidence
            ),
            "serious_false_accept": _minimum_zero_failure_sample(
                float(policy["maximum_serious_false_accept_upper_bound"]), confidence
            ),
        },
        "false_accept_upper_bound": false_upper,
        "serious_false_accept_upper_bound": serious_upper,
        "issued_at": issued.isoformat().replace("+00:00", "Z"),
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
        "passed": not failures,
        "failures": failures,
    }
    certificate["sha256"] = hashlib.sha256(
        json.dumps(certificate, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return certificate


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def verify_autonomy_certificate(
    certificate: dict[str, Any] | None,
    *,
    label: str,
    context: str,
    instance_context: str = "solo",
    pipeline_fingerprint: str,
    risk_bucket: str | None = None,
    allow_legacy: bool = False,
    now: datetime | None = None,
) -> tuple[bool, str]:
    if instance_context not in {"solo", "duo", "small_group"}:
        return False, "certificate_instance_context_invalid"
    if not certificate or certificate.get("passed") is not True:
        return False, "certificate_absent_or_failed"
    schema_version = certificate.get("schema_version")
    if schema_version == "1.1.0":
        if not allow_legacy:
            return False, "legacy_certificate_not_authoritative_for_autonomous_gold"
        if certificate.get("audit_authority") != "human_approved_gold_only":
            return False, "certificate_human_anchor_authority_missing"
    elif schema_version != "2.0.0" or certificate.get("audit_authority") != "human_anchor_gold":
        return False, "certificate_human_anchor_authority_missing"
    claimed = certificate.get("sha256")
    payload = {key: value for key, value in certificate.items() if key != "sha256"}
    actual = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if claimed != actual:
        return False, "certificate_hash_mismatch"
    if schema_version == "1.1.0":
        scope_matches = certificate.get("label") == label and certificate.get("context") == context
    else:
        bucket = risk_bucket or context
        covered_labels = certificate.get("covered_labels", ())
        covered_contexts = certificate.get("covered_contexts", ())
        scope_matches = (
            certificate.get("risk_bucket") == bucket
            and certificate.get("instance_context", "solo") == instance_context
            and label in covered_labels
            and context in covered_contexts
        )
    if not scope_matches or certificate.get("pipeline_fingerprint") != pipeline_fingerprint:
        return False, "certificate_scope_mismatch"
    current = (now or datetime.now(UTC)).astimezone(UTC)
    expires = datetime.fromisoformat(str(certificate["expires_at"]).replace("Z", "+00:00"))
    if current >= expires:
        return False, "certificate_expired"
    return True, "certificate_valid"


def verify_human_gold_audit_record(record: dict[str, Any], packages_root: Path) -> None:
    """Prove one certificate row is anchored to an immutable approved-gold package."""
    relative = Path(str(record["gold_package_path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise AutonomyCalibrationError("gold package path must stay below the package root")
    root = Path(packages_root).resolve()
    package = (root / relative).resolve()
    try:
        package.relative_to(root)
    except ValueError as exc:
        raise AutonomyCalibrationError("gold package escaped the package root") from exc
    manifest_path = package / "manifest.json"
    freeze_path = package / ".maskfactory_frozen.json"
    if not manifest_path.is_file() or not freeze_path.is_file():
        raise AutonomyCalibrationError("gold package manifest or freeze marker is missing")
    if _sha256_file(manifest_path) != record["gold_manifest_sha256"]:
        raise AutonomyCalibrationError("gold package manifest hash mismatch")
    if _sha256_file(freeze_path) != record["gold_freeze_sha256"]:
        raise AutonomyCalibrationError("gold package freeze hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failed_qc = tuple(result.qc_id for result in run_qc001_010(package) if not result.passed)
    if failed_qc:
        raise AutonomyCalibrationError(
            "gold package failed current hard QA: " + ", ".join(failed_qc)
        )
    review = manifest.get("review", {})
    part = manifest.get("parts", {}).get(record["label"], {})
    manifest_tier = manifest.get("truth_tier")
    anchor_authority = manifest_tier in {None, "human_anchor_gold"}
    anchor_partition = manifest.get("truth_partition")
    if anchor_partition is not None:
        try:
            require_partition_capability(anchor_partition, "certificate_fitter")
        except ValueError:
            anchor_authority = False
    if (
        manifest.get("image_id") != record["image_id"]
        or manifest.get("workflow_status") != "approved_gold"
        or not anchor_authority
        or manifest.get("qa", {}).get("qa_overall") != "pass"
        or not isinstance(review.get("reviewer"), str)
        or not review["reviewer"].strip()
        or not review.get("approved_at")
        or part.get("status") not in {"human_approved_gold", "human_anchor_gold"}
    ):
        raise AutonomyCalibrationError("package does not carry human-anchor calibration authority")
    mask_relative = Path(str(part.get("mask_file", "")))
    if mask_relative.is_absolute() or ".." in mask_relative.parts or not mask_relative.parts:
        raise AutonomyCalibrationError("gold label mask path is invalid")
    mask_path = (package / mask_relative).resolve()
    try:
        mask_path.relative_to(package)
    except ValueError as exc:
        raise AutonomyCalibrationError("gold label mask escaped the package") from exc
    mask_hash = record["gold_mask_sha256"]
    if (
        not mask_path.is_file()
        or _sha256_file(mask_path) != mask_hash
        or part.get("mask_sha256") != mask_hash
        or manifest.get("files", {}).get(mask_relative.as_posix()) != mask_hash
    ):
        raise AutonomyCalibrationError("gold label mask authority hash mismatch")
    frozen = json.loads(freeze_path.read_text(encoding="utf-8"))
    if frozen.get("reviewer") != review["reviewer"]:
        raise AutonomyCalibrationError("gold freeze reviewer differs from the manifest")


def verify_machine_audit_record(record: dict[str, Any], artifacts_root: Path) -> None:
    """Prove one audit row refers to a real pipeline-selected machine mask."""
    root = Path(artifacts_root).resolve()
    paths: dict[str, Path] = {}
    for key in ("machine_lifecycle_path", "machine_mask_path"):
        relative = Path(str(record[key]))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise AutonomyCalibrationError("machine audit artifact path is invalid")
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise AutonomyCalibrationError("machine audit artifact escaped its root") from exc
        if not path.is_file():
            raise AutonomyCalibrationError("machine audit artifact is missing")
        paths[key] = path
    lifecycle_path = paths["machine_lifecycle_path"]
    mask_path = paths["machine_mask_path"]
    if _sha256_file(lifecycle_path) != record["machine_lifecycle_sha256"]:
        raise AutonomyCalibrationError("machine lifecycle hash mismatch")
    if _sha256_file(mask_path) != record["machine_mask_sha256"]:
        raise AutonomyCalibrationError("machine mask hash mismatch")
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    if validate_document(lifecycle, "autonomy_lifecycle"):
        raise AutonomyCalibrationError("machine lifecycle contract is invalid")
    winner_id = lifecycle.get("winner_id")
    winner_rows = [
        row for row in lifecycle.get("ranking", ()) if row.get("candidate_id") == winner_id
    ]
    if (
        lifecycle.get("image_id") != record["image_id"]
        or lifecycle.get("label") != record["label"]
        or lifecycle.get("context") != record["context"]
        or lifecycle.get("pipeline_fingerprint") != record["pipeline_fingerprint"]
        or lifecycle.get("status") not in {"machine_verified_candidate", "calibrated_auto_accepted"}
        or lifecycle.get("winner_mask_sha256") != record["machine_mask_sha256"]
        or len(winner_rows) != 1
        or winner_rows[0].get("mask_sha256") != record["machine_mask_sha256"]
    ):
        raise AutonomyCalibrationError("machine lifecycle does not prove the audited winner")


def _wilson_upper(defects: int, total: int, confidence: float) -> float:
    if total <= 0 or defects < 0 or defects > total or not 0.5 < confidence < 1:
        return 1.0
    z = NormalDist().inv_cdf(confidence)
    rate = defects / total
    denominator = 1 + z * z / total
    center = rate + z * z / (2 * total)
    radius = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total))
    return min(1.0, (center + radius) / denominator)


def _exact_zero_failure_upper(defects: int, total: int, confidence: float) -> float:
    """Conservative exact upper bound for a zero-tolerance serious-failure lane."""
    if total <= 0 or defects < 0 or defects > total or not 0.5 < confidence < 1:
        return 1.0
    if defects:
        return 1.0
    return 1.0 - (1.0 - confidence) ** (1.0 / total)


def _minimum_zero_failure_sample(maximum_rate: float, confidence: float) -> int:
    """Power calculation: samples needed for a zero-event exact upper bound."""
    if not 0 < maximum_rate < 1 or not 0.5 < confidence < 1:
        raise AutonomyCalibrationError("risk-bucket rate/confidence target is invalid")
    return math.ceil(math.log(1.0 - confidence) / math.log(1.0 - maximum_rate))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "AutonomyCalibrationError",
    "build_autonomy_certificate",
    "build_autonomy_pipeline_fingerprint",
    "load_autonomy_config",
    "verify_autonomy_certificate",
    "verify_human_gold_audit_record",
    "verify_machine_audit_record",
]
