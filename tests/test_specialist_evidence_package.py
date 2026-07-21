import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from maskfactory.providers.benchmark_policy import (
    SPECIALIST_ROLES,
    load_specialist_margin_manifest,
)
from maskfactory.providers.specialist_evidence import (
    ROLE_EVIDENCE_KINDS,
    SpecialistEvidenceError,
    seal_package,
    validate_package,
)
from maskfactory.training.leaderboard import append_leaderboard_row
from maskfactory.validation import validate_document

ROOT = Path(__file__).resolve().parents[1]


def _sha256(value) -> str:
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _result(role: str, margins: dict[str, float], manifest_sha256: str) -> dict:
    document = {
        "schema_version": "1.0.0",
        "benchmark_id": f"specialist-{role}-fixture-v1",
        "role": role,
        "margin_manifest_sha256": manifest_sha256,
        "results_opened_at": "2026-07-15T02:00:00Z",
        "primary_win_or_labor_reduction": True,
        "rows": [
            {
                "bucket": bucket,
                "observed_delta": 0.0,
                "noninferiority_margin": margin,
                "passed": True,
            }
            for bucket, margin in sorted(margins.items())
        ],
    }
    document["sha256"] = _sha256(document)
    return document


def _leaderboard_row(run_id: str, dataset_ref: str) -> dict:
    metric = {"iou": 0.8, "bf": 0.8}
    context = {
        "mean_iou": 0.8,
        "mean_boundary_f": 0.8,
        "per_class": {"left_thumb": metric},
        "sample_count": 10,
    }
    return {
        "run_id": run_id,
        "model_family": run_id,
        "ckpt_sha": _sha256(run_id.encode()),
        "dataset_ref": dataset_ref,
        "split": "test_holdout",
        "mean_iou": 0.8,
        "mean_boundary_f": 0.8,
        "per_class": {"left_thumb": metric},
        "group_scores": {"specialist": metric},
        "instance_context_scores": {"solo": context},
        "sample_count": 10,
        "latency_ms_1024": 10.0,
        "vram_gb": 1.0,
        "seeds": [1],
        "notes": "synthetic contract fixture only",
    }


def _artifact(root: Path, relative: str, payload: str) -> dict:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return {"path": relative.replace("\\", "/"), "sha256": _sha256(path.read_bytes())}


def _fixture(tmp_path: Path) -> tuple[dict, dict[str, dict], dict]:
    manifest, expanded = load_specialist_margin_manifest()
    evaluation_sha = "e" * 64
    fingerprint_sha = "f" * 64
    dataset_ref = f"sha256:{evaluation_sha}"
    leaderboard_path = tmp_path / "runs/leaderboard.jsonl"
    results = {}
    lanes = {}
    for role in sorted(SPECIALIST_ROLES):
        baseline_id = f"{role}-baseline"
        challenger_id = f"{role}-challenger"
        append_leaderboard_row(leaderboard_path, _leaderboard_row(baseline_id, dataset_ref))
        append_leaderboard_row(leaderboard_path, _leaderboard_row(challenger_id, dataset_ref))
        result = _result(role, expanded[role], manifest["sha256"])
        results[role] = result
        role_evidence = _artifact(
            tmp_path,
            f"qa/evidence/{role}/role_evidence.json",
            json.dumps({"role": role, "fixture": True}),
        )
        role_evidence["kind"] = ROLE_EVIDENCE_KINDS[role]
        artifacts = []
        for kind in ("correction_diff", "disagreement_heatmap", "overlay_montage"):
            artifact = _artifact(
                tmp_path,
                f"qa/evidence/{role}/{kind}.bin",
                f"{role}:{kind}",
            )
            artifact["kind"] = kind
            artifacts.append(artifact)
        lanes[role] = {
            "role": role,
            "provider_keys": [f"{role}_baseline", f"{role}_challenger"],
            "sample_count": 10,
            "distinct_image_count": 10,
            "evaluation_set_sha256": evaluation_sha,
            "pipeline_fingerprint_sha256": fingerprint_sha,
            "benchmark_result_sha256": result["sha256"],
            "role_evidence": role_evidence,
            "artifacts": artifacts,
            "disagreement": {
                "compared_pixels": 1000,
                "disagree_pixels": 100,
                "fraction": 0.1,
            },
            "correction_pixels": {
                "predicted_pixels": 1000,
                "changed_pixels": 25,
                "changed_pixels_per_100k": 2500.0,
            },
            "review_time": {
                "case_count": 10,
                "baseline_seconds": 100.0,
                "challenger_seconds": 80.0,
                "delta_seconds_per_case": -2.0,
            },
            "leaderboard": {
                "baseline_run_id": baseline_id,
                "challenger_run_id": challenger_id,
            },
        }
    leaderboard = {
        "path": "runs/leaderboard.jsonl",
        "sha256": _sha256(leaderboard_path.read_bytes()),
    }
    draft = {
        "schema_version": "1.0.0",
        "package_id": "specialist-evidence-fixture-v1",
        "created_at": "2026-07-15T08:00:00Z",
        "evaluation_set_sha256": evaluation_sha,
        "pipeline_fingerprint_sha256": fingerprint_sha,
        "specialist_margin_manifest_sha256": manifest["sha256"],
        "enabled_lanes": sorted(SPECIALIST_ROLES),
        "leaderboard": leaderboard,
        "lanes": lanes,
        "authority": "measured_evidence_no_automatic_promotion_authority",
    }
    return draft, results, manifest


def _seal(draft: dict, results: dict, manifest: dict, root: Path) -> dict:
    return seal_package(
        draft,
        benchmark_results=results,
        margin_manifest=manifest,
        artifact_root=root,
    )


def _reseal(document: dict) -> None:
    document["sha256"] = _sha256({key: value for key, value in document.items() if key != "sha256"})


def test_complete_specialist_package_covers_all_nine_lanes_and_recomputes(
    tmp_path: Path,
) -> None:
    draft, results, manifest = _fixture(tmp_path)
    package = _seal(draft, results, manifest, tmp_path)
    assert not validate_document(package, "specialist_evidence_package")
    assert package["enabled_lanes"] == sorted(SPECIALIST_ROLES)
    assert len(package["lanes"]) == 9
    validate_package(
        package,
        benchmark_results=results,
        margin_manifest=manifest,
        artifact_root=tmp_path,
    )


def test_missing_or_extra_lane_and_result_set_fail_closed(tmp_path: Path) -> None:
    draft, results, manifest = _fixture(tmp_path)
    role = sorted(SPECIALIST_ROLES)[0]
    draft["lanes"].pop(role)
    with pytest.raises(SpecialistEvidenceError, match="minProperties|lane coverage"):
        _seal(draft, results, manifest, tmp_path)

    draft, results, manifest = _fixture(tmp_path)
    results.pop(role)
    with pytest.raises(SpecialistEvidenceError, match="result set is incomplete"):
        _seal(draft, results, manifest, tmp_path)


def test_benchmark_hard_bucket_failure_or_hash_drift_fails(tmp_path: Path) -> None:
    draft, results, manifest = _fixture(tmp_path)
    role = "hand_finger_segmentation"
    row = results[role]["rows"][0]
    row["observed_delta"] = -float(row["noninferiority_margin"]) - 0.01
    row["passed"] = False
    _reseal(results[role])
    draft["lanes"][role]["benchmark_result_sha256"] = results[role]["sha256"]
    with pytest.raises(SpecialistEvidenceError, match="non-inferiority failed"):
        _seal(draft, results, manifest, tmp_path)

    draft, results, manifest = _fixture(tmp_path)
    draft["lanes"][role]["benchmark_result_sha256"] = "a" * 64
    with pytest.raises(SpecialistEvidenceError, match="benchmark result hash mismatch"):
        _seal(draft, results, manifest, tmp_path)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("wrong_role_evidence_kind", "evidence kind is invalid"),
        ("missing_artifact_kind", "artifacts are incomplete"),
        ("artifact_hash_drift", "artifact hash mismatch"),
        ("role_evidence_hash_drift", "role evidence hash mismatch"),
        ("reused_artifact", "path is reused"),
        ("path_escape", "escapes root"),
    ],
)
def test_artifact_and_role_evidence_failures_are_exact(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    draft, results, manifest = _fixture(tmp_path)
    roles = sorted(SPECIALIST_ROLES)
    lane = draft["lanes"][roles[0]]
    if mutation == "wrong_role_evidence_kind":
        lane["role_evidence"]["kind"] = "pose_variant_benchmark"
    elif mutation == "missing_artifact_kind":
        lane["artifacts"][0]["kind"] = lane["artifacts"][1]["kind"]
    elif mutation == "artifact_hash_drift":
        lane["artifacts"][0]["sha256"] = "a" * 64
    elif mutation == "role_evidence_hash_drift":
        lane["role_evidence"]["sha256"] = "a" * 64
    elif mutation == "reused_artifact":
        draft["lanes"][roles[1]]["artifacts"][0] = copy.deepcopy(lane["artifacts"][0])
    elif mutation == "path_escape":
        outside = tmp_path.parent / "outside-specialist.bin"
        outside.write_bytes(b"outside")
        lane["artifacts"][0] = {
            "kind": "correction_diff",
            "path": "../outside-specialist.bin",
            "sha256": _sha256(outside.read_bytes()),
        }
    with pytest.raises(SpecialistEvidenceError, match=expected):
        _seal(draft, results, manifest, tmp_path)


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("disagreement", "disagreement fraction mismatch"),
        ("correction_pixels", "changed-pixels-per-100k mismatch"),
        ("review_time", "review-time delta mismatch"),
    ],
)
def test_derived_metric_denominators_cannot_be_asserted(
    tmp_path: Path, field: str, expected: str
) -> None:
    draft, results, manifest = _fixture(tmp_path)
    lane = draft["lanes"]["foot_toe_segmentation"]
    if field == "disagreement":
        lane[field]["fraction"] = 0.2
    elif field == "correction_pixels":
        lane[field]["changed_pixels_per_100k"] = 0.0
    else:
        lane[field]["delta_seconds_per_case"] = 0.0
    with pytest.raises(SpecialistEvidenceError, match=expected):
        _seal(draft, results, manifest, tmp_path)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("leaderboard_hash", "leaderboard file hash mismatch"),
        ("missing_run", "run reference is missing"),
        ("evaluation_ref", "leaderboard evaluation hash mismatch"),
    ],
)
def test_leaderboard_publication_is_hash_and_evaluation_bound(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    draft, results, manifest = _fixture(tmp_path)
    lane = draft["lanes"]["geometry_provider"]
    if mutation == "leaderboard_hash":
        draft["leaderboard"]["sha256"] = "a" * 64
    elif mutation == "missing_run":
        lane["leaderboard"]["challenger_run_id"] = "missing-run"
    else:
        draft["evaluation_set_sha256"] = "a" * 64
        for current in draft["lanes"].values():
            current["evaluation_set_sha256"] = "a" * 64
    with pytest.raises(SpecialistEvidenceError, match=expected):
        _seal(draft, results, manifest, tmp_path)


def test_pipeline_and_evaluation_drift_and_package_tamper_fail(tmp_path: Path) -> None:
    draft, results, manifest = _fixture(tmp_path)
    draft["lanes"]["pose_provider"]["pipeline_fingerprint_sha256"] = "a" * 64
    with pytest.raises(SpecialistEvidenceError, match="pipeline fingerprint mismatch"):
        _seal(draft, results, manifest, tmp_path)

    draft, results, manifest = _fixture(tmp_path)
    package = _seal(draft, results, manifest, tmp_path)
    package["lanes"]["pose_provider"]["sample_count"] += 1
    with pytest.raises(SpecialistEvidenceError, match="package hash mismatch"):
        validate_package(
            package,
            benchmark_results=results,
            margin_manifest=manifest,
            artifact_root=tmp_path,
        )


def test_one_command_tool_seals_and_verifies_complete_package(tmp_path: Path) -> None:
    draft, results, _manifest = _fixture(tmp_path)
    draft_path = tmp_path / "draft.json"
    output_path = tmp_path / "package.json"
    result_dir = tmp_path / "benchmark_results"
    result_dir.mkdir()
    draft_path.write_text(json.dumps(draft, indent=2) + "\n", encoding="utf-8")
    for role, result in results.items():
        (result_dir / f"{role}.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
    command = [
        sys.executable,
        str(ROOT / "tools/specialist_evidence_package.py"),
        str(draft_path),
        "--benchmark-results",
        str(result_dir),
        "--artifact-root",
        str(tmp_path),
        "--output",
        str(output_path),
    ]
    sealed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert sealed.returncode == 0, sealed.stderr
    verified = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/specialist_evidence_package.py"),
            str(output_path),
            "--benchmark-results",
            str(result_dir),
            "--artifact-root",
            str(tmp_path),
            "--verify",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr
