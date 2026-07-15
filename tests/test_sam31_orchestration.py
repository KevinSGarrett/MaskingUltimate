from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.providers.sam31_orchestration import (
    ORCHESTRATION_AUTHORITY,
    Sam31OrchestrationError,
    canonical_sam31_concept_routes,
    run_sam31_shadow_orchestration,
    verify_sam31_shadow_orchestration,
    write_sam31_shadow_noncompletion,
)
from maskfactory.providers.sam31_shadow import Sam31ConceptDetector, Sam31InteractiveSegmenter
from maskfactory.validation import validate_document


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "source.png"
    Image.fromarray(np.full((12, 16, 3), 127, dtype=np.uint8), "RGB").save(path)
    return path


def _providers(*, emit: bool = True):
    def discover(_path, *, concepts, exemplars):
        if not emit:
            return ()
        return (
            {
                "kind": "box",
                "confidence": 0.91,
                "label": concepts[0],
                "instance_key": hashlib.sha256(concepts[0].encode()).hexdigest()[:12],
                "value": (2, 2, 8, 8),
            },
        )

    def refine(_embedding, *, prompt):
        mask = np.zeros((12, 16), dtype=bool)
        if prompt["box_xyxy"] is not None:
            x1, y1, x2, y2 = (int(value) for value in prompt["box_xyxy"])
            mask[y1:y2, x1:x2] = True
        else:
            mask |= prompt["mask_prompt"]
        return ((mask, 0.95),)

    return (
        Sam31ConceptDetector(discover),
        Sam31InteractiveSegmenter(lambda image: image.shape, refine),
    )


def test_canonical_routes_cover_every_governed_lane_without_prompt_collision() -> None:
    routes = canonical_sam31_concept_routes()
    assert {route.lane for route in routes} == {
        "accessory",
        "chest_pelvic",
        "clothing",
        "foot_toe",
        "hair",
        "hand_finger",
        "repeated_instance",
    }
    assert len({route.concept for route in routes}) == len(routes)
    assert any(route.semantic_label == "vulva" for route in routes)
    assert any(route.semantic_label == "penis_shaft" for route in routes)


def test_production_shadow_orchestration_persists_all_lanes_without_active_map_change(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    detector, segmenter = _providers()
    pipeline = Path("configs/pipeline.yaml")
    before = pipeline.read_bytes()
    manifest = run_sam31_shadow_orchestration(
        source_image_path=source,
        parent_instance_key="p0",
        lifecycle_state="installed",
        concept_detector=detector,
        interactive_segmenter=segmenter,
        output_dir=tmp_path / "shadow",
    )
    document = json.loads(manifest.read_text(encoding="utf-8"))
    summary = verify_sam31_shadow_orchestration(
        manifest,
        artifact_root=manifest.parent,
        source_image_path=source,
    )

    assert not validate_document(document, "sam31_shadow_orchestration")
    assert summary["status"] == "complete"
    assert summary["candidate_count"] == len(canonical_sam31_concept_routes())
    assert len(summary["requested_lanes"]) == 7
    assert summary["authority"] == ORCHESTRATION_AUTHORITY
    assert pipeline.read_bytes() == before


def test_no_detection_and_unavailable_lifecycle_are_explicit_zero_authority_records(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    detector, segmenter = _providers(emit=False)
    no_candidates = run_sam31_shadow_orchestration(
        source_image_path=source,
        parent_instance_key="p0",
        lifecycle_state="installed",
        concept_detector=detector,
        interactive_segmenter=segmenter,
        output_dir=tmp_path / "none",
    )
    skipped = write_sam31_shadow_noncompletion(
        source_image_path=source,
        parent_instance_key="p0",
        lifecycle_state="planned",
        output_dir=tmp_path / "skip",
        status="skipped_unavailable",
        reason="official checkpoint remains gated",
    )

    assert json.loads(no_candidates.read_text())["status"] == "complete_no_candidates"
    assert json.loads(skipped.read_text())["status"] == "skipped_unavailable"
    assert not (no_candidates.parent / "candidates").exists()
    assert not (skipped.parent / "candidates").exists()


def test_foreign_authority_and_candidate_package_tamper_fail_closed(tmp_path: Path) -> None:
    source = _source(tmp_path)
    detector, segmenter = _providers()
    detector.authority = "active_mask_authority"
    with pytest.raises(Sam31OrchestrationError, match="not official shadow"):
        run_sam31_shadow_orchestration(
            source_image_path=source,
            parent_instance_key="p0",
            lifecycle_state="installed",
            concept_detector=detector,
            interactive_segmenter=segmenter,
            output_dir=tmp_path / "foreign",
        )

    detector, segmenter = _providers()
    manifest = run_sam31_shadow_orchestration(
        source_image_path=source,
        parent_instance_key="p0",
        lifecycle_state="installed",
        concept_detector=detector,
        interactive_segmenter=segmenter,
        output_dir=tmp_path / "tamper",
    )
    package = manifest.parent / "candidates/sam31_shadow_candidates.json"
    package.write_text(package.read_text() + " ", encoding="utf-8")
    with pytest.raises(Sam31OrchestrationError, match="file identity is stale"):
        verify_sam31_shadow_orchestration(
            manifest,
            artifact_root=manifest.parent,
            source_image_path=source,
        )
