"""Create a synthetic CVAT task and invoke the SAM2 interactor through CVAT."""

from __future__ import annotations

import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://localhost:8080"
TASK_NAME = "MaskFactory SAM2 synthetic smoke"
REPORT_PATH = ROOT / "qa" / "reports" / "cvat_sam2_smoke.json"


def _load_token() -> str:
    values: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    token = values.get("CVAT_TOKEN")
    if not token:
        raise RuntimeError("CVAT_TOKEN is missing from the ignored root .env")
    return token


def _synthetic_png() -> bytes:
    image = Image.new("RGB", (256, 256), "#202020")
    draw = ImageDraw.Draw(image)
    draw.ellipse((48, 48, 208, 208), fill="#f0f0f0")
    draw.rectangle((96, 86, 160, 224), fill="#f0f0f0")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _request_json(session: requests.Session, method: str, path: str, **kwargs) -> dict | list:
    response = session.request(method, BASE_URL + path, timeout=120, **kwargs)
    response.raise_for_status()
    return response.json()


def _get_or_create_task(session: requests.Session) -> int:
    tasks = _request_json(session, "GET", "/api/tasks", params={"search": TASK_NAME})
    exact = [task for task in tasks["results"] if task["name"] == TASK_NAME]
    for task in exact:
        if task.get("size") == 1:
            return int(task["id"])
        session.delete(BASE_URL + f"/api/tasks/{task['id']}", timeout=30).raise_for_status()

    task = _request_json(
        session,
        "POST",
        "/api/tasks",
        json={
            "name": TASK_NAME,
            "labels": [{"name": "object", "color": "#33aa55", "type": "mask"}],
        },
    )
    task_id = int(task["id"])
    response = session.post(
        BASE_URL + f"/api/tasks/{task_id}/data",
        data={"image_quality": "100", "sorting_method": "lexicographical"},
        files={"client_files[0]": ("sam2_synthetic.png", _synthetic_png(), "image/png")},
        timeout=120,
    )
    response.raise_for_status()
    request_id = response.json()["rq_id"]

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        request = _request_json(session, "GET", f"/api/requests/{request_id}")
        status = request["status"]
        if status == "finished":
            return task_id
        if status == "failed":
            raise RuntimeError(f"CVAT task data processing failed: {request.get('message')}")
        time.sleep(1)
    raise TimeoutError("CVAT did not finish the synthetic task within 180 seconds")


def main() -> None:
    """Exercise CVAT -> Nuclio -> SAM2 and persist non-secret measured evidence."""
    session = requests.Session()
    session.headers["Authorization"] = "Token " + _load_token()

    functions = _request_json(session, "GET", "/api/lambda/functions")
    function = next((item for item in functions if item["id"] == "pth-sam2"), None)
    if function is None or function.get("kind") != "interactor":
        raise RuntimeError("CVAT does not list pth-sam2 as an interactor")

    task_id = _get_or_create_task(session)
    started = time.perf_counter()
    result = _request_json(
        session,
        "POST",
        "/api/lambda/functions/pth-sam2",
        json={
            "task": task_id,
            "frame": 0,
            "pos_points": [[128, 128]],
            "neg_points": [[16, 16]],
        },
    )
    latency_seconds = time.perf_counter() - started

    mask = np.asarray(result["mask"], dtype=np.uint8)
    unique_values = sorted(int(value) for value in np.unique(mask))
    checks = {
        "shape_256x256": mask.shape == (256, 256),
        "binary_0_255": set(unique_values).issubset({0, 255}),
        "positive_point_foreground": int(mask[128, 128]) == 255,
        "negative_point_background": int(mask[16, 16]) == 0,
        "nonempty_foreground": int(np.count_nonzero(mask)) > 0,
    }
    if not all(checks.values()):
        raise RuntimeError(f"SAM2 smoke checks failed: {checks}")

    report = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "function_id": "pth-sam2",
        "function_name": function["name"],
        "function_version": function["version"],
        "task_id": task_id,
        "task_name": TASK_NAME,
        "fixture": "programmatically generated 256x256 synthetic image",
        "latency_seconds": round(latency_seconds, 3),
        "mask_shape": list(mask.shape),
        "unique_values": unique_values,
        "foreground_pixels": int(np.count_nonzero(mask)),
        "checks": checks,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"cvat_sam2_smoke=pass; task_id={task_id}; "
        f"latency_seconds={latency_seconds:.3f}; foreground_pixels={report['foreground_pixels']}"
    )


if __name__ == "__main__":
    main()
