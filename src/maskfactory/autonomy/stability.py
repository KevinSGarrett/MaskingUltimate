"""Pre-certification perturbation stability with ontology-aware horizontal flips."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from ..io.hashing import sha256_file
from ..io.png_strict import read_mask
from ..ontology import get_ontology
from ..qa.metrics import boundary_f, iou
from ..validation import ArtifactValidationError, require_valid_document
from .risk_buckets import RISK_BUCKET_NAMES, canonical_sha256

PERTURBATIONS = frozenset({"resize", "crop", "color", "prompt", "horizontal_flip"})
VARIANT_FIELDS = frozenset({"perturbation", "mask_path", "reported_label", "inverse_aligned"})


class StabilityError(ValueError):
    """Candidate stability evidence is incomplete, inconsistent, or tampered."""


def load_stability_policy(
    path: Path = Path("configs/autonomy_stability.yaml"),
) -> dict[str, Any]:
    try:
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise StabilityError(f"cannot load autonomy stability policy: {exc}") from exc
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "policy_id",
        "required_perturbations",
        "boundary_tolerance_px",
        "risk_bucket_thresholds",
    }:
        raise StabilityError("autonomy stability policy has the wrong top-level contract")
    if document["schema_version"] != "1.0.0" or document["policy_id"] != ("candidate_stability_v1"):
        raise StabilityError("autonomy stability policy version is invalid")
    if (
        set(document["required_perturbations"]) != PERTURBATIONS
        or len(document["required_perturbations"]) != len(PERTURBATIONS)
        or set(document["risk_bucket_thresholds"]) != RISK_BUCKET_NAMES
        or not isinstance(document["boundary_tolerance_px"], int)
        or document["boundary_tolerance_px"] < 0
    ):
        raise StabilityError("autonomy stability coverage is incomplete")
    for bucket, threshold in document["risk_bucket_thresholds"].items():
        if not isinstance(threshold, Mapping) or set(threshold) != {
            "certifiable",
            "minimum_iou",
            "minimum_boundary_f",
            "maximum_area_delta",
        }:
            raise StabilityError(f"stability threshold contract is invalid: {bucket}")
        if (
            not isinstance(threshold["certifiable"], bool)
            or not 0 <= float(threshold["minimum_iou"]) <= 1
            or not 0 <= float(threshold["minimum_boundary_f"]) <= 1
            or not 0 <= float(threshold["maximum_area_delta"]) <= 1
        ):
            raise StabilityError(f"stability thresholds are invalid: {bucket}")
    if document["risk_bucket_thresholds"]["out_of_distribution"]["certifiable"] is not False:
        raise StabilityError("out-of-distribution candidates cannot be certifiable")
    return document


def _strict_binary(path: Path) -> np.ndarray:
    array = read_mask(path)
    if (
        array.ndim != 2
        or array.dtype != np.uint8
        or not set(np.unique(array).tolist())
        <= {
            0,
            255,
        }
    ):
        raise StabilityError(f"stability mask is not strict binary grayscale PNG: {path}")
    return array > 0


def evaluate_candidate_stability(
    base_mask_path: Path,
    variants: Sequence[Mapping[str, Any]],
    *,
    candidate_id: str,
    pipeline_fingerprint: str,
    risk_bucket: str,
    label: str,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Inverse-align five perturbations and apply the bucket's frozen thresholds."""
    if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", candidate_id) is None:
        raise StabilityError("candidate stability ID is invalid")
    if not isinstance(pipeline_fingerprint, str) or not pipeline_fingerprint:
        raise StabilityError("candidate stability pipeline fingerprint is empty")
    if risk_bucket not in policy.get("risk_bucket_thresholds", {}):
        raise StabilityError(f"candidate stability risk bucket is unregistered: {risk_bucket}")
    ontology_label = get_ontology().label(label, require_enabled=True)
    indexed: dict[str, Mapping[str, Any]] = {}
    for raw in variants:
        if not isinstance(raw, Mapping) or set(raw) != VARIANT_FIELDS:
            raise StabilityError(
                f"stability variants must contain exactly {sorted(VARIANT_FIELDS)}"
            )
        perturbation = raw["perturbation"]
        if perturbation not in PERTURBATIONS or perturbation in indexed:
            raise StabilityError("stability perturbations are unknown or duplicated")
        if not isinstance(raw["inverse_aligned"], bool):
            raise StabilityError("stability inverse_aligned must be boolean")
        indexed[str(perturbation)] = raw
    if set(indexed) != PERTURBATIONS:
        raise StabilityError("stability evidence does not cover every required perturbation")
    base = _strict_binary(Path(base_mask_path))
    base_area = int(np.count_nonzero(base))
    threshold = policy["risk_bucket_thresholds"][risk_bucket]
    rows = []
    failures: list[str] = []
    for perturbation in policy["required_perturbations"]:
        variant = indexed[perturbation]
        mask_path = Path(variant["mask_path"])
        candidate = _strict_binary(mask_path)
        expected_label = label
        if perturbation == "horizontal_flip":
            if variant["inverse_aligned"] is not False:
                raise StabilityError(
                    "horizontal-flip evidence must be supplied before inverse alignment"
                )
            candidate = np.flip(candidate, axis=1)
            expected_label = ontology_label.swap_partner or label
        elif variant["inverse_aligned"] is not True:
            raise StabilityError(f"{perturbation} mask must be restored to source coordinates")
        if candidate.shape != base.shape:
            raise StabilityError(f"{perturbation} inverse-aligned dimensions differ from baseline")
        reported_label = variant["reported_label"]
        if not isinstance(reported_label, str) or not reported_label:
            raise StabilityError("stability reported label is empty")
        score_iou = iou(base, candidate)
        score_boundary = boundary_f(
            base, candidate, tolerance_px=int(policy["boundary_tolerance_px"])
        )
        candidate_area = int(np.count_nonzero(candidate))
        area_delta = (
            abs(candidate_area - base_area) / base_area
            if base_area
            else (0.0 if candidate_area == 0 else 1.0)
        )
        row_failures = []
        if reported_label != expected_label:
            row_failures.append("swap_partner_label_mismatch")
        if score_iou < float(threshold["minimum_iou"]):
            row_failures.append("minimum_iou_failed")
        if score_boundary < float(threshold["minimum_boundary_f"]):
            row_failures.append("minimum_boundary_f_failed")
        if area_delta > float(threshold["maximum_area_delta"]):
            row_failures.append("maximum_area_delta_failed")
        row_failures = sorted(row_failures)
        failures.extend(f"{perturbation}:{finding}" for finding in row_failures)
        rows.append(
            {
                "perturbation": perturbation,
                "mask_sha256": sha256_file(mask_path),
                "reported_label": reported_label,
                "expected_label": expected_label,
                "iou": score_iou,
                "boundary_f": score_boundary,
                "area_delta": area_delta,
                "passed": not row_failures,
                "failures": row_failures,
            }
        )
    if threshold["certifiable"] is not True:
        failures.append("risk_bucket_not_certifiable")
    evidence = {
        "schema_version": "1.0.0",
        "candidate_id": candidate_id,
        "pipeline_fingerprint": pipeline_fingerprint,
        "risk_bucket": risk_bucket,
        "label": label,
        "policy_id": policy["policy_id"],
        "policy_sha256": canonical_sha256(policy),
        "base_mask_sha256": sha256_file(Path(base_mask_path)),
        "variants": rows,
        "passed": not failures,
        "failures": sorted(failures),
    }
    evidence["sha256"] = canonical_sha256(evidence)
    try:
        require_valid_document(evidence, "autonomy_stability")
    except ArtifactValidationError as exc:
        raise StabilityError(f"candidate stability evidence is invalid: {exc}") from exc
    return evidence


def verify_stability_evidence(
    evidence: Mapping[str, Any],
    *,
    pipeline_fingerprint: str,
    risk_bucket: str,
    policy: Mapping[str, Any],
) -> None:
    try:
        require_valid_document(dict(evidence), "autonomy_stability")
    except ArtifactValidationError as exc:
        raise StabilityError(f"candidate stability evidence is invalid: {exc}") from exc
    if evidence.get("sha256") != canonical_sha256(
        {key: value for key, value in evidence.items() if key != "sha256"}
    ):
        raise StabilityError("candidate stability evidence hash mismatch")
    if evidence.get("policy_sha256") != canonical_sha256(policy):
        raise StabilityError("candidate stability policy hash mismatch")
    if (
        evidence.get("pipeline_fingerprint") != pipeline_fingerprint
        or evidence.get("risk_bucket") != risk_bucket
    ):
        raise StabilityError("candidate stability evidence scope mismatch")
    if evidence.get("passed") is not True or any(
        row.get("passed") is not True for row in evidence.get("variants", ())
    ):
        raise StabilityError("candidate stability gate did not pass")
    if {row.get("perturbation") for row in evidence["variants"]} != PERTURBATIONS:
        raise StabilityError("candidate stability perturbation coverage mismatch")


__all__ = [
    "PERTURBATIONS",
    "StabilityError",
    "evaluate_candidate_stability",
    "load_stability_policy",
    "verify_stability_evidence",
]
