from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from maskfactory.providers.contracts import BoxProposal
from maskfactory.providers.rtm_pose import RtmPoseProvider

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "qa" / "fixtures" / "smoke" / "ultralytics_bus_adults.jpg"
OUTPUT = ROOT / "qa" / "live_verification" / "rtm_pose_provider_20260714.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pose_record(result: dict[str, Any]) -> dict[str, Any]:
    points = np.asarray(result["keypoints"], dtype=np.float32)
    boxes = np.asarray(result["candidate_boxes_xyxy"], dtype=np.float32)
    return {
        "provider_key": result["provider_key"],
        "model_family": result["model_family"],
        "source_commit": result["source_commit"],
        "runtime_fingerprint": result["runtime_fingerprint"],
        "joint_count": len(result["joint_vocabulary"]),
        "joint_vocabulary": list(result["joint_vocabulary"]),
        "keypoints_shape": list(points.shape),
        "keypoints_sha256": hashlib.sha256(points.tobytes()).hexdigest(),
        "candidate_count": result["candidate_count"],
        "candidate_boxes_sha256": hashlib.sha256(boxes.tobytes()).hexdigest(),
        "selected_candidate_index": result["selected_candidate_index"],
        "selected_candidate_bbox_xyxy": list(result["candidate_bbox_xyxy"]),
        "requested_bbox_xyxy": list(result["requested_bbox_xyxy"]),
        "assignment_iou": result["assignment_iou"],
        "instance_key": result["instance_key"],
        "side_semantics": result["side_semantics"],
        "left_shoulder_index": result["character_side_indices"]["left_shoulder"],
        "right_shoulder_index": result["character_side_indices"]["right_shoulder"],
        "confidence_transform": result["confidence_transform"],
        "authority": result["authority"],
    }


def main() -> int:
    rtmw_box = BoxProposal((49.75, 398.25, 247.625, 905.5), 0.95, "person", "adult-bus-left")
    rtmo_box = BoxProposal(
        (221.1607, 403.4799, 349.3414, 862.1787),
        0.95,
        "person",
        "adult-bus-center",
    )
    rtmw = dict(RtmPoseProvider("rtmw_x").infer_pose(FIXTURE, person_box=rtmw_box))
    rtmo = dict(RtmPoseProvider("rtmo_crowd").infer_pose(FIXTURE, person_box=rtmo_box))
    if len(rtmw["joint_vocabulary"]) != 133:
        raise RuntimeError("RTMW-X live provider did not expose 133 joints")
    if len(rtmo["joint_vocabulary"]) != 14 or rtmo["candidate_count"] < 3:
        raise RuntimeError("RTMO live provider did not expose a crowded pose set")
    if rtmw["side_semantics"] != "character_anatomical_left_right":
        raise RuntimeError("RTMW-X live provider side semantics drifted")
    document = {
        "schema_version": "1.0.0",
        "captured_at": datetime.now(UTC).isoformat(),
        "result": "pass",
        "fixture": {
            "path": FIXTURE.relative_to(ROOT).as_posix(),
            "sha256": _sha256(FIXTURE),
        },
        "variants": {
            "rtmw_x": _pose_record(rtmw),
            "rtmo_crowd": _pose_record(rtmo),
        },
        "crowd_qualification": {
            "live_candidate_count": rtmo["candidate_count"],
            "requested_person_assignment_iou": rtmo["assignment_iou"],
            "stable_instance_key": rtmo["instance_key"],
            "distinct_character_assignment_test": "tests/test_rtm_pose_provider.py",
        },
        "fallback_selection": {
            "active": "dwpose_133",
            "independent_vote": "mediapipe_hands",
            "challengers": ["rtmw_x", "rtmo_crowd"],
            "rollback": "dwpose_133",
            "fallback_identity_test": "tests/test_rtm_pose_provider.py",
        },
        "authority": {
            "lifecycle_state": "installed",
            "shadow_only": True,
            "may_author_gold": False,
            "promotion_claimed": False,
        },
    }
    document["sha256"] = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
