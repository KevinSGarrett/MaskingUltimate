"""Frozen provider-neutral Mode A/Mode B workflow performance evidence."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from ..validation import ArtifactValidationError, require_valid_document

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY = ROOT / "qa" / "governance" / "serving_workflow_performance_v1.json"
LOCKED_POLICY_SHA256 = "d48666d930c4deb8eed214ba00434a66e8601930e723ae56a887aa88905a6666"
CASE_IDS = (
    "mode_b_predict_single",
    "mode_b_predict_multi",
    "mode_b_refine_single",
    "mode_b_refine_multi",
    "mode_a_package_single",
    "mode_a_package_multi",
)
ROLLBACK_ROLES = (
    "champion_bodypart",
    "champion_hand",
    "champion_clothing",
    "interactive_segmenter",
)
MODE_A_TRUTH_TIERS = ("human_anchor_gold", "autonomous_certified_gold")


class WorkflowPerformanceError(ValueError):
    """Workflow performance evidence is incomplete, stale, or overclaims authority."""


def canonical_sha256(value: Any) -> str:
    """Return the canonical JSON identity used by policy and report seals."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def file_sha256(path: Path) -> str:
    """Hash a potentially large evidence artifact without loading it all at once."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkflowPerformanceError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise WorkflowPerformanceError(f"{field} lacks a timezone")
    return parsed.astimezone(UTC)


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorkflowPerformanceError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise WorkflowPerformanceError(f"{field} must be finite and nonnegative")
    return result


def _artifact_path(value: Any, artifact_root: Path, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise WorkflowPerformanceError(f"{field} path is empty")
    candidate = Path(value)
    path = candidate if candidate.is_absolute() else Path(artifact_root) / candidate
    path = path.resolve()
    if not path.is_file():
        raise WorkflowPerformanceError(f"{field} artifact is missing: {value}")
    return path


def _verify_artifact(
    *, path_value: Any, digest_value: Any, artifact_root: Path, field: str
) -> Path:
    path = _artifact_path(path_value, artifact_root, field)
    if not isinstance(digest_value, str) or file_sha256(path) != digest_value:
        raise WorkflowPerformanceError(f"{field} artifact hash mismatch")
    return path


def validate_policy(
    document: Mapping[str, Any],
    *,
    root: Path = ROOT,
    expected_sha256: str | None = LOCKED_POLICY_SHA256,
) -> None:
    """Validate the frozen contract and every source byte it governs."""
    try:
        require_valid_document(dict(document), "serving_workflow_performance_policy")
    except ArtifactValidationError as exc:
        raise WorkflowPerformanceError(str(exc)) from exc
    payload = {key: value for key, value in document.items() if key != "sha256"}
    digest = canonical_sha256(payload)
    if document.get("sha256") != digest:
        raise WorkflowPerformanceError("workflow performance policy hash mismatch")
    if expected_sha256 is not None and digest != expected_sha256:
        raise WorkflowPerformanceError("workflow performance policy differs from locked hash")
    _timestamp(document["frozen_at"], "frozen_at")
    if document["source_scopes"] != {
        "single_person": {"minimum_people": 1, "maximum_people": 1},
        "multi_person": {"minimum_people": 2, "maximum_people": 4},
    }:
        raise WorkflowPerformanceError("workflow source scopes drifted")
    if document["source_requirements"] != {
        "governance_decision_required": True,
        "image_disjoint_from_training_calibration_and_tuning": True,
        "unseen_before_measurement": True,
        "private_source_path_may_be_outside_git": True,
    }:
        raise WorkflowPerformanceError("workflow source requirements drifted")
    cases = document["cases"]
    if tuple(case["case_id"] for case in cases) != CASE_IDS:
        raise WorkflowPerformanceError("workflow case inventory or order drifted")
    expected_case_identity = {
        "mode_b_predict_single": ("mode_b", "predict", "single_person"),
        "mode_b_predict_multi": ("mode_b", "predict", "multi_person"),
        "mode_b_refine_single": ("mode_b", "refine", "single_person"),
        "mode_b_refine_multi": ("mode_b", "refine", "multi_person"),
        "mode_a_package_single": ("mode_a", "package_read", "single_person"),
        "mode_a_package_multi": ("mode_a", "package_read", "multi_person"),
    }
    for case in cases:
        identity = (case["mode"], case["operation"], case["source_scope"])
        if identity != expected_case_identity[case["case_id"]]:
            raise WorkflowPerformanceError(f"{case['case_id']} identity drifted")
        expected_roles = (
            ["champion_bodypart", "champion_hand", "champion_clothing"]
            if case["operation"] == "predict"
            else ["interactive_segmenter"] if case["operation"] == "refine" else []
        )
        if case["required_provider_roles"] != expected_roles:
            raise WorkflowPerformanceError(f"{case['case_id']} provider roles drifted")
        _validate_latency_policy(case)
    if document["mode_a_requirements"] != {
        "eligible_truth_tiers": list(MODE_A_TRUTH_TIERS),
        "package_tree_unchanged": True,
        "maximum_model_load_count": 0,
        "maximum_write_attempt_count": 0,
    }:
        raise WorkflowPerformanceError("Mode A requirements drifted")
    if document["common_requirements"] != {
        "minimum_deterministic_repetitions": 2,
        "maximum_oom_count": 0,
        "maximum_crash_count": 0,
        "strict_output_required": True,
        "complete_provenance_required": True,
        "vram_measurement_required": True,
    }:
        raise WorkflowPerformanceError("workflow common requirements drifted")
    if tuple(document["rollback_roles"]) != ROLLBACK_ROLES:
        raise WorkflowPerformanceError("workflow rollback role inventory drifted")
    if document["rollback_requirements"] != {
        "active_and_rollback_provider_must_differ": True,
        "allowed_lifecycle_states": ["benchmarked", "promoted"],
        "rollback_smoke_required": True,
        "restored_smoke_required": True,
        "selection_and_lifecycle_round_trip_required": True,
        "frozen_artifacts_must_remain_unchanged": True,
    }:
        raise WorkflowPerformanceError("workflow rollback requirements drifted")
    for relative, expected in document["source_hashes"].items():
        path = (Path(root) / relative).resolve()
        try:
            path.relative_to(Path(root).resolve())
        except ValueError as exc:
            raise WorkflowPerformanceError("governing source escapes repository") from exc
        if not path.is_file() or file_sha256(path) != expected:
            raise WorkflowPerformanceError(f"governing source hash drift: {relative}")


def _validate_latency_policy(case: Mapping[str, Any]) -> None:
    operation = case["operation"]
    expected = (
        {
            "cold_start": (1, 60.0),
            "predict_all_warm": (3, 4.0),
            "predict_single_warm": (3, 2.0),
        }
        if operation == "predict"
        else (
            {"cold_start": (1, 60.0), "refine_per_click": (3, 1.2)}
            if operation == "refine"
            else {"package_cold": (1, None), "package_warm": (3, None)}
        )
    )
    observed = {
        key: (value["minimum_samples"], value["maximum_seconds"])
        for key, value in case["required_latency_checks"].items()
    }
    if observed != expected:
        raise WorkflowPerformanceError(f"{case['case_id']} latency contract drifted")


def load_policy(path: Path = DEFAULT_POLICY, *, root: Path = ROOT) -> dict[str, Any]:
    """Load and fully verify the locked pre-result policy."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowPerformanceError("workflow performance policy is unreadable") from exc
    if not isinstance(document, dict):
        raise WorkflowPerformanceError("workflow performance policy is not an object")
    validate_policy(document, root=root)
    return document


def verify_workflow_performance_report(
    report: Mapping[str, Any],
    *,
    policy_path: Path = DEFAULT_POLICY,
    policy_root: Path = ROOT,
    artifact_root: Path = ROOT,
) -> dict[str, Any]:
    """Recompute a complete real Mode A/Mode B report and reject partial evidence."""
    document = dict(report)
    try:
        require_valid_document(document, "serving_workflow_performance_report")
    except ArtifactValidationError as exc:
        raise WorkflowPerformanceError(str(exc)) from exc
    policy = load_policy(policy_path, root=policy_root)
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if document["sha256"] != canonical_sha256(payload):
        raise WorkflowPerformanceError("workflow performance report hash mismatch")
    if document["policy_sha256"] != policy["sha256"]:
        raise WorkflowPerformanceError("workflow performance report policy binding mismatch")
    _timestamp(document["measured_at"], "measured_at")
    sources = _verify_sources(document["sources"], policy, Path(artifact_root))
    cases = {row["case_id"]: row for row in document["case_results"]}
    if len(cases) != len(CASE_IDS) or set(cases) != set(CASE_IDS):
        raise WorkflowPerformanceError("workflow report case coverage is incomplete or duplicated")
    policy_cases = {row["case_id"]: row for row in policy["cases"]}
    for case_id in CASE_IDS:
        _verify_case(cases[case_id], policy_cases[case_id], sources, policy, Path(artifact_root))
    _verify_rollbacks(document["rollback_results"], policy, Path(artifact_root))
    return {
        "status": "pass_complete_live_measurements",
        "policy_sha256": policy["sha256"],
        "report_sha256": document["sha256"],
        "source_count": len(sources),
        "case_count": len(cases),
        "rollback_role_count": len(document["rollback_results"]),
    }


def _verify_sources(
    rows: Sequence[Mapping[str, Any]], policy: Mapping[str, Any], artifact_root: Path
) -> dict[str, Mapping[str, Any]]:
    sources: dict[str, Mapping[str, Any]] = {}
    scopes: dict[str, Mapping[str, Any]] = {}
    image_ids: set[str] = set()
    image_hashes: set[str] = set()
    for row in rows:
        source_id = row["source_id"]
        if source_id in sources or row["scope"] in scopes:
            raise WorkflowPerformanceError("workflow sources duplicate identity or scope")
        if row["image_id"] in image_ids or row["image_sha256"] in image_hashes:
            raise WorkflowPerformanceError(
                "single- and multi-person sources must be image-disjoint"
            )
        scope = policy["source_scopes"][row["scope"]]
        if not scope["minimum_people"] <= row["person_count"] <= scope["maximum_people"]:
            raise WorkflowPerformanceError(f"{source_id} person count is outside its scope")
        image_path = _verify_artifact(
            path_value=row["image_path"],
            digest_value=row["image_sha256"],
            artifact_root=artifact_root,
            field=f"{source_id}.image",
        )
        try:
            with Image.open(image_path) as opened:
                opened.verify()
                if opened.width < 1 or opened.height < 1:
                    raise ValueError
        except (OSError, ValueError) as exc:
            raise WorkflowPerformanceError(f"{source_id} image is not a readable raster") from exc
        _verify_artifact(
            path_value=row["governance_decision_path"],
            digest_value=row["governance_decision_sha256"],
            artifact_root=artifact_root,
            field=f"{source_id}.governance_decision",
        )
        sources[source_id] = row
        scopes[row["scope"]] = row
        image_ids.add(row["image_id"])
        image_hashes.add(row["image_sha256"])
    if set(scopes) != set(policy["source_scopes"]):
        raise WorkflowPerformanceError("workflow sources do not cover single and multi scopes")
    return sources


def _verify_case(
    result: Mapping[str, Any],
    case: Mapping[str, Any],
    sources: Mapping[str, Mapping[str, Any]],
    policy: Mapping[str, Any],
    artifact_root: Path,
) -> None:
    if (result["mode"], result["operation"]) != (case["mode"], case["operation"]):
        raise WorkflowPerformanceError(f"{case['case_id']} mode/operation mismatch")
    source = sources.get(result["source_id"])
    if source is None or source["scope"] != case["source_scope"]:
        raise WorkflowPerformanceError(f"{case['case_id']} source scope mismatch")
    providers = result["providers"]
    provider_roles = [row["role"] for row in providers]
    if provider_roles != case["required_provider_roles"] or len(provider_roles) != len(
        set(provider_roles)
    ):
        raise WorkflowPerformanceError(f"{case['case_id']} provider coverage mismatch")
    if len({row["provider_key"] for row in providers}) != len(providers):
        raise WorkflowPerformanceError(f"{case['case_id']} provider keys are not distinct")
    latency = result["latency"]
    requirements = case["required_latency_checks"]
    if set(latency) != set(requirements):
        raise WorkflowPerformanceError(f"{case['case_id']} latency coverage mismatch")
    for name, requirement in requirements.items():
        samples = latency[name]["samples_seconds"]
        if len(samples) < requirement["minimum_samples"]:
            raise WorkflowPerformanceError(f"{case['case_id']}.{name} sample floor failed")
        values = tuple(_finite(value, f"{case['case_id']}.{name}") for value in samples)
        maximum = requirement["maximum_seconds"]
        if maximum is not None and max(values) > maximum:
            raise WorkflowPerformanceError(f"{case['case_id']}.{name} latency gate failed")
    vram = result["vram"]
    before = _finite(vram["before_bytes"], f"{case['case_id']}.vram.before")
    peak = _finite(vram["peak_bytes"], f"{case['case_id']}.vram.peak")
    _finite(vram["after_bytes"], f"{case['case_id']}.vram.after")
    if peak < before:
        raise WorkflowPerformanceError(f"{case['case_id']} peak VRAM precedes baseline")
    common = policy["common_requirements"]
    if result["oom_count"] > common["maximum_oom_count"]:
        raise WorkflowPerformanceError(f"{case['case_id']} OOM gate failed")
    if result["crash_count"] > common["maximum_crash_count"]:
        raise WorkflowPerformanceError(f"{case['case_id']} crash gate failed")
    determinism = result["determinism"]
    hashes = determinism["output_sha256s"]
    if (
        determinism["repetitions"] < common["minimum_deterministic_repetitions"]
        or len(hashes) != determinism["repetitions"]
        or len(set(hashes)) != 1
        or hashes[0] != result["output_artifact_sha256"]
    ):
        raise WorkflowPerformanceError(f"{case['case_id']} determinism gate failed")
    _verify_artifact(
        path_value=result["provenance_path"],
        digest_value=result["provenance_sha256"],
        artifact_root=artifact_root,
        field=f"{case['case_id']}.provenance",
    )
    _verify_artifact(
        path_value=result["output_artifact_path"],
        digest_value=result["output_artifact_sha256"],
        artifact_root=artifact_root,
        field=f"{case['case_id']}.output",
    )
    read_only = result["read_only"]
    if case["mode"] == "mode_a":
        if not isinstance(read_only, Mapping):
            raise WorkflowPerformanceError(f"{case['case_id']} lacks Mode A read-only evidence")
        _verify_artifact(
            path_value=read_only["package_manifest_path"],
            digest_value=read_only["package_manifest_sha256"],
            artifact_root=artifact_root,
            field=f"{case['case_id']}.package_manifest",
        )
        mode_a = policy["mode_a_requirements"]
        if read_only["truth_tier"] not in mode_a["eligible_truth_tiers"]:
            raise WorkflowPerformanceError(f"{case['case_id']} truth tier is ineligible")
        if read_only["package_tree_sha256_before"] != read_only["package_tree_sha256_after"]:
            raise WorkflowPerformanceError(f"{case['case_id']} mutated the package tree")
        if read_only["model_load_count"] > mode_a["maximum_model_load_count"]:
            raise WorkflowPerformanceError(f"{case['case_id']} loaded a model in Mode A")
        if read_only["write_attempt_count"] > mode_a["maximum_write_attempt_count"]:
            raise WorkflowPerformanceError(f"{case['case_id']} attempted a package write")
    elif read_only is not None:
        raise WorkflowPerformanceError(f"{case['case_id']} has unexpected Mode A evidence")


def _verify_rollbacks(
    rows: Sequence[Mapping[str, Any]], policy: Mapping[str, Any], artifact_root: Path
) -> None:
    mapped = {row["role"]: row for row in rows}
    if len(mapped) != len(ROLLBACK_ROLES) or tuple(row["role"] for row in rows) != ROLLBACK_ROLES:
        raise WorkflowPerformanceError("workflow rollback role coverage or order is invalid")
    allowed = set(policy["rollback_requirements"]["allowed_lifecycle_states"])
    for role in ROLLBACK_ROLES:
        row = mapped[role]
        if row["active_provider"] == row["rollback_provider"]:
            raise WorkflowPerformanceError(f"{role} rollback provider is not distinct")
        if {row["active_lifecycle_state"], row["rollback_lifecycle_state"]} - allowed:
            raise WorkflowPerformanceError(f"{role} rollback lifecycle is ineligible")
        if row["selection_sha256_before"] != row["selection_sha256_restored"]:
            raise WorkflowPerformanceError(f"{role} selection was not restored")
        if row["selection_sha256_during_rollback"] == row["selection_sha256_before"]:
            raise WorkflowPerformanceError(f"{role} rollback selection did not change")
        _verify_artifact(
            path_value=row["rollback_smoke_path"],
            digest_value=row["rollback_smoke_sha256"],
            artifact_root=artifact_root,
            field=f"{role}.rollback_smoke",
        )
        _verify_artifact(
            path_value=row["restored_smoke_path"],
            digest_value=row["restored_smoke_sha256"],
            artifact_root=artifact_root,
            field=f"{role}.restored_smoke",
        )


__all__ = [
    "CASE_IDS",
    "DEFAULT_POLICY",
    "LOCKED_POLICY_SHA256",
    "MODE_A_TRUTH_TIERS",
    "ROLLBACK_ROLES",
    "WorkflowPerformanceError",
    "canonical_sha256",
    "file_sha256",
    "load_policy",
    "validate_policy",
    "verify_workflow_performance_report",
]
