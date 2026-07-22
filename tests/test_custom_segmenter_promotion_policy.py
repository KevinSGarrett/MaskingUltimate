import copy
import hashlib
import json
from pathlib import Path

import pytest

from maskfactory.training.promotion_policy import (
    CERTIFICATE_AUTHORITY,
    CUSTOM_SEGMENTER_MARGIN_MANIFEST_SHA256,
    DEFAULT_CUSTOM_SEGMENTER_MARGIN_MANIFEST,
    REQUIRED_CERTIFICATE_IDENTITY_HASHES,
    REQUIRED_RESULT_INPUT_HASHES,
    CustomSegmenterPromotionError,
    load_custom_segmenter_margin_manifest,
    validate_custom_segmenter_benchmark_results,
    validate_custom_segmenter_margin_manifest,
    validate_custom_segmenter_promotion_certificate,
)

ROOT = Path(__file__).resolve().parents[1]


def _sha256(document: dict) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _reseal(document: dict) -> None:
    document["sha256"] = _sha256({key: value for key, value in document.items() if key != "sha256"})


def _results(
    manifest: dict,
    margins: dict[str, float],
    *,
    primary_improvement: float = 0.005,
    labor_improvement: float = 0.0,
) -> dict:
    input_hashes = {key: _digest(key) for key in REQUIRED_RESULT_INPUT_HASHES}
    document = {
        "schema_version": "1.0.0",
        "benchmark_id": "custom-segmenter-fixture-v1",
        "role": "custom_segmenter",
        "margin_manifest_sha256": manifest["sha256"],
        "results_opened_at": "2026-07-15T05:30:00Z",
        "input_hashes": input_hashes,
        "primary_objective_result": {
            "metric": manifest["role"]["primary_objective"]["metric"],
            "observed_improvement": primary_improvement,
            "minimum_improvement": manifest["role"]["primary_objective"]["minimum_improvement"],
            "passed": primary_improvement
            >= manifest["role"]["primary_objective"]["minimum_improvement"],
        },
        "labor_objective_result": {
            "metric": manifest["role"]["labor_objective"]["metric"],
            "observed_improvement": labor_improvement,
            "minimum_improvement": manifest["role"]["labor_objective"]["minimum_improvement"],
            "passed": labor_improvement
            >= manifest["role"]["labor_objective"]["minimum_improvement"],
        },
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


def _certificate(manifest: dict, margins: dict[str, float]) -> tuple[dict, dict]:
    results = _results(manifest, margins)
    identities = {key: _digest(key) for key in REQUIRED_CERTIFICATE_IDENTITY_HASHES}
    identities["benchmark_results_sha256"] = results["sha256"]
    for key in REQUIRED_RESULT_INPUT_HASHES:
        identities[key] = results["input_hashes"][key]
    certificate = {
        "schema_version": "1.0.0",
        "authority": CERTIFICATE_AUTHORITY,
        "candidate_key": "eomt_dinov3_fixture",
        "target_role": "custom_segmenter",
        "lifecycle_state": "benchmarked",
        "identity_hashes": identities,
        "license_gate": {
            "verify_license": False,
            "checkpoint_decision": "allowed",
        },
        "benchmark_results": results,
        "rollback_evidence": {
            "candidate_provider": "eomt_dinov3_fixture",
            "incumbent_provider": "segformer_b2_fixture",
            "target_role": "custom_segmenter",
            "one_command": "maskfactory providers rollback custom_segmenter",
            "rollback_observed": True,
            "restore_observed": True,
            "result": "pass",
            "tested_at": "2026-07-15T05:45:00Z",
            "evidence_sha256": _digest("rollback"),
        },
    }
    certificate["sha256"] = _sha256(certificate)
    return certificate, copy.deepcopy(identities)


def test_frozen_manifest_covers_every_governed_bucket_and_is_hash_locked() -> None:
    manifest, expanded = load_custom_segmenter_margin_manifest()

    assert DEFAULT_CUSTOM_SEGMENTER_MARGIN_MANIFEST == (
        ROOT / "qa/governance/benchmark_matrices/custom_segmenter_margins_v1.json"
    )
    assert manifest["sha256"] == CUSTOM_SEGMENTER_MARGIN_MANIFEST_SHA256
    assert len(manifest["role"]["hard_labels"]) == 27
    assert len(manifest["role"]["high_risk_contexts"]) == 17
    assert len(expanded) == 161
    assert all(
        prefix in {bucket.split(":", maxsplit=1)[0] for bucket in expanded}
        for prefix in ("label", "context", "zero_regression")
    )


def test_manifest_edit_fails_even_after_recomputing_self_hash() -> None:
    manifest = json.loads(DEFAULT_CUSTOM_SEGMENTER_MARGIN_MANIFEST.read_text(encoding="utf-8"))
    tampered = copy.deepcopy(manifest)
    tampered["role"]["label_margins"]["mean_iou"] = 0.5
    with pytest.raises(CustomSegmenterPromotionError, match="hash mismatch"):
        validate_custom_segmenter_margin_manifest(tampered)

    _reseal(tampered)
    with pytest.raises(CustomSegmenterPromotionError, match="locked hash"):
        validate_custom_segmenter_margin_manifest(tampered)


def test_manifest_rejects_source_drift_and_missing_coverage(tmp_path: Path) -> None:
    manifest = json.loads(DEFAULT_CUSTOM_SEGMENTER_MARGIN_MANIFEST.read_text(encoding="utf-8"))
    root = tmp_path / "root"
    for relative in manifest["source_hashes"]:
        source = ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    (root / "configs/qa.yaml").write_text("metrics: {hard_classes: [hair]}\n", encoding="utf-8")
    with pytest.raises(CustomSegmenterPromotionError, match="governing source hash drift"):
        validate_custom_segmenter_margin_manifest(manifest, root=root)

    missing = copy.deepcopy(manifest)
    missing["role"]["hard_labels"].pop()
    _reseal(missing)
    with pytest.raises(CustomSegmenterPromotionError, match="locked hash"):
        validate_custom_segmenter_margin_manifest(missing)
    with pytest.raises(CustomSegmenterPromotionError, match="hard-label margins are incomplete"):
        validate_custom_segmenter_margin_manifest(missing, expected_sha256=None)


def test_primary_win_or_material_labor_reduction_each_pass() -> None:
    manifest, margins = load_custom_segmenter_margin_manifest()
    validate_custom_segmenter_benchmark_results(
        _results(manifest, margins, primary_improvement=0.005, labor_improvement=0.0),
        margin_manifest=manifest,
    )
    validate_custom_segmenter_benchmark_results(
        _results(manifest, margins, primary_improvement=0.0, labor_improvement=0.05),
        margin_manifest=manifest,
    )


def test_results_reject_neither_win_and_inconsistent_objective_flag() -> None:
    manifest, margins = load_custom_segmenter_margin_manifest()
    losing = _results(manifest, margins, primary_improvement=0.0, labor_improvement=0.0)
    with pytest.raises(CustomSegmenterPromotionError, match="lacks a primary win"):
        validate_custom_segmenter_benchmark_results(losing, margin_manifest=manifest)

    inconsistent = _results(manifest, margins)
    inconsistent["primary_objective_result"]["passed"] = False
    _reseal(inconsistent)
    with pytest.raises(CustomSegmenterPromotionError, match="pass flag is inconsistent"):
        validate_custom_segmenter_benchmark_results(inconsistent, margin_manifest=manifest)


@pytest.mark.parametrize("bucket_prefix", ["label:", "context:", "zero_regression:"])
def test_average_win_cannot_hide_any_bucket_regression(bucket_prefix: str) -> None:
    manifest, margins = load_custom_segmenter_margin_manifest()
    results = _results(manifest, margins, primary_improvement=0.2)
    row = next(row for row in results["rows"] if row["bucket"].startswith(bucket_prefix))
    row["observed_delta"] = -float(row["noninferiority_margin"]) - 0.000001
    row["passed"] = False
    _reseal(results)

    with pytest.raises(CustomSegmenterPromotionError, match="non-inferiority failed"):
        validate_custom_segmenter_benchmark_results(results, margin_manifest=manifest)


def test_results_reject_bucket_omission_margin_drift_nan_and_input_hash_gap() -> None:
    manifest, margins = load_custom_segmenter_margin_manifest()
    missing = _results(manifest, margins)
    missing["rows"].pop()
    _reseal(missing)
    with pytest.raises(CustomSegmenterPromotionError, match="coverage is incomplete"):
        validate_custom_segmenter_benchmark_results(missing, margin_manifest=manifest)

    drift = _results(manifest, margins)
    drift["rows"][0]["noninferiority_margin"] += 0.1
    _reseal(drift)
    with pytest.raises(CustomSegmenterPromotionError, match="margin drift"):
        validate_custom_segmenter_benchmark_results(drift, margin_manifest=manifest)

    nan = _results(manifest, margins)
    nan["rows"][0]["observed_delta"] = float("nan")
    _reseal(nan)
    with pytest.raises(CustomSegmenterPromotionError, match="margin drift"):
        validate_custom_segmenter_benchmark_results(nan, margin_manifest=manifest)

    gap = _results(manifest, margins)
    gap["input_hashes"].pop("qa_config_sha256")
    _reseal(gap)
    with pytest.raises(CustomSegmenterPromotionError, match="hash set is incomplete"):
        validate_custom_segmenter_benchmark_results(gap, margin_manifest=manifest)


def test_valid_identity_bound_certificate_grants_no_role_authority() -> None:
    manifest, margins = load_custom_segmenter_margin_manifest()
    certificate, current = _certificate(manifest, margins)

    summary = validate_custom_segmenter_promotion_certificate(
        certificate,
        expected_identity_hashes=current,
        margin_manifest=manifest,
    )
    assert summary["candidate_key"] == "eomt_dinov3_fixture"
    assert summary["rollback_provider"] == "segformer_b2_fixture"
    assert summary["authority"] == (
        "validated_prerequisites_only_no_role_serving_or_gold_authority"
    )


@pytest.mark.parametrize("identity_key", sorted(REQUIRED_CERTIFICATE_IDENTITY_HASHES))
def test_certificate_rejects_every_missing_identity(identity_key: str) -> None:
    manifest, margins = load_custom_segmenter_margin_manifest()
    certificate, current = _certificate(manifest, margins)
    certificate["identity_hashes"].pop(identity_key)
    _reseal(certificate)

    with pytest.raises(CustomSegmenterPromotionError, match="hash set is incomplete"):
        validate_custom_segmenter_promotion_certificate(
            certificate,
            expected_identity_hashes=current,
            margin_manifest=manifest,
        )


@pytest.mark.parametrize("identity_key", sorted(REQUIRED_CERTIFICATE_IDENTITY_HASHES))
def test_certificate_rejects_every_stale_identity(identity_key: str) -> None:
    manifest, margins = load_custom_segmenter_margin_manifest()
    certificate, current = _certificate(manifest, margins)
    current[identity_key] = "f" * 64

    with pytest.raises(CustomSegmenterPromotionError, match="identity is stale"):
        validate_custom_segmenter_promotion_certificate(
            certificate,
            expected_identity_hashes=current,
            margin_manifest=manifest,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda packet: packet.update(lifecycle_state="installed"), "identity or lifecycle"),
        (
            lambda packet: packet["license_gate"].update(verify_license=True),
            "license gate is unresolved",
        ),
        (
            lambda packet: packet["rollback_evidence"].update(
                incumbent_provider=packet["candidate_key"]
            ),
            "rollback evidence did not pass",
        ),
        (
            lambda packet: packet["rollback_evidence"].update(rollback_observed=False),
            "rollback evidence did not pass",
        ),
    ],
)
def test_certificate_rejects_nonbenchmarked_content_license_and_rollback_failures(
    mutation, message: str
) -> None:
    manifest, margins = load_custom_segmenter_margin_manifest()
    certificate, current = _certificate(manifest, margins)
    mutation(certificate)
    _reseal(certificate)

    with pytest.raises(CustomSegmenterPromotionError, match=message):
        validate_custom_segmenter_promotion_certificate(
            certificate,
            expected_identity_hashes=current,
            margin_manifest=manifest,
        )


def test_certificate_rejects_result_input_rebinding_and_packet_tamper() -> None:
    manifest, margins = load_custom_segmenter_margin_manifest()
    certificate, current = _certificate(manifest, margins)
    certificate["benchmark_results"]["input_hashes"]["qa_config_sha256"] = "e" * 64
    _reseal(certificate["benchmark_results"])
    certificate["identity_hashes"]["benchmark_results_sha256"] = certificate["benchmark_results"][
        "sha256"
    ]
    current["benchmark_results_sha256"] = certificate["benchmark_results"]["sha256"]
    _reseal(certificate)
    with pytest.raises(CustomSegmenterPromotionError, match="input binding is stale"):
        validate_custom_segmenter_promotion_certificate(
            certificate,
            expected_identity_hashes=current,
            margin_manifest=manifest,
        )

    certificate, current = _certificate(manifest, margins)
    certificate["rollback_evidence"]["one_command"] = "tampered"
    with pytest.raises(CustomSegmenterPromotionError, match="certificate hash mismatch"):
        validate_custom_segmenter_promotion_certificate(
            certificate,
            expected_identity_hashes=current,
            margin_manifest=manifest,
        )
