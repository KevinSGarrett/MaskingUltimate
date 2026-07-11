"""Transactional training-run provenance and lifecycle (doc 12 §5)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .augmentations import validate_augmentation_config
from .runtime import TrainingRuntimeError, validate_bodypart_class_contract

RUN_ID = re.compile(r"^r_\d{8}T\d{6}Z_[a-z0-9_]+_bodyparts_v\d+$")
DVC_MD5 = re.compile(r"^[a-f0-9]{32}$")
FINAL_STATUSES = {"complete", "failed"}


class TrainingRunError(ValueError):
    """A training run cannot establish immutable provenance or legal state."""


def initialize_training_run(
    *,
    model: str,
    dataset_root: Path,
    config_path: Path,
    dvc_md5: str,
    runs_root: Path,
    run_id: str | None = None,
    now: datetime | None = None,
    git_sha: str | None = None,
) -> Path:
    """Atomically create the full immutable run tree before training begins."""
    model_name = _slug(model)
    dataset_root = Path(dataset_root).resolve()
    config_path = Path(config_path).resolve()
    if not dataset_root.is_dir() or not (dataset_root / "build_manifest.json").is_file():
        raise TrainingRunError("dataset root lacks build_manifest.json")
    if not config_path.is_file():
        raise TrainingRunError(f"training config is missing: {config_path}")
    if not DVC_MD5.fullmatch(dvc_md5):
        raise TrainingRunError("dataset DVC md5 must be exactly 32 lowercase hex characters")
    dataset_ref = dataset_root.name
    if not re.fullmatch(r"bodyparts@v[1-9]\d*", dataset_ref):
        raise TrainingRunError("dataset reference must be bodyparts@vN")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise TrainingRunError("training config must be a mapping")
    try:
        validate_bodypart_class_contract(config)
    except TrainingRuntimeError as exc:
        raise TrainingRunError(str(exc)) from exc
    validate_augmentation_config(config)
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    selected_id = run_id or f"r_{timestamp}_{model_name}_{dataset_ref.replace('@', '_')}"
    if not RUN_ID.fullmatch(selected_id):
        raise TrainingRunError(f"invalid training run_id: {selected_id}")
    destination = Path(runs_root) / selected_id
    if destination.exists():
        raise FileExistsError(f"training run already exists: {destination}")
    revision = git_sha or _git_sha()
    if not re.fullmatch(r"[a-f0-9]{40}|unavailable", revision):
        raise TrainingRunError("git SHA must be 40 lowercase hex characters or unavailable")
    config_bytes = config_path.read_bytes()
    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "run_id": selected_id,
        "model": model_name,
        "status": "initialized",
        "created_at": (now or datetime.now(UTC)).astimezone(UTC).isoformat(),
        "updated_at": (now or datetime.now(UTC)).astimezone(UTC).isoformat(),
        "dataset_ref": dataset_ref,
        "dataset_root": str(dataset_root),
        "dataset_dvc_md5": dvc_md5,
        "git_sha": revision,
        "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "seed": int(config.get("data", {}).get("seed", 1337)),
    }
    Path(runs_root).mkdir(parents=True, exist_ok=True)
    staging = Path(runs_root) / f".{selected_id}.tmp-{uuid.uuid4().hex}"
    try:
        staging.mkdir()
        for name in ("ckpts", "tb", "eval"):
            (staging / name).mkdir()
        (staging / "config.yaml").write_bytes(config_bytes)
        (staging / "git_sha").write_text(revision + "\n", encoding="utf-8")
        (staging / "dataset_ref").write_text(dataset_ref + "\n", encoding="utf-8")
        (staging / "dataset_dvc_md5").write_text(dvc_md5 + "\n", encoding="utf-8")
        (staging / "run.json").write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination


def transition_training_run(run_root: Path, status: str, *, detail: str = "") -> dict[str, Any]:
    """Atomically move initialized→running→complete/failed; final states are immutable."""
    path = Path(run_root) / "run.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    current = document["status"]
    permitted = {
        "initialized": {"running", "failed"},
        "running": FINAL_STATUSES,
        "complete": set(),
        "failed": set(),
    }
    if status not in permitted.get(current, set()):
        raise TrainingRunError(f"illegal training run transition: {current} -> {status}")
    document["status"] = status
    document["updated_at"] = datetime.now(UTC).isoformat()
    if detail:
        document["status_detail"] = detail
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return document


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if not normalized:
        raise TrainingRunError("model name cannot be empty")
    return normalized


def _git_sha() -> str:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False
    )
    value = process.stdout.strip()
    return value if re.fullmatch(r"[a-f0-9]{40}", value) else "unavailable"
