import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.providers.currency import (
    CurrencyReviewError,
    build_currency_review,
    generate_currency_signing_key,
    verify_currency_review,
)
from maskfactory.validation import validate_document
from registry_helpers import governed_file_model, governed_registry

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


def _canonical_sha256(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _benchmark(*, issued_at: datetime = NOW):
    certificate = {
        "schema_version": "1.0.0",
        "target_role": "role_a",
        "primary_win_or_labor_reduction": True,
        "hard_bucket_results": [
            {
                "bucket": "hands_feet",
                "observed_delta": 0.01,
                "noninferiority_margin": 0.02,
                "passed": True,
            }
        ],
        "frozen_eval_sha256": "e" * 64,
        "issued_at": issued_at.isoformat().replace("+00:00", "Z"),
    }
    certificate["sha256"] = _canonical_sha256(certificate)
    return certificate


def _write_fixture(tmp_path: Path):
    pipeline_path = tmp_path / "pipeline.yaml"
    external_path = Path("configs/external_sources.yaml").resolve()
    model_path = tmp_path / "model_registry.json"
    rollback_path = tmp_path / "rollback_evidence.json"
    dependency_path = tmp_path / "requirements.lock.txt"
    private_key = tmp_path / "secret/currency_private.pem"
    public_key = tmp_path / "currency_public.pem"
    pipeline = {
        "provider_roles": {
            "role_a": {
                "active": "incumbent",
                "challengers": [],
                "rollback": "fallback",
            }
        },
        "provider_catalog": {
            "incumbent": {
                "registry": "model_registry",
                "key": "incumbent_model",
                "execution": "local",
                "billing": "none",
            },
            "fallback": {
                "registry": "model_registry",
                "key": "fallback_model",
                "execution": "local",
                "billing": "none",
            },
        },
    }
    pipeline_path.write_text(yaml.safe_dump(pipeline, sort_keys=False), encoding="utf-8")
    active = governed_file_model(
        key="incumbent_model",
        role="active_role",
        file="models/incumbent.bin",
        sha256="a" * 64,
        benchmark_certificate=_benchmark(),
    )
    fallback = governed_file_model(
        key="fallback_model",
        role="fallback_role",
        file="models/fallback.bin",
        sha256="b" * 64,
        lifecycle_state="benchmarked",
    )
    model_path.write_text(
        json.dumps(governed_registry([active, fallback]), indent=2), encoding="utf-8"
    )
    rollback_record = {
        "schema_version": "1.0.0",
        "role": "role_a",
        "active_provider": "incumbent",
        "rollback_provider": "fallback",
        "pipeline_sha256": hashlib.sha256(pipeline_path.read_bytes()).hexdigest(),
        "active_artifact_sha256": "a" * 64,
        "rollback_artifact_sha256": "b" * 64,
        "result": "pass",
        "rollback_observed": True,
        "restore_observed": True,
        "tested_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    rollback_record["sha256"] = _canonical_sha256(rollback_record)
    rollback_path.write_text(
        json.dumps({"schema_version": "1.0.0", "records": [rollback_record]}, indent=2),
        encoding="utf-8",
    )
    dependency_path.write_text("runtime==1.2.3\n", encoding="utf-8")
    generate_currency_signing_key(private_key, public_key)
    return {
        "pipeline_path": pipeline_path,
        "external_registry_path": external_path,
        "model_registry_path": model_path,
        "rollback_evidence_path": rollback_path,
        "dependency_paths": {"python_lock": dependency_path},
        "private_key_path": private_key,
        "public_key_path": public_key,
    }


def _build(paths, **overrides):
    arguments = {
        key: value
        for key, value in paths.items()
        if key
        in {
            "pipeline_path",
            "external_registry_path",
            "model_registry_path",
            "rollback_evidence_path",
            "dependency_paths",
            "private_key_path",
        }
    }
    arguments.update(
        {
            "event": "scheduled_90_day",
            "reviewer": "maskfactory-governance",
            "reviewed_at": NOW,
        }
    )
    arguments.update(overrides)
    return build_currency_review(**arguments)


def _verify(review, paths, **overrides):
    arguments = {
        key: value
        for key, value in paths.items()
        if key
        in {
            "pipeline_path",
            "external_registry_path",
            "model_registry_path",
            "rollback_evidence_path",
            "dependency_paths",
            "public_key_path",
        }
    }
    arguments.update({"now": NOW, "required_event": "scheduled_90_day"})
    arguments.update(overrides)
    return verify_currency_review(review, **arguments)


def test_signed_current_review_covers_every_active_role_and_recomputes(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    review = _build(paths)
    assert review["status"] == "pass"
    assert not validate_document(review, "currency_review")
    result = _verify(review, paths)
    assert result["active_role_count"] == 1
    assert result["review_sha256"] == review["review_sha256"]


def test_review_signature_and_payload_tampering_fail(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    review = _build(paths)
    review["reviewer"] = "tampered"
    with pytest.raises(CurrencyReviewError) as caught:
        _verify(review, paths)
    assert {
        "currency_review_hash_mismatch",
        "currency_review_payload_hash_mismatch",
        "currency_review_signature_invalid",
    } <= set(caught.value.codes)


def test_changed_active_input_hash_fails_even_with_valid_old_signature(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    review = _build(paths)
    paths["dependency_paths"]["python_lock"].write_text("runtime==1.2.4\n", encoding="utf-8")
    with pytest.raises(CurrencyReviewError) as caught:
        _verify(review, paths)
    assert "active_input_hash_mismatch" in caught.value.codes


def test_changed_governance_decision_log_fails_even_with_valid_old_signature(
    tmp_path: Path,
):
    paths = _write_fixture(tmp_path)
    decisions = tmp_path / "DECISIONS_LOG.md"
    decisions.write_text("# Frozen governance decisions\n", encoding="utf-8")
    paths["dependency_paths"]["governance_decisions"] = decisions
    review = _build(paths)
    decisions.write_text("# Mutated governance decisions\n", encoding="utf-8")
    with pytest.raises(CurrencyReviewError) as caught:
        _verify(review, paths)
    assert "active_input_hash_mismatch" in caught.value.codes


def test_review_expires_at_ninety_days(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    review = _build(paths)
    with pytest.raises(CurrencyReviewError) as caught:
        _verify(review, paths, now=NOW + timedelta(days=91))
    assert "currency_review_expired" in caught.value.codes
    assert "currency_review_stale" in caught.value.codes


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("missing_artifact_hash", "active_artifact_hash_missing"),
        ("unresolved_content", "content_compatibility_unresolved"),
        ("missing_benchmark", "benchmark_certificate_missing"),
        ("stale_benchmark", "benchmark_certificate_stale"),
        ("missing_rollback", "rollback_evidence_missing"),
    ],
)
def test_each_seeded_active_path_failure_reports_the_exact_gate(
    tmp_path: Path, mutation: str, expected: str
):
    paths = _write_fixture(tmp_path)
    models = json.loads(paths["model_registry_path"].read_text(encoding="utf-8"))
    active = next(row for row in models["models"] if row["key"] == "incumbent_model")
    if mutation == "missing_artifact_hash":
        active.pop("sha256")
    elif mutation == "unresolved_content":
        active["content_compatibility"]["consensual_explicit_adult"] = "unclear"
    elif mutation == "missing_benchmark":
        active.pop("benchmark_certificate")
    elif mutation == "stale_benchmark":
        active["benchmark_certificate"] = _benchmark(issued_at=NOW - timedelta(days=91))
    elif mutation == "missing_rollback":
        paths["rollback_evidence_path"].write_text(
            json.dumps({"schema_version": "1.0.0", "records": []}), encoding="utf-8"
        )
    paths["model_registry_path"].write_text(json.dumps(models, indent=2), encoding="utf-8")
    review = _build(paths)
    assert review["status"] == "fail"
    with pytest.raises(CurrencyReviewError) as caught:
        _verify(review, paths)
    assert expected in caught.value.codes
    _verify(review, paths, require_pass=False)


def test_review_cannot_fabricate_pass_over_derived_failure(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    rollback = json.loads(paths["rollback_evidence_path"].read_text(encoding="utf-8"))
    rollback["records"] = []
    paths["rollback_evidence_path"].write_text(json.dumps(rollback), encoding="utf-8")
    review = _build(paths)
    forged = copy.deepcopy(review)
    forged["status"] = "pass"
    with pytest.raises(CurrencyReviewError) as caught:
        _verify(forged, paths)
    assert "currency_review_status_mismatch" in caught.value.codes


def test_currency_review_cli_builds_and_verifies_exact_fixture(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    output = tmp_path / "review.json"
    runner = CliRunner()
    built = runner.invoke(
        main,
        [
            "governance",
            "build-currency-review",
            "--event",
            "scheduled_90_day",
            "--reviewer",
            "fixture-reviewer",
            "--private-key",
            str(paths["private_key_path"]),
            "--pipeline",
            str(paths["pipeline_path"]),
            "--external-registry",
            str(paths["external_registry_path"]),
            "--model-registry",
            str(paths["model_registry_path"]),
            "--rollback-evidence",
            str(paths["rollback_evidence_path"]),
            "--output",
            str(output),
        ],
    )
    assert built.exit_code == 0, built.output
    verified = runner.invoke(
        main,
        [
            "governance",
            "verify-currency-review",
            str(output),
            "--public-key",
            str(paths["public_key_path"]),
            "--pipeline",
            str(paths["pipeline_path"]),
            "--external-registry",
            str(paths["external_registry_path"]),
            "--model-registry",
            str(paths["model_registry_path"]),
            "--rollback-evidence",
            str(paths["rollback_evidence_path"]),
            "--required-event",
            "scheduled_90_day",
        ],
    )
    assert verified.exit_code == 0, verified.output
