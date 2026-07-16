"""Schema validation and package-level invariants for MaskFactory artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_DIR = Path(__file__).with_name("schemas")
SCHEMA_NAMES = frozenset(
    {
        "manifest",
        "manifest_v2",
        "qa_report",
        "model_registry",
        "failure_queue",
        "geometry_variant_benchmark_cases",
        "geometry_variant_benchmark_policy",
        "geometry_variant_benchmark_report",
        "coverage_matrix",
        "coverage_matrix_v2",
        "leaderboard",
        "mediapipe_vote_ablation_cases",
        "mediapipe_vote_ablation_policy",
        "mediapipe_vote_ablation_report",
        "pose_variant_benchmark_cases",
        "pose_variant_benchmark_policy",
        "pose_variant_benchmark_report",
        "provider_benchmark_matrix_manifest",
        "provider_benchmark_matrix_observations",
        "provider_benchmark_matrix_policy",
        "provider_benchmark_matrix_report",
        "matrix_promotion_certificate",
        "interactive_provider_promotion_certificate",
        "interactive_provider_transaction",
        "interactive_provider_rollback",
        "multi_person_family_availability_policy",
        "multi_person_lifecycle_route",
        "multi_person_tournament_evidence",
        "multi_person_tournament_execution",
        "sam31_shadow_candidate_package",
        "sam31_shadow_orchestration",
        "sam31_repair_orchestration",
        "qwen_challenger_benchmark_cases",
        "qwen_challenger_benchmark_policy",
        "qwen_challenger_benchmark_report",
        "retraining_operations_input",
        "retraining_operations_policy",
        "retraining_operations_report",
        "silhouette_variant_benchmark_cases",
        "silhouette_variant_benchmark_policy",
        "silhouette_variant_benchmark_report",
        "crop_transform",
        "autonomy_lifecycle",
        "autonomy_multi_person_risk_buckets",
        "autonomy_metrics",
        "autonomy_metrics_inputs",
        "autonomy_risk_buckets",
        "autonomy_stability",
        "completion_bundle_input",
        "completion_bundle_policy",
        "completion_bundle_report",
        "currency_review",
        "custom_segmenter_tournament_policy",
        "custom_segmenter_tournament_report",
        "custom_segmenter_tournament_runs",
        "custom_segmenter_benchmark_margins",
        "custom_segmenter_champion_rollback",
        "custom_segmenter_champion_transaction",
        "daz_operating_profile",
        "daz_acquisition_capacity",
        "daz_asset_identity_snapshot",
        "daz_asset_compatibility_graph",
        "daz_asset_pool_report",
        "daz_asset_smoke_plan",
        "daz_asset_smoke_result",
        "daz_asset_smoke_certificate",
        "daz_asset_quarantine",
        "daz_resolved_scene_recipe",
        "daz_paths",
        "daz_runtime",
        "daz_cms_snapshot",
        "daz_dim_manifest_snapshot",
        "daz_filesystem_inventory_snapshot",
        "daz_ontology_snapshot",
        "daz_scene_recipe",
        "daz_training_policy",
        "daz_worker",
        "daz_worker_result",
        "serving_provenance",
        "serving_route",
        "serving_workflow_performance_policy",
        "serving_workflow_performance_report",
        "serving_workflow_execution_input",
        "serving_workflow_preflight_report",
        "specialist_benchmark_margins",
        "specialist_champion_rollback",
        "specialist_champion_transaction",
        "specialist_evidence_package",
    }
)
VISIBLE_STATES = frozenset({"visible", "partially_visible"})


def _escape_pointer(token: object) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def _pointer(path: Iterable[object]) -> str:
    tokens = [_escape_pointer(token) for token in path]
    return "" if not tokens else "/" + "/".join(tokens)


@dataclass(frozen=True, order=True)
class ValidationIssue:
    """One stable validation finding with an RFC 6901 JSON pointer."""

    pointer: str
    validator: str
    message: str


class ArtifactValidationError(ValueError):
    """Raised when schema or package-invariant validation fails."""

    def __init__(self, issues: Iterable[ValidationIssue]) -> None:
        self.issues = tuple(sorted(issues))
        detail = "; ".join(
            f"{issue.pointer or '/'} [{issue.validator}] {issue.message}" for issue in self.issues
        )
        super().__init__(detail)


@lru_cache(maxsize=None)
def schema_validator(schema_name: str) -> Draft202012Validator:
    """Load and compile one named, bundled Draft 2020-12 schema."""
    if schema_name not in SCHEMA_NAMES:
        allowed = ", ".join(sorted(SCHEMA_NAMES))
        raise KeyError(f"unknown schema {schema_name!r}; expected one of: {allowed}")
    path = SCHEMA_DIR / f"{schema_name}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_document(document: Any, schema_name: str) -> tuple[ValidationIssue, ...]:
    """Return deterministic structural findings for a JSON-compatible document."""
    errors = schema_validator(schema_name).iter_errors(document)
    issues = (
        ValidationIssue(
            pointer=_pointer(error.absolute_path),
            validator=str(error.validator),
            message=error.message,
        )
        for error in errors
    )
    return tuple(sorted(issues))


def _manifest_invariant_issues(
    manifest: Mapping[str, Any], enabled_labels: Iterable[str]
) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    parts = manifest.get("parts")
    if not isinstance(parts, Mapping):
        return ()

    enabled = set(enabled_labels)
    missing = sorted(enabled.difference(parts))
    if missing:
        issues.append(
            ValidationIssue(
                pointer="/parts",
                validator="enabled_labels_complete",
                message="missing enabled ontology labels: " + ", ".join(missing),
            )
        )

    gold_present = False
    for label, raw_entry in sorted(parts.items()):
        if not isinstance(raw_entry, Mapping):
            continue
        entry = raw_entry
        pointer = "/parts/" + _escape_pointer(label)
        if (
            entry.get("mask_type") == "atomic_exclusive"
            and entry.get("visibility") not in VISIBLE_STATES
            and entry.get("mask_file") is not None
        ):
            issues.append(
                ValidationIssue(
                    pointer=pointer + "/mask_file",
                    validator="nonvisible_atomic_has_no_mask",
                    message="atomic mask_file must be null unless visibility is visible or partially_visible",
                )
            )
        gold_present = gold_present or entry.get("status") == "human_approved_gold"

    if gold_present:
        qa = manifest.get("qa")
        qa_overall = qa.get("qa_overall") if isinstance(qa, Mapping) else None
        if qa_overall != "pass":
            issues.append(
                ValidationIssue(
                    pointer="/qa/qa_overall",
                    validator="gold_requires_qa_pass",
                    message="human_approved_gold requires qa_overall=pass",
                )
            )
        review = manifest.get("review")
        review_complete = isinstance(review, Mapping) and all(
            review.get(field) is not None
            for field in ("reviewer", "approved_at", "review_time_sec")
        )
        if not review_complete:
            issues.append(
                ValidationIssue(
                    pointer="/review",
                    validator="gold_requires_review",
                    message="human_approved_gold requires reviewer, approved_at, and review_time_sec",
                )
            )
    return tuple(sorted(issues))


def validate_manifest(
    manifest: Mapping[str, Any], *, enabled_labels: Iterable[str]
) -> tuple[ValidationIssue, ...]:
    """Validate the manifest schema and non-overridable packager invariants."""
    structural = validate_document(manifest, "manifest")
    invariants = _manifest_invariant_issues(manifest, enabled_labels)
    return tuple(sorted((*structural, *invariants)))


def require_valid_document(document: Any, schema_name: str) -> None:
    """Raise with pointer-addressed findings unless a document is structurally valid."""
    issues = validate_document(document, schema_name)
    if issues:
        raise ArtifactValidationError(issues)


def require_valid_manifest(manifest: Mapping[str, Any], *, enabled_labels: Iterable[str]) -> None:
    """Raise unless a manifest passes schema and packager invariants."""
    issues = validate_manifest(manifest, enabled_labels=enabled_labels)
    if issues:
        raise ArtifactValidationError(issues)
