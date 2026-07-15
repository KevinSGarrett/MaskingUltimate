import copy
import hashlib
import json
from pathlib import Path

import pytest

from maskfactory.providers.benchmark_policy import (
    DEFAULT_SPECIALIST_MARGIN_MANIFEST,
    SPECIALIST_MARGIN_MANIFEST_SHA256,
    SPECIALIST_ROLES,
    SpecialistBenchmarkPolicyError,
    load_specialist_margin_manifest,
    validate_specialist_benchmark_results,
    validate_specialist_margin_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def _sha256(document: dict) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _results(role: str, margins: dict[str, float], manifest_sha256: str) -> dict:
    document = {
        "schema_version": "1.0.0",
        "benchmark_id": "specialist-fixture-v1",
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


def _reseal(document: dict) -> None:
    document["sha256"] = _sha256({key: value for key, value in document.items() if key != "sha256"})


def test_frozen_specialist_manifest_is_hash_locked_and_covers_every_role() -> None:
    manifest, expanded = load_specialist_margin_manifest()

    assert DEFAULT_SPECIALIST_MARGIN_MANIFEST == (
        ROOT / "qa/governance/benchmark_matrices/specialist_margins_v1.json"
    )
    assert manifest["sha256"] == SPECIALIST_MARGIN_MANIFEST_SHA256
    assert set(expanded) == SPECIALIST_ROLES
    assert all(buckets for buckets in expanded.values())
    assert all(
        any(bucket.startswith("label:") for bucket in buckets) for buckets in expanded.values()
    )
    assert all(
        any(bucket.startswith("context:") for bucket in buckets) for buckets in expanded.values()
    )
    assert all(
        any(bucket.startswith("zero_regression:") for bucket in buckets)
        for buckets in expanded.values()
    )


def test_manifest_margin_edit_fails_even_when_editor_recomputes_self_hash() -> None:
    manifest = json.loads(DEFAULT_SPECIALIST_MARGIN_MANIFEST.read_text(encoding="utf-8"))
    tampered = copy.deepcopy(manifest)
    tampered["roles"]["hand_finger_segmentation"]["label_margins"]["mean_iou"] = 0.20
    with pytest.raises(SpecialistBenchmarkPolicyError, match="hash mismatch"):
        validate_specialist_margin_manifest(tampered)

    _reseal(tampered)
    with pytest.raises(SpecialistBenchmarkPolicyError, match="locked hash"):
        validate_specialist_margin_manifest(tampered)


def test_manifest_source_drift_fails_before_results_can_open(tmp_path: Path) -> None:
    manifest = json.loads(DEFAULT_SPECIALIST_MARGIN_MANIFEST.read_text(encoding="utf-8"))
    root = tmp_path / "root"
    for relative in manifest["source_hashes"]:
        source = ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    (root / "configs/qa.yaml").write_text("metrics: {hard_classes: [hair]}\n", encoding="utf-8")

    with pytest.raises(SpecialistBenchmarkPolicyError, match="governing source hash drift"):
        validate_specialist_margin_manifest(manifest, root=root)


def test_exact_complete_specialist_results_pass_frozen_margins() -> None:
    manifest, expanded = load_specialist_margin_manifest()
    for role, margins in expanded.items():
        validate_specialist_benchmark_results(
            _results(role, margins, manifest["sha256"]),
            margin_manifest=manifest,
        )


def test_result_cannot_omit_a_hard_bucket_or_change_its_margin() -> None:
    manifest, expanded = load_specialist_margin_manifest()
    role = "hand_finger_segmentation"
    missing = _results(role, expanded[role], manifest["sha256"])
    missing["rows"].pop()
    _reseal(missing)
    with pytest.raises(SpecialistBenchmarkPolicyError, match="coverage is incomplete"):
        validate_specialist_benchmark_results(missing, margin_manifest=manifest)

    drifted = _results(role, expanded[role], manifest["sha256"])
    drifted["rows"][0]["noninferiority_margin"] += 0.01
    _reseal(drifted)
    with pytest.raises(SpecialistBenchmarkPolicyError, match="margin drift"):
        validate_specialist_benchmark_results(drifted, margin_manifest=manifest)


def test_primary_win_cannot_hide_one_hard_bucket_regression() -> None:
    manifest, expanded = load_specialist_margin_manifest()
    role = "chest_pelvic_segmentation"
    results = _results(role, expanded[role], manifest["sha256"])
    row = results["rows"][0]
    row["observed_delta"] = -float(row["noninferiority_margin"]) - 0.000001
    row["passed"] = False
    _reseal(results)

    with pytest.raises(SpecialistBenchmarkPolicyError, match="non-inferiority failed"):
        validate_specialist_benchmark_results(results, margin_manifest=manifest)


def test_results_must_bind_frozen_hash_and_postdate_freeze() -> None:
    manifest, expanded = load_specialist_margin_manifest()
    role = "pose_provider"
    wrong_hash = _results(role, expanded[role], "f" * 64)
    with pytest.raises(SpecialistBenchmarkPolicyError, match="margin hash mismatch"):
        validate_specialist_benchmark_results(wrong_hash, margin_manifest=manifest)

    early = _results(role, expanded[role], manifest["sha256"])
    early["results_opened_at"] = manifest["frozen_at"]
    _reseal(early)
    with pytest.raises(SpecialistBenchmarkPolicyError, match="predate frozen margins"):
        validate_specialist_benchmark_results(early, margin_manifest=manifest)
