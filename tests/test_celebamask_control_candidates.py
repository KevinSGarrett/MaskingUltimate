from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

from maskfactory.vlm.celebamask_control_candidates import (
    CelebAMaskControlCandidateError,
    build_celebamask_control_candidates,
    verify_celebamask_control_candidates,
)
from maskfactory.vlm.critic_catalog import canonical_sha256


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "CelebAMask-HQ"
    provenance = {
        "policy": {"source_masks_are_gold": False},
        "sources": {
            "celebamask_hq": {
                "official_source_url": "https://example.invalid/source",
                "license_status": "recorded_restricted_non_commercial",
                "allowed_uses": [
                    "private_noncommercial_semantic_critic_calibration_after_qualification"
                ],
                "training_admission": {
                    "status": "permitted_after_qualification",
                    "use_profile_id": "private",
                    "allowed_label_scope": ["hair", "neck"],
                },
            }
        },
    }
    remap = {
        "mappings": {
            "hair": {"action": "direct", "part": ["hair"]},
            "neck": {"action": "direct", "part": ["neck"]},
        }
    }
    provenance_path = tmp_path / "provenance.yaml"
    remap_path = tmp_path / "remap.yaml"
    provenance_path.write_text(yaml.safe_dump(provenance), encoding="utf-8")
    remap_path.write_text(yaml.safe_dump(remap), encoding="utf-8")
    (root / "CelebA-HQ-img").mkdir(parents=True, exist_ok=True)
    for index in range(32):
        image = np.full((16, 16, 3), index, dtype=np.uint8)
        Image.fromarray(image).save(root / "CelebA-HQ-img" / f"{index}.jpg")
        bucket = root / "CelebAMask-HQ-mask-anno" / str(index // 2000)
        bucket.mkdir(parents=True, exist_ok=True)
        for label, column in (("hair", 2), ("neck", 8)):
            mask = np.zeros((8, 8), dtype=np.uint8)
            mask[2:6, column % 8 : (column % 8) + 1] = 255
            Image.fromarray(mask).save(bucket / f"{index:05d}_{label}.png")
    return root, provenance_path, remap_path


def test_selects_exact_direct_labels_with_source_partition_integrity(
    tmp_path: Path,
) -> None:
    root, provenance, remap = _write_inputs(tmp_path)
    result = build_celebamask_control_candidates(
        root=root,
        provenance_path=provenance,
        remap_path=remap,
        per_label_partition=4,
    )
    verify_celebamask_control_candidates(result)
    assert result["selected_by_label"] == {"hair": 8, "neck": 8}
    assert result["selected_by_partition"] == {
        "qualification_test": 8,
        "qualification_train": 8,
    }
    partitions: dict[str, str] = {}
    for record in result["selected"]:
        partitions.setdefault(record["source_image_id"], record["assigned_partition"])
        assert partitions[record["source_image_id"]] == record["assigned_partition"]
        assert record["critic_control_eligible"] is False


def test_non_direct_mapping_fails_closed(tmp_path: Path) -> None:
    root, provenance, remap = _write_inputs(tmp_path)
    value = yaml.safe_load(remap.read_text(encoding="utf-8"))
    value["mappings"]["neck"]["action"] = "merge"
    remap.write_text(yaml.safe_dump(value), encoding="utf-8")
    with pytest.raises(CelebAMaskControlCandidateError, match="not an exact direct"):
        build_celebamask_control_candidates(
            root=root,
            provenance_path=provenance,
            remap_path=remap,
            per_label_partition=2,
        )


def test_authority_upgrade_fails_verification(tmp_path: Path) -> None:
    root, provenance, remap = _write_inputs(tmp_path)
    result = build_celebamask_control_candidates(
        root=root,
        provenance_path=provenance,
        remap_path=remap,
        per_label_partition=2,
    )
    changed = copy.deepcopy(result)
    changed["critic_control_authority_granted"] = True
    changed["self_sha256"] = canonical_sha256(
        {key: value for key, value in changed.items() if key != "self_sha256"}
    )
    with pytest.raises(CelebAMaskControlCandidateError, match="authority"):
        verify_celebamask_control_candidates(changed)
