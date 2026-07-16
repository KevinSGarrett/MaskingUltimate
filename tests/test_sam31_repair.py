from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.autonomy.calibration import load_autonomy_config
from maskfactory.providers.sam31_repair import (
    REPAIR_AUTHORITY,
    Sam31RepairError,
    Sam31RepairRequest,
    run_sam31_repair_orchestration,
    verify_sam31_repair_orchestration,
    write_sam31_repair_noncompletion,
)
from maskfactory.providers.sam31_shadow import Sam31InteractiveSegmenter
from maskfactory.validation import validate_document


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "source.png"
    Image.fromarray(np.full((12, 16, 3), 127, dtype=np.uint8), "RGB").save(path)
    return path


def _request() -> Sam31RepairRequest:
    current = np.zeros((12, 16), dtype=bool)
    current[4:8, 4:8] = True
    protected = np.zeros_like(current)
    protected[8:10, 8:10] = True
    return Sam31RepairRequest(
        label="left_forearm",
        roi_xyxy=(2, 2, 12, 11),
        positive_points=((5, 5),),
        negative_points=((11, 10),),
        current_mask=current,
        protected_mask=protected,
    )


def _segmenter(*, reject_only: bool = False) -> Sam31InteractiveSegmenter:
    def refine(_embedding, *, prompt):
        accepted = np.zeros((12, 16), dtype=bool)
        accepted[4:8, 4:8] = True
        rejected = accepted.copy()
        rejected[8:10, 8:10] = True
        return ((rejected, 0.93),) if reject_only else ((accepted, 0.97), (rejected, 0.93))

    return Sam31InteractiveSegmenter(lambda image: image.shape, refine)


def test_official_sam31_repair_materializes_only_guard_passing_candidates(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    pipeline = Path("configs/pipeline.yaml")
    before = pipeline.read_bytes()
    manifest = run_sam31_repair_orchestration(
        source_image_path=source,
        parent_instance_key="p0",
        lifecycle_state="installed",
        interactive_segmenter=_segmenter(),
        requests=(_request(),),
        output_dir=tmp_path / "repair",
        repair_policy=load_autonomy_config()["repair"],
    )
    document = json.loads(manifest.read_text(encoding="utf-8"))
    summary = verify_sam31_repair_orchestration(
        manifest,
        artifact_root=manifest.parent,
        source_image_path=source,
    )

    assert not validate_document(document, "sam31_repair_orchestration")
    assert summary["status"] == "complete"
    assert summary["proposal_count"] == 2
    assert summary["accepted_candidate_count"] == 1
    assert summary["authority"] == REPAIR_AUTHORITY
    proposals = document["requests"][0]["proposals"]
    assert proposals[0]["candidate_path"] == "candidates/sam31-repair-000-00.png"
    assert proposals[1]["candidate_path"] is None
    assert "candidate_protected_overlap" in proposals[1]["guard"]["vetoes"]
    assert pipeline.read_bytes() == before


def test_sam31_repair_skip_and_empty_plan_are_explicit(tmp_path: Path) -> None:
    source = _source(tmp_path)
    skipped = write_sam31_repair_noncompletion(
        source_image_path=source,
        parent_instance_key="p0",
        lifecycle_state="planned",
        output_dir=tmp_path / "skip",
        status="skipped_unavailable",
        reason="official checkpoint remains gated",
    )
    empty = run_sam31_repair_orchestration(
        source_image_path=source,
        parent_instance_key="p0",
        lifecycle_state="installed",
        interactive_segmenter=_segmenter(),
        requests=(),
        output_dir=tmp_path / "empty",
        repair_policy=load_autonomy_config()["repair"],
    )

    assert json.loads(skipped.read_text())["status"] == "skipped_unavailable"
    assert json.loads(empty.read_text())["status"] == "complete_no_candidates"
    assert not (skipped.parent / "candidates").exists()
    assert not (empty.parent / "candidates").exists()


def test_sam31_repair_foreign_authority_and_candidate_tamper_fail_closed(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    foreign = _segmenter()
    foreign.authority = "active_map_authority"
    with pytest.raises(Sam31RepairError, match="not official shadow"):
        run_sam31_repair_orchestration(
            source_image_path=source,
            parent_instance_key="p0",
            lifecycle_state="installed",
            interactive_segmenter=foreign,
            requests=(_request(),),
            output_dir=tmp_path / "foreign",
            repair_policy=load_autonomy_config()["repair"],
        )

    manifest = run_sam31_repair_orchestration(
        source_image_path=source,
        parent_instance_key="p0",
        lifecycle_state="installed",
        interactive_segmenter=_segmenter(reject_only=False),
        requests=(_request(),),
        output_dir=tmp_path / "tamper",
        repair_policy=load_autonomy_config()["repair"],
    )
    candidate = manifest.parent / "candidates/sam31-repair-000-00.png"
    candidate.write_bytes(candidate.read_bytes() + b"tamper")
    with pytest.raises(Sam31RepairError, match="file identity is stale"):
        verify_sam31_repair_orchestration(
            manifest,
            artifact_root=manifest.parent,
            source_image_path=source,
        )
