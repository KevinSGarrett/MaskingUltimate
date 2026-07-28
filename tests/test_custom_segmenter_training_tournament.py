from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from maskfactory.training.bodypart.v2_contract import V2_CLASS_NAMES
from maskfactory.training.custom_segmenter_tournament import (
    CONTEXTS,
    ERROR_FAMILIES,
    POLICY_SHA256,
    PROVIDERS,
    CustomSegmenterTournamentError,
    build_report,
    canonical_sha256,
    load_policy,
    measurement_bundle_sha256,
    validate_policy,
    verify_report,
)

ROOT = Path(__file__).resolve().parents[1]


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _metric(name: str, offset: int = 0) -> dict[str, object]:
    truth = 100 + offset
    predicted = 90 + offset
    intersection = 80 + offset
    return {
        "name": name,
        "truth_pixels": truth,
        "predicted_pixels": predicted,
        "intersection_pixels": intersection,
        "union_pixels": truth + predicted - intersection,
        "boundary_tp": 80 + offset,
        "boundary_fp": 5,
        "boundary_fn": 5,
        "small_part_eligible_count": 10,
        "small_part_hit_count": 9,
        "correction_pixels": 10,
        "evaluated_pixels": 1000,
    }


def _seal(document: dict[str, object]) -> None:
    document["sha256"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "sha256"}
    )


def _seal_run(runs: dict[str, object], provider: str) -> None:
    evidence = runs["runs"][provider]
    evidence["run_manifest_sha256"] = canonical_sha256(evidence["run_manifest"])
    _seal(runs)


def _runs() -> dict[str, object]:
    policy = load_policy()
    shared = {
        "certified_training_package_count": 200,
        "training_dataset_manifest_sha256": _hash("training-manifest"),
        "training_dataset_dvc_md5": hashlib.md5(  # noqa: S324 - schema fixture only
            b"training-dvc"
        ).hexdigest(),
        "training_partition": "train",
        "evaluation_truth_tier": "human_anchor_gold",
        "evaluation_partition": "holdout",
        "evaluation_holdout_manifest_sha256": _hash("holdout-manifest"),
        "train_holdout_overlap": False,
        "ontology_sha256": policy["source_hashes"]["configs/ontology_v2.yaml"],
        "qa_sha256": policy["source_hashes"]["configs/qa.yaml"],
        "measurement_bundle_sha256": measurement_bundle_sha256(policy),
        "hardware_fingerprint_sha256": _hash("same-hardware"),
    }
    shared_sha = canonical_sha256(shared)
    runs: dict[str, object] = {
        "schema_version": "1.0.0",
        "tournament_id": "custom_segmenter_training_tournament_v1",
        "results_opened_at": "2026-07-15T10:31:00Z",
        "policy_sha256": POLICY_SHA256,
        "shared_identity": shared,
        "runs": {},
    }
    for index, provider in enumerate(PROVIDERS):
        artifacts = {
            key: _hash(f"{provider}-{key}")
            for key in (
                "evaluation_observations",
                "final_checkpoint",
                "initial_checkpoint",
                "run_config",
                "runtime_lock",
                "train_log",
            )
        }
        if provider == "eomt_dinov3_small_640":
            artifacts["initial_checkpoint"] = (
                "1fed3231445cce739e368c1828f49215459ca33ba56b6712d48e3058274c5d6f"
            )
        manifest = {
            "run_id": f"run-{provider}",
            "provider": provider,
            "status": "complete",
            "started_at": f"2026-07-15T10:{32 + index:02d}:00Z",
            "completed_at": f"2026-07-15T11:{32 + index:02d}:00Z",
            "config_sha256": policy["providers"][provider]["config_sha256"],
            "shared_identity_sha256": shared_sha,
            "dataset_manifest_sha256": shared["training_dataset_manifest_sha256"],
            "holdout_manifest_sha256": shared["evaluation_holdout_manifest_sha256"],
            "ontology_sha256": shared["ontology_sha256"],
            "qa_sha256": shared["qa_sha256"],
            "measurement_bundle_sha256": shared["measurement_bundle_sha256"],
            "hardware_fingerprint_sha256": shared["hardware_fingerprint_sha256"],
            "seed": 1337,
            "iterations_completed": 40000,
            "artifact_hashes": artifacts,
            "runtime_fingerprint_sha256": _hash("same-runtime"),
        }
        evidence = {
            "run_manifest": manifest,
            "run_manifest_sha256": canonical_sha256(manifest),
            "label_observations": [_metric(name, index) for name in V2_CLASS_NAMES],
            "context_observations": [_metric(name, index) for name in CONTEXTS],
            "error_observations": [
                {"name": name, "eligible_count": 100, "error_count": index}
                for name in ERROR_FAMILIES
            ],
            "runtime_metrics": {
                "cold_latency_ms": 100.0 + index,
                "warm_latency_ms": 50.0 + index,
                "peak_vram_bytes": 4_000_000_000 + index,
                "oom_count": 0,
                "crash_count": 0,
                "repeat_count": 2,
                "deterministic_output_sha256": [
                    _hash(f"{provider}-output"),
                    _hash(f"{provider}-output"),
                ],
            },
        }
        runs["runs"][provider] = evidence
    _seal(runs)
    return runs


def test_frozen_policy_validates_and_all_training_surfaces_match() -> None:
    policy = load_policy()
    validate_policy(policy)
    assert policy["sha256"] == POLICY_SHA256
    assert policy["shared_values"]["required_deterministic_repeats"] == 2
    assert tuple(policy["providers"]) == PROVIDERS


def test_report_is_recomputed_comparability_evidence_without_authority() -> None:
    runs = _runs()
    report = build_report(runs)
    verify_report(report, runs)
    assert report["result"] == "comparable_complete_runs"
    assert report["comparability"]["complete_provider_count"] == 3
    assert [row["provider"] for row in report["providers"]] == list(PROVIDERS)
    assert report["authority"] == (
        "measurement_evidence_only_no_winner_promotion_serving_mask_or_gold_authority"
    )
    serialized = json.dumps(report)
    assert '"winner"' not in serialized
    assert '"promotion"' not in serialized


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("certified_training_package_count", 199),
        ("training_partition", "validation"),
        ("evaluation_truth_tier", "autonomous_gold"),
        ("evaluation_partition", "train"),
        ("train_holdout_overlap", True),
        ("measurement_bundle_sha256", "0" * 64),
        ("ontology_sha256", "0" * 64),
        ("qa_sha256", "0" * 64),
    ],
)
def test_shared_identity_drift_fails_closed(field: str, value: object) -> None:
    runs = _runs()
    runs["shared_identity"][field] = value
    _seal(runs)
    with pytest.raises(CustomSegmenterTournamentError):
        build_report(runs)


def test_identical_training_and_holdout_manifests_are_rejected() -> None:
    runs = _runs()
    runs["shared_identity"]["evaluation_holdout_manifest_sha256"] = runs["shared_identity"][
        "training_dataset_manifest_sha256"
    ]
    _seal(runs)
    with pytest.raises(CustomSegmenterTournamentError, match="identical"):
        build_report(runs)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "incomplete"),
        ("iterations_completed", 39999),
        ("seed", 42),
        ("config_sha256", "0" * 64),
        ("started_at", "2026-07-15T10:29:00Z"),
        ("completed_at", "2026-07-15T10:00:00Z"),
        ("shared_identity_sha256", "0" * 64),
    ],
)
def test_run_manifest_drift_fails_closed(field: str, value: object) -> None:
    runs = _runs()
    manifest = runs["runs"]["segformer_b3"]["run_manifest"]
    manifest[field] = value
    _seal_run(runs, "segformer_b3")
    with pytest.raises(CustomSegmenterTournamentError):
        build_report(runs)


def test_missing_provider_fails_schema() -> None:
    runs = _runs()
    del runs["runs"]["mask2former_swin_b"]
    _seal(runs)
    with pytest.raises(CustomSegmenterTournamentError):
        build_report(runs)


def test_duplicate_run_id_fails_closed() -> None:
    runs = _runs()
    runs["runs"]["mask2former_swin_b"]["run_manifest"]["run_id"] = runs["runs"]["segformer_b3"][
        "run_manifest"
    ]["run_id"]
    _seal_run(runs, "mask2former_swin_b")
    with pytest.raises(CustomSegmenterTournamentError, match="run IDs"):
        build_report(runs)


def test_missing_artifact_and_eomt_checkpoint_substitution_fail_closed() -> None:
    runs = _runs()
    del runs["runs"]["segformer_b3"]["run_manifest"]["artifact_hashes"]["train_log"]
    _seal_run(runs, "segformer_b3")
    with pytest.raises(CustomSegmenterTournamentError, match="artifact"):
        build_report(runs)

    runs = _runs()
    runs["runs"]["eomt_dinov3_small_640"]["run_manifest"]["artifact_hashes"][
        "initial_checkpoint"
    ] = _hash("substitute")
    _seal_run(runs, "eomt_dinov3_small_640")
    with pytest.raises(CustomSegmenterTournamentError, match="frozen initial"):
        build_report(runs)


def test_non_hex_artifact_and_runtime_fingerprints_fail_closed() -> None:
    runs = _runs()
    runs["runs"]["segformer_b3"]["run_manifest"]["artifact_hashes"]["train_log"] = "z" * 64
    _seal_run(runs, "segformer_b3")
    with pytest.raises(CustomSegmenterTournamentError, match="artifact hash"):
        build_report(runs)

    runs = _runs()
    runs["runs"]["segformer_b3"]["run_manifest"]["runtime_fingerprint_sha256"] = "z" * 64
    _seal_run(runs, "segformer_b3")
    with pytest.raises(CustomSegmenterTournamentError, match="runtime fingerprint"):
        build_report(runs)


@pytest.mark.parametrize("collection", ["label_observations", "context_observations"])
def test_duplicate_observation_name_fails_closed(collection: str) -> None:
    runs = _runs()
    rows = runs["runs"]["segformer_b3"][collection]
    rows[-1]["name"] = rows[0]["name"]
    _seal(runs)
    with pytest.raises(CustomSegmenterTournamentError, match="vocabulary"):
        build_report(runs)


def test_duplicate_error_name_fails_closed() -> None:
    runs = _runs()
    rows = runs["runs"]["segformer_b3"]["error_observations"]
    rows[-1]["name"] = rows[0]["name"]
    _seal(runs)
    with pytest.raises(CustomSegmenterTournamentError, match="error vocabulary"):
        build_report(runs)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("union_pixels", 999),
        ("intersection_pixels", 101),
        ("small_part_hit_count", 11),
        ("correction_pixels", 1001),
    ],
)
def test_metric_denominator_drift_fails_closed(field: str, value: int) -> None:
    runs = _runs()
    runs["runs"]["segformer_b3"]["label_observations"][0][field] = value
    _seal(runs)
    with pytest.raises(CustomSegmenterTournamentError):
        build_report(runs)


def test_error_count_cannot_exceed_explicit_denominator() -> None:
    runs = _runs()
    row = runs["runs"]["segformer_b3"]["error_observations"][0]
    row["error_count"] = row["eligible_count"] + 1
    _seal(runs)
    with pytest.raises(CustomSegmenterTournamentError, match="eligibility"):
        build_report(runs)


@pytest.mark.parametrize(
    ("repeat_count", "hashes"),
    [
        (1, [_hash("same")]),
        (2, [_hash("first"), _hash("second")]),
        (3, [_hash("same"), _hash("same"), _hash("same")]),
    ],
)
def test_deterministic_repeat_evidence_is_exact(repeat_count: int, hashes: list[str]) -> None:
    runs = _runs()
    runtime = runs["runs"]["segformer_b3"]["runtime_metrics"]
    runtime["repeat_count"] = repeat_count
    runtime["deterministic_output_sha256"] = hashes
    _seal(runs)
    with pytest.raises(CustomSegmenterTournamentError, match="repeat evidence"):
        build_report(runs)


def test_run_and_manifest_hash_tampering_fail_closed() -> None:
    runs = _runs()
    runs["sha256"] = "0" * 64
    with pytest.raises(CustomSegmenterTournamentError, match="runs hash"):
        build_report(runs)

    runs = _runs()
    runs["runs"]["segformer_b3"]["run_manifest_sha256"] = "0" * 64
    _seal(runs)
    with pytest.raises(CustomSegmenterTournamentError, match="manifest hash"):
        build_report(runs)


def test_report_tampering_fails_recomputation() -> None:
    runs = _runs()
    report = build_report(runs)
    report["providers"][0]["overall_metrics"]["macro_mean_iou"] = 1.0
    report["sha256"] = canonical_sha256(
        {key: value for key, value in report.items() if key != "sha256"}
    )
    with pytest.raises(CustomSegmenterTournamentError, match="recomputation"):
        verify_report(report, runs)


def test_cli_builds_and_verifies_report(tmp_path: Path) -> None:
    runs_path = tmp_path / "runs.json"
    report_path = tmp_path / "report.json"
    runs_path.write_text(json.dumps(_runs()), encoding="utf-8")
    command = [
        sys.executable,
        str(ROOT / "tools/evaluate_custom_segmenter_tournament.py"),
        str(runs_path),
        "--output",
        str(report_path),
    ]
    built = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    verified = subprocess.run(
        [*command, "--verify"], cwd=ROOT, check=False, capture_output=True, text=True
    )
    assert verified.returncode == 0, verified.stderr


def test_policy_hash_and_shared_value_tampering_fail_closed() -> None:
    policy = copy.deepcopy(load_policy())
    policy["shared_values"]["iterations"] = 1
    _seal(policy)
    with pytest.raises(CustomSegmenterTournamentError, match="shared training values"):
        validate_policy(policy, expected_sha256=None)

    policy = copy.deepcopy(load_policy())
    policy["sha256"] = "0" * 64
    with pytest.raises(CustomSegmenterTournamentError, match="policy hash"):
        validate_policy(policy, expected_sha256=None)
