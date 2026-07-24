"""Tests for the fail-closed Serverless protocol-V3 runtime gate."""

from __future__ import annotations

import pytest

from maskfactory.autonomy.serverless_v3_runtime_gate import (
    ServerlessV3RuntimeGateError,
    build_serverless_v3_runtime_gate,
    canonical_sha256,
)


EXPECTED = {
    "deferred_queue": "a" * 64,
    "execution": "b" * 64,
    "registry": "c" * 64,
    "runner": "d" * 64,
}


def _preflight(bindings: dict[str, str | None], modules: dict[str, dict[str, object]]):
    document: dict[str, object] = {
        "schema_version": "maskfactory.serverless_v3_runtime_preflight.v1",
        "artifact_type": "maskfactory_serverless_gpu_runtime_preflight",
        "authority_claimed": False,
        "critic_role_authority_granted": False,
        "visual_acceptance_claimed": False,
        "gold_or_training_authority_granted": False,
        "cuda_available": True,
        "modules": modules,
        "v3_input_sha256s": bindings,
    }
    document["self_sha256"] = canonical_sha256(document)
    return document


def test_allows_fully_bound_and_provisioned_runtime() -> None:
    ready = _preflight(
        EXPECTED,
        {name: {"available": True} for name in ("torch", "transformers", "vllm")},
    )

    gate = build_serverless_v3_runtime_gate(
        preflight=ready,
        expected_input_sha256s=EXPECTED,
        provider_binding_sha256s=EXPECTED,
    )

    assert gate["v3_submission_allowed"] is True
    assert gate["reason_codes"] == []


def test_denies_missing_modules_and_internal_binding_gap() -> None:
    unavailable = _preflight(
        {name: None for name in EXPECTED},
        {
            "torch": {"available": True},
            "transformers": {"available": False, "import_error": "missing"},
            "vllm": {"available": False, "import_error": "missing"},
        },
    )

    gate = build_serverless_v3_runtime_gate(
        preflight=unavailable,
        expected_input_sha256s=EXPECTED,
        provider_binding_sha256s=EXPECTED,
    )

    assert gate["v3_submission_allowed"] is False
    assert gate["missing_required_modules"] == ["transformers", "vllm"]
    assert gate["reason_codes"] == [
        "preflight_internal_binding_report_incomplete",
        "required_runtime_modules_unavailable",
    ]


def test_rejects_provider_binding_drift() -> None:
    ready = _preflight(
        EXPECTED,
        {name: {"available": True} for name in ("torch", "transformers", "vllm")},
    )
    drifted = dict(EXPECTED)
    drifted["runner"] = "e" * 64

    with pytest.raises(ServerlessV3RuntimeGateError, match="provider binding receipt"):
        build_serverless_v3_runtime_gate(
            preflight=ready,
            expected_input_sha256s=EXPECTED,
            provider_binding_sha256s=drifted,
        )
