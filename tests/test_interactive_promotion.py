import copy
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from maskfactory.providers.interactive_promotion import (
    CERTIFICATE_AUTHORITY,
    InteractivePromotionCertificateError,
    build_interactive_promotion_certificate,
    verify_interactive_promotion_certificate,
)
from maskfactory.validation import validate_document
from test_matrix_promotion import _build, _bundle, _fixture

ROOT = Path(__file__).resolve().parents[1]


def _seal(value: dict) -> None:
    value["sha256"] = hashlib.sha256(
        json.dumps(
            {key: item for key, item in value.items() if key != "sha256"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _inputs(tmp_path: Path) -> dict:
    matrix = _fixture(tmp_path)
    bundle = _bundle(tmp_path, matrix, _build(matrix))
    report_sha = matrix["matrix_report"]["sha256"]
    benchmark = {
        "schema_version": "1.0.0",
        "target_role": "interactive_segmenter",
        "primary_win_or_labor_reduction": True,
        "hard_bucket_results": [
            {
                "bucket": "small_parts",
                "observed_delta": 0.01,
                "noninferiority_margin": 0.02,
                "passed": True,
            }
        ],
        "frozen_eval_sha256": report_sha,
        "issued_at": "2026-07-17T00:00:00Z",
    }
    _seal(benchmark)
    rollback = {
        "schema_version": "1.0.0",
        "target_role": "interactive_segmenter",
        "candidate_provider": "sam3_1",
        "incumbent_provider": "sam2_1_large",
        "pipeline_before_sha256": "1" * 64,
        "pipeline_promoted_sha256": "2" * 64,
        "pipeline_restored_sha256": "1" * 64,
        "candidate_smoke_sha256": "3" * 64,
        "incumbent_smoke_sha256": "4" * 64,
        "rollback_observed": True,
        "restore_observed": True,
        "tested_at": "2026-07-17T01:00:00Z",
    }
    _seal(rollback)
    artifacts = matrix["matrix_manifest"]["shared_identity"]["provider_artifact_sha256"]
    return {
        "reviewer": "pytest-governance",
        "private_key_path": matrix["private_key_path"],
        "matrix_bundle_root": bundle,
        "benchmark_certificate": benchmark,
        "rollback_evidence": rollback,
        "candidate_key": "sam3_1",
        "incumbent_key": "sam2_1_large",
        "candidate_artifact_key": "sam3_1",
        "incumbent_artifact_key": "sam2_1",
        "candidate_checkpoint_sha256": artifacts["sam3_1"],
        "incumbent_checkpoint_sha256": artifacts["sam2_1"],
        "candidate_runtime_lock_sha256": "5" * 64,
        "issued_at": datetime(2026, 7, 18, tzinfo=UTC),
    }


def _verify(certificate: dict, inputs: dict) -> dict:
    return verify_interactive_promotion_certificate(
        certificate,
        **{
            key: value
            for key, value in inputs.items()
            if key not in {"private_key_path", "reviewer", "issued_at"}
        },
    )


def test_signed_interactive_certificate_binds_matrix_benchmark_and_rollback(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    certificate = build_interactive_promotion_certificate(**inputs)
    summary = _verify(certificate, inputs)

    assert not validate_document(certificate, "interactive_provider_promotion_certificate")
    assert summary["candidate_key"] == "sam3_1"
    assert summary["incumbent_key"] == "sam2_1_large"
    assert summary["authority"] == CERTIFICATE_AUTHORITY
    aggregate = json.loads(
        (inputs["matrix_bundle_root"] / "certificate.json").read_text(encoding="utf-8")
    )
    assert certificate["matrix_certificate_sha256"] == aggregate["certificate_sha256"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["benchmark_certificate"].update(frozen_eval_sha256="0" * 64),
            "matrix report",
        ),
        (
            lambda value: value["rollback_evidence"].update(pipeline_restored_sha256="9" * 64),
            "rollback rehearsal",
        ),
        (
            lambda value: value.update(candidate_checkpoint_sha256="8" * 64),
            "absent from the matrix",
        ),
    ],
)
def test_interactive_certificate_rejects_stale_inputs(
    tmp_path: Path, mutation, message: str
) -> None:
    inputs = _inputs(tmp_path)
    mutation(inputs)
    if "benchmark_certificate" in inputs:
        _seal(inputs["benchmark_certificate"])
    if "rollback_evidence" in inputs:
        _seal(inputs["rollback_evidence"])
    with pytest.raises(InteractivePromotionCertificateError, match=message):
        build_interactive_promotion_certificate(**inputs)


def test_interactive_certificate_rejects_signature_and_live_rebinding(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    certificate = build_interactive_promotion_certificate(**inputs)
    rebound = copy.deepcopy(inputs)
    rebound["candidate_runtime_lock_sha256"] = "a" * 64
    with pytest.raises(InteractivePromotionCertificateError, match="stale or rebound"):
        _verify(certificate, rebound)

    tampered = copy.deepcopy(certificate)
    tampered["signature"] = "A" * 86 + "=="
    tampered["certificate_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in tampered.items() if key != "certificate_sha256"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    with pytest.raises(InteractivePromotionCertificateError, match="signature is invalid"):
        _verify(tampered, inputs)


def test_interactive_certificate_tool_builds_and_verifies(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    benchmark_path = tmp_path / "benchmark.json"
    rollback_path = tmp_path / "rollback.json"
    output = tmp_path / "certificate.json"
    benchmark_path.write_text(json.dumps(inputs["benchmark_certificate"]), encoding="utf-8")
    rollback_path.write_text(json.dumps(inputs["rollback_evidence"]), encoding="utf-8")
    common = [
        sys.executable,
        str(ROOT / "tools/certify_interactive_provider_promotion.py"),
        "--matrix-bundle",
        str(inputs["matrix_bundle_root"]),
        "--benchmark-certificate",
        str(benchmark_path),
        "--rollback-evidence",
        str(rollback_path),
        "--candidate-key",
        inputs["candidate_key"],
        "--incumbent-key",
        inputs["incumbent_key"],
        "--candidate-artifact-key",
        inputs["candidate_artifact_key"],
        "--incumbent-artifact-key",
        inputs["incumbent_artifact_key"],
        "--candidate-checkpoint-sha256",
        inputs["candidate_checkpoint_sha256"],
        "--incumbent-checkpoint-sha256",
        inputs["incumbent_checkpoint_sha256"],
        "--candidate-runtime-lock-sha256",
        inputs["candidate_runtime_lock_sha256"],
    ]
    built = subprocess.run(
        [
            *common,
            "--private-key",
            str(inputs["private_key_path"]),
            "--reviewer",
            inputs["reviewer"],
            "--issued-at",
            inputs["issued_at"].isoformat(),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    verified = subprocess.run(
        [*common, "--verify", "--certificate", str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr
