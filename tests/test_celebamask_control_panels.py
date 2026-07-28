from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.vlm.canonical_polygon_source_candidates import sha256_file
from maskfactory.vlm.celebamask_control_candidates import (
    SCHEMA_VERSION as CANDIDATE_SCHEMA,
)
from maskfactory.vlm.celebamask_control_panels import (
    CelebAMaskControlPanelError,
    materialize_celebamask_control_panels,
    verify_celebamask_control_panel_report,
)
from maskfactory.vlm.critic_catalog import canonical_sha256


def _candidate_document(root: Path) -> dict:
    source_path = root / "CelebA-HQ-img" / "1.jpg"
    mask_path = root / "CelebAMask-HQ-mask-anno" / "0" / "00001_hair.png"
    source_path.parent.mkdir(parents=True)
    mask_path.parent.mkdir(parents=True)
    Image.fromarray(np.full((32, 32, 3), 90, dtype=np.uint8)).save(source_path)
    mask = np.zeros((16, 16), dtype=np.uint8)
    mask[2:10, 4:12] = 255
    Image.fromarray(mask).save(mask_path)
    record = {
        "sample_id": "celebamask_00001_hair",
        "source_image_id": "celebamask_00001",
        "canonical_label": "hair",
        "raw_label": "hair",
        "assigned_partition": "qualification_test",
        "source_relative_path": "CelebA-HQ-img/1.jpg",
        "source_sha256": sha256_file(source_path),
        "source_dimensions": [32, 32],
        "mask_relative_path": "CelebAMask-HQ-mask-anno/0/00001_hair.png",
        "mask_sha256": sha256_file(mask_path),
        "mask_dimensions": [16, 16],
        "mask_pixel_count": 64,
        "mask_values": [0, 255],
        "alignment_policy": "resize_source_to_mask_bilinear",
        "external_reference_qualification_complete": False,
        "visual_alignment_reviewed": False,
        "critic_control_eligible": False,
        "gold_or_production_authority": False,
    }
    document = {
        "schema_version": CANDIDATE_SCHEMA,
        "selected_count": 1,
        "selected": [record],
        "authority_claimed": False,
        "critic_control_authority_granted": False,
        "gold_or_production_authority_granted": False,
    }
    document["self_sha256"] = canonical_sha256(document)
    return document


def test_materializes_complete_exact_panels_without_authority(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    candidates = _candidate_document(source_root)
    output_root = tmp_path / "output"
    report = materialize_celebamask_control_panels(
        source_root=source_root,
        candidate_document=candidates,
        output_root=output_root,
    )
    verify_celebamask_control_panel_report(report, output_root)
    assert report["record_count"] == 1
    assert report["panel_count"] == 6
    assert report["critic_control_authority_granted"] is False


def test_report_authority_upgrade_fails(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    report = materialize_celebamask_control_panels(
        source_root=source_root,
        candidate_document=_candidate_document(source_root),
        output_root=tmp_path / "output",
    )
    changed = copy.deepcopy(report)
    changed["critic_control_authority_granted"] = True
    changed["self_sha256"] = canonical_sha256(
        {key: value for key, value in changed.items() if key != "self_sha256"}
    )
    with pytest.raises(CelebAMaskControlPanelError, match="authority"):
        verify_celebamask_control_panel_report(changed, tmp_path / "output")
