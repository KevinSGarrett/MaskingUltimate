from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from tools.build_seeded_defect_controls import materialize

from maskfactory.vlm.calibration_corpus import DEFECT_TYPES
from maskfactory.vlm.seeded_defect_controls import (
    SeededDefectControlError,
    build_seeded_defect_controls,
    mask_sha256,
)


def _positive() -> np.ndarray:
    mask = np.zeros((16, 16), dtype=np.uint8)
    mask[5:11, 5:11] = 255
    return mask


def _resources() -> dict[str, np.ndarray]:
    masks = {}
    for name, coordinates in {
        "neighbor_mask": (1, 1),
        "wrong_label_mask": (1, 8),
        "opposite_side_mask": (8, 1),
        "other_owner_mask": (11, 1),
        "protected_region_mask": (11, 11),
    }.items():
        value = np.zeros((16, 16), dtype=np.uint8)
        y, x = coordinates
        value[y : y + 3, x : x + 3] = 255
        masks[name] = value
    return masks


def _record() -> dict[str, str]:
    positive = _positive()
    return {
        "record_id": "admitted-hair-control-001",
        "label_id": "hair",
        "partition": "calibration",
        "control_authority": "calibration_only",
        "admission_sha256": "a" * 64,
        "positive_mask_sha256": mask_sha256(positive),
    }


def test_full_hash_bound_taxonomy_is_calibration_only_and_deterministic() -> None:
    first = build_seeded_defect_controls(
        record=_record(), positive_mask=_positive(), resources=_resources()
    )
    second = build_seeded_defect_controls(
        record=_record(), positive_mask=_positive(), resources=_resources()
    )
    manifest = first["manifest"]
    assert {row["defect_type"] for row in manifest["negatives"]} == set(DEFECT_TYPES)
    assert all(row["changed_pixel_count"] > 0 for row in manifest["negatives"])
    assert manifest["manifest_sha256"] == second["manifest"]["manifest_sha256"]
    assert manifest["authority_claimed"] is False
    assert manifest["gold_or_training_truth_allowed"] is False
    assert manifest["certificate_issuance_allowed"] is False


def test_unadmitted_positive_and_missing_operator_context_fail_closed() -> None:
    record = _record()
    record["control_authority"] = "external_labeled_reference"
    with pytest.raises(SeededDefectControlError, match="calibration-only"):
        build_seeded_defect_controls(
            record=record, positive_mask=_positive(), resources=_resources()
        )
    resources = _resources()
    del resources["other_owner_mask"]
    with pytest.raises(SeededDefectControlError, match="owner_swap requires"):
        build_seeded_defect_controls(
            record=_record(), positive_mask=_positive(), resources=resources
        )


def test_input_mask_hash_drift_is_rejected_before_any_negative_is_emitted() -> None:
    record = deepcopy(_record())
    record["positive_mask_sha256"] = "b" * 64
    with pytest.raises(SeededDefectControlError, match="hash drifted"):
        build_seeded_defect_controls(
            record=record, positive_mask=_positive(), resources=_resources()
        )


def test_materializer_writes_all_hash_bound_pngs_with_no_authority_uplift(tmp_path: Path) -> None:
    root = tmp_path / "input"
    root.mkdir()
    positive = _positive()
    Image.fromarray(positive, mode="L").save(root / "positive.png")
    resource_paths = {}
    for key, mask in _resources().items():
        filename = f"{key}.png"
        Image.fromarray(mask, mode="L").save(root / filename)
        resource_paths[key] = filename
    manifest = materialize(
        input_value={
            "record": _record(),
            "positive_mask_path": "positive.png",
            "resources": resource_paths,
        },
        input_root=root,
        output_dir=tmp_path / "output",
    )
    assert len(manifest["files"]) == len(DEFECT_TYPES)
    assert all((tmp_path / "output" / row["path"]).is_file() for row in manifest["files"])
    assert manifest["gold_or_training_truth_allowed"] is False
    assert json.loads((tmp_path / "output" / "manifest.json").read_text())["materialization_sha256"]
