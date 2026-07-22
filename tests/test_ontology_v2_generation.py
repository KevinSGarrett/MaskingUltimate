from pathlib import Path

import pytest
import yaml

from maskfactory.ontology import load_ontology
from maskfactory.ontology_v2 import (
    OntologyV2Error,
    build_derived_v2,
    build_ontology_v2,
    build_viz_v2,
    generate_v2_artifacts,
    resolve_v2_alias,
    v2_artifacts_are_current,
)


def test_v2_generator_is_append_only_and_inactive() -> None:
    v1 = load_ontology(Path("configs/ontology.yaml"))
    document = build_ontology_v2()
    path = Path("configs/ontology_v2.yaml")
    v2 = load_ontology(path)

    assert document["activation_status"] == "approved_design_not_active"
    assert v2.version == "body_parts_v2"
    v1_parts = [(label.id, label.name) for label in v1.labels_for_map("part")]
    v2_parts = [(label.id, label.name) for label in v2.labels_for_map("part")]
    assert v2_parts[:56] == v1_parts
    assert [label_id for label_id, _ in v2_parts] == list(range(66))
    assert len(v2_parts) == 66
    assert document["visibility_state_aliases"] == {"fully_occluded": "occluded"}


def test_v2_boundary_swaps_derived_and_visualization_are_complete() -> None:
    ontology = build_ontology_v2()
    by_name = {label["name"]: label for label in ontology["labels"]}
    for name in (
        "left_areola",
        "right_areola",
        "left_nipple",
        "right_nipple",
        "vulva",
        "penis_shaft",
        "glans_penis",
        "left_scrotal_region",
        "right_scrotal_region",
        "anus",
    ):
        label = by_name[name]
        assert label["boundary_rule"] in ontology["boundary_rules"]
        assert label["visibility_default"] == "unreviewed_for_v2"
        if label["swap_partner"] is not None:
            assert by_name[label["swap_partner"]]["swap_partner"] == name

    derived = build_derived_v2()
    assert derived["activation_status"] == "approved_design_not_active"
    for required in (
        "both_areolae",
        "both_nipples",
        "left_breast_full",
        "right_breast_full",
        "external_genitalia_visible",
        "external_pelvic_anatomy_visible",
        "pelvic_anatomy_visible",
    ):
        assert required in derived["formulas"]
    assert "part_ids:56-65" in derived["formulas"]["full_body_parts_visible"]

    v1_viz = yaml.safe_load(Path("configs/viz.yaml").read_text(encoding="utf-8"))
    v2_viz = build_viz_v2()
    assert v2_viz["activation_status"] == "approved_design_not_active"
    assert set(v1_viz["label_colors"].items()) <= set(v2_viz["label_colors"].items())
    assert set(v2_viz["label_colors"]) == set(by_name)
    assert len(set(v2_viz["label_colors"].values())) == len(v2_viz["label_colors"])


def test_v2_aliases_return_canonical_provenance_and_never_become_labels() -> None:
    head = resolve_v2_alias("penis head")
    assert head.provenance() == {
        "requested": "penis head",
        "canonical": "glans_penis",
        "was_alias": True,
        "kind": "atomic",
        "warning": None,
    }
    testicle = resolve_v2_alias("left_testicle")
    assert testicle.canonical == "left_scrotal_region"
    assert testicle.warning == "external_scrotal_surface_not_internal_organ"
    assert resolve_v2_alias("asshole").canonical == "anus"
    assert resolve_v2_alias("left butt cheek").canonical == "left_glute"
    assert resolve_v2_alias("breasts").canonical == "both_breasts_full"
    canonical = resolve_v2_alias("both_nipples")
    assert canonical.canonical == "both_nipples"
    assert canonical.was_alias is False
    label_names = {label["name"] for label in build_ontology_v2()["labels"]}
    assert "penis head" not in label_names
    assert "left_testicle" not in label_names
    with pytest.raises(OntologyV2Error, match="unknown ontology-v2 selector"):
        resolve_v2_alias("invented_anatomy")


def test_v2_artifacts_generate_deterministically_and_detect_drift(tmp_path: Path) -> None:
    ontology = tmp_path / "ontology_v2.yaml"
    derived = tmp_path / "derived_v2.yaml"
    viz = tmp_path / "viz_v2.yaml"
    generate_v2_artifacts(ontology_path=ontology, derived_path=derived, viz_path=viz)
    assert v2_artifacts_are_current(ontology_path=ontology, derived_path=derived, viz_path=viz)
    ontology.write_text(ontology.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    assert not v2_artifacts_are_current(ontology_path=ontology, derived_path=derived, viz_path=viz)
