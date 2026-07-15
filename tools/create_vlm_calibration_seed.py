"""Create a local, non-gold hand-mask calibration seed through CVAT's SAM2 interactor."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maskfactory.io.png_strict import write_binary_mask  # noqa: E402

BASE_URL = "http://localhost:8080"
SOURCE = ROOT / "qa" / "fixtures" / "smoke" / "mediapipe_thumb_up.jpg"
OUTPUT = ROOT / "qa" / "vlm_eval" / "seed"


def _token() -> str:
    value = os.environ.get("CVAT_TOKEN")
    if value:
        return value
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("CVAT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("CVAT_TOKEN unavailable")


def _wait(session: requests.Session, request_id: str) -> None:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        response = session.get(BASE_URL + f"/api/requests/{request_id}", timeout=30)
        response.raise_for_status()
        status = response.json()["status"]
        if status == "finished":
            return
        if status == "failed":
            raise RuntimeError(f"CVAT upload failed: {response.json().get('message')}")
        time.sleep(1)
    raise TimeoutError("CVAT upload did not finish")


def main() -> None:
    session = requests.Session()
    session.headers["Authorization"] = "Token " + _token()
    task = session.post(
        BASE_URL + "/api/tasks",
        json={
            "name": "MaskFactory VLM calibration seed - adult hand",
            "labels": [{"name": "hand", "color": "#33aa55", "type": "mask"}],
        },
        timeout=30,
    )
    task.raise_for_status()
    task_id = int(task.json()["id"])
    with SOURCE.open("rb") as handle:
        upload = session.post(
            BASE_URL + f"/api/tasks/{task_id}/data",
            data={"image_quality": "100", "sorting_method": "lexicographical"},
            files={"client_files[0]": (SOURCE.name, handle, "image/jpeg")},
            timeout=120,
        )
    upload.raise_for_status()
    _wait(session, upload.json()["rq_id"])
    positive = [[230, 220], [190, 115], [310, 300], [155, 220]]
    negative = [[20, 20], [350, 20], [20, 350], [80, 220]]
    response = session.post(
        BASE_URL + "/api/lambda/functions/pth-sam2",
        json={
            "task": task_id,
            "frame": 0,
            "pos_points": positive,
            "neg_points": negative,
        },
        timeout=300,
    )
    response.raise_for_status()
    mask = np.asarray(response.json()["mask"], dtype=np.uint8)
    with Image.open(SOURCE) as opened:
        size = opened.size
    if mask.shape != (size[1], size[0]) or set(np.unique(mask).tolist()) - {0, 255}:
        raise RuntimeError("SAM2 seed mask violates dimensions/binary contract")
    if not all(mask[y, x] == 255 for x, y in positive) or not all(
        mask[y, x] == 0 for x, y in negative
    ):
        raise RuntimeError(
            "SAM2 seed mask violates prompt polarity: "
            f"positive={[int(mask[y, x]) for x, y in positive]} "
            f"negative={[int(mask[y, x]) for x, y in negative]}"
        )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    mask_path = write_binary_mask(OUTPUT / "adult_hand_seed.png", mask, source_size=size)
    provenance = {
        "created_at": datetime.now(UTC).isoformat(),
        "source": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "mask": str(mask_path.relative_to(ROOT)).replace("\\", "/"),
        "label": "hand_forearm_candidate",
        "authority": "calibration_seed_only_not_gold",
        "cvat_task_id": task_id,
        "interactor": "pth-sam2",
        "positive_points": positive,
        "negative_points": negative,
    }
    (OUTPUT / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(provenance, sort_keys=True))


if __name__ == "__main__":
    main()
