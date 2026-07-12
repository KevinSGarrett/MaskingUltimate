from dataclasses import replace

import numpy as np

from maskfactory.qa.semantic import SemanticInputs, run_semantic_qc


def _clean() -> SemanticInputs:
    shape = (100, 100)
    abdomen = np.zeros(shape, dtype=bool)
    abdomen[40:60, 40:60] = True  # 4% of bbox, ontology-valid
    silhouette = np.zeros(shape, dtype=bool)
    silhouette[30:70, 30:70] = True
    empty = np.zeros(shape, dtype=bool)
    return SemanticInputs(
        atomic_parts={"abdomen_stomach": abdomen},
        silhouette=silhouette,
        protected=empty,
        skin_derived=abdomen,
        clothing=empty,
        person_bbox_area=10_000,
        breast_skin=empty,
        material_skin=abdomen,
        projected_allowed_region=silhouette,
        source_gray=np.zeros(shape, dtype=np.float32),
    )


def _by_id(inputs: SemanticInputs):
    return {result.qc_id: result for result in run_semantic_qc(inputs)}


def test_clean_semantic_fixture_passes_qc011_through_qc024() -> None:
    results = run_semantic_qc(_clean())
    assert [result.qc_id for result in results] == [f"QC-{number:03d}" for number in range(11, 25)]
    assert all(result.passed for result in results), results
    assert {
        result.severity
        for result in results
        if result.qc_id in {"QC-011", "QC-013", "QC-014", "QC-016", "QC-018", "QC-019", "QC-020"}
    } == {"BLOCK"}


def test_qc011_017_detect_overlap_containment_votes_area_frame_and_components() -> None:
    base = _clean()
    abdomen = base.atomic_parts["abdomen_stomach"]
    overlap = _by_id(
        replace(base, atomic_parts={"abdomen_stomach": abdomen, "chest_upper_torso": abdomen})
    )
    assert not overlap["QC-011"].passed
    outside_mask = abdomen.copy()
    outside_mask[0:2, 0:2] = True
    assert not _by_id(replace(base, atomic_parts={"abdomen_stomach": outside_mask}))[
        "QC-012"
    ].passed
    assert not _by_id(replace(base, protected=abdomen))["QC-013"].passed
    protected_self = replace(
        base,
        atomic_parts={"other_person": abdomen},
        protected=abdomen,
        skin_derived=base.skin_derived & False,
        material_skin=base.material_skin & False,
    )
    assert _by_id(protected_self)["QC-013"].passed

    left = np.zeros_like(abdomen)
    left[40:50, 40:50] = True
    side = replace(base, atomic_parts={"left_forearm": left}, skin_derived=left, material_skin=left)
    assert not _by_id(side)["QC-014"].passed
    swapped = replace(
        side,
        side_votes={"left_forearm": ("right", "right", "left")},
    )
    assert not _by_id(swapped)["QC-014"].passed  # seeded L/R swap: 2-of-3 contradict label
    corrected = replace(
        side,
        side_votes={"left_forearm": ("left", "left", "right")},
    )
    assert _by_id(corrected)["QC-014"].passed
    tiny = np.zeros_like(abdomen)
    tiny[50, 50] = True
    assert not _by_id(replace(base, atomic_parts={"abdomen_stomach": tiny}))["QC-015"].passed
    assert not _by_id(replace(base, pose_absent_parts=frozenset({"abdomen_stomach"})))[
        "QC-016"
    ].passed
    split = np.zeros_like(abdomen)
    split[35:40, 35:40] = True
    split[50:55, 50:55] = True
    split[60:65, 60:65] = True
    assert not _by_id(replace(base, atomic_parts={"abdomen_stomach": split}))["QC-017"].passed


def test_qc018_024_detect_roundtrip_identity_projection_holes_edges_state_surface() -> None:
    base = _clean()
    abdomen = base.atomic_parts["abdomen_stomach"]
    shifted = np.roll(abdomen, 2, axis=1)
    assert not _by_id(replace(base, crop_roundtrips={"abdomen": (abdomen, shifted)}))[
        "QC-018"
    ].passed
    wrong_breast = np.zeros_like(abdomen)
    wrong_breast[0, 0] = True
    assert not _by_id(replace(base, breast_skin=wrong_breast))["QC-019"].passed
    projected = np.zeros_like(abdomen)
    projected[0, 0] = True
    assert not _by_id(replace(base, projected={"left_breast": projected}))["QC-020"].passed
    holed = abdomen.copy()
    holed[45:55, 45:55] = False
    assert not _by_id(replace(base, atomic_parts={"abdomen_stomach": holed}))["QC-021"].passed

    source = np.zeros_like(abdomen, dtype=np.float32)
    source[:, 62:] = 255  # strong edge two pixels outside right contour, inside ±3 band
    assert not _by_id(replace(base, source_gray=source))["QC-022"].passed
    assert not _by_id(
        replace(
            base,
            visibility_states={"abdomen_stomach": "visible"},
            amodal_areas={"abdomen_stomach": 1000},
        )
    )["QC-023"].passed
    assert not _by_id(replace(base, densepose_front_fraction={"abdomen_stomach": 0.1}))[
        "QC-024"
    ].passed
