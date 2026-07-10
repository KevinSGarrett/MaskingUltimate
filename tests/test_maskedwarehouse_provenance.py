from pathlib import Path

import yaml

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


def test_restricted_sources_are_not_approved_for_production_training_or_gold():
    provenance = _load_yaml(PROVENANCE)

    for source, entry in provenance["sources"].items():
        assert entry["training_gate"].startswith("blocked"), source
        assert entry["gold_gate"].startswith("blocked"), source
        assert (
            "production_model_training" in entry["prohibited_uses"]
            or "model_training" in entry["prohibited_uses"]
        )


def test_unknown_or_no_derivatives_sources_cannot_enter_converted_fixtures():
    provenance = _load_yaml(PROVENANCE)

    for source in ("swimsuit_preview", "body_archive"):
        entry = provenance["sources"][source]
        assert entry["conversion_gate"].startswith("blocked")
        assert "converted_mask_fixtures" in entry["prohibited_uses"]


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
