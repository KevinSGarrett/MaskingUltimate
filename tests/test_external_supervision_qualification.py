import copy
import json
from pathlib import Path

import yaml

from maskfactory.external_supervision_qualification import (
    verify_external_qualification_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "configs" / "maskedwarehouse_inventory.json"
PROVENANCE = ROOT / "configs" / "maskedwarehouse_provenance.yaml"


def _load_inventory() -> dict:
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def _load_provenance() -> dict:
    return yaml.safe_load(PROVENANCE.read_text(encoding="utf-8"))


def test_admission_is_deterministic_with_complete_gate_set():
    provenance = _load_provenance()
    inventory = _load_inventory()

    required = set(provenance["sources"]["lv_mhp_v1"]["training_admission"]["required_gates"])
    decision_a = verify_external_qualification_evidence(
        provenance,
        inventory,
        source="lv_mhp_v1",
        completed_gates=required,
    )
    decision_b = verify_external_qualification_evidence(
        provenance,
        inventory,
        source="lv_mhp_v1",
        completed_gates=required,
    )

    assert decision_a == decision_b
    assert decision_a.admitted is True
    assert decision_a.unmet_gates == ()
    assert decision_a.evidence_tokens == ()


def test_missing_gate_fails_closed_with_unmet_gate():
    provenance = _load_provenance()
    inventory = _load_inventory()

    required = set(provenance["sources"]["lapa"]["training_admission"]["required_gates"])
    decision = verify_external_qualification_evidence(
        provenance,
        inventory,
        source="lapa",
        completed_gates=required - {"split_dedup_passed"},
    )

    assert decision.legally_eligible is True
    assert decision.technically_qualified is False
    assert decision.admitted is False
    assert decision.unmet_gates == ("split_dedup_passed",)


def test_unknown_source_fails_closed():
    decision = verify_external_qualification_evidence(
        _load_provenance(),
        _load_inventory(),
        source="not_a_real_source",
        completed_gates=set(),
    )

    assert decision.admitted is False
    assert "unknown_external_source" in decision.evidence_tokens


def test_registry_source_set_drift_fails_closed():
    provenance = _load_provenance()
    inventory = _load_inventory()

    inventory["sources"] = [source for source in inventory["sources"] if source["source"] != "lapa"]
    decision = verify_external_qualification_evidence(
        provenance,
        inventory,
        source="lv_mhp_v1",
        completed_gates=set(),
    )

    assert decision.admitted is False
    assert "source_set_drift_detected" in decision.evidence_tokens


def test_authority_drift_fails_closed():
    provenance = copy.deepcopy(_load_provenance())
    inventory = _load_inventory()

    provenance["sources"]["celebamask_hq"]["training_admission"]["holdout_eligible"] = True
    required = set(provenance["sources"]["celebamask_hq"]["training_admission"]["required_gates"])
    decision = verify_external_qualification_evidence(
        provenance,
        inventory,
        source="celebamask_hq",
        completed_gates=required,
    )

    assert decision.admitted is False
    assert "holdout_authority_drift" in decision.evidence_tokens


def test_blocked_source_never_becomes_eligible():
    decision = verify_external_qualification_evidence(
        _load_provenance(),
        _load_inventory(),
        source="swimsuit_preview",
        completed_gates={"compatible_derivative_and_training_rights"},
    )

    assert decision.legally_eligible is False
    assert decision.admitted is False
    assert "blocked_by_registry_status" in decision.evidence_tokens
