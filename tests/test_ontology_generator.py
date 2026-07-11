from pathlib import Path

import yaml

from maskfactory.ontology_generator import (
    build_ontology,
    generate_ontology,
    ontology_is_current,
    render_ontology,
)

REQUIRED_FIELDS = {
    "id",
    "name",
    "mask_type",
    "map",
    "side",
    "parent_union",
    "enabled",
    "expected_area_pct_range",
    "max_components",
    "exclusivity_group",
    "swap_partner",
    "visibility_default",
}


def test_generator_emits_every_required_field_and_registry() -> None:
    document = build_ontology()
    labels = document["labels"]
    assert len(labels) == 135
    assert all(REQUIRED_FIELDS <= set(label) for label in labels)
    assert len({label["name"] for label in labels}) == len(labels)
    assert document["mask_ontology_version"] == "body_parts_v1"
    assert document["left_right_convention"] == "character_perspective"
    assert document["protected_classes"] == [
        "other_person",
        "occluding_object",
        "support_surface",
        "accessory_or_prop",
    ]


def test_generator_output_is_deterministic_roundtrip_and_drift_detectable(tmp_path: Path) -> None:
    output = tmp_path / "ontology.yaml"
    generate_ontology(output)
    assert ontology_is_current(output)
    assert yaml.safe_load(output.read_text(encoding="utf-8")) == build_ontology()
    assert output.read_text(encoding="utf-8") == render_ontology()
    output.write_text(output.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    assert not ontology_is_current(output)
