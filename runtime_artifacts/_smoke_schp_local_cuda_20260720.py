"""One-shot SCHP ATR local-CUDA smoke via ComfyUI CUDA venv."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    script = REPO_ROOT / "tools" / "smoke_schp_wsl.py"
    checkpoint = REPO_ROOT / "models/parsing_fallback/exp-schp-201908301523-atr.pth"
    image = REPO_ROOT / "qa/fixtures/smoke/ultralytics_bus_adults.jpg"
    cache = REPO_ROOT / "models" / "runtime_cache" / "schp"
    env = os.environ.copy()
    env["MASKFACTORY_SCHP_CACHE"] = str(cache)
    process = subprocess.run(
        [
            sys.executable,
            str(script),
            "--checkpoint",
            str(checkpoint),
            "--image",
            str(image),
            "--dataset",
            "atr",
        ],
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
        env=env,
        cwd=str(REPO_ROOT),
    )
    stdout = process.stdout.strip()
    stderr = process.stderr.strip()
    result: dict
    if process.returncode != 0:
        result = {
            "passed": False,
            "family": "schp_atr",
            "runtime": "local_cuda_comfyui_venv",
            "exit_code": process.returncode,
            "stderr_tail": stderr[-3000:],
            "stdout_tail": stdout[-3000:],
        }
    else:
        try:
            payload = json.loads(stdout.splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            result = {
                "passed": False,
                "family": "schp_atr",
                "runtime": "local_cuda_comfyui_venv",
                "reason": f"invalid json: {exc}",
                "stdout_tail": stdout[-2000:],
            }
        else:
            result = {
                **payload,
                "family": "schp_atr",
                "runtime": "local_cuda_comfyui_venv",
            }
    out = REPO_ROOT / "qa/live_verification/_schp_atr_local_cuda_20260720T0956.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
