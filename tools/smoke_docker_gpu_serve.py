"""Live smoke for the containerized MaskFactory GPU serve/train runtime.

Bypasses the corrupt WSL Ubuntu-22.04 ext4 VHD by exercising the CUDA runtime
inside a host NVIDIA-backed container (`docker run --gpus all`). Records only
raw, reproducible facts; it never asserts a proof tier itself.

Checks (each independent, fail-closed):
  1. torch CUDA availability + device capability inside the serve image.
  2. `maskfactory serve` /health and /models over loopback from the container.
  3. (optional --train-image) `maskfactory training-doctor` inside the train image.

Usage:
  python tools/smoke_docker_gpu_serve.py \
      --serve-image maskfactory/serve:cu128 \
      [--train-image maskfactory/train:cu128] \
      --output qa/live_verification/smoke_docker_gpu_serve_<ts>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

TORCH_PROBE = (
    "import json,torch;"
    "cap=list(torch.cuda.get_device_capability(0)) if torch.cuda.is_available() else None;"
    "name=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None;"
    "print(json.dumps({"
    "'torch_version':torch.__version__,"
    "'cuda_available':bool(torch.cuda.is_available()),"
    "'device_capability':cap,'device_name':name,"
    "'cuda_runtime':getattr(torch.version,'cuda',None)}))"
)


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


def probe_torch_cuda(serve_image: str) -> dict[str, Any]:
    result = _run(
        ["docker", "run", "--rm", "--gpus", "all", serve_image, "python", "-c", TORCH_PROBE]
    )
    parsed: dict[str, Any] | None = None
    for line in reversed((result["stdout"] or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                parsed = None
            break
    return {
        "check": "torch_cuda_in_container",
        "passed": bool(result["exit_code"] == 0 and parsed and parsed.get("cuda_available")),
        "parsed": parsed,
        "exit_code": result["exit_code"],
        "stderr_tail": (result["stderr"] or "")[-800:],
    }


def _http_json(url: str, *, timeout: int = 10) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 loopback only
            body = response.read().decode("utf-8")
            return {"ok": True, "status": response.status, "body": body}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "body": exc.read().decode("utf-8", "replace")}
    except (urllib.error.URLError, OSError) as exc:
        return {"ok": False, "status": None, "body": str(exc)}


def probe_serve(serve_image: str, *, port: int = 8765) -> dict[str, Any]:
    name = f"maskfactory_serve_smoke_{int(time.time())}"
    up = _run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--gpus",
            "all",
            "-p",
            f"127.0.0.1:{port}:8765",
            "-v",
            f"{REPO_ROOT.as_posix()}:/opt/maskfactory",
            "-w",
            "/opt/maskfactory",
            "--name",
            name,
            serve_image,
        ]
    )
    if up["exit_code"] != 0:
        return {
            "check": "serve_health_models_in_container",
            "passed": False,
            "container_started": False,
            "stderr_tail": (up["stderr"] or "")[-800:],
        }
    health: dict[str, Any] = {"ok": False}
    models: dict[str, Any] = {"ok": False}
    try:
        for _ in range(30):
            health = _http_json(f"http://127.0.0.1:{port}/health")
            if health.get("ok"):
                break
            time.sleep(2)
        if health.get("ok"):
            models = _http_json(f"http://127.0.0.1:{port}/models")
        logs = _run(["docker", "logs", name], timeout=30)
    finally:
        _run(["docker", "stop", name], timeout=60)
    return {
        "check": "serve_health_models_in_container",
        "passed": bool(health.get("ok")),
        "container_started": True,
        "health": health,
        "models": models,
        "logs_tail": (logs.get("stdout", "") + logs.get("stderr", ""))[-1200:],
    }


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
        timeout=600,
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve-image", default="maskfactory/serve:cu128")
    parser.add_argument("--train-image", default=None)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    checks.append(probe_torch_cuda(args.serve_image))
    checks.append(probe_serve(args.serve_image, port=args.port))
    if args.train_image:
        checks.append(probe_training_doctor(args.train_image))

    evidence: dict[str, Any] = {
        "artifact_type": "docker_gpu_serve_smoke",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "serve_image": args.serve_image,
        "train_image": args.train_image,
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
