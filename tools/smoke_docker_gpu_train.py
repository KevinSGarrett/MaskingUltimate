"""Live smoke for the containerized MaskFactory GPU TRAIN runtime.

Runs `maskfactory training-doctor` INSIDE the prebuilt train image with real
CUDA on the host NVIDIA stack (`docker run --gpus all`), bypassing the corrupt
WSL Ubuntu-22.04 ext4 VHD. Records only raw, reproducible facts.

SAFETY: this tool NEVER builds an image. If maskfactory/train:cu128 is absent it
fails closed with `image_absent` guidance so a heavy from-source build can never
be triggered accidentally (the sm_120 mmcv build can exhaust the WSL2 backend
and crash the Docker daemon; build it deliberately, out of band).

Usage:
  python tools/smoke_docker_gpu_train.py \
      --train-image maskfactory/train:cu128 \
      --output qa/live_verification/smoke_docker_gpu_train_<ts>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], *, timeout: int = 300) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - infra failure path
        return {"cmd": cmd, "exit_code": None, "stdout": "", "stderr": str(exc)}
    return {
        "cmd": cmd,
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def image_present(train_image: str) -> bool:
    result = _run(["docker", "image", "inspect", train_image], timeout=60)
    return result["exit_code"] == 0


def probe_training_doctor(train_image: str) -> dict[str, Any]:
    result = _run(
        [
            "docker",
            "run",
            "--rm",
            "--gpus",
            "all",
            "-v",
            f"{REPO_ROOT.as_posix()}:/opt/maskfactory",
            "-w",
            "/opt/maskfactory",
            train_image,
            "python",
            "-m",
            "maskfactory",
            "training-doctor",
        ],
        timeout=900,
    )
    report: dict[str, Any] | None = None
    for line in reversed((result["stdout"] or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                report = json.loads(line)
            except json.JSONDecodeError:
                report = None
            break
    return {
        "check": "training_doctor_in_container",
        "passed": bool(report and report.get("ready") is True),
        "report": report,
        "exit_code": result["exit_code"],
        "stdout_tail": (result["stdout"] or "")[-1500:],
        "stderr_tail": (result["stderr"] or "")[-800:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-image", default="maskfactory/train:cu128")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    if not image_present(args.train_image):
        checks.append(
            {
                "check": "train_image_present",
                "passed": False,
                "guidance": (
                    "train image absent; this tool never builds. Build deliberately with "
                    "`docker compose -f docker/compose.gpu.yml build maskfactory-train` "
                    "(heavy sm_120 mmcv from-source build) with adequate WSL2 headroom, "
                    "then re-run this smoke."
                ),
            }
        )
    else:
        checks.append({"check": "train_image_present", "passed": True})
        checks.append(probe_training_doctor(args.train_image))

    evidence: dict[str, Any] = {
        "artifact_type": "docker_gpu_train_smoke",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "train_image": args.train_image,
        "build_attempted": False,
        "checks": checks,
        "summary": {check["check"]: check["passed"] for check in checks},
    }
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence["summary"], sort_keys=True))
    return 0 if all(check["passed"] for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
