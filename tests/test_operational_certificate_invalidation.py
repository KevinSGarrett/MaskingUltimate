from __future__ import annotations

import base64
import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from maskfactory.authority import evaluate_operational_certificate_at_use
from maskfactory.validation import canonical_json_bytes
from test_operational_certificate_issuance import _issue, _prepare


def _state(
    certificate: dict,
    *,
    revocations: list[dict] | None = None,
    provider_lifecycle: str = "promoted",
    binding_overrides: dict[str, str] | None = None,
    observed_at: str = "2026-07-17T00:00:05Z",
) -> tuple[dict, dict]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    state = {
        "schema_version": "1.0.0",
        "record_type": "operational_authority_current_state",
        "observed_at": observed_at,
        "current_bindings": {
            "pipeline_sha256": certificate["pipeline_policy_binding"]["pipeline_sha256"],
            "policy_sha256": certificate["pipeline_policy_binding"]["policy_sha256"],
            "ontology_sha256": certificate["ontology_binding"]["sha256"],
            "execution_fingerprint_sha256": certificate["execution_binding"][
                "execution_fingerprint_sha256"
            ],
            "provider_stack_sha256": certificate["execution_binding"]["provider_stack_sha256"],
            "provider_lifecycle": provider_lifecycle,
        },
        "revocations": revocations or [],
    }
    state["current_bindings"].update(binding_overrides or {})
    signature = private.sign(canonical_json_bytes(state))
    state["signature"] = {
        "key_id": "runtime-state-authority",
        "value_base64": base64.b64encode(signature).decode("ascii"),
    }
    trusted = {
        "runtime-state-authority": {
            "status": "active",
            "public_key_base64": base64.b64encode(public).decode("ascii"),
        }
    }
    return state, trusted


def _decision(
    certificate: dict,
    state: dict,
    state_keys: dict,
    certificate_keys: dict,
    use_time: str = "2026-07-17T00:00:05Z",
) -> dict:
    return evaluate_operational_certificate_at_use(
        certificate,
        current_state=state,
        trusted_state_keys=state_keys,
        trusted_certificate_keys=certificate_keys,
        use_time=use_time,
    )


def test_at_use_invalidation_preserves_historical_certificate_and_unrelated_scope(
    tmp_path: Path,
) -> None:
    prepared = _prepare(tmp_path)
    certificate = _issue(prepared)
    historical = copy.deepcopy(certificate)
    state, state_keys = _state(
        certificate,
        revocations=[
            {
                "certificate_id": "mfac_" + "0" * 24,
                "certificate_payload_sha256": "0" * 64,
                "status": "revoked",
            }
        ],
    )

    decision = _decision(certificate, state, state_keys, prepared["trusted"])

    assert decision["status"] == "allow"
    assert certificate == historical


def test_at_use_concurrently_rejects_exact_revocation_and_dependency_drift(tmp_path: Path) -> None:
    prepared = _prepare(tmp_path)
    certificate = _issue(prepared)
    revoked_state, state_keys = _state(
        certificate,
        revocations=[
            {
                "certificate_id": certificate["certificate_id"],
                "certificate_payload_sha256": certificate["certificate_payload_sha256"],
                "status": "revoked",
            }
        ],
    )
    drifted_state, drifted_state_keys = _state(certificate, provider_lifecycle="disabled")
    decisions = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(_decision, certificate, revoked_state, state_keys, prepared["trusted"])
            for _ in range(16)
        ]
        decisions = [future.result() for future in futures]

    assert {decision["status"] for decision in decisions} == {"reject"}
    assert all("certificate_revoked" in decision["reasons"] for decision in decisions)
    assert certificate["status"] == "active"
    drifted = _decision(certificate, drifted_state, drifted_state_keys, prepared["trusted"])
    assert "provider_lifecycle_drift" in drifted["reasons"]


@pytest.mark.parametrize(
    ("binding", "reason"),
    [
        ("pipeline_sha256", "pipeline_sha256_drift"),
        ("policy_sha256", "policy_sha256_drift"),
        ("ontology_sha256", "ontology_sha256_drift"),
        ("execution_fingerprint_sha256", "execution_fingerprint_sha256_drift"),
        ("provider_stack_sha256", "provider_stack_sha256_drift"),
    ],
)
def test_at_use_rejects_each_exact_binding_drift(tmp_path: Path, binding: str, reason: str) -> None:
    prepared = _prepare(tmp_path)
    certificate = _issue(prepared)
    state, state_keys = _state(certificate, binding_overrides={binding: "f" * 64})

    decision = _decision(certificate, state, state_keys, prepared["trusted"])

    assert decision["status"] == "reject"
    assert reason in decision["reasons"]


def test_at_use_rejects_expiry_without_rewriting_historical_evidence(tmp_path: Path) -> None:
    prepared = _prepare(tmp_path)
    certificate = _issue(prepared)
    historical = copy.deepcopy(certificate)
    use_time = "2026-07-18T00:00:04Z"
    state, state_keys = _state(certificate, observed_at=use_time)

    decision = _decision(certificate, state, state_keys, prepared["trusted"], use_time)

    assert decision["status"] == "reject"
    assert "certificate_certificate_use_time" in decision["reasons"]
    assert certificate == historical
