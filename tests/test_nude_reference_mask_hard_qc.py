from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.nude_box_mask_generation import generate_box_prompt_provider_batch
from maskfactory.nude_person_catalog import compare_person_proposal_catalogs
from maskfactory.nude_reference_mask_hard_qc import (
    NudeReferenceMaskHardQcError,
    build_reference_mask_hard_qc_stage_receipt,
    run_reference_person_mask_hard_qc,
    validate_reference_mask_hard_qc_stage_receipt,
    validate_reference_person_mask_hard_qc,
)
from maskfactory.providers.contracts import MaskProposal, ProviderIdentity


def _sha(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class _Provider:
    def __init__(self, *, overlap: bool = False, collapsed: bool = False):
        self.identity = ProviderIdentity(
            "provider-a", "interactive_segmenter", "family-a", "a" * 40, "b" * 64
        )
        self.overlap = overlap
        self.collapsed = collapsed

    def embed(self, image):
        return np.asarray(image).shape[:2]

    def refine(self, embedding, *, prompt):
        height, width = embedding
        left, top, right, bottom = prompt["box_xyxy"]
        point_x, point_y = prompt["positive_points"][0]
        mask = np.zeros((height, width), dtype=bool)
        if self.collapsed:
            mask[point_y, point_x] = True
        else:
            inset = 0 if self.overlap else 1
            mask[top + 1 : bottom - 1, left + inset : right - inset] = True
            mask[point_y, point_x] = True
        return (MaskProposal(mask, 0.9, self.identity, "prompt"),)


def _catalog(source_sha256: str, *, two_people: bool = False):
    proposals_a = [[2, 2, 18, 22]]
    proposals_b = [[3, 3, 17, 21]]
    if two_people:
        proposals_a.append([16, 2, 31, 22])
        proposals_b.append([17, 3, 30, 21])
    providers = []
    for provider_id, family_id, boxes, artifact in (
        ("detector-a", "detector-family-a", proposals_a, "1" * 64),
        ("detector-b", "detector-family-b", proposals_b, "2" * 64),
    ):
        providers.append(
            {
                "provider_id": provider_id,
                "family_id": family_id,
                "revision": "r1",
                "artifact_sha256": artifact,
                "source_sha256": source_sha256,
                "proposals": [
                    {
                        "bbox_xyxy": box,
                        "confidence": 0.9,
                        "label": "person",
                        "authority": "proposal_only",
                    }
                    for box in boxes
                ],
            }
        )
    return compare_person_proposal_catalogs(
        sample_id="sample-a",
        source_sha256=source_sha256,
        image_size=[32, 24],
        provider_records=providers,
        iou_min=0.5,
    )


def _fixture(tmp_path: Path, *, provider=None, two_people: bool = False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 24), (30, 40, 50)).save(source)
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    record = _catalog(source_sha, two_people=two_people)
    body = {
        "schema_version": "maskfactory.nude_person_catalog_batch.v1",
        "record_count": 1,
        "records": [record],
    }
    catalog = {**body, "self_sha256": _sha(body)}
    root = tmp_path / "masks"
    batch = generate_box_prompt_provider_batch(
        catalog_batch=catalog,
        source_paths={"sample-a": source},
        provider=provider or _Provider(),
        output_root=root,
    )
    return source, root, batch


def test_clean_candidate_passes_all_hard_vetoes_and_revalidates(tmp_path: Path):
    source, root, batch = _fixture(tmp_path)
    result = run_reference_person_mask_hard_qc(
        batch, output_root=root, source_paths={"sample-a": source}
    )
    assert result["status_counts"] == {"pass": 1}
    report = result["records"][0]["candidate_reports"][0]
    assert report["status"] == "pass"
    assert [check["check_id"] for check in report["checks"]] == [
        "NREF-QC-001",
        "NREF-QC-002",
        "NREF-QC-003",
        "NREF-QC-004",
        "NREF-QC-005",
        "NREF-QC-006",
        "NREF-QC-007",
        "NREF-QC-008",
    ]
    assert result["hard_qc_may_be_overridden"] is False
    assert result["strict_visual_review_complete"] is False
    assert (
        validate_reference_person_mask_hard_qc(
            result,
            provider_batch=batch,
            output_root=root,
            source_paths={"sample-a": source},
        )
        == result
    )


def test_collapsed_candidate_is_hard_blocked(tmp_path: Path):
    source, root, batch = _fixture(tmp_path, provider=_Provider(collapsed=True))
    result = run_reference_person_mask_hard_qc(
        batch, output_root=root, source_paths={"sample-a": source}
    )
    report = result["records"][0]["candidate_reports"][0]
    assert report["status"] == "fail"
    assert "NREF-QC-005" in report["blockers"]


def test_cross_person_overlap_is_hard_blocked(tmp_path: Path):
    source, root, batch = _fixture(tmp_path, provider=_Provider(overlap=True), two_people=True)
    result = run_reference_person_mask_hard_qc(
        batch, output_root=root, source_paths={"sample-a": source}
    )
    assert result["records"][0]["status"] == "fail"
    assert all(
        "NREF-QC-008" in report["blockers"] for report in result["records"][0]["candidate_reports"]
    )


def test_artifact_tamper_and_source_drift_fail_before_visual_review(tmp_path: Path):
    source, root, batch = _fixture(tmp_path)
    candidate = batch["records"][0]["candidates"][0]
    (root / candidate["artifact_relative_path"]).write_bytes(b"tampered")
    result = run_reference_person_mask_hard_qc(
        batch, output_root=root, source_paths={"sample-a": source}
    )
    assert result["records"][0]["status"] == "fail"
    assert "NREF-QC-001" in result["records"][0]["candidate_reports"][0]["blockers"]

    source, root, batch = _fixture(tmp_path / "other")
    source.write_bytes(b"drift")
    result = run_reference_person_mask_hard_qc(
        batch, output_root=root, source_paths={"sample-a": source}
    )
    assert result["records"][0]["status"] == "fail"
    assert result["records"][0]["blockers"] == ["NREF-QC-000"]


def test_policy_is_closed_and_cannot_weaken_overlap_below_zero(tmp_path: Path):
    source, root, batch = _fixture(tmp_path)
    with pytest.raises(NudeReferenceMaskHardQcError, match="policy_invalid"):
        run_reference_person_mask_hard_qc(
            batch,
            output_root=root,
            source_paths={"sample-a": source},
            policy={
                "minimum_mask_to_prompt_box_ratio": 0.05,
                "maximum_component_count": 16,
                "minimum_largest_component_fraction": 0.5,
                "maximum_cross_person_overlap_pixels": -1,
            },
        )


def test_hard_qc_stage_receipt_is_nonterminal_and_nonoverridable(tmp_path: Path):
    source, root, batch = _fixture(tmp_path)
    result = run_reference_person_mask_hard_qc(
        batch, output_root=root, source_paths={"sample-a": source}
    )
    receipt = build_reference_mask_hard_qc_stage_receipt(
        provider=result["provider"],
        provider_batch_sha256=result["provider_batch_sha256"],
        policy_sha256=result["policy_sha256"],
        record=result["records"][0],
    )
    assert receipt["stage"] == "reference_person_mask_hard_qc:provider-a"
    assert receipt["hard_qc_may_be_overridden"] is False
    assert receipt["production_mask_authority"] is False
    assert validate_reference_mask_hard_qc_stage_receipt(receipt) == receipt

    drifted = json.loads(json.dumps(receipt))
    drifted["blockers"] = ["invented"]
    with pytest.raises(NudeReferenceMaskHardQcError, match="status_blocker_mismatch"):
        validate_reference_mask_hard_qc_stage_receipt(drifted)

    with pytest.raises(NudeReferenceMaskHardQcError, match="policy_weakened"):
        run_reference_person_mask_hard_qc(
            batch,
            output_root=root,
            source_paths={"sample-a": source},
            policy={
                "minimum_mask_to_prompt_box_ratio": 0.01,
                "maximum_component_count": 16,
                "minimum_largest_component_fraction": 0.5,
                "maximum_cross_person_overlap_pixels": 0,
            },
        )
