from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.io.png_strict import write_binary_mask
from maskfactory.nude_split_person_recomposition import (
    SplitPersonRecompositionError,
    build_split_person_recomposition,
    validate_split_person_recomposition,
)

CATALOG_SHA256 = "a" * 64


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, list[Path]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "source.png"
    Image.fromarray(np.full((80, 100, 3), 127, dtype=np.uint8), mode="RGB").save(source)
    left = np.zeros((80, 100), dtype=bool)
    right = np.zeros((80, 100), dtype=bool)
    left[11:69, 11:49] = True
    right[11:69, 51:89] = True
    paths = [
        write_binary_mask(tmp_path / "left.png", left, source_size=(100, 80)),
        write_binary_mask(tmp_path / "right.png", right, source_size=(100, 80)),
    ]
    return source, paths


def _build(tmp_path: Path, **overrides):
    source, parents = _fixture(tmp_path)
    kwargs = {
        "sample_id": "sample-1",
        "source_path": source,
        "parent_paths": parents,
        "parent_confidences": [0.8, 0.7],
        "detector_box_xyxy": [10, 10, 90, 70],
        "detector_person_count": 1,
        "catalog_batch_sha256": CATALOG_SHA256,
        "output_root": tmp_path / "out",
        "output_relative_path": Path("repair/union.png"),
        "source_commit": "test-commit",
        "runtime_fingerprint": "test-runtime",
    }
    kwargs.update(overrides)
    return source, parents, kwargs, build_split_person_recomposition(**kwargs)


def test_split_person_union_is_draft_hash_bound_and_revalidates(tmp_path: Path) -> None:
    source, parents, kwargs, (batch, report) = _build(tmp_path)
    parent_hashes = [_sha(path) for path in parents]

    candidate = batch["records"][0]["candidates"][0]
    assert candidate["authority"] == "draft_machine_candidate_only"
    assert candidate["production_mask_authority"] is False
    assert report["operation"] == "union_disjoint_same_owner_proposals_v1"
    assert report["immutable_parents_preserved"] is True
    assert report["hard_qc_complete"] is False
    assert report["strict_visual_review_complete"] is False
    assert report["autonomous_certified_gold_created"] is False
    assert report["training_truth_created"] is False
    assert batch["records"][0]["candidates"][0]["prompt"]["box_xyxy"] == [10, 10, 90, 70]
    assert [_sha(path) for path in parents] == parent_hashes

    validated_batch, validated_report = validate_split_person_recomposition(
        provider_batch=batch,
        report=report,
        source_path=source,
        parent_paths=parents,
        output_root=kwargs["output_root"],
    )
    assert validated_batch == batch
    assert validated_report == report


@pytest.mark.parametrize("detector_count", [0, 2])
def test_split_person_requires_exactly_one_detector_owner(
    tmp_path: Path, detector_count: int
) -> None:
    source, parents = _fixture(tmp_path)
    with pytest.raises(
        SplitPersonRecompositionError,
        match="split_person_requires_exactly_one_detector_owner",
    ):
        build_split_person_recomposition(
            sample_id="sample-1",
            source_path=source,
            parent_paths=parents,
            parent_confidences=[0.8, 0.7],
            detector_box_xyxy=[10, 10, 90, 70],
            detector_person_count=detector_count,
            catalog_batch_sha256=CATALOG_SHA256,
            output_root=tmp_path / "out",
            output_relative_path=Path("repair/union.png"),
            source_commit="test-commit",
            runtime_fingerprint="test-runtime",
        )


def test_split_person_rejects_overlapping_or_outside_parent(tmp_path: Path) -> None:
    source, parents = _fixture(tmp_path)
    overlap = np.zeros((80, 100), dtype=bool)
    overlap[11:69, 30:70] = True
    write_binary_mask(parents[1], overlap, source_size=(100, 80))
    with pytest.raises(SplitPersonRecompositionError, match="parents_not_complementary"):
        _build(
            tmp_path / "overlap",
            source_path=source,
            parent_paths=parents,
        )

    outside_root = tmp_path / "outside"
    source, parents = _fixture(outside_root)
    outside = np.zeros((80, 100), dtype=bool)
    outside[11:69, 1:49] = True
    write_binary_mask(parents[0], outside, source_size=(100, 80))
    with pytest.raises(SplitPersonRecompositionError, match="parent_outside_detector_owner"):
        build_split_person_recomposition(
            sample_id="sample-1",
            source_path=source,
            parent_paths=parents,
            parent_confidences=[0.8, 0.7],
            detector_box_xyxy=[10, 10, 90, 70],
            detector_person_count=1,
            catalog_batch_sha256=CATALOG_SHA256,
            output_root=outside_root / "out",
            output_relative_path=Path("repair/union.png"),
            source_commit="test-commit",
            runtime_fingerprint="test-runtime",
        )


def test_split_person_validation_rejects_parent_or_authority_tamper(tmp_path: Path) -> None:
    source, parents, kwargs, (batch, report) = _build(tmp_path)
    authority_tamper = copy.deepcopy(report)
    authority_tamper["autonomous_certified_gold_created"] = True
    with pytest.raises(SplitPersonRecompositionError, match="report_seal_invalid"):
        validate_split_person_recomposition(
            provider_batch=batch,
            report=authority_tamper,
            source_path=source,
            parent_paths=parents,
            output_root=kwargs["output_root"],
        )

    changed = np.zeros((80, 100), dtype=bool)
    changed[11:69, 12:49] = True
    write_binary_mask(parents[0], changed, source_size=(100, 80))
    with pytest.raises(SplitPersonRecompositionError, match="parent_hash_mismatch"):
        validate_split_person_recomposition(
            provider_batch=batch,
            report=report,
            source_path=source,
            parent_paths=parents,
            output_root=kwargs["output_root"],
        )
