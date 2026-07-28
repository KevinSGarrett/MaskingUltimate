from __future__ import annotations

import copy
import hashlib
import json

import pytest

from maskfactory.providers.benchmark_policy import load_specialist_margin_manifest
from maskfactory.providers.promotion import (
    LOCAL_GPU_BUDGET_BYTES,
    SpecialistPromotionError,
    validate_specialist_promotion_packet,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _seal(value: dict) -> dict:
    value["sha256"] = hashlib.sha256(
        json.dumps(
            {key: item for key, item in value.items() if key != "sha256"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return value


def _valid_packet() -> tuple[dict, dict]:
    manifest, expanded = load_specialist_margin_manifest()
    role = "hand_finger_segmentation"
    results = _seal(
        {
            "schema_version": "1.0.0",
            "benchmark_id": "pytest-specialist-promotion",
            "role": role,
            "margin_manifest_sha256": manifest["sha256"],
            "results_opened_at": "2026-07-16T00:00:00Z",
            "primary_win_or_labor_reduction": True,
            "rows": [
                {
                    "bucket": bucket,
                    "observed_delta": 0.0,
                    "noninferiority_margin": margin,
                    "passed": True,
                }
                for bucket, margin in expanded[role].items()
            ],
        }
    )
    packet = _seal(
        {
            "schema_version": "1.0.0",
            "authority": "specialist_role_promotion_gate",
            "candidate_key": "hand_challenger",
            "target_role": role,
            "lifecycle_state": "benchmarked",
            "identity_hashes": {
                "source_tree_sha256": _sha("source"),
                "checkpoint_sha256": _sha("checkpoint"),
                "runtime_lock_sha256": _sha("runtime"),
                "license_evidence_sha256": _sha("license"),
            },
            "license_gate": {
                "verify_license": False,
                "checkpoint_decision": "allowed",
            },
            "benchmark_results": results,
            "runtime_reliability": {
                "mode": "local_8gb",
                "hardware_profile_sha256": _sha("hardware"),
                "peak_reserved_bytes": LOCAL_GPU_BUDGET_BYTES,
                "repetitions": 2,
                "deterministic": True,
                "oom_count": 0,
                "crash_count": 0,
                "alternate_runtime_approval": None,
            },
            "rollback_evidence": {
                "candidate_provider": "hand_challenger",
                "incumbent_provider": "hand_incumbent",
                "target_role": role,
                "one_command": "maskfactory providers rollback hand_finger_segmentation",
                "rollback_observed": True,
                "restore_observed": True,
                "result": "pass",
                "tested_at": "2026-07-16T01:00:00Z",
                "evidence_sha256": _sha("rollback"),
            },
        }
    )
    return packet, manifest


def _reseal(packet: dict) -> dict:
    packet["sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in packet.items() if key != "sha256"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return packet


def test_valid_specialist_packet_grants_no_role_or_gold_authority() -> None:
    packet, manifest = _valid_packet()
    result = validate_specialist_promotion_packet(packet, margin_manifest=manifest)
    assert result == {
        "candidate_key": "hand_challenger",
        "target_role": "hand_finger_segmentation",
        "lifecycle_state": "benchmarked",
        "rollback_provider": "hand_incumbent",
        "packet_sha256": packet["sha256"],
        "authority": "validated_prerequisites_only_no_role_or_gold_authority",
    }


def test_model_card_download_and_smoke_alone_cannot_promote() -> None:
    packet = {
        "candidate_key": "downloaded_smoke_passed_model_card_candidate",
        "downloaded": True,
        "smoke_passed": True,
        "model_card": "available",
    }
    with pytest.raises(SpecialistPromotionError, match="structure is invalid"):
        validate_specialist_promotion_packet(packet)


@pytest.mark.parametrize(
    "field",
    [
        "identity_hashes",
        "license_gate",
        "benchmark_results",
        "runtime_reliability",
        "rollback_evidence",
    ],
)
def test_missing_promotion_prerequisite_is_rejected(field: str) -> None:
    packet, manifest = _valid_packet()
    del packet[field]
    with pytest.raises(SpecialistPromotionError, match="structure is invalid"):
        validate_specialist_promotion_packet(packet, margin_manifest=manifest)


@pytest.mark.parametrize(
    "field",
    sorted(
        {
            "source_tree_sha256",
            "checkpoint_sha256",
            "runtime_lock_sha256",
            "license_evidence_sha256",
        }
    ),
)
def test_each_missing_identity_hash_is_rejected(field: str) -> None:
    packet, manifest = _valid_packet()
    del packet["identity_hashes"][field]
    _reseal(packet)
    with pytest.raises(SpecialistPromotionError, match="identity hashes are incomplete"):
        validate_specialist_promotion_packet(packet, margin_manifest=manifest)


def test_installed_but_unbenchmarked_candidate_is_rejected() -> None:
    packet, manifest = _valid_packet()
    packet["lifecycle_state"] = "installed"
    _reseal(packet)
    with pytest.raises(SpecialistPromotionError, match="benchmarked candidate"):
        validate_specialist_promotion_packet(packet, margin_manifest=manifest)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("license_gate", "verify_license"), True, "unresolved"),
        (("license_gate", "checkpoint_decision"), "unclear", "unresolved"),
        (("runtime_reliability", "deterministic"), False, "not reliable"),
        (("runtime_reliability", "oom_count"), 1, "not reliable"),
        (("runtime_reliability", "crash_count"), 1, "not reliable"),
        (
            ("runtime_reliability", "peak_reserved_bytes"),
            LOCAL_GPU_BUDGET_BYTES + 1,
            "exceeds the local 8 GB",
        ),
        (("rollback_evidence", "rollback_observed"), False, "did not pass"),
        (("rollback_evidence", "restore_observed"), False, "did not pass"),
        (("rollback_evidence", "result"), "fail", "did not pass"),
    ],
)
def test_failed_license_runtime_or_rollback_gate_is_rejected(
    path: tuple[str, str], value: object, message: str
) -> None:
    packet, manifest = _valid_packet()
    packet[path[0]][path[1]] = value
    _reseal(packet)
    with pytest.raises(SpecialistPromotionError, match=message):
        validate_specialist_promotion_packet(packet, margin_manifest=manifest)


def test_rollback_must_be_to_a_distinct_incumbent() -> None:
    packet, manifest = _valid_packet()
    packet["rollback_evidence"]["incumbent_provider"] = packet["candidate_key"]
    _reseal(packet)
    with pytest.raises(SpecialistPromotionError, match="did not pass"):
        validate_specialist_promotion_packet(packet, margin_manifest=manifest)


def test_hard_bucket_regression_is_rejected_even_with_primary_win() -> None:
    packet, manifest = _valid_packet()
    row = packet["benchmark_results"]["rows"][0]
    row["observed_delta"] = -float(row["noninferiority_margin"]) - 0.001
    row["passed"] = False
    _seal(packet["benchmark_results"])
    _reseal(packet)
    with pytest.raises(SpecialistPromotionError, match="non-inferiority failed"):
        validate_specialist_promotion_packet(packet, margin_manifest=manifest)


def test_approved_alternate_runtime_requires_kevin_and_exact_evidence() -> None:
    packet, manifest = _valid_packet()
    runtime = packet["runtime_reliability"]
    runtime["mode"] = "approved_alternate"
    runtime["peak_reserved_bytes"] = LOCAL_GPU_BUDGET_BYTES + 1
    runtime["alternate_runtime_approval"] = {
        "approved_by": "Kevin",
        "approved_at": "2026-07-16T00:30:00Z",
        "runtime_key": "remote_gpu_fixture",
        "reason": "Approved governed alternate for this exact specialist role.",
        "evidence_sha256": _sha("alternate-runtime"),
    }
    _reseal(packet)
    validate_specialist_promotion_packet(packet, margin_manifest=manifest)

    packet = copy.deepcopy(packet)
    packet["runtime_reliability"]["alternate_runtime_approval"]["approved_by"] = "AI"
    _reseal(packet)
    with pytest.raises(SpecialistPromotionError, match="approval is invalid"):
        validate_specialist_promotion_packet(packet, margin_manifest=manifest)


def test_packet_hash_tamper_is_rejected_last() -> None:
    packet, manifest = _valid_packet()
    packet["sha256"] = "0" * 64
    with pytest.raises(SpecialistPromotionError, match="packet hash mismatch"):
        validate_specialist_promotion_packet(packet, margin_manifest=manifest)
