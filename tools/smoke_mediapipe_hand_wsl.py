"""One-image MediaPipe 21-point hand smoke in authoritative WSL."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import mediapipe as mp


def run(checkpoint: Path, image: Path) -> dict[str, object]:
    options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(checkpoint)),
        num_hands=2,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    sample = mp.Image.create_from_file(str(image))
    with mp.tasks.vision.HandLandmarker.create_from_options(options) as landmarker:
        result = landmarker.detect(sample)
    if len(result.hand_landmarks) != 1 or len(result.hand_landmarks[0]) != 21:
        return {
            "passed": False,
            "output_sha256": "",
            "reason": f"expected one 21-point hand, got {[len(hand) for hand in result.hand_landmarks]}",
        }
    landmarks = [
        [round(float(point.x), 6), round(float(point.y), 6), round(float(point.z), 6)]
        for point in result.hand_landmarks[0]
    ]
    world = [
        [round(float(point.x), 6), round(float(point.y), 6), round(float(point.z), 6)]
        for point in result.hand_world_landmarks[0]
    ]
    handedness = result.handedness[0][0]
    payload = {
        "landmarks": landmarks,
        "world_landmarks": world,
        "handedness": handedness.category_name,
        "handedness_score": round(float(handedness.score), 6),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {
        "passed": True,
        "output_sha256": hashlib.sha256(encoded).hexdigest(),
        "hand_count": 1,
        "landmark_count": 21,
        "world_landmark_count": 21,
        "handedness": handedness.category_name,
        "handedness_score": round(float(handedness.score), 6),
        "mediapipe": mp.__version__,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.checkpoint, args.image), sort_keys=True))


if __name__ == "__main__":
    main()
