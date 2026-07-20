"""Smoke DensePose R50 via ComfyUI cu128 + runtime_cache Detectron2 PYTHONPATH."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMFY_PY = Path(r"C:\Comfy_UI_Main\ComfyUI\.venv\Scripts\python.exe")
SOURCE = ROOT / "models/runtime_cache/detectron2/02b5c4e295e990042a714712c21dc79b731e8833"
DEPS = ROOT / "models/runtime_cache/detectron2_deps"
CONFIG = SOURCE / "projects/DensePose/configs/densepose_rcnn_R_50_FPN_s1x.yaml"
CHECKPOINT = ROOT / "models/densepose/densepose_rcnn_R_50_FPN_s1x.pkl"
IMAGE = ROOT / "qa/fixtures/smoke/ultralytics_bus_adults.jpg"
SMOKE = ROOT / "tools/smoke_densepose_wsl.py"


def main() -> int:
    for path in (
        COMFY_PY,
        SOURCE / "detectron2/__init__.py",
        DEPS / "cloudpickle",
        CONFIG,
        CHECKPOINT,
        IMAGE,
        SMOKE,
    ):
        if not Path(path).exists():
            print(json.dumps({"passed": False, "reason": f"missing: {path}"}))
            return 2
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(SOURCE.resolve()),
            str((SOURCE / "projects/DensePose").resolve()),
            str(DEPS.resolve()),
            *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []),
        ]
    )
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.run(
        [
            str(COMFY_PY),
            str(SMOKE),
            "--checkpoint",
            str(CHECKPOINT.resolve()),
            "--image",
            str(IMAGE.resolve()),
            "--config",
            str(CONFIG.resolve()),
        ],
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
        cwd=str(ROOT),
        env=env,
    )
    result: dict
    if proc.returncode != 0:
        result = {
            "passed": False,
            "family": "densepose_rcnn_r50_fpn_s1x",
            "exit_code": proc.returncode,
            "stderr_tail": (proc.stderr or "")[-3000:],
            "stdout_tail": (proc.stdout or "")[-1500:],
            "runtime": "local_cuda_comfyui_venv_detectron2_runtime_cache",
            "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
    else:
        try:
            result = json.loads((proc.stdout or "").strip().splitlines()[-1])
        except Exception as exc:  # noqa: BLE001
            result = {
                "passed": False,
                "family": "densepose_rcnn_r50_fpn_s1x",
                "reason": f"bad json: {exc}",
                "stdout_tail": (proc.stdout or "")[-1500:],
                "stderr_tail": (proc.stderr or "")[-1500:],
            }
        result["family"] = "densepose_rcnn_r50_fpn_s1x"
        result["runtime"] = "local_cuda_comfyui_venv_detectron2_runtime_cache"
        result["recorded_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
