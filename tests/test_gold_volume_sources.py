"""Tests for read-when-present gold-volume tournament input selection."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from maskfactory.autonomy.gold_volume_sources import (
    GOLD_VOLUME_SOURCES_MAP_ID,
    GoldVolumeSourcesError,
    default_maskedwarehouse_lv_mhp_root,
    load_gold_volume_source_map,
    probe_gold_volume_sources,
    resolve_tournament_source_root,
    select_tournament_input_roots,
)

ROOT = Path(__file__).resolve().parents[1]
REAL_CONFIG = ROOT / "configs" / "gold_volume_sources.yaml"


def _write_config(tmp_path: Path, sources: dict, **extra) -> Path:
    document = {
        "schema_version": "1.0.0",
        "map_id": GOLD_VOLUME_SOURCES_MAP_ID,
        "claim_boundary": {
            "read_when_present_only": True,
            "never_junction_critical_runtime_to_usb": True,
            "never_relocate_data_models_docker_to_removable": True,
            "never_treat_external_labels_as_gold": True,
            "never_force_register_champion": True,
            "inputs_only": True,
        },
        "sources": sources,
        "dataset_hints": extra.get("dataset_hints", {}),
    }
    path = tmp_path / "gold_volume_sources.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_real_config_loads_and_is_honest() -> None:
    document = load_gold_volume_source_map(REAL_CONFIG)
    assert document["map_id"] == GOLD_VOLUME_SOURCES_MAP_ID
    assert document["claim_boundary"]["never_junction_critical_runtime_to_usb"] is True
    assert set(document["sources"]) >= {"maskedwarehouse", "reference_library", "daz"}


def test_selects_present_fixed_local_over_absent_usb(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse"
    (warehouse / "Body").mkdir(parents=True)
    usb = tmp_path / "usb_missing"
    config = _write_config(
        tmp_path,
        {
            "maskedwarehouse": {
                "role": "tournament_external_supervision_input",
                "description": "test",
                "required_child_any": ["Body", "CelebAMask-HQ"],
                "candidates": [
                    {"path": str(warehouse), "media": "fixed_local", "priority": 10},
                    {"path": str(usb), "media": "removable_usb", "priority": 20},
                ],
            }
        },
        dataset_hints={
            "maskedwarehouse": [{"relative": "Body", "use": "body"}],
        },
    )
    probe = probe_gold_volume_sources(config)
    assert probe.sources["maskedwarehouse"].present is True
    assert probe.sources["maskedwarehouse"].selected_root == warehouse
    assert probe.sources["maskedwarehouse"].selected_media == "fixed_local"
    assert probe.junction_critical_runtime_to_usb is False
    roots = select_tournament_input_roots(config)
    assert roots["maskedwarehouse"] == warehouse


def test_omits_absent_removable_roots_without_raising(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        {
            "daz": {
                "role": "tournament_synthetic_geometry_input",
                "description": "test",
                "required_child_any": ["00_control"],
                "candidates": [
                    {
                        "path": str(tmp_path / "no_such_daz"),
                        "media": "removable_usb",
                        "priority": 10,
                    }
                ],
            }
        },
    )
    roots = select_tournament_input_roots(config)
    assert roots == {}
    with pytest.raises(GoldVolumeSourcesError, match="missing"):
        select_tournament_input_roots(config, require_all=True)


def test_rejects_dishonest_claim_boundary(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        {
            "daz": {
                "role": "x",
                "description": "x",
                "required_child_any": [],
                "candidates": [{"path": str(tmp_path), "media": "fixed_local", "priority": 1}],
            }
        },
    )
    text = path.read_text(encoding="utf-8").replace(
        "never_junction_critical_runtime_to_usb: true",
        "never_junction_critical_runtime_to_usb: false",
    )
    path.write_text(text, encoding="utf-8")
    with pytest.raises(GoldVolumeSourcesError, match="claim_boundary"):
        load_gold_volume_source_map(path)


def test_resolve_relative_dataset_hint(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse"
    target = warehouse / "Body" / "LV-MHP-v1"
    target.mkdir(parents=True)
    config = _write_config(
        tmp_path,
        {
            "maskedwarehouse": {
                "role": "tournament_external_supervision_input",
                "description": "test",
                "required_child_any": ["Body"],
                "candidates": [{"path": str(warehouse), "media": "fixed_local", "priority": 10}],
            }
        },
    )
    assert (
        resolve_tournament_source_root(
            "maskedwarehouse", relative="Body/LV-MHP-v1", config_path=config
        )
        == target
    )
    assert default_maskedwarehouse_lv_mhp_root(config) == target
