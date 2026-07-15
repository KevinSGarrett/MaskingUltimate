from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import maskfactory.ontology_v2_activation as activation_module
from maskfactory.derive import compute_derivations
from maskfactory.io.png_strict import write_label_map
from maskfactory.ontology import load_ontology
from maskfactory.ontology_v2_activation import (
    REQUIRED_V2_DERIVED,
    OntologyV2ActivationError,
    rehearse_v2_authority_pair,
    render_active_v2_authority_pair,
    validate_v2_authority_pair,
)


def test_inactive_and_activation_ready_pairs_are_exact_and_complete() -> None:
    inactive_ontology = Path("configs/ontology_v2.yaml").read_bytes()
    inactive_derived = Path("configs/derived_v2.yaml").read_bytes()
    inactive = validate_v2_authority_pair(
        inactive_ontology,
        inactive_derived,
        expected_status="approved_design_not_active",
    )
    active_ontology, active_derived = render_active_v2_authority_pair()
    active = validate_v2_authority_pair(active_ontology, active_derived, expected_status="active")
    assert inactive["part_class_count"] == active["part_class_count"] == 65
    assert inactive["formula_count"] == active["formula_count"] == 52
    assert inactive["required_v2_formula_count"] == len(REQUIRED_V2_DERIVED) == 12
    assert inactive["ontology_sha256"] != active["ontology_sha256"]
    assert inactive["derived_sha256"] != active["derived_sha256"]


def test_every_v2_formula_executes_and_visible_silhouette_includes_new_atomics(
    tmp_path: Path,
) -> None:
    package = tmp_path / "package"
    part = np.arange(65, dtype=np.uint16)[None, :]
    material = np.ones(part.shape, dtype=np.uint8)
    write_label_map(package / "label_map_part.png", part, bits=16)
    write_label_map(package / "label_map_material.png", material, bits=8)
    ontology = load_ontology(Path("configs/ontology_v2.yaml"))
    masks, formulas, _ = compute_derivations(
        package,
        config_path=Path("configs/derived_v2.yaml"),
        ontology=ontology,
    )
    assert len(masks) == len(formulas) == 52
    expected_visible_ids = set(range(1, 50)) | set(range(54, 65))
    person_visible = masks["person_full_visible"][0]
    full_body = masks["full_body_parts_visible"][0]
    assert {index for index, value in enumerate(person_visible) if value} == expected_visible_ids
    assert {index for index, value in enumerate(full_body) if value} == expected_visible_ids
    assert np.array_equal(masks["both_areolae"], np.isin(part, (56, 57)))
    assert np.array_equal(masks["both_nipples"], np.isin(part, (58, 59)))
    assert np.array_equal(masks["left_breast_full"], np.isin(part, (5, 56, 58)))
    assert np.array_equal(masks["right_breast_full"], np.isin(part, (6, 57, 59)))
    assert np.array_equal(masks["penis_visible"], np.isin(part, (61, 62)))
    assert np.array_equal(masks["scrotum_visible"], np.isin(part, (63, 64)))
    assert np.array_equal(masks["external_genitalia_visible"], np.isin(part, (60, 61, 62, 63, 64)))
    assert np.array_equal(masks["pelvic_anatomy_visible"], np.isin(part, (9, 60, 61, 62, 63, 64)))


def test_active_v1_silhouette_behavior_remains_legacy_until_activation(tmp_path: Path) -> None:
    package = tmp_path / "package"
    part = np.array([[1, 49, 54, 55]], dtype=np.uint16)
    material = np.ones(part.shape, dtype=np.uint8)
    write_label_map(package / "label_map_part.png", part, bits=16)
    write_label_map(package / "label_map_material.png", material, bits=8)
    ontology = load_ontology(Path("configs/ontology.yaml"))
    masks, _, _ = compute_derivations(
        package,
        config_path=Path("configs/derived.yaml"),
        ontology=ontology,
    )
    assert masks["person_full_visible"].tolist() == [[True, True, False, False]]


def test_rehearsal_switches_pair_and_restores_seeded_partial_failure_without_activation() -> None:
    ontology = Path("configs/ontology.yaml")
    derived = Path("configs/derived.yaml")
    before = {ontology: ontology.read_bytes(), derived: derived.read_bytes()}
    report = rehearse_v2_authority_pair()
    assert report["mode"] == "isolated_copy_no_production_activation"
    assert report["active_ontology_preserved"] == "body_parts_v1"
    assert report["production_activation_performed"] is False
    assert report["inactive_drift_check"] == "pass"
    assert report["successful_pair_switch"]["active"]["part_class_count"] == 65
    assert report["seeded_second_file_failure_restored_v1"] is True
    assert report["source_unchanged"] is True
    assert len(report["sha256"]) == 64
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("artifact", ["ontology", "derived"])
def test_rehearsal_refuses_inactive_generator_drift(tmp_path: Path, artifact: str) -> None:
    ontology = tmp_path / "ontology_v2.yaml"
    derived = tmp_path / "derived_v2.yaml"
    ontology.write_bytes(Path("configs/ontology_v2.yaml").read_bytes())
    derived.write_bytes(Path("configs/derived_v2.yaml").read_bytes())
    target = ontology if artifact == "ontology" else derived
    target.write_bytes(target.read_bytes() + b"# seeded drift\n")
    with pytest.raises(OntologyV2ActivationError, match="generator drift"):
        rehearse_v2_authority_pair(
            inactive_ontology=ontology,
            inactive_derived=derived,
        )


def test_pair_validator_rejects_required_formula_semantic_drift() -> None:
    ontology = Path("configs/ontology_v2.yaml").read_bytes()
    derived = (
        Path("configs/derived_v2.yaml")
        .read_bytes()
        .replace(
            b"part:left_areola | part:right_areola",
            b"part:left_areola | part:left_areola ",
            1,
        )
    )
    with pytest.raises(OntologyV2ActivationError, match="required formula drifted"):
        validate_v2_authority_pair(
            ontology,
            derived,
            expected_status="approved_design_not_active",
        )


def test_post_replace_validation_failure_restores_exact_v1_pair(tmp_path: Path) -> None:
    ontology = tmp_path / "ontology.yaml"
    derived = tmp_path / "derived.yaml"
    ontology.write_bytes(Path("configs/ontology.yaml").read_bytes())
    derived.write_bytes(Path("configs/derived.yaml").read_bytes())
    originals = {ontology: ontology.read_bytes(), derived: derived.read_bytes()}
    active_ontology, active_derived = render_active_v2_authority_pair()

    def corrupt_second(source: Path, destination: Path) -> None:
        source.replace(destination)
        if destination.name == "derived.yaml":
            destination.write_bytes(destination.read_bytes() + b"activation_status: corrupted\n")

    with pytest.raises(OntologyV2ActivationError, match="exact v1 pair restored"):
        activation_module._switch_pair_failure_atomic(
            ontology,
            derived,
            active_ontology,
            active_derived,
            replace=corrupt_second,
        )
    assert {path: path.read_bytes() for path in originals} == originals
