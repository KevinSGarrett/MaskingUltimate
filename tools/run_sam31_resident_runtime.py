"""Serve exact official SAM 3.1 requests from one persistent model process."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from run_sam31_runtime import execute, resident_cache_stats

SCHEMA_VERSION = "maskfactory.sam31_resident_protocol.v1"
REQUEST_FIELDS = frozenset(
    {"schema_version", "operation", "request_id", "frame_dir", "request", "prompt_npz", "output"}
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--requirements-lock", type=Path, required=True)
    parser.add_argument("--expected-source-commit", required=True)
    return parser.parse_args()


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":")), flush=True)


def _common_identity(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "source_root": str(args.source_root.resolve()),
        "checkpoint_sha256": _sha256(args.checkpoint),
        "runtime_lock_sha256": _sha256(args.runtime_lock),
        "requirements_lock_sha256": _sha256(args.requirements_lock),
        "expected_source_commit": args.expected_source_commit,
        "runner_sha256": _sha256(Path(__file__).with_name("run_sam31_runtime.py")),
        "server_sha256": _sha256(Path(__file__)),
    }


def main() -> int:
    args = _args()
    common = _common_identity(args)
    common_sha256 = _canonical_sha256(common)
    request_count = 0
    successful_count = 0
    failed_count = 0
    _emit(
        {
            "schema_version": SCHEMA_VERSION,
            "status": "ready",
            "process_id": os.getpid(),
            "common_identity": common,
            "common_identity_sha256": common_sha256,
        }
    )
    for raw_line in sys.stdin:
        command: Any = None
        try:
            command = json.loads(raw_line)
            if not isinstance(command, dict) or set(command) != REQUEST_FIELDS:
                raise ValueError("resident request fields are not closed")
            if command["schema_version"] != SCHEMA_VERSION:
                raise ValueError("resident request schema version drifted")
            request_id = command["request_id"]
            if not isinstance(request_id, str) or not request_id:
                raise ValueError("resident request_id is invalid")
            if command["operation"] == "shutdown":
                if any(
                    command[field] is not None
                    for field in ("frame_dir", "request", "prompt_npz", "output")
                ):
                    raise ValueError("resident shutdown carried request paths")
                stats = resident_cache_stats()
                summary = {
                    "schema_version": SCHEMA_VERSION,
                    "status": "stopped",
                    "request_id": request_id,
                    "process_id": os.getpid(),
                    "common_identity_sha256": common_sha256,
                    "request_count": request_count,
                    "successful_request_count": successful_count,
                    "failed_request_count": failed_count,
                    **stats,
                }
                summary["self_sha256"] = _canonical_sha256(summary)
                _emit(summary)
                return 0
            if command["operation"] != "execute":
                raise ValueError("resident operation is invalid")
            if any(
                not isinstance(command[field], str) or not command[field]
                for field in ("frame_dir", "request", "prompt_npz", "output")
            ):
                raise ValueError("resident execute paths are invalid")
            request_count += 1
            execution_args = argparse.Namespace(
                source_root=args.source_root,
                checkpoint=args.checkpoint,
                runtime_lock=args.runtime_lock,
                requirements_lock=args.requirements_lock,
                expected_source_commit=args.expected_source_commit,
                frame_dir=Path(command["frame_dir"]),
                request=Path(command["request"]),
                prompt_npz=Path(command["prompt_npz"]),
                output=Path(command["output"]),
            )
            report = execute(execution_args)
            successful_count += 1
            _emit(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "complete",
                    "request_id": request_id,
                    "process_id": os.getpid(),
                    "request_sequence": request_count,
                    "model_load_count": resident_cache_stats()["model_load_count"],
                    "report": report,
                }
            )
        except Exception as exc:
            failed_count += 1
            _emit(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "error",
                    "request_id": (
                        command.get("request_id") if isinstance(command, dict) else None
                    ),
                    "process_id": os.getpid(),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
