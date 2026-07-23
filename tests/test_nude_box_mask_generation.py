from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.nude_box_mask_generation import (
    NudeBoxMaskGenerationError,
    Sam2BoxPromptInteractiveSegmenter,
    build_box_prompt_mask_stage_receipt,
    compare_box_prompt_provider_batches,
    generate_box_prompt_provider_batch,
    validate_box_prompt_mask_stage_receipt,
    validate_box_prompt_provider_batch,
)
from maskfactory.nude_person_catalog import compare_person_proposal_catalogs
from maskfactory.providers.contracts import MaskProposal, ProviderIdentity
from maskfactory.stages.s07_sam2 import SamCandidate


def _sha(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class _Provider:
    def __init__(self, key: str, family: str, *, offset: int = 0, fail: bool = False):
        self.identity = ProviderIdentity(key, "interactive_segmenter", family, "a" * 40, "b" * 64)
        self.offset = offset
        self.fail = fail
        self.embed_count = 0
        self.close_count = 0

    def embed(self, image: np.ndarray):
        self.embed_count += 1
        return np.asarray(image).shape[:2]

    def refine(self, embedding, *, prompt):
        if self.fail:
            raise RuntimeError("bounded provider failure")
        height, width = embedding
        left, top, right, bottom = prompt["box_xyxy"]
        point_x, point_y = prompt["positive_points"][0]
        mask = np.zeros((height, width), dtype=bool)
        mask[top + 1 : bottom - 1, left + 1 + self.offset : right - 1] = True
        mask[point_y, point_x] = True
        return (MaskProposal(mask, 0.8, self.identity, f"prompt-{self.identity.provider_key}"),)

    def close(self, embedding):
        self.close_count += 1


def _catalog(sample_id: str, source_sha256: str, *, status: str = "pass"):
    if status == "pass":
        return compare_person_proposal_catalogs(
            sample_id=sample_id,
            source_sha256=source_sha256,
            image_size=[20, 16],
            provider_records=[
                {
                    "provider_id": "detector-a",
                    "family_id": "detector-family-a",
                    "revision": "r1",
                    "artifact_sha256": "1" * 64,
                    "source_sha256": source_sha256,
                    "proposals": [
                        {
                            "bbox_xyxy": [2, 2, 18, 15],
                            "confidence": 0.9,
                            "label": "person",
                            "authority": "proposal_only",
                        }
                    ],
                },
                {
                    "provider_id": "detector-b",
                    "family_id": "detector-family-b",
                    "revision": "r2",
                    "artifact_sha256": "2" * 64,
                    "source_sha256": source_sha256,
                    "proposals": [
                        {
                            "bbox_xyxy": [3, 3, 17, 14],
                            "confidence": 0.8,
                            "label": "person",
                            "authority": "proposal_only",
                        }
                    ],
                },
            ],
        )
    return compare_person_proposal_catalogs(
        sample_id=sample_id,
        source_sha256=source_sha256,
        image_size=[20, 16],
        provider_records=[
            {
                "provider_id": "detector-a",
                "family_id": "detector-family-a",
                "revision": "r1",
                "artifact_sha256": "1" * 64,
                "source_sha256": source_sha256,
                "proposals": [],
            },
            {
                "provider_id": "detector-b",
                "family_id": "detector-family-b",
                "revision": "r2",
                "artifact_sha256": "2" * 64,
                "source_sha256": source_sha256,
                "proposals": [],
            },
        ],
    )


def _fixture(tmp_path: Path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (20, 16), (20, 30, 40)).save(first)
    Image.new("RGB", (20, 16), (50, 60, 70)).save(second)
    first_sha = hashlib.sha256(first.read_bytes()).hexdigest()
    second_sha = hashlib.sha256(second.read_bytes()).hexdigest()
    records = [_catalog("sample-a", first_sha), _catalog("sample-b", second_sha, status="abstain")]
    body = {
        "schema_version": "maskfactory.nude_person_catalog_batch.v1",
        "record_count": 2,
        "records": records,
    }
    batch = {**body, "self_sha256": _sha(body)}
    return batch, {"sample-a": first, "sample-b": second}


def test_generates_strict_hash_bound_draft_and_skips_catalog_abstain(tmp_path: Path):
    catalog, paths = _fixture(tmp_path)
    provider = _Provider("provider-a", "family-a")
    root = tmp_path / "provider-a"

    result = generate_box_prompt_provider_batch(
        catalog_batch=catalog, source_paths=paths, provider=provider, output_root=root
    )

    assert result["status_counts"] == {"catalog_abstain": 1, "generated": 1}
    assert result["candidate_count"] == 1
    assert result["production_mask_authority"] is False
    assert result["boxes_are_pixel_truth"] is False
    assert provider.embed_count == provider.close_count == 1
    candidate = result["records"][0]["candidates"][0]
    assert candidate["authority"] == "draft_machine_candidate_only"
    assert candidate["prompt"]["positive_points"] == [[10, 8]]
    path = root / candidate["artifact_relative_path"]
    with Image.open(path) as image:
        assert image.mode == "L"
        assert image.size == (20, 16)
        assert set(np.unique(np.asarray(image)).tolist()) == {0, 255}
    assert validate_box_prompt_provider_batch(result, output_root=root) == result

    replay = generate_box_prompt_provider_batch(
        catalog_batch=catalog, source_paths=paths, provider=provider, output_root=root
    )
    assert replay == result


def test_box_prompt_generation_removes_tiny_provider_islands_without_qc_weakening(
    tmp_path: Path,
):
    source = tmp_path / "source.png"
    Image.new("RGB", (120, 120), (20, 30, 40)).save(source)
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    record = compare_person_proposal_catalogs(
        sample_id="sample-speckled",
        source_sha256=source_sha,
        image_size=[120, 120],
        provider_records=[
            {
                "provider_id": "detector-a",
                "family_id": "detector-family-a",
                "revision": "r1",
                "artifact_sha256": "1" * 64,
                "source_sha256": source_sha,
                "proposals": [
                    {
                        "bbox_xyxy": [5, 5, 115, 115],
                        "confidence": 0.9,
                        "label": "person",
                        "authority": "proposal_only",
                    }
                ],
            },
            {
                "provider_id": "detector-b",
                "family_id": "detector-family-b",
                "revision": "r2",
                "artifact_sha256": "2" * 64,
                "source_sha256": source_sha,
                "proposals": [
                    {
                        "bbox_xyxy": [6, 6, 114, 114],
                        "confidence": 0.8,
                        "label": "person",
                        "authority": "proposal_only",
                    }
                ],
            },
        ],
    )
    body = {
        "schema_version": "maskfactory.nude_person_catalog_batch.v1",
        "record_count": 1,
        "records": [record],
    }
    catalog = {**body, "self_sha256": _sha(body)}

    class Speckled(_Provider):
        def refine(self, embedding, *, prompt):
            mask = np.zeros(embedding, dtype=bool)
            mask[30:100, 30:100] = True
            for offset in range(24):
                mask[8 + (offset % 4) * 4, 10 + offset * 4] = True
            point_x, point_y = prompt["positive_points"][0]
            mask[point_y, point_x] = True
            return (MaskProposal(mask, 0.9, self.identity, "speckled"),)

    root = tmp_path / "speckled"
    result = generate_box_prompt_provider_batch(
        catalog_batch=catalog,
        source_paths={"sample-speckled": source},
        provider=Speckled("sam3_1", "sam3"),
        output_root=root,
    )

    candidate = result["records"][0]["candidates"][0]
    assert candidate["postprocess"]["operation"] == "strict_box_clip_component_cleanup_v1"
    assert candidate["postprocess"]["applied"] is True
    assert candidate["postprocess"]["input_component_count"] > 16
    assert candidate["postprocess"]["output_component_count"] == 1
    with Image.open(root / candidate["artifact_relative_path"]) as image:
        mask = np.asarray(image) == 255
    assert int(mask.sum()) == candidate["pixel_count"]
    assert not mask[8, 10]
    assert mask[60, 60]
    assert validate_box_prompt_provider_batch(result, output_root=root) == result


def test_record_failure_abstains_without_stopping_batch(tmp_path: Path):
    catalog, paths = _fixture(tmp_path)
    result = generate_box_prompt_provider_batch(
        catalog_batch=catalog,
        source_paths=paths,
        provider=_Provider("provider-a", "family-a", fail=True),
        output_root=tmp_path / "failed",
    )
    assert result["status_counts"] == {"catalog_abstain": 1, "provider_abstain": 1}
    assert result["candidate_count"] == 0
    assert "RuntimeError:bounded provider failure" in result["records"][0]["reason"]


def test_later_person_failure_does_not_publish_partial_record_artifacts(tmp_path: Path):
    source = tmp_path / "multi.png"
    Image.new("RGB", (40, 20), (20, 30, 40)).save(source)
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    provider_records = []
    for provider_id, family_id, offset in (
        ("detector-a", "detector-family-a", 0),
        ("detector-b", "detector-family-b", 1),
    ):
        provider_records.append(
            {
                "provider_id": provider_id,
                "family_id": family_id,
                "revision": "r1",
                "artifact_sha256": str(offset + 1) * 64,
                "source_sha256": source_sha,
                "proposals": [
                    {
                        "bbox_xyxy": [2 + offset, 2, 18, 18],
                        "confidence": 0.9,
                        "label": "person",
                        "authority": "proposal_only",
                    },
                    {
                        "bbox_xyxy": [22 + offset, 2, 38, 18],
                        "confidence": 0.9,
                        "label": "person",
                        "authority": "proposal_only",
                    },
                ],
            }
        )
    record = compare_person_proposal_catalogs(
        sample_id="sample-multi",
        source_sha256=source_sha,
        image_size=[40, 20],
        provider_records=provider_records,
    )
    body = {
        "schema_version": "maskfactory.nude_person_catalog_batch.v1",
        "record_count": 1,
        "records": [record],
    }
    catalog = {**body, "self_sha256": _sha(body)}

    class FailSecondPerson(_Provider):
        def __init__(self):
            super().__init__("provider-a", "family-a")
            self.refine_count = 0

        def refine(self, embedding, *, prompt):
            self.refine_count += 1
            if self.refine_count == 2:
                raise RuntimeError("second person failed")
            return super().refine(embedding, prompt=prompt)

    root = tmp_path / "atomic-record-output"
    result = generate_box_prompt_provider_batch(
        catalog_batch=catalog,
        source_paths={"sample-multi": source},
        provider=FailSecondPerson(),
        output_root=root,
    )

    assert result["status_counts"] == {"provider_abstain": 1}
    assert result["candidate_count"] == 0
    assert result["records"][0]["candidates"] == []
    assert "RuntimeError:second person failed" in result["records"][0]["reason"]
    assert not list(root.rglob("*.png"))
    assert not (root / "sample-multi").exists()


def test_provider_output_must_be_prompt_compliant(tmp_path: Path):
    catalog, paths = _fixture(tmp_path)

    class Outside(_Provider):
        def refine(self, embedding, *, prompt):
            mask = np.ones(embedding, dtype=bool)
            return (MaskProposal(mask, 0.9, self.identity, "outside"),)

    result = generate_box_prompt_provider_batch(
        catalog_batch=catalog,
        source_paths=paths,
        provider=Outside("provider-a", "family-a"),
        output_root=tmp_path / "outside",
    )
    assert result["records"][0]["status"] == "provider_abstain"
    assert "provider_returned_no_prompt_compliant_mask" in result["records"][0]["reason"][0]


def test_independent_provider_comparison_passes_and_abstains(tmp_path: Path):
    catalog, paths = _fixture(tmp_path)
    roots = [tmp_path / "a", tmp_path / "b"]
    first = generate_box_prompt_provider_batch(
        catalog_batch=catalog,
        source_paths=paths,
        provider=_Provider("provider-a", "family-a"),
        output_root=roots[0],
    )
    second = generate_box_prompt_provider_batch(
        catalog_batch=catalog,
        source_paths=paths,
        provider=_Provider("provider-b", "family-b", offset=1),
        output_root=roots[1],
    )
    comparison = compare_box_prompt_provider_batches(
        [first, second], output_roots=roots, iou_min=0.80
    )
    by_sample = {row["sample_id"]: row for row in comparison["records"]}
    assert by_sample["sample-a"]["status"] == "pass"
    assert by_sample["sample-a"]["comparisons"][0]["minimum_pairwise_iou"] > 0.8
    assert by_sample["sample-b"]["status"] == "abstain"
    assert comparison["hard_qc_complete"] is False
    assert comparison["strict_visual_review_complete"] is False
    assert comparison["operational_certificates_issued"] is False


def test_corrupt_artifact_and_correlated_families_fail_closed(tmp_path: Path):
    catalog, paths = _fixture(tmp_path)
    roots = [tmp_path / "a", tmp_path / "b"]
    first = generate_box_prompt_provider_batch(
        catalog_batch=catalog,
        source_paths=paths,
        provider=_Provider("provider-a", "same-family"),
        output_root=roots[0],
    )
    second = generate_box_prompt_provider_batch(
        catalog_batch=catalog,
        source_paths=paths,
        provider=_Provider("provider-b", "same-family"),
        output_root=roots[1],
    )
    with pytest.raises(NudeBoxMaskGenerationError, match="families_not_independent"):
        compare_box_prompt_provider_batches([first, second], output_roots=roots)

    path = roots[0] / first["records"][0]["candidates"][0]["artifact_relative_path"]
    path.write_bytes(b"corrupt")
    with pytest.raises(NudeBoxMaskGenerationError, match="artifact_hash_mismatch"):
        validate_box_prompt_provider_batch(first, output_root=roots[0])

    authority_drift = json.loads(json.dumps(second))
    authority_drift["records"][0]["candidates"][0]["production_mask_authority"] = True
    body = {key: value for key, value in authority_drift.items() if key != "self_sha256"}
    authority_drift["self_sha256"] = _sha(body)
    with pytest.raises(NudeBoxMaskGenerationError, match="candidate_authority_invalid"):
        validate_box_prompt_provider_batch(authority_drift, output_root=roots[1])


def test_catalog_hash_and_source_hash_fail_closed(tmp_path: Path):
    catalog, paths = _fixture(tmp_path)
    drifted = json.loads(json.dumps(catalog))
    drifted["record_count"] = 3
    with pytest.raises(NudeBoxMaskGenerationError, match="catalog_batch_hash_mismatch"):
        generate_box_prompt_provider_batch(
            catalog_batch=drifted,
            source_paths=paths,
            provider=_Provider("provider-a", "family-a"),
            output_root=tmp_path / "drifted",
        )

    paths["sample-a"].write_bytes(b"changed")
    result = generate_box_prompt_provider_batch(
        catalog_batch=catalog,
        source_paths=paths,
        provider=_Provider("provider-a", "family-a"),
        output_root=tmp_path / "changed",
    )
    assert result["records"][0]["status"] == "provider_abstain"
    assert "source_file_hash_mismatch" in result["records"][0]["reason"][0]


def test_stage_receipt_is_provider_specific_nonterminal_and_fail_closed(tmp_path: Path):
    catalog, paths = _fixture(tmp_path)
    batch = generate_box_prompt_provider_batch(
        catalog_batch=catalog,
        source_paths=paths,
        provider=_Provider("provider-a", "family-a"),
        output_root=tmp_path / "provider-a",
    )
    receipt = build_box_prompt_mask_stage_receipt(
        provider=batch["provider"],
        catalog_batch_sha256=batch["catalog_batch_sha256"],
        record=batch["records"][0],
    )
    assert receipt["stage"] == "box_prompt_mask_generation:provider-a"
    assert receipt["authority"] == "intermediate_non_authoritative_evidence"
    assert receipt["operational_certificate_issued"] is False
    assert validate_box_prompt_mask_stage_receipt(receipt) == receipt

    drifted = json.loads(json.dumps(receipt))
    drifted["candidates"][0]["production_mask_authority"] = True
    with pytest.raises(NudeBoxMaskGenerationError, match="candidate_authority_invalid"):
        validate_box_prompt_mask_stage_receipt(drifted)


def test_sam2_bridge_binds_model_prompt_and_strict_box_clip():
    class Sam2:
        def embed(self, image, *, model, precision):
            assert model == "sam2.1_hiera_large"
            assert precision == "fp16"
            return image.shape[:2]

        def predict(self, embedding, plan, *, multimask_output):
            assert multimask_output is True
            logits = np.ones(embedding, dtype=np.float32)
            return [SamCandidate(logits, 0.91)]

        def close(self, embedding):
            self.closed = embedding

    runtime = Sam2()
    identity = ProviderIdentity(
        "sam2_1_large_with_base_plus_oom",
        "interactive_segmenter",
        "sam2",
        "a" * 40,
        "b" * 64,
    )
    bridge = Sam2BoxPromptInteractiveSegmenter(runtime, identity)
    embedding = bridge.embed(np.zeros((16, 20, 3), dtype=np.uint8))
    proposals = bridge.refine(
        embedding,
        prompt={
            "positive_points": [[10, 8]],
            "negative_points": [],
            "box_xyxy": [2, 3, 18, 15],
            "mask_prompt": None,
        },
    )
    assert len(proposals) == 1
    assert proposals[0].mask[3:15, 2:18].all()
    assert not proposals[0].mask[:3].any()
    assert not proposals[0].mask[:, :2].any()
    assert proposals[0].confidence == 0.91
    assert len(proposals[0].prompt_fingerprint) == 64
    bridge.close(embedding)
    assert runtime.closed == (16, 20)
