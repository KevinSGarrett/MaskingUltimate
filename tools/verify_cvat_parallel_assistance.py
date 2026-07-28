"""Verify preserved-task SAM2 assistance through the parallel CVAT target."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "http://localhost:8080"
TARGET_URL = "http://127.0.0.1:18080"
TARGET_HOST = "cvat269.localhost"
DEFAULT_OUTPUT = ROOT / "qa" / "live_verification" / "cvat_parallel_sam2_assistance_20260715.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_token() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("CVAT_TOKEN="):
            token = line.split("=", 1)[1].strip()
            if token:
                return token
    raise RuntimeError("CVAT_TOKEN is missing from the ignored root .env")


def _session(token: str, *, host: str | None = None) -> requests.Session:
    session = requests.Session()
    session.headers["Authorization"] = f"Token {token}"
    if host is not None:
        session.headers["Host"] = host
    return session


def _json(session: requests.Session, method: str, url: str, **kwargs: Any) -> Any:
    response = session.request(method, url, timeout=120, **kwargs)
    response.raise_for_status()
    return response.json()


def _task_identity(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(task["id"]),
        "name": str(task["name"]),
        "size": int(task["size"]),
        "project_id": task.get("project_id"),
        "subset": str(task.get("subset", "")),
        "mode": str(task["mode"]),
        "dimension": str(task["dimension"]),
    }


def _validate_mask(result: dict[str, Any]) -> tuple[dict[str, Any], np.ndarray]:
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
        raise RuntimeError(f"parallel CVAT SAM2 mask checks failed: {checks}")
    return (
        {
            "shape": list(mask.shape),
            "unique_values": unique_values,
            "foreground_pixels": int(np.count_nonzero(mask)),
            "checks": checks,
        },
        mask,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify target CVAT version, preserved task, and SAM2 assistance"
    )
    parser.add_argument("--task-id", type=int, default=1)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    token = _load_token()
    source = _session(token)
    target = _session(token, host=TARGET_HOST)
    source_about = _json(source, "GET", f"{SOURCE_URL}/api/server/about")
    target_about = _json(target, "GET", f"{TARGET_URL}/api/server/about")
    if source_about.get("version") != "2.24.0" or target_about.get("version") != "2.69.0":
        raise RuntimeError("parallel CVAT versions differ from the frozen migration contract")

    source_task = _task_identity(_json(source, "GET", f"{SOURCE_URL}/api/tasks/{args.task_id}"))
    target_task = _task_identity(_json(target, "GET", f"{TARGET_URL}/api/tasks/{args.task_id}"))
    if source_task != target_task or source_task["size"] != 1:
        raise RuntimeError("parallel CVAT task identity is not preserved exactly")

    functions = _json(target, "GET", f"{TARGET_URL}/api/lambda/functions")
    function = next((row for row in functions if row.get("id") == "pth-sam2"), None)
    if function is None or function.get("kind") != "interactor":
        raise RuntimeError("parallel CVAT does not expose pth-sam2 as an interactor")

    started = datetime.now(UTC)
    result = _json(
        target,
        "POST",
        f"{TARGET_URL}/api/lambda/functions/pth-sam2",
        json={
            "task": args.task_id,
            "frame": 0,
            "pos_points": [[128, 128]],
            "neg_points": [[16, 16]],
        },
    )
    finished = datetime.now(UTC)
    mask_evidence, mask = _validate_mask(result)
    mask_evidence["array_sha256"] = hashlib.sha256(mask.tobytes()).hexdigest()
    mask_evidence["latency_seconds"] = round((finished - started).total_seconds(), 3)

    migration_path = ROOT / "qa/live_verification/cvat_parallel_upgrade_v269_20260714.json"
    source_smoke_path = ROOT / "qa/reports/cvat_sam2_smoke.json"
    override_path = ROOT / "configs/cvat-compose.parallel-v269.yml"
    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "captured_at": finished.isoformat().replace("+00:00", "Z"),
        "result": "sam2_pass_sam31_checkpoint_pending",
        "versions": {
            "incumbent": source_about["version"],
            "parallel_target": target_about["version"],
        },
        "preserved_task": source_task,
        "task_identity_matches_exactly": True,
        "target_interactor": {
            "id": function["id"],
            "name": function["name"],
            "version": function["version"],
            "kind": function["kind"],
        },
        "target_sam2_inference": mask_evidence,
        "bound_artifacts": {
            "migration_evidence_sha256": _sha256(migration_path),
            "source_sam2_smoke_sha256": _sha256(source_smoke_path),
            "parallel_override_sha256": _sha256(override_path),
        },
        "sam31_assistance": {
            "status": "pending_gated_checkpoint",
            "tracker_item": "MF-P0-17.04",
            "authority_granted": False,
        },
        "production_annotations_or_task_state_mutated": False,
        "authority": (
            "parallel_assistance_live_evidence_only_no_provider_promotion_"
            "task_mutation_gold_training_or_completion_authority"
        ),
    }
    document["sha256"] = _canonical_sha256(document)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(
        "parallel_cvat_sam2=pass; "
        f"task_id={args.task_id}; foreground_pixels={mask_evidence['foreground_pixels']}; "
        f"latency_seconds={mask_evidence['latency_seconds']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
