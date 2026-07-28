from maskfactory.ontology_source import (
    BOUNDARY_RULES,
    DERIVED_FORMULAS,
    DERIVED_UNIONS,
    MATERIAL_LABELS,
    PART_LABELS,
    PROJECTED_REGISTRY,
    PROTECTED_CLASSES,
    REGION_BANDS,
)


def test_part_and_material_tables_are_complete_unique_and_stable() -> None:
    assert [label.id for label in PART_LABELS] == list(range(56))
    assert len({label.name for label in PART_LABELS}) == 56
    assert [label.id for label in MATERIAL_LABELS] == list(range(16))
    assert len({label.name for label in MATERIAL_LABELS}) == 16
    assert PART_LABELS[54].name == "left_ear" and PART_LABELS[54].enabled is False
    assert PART_LABELS[55].name == "right_ear" and PART_LABELS[55].enabled is False


def test_sided_labels_have_reciprocal_swap_partners() -> None:
    by_name = {label.name: label for label in PART_LABELS}
    for label in PART_LABELS:
        if label.side in {"left", "right"}:
            assert label.swap_partner in by_name
            assert by_name[label.swap_partner].swap_partner == label.name


def test_every_atomic_has_qc_area_components_and_boundary_metadata() -> None:
    for label in PART_LABELS:
        if label.mask_type == "atomic_exclusive":
            assert label.expected_area_pct_range is not None
            assert label.expected_area_pct_range[0] <= label.expected_area_pct_range[1]
            assert label.max_components is not None and label.max_components >= 1
            assert label.boundary_rule in BOUNDARY_RULES
    by_name = {label.name: label for label in PART_LABELS}
    assert by_name["left_forearm"].expected_area_pct_range == (0.8, 4.0)
    assert by_name["left_index_finger"].expected_area_pct_range == (0.02, 0.5)
    assert by_name["left_thigh"].expected_area_pct_range == (3.0, 12.0)


def test_all_secondary_doc02_registries_are_encoded() -> None:
    assert PROTECTED_CLASSES == (
        "other_person",
        "occluding_object",
        "support_surface",
        "accessory_or_prop",
    )
    region_names = {entry["name"] for entry in REGION_BANDS}
    assert "body_contact_region" in region_names
    assert "interperson_contact_boundary" in region_names
    assert len(region_names) == len(REGION_BANDS)
    assert len(DERIVED_UNIONS) == 40
    assert len(set(DERIVED_UNIONS)) == len(DERIVED_UNIONS)
    assert set(DERIVED_FORMULAS) == set(DERIVED_UNIONS)
    assert all(DERIVED_FORMULAS.values())
    projected = {entry["name"] for entry in PROJECTED_REGISTRY}
    assert {
        "left_breast_projected_region",
        "right_breast_projected_region",
        "amodal_<part>",
        "inpaint_<part>_d<k>f<f>",
    } <= projected
