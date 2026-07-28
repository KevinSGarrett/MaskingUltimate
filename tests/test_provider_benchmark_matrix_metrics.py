from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from maskfactory.providers.provider_matrix import (
    POLICY_SHA256,
    PROVIDER_ARTIFACT_KEYS,
    canonical_sha256,
    expected_enrichment_cells,
    expected_screening_cells,
    load_policy,
    measurement_bundle_sha256,
    seal_manifest,
)
from maskfactory.providers.provider_matrix_metrics import (
    ARTIFACT_KEYS,
    ProviderMatrixMetricsError,
    build_report,
    verify_report,
)
from maskfactory.training.bodypart.v2_contract import V2_CLASS_NAMES

ROOT = Path(__file__).resolve().parents[1]


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _manifest() -> dict[str, object]:
    policy = load_policy()
    shared = {
        "truth_tier": "human_anchor_gold",
        "truth_partition": "holdout",
        "image_disjoint": True,
        "evaluation_set_sha256": _hash("evaluation"),
        "prompt_set_sha256": _hash("prompts"),
        "part_set_sha256": _hash("parts"),
        "hardware_profile_sha256": _hash("hardware"),
        "qa_sha256": policy["source_hashes"]["configs/qa.yaml"],
        "pipeline_sha256": policy["source_hashes"]["configs/pipeline.yaml"],
        "ontology_sha256": policy["source_hashes"]["configs/ontology_v2.yaml"],
        "measurement_bundle_sha256": measurement_bundle_sha256(policy),
        "provider_artifact_sha256": {
            key: _hash(f"artifact-{key}") for key in PROVIDER_ARTIFACT_KEYS
        },
    }
    shared_sha = canonical_sha256(shared)
    selected = ("sam2_1_only",)
    return seal_manifest(
        {
            "schema_version": "1.0.0",
            "matrix_id": "provider_benchmark_matrix_v1",
            "opened_at": "2026-07-15T11:06:00Z",
            "policy_sha256": POLICY_SHA256,
            "authority": "immutable_matrix_identity_only_no_metric_result_or_authority",
            "shared_identity": shared,
            "screening_cells": expected_screening_cells(shared_sha),
            "finalist_selection": {
                "screening_result_sha256": _hash("screening-result"),
                "selected_routes": list(selected),
            },
            "enrichment_cells": expected_enrichment_cells(selected, shared_sha),
        }
    )


def _counts() -> dict[str, object]:
    return {
        "small_part_eligible_count": 100,
        "small_part_hit_count": 90,
        "person_instance_eligible_count": 100,
        "person_instance_hit_count": 95,
        "part_instance_eligible_count": 200,
        "part_instance_hit_count": 180,
        "predicted_person_pixels": 1000,
        "cross_person_bleed_pixels": 1,
        "side_eligible_count": 100,
        "left_right_error_count": 1,
        "front_back_eligible_count": 100,
        "front_back_error_count": 1,
        "anatomy_clothing_eligible_count": 100,
        "anatomy_clothing_confusion_count": 1,
        "expected_part_count": 200,
        "missing_part_count": 2,
        "predicted_part_count": 200,
        "hallucinated_part_count": 1,
        "hard_qa_eligible_count": 100,
        "hard_qa_failure_count": 1,
        "predicted_pixels": 10000,
        "correction_pixels": 100,
        "audit_case_count": 10,
        "audit_seconds": 20.0,
        "execution_attempt_count": 2,
        "oom_count": 0,
        "crash_count": 0,
        "peak_vram_bytes": 4_000_000_000,
        "cold_latency_ms": 100.0,
        "warm_latency_ms": 50.0,
        "deterministic_output_sha256": [_hash("same"), _hash("same")],
    }


def _cell(cell: dict[str, object]) -> dict[str, object]:
    labels = [
        {
            "name": name,
            "truth_pixels": 100,
            "predicted_pixels": 90,
            "intersection_pixels": 80,
            "union_pixels": 110,
            "boundary_tp": 80,
            "boundary_fp": 5,
            "boundary_fn": 5,
        }
        for name in V2_CLASS_NAMES
    ]
    artifacts = {key: _hash(f"{cell['cell_id']}-{key}") for key in ARTIFACT_KEYS}
    evidence = {
        "cell_id": cell["cell_id"],
        "cell_identity_sha256": canonical_sha256(cell),
        "label_observations": labels,
        "aggregate_counts": _counts(),
        "artifact_hashes": artifacts,
    }
    evidence["observations_sha256"] = canonical_sha256(
        {
            "label_observations": labels,
            "aggregate_counts": evidence["aggregate_counts"],
            "artifact_hashes": artifacts,
        }
    )
    return evidence


def _observations(manifest: dict[str, object]) -> dict[str, object]:
    cells = [*manifest["screening_cells"], *manifest["enrichment_cells"]]
    document = {
        "schema_version": "1.0.0",
        "matrix_id": "provider_benchmark_matrix_v1",
        "results_opened_at": "2026-07-15T11:07:00Z",
        "policy_sha256": POLICY_SHA256,
        "manifest_sha256": manifest["sha256"],
        "cells": [_cell(cell) for cell in cells],
    }
    _rehash(document)
    return document


def _rehash(document: dict[str, object]) -> None:
    document["sha256"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "sha256"}
    )


def _reseal_cell(observations: dict[str, object], index: int = 0) -> None:
    cell = observations["cells"][index]
    cell["observations_sha256"] = canonical_sha256(
        {
            "label_observations": cell["label_observations"],
            "aggregate_counts": cell["aggregate_counts"],
            "artifact_hashes": cell["artifact_hashes"],
        }
    )
    _rehash(observations)


@pytest.fixture()
def matrix_pair() -> tuple[dict[str, object], dict[str, object]]:
    manifest = _manifest()
    return manifest, _observations(manifest)


def test_complete_report_recomputes_all_nineteen_metrics_for_every_cell(
    matrix_pair: tuple[dict[str, object], dict[str, object]],
) -> None:
    manifest, observations = matrix_pair
    report = build_report(observations, manifest)
    verify_report(report, observations, manifest)
    assert report["cell_count"] == 66
    assert len(report["cells"]) == 66
    assert all(len(cell["metrics"]) == 19 for cell in report["cells"])
    assert report["cells"][0]["metrics"]["correction_pixels_per_100k"] == 1000.0
    assert report["cells"][0]["metrics"]["deterministic_repeatability"] == 1.0
    assert '"winner":' not in json.dumps(report)


def test_nondeterminism_is_measured_not_hidden_or_rejected(
    matrix_pair: tuple[dict[str, object], dict[str, object]],
) -> None:
    manifest, observations = matrix_pair
    observations["cells"][0]["aggregate_counts"]["deterministic_output_sha256"][1] = _hash(
        "different"
    )
    _reseal_cell(observations)
    report = build_report(observations, manifest)
    assert report["cells"][0]["metrics"]["deterministic_repeatability"] == 0.0


def test_missing_or_reordered_cell_fails_closed(
    matrix_pair: tuple[dict[str, object], dict[str, object]],
) -> None:
    manifest, observations = matrix_pair
    observations["cells"].pop()
    _rehash(observations)
    with pytest.raises(ProviderMatrixMetricsError):
        build_report(observations, manifest)

    observations = _observations(manifest)
    observations["cells"].reverse()
    _rehash(observations)
    with pytest.raises(ProviderMatrixMetricsError, match="ordering"):
        build_report(observations, manifest)


def test_cell_and_observation_hash_tampering_fail_closed(
    matrix_pair: tuple[dict[str, object], dict[str, object]],
) -> None:
    manifest, observations = matrix_pair
    observations["cells"][0]["cell_identity_sha256"] = "0" * 64
    _rehash(observations)
    with pytest.raises(ProviderMatrixMetricsError, match="cell identity"):
        build_report(observations, manifest)

    observations = _observations(manifest)
    observations["cells"][0]["observations_sha256"] = "0" * 64
    _rehash(observations)
    with pytest.raises(ProviderMatrixMetricsError, match="observations hash"):
        build_report(observations, manifest)


def test_label_coverage_and_union_invariants_fail_closed(
    matrix_pair: tuple[dict[str, object], dict[str, object]],
) -> None:
    manifest, observations = matrix_pair
    labels = observations["cells"][0]["label_observations"]
    labels[-1]["name"] = labels[0]["name"]
    _reseal_cell(observations)
    with pytest.raises(ProviderMatrixMetricsError, match="vocabulary"):
        build_report(observations, manifest)

    observations = _observations(manifest)
    observations["cells"][0]["label_observations"][0]["union_pixels"] = 999
    _reseal_cell(observations)
    with pytest.raises(ProviderMatrixMetricsError, match="union"):
        build_report(observations, manifest)


@pytest.mark.parametrize(
    ("denominator", "numerator"),
    [
        ("small_part_eligible_count", "small_part_hit_count"),
        ("predicted_person_pixels", "cross_person_bleed_pixels"),
        ("side_eligible_count", "left_right_error_count"),
        ("front_back_eligible_count", "front_back_error_count"),
        ("hard_qa_eligible_count", "hard_qa_failure_count"),
        ("predicted_pixels", "correction_pixels"),
    ],
)
def test_explicit_denominator_invariants_fail_closed(
    matrix_pair: tuple[dict[str, object], dict[str, object]],
    denominator: str,
    numerator: str,
) -> None:
    manifest, observations = matrix_pair
    counts = observations["cells"][0]["aggregate_counts"]
    counts[numerator] = counts[denominator] + 1
    _reseal_cell(observations)
    with pytest.raises(ProviderMatrixMetricsError, match="exceeds explicit denominator"):
        build_report(observations, manifest)


def test_missing_aggregate_field_and_runtime_failure_nesting_fail_closed(
    matrix_pair: tuple[dict[str, object], dict[str, object]],
) -> None:
    manifest, observations = matrix_pair
    del observations["cells"][0]["aggregate_counts"]["audit_case_count"]
    _reseal_cell(observations)
    with pytest.raises(ProviderMatrixMetricsError, match="aggregate count contract"):
        build_report(observations, manifest)

    observations = _observations(manifest)
    counts = observations["cells"][0]["aggregate_counts"]
    counts["oom_count"] = 2
    counts["crash_count"] = 1
    _reseal_cell(observations)
    with pytest.raises(ProviderMatrixMetricsError, match="failures exceed"):
        build_report(observations, manifest)


@pytest.mark.parametrize(
    ("field", "value"),
    [("audit_seconds", math.inf), ("cold_latency_ms", math.nan), ("warm_latency_ms", -1.0)],
)
def test_nonfinite_or_negative_measurements_fail_closed(
    matrix_pair: tuple[dict[str, object], dict[str, object]],
    field: str,
    value: float,
) -> None:
    manifest, observations = matrix_pair
    observations["cells"][0]["aggregate_counts"][field] = value
    _reseal_cell(observations)
    with pytest.raises(ProviderMatrixMetricsError):
        build_report(observations, manifest)


def test_exact_repeat_and_artifact_evidence_is_required(
    matrix_pair: tuple[dict[str, object], dict[str, object]],
) -> None:
    manifest, observations = matrix_pair
    observations["cells"][0]["aggregate_counts"]["deterministic_output_sha256"].pop()
    _reseal_cell(observations)
    with pytest.raises(ProviderMatrixMetricsError, match="two repeat"):
        build_report(observations, manifest)

    observations = _observations(manifest)
    del observations["cells"][0]["artifact_hashes"]["runtime_log"]
    _reseal_cell(observations)
    with pytest.raises(ProviderMatrixMetricsError):
        build_report(observations, manifest)


def test_observation_manifest_policy_and_time_binding_fail_closed(
    matrix_pair: tuple[dict[str, object], dict[str, object]],
) -> None:
    manifest, observations = matrix_pair
    observations["manifest_sha256"] = "0" * 64
    _rehash(observations)
    with pytest.raises(ProviderMatrixMetricsError, match="manifest hash"):
        build_report(observations, manifest)

    observations = _observations(manifest)
    observations["results_opened_at"] = manifest["opened_at"]
    _rehash(observations)
    with pytest.raises(ProviderMatrixMetricsError, match="predate"):
        build_report(observations, manifest)


def test_observations_and_report_tampering_fail_closed(
    matrix_pair: tuple[dict[str, object], dict[str, object]],
) -> None:
    manifest, observations = matrix_pair
    observations["sha256"] = "0" * 64
    with pytest.raises(ProviderMatrixMetricsError, match="observations hash"):
        build_report(observations, manifest)

    observations = _observations(manifest)
    report = build_report(observations, manifest)
    report["cells"][0]["metrics"]["small_part_recall"] = 1.0
    report["sha256"] = canonical_sha256(
        {key: value for key, value in report.items() if key != "sha256"}
    )
    with pytest.raises(ProviderMatrixMetricsError, match="recomputation"):
        verify_report(report, observations, manifest)


def test_cli_builds_and_verifies_complete_report(
    tmp_path: Path,
    matrix_pair: tuple[dict[str, object], dict[str, object]],
) -> None:
    manifest, observations = matrix_pair
    manifest_path = tmp_path / "manifest.json"
    observations_path = tmp_path / "observations.json"
    report_path = tmp_path / "report.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    observations_path.write_text(json.dumps(observations), encoding="utf-8")
    command = [
        sys.executable,
        str(ROOT / "tools/evaluate_provider_benchmark_matrix.py"),
        str(observations_path),
        "--manifest",
        str(manifest_path),
        "--output",
        str(report_path),
    ]
    built = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert built.returncode == 0, built.stderr
    verified = subprocess.run(
        [*command, "--verify"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert verified.returncode == 0, verified.stderr
