from pathlib import Path

import pytest
import yaml

from maskfactory import ontology as ontology_module
from maskfactory.models import ontology_contract
from maskfactory.ontology import OntologyError, get_ontology, load_ontology


def test_canonical_loader_resolves_names_ids_and_maps() -> None:
    ontology = get_ontology()
    assert ontology.version == "body_parts_v1"
    assert ontology.label("left_forearm").id == 18
    assert ontology.label_for_id("part", 18).name == "left_forearm"
    assert len(ontology.labels_for_map("part")) == 56
    assert len(ontology.labels_for_map("material")) == 16


def test_unknown_disabled_and_unknown_map_references_hard_fail() -> None:
    ontology = get_ontology()
    with pytest.raises(OntologyError, match="unknown ontology label"):
        ontology.label("not_a_real_label")
    with pytest.raises(OntologyError, match="disabled"):
        ontology.label("left_ear", require_enabled=True)
    with pytest.raises(OntologyError, match="unknown ontology map/id"):
        ontology.label_for_id("part", 999)
    with pytest.raises(OntologyError, match="unknown or empty"):
        ontology.labels_for_map("not_a_map")


def test_canonical_singleton_does_not_require_repository_config_at_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An installed wheel must not need ``<venv>/Lib/configs/ontology.yaml``."""

    get_ontology.cache_clear()
    monkeypatch.setattr(ontology_module, "DEFAULT_OUTPUT", tmp_path / "missing.yaml")
    try:
        ontology = get_ontology()
        assert ontology.version == "body_parts_v1"
        assert ontology.label("left_forearm").id == 18
    finally:
        get_ontology.cache_clear()


def test_v2_ontology_is_lazy_but_missing_v2_config_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CLI discovery must not load v2; an actual v2 request still must."""

    ontology_contract._v2_ontology.cache_clear()
    monkeypatch.setattr(ontology_contract, "DEFAULT_ONTOLOGY_V2", tmp_path / "missing-v2.yaml")
    try:
        assert ontology_contract.V1_PART_CLASS_NAMES[18] == "left_forearm"
        with pytest.raises(OntologyError, match="cannot load ontology"):
            ontology_contract.ontology_for_version("body_parts_v2")
    finally:
        ontology_contract._v2_ontology.cache_clear()


def test_loader_rejects_duplicate_names_and_unknown_swap_partner(tmp_path: Path) -> None:
    source = Path("configs/ontology.yaml")
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    document["labels"][1]["name"] = document["labels"][0]["name"]
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(OntologyError, match="duplicate label name"):
        load_ontology(duplicate)

    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    document["labels"][12]["swap_partner"] = "missing_right_label"
    invalid_swap = tmp_path / "invalid-swap.yaml"
    invalid_swap.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(OntologyError, match="unknown swap_partner"):
        load_ontology(invalid_swap)
