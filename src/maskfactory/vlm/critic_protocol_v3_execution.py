"""Hash-bound, reference-paired execution inputs for critic protocol v3.

The frozen single-board corpus can supply image panels, but it cannot silently
be treated as a v3 run.  This overlay binds every proposed case to an
image-disjoint known-good reference and one exact protocol registry before a
backend is allowed to load.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .calibration_corpus import validate_calibration_corpus
from .critic_catalog import canonical_sha256
from .critic_protocol_v3 import (
    LABEL_SCALES,
    PROTOCOL_ID,
    SOURCE_AUTHORITY_TIERS,
    CriticProtocolV3Error,
    protocol_registry_sha256,
    require_holdout_eligible_registry,
    validate_protocol_registry,
)

EXECUTION_SCHEMA_VERSION = "1.0.0"
EXECUTION_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "execution_id",
        "protocol_id",
        "protocol_version",
        "corpus_sha256",
        "registry_sha256",
        "cases",
        "execution_manifest_sha256",
    }
)
EXECUTION_CASE_KEYS = frozenset(
    {"case_id", "reference_case_id", "source_authority_tier", "label_scale"}
)
EXECUTION_RESULT_KEYS = frozenset({"case_id", "verdict", "serious_dimensions", "minor_dimensions"})


class CriticProtocolV3ExecutionError(ValueError):
    """A protocol-v3 execution overlay is incomplete, leaked, or unbound."""


def execution_manifest_sha256(manifest: Mapping[str, Any]) -> str:
    """Return the canonical identity of a v3 execution overlay."""

    return canonical_sha256(
        {key: value for key, value in manifest.items() if key != "execution_manifest_sha256"}
    )


def _source_sha256(case: Mapping[str, Any]) -> str:
    source = case["target_contract"]["source"]
    return str(source.get("encoded_sha256", source.get("sha256", "")))


def _target_label(case: Mapping[str, Any]) -> str:
    return str(case["target_contract"]["target"]["label_id"])


def _target_roi(case: Mapping[str, Any]) -> list[float]:
    roi = case["target_contract"]["target"]["allowed_roi_xyxy"]
    if not isinstance(roi, Sequence) or isinstance(roi, (str, bytes)) or len(roi) != 4:
        raise CriticProtocolV3ExecutionError("case target ROI is invalid")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in roi):
        raise CriticProtocolV3ExecutionError("case target ROI is invalid")
    if not roi[0] < roi[2] or not roi[1] < roi[3]:
        raise CriticProtocolV3ExecutionError("case target ROI has no area")
    return [float(value) for value in roi]


def validate_protocol_v3_execution_manifest(
    manifest: Mapping[str, Any],
    corpus: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> None:
    """Validate exact case/reference bindings before a v3 backend may start."""

    validate_calibration_corpus(corpus)
    validate_protocol_registry(registry)
    if not isinstance(manifest, Mapping) or set(manifest) != EXECUTION_MANIFEST_KEYS:
        raise CriticProtocolV3ExecutionError("protocol-v3 execution manifest fields are invalid")
    if manifest["schema_version"] != EXECUTION_SCHEMA_VERSION:
        raise CriticProtocolV3ExecutionError("protocol-v3 execution manifest schema is unsupported")
    if manifest["protocol_id"] != PROTOCOL_ID:
        raise CriticProtocolV3ExecutionError("protocol-v3 execution manifest identity is invalid")
    if manifest["protocol_version"] != registry["protocol_version"]:
        raise CriticProtocolV3ExecutionError("protocol-v3 execution registry version drifted")
    if manifest["corpus_sha256"] != corpus["corpus_sha256"]:
        raise CriticProtocolV3ExecutionError("protocol-v3 execution corpus hash drifted")
    if manifest["registry_sha256"] != protocol_registry_sha256(registry):
        raise CriticProtocolV3ExecutionError("protocol-v3 execution registry hash drifted")
    if (
        not isinstance(manifest["execution_id"], str)
        or not manifest["execution_id"].strip()
        or manifest["execution_manifest_sha256"] != execution_manifest_sha256(manifest)
    ):
        raise CriticProtocolV3ExecutionError("protocol-v3 execution manifest identity is unsealed")

    cases = manifest["cases"]
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)) or not cases:
        raise CriticProtocolV3ExecutionError("protocol-v3 execution manifest has no cases")
    corpus_cases = {str(case["case_id"]): case for case in corpus["cases"]}
    candidate_ids: set[str] = set()
    ordered_ids: list[str] = []
    for binding in cases:
        if not isinstance(binding, Mapping) or set(binding) != EXECUTION_CASE_KEYS:
            raise CriticProtocolV3ExecutionError("protocol-v3 execution case fields are invalid")
        case_id = binding["case_id"]
        reference_case_id = binding["reference_case_id"]
        if (
            not isinstance(case_id, str)
            or not case_id
            or not isinstance(reference_case_id, str)
            or not reference_case_id
            or case_id == reference_case_id
            or case_id in candidate_ids
        ):
            raise CriticProtocolV3ExecutionError("protocol-v3 case/reference identity is invalid")
        candidate_ids.add(case_id)
        ordered_ids.append(case_id)
        candidate = corpus_cases.get(case_id)
        reference = corpus_cases.get(reference_case_id)
        if candidate is None or reference is None:
            raise CriticProtocolV3ExecutionError("protocol-v3 case/reference is absent from corpus")
        if candidate["partition"] != reference["partition"]:
            raise CriticProtocolV3ExecutionError("protocol-v3 reference crosses a corpus partition")
        if _source_sha256(candidate) == _source_sha256(reference):
            raise CriticProtocolV3ExecutionError("protocol-v3 reference is not image-disjoint")
        if reference["expected_outcome"] != "valid_mask":
            raise CriticProtocolV3ExecutionError("protocol-v3 reference is not known-good")
        if _target_label(candidate) != _target_label(reference):
            raise CriticProtocolV3ExecutionError("protocol-v3 reference target label drifted")
        if binding["source_authority_tier"] not in SOURCE_AUTHORITY_TIERS:
            raise CriticProtocolV3ExecutionError("protocol-v3 source authority tier is invalid")
        if binding["label_scale"] not in LABEL_SCALES:
            raise CriticProtocolV3ExecutionError("protocol-v3 label scale is invalid")
        _target_roi(candidate)
        if candidate["partition"] == "qualification_holdout":
            try:
                require_holdout_eligible_registry(registry)
            except CriticProtocolV3Error as exc:
                raise CriticProtocolV3ExecutionError(str(exc)) from exc
    if ordered_ids != sorted(ordered_ids):
        raise CriticProtocolV3ExecutionError(
            "protocol-v3 execution cases are not deterministically ordered"
        )


def resolve_protocol_v3_execution_cases(
    manifest: Mapping[str, Any],
    corpus: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Resolve only validated bindings into deterministic runner-ready records."""

    validate_protocol_v3_execution_manifest(manifest, corpus, registry)
    corpus_cases = {str(case["case_id"]): case for case in corpus["cases"]}
    return [
        {
            "case_id": binding["case_id"],
            "reference_case_id": binding["reference_case_id"],
            "partition": corpus_cases[binding["case_id"]]["partition"],
            "expected_outcome": corpus_cases[binding["case_id"]]["expected_outcome"],
            "label_id": _target_label(corpus_cases[binding["case_id"]]),
            "source_authority_tier": binding["source_authority_tier"],
            "label_scale": binding["label_scale"],
            "target_roi_xyxy": _target_roi(corpus_cases[binding["case_id"]]),
            "candidate_panel_set_sha256": corpus_cases[binding["case_id"]]["panel_set_sha256"],
            "reference_panel_set_sha256": corpus_cases[binding["reference_case_id"]][
                "panel_set_sha256"
            ],
        }
        for binding in manifest["cases"]
    ]


def build_calibration_observations(
    execution_cases: Sequence[Mapping[str, Any]],
    derived_results: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Extract fit-eligible rows; defects/holdout evidence never tune a budget."""

    if not isinstance(execution_cases, Sequence) or not isinstance(derived_results, Sequence):
        raise CriticProtocolV3ExecutionError("protocol-v3 execution results are invalid")
    by_case = {str(case["case_id"]): case for case in execution_cases}
    if len(by_case) != len(execution_cases):
        raise CriticProtocolV3ExecutionError("protocol-v3 execution case identities are duplicated")
    results_by_case: dict[str, Mapping[str, Any]] = {}
    for result in derived_results:
        if not isinstance(result, Mapping) or set(result) != EXECUTION_RESULT_KEYS:
            raise CriticProtocolV3ExecutionError("protocol-v3 result fields are invalid")
        case_id = result["case_id"]
        if not isinstance(case_id, str) or case_id not in by_case or case_id in results_by_case:
            raise CriticProtocolV3ExecutionError("protocol-v3 result case identity is invalid")
        if result["verdict"] not in {"pass", "pass_with_findings", "defect", "abstain"}:
            raise CriticProtocolV3ExecutionError("protocol-v3 result verdict is invalid")
        for field in ("serious_dimensions", "minor_dimensions"):
            if not isinstance(result[field], Sequence) or isinstance(result[field], (str, bytes)):
                raise CriticProtocolV3ExecutionError("protocol-v3 result dimensions are invalid")
        results_by_case[case_id] = result
    if set(results_by_case) != set(by_case):
        raise CriticProtocolV3ExecutionError("protocol-v3 execution results are incomplete")

    observations = []
    for case_id, case in sorted(by_case.items()):
        if case["partition"] != "calibration":
            raise CriticProtocolV3ExecutionError(
                "protocol-v3 holdout result may not fit calibration"
            )
        if case["expected_outcome"] != "valid_mask":
            continue
        result = results_by_case[case_id]
        if result["verdict"] not in {"pass", "pass_with_findings"}:
            raise CriticProtocolV3ExecutionError(
                "protocol-v3 valid calibration row did not produce a fit-eligible verdict"
            )
        observations.append(
            {
                "split": "calibration",
                "label_id": case["label_id"],
                "source_authority_tier": case["source_authority_tier"],
                "label_scale": case["label_scale"],
                "expected_outcome": "valid_mask",
                "serious_defect_count": len(result["serious_dimensions"]),
                "minor_finding_count": len(result["minor_dimensions"]),
            }
        )
    if not observations:
        raise CriticProtocolV3ExecutionError("protocol-v3 execution has no valid calibration rows")
    return observations
