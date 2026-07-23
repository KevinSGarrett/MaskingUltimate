"""Compile exact real-source deficits for visual-role qualification.

This module does not build a critic corpus and cannot grant visual authority.
It reconciles the existing frozen regression suite, the ontology-v2 real-image
pilot, and the historical CAA quarantine into one deterministic answer to a
narrow question: which canonical labels already have an eligible real-pixel
positive control, and which merely have diagnostic, ambiguous, reference-only,
or quarantined material?
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Mapping
from typing import Any

from ..ontology_v2_authority_pilot import verify_authority_pilot
from .critic_catalog import canonical_sha256
from .real_corpus_policy import ALLOWED_AUTHORITIES
from .regression_suite import required_canonical_v2_labels, validate_regression_suite

SCHEMA_VERSION = "maskfactory.visual_corpus_source_deficits.v1"
ELIGIBLE = "eligible_exact_real_positive"
NONCANONICAL = "noncanonical_or_coarse_diagnostic"
UNQUALIFIED = "exact_label_unqualified_diagnostic"
AMBIGUOUS = "fine_or_laterality_ambiguous"
REFERENCE_ONLY = "reference_only_no_mask_truth"
QUARANTINED = "quarantined_historical"


class VisualCorpusSourceDeficitError(ValueError):
    """Source evidence is malformed or attempts to overstate authority."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _self_sha256(document: Mapping[str, Any]) -> str:
    return canonical_sha256({key: value for key, value in document.items() if key != "self_sha256"})


def _classify_regression_case(
    case: Mapping[str, Any], canonical: frozenset[str]
) -> tuple[str, str]:
    label = str(case["target_contract"]["target"]["label_id"])
    binding = case["source_binding"]
    if label not in canonical:
        return label, NONCANONICAL
    if (
        binding["source_authority"] in ALLOWED_AUTHORITIES
        and binding["real_source_pixels"] is True
        and binding["synthetic"] is False
        and binding["production_draft"] is False
    ):
        return label, ELIGIBLE
    return label, UNQUALIFIED


def build_visual_corpus_source_deficits(
    *,
    regression_manifest: Mapping[str, Any],
    authority_pilot: Mapping[str, Any],
    historical_caa_evidence: Mapping[str, Any],
    input_file_sha256s: Mapping[str, str],
) -> dict[str, Any]:
    """Build a closed, hash-bound 66-label source-authority deficit report."""

    validate_regression_suite(regression_manifest)
    if regression_manifest.get("schema_version") != "2.0.0":
        raise VisualCorpusSourceDeficitError("real regression manifest is required")
    verify_authority_pilot(authority_pilot)
    canonical_labels = required_canonical_v2_labels()
    canonical = frozenset(canonical_labels)
    if set(input_file_sha256s) != {
        "ontology",
        "regression_manifest",
        "authority_pilot",
        "historical_caa_evidence",
    } or any(
        not isinstance(value, str) or len(value) != 64 for value in input_file_sha256s.values()
    ):
        raise VisualCorpusSourceDeficitError("input file hash bindings are incomplete")

    eligible: dict[str, set[str]] = defaultdict(set)
    diagnostic: dict[str, set[str]] = defaultdict(set)
    noncanonical_counts: Counter[str] = Counter()
    regression_classifications: Counter[str] = Counter()
    for case in regression_manifest["cases"]:
        label, classification = _classify_regression_case(case, canonical)
        case_id = str(case["case_id"])
        regression_classifications[classification] += 1
        if classification == ELIGIBLE:
            eligible[label].add(case_id)
        elif classification == UNQUALIFIED:
            diagnostic[label].add(case_id)
        else:
            noncanonical_counts[label] += 1

    pilot_exact: dict[str, set[str]] = defaultdict(set)
    pilot_ambiguous: dict[str, set[str]] = defaultdict(set)
    pilot_reference_count = 0
    for image in authority_pilot["images"]:
        image_id = str(image["image_id"])
        if image["source_kind"] == "reference_library_coverage":
            if (
                image["source_authority"] != REFERENCE_ONLY
                or image["mask_truth_authority"] is not False
            ):
                raise VisualCorpusSourceDeficitError(
                    "reference image attempted to acquire mask authority"
                )
            pilot_reference_count += 1
            continue
        for label, observation in image["observed_semantics"].items():
            if label not in canonical:
                raise VisualCorpusSourceDeficitError(f"pilot observation is not canonical: {label}")
            if observation["state"] == "ambiguous_do_not_use":
                pilot_ambiguous[label].add(image_id)
            else:
                # The pilot explicitly has no mask-truth authority, so even an
                # exact raw label remains diagnostic until separately qualified.
                pilot_exact[label].add(image_id)

    reconciliation = historical_caa_evidence.get("reconciliation")
    classification = historical_caa_evidence.get("authority_classification")
    if not isinstance(reconciliation, Mapping) or not isinstance(classification, Mapping):
        raise VisualCorpusSourceDeficitError("historical CAA evidence is incomplete")
    quarantined_count = reconciliation.get("quarantined_legacy_package_count")
    if (
        not isinstance(quarantined_count, int)
        or quarantined_count < 1
        or reconciliation.get("current_authority_eligible_count") != 0
        or classification.get("training_admission_allowed") is not False
        or classification.get("production_mask_authority_allowed") is not False
    ):
        raise VisualCorpusSourceDeficitError("historical CAA population is not proven fail-closed")

    label_rows = []
    for label in canonical_labels:
        eligible_ids = sorted(eligible[label])
        diagnostic_ids = sorted(diagnostic[label] | pilot_exact[label])
        ambiguous_ids = sorted(pilot_ambiguous[label])
        source_status = (
            "eligible_real_positive_present" if eligible_ids else "missing_qualified_real_positive"
        )
        if eligible_ids:
            next_action = "materialize_frozen_positive_and_seeded_negative_controls"
        elif diagnostic_ids:
            next_action = "qualify_exact_external_annotation_then_materialize_controls"
        elif ambiguous_ids:
            next_action = "acquire_exact_fine_or_laterality_pixel_annotation"
        else:
            next_action = "acquire_exact_real_pixel_annotation"
        label_rows.append(
            {
                "canonical_label": label,
                "source_status": source_status,
                "eligible_exact_real_positive_case_ids": eligible_ids,
                "diagnostic_exact_unqualified_ids": diagnostic_ids,
                "ambiguous_fine_or_laterality_ids": ambiguous_ids,
                "next_action": next_action,
            }
        )

    eligible_labels = [
        row["canonical_label"]
        for row in label_rows
        if row["source_status"] == "eligible_real_positive_present"
    ]
    missing_labels = [
        row["canonical_label"]
        for row in label_rows
        if row["source_status"] != "eligible_real_positive_present"
    ]
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "visual_critic_canonical_source_coverage_and_deficits",
        "authority_claimed": False,
        "promotion_allowed": False,
        "qualification_corpus_ready": False,
        "input_file_sha256s": dict(sorted(input_file_sha256s.items())),
        "input_artifact_sha256s": {
            "regression_suite_sha256": regression_manifest["suite_sha256"],
            "authority_pilot_sha256": authority_pilot["self_sha256"],
            "historical_caa_classification_sha256": historical_caa_evidence[
                "classification_report_sha256"
            ],
        },
        "required_canonical_label_count": len(canonical_labels),
        "eligible_canonical_label_count": len(eligible_labels),
        "missing_canonical_label_count": len(missing_labels),
        "eligible_canonical_labels": eligible_labels,
        "missing_canonical_labels": missing_labels,
        "source_population": {
            "real_regression_case_count": len(regression_manifest["cases"]),
            "regression_case_classifications": dict(sorted(regression_classifications.items())),
            "noncanonical_target_label_counts": dict(sorted(noncanonical_counts.items())),
            "pilot_image_count": authority_pilot["image_count"],
            "pilot_reference_only_count": pilot_reference_count,
            "pilot_exact_but_unqualified_observation_count": sum(
                len(values) for values in pilot_exact.values()
            ),
            "pilot_ambiguous_observation_count": sum(
                len(values) for values in pilot_ambiguous.values()
            ),
            "quarantined_historical_package_count": quarantined_count,
            "quarantined_historical_authority_eligible_count": 0,
        },
        "authority_classes": {
            ELIGIBLE: ("may supply a positive-control source only after exact case construction"),
            NONCANONICAL: "diagnostic only; never canonical-label coverage",
            UNQUALIFIED: "diagnostic only until source qualification is current",
            AMBIGUOUS: "cannot invent fine anatomy or laterality",
            REFERENCE_ONLY: "retrieval and risk coverage only; no pixel truth",
            QUARANTINED: "historical bytes only; no current authority",
        },
        "labels": label_rows,
        "claim_limits": [
            "This artifact inventories source eligibility; it is not a critic corpus.",
            "An eligible source does not become a positive control until its exact target contract, panels, split, and qualification bindings are frozen.",
            "External aliases, coarse or unsided labels, reference-only images, and quarantined historical packages never count as canonical positive coverage.",
            "Visual-role qualification and promotion remain blocked until every required canonical label and risk/domain stratum has valid and serious real-image controls.",
        ],
    }
    document["self_sha256"] = _self_sha256(document)
    verify_visual_corpus_source_deficits(document)
    return document


def verify_visual_corpus_source_deficits(document: Mapping[str, Any]) -> None:
    """Verify the report's closed authority and per-label invariants."""

    required = {
        "schema_version",
        "artifact_type",
        "authority_claimed",
        "promotion_allowed",
        "qualification_corpus_ready",
        "input_file_sha256s",
        "input_artifact_sha256s",
        "required_canonical_label_count",
        "eligible_canonical_label_count",
        "missing_canonical_label_count",
        "eligible_canonical_labels",
        "missing_canonical_labels",
        "source_population",
        "authority_classes",
        "labels",
        "claim_limits",
        "self_sha256",
    }
    if set(document) != required:
        raise VisualCorpusSourceDeficitError("source-deficit fields are not closed")
    if (
        document["schema_version"] != SCHEMA_VERSION
        or document["authority_claimed"] is not False
        or document["promotion_allowed"] is not False
        or document["qualification_corpus_ready"] is not False
        or _self_sha256(document) != document["self_sha256"]
    ):
        raise VisualCorpusSourceDeficitError("source-deficit authority or hash drift")
    canonical = required_canonical_v2_labels()
    rows = document["labels"]
    if (
        not isinstance(rows, list)
        or [row.get("canonical_label") for row in rows] != list(canonical)
        or document["required_canonical_label_count"] != len(canonical)
    ):
        raise VisualCorpusSourceDeficitError("source-deficit label rows are not exact")
    eligible = [
        row["canonical_label"]
        for row in rows
        if row["source_status"] == "eligible_real_positive_present"
    ]
    missing = [
        row["canonical_label"]
        for row in rows
        if row["source_status"] == "missing_qualified_real_positive"
    ]
    if (
        eligible != document["eligible_canonical_labels"]
        or missing != document["missing_canonical_labels"]
        or len(eligible) != document["eligible_canonical_label_count"]
        or len(missing) != document["missing_canonical_label_count"]
        or len(eligible) + len(missing) != len(canonical)
    ):
        raise VisualCorpusSourceDeficitError("source-deficit summary drift")


__all__ = [
    "VisualCorpusSourceDeficitError",
    "build_visual_corpus_source_deficits",
    "sha256_bytes",
    "verify_visual_corpus_source_deficits",
]
