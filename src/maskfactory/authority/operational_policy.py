"""Fail-closed perturbation, metamorphic-truth, and replay policy evidence."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from maskfactory.autonomy.risk_buckets import canonical_sha256
from maskfactory.autonomy.stability import PERTURBATIONS
from maskfactory.io.hashing import sha256_file
from maskfactory.io.png_strict import read_mask
from maskfactory.ontology import get_ontology
from maskfactory.validation import ArtifactValidationError, require_valid_document

REQUIRED_GATE_IDS = frozenset({"perturbation", "metamorphic", "stability_replay"})
REQUIRED_SYNTHETIC_CASE_KINDS = frozenset(
    {"exact_truth", "boundary_shift", "missing_area", "side_inconsistency"}
)
_POLICY_FIELDS = frozenset(
    {
        "schema_version",
        "policy_id",
        "stability_policy_id",
        "required_perturbations",
        "required_gate_ids",
        "required_synthetic_case_kinds",
        "replay_count",
        "fixed_seed",
    }
)
_SCOPE_FIELDS = frozenset(
    {
        "candidate_id",
        "source_decoded_pixel_sha256",
        "output_artifact_identity_sha256s",
        "pipeline_fingerprint",
        "risk_bucket",
        "label",
        "seed",
    }
)
_CASE_FIELDS = frozenset(
    {
        "case_id",
        "case_kind",
        "truth_mask_path",
        "candidate_mask_path",
        "expected_label",
        "reported_label",
    }
)
_REPLAY_FIELDS = frozenset({"replay_id", "input_sha256", "decision", "decision_sha256"})
_DECISION_CORE_FIELDS = frozenset(
    {
        "status",
        "abstention_codes",
        "output_artifact_identity_sha256s",
        "label",
        "risk_bucket",
        "policy_sha256",
        "seed",
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class OperationalPolicyError(ValueError):
    """Operational policy input or evidence is malformed, incomplete, or tampered."""


def load_operational_policy(
    path: Path = Path("configs/operational_autonomy_policy.yaml"),
) -> dict[str, Any]:
    try:
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise OperationalPolicyError(f"cannot load operational autonomy policy: {exc}") from exc
    if not isinstance(document, dict) or set(document) != _POLICY_FIELDS:
        raise OperationalPolicyError("operational autonomy policy has the wrong contract")
    if document["schema_version"] != "1.0.0" or document["policy_id"] != ("operational-mask-qa-v1"):
        raise OperationalPolicyError("operational autonomy policy version is invalid")
    if document["stability_policy_id"] != "candidate_stability_v1":
        raise OperationalPolicyError("operational autonomy stability policy identity is invalid")
    if set(document["required_perturbations"]) != PERTURBATIONS:
        raise OperationalPolicyError("operational autonomy perturbation coverage is incomplete")
    if set(document["required_gate_ids"]) != REQUIRED_GATE_IDS:
        raise OperationalPolicyError("operational autonomy gate coverage is incomplete")
    if set(document["required_synthetic_case_kinds"]) != REQUIRED_SYNTHETIC_CASE_KINDS:
        raise OperationalPolicyError("operational autonomy synthetic coverage is incomplete")
    if document["replay_count"] != 2 or document["fixed_seed"] != 1337:
        raise OperationalPolicyError("operational autonomy replay policy is invalid")
    return document


def _strict_binary(path: Path) -> np.ndarray:
    try:
        array = read_mask(path)
    except (OSError, ValueError) as exc:
        raise OperationalPolicyError(f"synthetic truth mask is unreadable: {path}") from exc
    if array.ndim != 2 or array.dtype != np.uint8 or not set(np.unique(array)).issubset({0, 255}):
        raise OperationalPolicyError(f"synthetic truth mask is not strict binary: {path}")
    return array > 0


def _validate_scope(scope: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    if set(scope) != _SCOPE_FIELDS:
        raise OperationalPolicyError("operational candidate scope has the wrong contract")
    normalized = copy.deepcopy(dict(scope))
    if _SAFE_ID.fullmatch(str(normalized["candidate_id"])) is None:
        raise OperationalPolicyError("operational candidate ID is invalid")
    for field in ("source_decoded_pixel_sha256", "pipeline_fingerprint"):
        if _SHA256.fullmatch(str(normalized[field])) is None:
            raise OperationalPolicyError(f"operational candidate {field} is invalid")
    identities = normalized["output_artifact_identity_sha256s"]
    if (
        not isinstance(identities, list)
        or not identities
        or len(identities) != len(set(identities))
        or any(_SHA256.fullmatch(str(value)) is None for value in identities)
    ):
        raise OperationalPolicyError("operational output artifact identities are invalid")
    get_ontology().label(str(normalized["label"]), require_enabled=True)
    if not isinstance(normalized["risk_bucket"], str) or not normalized["risk_bucket"]:
        raise OperationalPolicyError("operational risk bucket is invalid")
    if normalized["seed"] != policy["fixed_seed"]:
        raise OperationalPolicyError("operational policy seed is not the frozen seed")
    return normalized


def _validate_stability_evidence(
    evidence: Mapping[str, Any],
    *,
    candidate_scope: Mapping[str, Any],
    stability_policy: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    document = copy.deepcopy(dict(evidence))
    try:
        require_valid_document(document, "autonomy_stability")
    except ArtifactValidationError as exc:
        raise OperationalPolicyError(f"candidate stability evidence is invalid: {exc}") from exc
    unsigned = {key: value for key, value in document.items() if key != "sha256"}
    if document.get("sha256") != canonical_sha256(unsigned):
        raise OperationalPolicyError("candidate stability evidence hash mismatch")
    if document.get("policy_sha256") != canonical_sha256(stability_policy):
        raise OperationalPolicyError("candidate stability policy hash mismatch")
    if (
        document.get("candidate_id") != candidate_scope["candidate_id"]
        or document.get("pipeline_fingerprint") != candidate_scope["pipeline_fingerprint"]
        or document.get("risk_bucket") != candidate_scope["risk_bucket"]
        or document.get("label") != candidate_scope["label"]
    ):
        raise OperationalPolicyError("candidate stability scope mismatch")
    failures = list(document.get("failures") or ())
    codes: list[str] = []
    if document.get("passed") is not True or any(
        row.get("passed") is not True for row in document.get("variants", ())
    ):
        if any("swap_partner_label_mismatch" in failure for failure in failures):
            codes.append("side_inconsistency")
        elif "risk_bucket_not_certifiable" in failures:
            codes.append("out_of_distribution")
        else:
            codes.append("perturbation_instability")
    return document, codes


def _evaluate_synthetic_truth_cases(
    cases: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]
) -> dict[str, Any]:
    if len(cases) != len(REQUIRED_SYNTHETIC_CASE_KINDS):
        raise OperationalPolicyError("synthetic truth suite must contain exactly four cases")
    indexed: dict[str, Mapping[str, Any]] = {}
    for raw in cases:
        if not isinstance(raw, Mapping) or set(raw) != _CASE_FIELDS:
            raise OperationalPolicyError("synthetic truth case has the wrong contract")
        kind = str(raw["case_kind"])
        if kind not in REQUIRED_SYNTHETIC_CASE_KINDS or kind in indexed:
            raise OperationalPolicyError("synthetic truth case kinds are unknown or duplicated")
        indexed[kind] = raw
    if set(indexed) != set(policy["required_synthetic_case_kinds"]):
        raise OperationalPolicyError("synthetic truth case coverage is incomplete")

    rows: list[dict[str, Any]] = []
    for kind in policy["required_synthetic_case_kinds"]:
        raw = indexed[kind]
        case_id = str(raw["case_id"])
        if _SAFE_ID.fullmatch(case_id) is None:
            raise OperationalPolicyError("synthetic truth case ID is invalid")
        truth_path = Path(raw["truth_mask_path"])
        candidate_path = Path(raw["candidate_mask_path"])
        truth = _strict_binary(truth_path)
        candidate = _strict_binary(candidate_path)
        if truth.shape != candidate.shape:
            raise OperationalPolicyError("synthetic truth candidate dimensions differ from truth")
        expected_label = str(raw["expected_label"])
        reported_label = str(raw["reported_label"])
        ontology_label = get_ontology().label(expected_label, require_enabled=True)
        pixel_equal = bool(np.array_equal(truth, candidate))
        label_equal = reported_label == expected_label
        findings: list[str] = []
        if not pixel_equal:
            findings.append("pixel_mismatch")
        if not label_equal:
            findings.append("side_inconsistency")
        observed_status = "pass" if pixel_equal and label_equal else "autonomous_abstention"
        expected_status = "pass" if kind == "exact_truth" else "autonomous_abstention"
        truth_area = int(np.count_nonzero(truth))
        candidate_area = int(np.count_nonzero(candidate))
        semantics_passed = {
            "exact_truth": pixel_equal and label_equal,
            "boundary_shift": (not pixel_equal and label_equal and candidate_area == truth_area),
            "missing_area": (not pixel_equal and label_equal and candidate_area < truth_area),
            "side_inconsistency": (
                pixel_equal
                and not label_equal
                and ontology_label.swap_partner is not None
                and reported_label == ontology_label.swap_partner
            ),
        }[kind]
        rows.append(
            {
                "case_id": case_id,
                "case_kind": kind,
                "truth_mask_sha256": sha256_file(truth_path),
                "candidate_mask_sha256": sha256_file(candidate_path),
                "expected_label": expected_label,
                "reported_label": reported_label,
                "pixel_equal": pixel_equal,
                "label_equal": label_equal,
                "expected_status": expected_status,
                "observed_status": observed_status,
                "detected_findings": sorted(findings),
                "passed": semantics_passed and observed_status == expected_status,
            }
        )
    summary = {
        "case_kinds": list(policy["required_synthetic_case_kinds"]),
        "cases": rows,
        "passed": all(row["passed"] for row in rows),
    }
    summary["evidence_sha256"] = canonical_sha256(summary)
    return summary


def _decision_core(
    candidate_scope: Mapping[str, Any], policy_sha256: str, abstention_codes: Sequence[str]
) -> dict[str, Any]:
    codes = sorted(set(abstention_codes))
    return {
        "status": "autonomous_abstention" if codes else "pass",
        "abstention_codes": codes,
        "output_artifact_identity_sha256s": list(
            candidate_scope["output_artifact_identity_sha256s"]
        ),
        "label": candidate_scope["label"],
        "risk_bucket": candidate_scope["risk_bucket"],
        "policy_sha256": policy_sha256,
        "seed": candidate_scope["seed"],
    }


def build_operational_policy_replay_observation(
    replay_id: str,
    *,
    input_sha256: str,
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    if _SAFE_ID.fullmatch(replay_id) is None or _SHA256.fullmatch(input_sha256) is None:
        raise OperationalPolicyError("operational replay identity is invalid")
    if set(decision) != _DECISION_CORE_FIELDS:
        raise OperationalPolicyError("operational replay decision has the wrong contract")
    document = {
        "replay_id": replay_id,
        "input_sha256": input_sha256,
        "decision": copy.deepcopy(dict(decision)),
        "decision_sha256": canonical_sha256(decision),
    }
    return document


def prepare_operational_policy_replay(
    stability_evidence: Mapping[str, Any],
    synthetic_truth_cases: Sequence[Mapping[str, Any]],
    *,
    candidate_scope: Mapping[str, Any],
    policy: Mapping[str, Any],
    stability_policy: Mapping[str, Any],
    replay_ids: Sequence[str] = ("replay-1", "replay-2"),
) -> tuple[dict[str, Any], ...]:
    scope = _validate_scope(candidate_scope, policy)
    stability, codes = _validate_stability_evidence(
        stability_evidence, candidate_scope=scope, stability_policy=stability_policy
    )
    synthetic = _evaluate_synthetic_truth_cases(synthetic_truth_cases, policy)
    if not synthetic["passed"]:
        codes.append("synthetic_policy_self_test_failed")
    policy_sha256 = canonical_sha256(policy)
    replay_input_sha256 = canonical_sha256(
        {
            "candidate_scope": scope,
            "perturbation_evidence_sha256": stability["sha256"],
            "synthetic_truth_evidence_sha256": synthetic["evidence_sha256"],
            "policy_sha256": policy_sha256,
            "stability_policy_sha256": canonical_sha256(stability_policy),
        }
    )
    decision = _decision_core(scope, policy_sha256, codes)
    if len(replay_ids) != policy["replay_count"] or len(set(replay_ids)) != len(replay_ids):
        raise OperationalPolicyError("operational replay IDs are incomplete or duplicated")
    return tuple(
        build_operational_policy_replay_observation(
            replay_id, input_sha256=replay_input_sha256, decision=decision
        )
        for replay_id in replay_ids
    )


def evaluate_operational_policy(
    stability_evidence: Mapping[str, Any],
    synthetic_truth_cases: Sequence[Mapping[str, Any]],
    replay_observations: Sequence[Mapping[str, Any]],
    *,
    report_id: str,
    candidate_scope: Mapping[str, Any],
    policy: Mapping[str, Any],
    stability_policy: Mapping[str, Any],
    evaluator_id: str,
    evaluator_sha256: str,
) -> dict[str, Any]:
    """Evaluate exact-output policy evidence and return pass or typed abstention."""
    if _SAFE_ID.fullmatch(report_id) is None or _SAFE_ID.fullmatch(evaluator_id) is None:
        raise OperationalPolicyError("operational policy report or evaluator ID is invalid")
    if _SHA256.fullmatch(evaluator_sha256) is None:
        raise OperationalPolicyError("operational policy evaluator hash is invalid")
    scope = _validate_scope(candidate_scope, policy)
    stability, codes = _validate_stability_evidence(
        stability_evidence, candidate_scope=scope, stability_policy=stability_policy
    )
    synthetic = _evaluate_synthetic_truth_cases(synthetic_truth_cases, policy)
    if not synthetic["passed"]:
        codes.append("synthetic_policy_self_test_failed")
    policy_sha256 = canonical_sha256(policy)
    stability_policy_sha256 = canonical_sha256(stability_policy)
    replay_input_sha256 = canonical_sha256(
        {
            "candidate_scope": scope,
            "perturbation_evidence_sha256": stability["sha256"],
            "synthetic_truth_evidence_sha256": synthetic["evidence_sha256"],
            "policy_sha256": policy_sha256,
            "stability_policy_sha256": stability_policy_sha256,
        }
    )
    expected_decision = _decision_core(scope, policy_sha256, codes)
    replay_rows: list[dict[str, Any]] = []
    replay_valid = len(replay_observations) == policy["replay_count"]
    replay_ids: set[str] = set()
    for raw in replay_observations:
        if not isinstance(raw, Mapping) or set(raw) != _REPLAY_FIELDS:
            replay_valid = False
            continue
        row = copy.deepcopy(dict(raw))
        replay_id = str(row["replay_id"])
        if _SAFE_ID.fullmatch(replay_id) is None or replay_id in replay_ids:
            replay_valid = False
        replay_ids.add(replay_id)
        decision = row.get("decision")
        if not isinstance(decision, Mapping) or set(decision) != _DECISION_CORE_FIELDS:
            replay_valid = False
        elif row.get("decision_sha256") != canonical_sha256(decision):
            replay_valid = False
        elif dict(decision) != expected_decision:
            replay_valid = False
        if row.get("input_sha256") != replay_input_sha256:
            replay_valid = False
        replay_rows.append(row)
    if len(replay_ids) != policy["replay_count"]:
        replay_valid = False
    replay_summary = {
        "observations": replay_rows,
        "reproducible": replay_valid,
    }
    replay_summary["evidence_sha256"] = canonical_sha256(replay_summary)
    if not replay_valid:
        codes.append("deterministic_replay_mismatch")

    decision_core = _decision_core(scope, policy_sha256, codes)
    decision = {
        **decision_core,
        "may_issue_certificate": not codes,
        "decision_sha256": canonical_sha256(decision_core),
    }
    evidence_by_gate = {
        "perturbation": stability["sha256"],
        "metamorphic": synthetic["evidence_sha256"],
        "stability_replay": replay_summary["evidence_sha256"],
    }
    report = {
        "schema_version": "1.0.0",
        "report_id": report_id,
        "candidate_scope": scope,
        "policy": {
            "policy_id": policy["policy_id"],
            "policy_sha256": policy_sha256,
            "stability_policy_id": stability_policy["policy_id"],
            "stability_policy_sha256": stability_policy_sha256,
        },
        "evaluator": {
            "evaluator_id": evaluator_id,
            "evaluator_sha256": evaluator_sha256,
        },
        "perturbation": {
            "evidence_sha256": stability["sha256"],
            "passed": stability["passed"],
            "failures": sorted(stability["failures"]),
        },
        "synthetic_truth": synthetic,
        "replay": replay_summary,
        "decision": decision,
        "gate_bindings": [
            {
                "gate_id": gate_id,
                "evidence_sha256": evidence_by_gate[gate_id],
                "executor_id": evaluator_id,
                "executor_sha256": evaluator_sha256,
            }
            for gate_id in policy["required_gate_ids"]
        ],
    }
    report["report_sha256"] = canonical_sha256(report)
    try:
        require_valid_document(report, "operational_policy_evidence")
    except ArtifactValidationError as exc:
        raise OperationalPolicyError(f"operational policy evidence is invalid: {exc}") from exc
    return report


def verify_operational_policy_report(report: Mapping[str, Any]) -> None:
    document = copy.deepcopy(dict(report))
    try:
        require_valid_document(document, "operational_policy_evidence")
    except ArtifactValidationError as exc:
        raise OperationalPolicyError(f"operational policy evidence is invalid: {exc}") from exc
    unsigned = {key: value for key, value in document.items() if key != "report_sha256"}
    if document.get("report_sha256") != canonical_sha256(unsigned):
        raise OperationalPolicyError("operational policy evidence hash mismatch")
    if {row["gate_id"] for row in document["gate_bindings"]} != REQUIRED_GATE_IDS:
        raise OperationalPolicyError("operational policy gate bindings are incomplete")
    if set(document["synthetic_truth"]["case_kinds"]) != REQUIRED_SYNTHETIC_CASE_KINDS:
        raise OperationalPolicyError("operational policy synthetic coverage is incomplete")
    decision = document["decision"]
    core = {key: decision[key] for key in _DECISION_CORE_FIELDS}
    if decision["decision_sha256"] != canonical_sha256(core):
        raise OperationalPolicyError("operational policy decision hash mismatch")
    if decision["may_issue_certificate"] != (decision["status"] == "pass"):
        raise OperationalPolicyError("operational policy decision authority is inconsistent")


def bind_operational_policy_report(
    unsigned_certificate: Mapping[str, Any], report: Mapping[str, Any]
) -> dict[str, Any]:
    """Bind the three existing frozen-v1 QA gate rows to a verified report."""
    verify_operational_policy_report(report)
    document = copy.deepcopy(dict(unsigned_certificate))
    qa_evidence = document.get("qa_evidence")
    if not isinstance(qa_evidence, dict):
        raise OperationalPolicyError("certificate QA evidence is missing")
    qa_evidence["qa_policy_id"] = report["policy"]["policy_id"]
    qa_evidence["qa_policy_sha256"] = report["policy"]["policy_sha256"]
    indexed = {row.get("gate_id"): row for row in qa_evidence.get("gate_results", ())}
    for binding in report["gate_bindings"]:
        gate = indexed.get(binding["gate_id"])
        if not isinstance(gate, dict):
            raise OperationalPolicyError(f"certificate QA gate is missing: {binding['gate_id']}")
        gate.update(
            evidence_sha256=binding["evidence_sha256"],
            executor_id=binding["executor_id"],
            executor_sha256=binding["executor_sha256"],
        )
    return document


def validate_operational_policy_report_binding(
    report: Mapping[str, Any],
    certificate: Mapping[str, Any],
    *,
    trusted_evaluators: Mapping[str, str],
) -> tuple[str, ...]:
    codes: list[str] = []
    try:
        verify_operational_policy_report(report)
    except OperationalPolicyError:
        return ("operational_policy_report_invalid",)
    evaluator = report["evaluator"]
    if trusted_evaluators.get(evaluator["evaluator_id"]) != evaluator["evaluator_sha256"]:
        codes.append("operational_policy_evaluator_untrusted")
    decision = report["decision"]
    if decision["status"] != "pass" or decision["may_issue_certificate"] is not True:
        codes.append("operational_policy_abstained")
    scope = report["candidate_scope"]
    source = certificate.get("source_binding", {})
    certified_scope = certificate.get("certified_output_scope", {})
    execution = certificate.get("execution_binding", {})
    route = certificate.get("qualified_route_scope", {})
    pipeline_policy = certificate.get("pipeline_policy_binding", {})
    qa_evidence = certificate.get("qa_evidence", {})
    artifacts = certificate.get("bound_artifacts", ())
    if scope["source_decoded_pixel_sha256"] != source.get("decoded_pixel_sha256"):
        codes.append("operational_policy_source_scope_mismatch")
    if scope["output_artifact_identity_sha256s"] != certified_scope.get(
        "artifact_identity_sha256s"
    ):
        codes.append("operational_policy_output_scope_mismatch")
    if scope["pipeline_fingerprint"] != execution.get("execution_fingerprint_sha256"):
        codes.append("operational_policy_pipeline_scope_mismatch")
    if scope["label"] not in {row.get("label") for row in artifacts if isinstance(row, Mapping)}:
        codes.append("operational_policy_label_scope_mismatch")
    if scope["risk_bucket"] not in set(route.get("risk_buckets") or ()):
        codes.append("operational_policy_risk_scope_mismatch")
    if scope["seed"] != pipeline_policy.get("seed"):
        codes.append("operational_policy_seed_mismatch")
    if report["policy"]["policy_id"] != qa_evidence.get("qa_policy_id") or report["policy"][
        "policy_sha256"
    ] != qa_evidence.get("qa_policy_sha256"):
        codes.append("operational_policy_identity_mismatch")
    gate_rows = {row.get("gate_id"): row for row in qa_evidence.get("gate_results", ())}
    for binding in report["gate_bindings"]:
        row = gate_rows.get(binding["gate_id"])
        if not isinstance(row, Mapping) or any(
            row.get(field) != binding[field]
            for field in ("evidence_sha256", "executor_id", "executor_sha256")
        ):
            codes.append(f"operational_policy_gate_binding:{binding['gate_id']}")
    return tuple(sorted(set(codes)))


__all__ = [
    "OperationalPolicyError",
    "REQUIRED_GATE_IDS",
    "REQUIRED_SYNTHETIC_CASE_KINDS",
    "bind_operational_policy_report",
    "build_operational_policy_replay_observation",
    "evaluate_operational_policy",
    "load_operational_policy",
    "prepare_operational_policy_replay",
    "validate_operational_policy_report_binding",
    "verify_operational_policy_report",
]
