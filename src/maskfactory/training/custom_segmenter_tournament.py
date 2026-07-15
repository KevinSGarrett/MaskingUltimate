"""Frozen fair-training tournament for the three custom segmenter families."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..validation import ArtifactValidationError, require_valid_document
from .bodypart.v2_contract import V2_CLASS_NAMES

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY_PATH = (
    ROOT
    / "qa"
    / "governance"
    / "benchmark_matrices"
    / "custom_segmenter_training_tournament_v1.json"
)
POLICY_SHA256 = "550ff7c9efce0bef8cddc55c943dacb8d90ab066fd18a11e004984cfedfee983"
PROVIDERS = ("segformer_b3", "mask2former_swin_b", "eomt_dinov3_small_640")
CONTEXTS = (
    "clothing_materials",
    "contact",
    "crowding",
    "duo_baseline",
    "duo_overlap",
    "hair_boundaries",
    "hands_feet",
    "identity_ambiguity",
    "multi_person_overlap",
    "occlusion",
    "occlusion_contact",
    "scale_disparity",
    "sensitive_anatomy",
    "small_group_baseline",
    "small_group_overlap",
    "small_parts",
    "truncation",
)
ERROR_FAMILIES = (
    "anatomy_clothing_confusion_rate",
    "crash_rate",
    "cross_person_bleed_rate",
    "determinism_failure_rate",
    "front_back_error_rate",
    "hallucinated_part_rate",
    "hard_qa_failure_rate",
    "instance_identity_error_rate",
    "left_right_error_rate",
    "oom_rate",
    "protected_region_failure_rate",
    "rollback_failure_rate",
)
REQUIRED_ARTIFACT_KEYS = (
    "evaluation_observations",
    "final_checkpoint",
    "initial_checkpoint",
    "run_config",
    "runtime_lock",
    "train_log",
)
SOURCE_FILES = (
    "configs/ontology_v2.yaml",
    "configs/qa.yaml",
    "configs/training/bodypart_v2_mask2former_swinb.yaml",
    "configs/training/bodypart_v2_segformer_b3.yaml",
    "configs/training/eomt_dinov3_small_v2.yaml",
    "env/eomt_dinov3_runtime.lock.json",
    "qa/governance/benchmark_matrices/custom_segmenter_margins_v1.json",
    "src/maskfactory/training/bodypart/v2_contract.py",
    "src/maskfactory/training/mmseg_metric.py",
    "src/maskfactory/training/run.py",
)
MEASUREMENT_SOURCE_FILES = (
    "configs/ontology_v2.yaml",
    "configs/qa.yaml",
    "qa/governance/benchmark_matrices/custom_segmenter_margins_v1.json",
    "src/maskfactory/training/bodypart/v2_contract.py",
    "src/maskfactory/training/mmseg_metric.py",
    "src/maskfactory/training/run.py",
)
SHARED_TRAINING_KEYS = (
    "amp",
    "batch_per_gpu",
    "class_weights",
    "gradient_accumulation",
    "iterations",
    "iterations_at_500_gold",
)
RUN_MANIFEST_KEYS = frozenset(
    {
        "run_id",
        "provider",
        "status",
        "started_at",
        "completed_at",
        "config_sha256",
        "shared_identity_sha256",
        "dataset_manifest_sha256",
        "holdout_manifest_sha256",
        "ontology_sha256",
        "qa_sha256",
        "measurement_bundle_sha256",
        "hardware_fingerprint_sha256",
        "seed",
        "iterations_completed",
        "artifact_hashes",
        "runtime_fingerprint_sha256",
    }
)
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class CustomSegmenterTournamentError(ValueError):
    """The frozen tournament policy, run records, or report are invalid."""


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise CustomSegmenterTournamentError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise CustomSegmenterTournamentError(f"{field} lacks a timezone")
    return parsed.astimezone(UTC)


def _count(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CustomSegmenterTournamentError(f"{field} must be a nonnegative integer")
    return value


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CustomSegmenterTournamentError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise CustomSegmenterTournamentError(f"{field} must be finite and nonnegative")
    return result


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None


def _load_yaml(path: Path) -> Mapping[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise CustomSegmenterTournamentError(f"training config is not an object: {path}")
    return document


def _training_surface(config: Mapping[str, Any]) -> dict[str, Any]:
    training = config.get("training")
    if not isinstance(training, Mapping):
        raise CustomSegmenterTournamentError("training config lacks a training object")
    try:
        return {key: training[key] for key in SHARED_TRAINING_KEYS}
    except KeyError as exc:
        raise CustomSegmenterTournamentError(
            f"training config lacks shared field: {exc.args[0]}"
        ) from exc


def _validate_training_configs(policy: Mapping[str, Any], root: Path) -> None:
    surfaces: dict[str, dict[str, Any]] = {}
    for provider in PROVIDERS:
        spec = policy["providers"][provider]
        config_path = Path(root) / spec["config_path"]
        if not config_path.is_file() or _file_sha256(config_path) != spec["config_sha256"]:
            raise CustomSegmenterTournamentError(f"{provider} training config hash drift")
        config = _load_yaml(config_path)
        surfaces[provider] = {
            "data": config.get("data"),
            "augmentations": config.get("augmentations"),
            "training": _training_surface(config),
            "evaluation": config.get("evaluation"),
            "thermal": config.get("thermal"),
        }
        for name, value in surfaces[provider].items():
            if canonical_sha256(value) != policy["shared_contract_hashes"][name]:
                raise CustomSegmenterTournamentError(
                    f"{provider} {name} surface differs from frozen fair-training contract"
                )
    baseline = surfaces[PROVIDERS[0]]
    if any(surfaces[provider] != baseline for provider in PROVIDERS[1:]):
        raise CustomSegmenterTournamentError("provider fair-training surfaces are not identical")

    for provider in PROVIDERS[:2]:
        config = _load_yaml(Path(root) / policy["providers"][provider]["config_path"])
        model = config.get("model", {})
        if (
            model.get("num_classes") != len(V2_CLASS_NAMES)
            or tuple(model.get("classes", ())) != V2_CLASS_NAMES
        ):
            raise CustomSegmenterTournamentError(f"{provider} ontology vocabulary drift")


def validate_policy(
    document: Mapping[str, Any],
    *,
    root: Path = ROOT,
    expected_sha256: str | None = POLICY_SHA256,
) -> None:
    try:
        require_valid_document(document, "custom_segmenter_tournament_policy")
    except ArtifactValidationError as exc:
        raise CustomSegmenterTournamentError(str(exc)) from exc
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if document["sha256"] != canonical_sha256(payload):
        raise CustomSegmenterTournamentError("tournament policy hash mismatch")
    if expected_sha256 is not None and document["sha256"] != expected_sha256:
        raise CustomSegmenterTournamentError("tournament policy differs from locked hash")
    if tuple(document["providers"]) != PROVIDERS:
        raise CustomSegmenterTournamentError("tournament provider ordering or set drifted")
    if tuple(document["required_contexts"]) != CONTEXTS:
        raise CustomSegmenterTournamentError("tournament context vocabulary drifted")
    if tuple(document["required_error_families"]) != ERROR_FAMILIES:
        raise CustomSegmenterTournamentError("tournament error vocabulary drifted")
    if tuple(document["required_run_artifact_keys"]) != REQUIRED_ARTIFACT_KEYS:
        raise CustomSegmenterTournamentError("tournament run artifact contract drifted")
    if set(document["source_hashes"]) != set(SOURCE_FILES):
        raise CustomSegmenterTournamentError("tournament source hash set is incomplete")
    for relative in SOURCE_FILES:
        source = Path(root) / relative
        if not source.is_file() or _file_sha256(source) != document["source_hashes"][relative]:
            raise CustomSegmenterTournamentError(f"governing source hash drift: {relative}")

    eligible = document["eligible_data"]
    if eligible != {
        "minimum_certified_training_packages": 200,
        "training_partition": "train",
        "evaluation_tier": "human_anchor_gold",
        "evaluation_partition": "holdout",
        "train_holdout_overlap_allowed": False,
    }:
        raise CustomSegmenterTournamentError("eligible data contract drifted")
    values = document["shared_values"]
    expected_values = {
        "ontology_version": "body_parts_v2",
        "class_count": 65,
        "class_names_sha256": canonical_sha256(list(V2_CLASS_NAMES)),
        "ignore_index": 255,
        "seed": 1337,
        "crop_size": [512, 512],
        "iterations": 40000,
        "iterations_at_500_gold": 80000,
        "batch_per_gpu": 2,
        "gradient_accumulation": 8,
        "amp": "bf16",
        "evaluation_interval_iters": 4000,
        "evaluation_metrics": [
            "per_class_iou",
            "boundary_f_2px",
            "positive_recall",
            "clothed_false_positive_rate",
            "left_right_swap_rate",
        ],
        "evaluation_splits": [
            "positive_holdout",
            "clothed_negative_holdout",
            "hard_case_holdout",
        ],
        "required_deterministic_repeats": 2,
        "max_temperature_celsius": 87,
    }
    if values != expected_values:
        raise CustomSegmenterTournamentError("shared training values drifted")
    if document["providers"]["eomt_dinov3_small_640"]["frozen_initial_artifact_hashes"] != {
        "initial_checkpoint": "1fed3231445cce739e368c1828f49215459ca33ba56b6712d48e3058274c5d6f"
    }:
        raise CustomSegmenterTournamentError("EoMT frozen initial checkpoint drifted")
    _validate_training_configs(document, Path(root))


def load_policy(path: Path = DEFAULT_POLICY_PATH, *, root: Path = ROOT) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise CustomSegmenterTournamentError("tournament policy is not an object")
    validate_policy(document, root=root)
    return document


def measurement_bundle_sha256(policy: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {relative: policy["source_hashes"][relative] for relative in MEASUREMENT_SOURCE_FILES}
    )


def _validate_metric_observation(provider: str, row: Mapping[str, Any]) -> None:
    prefix = f"{provider}.{row.get('name', '<unnamed>')}"
    counts = {
        field: _count(row[field], f"{prefix}.{field}")
        for field in (
            "truth_pixels",
            "predicted_pixels",
            "intersection_pixels",
            "union_pixels",
            "boundary_tp",
            "boundary_fp",
            "boundary_fn",
            "small_part_eligible_count",
            "small_part_hit_count",
            "correction_pixels",
            "evaluated_pixels",
        )
    }
    if counts["intersection_pixels"] > min(counts["truth_pixels"], counts["predicted_pixels"]):
        raise CustomSegmenterTournamentError(f"{prefix} intersection exceeds input pixels")
    if counts["union_pixels"] != (
        counts["truth_pixels"] + counts["predicted_pixels"] - counts["intersection_pixels"]
    ):
        raise CustomSegmenterTournamentError(f"{prefix} union identity failed")
    if counts["small_part_hit_count"] > counts["small_part_eligible_count"]:
        raise CustomSegmenterTournamentError(f"{prefix} small-part hits exceed eligibility")
    if counts["correction_pixels"] > counts["evaluated_pixels"]:
        raise CustomSegmenterTournamentError(f"{prefix} corrections exceed evaluated pixels")


def _validate_named_rows(
    provider: str,
    rows: Sequence[Mapping[str, Any]],
    expected_names: Sequence[str],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        name = row["name"]
        if name not in expected_names or name in result:
            raise CustomSegmenterTournamentError(f"{provider} observation vocabulary is invalid")
        _validate_metric_observation(provider, row)
        result[name] = row
    if set(result) != set(expected_names):
        raise CustomSegmenterTournamentError(f"{provider} observation coverage is incomplete")
    return result


def _validate_error_rows(
    provider: str, rows: Sequence[Mapping[str, Any]]
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        name = row["name"]
        if name not in ERROR_FAMILIES or name in result:
            raise CustomSegmenterTournamentError(f"{provider} error vocabulary is invalid")
        eligible = _count(row["eligible_count"], f"{provider}.{name}.eligible_count")
        errors = _count(row["error_count"], f"{provider}.{name}.error_count")
        if errors > eligible:
            raise CustomSegmenterTournamentError(f"{provider}.{name} errors exceed eligibility")
        result[name] = row
    if set(result) != set(ERROR_FAMILIES):
        raise CustomSegmenterTournamentError(f"{provider} error coverage is incomplete")
    return result


def _validate_runtime(provider: str, runtime: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    for field in ("cold_latency_ms", "warm_latency_ms", "peak_vram_bytes"):
        _finite(runtime[field], f"{provider}.{field}")
    for field in ("oom_count", "crash_count", "repeat_count"):
        _count(runtime[field], f"{provider}.{field}")
    required = policy["shared_values"]["required_deterministic_repeats"]
    hashes = runtime["deterministic_output_sha256"]
    if runtime["repeat_count"] != required or len(hashes) != required or len(set(hashes)) != 1:
        raise CustomSegmenterTournamentError(f"{provider} deterministic repeat evidence failed")


def _validate_run(
    provider: str,
    evidence: Mapping[str, Any],
    shared: Mapping[str, Any],
    shared_sha256: str,
    policy: Mapping[str, Any],
) -> tuple[
    dict[str, Mapping[str, Any]],
    dict[str, Mapping[str, Any]],
    dict[str, Mapping[str, Any]],
]:
    manifest = evidence["run_manifest"]
    if not isinstance(manifest, Mapping) or set(manifest) != RUN_MANIFEST_KEYS:
        raise CustomSegmenterTournamentError(f"{provider} run manifest contract is incomplete")
    if evidence["run_manifest_sha256"] != canonical_sha256(manifest):
        raise CustomSegmenterTournamentError(f"{provider} run manifest hash mismatch")
    spec = policy["providers"][provider]
    exact = {
        "provider": provider,
        "status": "complete",
        "config_sha256": spec["config_sha256"],
        "shared_identity_sha256": shared_sha256,
        "dataset_manifest_sha256": shared["training_dataset_manifest_sha256"],
        "holdout_manifest_sha256": shared["evaluation_holdout_manifest_sha256"],
        "ontology_sha256": shared["ontology_sha256"],
        "qa_sha256": shared["qa_sha256"],
        "measurement_bundle_sha256": shared["measurement_bundle_sha256"],
        "hardware_fingerprint_sha256": shared["hardware_fingerprint_sha256"],
        "seed": policy["shared_values"]["seed"],
        "iterations_completed": policy["shared_values"]["iterations"],
    }
    for field, expected in exact.items():
        if manifest[field] != expected:
            raise CustomSegmenterTournamentError(f"{provider} run manifest {field} mismatch")
    if not isinstance(manifest["run_id"], str) or not manifest["run_id"]:
        raise CustomSegmenterTournamentError(f"{provider} run_id is empty")
    frozen_at = _timestamp(policy["frozen_at"], "policy.frozen_at")
    started_at = _timestamp(manifest["started_at"], f"{provider}.started_at")
    completed_at = _timestamp(manifest["completed_at"], f"{provider}.completed_at")
    if started_at <= frozen_at or completed_at < started_at:
        raise CustomSegmenterTournamentError(f"{provider} run timestamp order is invalid")
    artifacts = manifest["artifact_hashes"]
    if not isinstance(artifacts, Mapping) or tuple(sorted(artifacts)) != REQUIRED_ARTIFACT_KEYS:
        raise CustomSegmenterTournamentError(f"{provider} artifact set is incomplete")
    if any(not _is_sha256(value) for value in artifacts.values()):
        raise CustomSegmenterTournamentError(f"{provider} artifact hash is invalid")
    for key, expected in spec["frozen_initial_artifact_hashes"].items():
        if artifacts[key] != expected:
            raise CustomSegmenterTournamentError(f"{provider} frozen initial artifact mismatch")
    runtime_fingerprint = manifest["runtime_fingerprint_sha256"]
    if not _is_sha256(runtime_fingerprint):
        raise CustomSegmenterTournamentError(f"{provider} runtime fingerprint is invalid")

    labels = _validate_named_rows(provider, evidence["label_observations"], V2_CLASS_NAMES)
    contexts = _validate_named_rows(provider, evidence["context_observations"], CONTEXTS)
    errors = _validate_error_rows(provider, evidence["error_observations"])
    _validate_runtime(provider, evidence["runtime_metrics"], policy)
    return labels, contexts, errors


def _metric(row: Mapping[str, Any]) -> dict[str, Any]:
    boundary_denominator = 2 * row["boundary_tp"] + row["boundary_fp"] + row["boundary_fn"]
    return {
        "name": row["name"],
        "iou": _rate(row["intersection_pixels"], row["union_pixels"]),
        "boundary_f": _rate(2 * row["boundary_tp"], boundary_denominator),
        "small_part_recall": _rate(row["small_part_hit_count"], row["small_part_eligible_count"]),
        "correction_pixels_per_100k": 100000
        * _rate(row["correction_pixels"], row["evaluated_pixels"]),
    }


def _overall(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = [_metric(row) for row in rows]
    small_eligible = sum(row["small_part_eligible_count"] for row in rows)
    evaluated = sum(row["evaluated_pixels"] for row in rows)
    return {
        "macro_mean_iou": sum(row["iou"] for row in metrics) / len(metrics),
        "macro_boundary_f": sum(row["boundary_f"] for row in metrics) / len(metrics),
        "small_part_recall": _rate(
            sum(row["small_part_hit_count"] for row in rows), small_eligible
        ),
        "correction_pixels_per_100k": 100000
        * _rate(sum(row["correction_pixels"] for row in rows), evaluated),
    }


def build_report(
    runs_document: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    policy_document = dict(policy) if policy is not None else load_policy(root=root)
    validate_policy(policy_document, root=root)
    try:
        require_valid_document(runs_document, "custom_segmenter_tournament_runs")
    except ArtifactValidationError as exc:
        raise CustomSegmenterTournamentError(str(exc)) from exc
    payload = {key: value for key, value in runs_document.items() if key != "sha256"}
    if runs_document["sha256"] != canonical_sha256(payload):
        raise CustomSegmenterTournamentError("tournament runs hash mismatch")
    if runs_document["policy_sha256"] != policy_document["sha256"]:
        raise CustomSegmenterTournamentError("tournament runs policy hash mismatch")
    if runs_document["tournament_id"] != policy_document["policy_id"]:
        raise CustomSegmenterTournamentError("tournament identity mismatch")
    if _timestamp(runs_document["results_opened_at"], "results_opened_at") <= _timestamp(
        policy_document["frozen_at"], "policy.frozen_at"
    ):
        raise CustomSegmenterTournamentError("tournament results predate frozen policy")

    shared = runs_document["shared_identity"]
    eligible = policy_document["eligible_data"]
    if shared["certified_training_package_count"] < eligible["minimum_certified_training_packages"]:
        raise CustomSegmenterTournamentError("certified training package floor is not met")
    expected_shared = {
        "training_partition": eligible["training_partition"],
        "evaluation_truth_tier": eligible["evaluation_tier"],
        "evaluation_partition": eligible["evaluation_partition"],
        "train_holdout_overlap": eligible["train_holdout_overlap_allowed"],
        "ontology_sha256": policy_document["source_hashes"]["configs/ontology_v2.yaml"],
        "qa_sha256": policy_document["source_hashes"]["configs/qa.yaml"],
        "measurement_bundle_sha256": measurement_bundle_sha256(policy_document),
    }
    for field, expected in expected_shared.items():
        if shared[field] != expected:
            raise CustomSegmenterTournamentError(f"shared identity {field} mismatch")
    if shared["training_dataset_manifest_sha256"] == shared["evaluation_holdout_manifest_sha256"]:
        raise CustomSegmenterTournamentError("training and holdout manifests are identical")
    shared_sha256 = canonical_sha256(shared)

    run_ids: set[str] = set()
    provider_reports: list[dict[str, Any]] = []
    for provider in PROVIDERS:
        evidence = runs_document["runs"][provider]
        labels, contexts, errors = _validate_run(
            provider, evidence, shared, shared_sha256, policy_document
        )
        manifest = evidence["run_manifest"]
        if manifest["run_id"] in run_ids:
            raise CustomSegmenterTournamentError("provider run IDs are not unique")
        run_ids.add(manifest["run_id"])
        provider_reports.append(
            {
                "provider": provider,
                "run_id": manifest["run_id"],
                "config_sha256": manifest["config_sha256"],
                "run_manifest_sha256": evidence["run_manifest_sha256"],
                "artifact_hashes": manifest["artifact_hashes"],
                "runtime_fingerprint_sha256": manifest["runtime_fingerprint_sha256"],
                "label_metrics": [_metric(labels[name]) for name in V2_CLASS_NAMES],
                "context_metrics": [_metric(contexts[name]) for name in CONTEXTS],
                "overall_metrics": _overall([labels[name] for name in V2_CLASS_NAMES]),
                "error_metrics": [
                    {
                        "name": name,
                        "rate": _rate(errors[name]["error_count"], errors[name]["eligible_count"]),
                    }
                    for name in ERROR_FAMILIES
                ],
                "runtime_metrics": evidence["runtime_metrics"],
            }
        )

    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "tournament_id": runs_document["tournament_id"],
        "evaluated_at": runs_document["results_opened_at"],
        "policy_sha256": policy_document["sha256"],
        "source_runs_sha256": runs_document["sha256"],
        "shared_identity_sha256": shared_sha256,
        "providers": provider_reports,
        "comparability": {
            "provider_order": list(PROVIDERS),
            "certified_training_package_count": shared["certified_training_package_count"],
            "training_dataset_manifest_sha256": shared["training_dataset_manifest_sha256"],
            "evaluation_holdout_manifest_sha256": shared["evaluation_holdout_manifest_sha256"],
            "ontology_sha256": shared["ontology_sha256"],
            "qa_sha256": shared["qa_sha256"],
            "measurement_bundle_sha256": shared["measurement_bundle_sha256"],
            "hardware_fingerprint_sha256": shared["hardware_fingerprint_sha256"],
            "train_holdout_overlap": False,
            "complete_provider_count": len(PROVIDERS),
            "identical_frozen_training_contract": True,
        },
        "result": "comparable_complete_runs",
        "authority": (
            "measurement_evidence_only_no_winner_promotion_serving_mask_or_gold_authority"
        ),
    }
    report["sha256"] = canonical_sha256(report)
    require_valid_document(report, "custom_segmenter_tournament_report")
    return report


def verify_report(
    report: Mapping[str, Any],
    runs_document: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
    root: Path = ROOT,
) -> None:
    try:
        require_valid_document(report, "custom_segmenter_tournament_report")
    except ArtifactValidationError as exc:
        raise CustomSegmenterTournamentError(str(exc)) from exc
    expected = build_report(runs_document, policy=policy, root=root)
    if dict(report) != expected:
        raise CustomSegmenterTournamentError("tournament report recomputation mismatch")


__all__ = [
    "CONTEXTS",
    "DEFAULT_POLICY_PATH",
    "ERROR_FAMILIES",
    "POLICY_SHA256",
    "PROVIDERS",
    "CustomSegmenterTournamentError",
    "build_report",
    "canonical_sha256",
    "load_policy",
    "measurement_bundle_sha256",
    "validate_policy",
    "verify_report",
]
