from pathlib import Path

import pytest
import yaml

from maskfactory.external_supervision import (
    PRIVATE_NONCOMMERCIAL_PROFILE,
    ExternalSupervisionError,
    evaluate_training_admission,
    load_external_supervision_registry,
    validate_external_supervision_registry,
)

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "configs" / "maskedwarehouse_inventory.json"
PROVENANCE = ROOT / "configs" / "maskedwarehouse_provenance.yaml"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_every_inventory_source_has_provenance_entry():
    import json

    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    provenance = _load_yaml(PROVENANCE)

    inventory_sources = {source["source"] for source in inventory["sources"]}
    provenance_sources = set(provenance["sources"])

    assert provenance["policy"]["require_entry_for_every_inventory_source"] is True
    assert provenance_sources == inventory_sources


def test_machine_registry_validator_accepts_locked_private_noncommercial_profile():
    registry = load_external_supervision_registry(PROVENANCE, INVENTORY)
    assert registry["project_use_profile"]["id"] == PRIVATE_NONCOMMERCIAL_PROFILE
    assert registry["policy"]["maximum_combined_external_batch_fraction"] == 0.35


def test_all_provenance_entries_record_license_and_gates():
    provenance = _load_yaml(PROVENANCE)

    required = {
        "local_root",
        "inventory_counts",
        "role",
        "license_status",
        "license_terms_summary",
        "provenance_status",
        "allowed_uses",
        "prohibited_uses",
        "conversion_gate",
        "training_gate",
        "gold_gate",
        "source_role",
        "training_admission",
    }

    for source, entry in provenance["sources"].items():
        missing = required - set(entry)
        assert not missing, f"{source} missing {sorted(missing)}"
        assert entry["license_status"]
        assert entry["license_terms_summary"]
        assert entry["provenance_status"]
        assert str(entry["local_root"]).startswith("C:\\Comfy_UI_Main\\MaskedWarehouse")
        assert "gold_package_inputs" in entry["prohibited_uses"]
        assert entry["gold_gate"] == "blocked_external_source_masks_are_not_gold"


def test_known_noncommercial_sources_are_train_eligible_only_as_weighted_pseudo_labels():
    provenance = _load_yaml(PROVENANCE)

    for source in ("celebamask_hq", "lapa", "lv_mhp_v1"):
        entry = provenance["sources"][source]
        admission = entry["training_admission"]
        assert entry["training_gate"].startswith("permitted_private_noncommercial"), source
        assert entry["gold_gate"].startswith("blocked"), source
        assert admission["truth_tier"] == "weighted_pseudo_label"
        assert admission["truth_partition"] == "train"
        assert admission["holdout_eligible"] is False
        assert admission["dataset_volume_eligible"] is False
        assert 0.10 <= admission["training_loss_weight"] <= 0.25


def test_external_training_admission_fails_closed_until_every_qualification_gate_passes():
    registry = load_external_supervision_registry(PROVENANCE, INVENTORY)
    required = set(registry["sources"]["lv_mhp_v1"]["training_admission"]["required_gates"])
    pending = evaluate_training_admission(
        registry,
        "lv_mhp_v1",
        completed_gates=required - {"split_dedup_passed"},
    )
    assert pending.legally_eligible is True
    assert pending.technically_qualified is False
    assert pending.admitted is False
    assert pending.unmet_gates == ("split_dedup_passed",)

    admitted = evaluate_training_admission(registry, "lv_mhp_v1", completed_gates=required)
    assert admitted.admitted is True
    assert admitted.truth_tier == "weighted_pseudo_label"
    assert admitted.truth_partition == "train"
    assert admitted.training_loss_weight == 0.20


def test_use_profile_change_revokes_noncommercial_training_admission():
    registry = load_external_supervision_registry(PROVENANCE, INVENTORY)
    required = set(registry["sources"]["lapa"]["training_admission"]["required_gates"])
    decision = evaluate_training_admission(
        registry,
        "lapa",
        completed_gates=required,
        use_profile_id="commercial_or_distributed",
    )
    assert decision.admitted is False
    assert decision.truth_tier is None
    assert decision.unmet_gates == ("locked_use_profile",)


def test_unknown_or_no_derivatives_sources_cannot_enter_converted_fixtures():
    provenance = _load_yaml(PROVENANCE)

    for source in ("swimsuit_preview", "body_archive"):
        entry = provenance["sources"][source]
        assert entry["conversion_gate"].startswith("blocked")
        assert entry["training_gate"].startswith("blocked")
        assert entry["training_admission"]["status"] == "blocked"
        assert "converted_mask_fixtures" in entry["prohibited_uses"]


def test_registry_validator_rejects_gold_or_holdout_authority():
    import copy
    import json

    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    registry = copy.deepcopy(_load_yaml(PROVENANCE))
    registry["sources"]["lapa"]["training_admission"]["holdout_eligible"] = True
    with pytest.raises(ExternalSupervisionError, match="holdout_eligible"):
        validate_external_supervision_registry(registry, inventory)


def test_inventory_counts_match_provenance_counts():
    import json

    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    provenance = _load_yaml(PROVENANCE)

    for source in inventory["sources"]:
        counts = source["counts"]
        recorded = provenance["sources"][source["source"]]["inventory_counts"]
        assert recorded["images"] == counts["images"]
        assert recorded["masks"] == counts["masks"]
        assert recorded["metadata"] == counts["metadata"]
        assert recorded["total_files"] == counts["total_files"]
