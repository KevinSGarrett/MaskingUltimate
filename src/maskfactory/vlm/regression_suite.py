"""Frozen visual-regression suite and promotion-change gate."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .critic_catalog import MODEL_ROLES, canonical_sha256
from .target_contract import validate_target_contract

SHA256 = re.compile(r"^[a-f0-9]{64}$")
REQUIRED_DOMAINS = (
    "clothing_skin_boundary",
    "feet",
    "hair",
    "hands",
    "multi_person_ownership",
    "occlusion_contact",
    "visible_anatomy",
)
DOMAIN_LABELS = {
    "clothing_skin_boundary": frozenset({"torso_skin"}),
    "feet": frozenset({"left_foot", "right_foot"}),
    "hair": frozenset({"hair"}),
    "hands": frozenset({"left_hand", "right_hand"}),
    "multi_person_ownership": frozenset({"left_arm", "right_arm"}),
    "occlusion_contact": frozenset({"left_hand", "right_hand"}),
    "visible_anatomy": frozenset({"face_skin", "torso_skin"}),
}
PANEL_KEYS = frozenset(
    {
        "source",
        "binary_mask",
        "overlay",
        "contour",
        "full_context",
        "uncertainty_zoom",
        "disagreement",
    }
)
MANIFEST_KEYS = frozenset(
    {"schema_version", "suite_id", "frozen_at", "required_domains", "cases", "suite_sha256"}
)
CASE_KEYS = frozenset(
    {
        "case_id",
        "domain",
        "expected_outcome",
        "defect_type",
        "target_contract",
        "panels",
        "panel_files",
        "panel_set_sha256",
        "case_sha256",
    }
)
CHANGE_KEYS = frozenset(
    {
        "schema_version",
        "suite_sha256",
        "promoted_role",
        "model_artifact_sha256",
        "provider_set_sha256",
        "prompt_sha256",
        "runtime_sha256",
        "renderer_sha256",
        "target_contract_schema_sha256",
    }
)
RESULT_KEYS = frozenset(
    {
        "case_id",
        "panel_set_sha256",
        "verdict",
        "defect_type",
        "response_sha256",
        "deterministic_replay",
    }
)


class VisualRegressionError(ValueError):
    """Regression evidence is incomplete, drifted, or unsafe for promotion."""


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise VisualRegressionError(f"{field} must be a SHA-256")
    return value


def regression_case_sha256(case: Mapping[str, Any]) -> str:
    return canonical_sha256({key: value for key, value in case.items() if key != "case_sha256"})


def regression_suite_sha256(manifest: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {key: value for key, value in manifest.items() if key != "suite_sha256"}
    )


def validate_regression_suite(manifest: Mapping[str, Any]) -> None:
    if set(manifest) != MANIFEST_KEYS or manifest.get("schema_version") != "1.0.0":
        raise VisualRegressionError("regression suite fields or schema are invalid")
    if manifest["required_domains"] != list(REQUIRED_DOMAINS):
        raise VisualRegressionError("regression suite domain contract drifted")
    if manifest["suite_sha256"] != regression_suite_sha256(manifest):
        raise VisualRegressionError("regression suite canonical hash mismatch")
    cases = manifest["cases"]
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)) or not cases:
        raise VisualRegressionError("regression suite has no cases")
    case_ids: set[str] = set()
    sources: set[str] = set()
    outcomes: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        if not isinstance(case, Mapping) or set(case) != CASE_KEYS:
            raise VisualRegressionError("regression case fields are invalid")
        case_id = str(case["case_id"])
        if not case_id or case_id in case_ids:
            raise VisualRegressionError("regression case IDs are empty or duplicated")
        case_ids.add(case_id)
        domain = str(case["domain"])
        if domain not in REQUIRED_DOMAINS:
            raise VisualRegressionError(f"{case_id} domain is invalid")
        try:
            validate_target_contract(case["target_contract"])
        except Exception as exc:
            raise VisualRegressionError(f"{case_id} target contract is invalid: {exc}") from exc
        if case["target_contract"]["target"]["label_id"] not in DOMAIN_LABELS[domain]:
            raise VisualRegressionError(f"{case_id} target label does not prove its domain")
        source_sha = _sha(case["target_contract"]["source"]["sha256"], f"{case_id}.source")
        if source_sha in sources:
            raise VisualRegressionError("regression source images are not image-disjoint")
        sources.add(source_sha)
        if not isinstance(case["panels"], Mapping) or set(case["panels"]) != PANEL_KEYS:
            raise VisualRegressionError(f"{case_id} panel hashes are incomplete")
        if not isinstance(case["panel_files"], Mapping) or set(case["panel_files"]) != PANEL_KEYS:
            raise VisualRegressionError(f"{case_id} panel files are incomplete")
        for name, value in case["panels"].items():
            _sha(value, f"{case_id}.{name}")
        if case["panels"]["source"] != source_sha:
            raise VisualRegressionError(f"{case_id} source panel hash drifted")
        if case["panels"]["binary_mask"] != case["target_contract"]["candidate"]["mask_sha256"]:
            raise VisualRegressionError(f"{case_id} candidate panel hash drifted")
        if any(
            not isinstance(path, str)
            or not path
            or path.startswith(("/", "\\"))
            or ".." in path.replace("\\", "/").split("/")
            for path in case["panel_files"].values()
        ):
            raise VisualRegressionError(f"{case_id} panel path is unsafe")
        _sha(case["panel_set_sha256"], f"{case_id}.panel_set_sha256")
        if case["case_sha256"] != regression_case_sha256(case):
            raise VisualRegressionError(f"{case_id} canonical hash mismatch")
        outcome = case["expected_outcome"]
        defect = case["defect_type"]
        if outcome == "valid_mask" and defect is not None:
            raise VisualRegressionError(f"{case_id} valid control carries a defect")
        if outcome == "serious_defect" and not isinstance(defect, str):
            raise VisualRegressionError(f"{case_id} serious control lacks a defect")
        if outcome not in {"valid_mask", "serious_defect"}:
            raise VisualRegressionError(f"{case_id} outcome is invalid")
        outcomes[domain].add(str(outcome))
    if any(outcomes[domain] != {"valid_mask", "serious_defect"} for domain in REQUIRED_DOMAINS):
        raise VisualRegressionError("every regression domain needs valid and serious controls")


def validate_regression_suite_files(manifest: Mapping[str, Any], root: Path) -> None:
    validate_regression_suite(manifest)
    root = Path(root).resolve()
    seen: set[Path] = set()
    for case in manifest["cases"]:
        for name, relative in case["panel_files"].items():
            path = (root / relative).resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise VisualRegressionError("regression panel path escapes suite root") from exc
            if path in seen or not path.is_file():
                raise VisualRegressionError("regression panel file is missing or duplicated")
            seen.add(path)
            if hashlib.sha256(path.read_bytes()).hexdigest() != case["panels"][name]:
                raise VisualRegressionError(f"regression panel hash drifted: {relative}")


def evaluate_visual_regression(
    change: Mapping[str, Any], results: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate one exact promotion fingerprint; any serious miss blocks it."""

    validate_regression_suite(manifest)
    if set(change) != CHANGE_KEYS or change.get("schema_version") != "1.0.0":
        raise VisualRegressionError("regression change binding fields or schema are invalid")
    if change["suite_sha256"] != manifest["suite_sha256"]:
        raise VisualRegressionError("regression change binding names a stale suite")
    if change["promoted_role"] not in MODEL_ROLES:
        raise VisualRegressionError("regression change binding role is invalid")
    for field in CHANGE_KEYS - {"schema_version", "promoted_role"}:
        _sha(change[field], field)
    cases = {str(case["case_id"]): case for case in manifest["cases"]}
    observed: dict[str, Mapping[str, Any]] = {}
    for result in results:
        if not isinstance(result, Mapping) or set(result) != RESULT_KEYS:
            raise VisualRegressionError("regression result fields are invalid")
        case_id = str(result["case_id"])
        case = cases.get(case_id)
        if case is None or case_id in observed:
            raise VisualRegressionError("regression result case is unknown or duplicated")
        observed[case_id] = result
        if result["panel_set_sha256"] != case["panel_set_sha256"]:
            raise VisualRegressionError(f"{case_id} regression panel binding drifted")
        _sha(result["response_sha256"], f"{case_id}.response_sha256")
        if result["verdict"] not in {"pass", "defect", "abstain"}:
            raise VisualRegressionError(f"{case_id} verdict is invalid")
        if result["verdict"] != "defect" and result["defect_type"] is not None:
            raise VisualRegressionError(f"{case_id} non-defect verdict carries a defect")
    if set(observed) != set(cases):
        raise VisualRegressionError("regression results do not cover the frozen suite")
    regressions = []
    replay_failures = []
    for case_id, case in cases.items():
        result = observed[case_id]
        if result["deterministic_replay"] is not True:
            replay_failures.append(case_id)
        expected_pass = case["expected_outcome"] == "valid_mask"
        correct = (
            result["verdict"] == "pass"
            if expected_pass
            else (result["verdict"] == "defect" and result["defect_type"] == case["defect_type"])
        )
        if not correct:
            regressions.append(case_id)
    failures = []
    if regressions:
        failures.append("serious_visual_regression")
    if replay_failures:
        failures.append("deterministic_replay_failure")
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "status": "pass" if not failures else "fail",
        "promotion_allowed": not failures,
        "authority_claimed": False,
        "suite_sha256": manifest["suite_sha256"],
        "change_sha256": canonical_sha256(change),
        "case_count": len(cases),
        "regression_case_ids": regressions,
        "replay_failure_case_ids": replay_failures,
        "failures": failures,
    }
    report["report_sha256"] = canonical_sha256(report)
    return report


def require_current_passing_regression(
    report: Mapping[str, Any], change: Mapping[str, Any], manifest: Mapping[str, Any]
) -> None:
    validate_regression_suite(manifest)
    if (
        report.get("status") != "pass"
        or report.get("promotion_allowed") is not True
        or report.get("suite_sha256") != manifest["suite_sha256"]
        or report.get("change_sha256") != canonical_sha256(change)
    ):
        raise VisualRegressionError("current promotion fingerprint lacks a passing regression")
