import copy
import json
from pathlib import Path

import numpy as np
import pytest

from maskfactory.anatomy_v2_drafting import NEW_LABELS
from maskfactory.anatomy_v2_qa import (
    QC_IDS,
    AnatomyV2QaError,
    AnatomyV2QaInputs,
    ClothedSweepCase,
    clothed_false_positive_sweep,
    load_anatomy_v2_qa_config,
    run_anatomy_v2_qc,
    write_anatomy_v2_qa_report,
)
from maskfactory.ontology import load_ontology
from maskfactory.ontology_v2 import DEFAULT_ONTOLOGY_V2, load_v2_proposal


def _good_inputs() -> AnatomyV2QaInputs:
    ontology = load_ontology(DEFAULT_ONTOLOGY_V2)
    ids = {
        label.name: int(label.id)
        for label in ontology.labels_for_map("part", enabled_only=True)
        if label.id is not None
    }
    shape = (64, 64)
    part = np.zeros(shape, dtype=np.uint16)

    left_breast = np.zeros(shape, dtype=bool)
    left_breast[8:28, 6:28] = True
    right_breast = np.zeros(shape, dtype=bool)
    right_breast[8:28, 36:58] = True
    pelvic = np.zeros(shape, dtype=bool)
    pelvic[34:61, 20:44] = True
    part[left_breast] = ids["left_breast"]
    part[right_breast] = ids["right_breast"]
    part[pelvic] = ids["pelvic_region"]

    left_areola = np.zeros(shape, dtype=bool)
    left_areola[14:22, 14:22] = True
    left_nipple = np.zeros(shape, dtype=bool)
    left_nipple[17:19, 17:19] = True
    left_areola &= ~left_nipple
    right_areola = np.zeros(shape, dtype=bool)
    right_areola[14:22, 42:50] = True
    right_nipple = np.zeros(shape, dtype=bool)
    right_nipple[17:19, 45:47] = True
    right_areola &= ~right_nipple
    shaft = np.zeros(shape, dtype=bool)
    shaft[40:50, 30:34] = True
    glans = np.zeros(shape, dtype=bool)
    glans[37:40, 30:34] = True
    left_scrotal = np.zeros(shape, dtype=bool)
    left_scrotal[50:57, 24:32] = True
    right_scrotal = np.zeros(shape, dtype=bool)
    right_scrotal[50:57, 32:40] = True
    positives = {
        "left_areola": left_areola,
        "right_areola": right_areola,
        "left_nipple": left_nipple,
        "right_nipple": right_nipple,
        "penis_shaft": shaft,
        "glans_penis": glans,
        "left_scrotal_region": left_scrotal,
        "right_scrotal_region": right_scrotal,
    }
    for name, mask in positives.items():
        part[mask] = ids[name]

    atomics = {name: part == label_id for name, label_id in ids.items()}
    derived = {
        "left_breast_full": (
            atomics["left_breast"] | atomics["left_areola"] | atomics["left_nipple"]
        ),
        "right_breast_full": (
            atomics["right_breast"] | atomics["right_areola"] | atomics["right_nipple"]
        ),
        "pelvic_anatomy_visible": np.logical_or.reduce(
            [
                atomics[name]
                for name in (
                    "pelvic_region",
                    "vulva",
                    "penis_shaft",
                    "glans_penis",
                    "left_scrotal_region",
                    "right_scrotal_region",
                )
            ]
        ),
    }
    parts = {
        name: {"visibility": "visible" if mask.any() else "not_visible"}
        for name, mask in atomics.items()
    }
    manifest = {
        "workflow_status": "approved_gold",
        "reviewed_ontology_version": "body_parts_v2",
        "source": {"source_origin": "owned_photo"},
        "parts": parts,
    }
    chest_roi = np.zeros(shape, dtype=bool)
    chest_roi[6:30, 4:60] = True
    pelvic_roi = np.zeros(shape, dtype=bool)
    pelvic_roi[32:63, 18:46] = True
    rois = {
        name: (chest_roi.copy() if name in NEW_LABELS[:4] else pelvic_roi.copy())
        for name in NEW_LABELS
    }
    provenance = {
        name: {
            "authority": "human_visible_review",
            "visible_surface_only": True,
        }
        for name in NEW_LABELS
    }
    return AnatomyV2QaInputs(
        manifest=manifest,
        part_map=part,
        material_map=np.ones(shape, dtype=np.uint8),
        atomic_masks=atomics,
        derived_masks=derived,
        ambiguity_masks={},
        review_rois=rois,
        label_provenance=provenance,
        midline_x=32,
        character_left_is_lower_x=True,
    )


def _clone(inputs: AnatomyV2QaInputs, **overrides) -> AnatomyV2QaInputs:
    values = {
        "manifest": copy.deepcopy(inputs.manifest),
        "part_map": inputs.part_map.copy(),
        "material_map": inputs.material_map.copy(),
        "atomic_masks": {name: mask.copy() for name, mask in inputs.atomic_masks.items()},
        "derived_masks": {name: mask.copy() for name, mask in inputs.derived_masks.items()},
        "ambiguity_masks": {name: mask.copy() for name, mask in inputs.ambiguity_masks.items()},
        "review_rois": {name: mask.copy() for name, mask in inputs.review_rois.items()},
        "label_provenance": copy.deepcopy(inputs.label_provenance),
        "projected_or_amodal_labels": frozenset(inputs.projected_or_amodal_labels),
        "midline_x": inputs.midline_x,
        "character_left_is_lower_x": inputs.character_left_is_lower_x,
    }
    values.update(overrides)
    return AnatomyV2QaInputs(**values)


def _seed_defect(inputs: AnatomyV2QaInputs, qc_id: str) -> AnatomyV2QaInputs:
    seeded = _clone(inputs)
    if qc_id == "QC-V2-001":
        seeded.manifest["reviewed_ontology_version"] = "body_parts_v1"
    elif qc_id == "QC-V2-002":
        seeded.manifest["parts"]["vulva"]["visibility"] = "visible"
    elif qc_id == "QC-V2-003":
        seeded.atomic_masks["vulva"][10:12, 10:12] = True
        seeded.manifest["parts"]["vulva"]["visibility"] = "visible"
        seeded.derived_masks["pelvic_anatomy_visible"] |= seeded.atomic_masks["vulva"]
    elif qc_id == "QC-V2-004":
        original = seeded.atomic_masks["left_nipple"].copy()
        nipple_id = int(seeded.part_map[original][0])
        breast_id = int(seeded.part_map[24, 24])
        seeded.atomic_masks["left_nipple"][:] = False
        seeded.atomic_masks["left_nipple"][24:26, 24:26] = True
        seeded.atomic_masks["left_breast"][original] = True
        seeded.atomic_masks["left_breast"][24:26, 24:26] = False
        seeded.part_map[original] = breast_id
        seeded.part_map[24:26, 24:26] = nipple_id
        seeded.derived_masks["left_breast_full"] = np.logical_or.reduce(
            [
                seeded.atomic_masks["left_breast"],
                seeded.atomic_masks["left_areola"],
                seeded.atomic_masks["left_nipple"],
            ]
        )
    elif qc_id == "QC-V2-005":
        seeded.derived_masks["left_breast_full"][:] = False
    elif qc_id == "QC-V2-006":
        seeded.derived_masks["pelvic_anatomy_visible"][:] = False
    elif qc_id == "QC-V2-007":
        original = seeded.atomic_masks["glans_penis"].copy()
        glans_id = int(seeded.part_map[original][0])
        pelvic_id = int(seeded.part_map[34, 40])
        seeded.atomic_masks["glans_penis"][:] = False
        seeded.atomic_masks["glans_penis"][34:37, 40:44] = True
        seeded.atomic_masks["pelvic_region"][original] = True
        seeded.atomic_masks["pelvic_region"][34:37, 40:44] = False
        seeded.part_map[original] = pelvic_id
        seeded.part_map[34:37, 40:44] = glans_id
        seeded.derived_masks["pelvic_anatomy_visible"] = np.logical_or.reduce(
            [
                seeded.atomic_masks[name]
                for name in (
                    "pelvic_region",
                    "vulva",
                    "penis_shaft",
                    "glans_penis",
                    "left_scrotal_region",
                    "right_scrotal_region",
                )
            ]
        )
    elif qc_id == "QC-V2-008":
        left = seeded.atomic_masks["left_scrotal_region"].copy()
        right = seeded.atomic_masks["right_scrotal_region"].copy()
        left_id = int(seeded.part_map[left][0])
        right_id = int(seeded.part_map[right][0])
        seeded.atomic_masks["left_scrotal_region"] = seeded.atomic_masks[
            "right_scrotal_region"
        ].copy()
        seeded.atomic_masks["right_scrotal_region"] = left
        seeded.part_map[left] = right_id
        seeded.part_map[right] = left_id
    elif qc_id == "QC-V2-009":
        seeded.manifest["parts"]["vulva"]["visibility"] = "occluded_by_clothing"
    elif qc_id == "QC-V2-010":
        seeded = _clone(seeded, projected_or_amodal_labels=frozenset({"left_areola"}))
    elif qc_id == "QC-V2-012":
        seeded.manifest["parts"]["vagina"] = {"visibility": "not_visible"}
    else:  # pragma: no cover - closed parameter list below
        raise AssertionError(qc_id)
    return seeded


def test_config_has_exact_checks_and_qa_only_canonical_vlm_vocabulary() -> None:
    config = load_anatomy_v2_qa_config()
    assert tuple(config["hard_checks"]) == QC_IDS
    assert tuple(config["vlm"]["canonical_anatomy_vocabulary"]) == NEW_LABELS
    assert config["vlm"]["role"] == "qa_only"
    assert config["vlm"]["may_author_masks"] is False
    assert config["vlm"]["may_approve_gold"] is False
    assert config["vlm"]["may_clear_blocks"] is False
    assert not set(load_v2_proposal()["aliases"]) & set(
        config["vlm"]["canonical_anatomy_vocabulary"]
    )
    assert "QC-V2-011" not in config["hard_checks"]


def test_good_seed_passes_all_active_checks_and_report_remains_non_authoritative(
    tmp_path: Path,
) -> None:
    results = run_anatomy_v2_qc(_good_inputs())
    assert tuple(result.qc_id for result in results) == QC_IDS
    assert all(result.passed for result in results)
    path = write_anatomy_v2_qa_report(
        tmp_path / "qa.json", results, clothed_sweep={"passed": True, "case_count": 1}
    )
    report = json.loads(path.read_text())
    assert report["overall"] == "pass" and report["authority"] == "qa_only"
    assert report["production_activation_granted"] is False
    assert report["may_author_masks"] is False and report["may_approve_gold"] is False


@pytest.mark.parametrize("qc_id", QC_IDS)
def test_each_seeded_defect_trips_exactly_its_named_v2_check(qc_id: str) -> None:
    results = run_anatomy_v2_qc(_seed_defect(_good_inputs(), qc_id))
    failed = [result.qc_id for result in results if not result.passed]
    assert failed == [qc_id], results


def test_clothed_false_positive_sweep_requires_zero_anatomy_in_reviewed_garments() -> None:
    shape = (32, 32)
    part = np.zeros(shape, dtype=np.uint16)
    material = np.zeros(shape, dtype=np.uint8)
    roi = np.zeros(shape, dtype=bool)
    roi[4:28, 6:26] = True
    material[roi] = 4
    clean = ClothedSweepCase("clean_clothed", part, material, roi)
    report = clothed_false_positive_sweep((clean,))
    assert report["passed"] is True and report["cases"][0]["false_positive_rate"] == 0

    defect = part.copy()
    defect[10:12, 10:12] = 56
    failed = clothed_false_positive_sweep(
        (ClothedSweepCase("false_positive", defect, material, roi),)
    )
    assert failed["passed"] is False
    assert failed["cases"][0]["anatomy_false_positive_pixels"] == 4

    with pytest.raises(AnatomyV2QaError, match="lacks reviewed garment pixels"):
        clothed_false_positive_sweep(
            (ClothedSweepCase("not_clothing", part, np.ones(shape, dtype=np.uint8), roi),)
        )
