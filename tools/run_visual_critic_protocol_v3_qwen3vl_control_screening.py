#!/usr/bin/env python3
"""Run one hash-bound, local-only Qwen3-VL Protocol V3 control-screening job.

This launcher is deliberately unavailable while any existing compute process is
visible on the selected Pod. It starts only the vLLM child it owns and records
a terminal receipt; it never grants critic, certification, gold, training, or
production authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXPECTED_GPU_NAME = "NVIDIA RTX 6000 Ada Generation"
MINIMUM_TOTAL_GPU_MIB = 49000
DEFAULT_PORT = 18003
DEFAULT_STARTUP_TIMEOUT_SECONDS = 1200
MODEL_ID = "qwen3_vl_30b_a3b_instruct_fp8"


@dataclass(frozen=True)
class GpuSnapshot:
    name: str
    total_mib: int
    compute_pids: tuple[int, ...]


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_compute_processes(output: str) -> tuple[int, ...]:
    rows = [row.strip() for row in output.splitlines() if row.strip()]
    if not rows or rows == ["No running processes found"]:
        return ()
    if rows[0].lower().startswith("pid"):
        rows = rows[1:]
    pids: list[int] = []
    for row in rows:
        match = re.fullmatch(r"(\d+)(?:\s*,.*)?", row)
        if not match:
            raise ValueError(f"unparseable nvidia-smi compute-process row: {row!r}")
        pids.append(int(match.group(1)))
    return tuple(pids)


def parse_single_gpu(output: str) -> tuple[str, int]:
    rows = [row.strip() for row in output.splitlines() if row.strip()]
    if rows and rows[0].lower().startswith("name"):
        rows = rows[1:]
    if len(rows) != 1:
        raise ValueError(f"expected exactly one GPU row, found {len(rows)}")
    parts = [part.strip() for part in rows[0].split(",")]
    if len(parts) != 2:
        raise ValueError(f"unparseable nvidia-smi GPU row: {rows[0]!r}")
    memory = re.search(r"(\d+)", parts[1])
    if memory is None:
        raise ValueError(f"unparseable GPU memory value: {parts[1]!r}")
    return parts[0], int(memory.group(1))


def inspect_local_gpu() -> GpuSnapshot:
    gpu = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv"],
        check=True,
        capture_output=True,
        text=True,
    )
    processes = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv"],
        check=True,
        capture_output=True,
        text=True,
    )
    name, total_mib = parse_single_gpu(gpu.stdout)
    return GpuSnapshot(name, total_mib, parse_compute_processes(processes.stdout))


def assert_local_admission(snapshot: GpuSnapshot) -> None:
    if snapshot.name != EXPECTED_GPU_NAME:
        raise RuntimeError(f"refusing non-designated GPU: {snapshot.name!r}")
    if snapshot.total_mib < MINIMUM_TOTAL_GPU_MIB:
        raise RuntimeError(
            f"refusing insufficient GPU capacity: {snapshot.total_mib} MiB < "
            f"{MINIMUM_TOTAL_GPU_MIB} MiB"
        )
    if snapshot.compute_pids:
        pids = ",".join(str(pid) for pid in snapshot.compute_pids)
        raise RuntimeError(f"refusing to start while another compute process is present: {pids}")


def verify_expected_hash(path: Path, expected: str, label: str) -> str:
    actual = file_sha256(path)
    if actual != expected:
        raise RuntimeError(f"{label} SHA-256 drift: expected {expected}, got {actual}")
    return actual


def build_server_argv(runtime_python: Path, model_path: Path, port: int) -> list[str]:
    return [
        str(runtime_python),
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        str(model_path),
        "--served-model-name",
        MODEL_ID,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--trust-remote-code",
        "--gpu-memory-utilization",
        "0.92",
        "--max-model-len",
        "16384",
        "--max-num-seqs",
        "1",
        "--mm-processor-cache-gb",
        "0",
        "--limit-mm-per-prompt",
        '{"image":3}',
        "--seed",
        "1337",
        "--generation-config",
        "vllm",
    ]


def wait_for_health(endpoint: str, child: subprocess.Popen[bytes], timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError(
                f"vLLM server exited before health check with code {child.returncode}"
            )
        try:
            with urllib.request.urlopen(endpoint.rstrip("/") + "/health", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError(f"vLLM server did not become healthy within {timeout_seconds} seconds")


def package_versions(runtime_python: Path) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for package in ("torch", "transformers", "vllm"):
        probe = subprocess.run(
            [
                str(runtime_python),
                "-c",
                f"import importlib.metadata; print(importlib.metadata.version('{package}'))",
            ],
            text=True,
            capture_output=True,
        )
        versions[package] = probe.stdout.strip() if probe.returncode == 0 else None
    return versions


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise RuntimeError(f"refusing to overwrite immutable evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-python", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--panel-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--server-log", type=Path, required=True)
    parser.add_argument("--expected-execution-sha256", required=True)
    parser.add_argument("--expected-registry-sha256", required=True)
    parser.add_argument("--expected-runner-sha256", required=True)
    parser.add_argument("--expected-model-config-sha256", required=True)
    parser.add_argument("--expected-model-index-sha256", required=True)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--startup-timeout-seconds", type=int, default=DEFAULT_STARTUP_TIMEOUT_SECONDS
    )
    return parser.parse_args()


def stop_owned_child(child: subprocess.Popen[bytes] | None) -> None:
    if child is None or child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=60)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=30)


def main() -> int:
    args = parse_args()
    if args.startup_timeout_seconds < DEFAULT_STARTUP_TIMEOUT_SECONDS:
        raise SystemExit(
            f"startup timeout must be at least {DEFAULT_STARTUP_TIMEOUT_SECONDS} seconds"
        )
    bindings = {
        "execution": (args.execution, args.expected_execution_sha256),
        "registry": (args.registry, args.expected_registry_sha256),
        "runner": (args.runner, args.expected_runner_sha256),
        "model_config": (args.model_path / "config.json", args.expected_model_config_sha256),
        "model_index": (
            args.model_path / "model.safetensors.index.json",
            args.expected_model_index_sha256,
        ),
    }
    observed_hashes: dict[str, str] = {}
    for label, (path, expected) in bindings.items():
        if not path.is_file():
            raise SystemExit(f"missing required {label}: {path}")
        observed_hashes[label] = verify_expected_hash(path, expected, label)
    if not args.panel_root.is_dir():
        raise SystemExit(f"missing panel root: {args.panel_root}")
    if not args.runtime_python.is_file():
        raise SystemExit(f"missing runtime Python: {args.runtime_python}")
    for path in (args.output, args.receipt, args.server_log):
        if path.exists():
            raise SystemExit(f"refusing to overwrite immutable output: {path}")

    snapshot = inspect_local_gpu()
    assert_local_admission(snapshot)
    endpoint = f"http://127.0.0.1:{args.port}"
    server_argv = build_server_argv(args.runtime_python, args.model_path, args.port)
    child: subprocess.Popen[bytes] | None = None
    runtime_sha256: str | None = None
    status = "STARTUP_FAILED"
    failure_detail: str | None = None
    try:
        args.server_log.parent.mkdir(parents=True, exist_ok=True)
        with args.server_log.open("xb") as server_log:
            child = subprocess.Popen(server_argv, stdout=server_log, stderr=subprocess.STDOUT)
        wait_for_health(endpoint, child, args.startup_timeout_seconds)
        runtime = {
            "schema_version": "1.0.0",
            "artifact_type": "protocol_v3_qwen3_vl_30b_runtime_fingerprint",
            "model_id": MODEL_ID,
            "endpoint": endpoint,
            "server_argv": server_argv,
            "startup_timeout_seconds": args.startup_timeout_seconds,
            "gpu": {
                "name": snapshot.name,
                "total_mib": snapshot.total_mib,
                "compute_pids_at_admission": list(snapshot.compute_pids),
            },
            "input_sha256": observed_hashes,
            "launcher_sha256": file_sha256(Path(__file__).resolve()),
            "runtime_python": str(args.runtime_python),
            "runtime_packages": package_versions(args.runtime_python),
        }
        runtime_sha256 = canonical_sha256(runtime)
        command = [
            str(args.runtime_python),
            str(args.runner),
            "--backend",
            "openai",
            "--model-id",
            MODEL_ID,
            "--runtime-sha256",
            runtime_sha256,
            "--execution",
            str(args.execution),
            "--panel-root",
            str(args.panel_root),
            "--registry",
            str(args.registry),
            "--endpoint",
            endpoint,
            "--output",
            str(args.output),
        ]
        environment = dict(os.environ)
        source_root = str(args.runner.parent.parent / "src")
        environment["PYTHONPATH"] = source_root + (
            ":" + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
        )
        subprocess.run(command, check=True, env=environment)
        if not args.output.is_file():
            raise RuntimeError("V3 runner exited without producing its immutable bundle")
        status = "COMPLETED_CALIBRATION_ONLY"
    except Exception as error:
        failure_detail = f"{type(error).__name__}: {error}"
        raise
    finally:
        stop_owned_child(child)
        receipt = {
            "schema_version": "1.0.0",
            "artifact_type": "protocol_v3_qwen3_vl_30b_local_launch_receipt",
            "status": status,
            "authority_claimed": False,
            "role_certificate_issuance_allowed": False,
            "strict_visual_authority_allowed": False,
            "gold_or_training_authority_allowed": False,
            "production_authority_allowed": False,
            "model_id": MODEL_ID,
            "server_log": str(args.server_log),
            "output": str(args.output),
            "runtime_sha256": runtime_sha256,
            "failure_detail": failure_detail,
        }
        receipt["self_sha256"] = canonical_sha256(receipt)
        write_json_once(args.receipt, receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
