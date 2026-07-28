"""Frozen visual-regression suite and promotion-change gate."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from .critic_catalog import MODEL_ROLES, canonical_sha256
from .target_contract import validate_target_contract

SHA256 = re.compile(r"^[a-f0-9]{64}$")
ROOT = Path(__file__).resolve().parents[3]
CANONICAL_V2_ONTOLOGY_PATH = ROOT / "configs" / "ontology_v2.yaml"
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
    "clothing_skin_boundary": frozenset({"torso_skin", "torso_skin_external_reference"}),
    "feet": frozenset({"left_foot", "right_foot", "left_foot_external_reference"}),
    "hair": frozenset({"hair", "hair_external_reference"}),
    "hands": frozenset({"left_hand", "right_hand", "left_hand_region_external_reference"}),
    "multi_person_ownership": frozenset({"left_arm", "right_arm", "right_arm_external_reference"}),
    "occlusion_contact": frozenset({"left_hand", "right_hand", "right_arm_external_reference"}),
    "visible_anatomy": frozenset({"face_skin", "torso_skin", "face_external_reference"}),
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
MANIFEST_KEYS_V1 = frozenset(
    {"schema_version", "suite_id", "frozen_at", "required_domains", "cases", "suite_sha256"}
)
MANIFEST_KEYS_V2 = MANIFEST_KEYS_V1 | frozenset(
    {"truth_source", "source_bindings_sha256", "reference_coverage"}
)
CASE_KEYS_V1 = frozenset(
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
CASE_KEYS_V2 = CASE_KEYS_V1 | frozenset({"source_binding"})
SOURCE_BINDING_KEYS = frozenset(
    {
        "source_family",
        "source_root_id",
        "source_relative_path",
        "source_file_sha256",
        "source_panel_sha256",
        "annotation_relative_paths",
        "annotation_file_sha256s",
        "base_mask_pixel_sha256",
        "source_authority",
        "real_source_pixels",
        "synthetic",
        "production_draft",
        "qualification_evidence_sha256",
        "source_binding_sha256",
    }
)
REFERENCE_COVERAGE_KEYS = frozenset(
    {"root_id", "inventory_relative_path", "inventory_sha256", "role", "truth_authority"}
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


def required_canonical_v2_labels(
    ontology_path: Path = CANONICAL_V2_ONTOLOGY_PATH,
) -> tuple[str, ...]:
    """Load the exact 66-class part-map contract used by promotion coverage."""

    document = yaml.safe_load(Path(ontology_path).read_text(encoding="utf-8"))
    labels = document.get("labels") if isinstance(document, Mapping) else None
    if not isinstance(labels, Sequence) or isinstance(labels, (str, bytes)):
        raise VisualRegressionError("canonical v2 ontology labels are invalid")
    rows = [row for row in labels if isinstance(row, Mapping) and row.get("map") == "part"]
    ids = [row.get("id") for row in rows]
    names = [row.get("name") for row in rows]
    if (
        ids != list(range(66))
        or len(set(names)) != 66
        or any(not isinstance(name, str) or not name for name in names)
    ):
        raise VisualRegressionError("canonical v2 ontology is not exact IDs 0..65")
    return tuple(names)


def evaluate_canonical_label_coverage(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Report exact canonical-label gaps without treating external aliases as coverage."""

    validate_regression_suite(manifest)
    required = required_canonical_v2_labels()
    observed = sorted(
        {str(case["target_contract"]["target"]["label_id"]) for case in manifest["cases"]}
    )
    covered = sorted(set(observed).intersection(required))
    missing = sorted(set(required) - set(covered))
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "status": "pass" if not missing else "fail",
        "suite_sha256": manifest["suite_sha256"],
        "required_label_count": len(required),
        "covered_label_count": len(covered),
        "required_label_ids": list(required),
        "covered_label_ids": covered,
        "missing_label_ids": missing,
        "noncanonical_target_labels": sorted(set(observed) - set(required)),
    }
    report["coverage_sha256"] = canonical_sha256(report)
    return report


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
    schema_version = manifest.get("schema_version")
    expected_manifest_keys = MANIFEST_KEYS_V2 if schema_version == "2.0.0" else MANIFEST_KEYS_V1
    if set(manifest) != expected_manifest_keys or schema_version not in {"1.0.0", "2.0.0"}:
        raise VisualRegressionError("regression suite fields or schema are invalid")
    real_suite = schema_version == "2.0.0"
    if real_suite:
        if manifest.get("truth_source") != "real_image_external_labeled_reference":
            raise VisualRegressionError("real regression suite truth source is invalid")
        reference = manifest.get("reference_coverage")
        if not isinstance(reference, Mapping) or set(reference) != REFERENCE_COVERAGE_KEYS:
            raise VisualRegressionError("real regression reference coverage is invalid")
        _sha(reference.get("inventory_sha256"), "reference_coverage.inventory_sha256")
        if (
            reference.get("root_id") != "reference_library"
            or reference.get("role") != "coverage_retrieval_only"
            or reference.get("truth_authority") != "none"
        ):
            raise VisualRegressionError("real regression reference authority is invalid")
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
    source_bindings: list[Mapping[str, Any]] = []
    for case in cases:
        expected_case_keys = CASE_KEYS_V2 if real_suite else CASE_KEYS_V1
        if not isinstance(case, Mapping) or set(case) != expected_case_keys:
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
        if real_suite:
            binding = case.get("source_binding")
            if not isinstance(binding, Mapping) or set(binding) != SOURCE_BINDING_KEYS:
                raise VisualRegressionError(f"{case_id} real source binding is invalid")
            if binding.get("source_binding_sha256") != canonical_sha256(
                {key: value for key, value in binding.items() if key != "source_binding_sha256"}
            ):
                raise VisualRegressionError(f"{case_id} real source binding hash mismatch")
            if (
                binding.get("source_family") != "maskedwarehouse"
                or binding.get("source_root_id") != "maskedwarehouse"
                or binding.get("source_authority") != "external_labeled_reference"
                or binding.get("real_source_pixels") is not True
                or binding.get("synthetic") is not False
                or binding.get("production_draft") is not False
                or binding.get("source_panel_sha256") != source_sha
            ):
                raise VisualRegressionError(f"{case_id} real source authority is invalid")
            for field in (
                "source_file_sha256",
                "base_mask_pixel_sha256",
                "qualification_evidence_sha256",
            ):
                _sha(binding.get(field), f"{case_id}.{field}")
            annotation_paths = binding.get("annotation_relative_paths")
            annotation_hashes = binding.get("annotation_file_sha256s")
            if (
                not isinstance(annotation_paths, list)
                or not annotation_paths
                or not isinstance(annotation_hashes, list)
                or len(annotation_paths) != len(annotation_hashes)
            ):
                raise VisualRegressionError(f"{case_id} annotation binding is invalid")
            for path in [binding.get("source_relative_path"), *annotation_paths]:
                if (
                    not isinstance(path, str)
                    or not path
                    or path.startswith(("/", "\\"))
                    or ".." in path.replace("\\", "/").split("/")
                ):
                    raise VisualRegressionError(f"{case_id} real source path is unsafe")
            for index, digest in enumerate(annotation_hashes):
                _sha(digest, f"{case_id}.annotation[{index}]")
            source_bindings.append(binding)
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
    if real_suite and manifest.get("source_bindings_sha256") != canonical_sha256(source_bindings):
        raise VisualRegressionError("real regression source-binding seal mismatch")


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
    if manifest.get("schema_version") != "2.0.0":
        raise VisualRegressionError("synthetic-only regression suite cannot authorize promotion")
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
    label_coverage = evaluate_canonical_label_coverage(manifest)
    if label_coverage["status"] != "pass":
        failures.append("canonical_ontology_coverage_incomplete")
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
        "canonical_label_coverage": label_coverage,
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
