"""Frozen positive-and-negative visual-critic calibration corpus contract."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .critic_catalog import canonical_sha256
from .target_contract import validate_target_contract

SHA256 = re.compile(r"^[a-f0-9]{64}$")
PARTITIONS = frozenset({"calibration", "qualification_holdout"})
DEFECT_TYPES = frozenset(
    {
        "boundary",
        "leakage",
        "missing_area",
        "flood",
        "wrong_label",
        "wrong_side",
        "anatomy",
        "ownership",
        "protected_region",
        "transform",
    }
)
PANEL_KEYS = frozenset(
    {
        "source",
        "binary_mask",
        "overlay",
        "contour",
        "full_context",
        "uncertainty_zoom",
    }
)
MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "corpus_id",
        "frozen_at",
        "partitions",
        "defect_taxonomy",
        "cases",
        "corpus_sha256",
    }
)
CASE_KEYS = frozenset(
    {
        "case_id",
        "partition",
        "expected_outcome",
        "defect_type",
        "target_contract",
        "panels",
        "panel_set_sha256",
    }
)


class CalibrationCorpusError(ValueError):
    """The calibration corpus is incomplete, leaked, duplicated, or unsealed."""


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise CalibrationCorpusError(f"{field} must be a SHA-256")
    return value


def panel_set_sha256(case: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "target_contract_sha256": case["target_contract"]["contract_sha256"],
            "panels": case["panels"],
        }
    )


def calibration_corpus_sha256(manifest: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {key: value for key, value in manifest.items() if key != "corpus_sha256"}
    )


def validate_calibration_corpus(manifest: Mapping[str, Any]) -> None:
    """Validate a sealed, image-disjoint two-partition critic corpus."""

    if set(manifest) != MANIFEST_KEYS:
        raise CalibrationCorpusError("calibration corpus fields are incomplete or unknown")
    if manifest["schema_version"] != "1.0.0":
        raise CalibrationCorpusError("calibration corpus schema is unsupported")
    if not str(manifest["corpus_id"]).strip() or not str(manifest["frozen_at"]).strip():
        raise CalibrationCorpusError("calibration corpus identity or freeze time is empty")
    if manifest["partitions"] != ["calibration", "qualification_holdout"]:
        raise CalibrationCorpusError("calibration corpus partitions are not frozen")
    if manifest["defect_taxonomy"] != sorted(DEFECT_TYPES):
        raise CalibrationCorpusError("calibration defect taxonomy drifted")
    if manifest["corpus_sha256"] != calibration_corpus_sha256(manifest):
        raise CalibrationCorpusError("calibration corpus canonical hash mismatch")

    cases = manifest["cases"]
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)) or not cases:
        raise CalibrationCorpusError("calibration corpus has no cases")

    case_ids: set[str] = set()
    panel_sets: set[str] = set()
    candidate_bindings: set[tuple[str, str, str]] = set()
    source_partitions: dict[str, set[str]] = defaultdict(set)
    outcomes_by_partition: dict[str, set[str]] = defaultdict(set)
    observed_defects: set[str] = set()

    for case in cases:
        if not isinstance(case, Mapping) or set(case) != CASE_KEYS:
            raise CalibrationCorpusError("calibration case fields are incomplete or unknown")
        case_id = str(case["case_id"])
        if not case_id or case_id in case_ids:
            raise CalibrationCorpusError("calibration case IDs are empty or duplicated")
        case_ids.add(case_id)
        partition = str(case["partition"])
        if partition not in PARTITIONS:
            raise CalibrationCorpusError(f"{case_id} partition is invalid")

        contract = case["target_contract"]
        try:
            validate_target_contract(contract)
        except Exception as exc:
            raise CalibrationCorpusError(f"{case_id} target contract is incomplete: {exc}") from exc
        source_sha = _sha256(contract["source"]["sha256"], f"{case_id}.source")
        candidate_sha = _sha256(contract["candidate"]["mask_sha256"], f"{case_id}.candidate")
        contract_sha = _sha256(contract["contract_sha256"], f"{case_id}.target_contract")
        source_partitions[source_sha].add(partition)

        panels = case["panels"]
        if not isinstance(panels, Mapping) or set(panels) != PANEL_KEYS:
            raise CalibrationCorpusError(f"{case_id} panel set is incomplete")
        for panel_name, panel_hash in panels.items():
            _sha256(panel_hash, f"{case_id}.panels.{panel_name}")
        if panels["source"] != source_sha or panels["binary_mask"] != candidate_sha:
            raise CalibrationCorpusError(f"{case_id} source or candidate panel hash drifted")
        expected_panel_set = panel_set_sha256(case)
        if case["panel_set_sha256"] != expected_panel_set:
            raise CalibrationCorpusError(f"{case_id} panel-set hash mismatch")
        if expected_panel_set in panel_sets:
            raise CalibrationCorpusError("calibration panel sets are duplicated")
        panel_sets.add(expected_panel_set)
        binding = (source_sha, candidate_sha, contract_sha)
        if binding in candidate_bindings:
            raise CalibrationCorpusError("calibration candidate binding is duplicated")
        candidate_bindings.add(binding)

        outcome = case["expected_outcome"]
        defect = case["defect_type"]
        if outcome == "valid_mask":
            if defect is not None:
                raise CalibrationCorpusError(f"{case_id} valid mask carries a defect label")
        elif outcome == "known_defect":
            if defect not in DEFECT_TYPES:
                raise CalibrationCorpusError(f"{case_id} defect label is invalid")
            observed_defects.add(str(defect))
        else:
            raise CalibrationCorpusError(f"{case_id} expected outcome is invalid")
        outcomes_by_partition[partition].add(str(outcome))

    if any(len(partitions) != 1 for partitions in source_partitions.values()):
        raise CalibrationCorpusError("source image leaks across calibration partitions")
    required_outcomes = {"valid_mask", "known_defect"}
    if any(outcomes_by_partition[partition] != required_outcomes for partition in PARTITIONS):
        raise CalibrationCorpusError("each partition requires both valid and defect masks")
    if observed_defects != DEFECT_TYPES:
        raise CalibrationCorpusError("calibration cases do not cover the frozen defect taxonomy")
