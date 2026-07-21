from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from maskfactory.vlm.critic_authority import certificate_sha256
from maskfactory.vlm.critic_catalog import CriticCatalogError, canonical_sha256, load_catalog
from maskfactory.vlm.critic_routing import (
    arbitration_disagreement_sha256,
    resolve_bounded_arbiter_route,
)
from maskfactory.vlm.target_contract import target_contract_sha256

NOW = datetime(2026, 7, 21, 23, 0, tzinfo=UTC)


def _catalog(*, feasible_arbiter: bool = False) -> dict:
    catalog = deepcopy(load_catalog())
    assignments = ((5, "primary_visual_critic"), (3, "independent_juror"))
    if feasible_arbiter:
        catalog["models"][5]["candidate_roles"].append("senior_arbiter")
        assignments += ((5, "senior_arbiter"),)
    for index, role in assignments:
        model = catalog["models"][index]
        model["lifecycle"] = "promoted"
        if role not in model["assigned_roles"]:
            model["assigned_roles"].append(role)
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
        "certificate_id": f"cert-{model['model_id']}-{role}",
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


def _target() -> dict:
    contract = {
        "schema_version": "1.0.0",
        "contract_id": "arbiter-target",
        "source": {"image_id": "image-1", "sha256": "1" * 64, "width": 100, "height": 80},
        "owner": {
            "person_index": 0,
            "character_instance_id": "character-1",
            "person_mask_sha256": "2" * 64,
        },
        "target": {
            "label_id": "left_hand",
            "expected_presence": "visible_nonempty",
            "inclusion_rule": "visible_pixels_only",
            "exclusion_rule": "exclude_occluded_outside_owner_and_named_labels",
            "allowed_roi_xyxy": [10, 10, 90, 70],
            "minimum_area_pixels": 1,
            "maximum_area_pixels": 3000,
        },
        "excluded_labels": ["right_hand"],
        "protected_regions": [],
        "candidate": {
            "mask_sha256": "3" * 64,
            "width": 100,
            "height": 80,
            "binary_values": [0, 255],
        },
        "transforms": {
            "source_to_candidate": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "candidate_to_source": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        },
    }
    contract["contract_sha256"] = target_contract_sha256(contract)
    return contract


def _disagreement(target: dict, primary: dict, juror: dict) -> dict:
    value = {
        "schema_version": "1.0.0",
        "target_contract_sha256": target["contract_sha256"],
        "allowed_roi_xyxy": [20, 20, 40, 40],
        "primary_certificate_sha256": primary["certificate_sha256"],
        "juror_certificate_sha256": juror["certificate_sha256"],
        "primary_verdict": "pass",
        "juror_verdict": "defect",
    }
    value["disagreement_sha256"] = arbitration_disagreement_sha256(value)
    return value


def _inputs(*, feasible_arbiter: bool = False):
    catalog = _catalog(feasible_arbiter=feasible_arbiter)
    primary = _certificate(catalog, 5, "primary_visual_critic")
    juror = _certificate(catalog, 3, "independent_juror")
    arbiter = _certificate(catalog, 5, "senior_arbiter") if feasible_arbiter else None
    target = _target()
    return catalog, target, _disagreement(target, primary, juror), [primary, juror], arbiter


def test_current_infeasible_arbiter_abstains_without_invocation() -> None:
    catalog, target, disagreement, critics, _ = _inputs()
    result = resolve_bounded_arbiter_route(
        catalog, target, disagreement, critics, None, now=NOW, deterministic_hard_veto=False
    )
    assert result["status"] == "abstain"
    assert result["reason"] == "qualified_arbiter_certificate_unavailable"
    assert result["arbiter_invoked"] is False


def test_exact_qualified_bounded_disagreement_selects_hash_bound_arbiter() -> None:
    catalog, target, disagreement, critics, arbiter = _inputs(feasible_arbiter=True)
    result = resolve_bounded_arbiter_route(
        catalog, target, disagreement, critics, arbiter, now=NOW, deterministic_hard_veto=False
    )
    assert result["status"] == "selected"
    assert result["allowed_roi_xyxy"] == [20, 20, 40, 40]
    assert len(result["invocation_sha256"]) == 64


def test_hard_veto_prevents_arbiter_even_with_valid_certificates() -> None:
    catalog, target, disagreement, critics, arbiter = _inputs(feasible_arbiter=True)
    result = resolve_bounded_arbiter_route(
        catalog, target, disagreement, critics, arbiter, now=NOW, deterministic_hard_veto=True
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "deterministic_hard_veto"
    assert result["arbiter_invoked"] is False


def test_catalog_only_evidence_cannot_run_arbiter() -> None:
    catalog, target, disagreement, critics, _ = _inputs(feasible_arbiter=True)
    result = resolve_bounded_arbiter_route(
        catalog, target, disagreement, critics, None, now=NOW, deterministic_hard_veto=False
    )
    assert result["status"] == "abstain"
    assert result["reason"] == "qualified_arbiter_certificate_unavailable"


def test_no_actual_disagreement_does_not_invoke_arbiter() -> None:
    catalog, target, disagreement, critics, arbiter = _inputs(feasible_arbiter=True)
    disagreement["juror_verdict"] = "pass"
    disagreement["disagreement_sha256"] = arbitration_disagreement_sha256(disagreement)
    result = resolve_bounded_arbiter_route(
        catalog, target, disagreement, critics, arbiter, now=NOW, deterministic_hard_veto=False
    )
    assert result["status"] == "abstain"
    assert result["reason"] == "bounded_critic_disagreement_absent"


def test_scope_widening_or_certificate_drift_is_rejected() -> None:
    catalog, target, disagreement, critics, arbiter = _inputs(feasible_arbiter=True)
    disagreement["allowed_roi_xyxy"] = [0, 0, 100, 80]
    disagreement["disagreement_sha256"] = arbitration_disagreement_sha256(disagreement)
    with pytest.raises(CriticCatalogError, match="widens"):
        resolve_bounded_arbiter_route(
            catalog, target, disagreement, critics, arbiter, now=NOW, deterministic_hard_veto=False
        )

    disagreement = _disagreement(target, critics[0], critics[1])
    disagreement["primary_certificate_sha256"] = "f" * 64
    disagreement["disagreement_sha256"] = arbitration_disagreement_sha256(disagreement)
    with pytest.raises(CriticCatalogError, match="certificate binding drifted"):
        resolve_bounded_arbiter_route(
            catalog, target, disagreement, critics, arbiter, now=NOW, deterministic_hard_veto=False
        )
