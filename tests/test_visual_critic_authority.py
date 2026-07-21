from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from maskfactory.vlm.critic_authority import (
    CriticAuthorityError,
    certificate_sha256,
    evaluate_pass_quorum,
    validate_role_certificate,
)
from maskfactory.vlm.critic_catalog import canonical_sha256, load_catalog

NOW = datetime(2026, 7, 21, 22, 0, tzinfo=UTC)


def _promoted_catalog(*, same_family: bool = False) -> dict:
    catalog = deepcopy(load_catalog())
    assignments = (
        (0, "primary_visual_critic"),
        (2 if same_family else 3, "independent_juror"),
    )
    for index, role in assignments:
        model = catalog["models"][index]
        if role not in model["candidate_roles"]:
            model["candidate_roles"].append(role)
        model["lifecycle"] = "promoted"
        model["assigned_roles"] = [role]
        model["artifact_sha256"] = f"{index + 1:x}" * 64
        model["calibration"] = {"status": "pass", "report_sha256": f"{index + 5:x}" * 64}
        model["private_endpoint"] = f"http://127.0.0.1:{18100 + index}"
    catalog["sha256"] = canonical_sha256(
        {key: value for key, value in catalog.items() if key != "sha256"}
    )
    return catalog


def _certificate(catalog: dict, model_index: int, role: str) -> dict:
    model = catalog["models"][model_index]
    certificate = {
        "schema_version": "1.0.0",
        "certificate_id": f"cert-{model['model_id']}",
        "role_id": role,
        "model_id": model["model_id"],
        "family_id": model["family_id"],
        "catalog_sha256": catalog["sha256"],
        "revision": model["revision"],
        "artifact_sha256": model["artifact_sha256"],
        "calibration_report_sha256": model["calibration"]["report_sha256"],
        "prompt_sha256": "a" * 64,
        "runtime_sha256": "b" * 64,
        "issued_at": "2026-07-20T00:00:00Z",
        "qualified_until": "2026-08-20T00:00:00Z",
        "status": "pass",
    }
    certificate["certificate_sha256"] = certificate_sha256(certificate)
    return certificate


def test_current_exact_independent_quorum_is_eligible_and_hash_bound() -> None:
    catalog = _promoted_catalog()
    certificates = [
        _certificate(catalog, 0, "primary_visual_critic"),
        _certificate(catalog, 3, "independent_juror"),
    ]
    result = evaluate_pass_quorum(certificates, catalog, now=NOW, deterministic_hard_veto=False)
    assert result["status"] == "eligible"
    assert len(result["quorum_sha256"]) == 64


def test_deterministic_hard_veto_precedes_valid_critic_quorum() -> None:
    catalog = _promoted_catalog()
    result = evaluate_pass_quorum([], catalog, now=NOW, deterministic_hard_veto=True)
    assert result == {
        "status": "blocked",
        "reason": "deterministic_hard_veto",
        "catalog_sha256": catalog["sha256"],
    }


def test_same_family_variants_abstain_instead_of_forming_quorum() -> None:
    catalog = _promoted_catalog(same_family=True)
    result = evaluate_pass_quorum(
        [
            _certificate(catalog, 0, "primary_visual_critic"),
            _certificate(catalog, 2, "independent_juror"),
        ],
        catalog,
        now=NOW,
        deterministic_hard_veto=False,
    )
    assert result["status"] == "abstain"
    assert result["reason"] == "critic_families_not_independent"


def test_missing_role_abstains() -> None:
    catalog = _promoted_catalog()
    result = evaluate_pass_quorum(
        [_certificate(catalog, 0, "primary_visual_critic")],
        catalog,
        now=NOW,
        deterministic_hard_veto=False,
    )
    assert result["status"] == "abstain"
    assert result["reason"] == "required_role_quorum_unavailable"


def test_stale_certificate_is_rejected() -> None:
    catalog = _promoted_catalog()
    certificate = _certificate(catalog, 0, "primary_visual_critic")
    certificate["qualified_until"] = "2026-07-21T21:59:59Z"
    certificate["certificate_sha256"] = certificate_sha256(certificate)
    with pytest.raises(CriticAuthorityError, match="not currently qualified"):
        validate_role_certificate(certificate, catalog, now=NOW)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("model_id", "famous-model-name", "not cataloged"),
        ("catalog_sha256", "f" * 64, "catalog hash drifted"),
        ("artifact_sha256", "f" * 64, "promoted catalog evidence"),
        ("calibration_report_sha256", "f" * 64, "promoted catalog evidence"),
    ],
)
def test_name_or_evidence_drift_is_rejected(field: str, value: str, message: str) -> None:
    catalog = _promoted_catalog()
    certificate = _certificate(catalog, 0, "primary_visual_critic")
    certificate[field] = value
    certificate["certificate_sha256"] = certificate_sha256(certificate)
    with pytest.raises(CriticAuthorityError, match=message):
        validate_role_certificate(certificate, catalog, now=NOW)


def test_uncalibrated_or_unpromoted_catalog_cannot_validate_certificate() -> None:
    catalog = _promoted_catalog()
    certificate = _certificate(catalog, 0, "primary_visual_critic")
    catalog["models"][0]["lifecycle"] = "smoked"
    catalog["models"][0]["assigned_roles"] = []
    catalog["sha256"] = canonical_sha256(
        {key: value for key, value in catalog.items() if key != "sha256"}
    )
    certificate["catalog_sha256"] = catalog["sha256"]
    certificate["certificate_sha256"] = certificate_sha256(certificate)
    with pytest.raises(CriticAuthorityError, match="promoted catalog evidence"):
        validate_role_certificate(certificate, catalog, now=NOW)
