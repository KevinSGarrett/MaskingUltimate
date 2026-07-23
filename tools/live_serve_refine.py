"""Run one bounded live localhost SAM2 refine proof and seal its evidence."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--image", type=Path, default=ROOT / "qa/fixtures/smoke/ultralytics_bus_adults.jpg"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "qa/live_verification/serve_refine_cuda_20260712.json"
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    image = args.image.resolve()
    if not image.is_file() or not 1 <= args.port <= 65535:
        raise ValueError("live refine image/port is invalid")
    serve_site = ROOT / ".runtime_tmp/serve_site"
    if not (serve_site / "fastapi").is_dir():
        raise RuntimeError("project-local pinned FastAPI runtime is missing")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join((str(serve_site), str(ROOT / "src")))
    stderr_path = ROOT / ".runtime_tmp/serve_refine_stderr.log"
    stdout_path = ROOT / ".runtime_tmp/serve_refine_stdout.log"
    command = [
        sys.executable,
        "-m",
        "maskfactory.cli",
        "serve",
        "--port",
        str(args.port),
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with (
        stdout_path.open("w", encoding="utf-8") as stdout,
        stderr_path.open("w", encoding="utf-8") as stderr,
    ):
        server = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
        )
        try:
            health = _wait_for_health(server, args.port, stderr_path)
            cold_clicks = [
                {"x": 150, "y": 520, "positive": True},
                {"x": 20, "y": 20, "positive": False},
            ]
            started = time.perf_counter()
            cold_response = requests.post(
                f"http://127.0.0.1:{args.port}/refine",
                files={"image": (image.name, image.read_bytes(), "image/jpeg")},
                data={"label": "left_forearm", "clicks": json.dumps(cold_clicks)},
                timeout=600,
            )
            cold_elapsed = time.perf_counter() - started
            cold_response.raise_for_status()
            clicks = [*cold_clicks, {"x": 170, "y": 540, "positive": True}]
            started = time.perf_counter()
            response = requests.post(
                f"http://127.0.0.1:{args.port}/refine",
                files={"image": (image.name, image.read_bytes(), "image/jpeg")},
                data={"label": "left_forearm", "clicks": json.dumps(clicks)},
                timeout=600,
            )
            elapsed = time.perf_counter() - started
            response.raise_for_status()
            document = response.json()
            raw_mask = base64.b64decode(document["mask"], validate=True)
            with Image.open(io.BytesIO(raw_mask)) as opened:
                opened.load()
                mode = opened.mode
                size = list(opened.size)
                values = sorted(set(bytes(opened.tobytes())))
            audit = {
                "schema_version": "1.0.0",
                "item_progress": ["MF-P6-02.01", "MF-P6-02.05"],
                "endpoint": f"http://127.0.0.1:{args.port}/refine",
                "http_status": response.status_code,
                "cold_start_seconds": cold_elapsed,
                "elapsed_seconds": elapsed,
                "latency_target_seconds": 1.2,
                "latency_target_met": elapsed <= 1.2,
                "health": health,
                "source_path": image.relative_to(ROOT).as_posix(),
                "source_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                "label": "left_forearm",
                "clicks": clicks,
                "response_status": document["status"],
                "area_px": document["area_px"],
                "provenance": document["provenance"],
                "mask_mode": mode,
                "mask_size": size,
                "mask_values": values,
                "mask_sha256": hashlib.sha256(raw_mask).hexdigest(),
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(json.dumps(audit, indent=2, sort_keys=True))
        finally:
            server.terminate()
            try:
                server.wait(timeout=20)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)


def _wait_for_health(server: subprocess.Popen, port: int, stderr_path: Path) -> dict:
    url = f"http://127.0.0.1:{port}/health"
    for _ in range(120):
        if server.poll() is not None:
            raise RuntimeError(
                f"serving process exited {server.returncode}: "
                + stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            )
        try:
            with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310
                return json.loads(response.read())
        except (OSError, json.JSONDecodeError):
            time.sleep(0.5)
    raise TimeoutError("serving health endpoint did not become ready")


if __name__ == "__main__":
    main()
