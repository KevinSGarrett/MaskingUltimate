from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.providers.contracts import MaskProposal, ProviderIdentity
from maskfactory.providers.provider_matrix import canonical_sha256
from maskfactory.providers.sam31_candidates import (
    LANE_TO_ROLE,
    PACKAGE_AUTHORITY,
    Sam31CandidatePackageError,
    Sam31LaneCandidate,
    verify_sam31_candidate_package,
    write_sam31_candidate_package,
)
from maskfactory.providers.sam31_shadow import sam31_provider_identity
from maskfactory.validation import validate_document

ROOT = Path(__file__).resolve().parents[1]
LANE_LABELS = {
    "accessory": "accessory",
    "chest_pelvic": "pelvic_region",
    "clothing": "top_garment",
    "foot_toe": "left_toes",
    "hair": "hair",
    "hand_finger": "left_index_finger",
    "repeated_instance": "other_person",
}


def _source(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "source.png"
    Image.fromarray(np.zeros((20, 24, 3), dtype=np.uint8), "RGB").save(path)
    return path


def _candidates() -> tuple[Sam31LaneCandidate, ...]:
    identity = sam31_provider_identity("interactive_segmenter")
    values = []
    for index, (lane, label) in enumerate(sorted(LANE_LABELS.items())):
        mask = np.zeros((20, 24), dtype=bool)
        mask[2 + index : 5 + index, 3 + index : 8 + index] = True
        values.append(
            Sam31LaneCandidate(
                f"sam31-{lane}-p0",
                lane,
                label,
                "person-0",
                MaskProposal(mask, 0.9, identity, f"{index + 1:064x}"),
            )
        )
    return tuple(values)


def _build(tmp_path: Path) -> tuple[Path, Path, dict]:
    root = tmp_path / "package"
    manifest = write_sam31_candidate_package(
        source_image_path=_source(tmp_path), candidates=_candidates(), output_dir=root
    )
    return manifest, root, json.loads(manifest.read_text(encoding="utf-8"))


def _reseal(path: Path, document: dict) -> None:
    document["sha256"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "sha256"}
    )
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def test_all_seven_lanes_persist_isolated_strict_hash_bound_candidates(tmp_path: Path) -> None:
    manifest, root, document = _build(tmp_path)
    summary = verify_sam31_candidate_package(manifest, artifact_root=root)
    assert not validate_document(document, "sam31_shadow_candidate_package")
    assert summary == {
        "candidate_count": 7,
        "enabled_lanes": sorted(LANE_TO_ROLE),
        "sha256": document["sha256"],
        "authority": PACKAGE_AUTHORITY,
    }
    assert document["pipeline_sha256_before"] == document["pipeline_sha256_after"]
    assert len({row["mask_path"] for row in document["candidates"]}) == 7
    for row in document["candidates"]:
        assert row["benchmark_role"] == LANE_TO_ROLE[row["lane"]]
        with Image.open(root / row["mask_path"]) as image:
            assert image.format == "PNG" and image.mode == "L" and image.size == (24, 20)
            assert set(np.unique(np.asarray(image)).tolist()) == {0, 255}


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda doc: doc["candidates"][1].update(
                candidate_id=doc["candidates"][0]["candidate_id"]
            ),
            "duplicated",
        ),
        (
            lambda doc: doc["candidates"][1].update(mask_path=doc["candidates"][0]["mask_path"]),
            "duplicated",
        ),
        (
            lambda doc: doc["candidates"][0].update(semantic_label="not_governed"),
            "duplicated or invalid",
        ),
        (lambda doc: doc["candidates"][0].update(benchmark_role="wrong"), "duplicated or invalid"),
        (
            lambda doc: doc["candidates"][0].update(provider_runtime_fingerprint="0" * 64),
            "duplicated or invalid",
        ),
        (lambda doc: doc.update(pipeline_sha256_after="0" * 64), "active-map identity"),
    ],
)
def test_manifest_rebinding_duplicate_reuse_and_active_map_drift_fail(
    tmp_path: Path, mutation, message: str
) -> None:
    manifest, root, document = _build(tmp_path)
    mutation(document)
    _reseal(manifest, document)
    with pytest.raises(Sam31CandidatePackageError, match=message):
        verify_sam31_candidate_package(manifest, artifact_root=root)


def test_artifact_hash_format_bbox_count_and_path_escape_fail(tmp_path: Path) -> None:
    manifest, root, document = _build(tmp_path)
    row = document["candidates"][0]
    path = root / row["mask_path"]
    Image.fromarray(np.full((20, 24), 128, dtype=np.uint8), "L").save(path)
    with pytest.raises(Sam31CandidatePackageError, match="strict PNG"):
        verify_sam31_candidate_package(manifest, artifact_root=root)

    manifest, root, document = _build(tmp_path / "hash")
    document["candidates"][0]["foreground_pixels"] += 1
    _reseal(manifest, document)
    with pytest.raises(Sam31CandidatePackageError, match="artifact evidence"):
        verify_sam31_candidate_package(manifest, artifact_root=root)

    manifest, root, document = _build(tmp_path / "escape")
    document["candidates"][0]["mask_path"] = "../outside.png"
    _reseal(manifest, document)
    with pytest.raises(Sam31CandidatePackageError):
        verify_sam31_candidate_package(manifest, artifact_root=root)


def test_writer_rejects_wrong_lane_label_provider_shape_empty_and_duplicate(tmp_path: Path) -> None:
    source = _source(tmp_path)
    base = list(_candidates())
    wrong_label = copy.copy(base[0])
    object.__setattr__(wrong_label, "semantic_label", "hair")
    with pytest.raises(Sam31CandidatePackageError, match="not governed"):
        write_sam31_candidate_package(
            source_image_path=source, candidates=(wrong_label,), output_dir=tmp_path / "bad-label"
        )

    wrong_identity = sam31_provider_identity("concept_detector")
    mask = np.zeros((20, 24), dtype=bool)
    mask[1:3, 1:3] = True
    proposal = MaskProposal(mask, 0.9, wrong_identity, "a" * 64)
    wrong_provider = Sam31LaneCandidate("wrong-provider", "hair", "hair", "p0", proposal)
    # Concept discovery masks are valid candidates too; a foreign provider is not.
    foreign = copy.copy(proposal)
    object.__setattr__(
        foreign,
        "provider",
        ProviderIdentity(
            "fake",
            wrong_identity.role,
            wrong_identity.model_family,
            wrong_identity.source_commit,
            wrong_identity.runtime_fingerprint,
        ),
    )
    wrong_provider = Sam31LaneCandidate("wrong-provider", "hair", "hair", "p0", foreign)
    with pytest.raises(Sam31CandidatePackageError, match="identity is stale"):
        write_sam31_candidate_package(
            source_image_path=source,
            candidates=(wrong_provider,),
            output_dir=tmp_path / "bad-provider",
        )

    duplicate = (base[0], copy.copy(base[0]))
    with pytest.raises(Sam31CandidatePackageError, match="safe and unique"):
        write_sam31_candidate_package(
            source_image_path=source, candidates=duplicate, output_dir=tmp_path / "duplicate"
        )


def test_cross_semantic_near_duplicate_masks_fail_closed(tmp_path: Path) -> None:
    source = _source(tmp_path)
    identity = sam31_provider_identity("concept_detector")
    mask = np.zeros((20, 24), dtype=bool)
    mask[2:18, 2:22] = True
    almost_same = mask.copy()
    almost_same[2, 2] = False
    candidates = (
        Sam31LaneCandidate(
            "sam31-hair-p0",
            "hair",
            "hair",
            "person-0.hair",
            MaskProposal(mask, 0.95, identity, "a" * 64),
        ),
        Sam31LaneCandidate(
            "sam31-head-face-p0",
            "hair",
            "head_face",
            "person-0.head-face",
            MaskProposal(almost_same, 0.94, identity, "b" * 64),
        ),
    )

    with pytest.raises(Sam31CandidatePackageError, match="cross-semantic.*near-duplicates"):
        write_sam31_candidate_package(
            source_image_path=source,
            candidates=candidates,
            output_dir=tmp_path / "near-duplicate",
        )
