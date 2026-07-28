"""Fail-closed Wilson evaluation for frozen protocol-v3 stage-2 critic boards.

This module evaluates measured model responses.  It does not issue a role
certificate, grant visual authority, or authorize any certificate/gold path.
Those decisions remain separate authority-controlled operations.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .critic_catalog import MODEL_ROLES, canonical_sha256
from .critic_protocol_v3 import PROTOCOL_ID, SOURCE_AUTHORITY_TIERS

SHA256 = re.compile(r"^[a-f0-9]{64}$")
BOARD_SCHEMA_VERSION = "maskfactory.critic_stage2_board.v1"
RESULTS_SCHEMA_VERSION = "maskfactory.critic_stage2_results.v1"
REPORT_SCHEMA_VERSION = "maskfactory.critic_stage2_report.v1"
ONE_SIDED_95_Z = 1.6448536269514722
MINIMUM_CASE_COUNT = 100
MINIMUM_VALID_CASE_COUNT = 40
MINIMUM_SERIOUS_DEFECT_CASE_COUNT = 60
MINIMUM_SERIOUS_RECALL_LOWER_BOUND = 0.90
MINIMUM_VALID_PASS_LOWER_BOUND = 0.80

BOARD_KEYS = frozenset(
    {
        "schema_version",
        "board_id",
        "frozen_at",
        "role_id",
        "protocol_id",
        "registry_sha256",
        "corpus_sha256",
        "execution_manifest_sha256",
        "cases",
        "board_sha256",
    }
)
BOARD_CASE_KEYS = frozenset(
    {
        "case_id",
        "partition",
        "label_id",
        "expected_outcome",
        "expected_severity",
        "source_authority_tier",
        "source_sha256",
        "target_contract_sha256",
        "panel_set_sha256",
    }
)
RESULTS_KEYS = frozenset(
    {
        "schema_version",
        "board_sha256",
        "model_id",
        "family_id",
        "runtime_sha256",
        "artifact_tree_sha256",
        "prompt_sha256",
        "predictions",
        "results_sha256",
    }
)
PREDICTION_KEYS = frozenset(
    {
        "case_id",
        "verdict",
        "serious_dimensions",
        "schema_valid",
        "deterministic_replay",
        "evidence_localization_coherent",
        "response_sha256",
    }
)
PASS_VERDICTS = frozenset({"pass", "pass_with_findings"})
VERDICTS = PASS_VERDICTS | frozenset({"defect", "abstain"})


class CriticStage2QualificationError(ValueError):
    """A stage-2 board or its measured result set is incomplete or unbound."""


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise CriticStage2QualificationError(f"{field} must be a SHA-256")
    return value


def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CriticStage2QualificationError(f"{field} must be a nonempty string")
    return value


def board_sha256(board: Mapping[str, Any]) -> str:
    """Return the canonical identity of a frozen stage-2 board."""

    return canonical_sha256({key: value for key, value in board.items() if key != "board_sha256"})


def results_sha256(results: Mapping[str, Any]) -> str:
    """Return the canonical identity of one exact model result set."""

    return canonical_sha256(
        {key: value for key, value in results.items() if key != "results_sha256"}
    )


def seal_stage2_board(board: Mapping[str, Any]) -> dict[str, Any]:
    """Seal a board after validating all content other than its final hash."""

    sealed = dict(board)
    sealed["board_sha256"] = "0" * 64
    validate_stage2_board(sealed, permit_unsealed_hash=True)
    sealed["board_sha256"] = board_sha256(sealed)
    validate_stage2_board(sealed)
    return sealed


def seal_stage2_results(results: Mapping[str, Any]) -> dict[str, Any]:
    """Seal exact results after the board-facing fields have been populated."""

    sealed = dict(results)
    sealed["results_sha256"] = "0" * 64
    _validate_results_shape(sealed, permit_unsealed_hash=True)
    sealed["results_sha256"] = results_sha256(sealed)
    _validate_results_shape(sealed)
    return sealed


def validate_stage2_board(board: Mapping[str, Any], *, permit_unsealed_hash: bool = False) -> None:
    """Require a frozen real-image holdout board with adequate statistical support."""

    if not isinstance(board, Mapping) or set(board) != BOARD_KEYS:
        raise CriticStage2QualificationError("stage-2 board fields are incomplete or unknown")
    if board.get("schema_version") != BOARD_SCHEMA_VERSION:
        raise CriticStage2QualificationError("stage-2 board schema is unsupported")
    for field in ("board_id", "frozen_at"):
        _require_nonempty_string(board.get(field), field)
    if board.get("role_id") not in MODEL_ROLES:
        raise CriticStage2QualificationError("stage-2 board role is unknown")
    if board.get("protocol_id") != PROTOCOL_ID:
        raise CriticStage2QualificationError("stage-2 board is not bound to protocol v3")
    for field in ("registry_sha256", "corpus_sha256", "execution_manifest_sha256", "board_sha256"):
        _require_sha256(board.get(field), field)
    if not permit_unsealed_hash and board["board_sha256"] != board_sha256(board):
        raise CriticStage2QualificationError("stage-2 board hash drifted")

    cases = board.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)):
        raise CriticStage2QualificationError("stage-2 board cases are invalid")
    if len(cases) < MINIMUM_CASE_COUNT:
        raise CriticStage2QualificationError("stage-2 board has fewer than 100 cases")
    case_ids: set[str] = set()
    panel_sets: set[str] = set()
    source_label_bindings: set[tuple[str, str]] = set()
    valid_case_count = 0
    serious_defect_case_count = 0
    for case in cases:
        if not isinstance(case, Mapping) or set(case) != BOARD_CASE_KEYS:
            raise CriticStage2QualificationError("stage-2 board case fields are invalid")
        case_id = _require_nonempty_string(case.get("case_id"), "case_id")
        if case_id in case_ids:
            raise CriticStage2QualificationError("stage-2 board case IDs are duplicated")
        case_ids.add(case_id)
        if case.get("partition") != "qualification_holdout":
            raise CriticStage2QualificationError("stage-2 board case is not an untouched holdout")
        label_id = _require_nonempty_string(case.get("label_id"), f"{case_id}.label_id")
        if case.get("source_authority_tier") not in SOURCE_AUTHORITY_TIERS:
            raise CriticStage2QualificationError("stage-2 source authority tier is invalid")
        source_sha = _require_sha256(case.get("source_sha256"), f"{case_id}.source_sha256")
        _require_sha256(case.get("target_contract_sha256"), f"{case_id}.target_contract_sha256")
        panel_set_sha = _require_sha256(case.get("panel_set_sha256"), f"{case_id}.panel_set_sha256")
        if panel_set_sha in panel_sets:
            raise CriticStage2QualificationError("stage-2 board panel set is duplicated")
        panel_sets.add(panel_set_sha)
        source_label = (source_sha, label_id)
        if source_label in source_label_bindings:
            raise CriticStage2QualificationError("stage-2 board source/label binding is duplicated")
        source_label_bindings.add(source_label)
        outcome = case.get("expected_outcome")
        severity = case.get("expected_severity")
        if outcome == "valid_mask" and severity == "none":
            valid_case_count += 1
        elif outcome == "known_defect" and severity == "serious":
            serious_defect_case_count += 1
        else:
            raise CriticStage2QualificationError("stage-2 board outcome/severity is invalid")
    if valid_case_count < MINIMUM_VALID_CASE_COUNT:
        raise CriticStage2QualificationError("stage-2 board has fewer than 40 valid-mask cases")
    if serious_defect_case_count < MINIMUM_SERIOUS_DEFECT_CASE_COUNT:
        raise CriticStage2QualificationError("stage-2 board has fewer than 60 serious-defect cases")


def _validate_results_shape(
    results: Mapping[str, Any], *, permit_unsealed_hash: bool = False
) -> None:
    if not isinstance(results, Mapping) or set(results) != RESULTS_KEYS:
        raise CriticStage2QualificationError("stage-2 result fields are incomplete or unknown")
    if results.get("schema_version") != RESULTS_SCHEMA_VERSION:
        raise CriticStage2QualificationError("stage-2 results schema is unsupported")
    for field in (
        "board_sha256",
        "runtime_sha256",
        "artifact_tree_sha256",
        "prompt_sha256",
        "results_sha256",
    ):
        _require_sha256(results.get(field), field)
    for field in ("model_id", "family_id"):
        _require_nonempty_string(results.get(field), field)
    if not permit_unsealed_hash and results["results_sha256"] != results_sha256(results):
        raise CriticStage2QualificationError("stage-2 result hash drifted")
    predictions = results.get("predictions")
    if not isinstance(predictions, Sequence) or isinstance(predictions, (str, bytes)):
        raise CriticStage2QualificationError("stage-2 predictions are invalid")
    for prediction in predictions:
        if not isinstance(prediction, Mapping) or set(prediction) != PREDICTION_KEYS:
            raise CriticStage2QualificationError("stage-2 prediction fields are invalid")
        _require_nonempty_string(prediction.get("case_id"), "prediction.case_id")
        if prediction.get("verdict") not in VERDICTS:
            raise CriticStage2QualificationError("stage-2 prediction verdict is invalid")
        dimensions = prediction.get("serious_dimensions")
        if (
            not isinstance(dimensions, Sequence)
            or isinstance(dimensions, (str, bytes))
            or len(set(dimensions)) != len(dimensions)
            or any(not isinstance(value, str) or not value.strip() for value in dimensions)
        ):
            raise CriticStage2QualificationError("stage-2 serious dimensions are invalid")
        if prediction["verdict"] != "defect" and dimensions:
            raise CriticStage2QualificationError(
                "non-defect stage-2 prediction carries serious dimensions"
            )
        for field in (
            "schema_valid",
            "deterministic_replay",
            "evidence_localization_coherent",
        ):
            if not isinstance(prediction.get(field), bool):
                raise CriticStage2QualificationError(f"stage-2 {field} must be boolean")
        _require_sha256(prediction.get("response_sha256"), "prediction.response_sha256")


def _wilson_lower_bound(successes: int, total: int) -> float:
    if total <= 0 or successes < 0 or successes > total:
        raise CriticStage2QualificationError("stage-2 Wilson inputs are invalid")
    proportion = successes / total
    z_squared = ONE_SIDED_95_Z**2
    numerator = (
        proportion
        + z_squared / (2 * total)
        - ONE_SIDED_95_Z
        * math.sqrt(proportion * (1 - proportion) / total + z_squared / (4 * total**2))
    )
    return numerator / (1 + z_squared / total)


def evaluate_stage2_qualification(
    board: Mapping[str, Any], results: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate one exact result set against a frozen stage-2 board.

    Any malformed or incomplete result is rejected before metrics are calculated.
    A passing report is only measurement evidence; it cannot itself issue a role
    certificate or elevate any authority tier.
    """

    validate_stage2_board(board)
    _validate_results_shape(results)
    if results["board_sha256"] != board["board_sha256"]:
        raise CriticStage2QualificationError("stage-2 results target a different board")

    board_cases = {str(case["case_id"]): case for case in board["cases"]}
    predictions: dict[str, Mapping[str, Any]] = {}
    for prediction in results["predictions"]:
        case_id = str(prediction["case_id"])
        if case_id not in board_cases or case_id in predictions:
            raise CriticStage2QualificationError("stage-2 predictions are unknown or duplicated")
        predictions[case_id] = prediction
    if set(predictions) != set(board_cases):
        raise CriticStage2QualificationError("stage-2 predictions do not cover the board exactly")

    valid_cases = [case for case in board["cases"] if case["expected_outcome"] == "valid_mask"]
    serious_cases = [
        case
        for case in board["cases"]
        if case["expected_outcome"] == "known_defect" and case["expected_severity"] == "serious"
    ]
    valid_passes = sum(
        predictions[case["case_id"]]["verdict"] in PASS_VERDICTS for case in valid_cases
    )
    serious_detections = sum(
        predictions[case["case_id"]]["verdict"] == "defect"
        and bool(predictions[case["case_id"]]["serious_dimensions"])
        for case in serious_cases
    )
    serious_false_passes = sum(
        predictions[case["case_id"]]["verdict"] in PASS_VERDICTS for case in serious_cases
    )
    schema_failures = sum(not row["schema_valid"] for row in predictions.values())
    replay_failures = sum(not row["deterministic_replay"] for row in predictions.values())
    localization_failures = sum(
        not row["evidence_localization_coherent"] for row in predictions.values()
    )
    metrics = {
        "valid_mask_pass_count": valid_passes,
        "valid_mask_case_count": len(valid_cases),
        "valid_mask_pass_rate": valid_passes / len(valid_cases),
        "valid_mask_pass_wilson_lower_95": _wilson_lower_bound(valid_passes, len(valid_cases)),
        "serious_defect_detected_count": serious_detections,
        "serious_defect_case_count": len(serious_cases),
        "serious_defect_recall": serious_detections / len(serious_cases),
        "serious_defect_recall_wilson_lower_95": _wilson_lower_bound(
            serious_detections, len(serious_cases)
        ),
        "serious_false_pass_count": serious_false_passes,
        "schema_failure_count": schema_failures,
        "deterministic_replay_failure_count": replay_failures,
        "evidence_localization_failure_count": localization_failures,
    }
    failures: list[str] = []
    if metrics["serious_defect_recall_wilson_lower_95"] < MINIMUM_SERIOUS_RECALL_LOWER_BOUND:
        failures.append("serious_defect_recall_wilson_lower_95_below_minimum")
    if metrics["valid_mask_pass_wilson_lower_95"] < MINIMUM_VALID_PASS_LOWER_BOUND:
        failures.append("valid_mask_pass_wilson_lower_95_below_minimum")
    if serious_false_passes:
        failures.append("serious_false_passes_present")
    if schema_failures:
        failures.append("schema_failures_present")
    if replay_failures:
        failures.append("nondeterministic_replay_present")
    if localization_failures:
        failures.append("incoherent_evidence_localization_present")
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "pass" if not failures else "fail",
        "authority_claimed": False,
        "role_certificate_issuance_allowed": False,
        "board_sha256": board["board_sha256"],
        "registry_sha256": board["registry_sha256"],
        "corpus_sha256": board["corpus_sha256"],
        "execution_manifest_sha256": board["execution_manifest_sha256"],
        "role_id": board["role_id"],
        "model_id": results["model_id"],
        "family_id": results["family_id"],
        "results_sha256": results["results_sha256"],
        "thresholds": {
            "one_sided_confidence": 0.95,
            "minimum_case_count": MINIMUM_CASE_COUNT,
            "minimum_valid_case_count": MINIMUM_VALID_CASE_COUNT,
            "minimum_serious_defect_case_count": MINIMUM_SERIOUS_DEFECT_CASE_COUNT,
            "minimum_serious_defect_recall_wilson_lower_95": (MINIMUM_SERIOUS_RECALL_LOWER_BOUND),
            "minimum_valid_mask_pass_wilson_lower_95": MINIMUM_VALID_PASS_LOWER_BOUND,
            "maximum_serious_false_pass_count": 0,
            "maximum_schema_failure_count": 0,
        },
        "metrics": metrics,
        "failures": failures,
    }
    report["report_sha256"] = canonical_sha256(report)
    return report


__all__ = [
    "BOARD_SCHEMA_VERSION",
    "CriticStage2QualificationError",
    "MINIMUM_CASE_COUNT",
    "MINIMUM_SERIOUS_DEFECT_CASE_COUNT",
    "MINIMUM_VALID_CASE_COUNT",
    "REPORT_SCHEMA_VERSION",
    "RESULTS_SCHEMA_VERSION",
    "board_sha256",
    "evaluate_stage2_qualification",
    "results_sha256",
    "seal_stage2_board",
    "seal_stage2_results",
    "validate_stage2_board",
]
