import json
from pathlib import Path

import numpy as np

from maskfactory.stages.s04_pose import (
    PoseCandidate,
    assign_pose_candidates_to_instances,
    process_pose_candidates,
)


def test_s04_missing_pose_uses_parsing_only_fallback_and_preserves_review_tag(
    tmp_path: Path,
) -> None:
    result = process_pose_candidates(
        [],
        instance_bbox_xyxy=(10.0, 10.0, 30.0, 30.0),
        output_dir=tmp_path,
        pose_tag_rules={},
    )

    assert result.pose_degraded is True
    document = json.loads((tmp_path / "pose133.json").read_text(encoding="utf-8"))
    assert document["pose_candidate_missing"] is True
    assert document["geometry_prior_mode"] == "parsing_only"
    assert document["review_tags"] == ["careful_review"]
    assert len(document["keypoints"]) == 133


def test_s04_assigns_distinct_candidates_to_distinct_instances() -> None:
    def candidate(box: tuple[float, float, float, float]) -> PoseCandidate:
        points = np.zeros((133, 3), dtype=np.float64)
        return PoseCandidate(box, points)

    assignments = assign_pose_candidates_to_instances(
        [candidate((0.0, 0.0, 10.0, 10.0)), candidate((20.0, 20.0, 30.0, 30.0))],
        {0: (0.0, 0.0, 10.0, 10.0), 1: (20.0, 20.0, 30.0, 30.0)},
    )
    assert assignments == {0: 0, 1: 1}
