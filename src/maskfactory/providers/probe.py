"""Read-only availability and provenance probe for external providers.

The probe never installs packages or downloads weights. It only inspects the
configured paths and workflow-reference registry, hashes artifacts that already
exist, and writes explicit availability/degraded evidence (MF-P0-11).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..governance import provider_activation_issues, validate_external_source_registry

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "configs" / "external_sources.yaml"
DEFAULT_WORKFLOWS = ROOT / "configs" / "civitai_classifications.json"
DEFAULT_OUTPUT = ROOT / "work" / "external_probe" / "provider_probe.json"

MODEL_SUFFIXES = {
    ".bin",
    ".ckpt",
    ".onnx",
    ".pkl",
    ".pt",
    ".pt2",
    ".pth",
    ".safetensors",
    ".torchscript",
}

FALLBACKS = {
    "schp": ["sapiens"],
    "openpose": ["dwpose"],
    "rmbg": ["birefnet"],
    "florence2": ["groundingdino"],
    "faceparse_bisenet": ["sapiens"],
}


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_path(value: str | None, root: Path) -> Path | None:
    if not value or value.startswith("(") or value.startswith("managed by"):
        return None
    normalized = value.replace("\\", os.sep).replace("/", os.sep)
    path = Path(normalized).expanduser()
    return path if path.is_absolute() else root / path


def _artifact_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file() and candidate.suffix.lower() in MODEL_SUFFIXES
    )


def _file_record(path: Path, root: Path) -> dict[str, Any]:
    stat = path.stat()
    try:
        display_path = str(path.relative_to(root))
    except ValueError:
        display_path = str(path)
    return {
        "path": display_path,
        "size_bytes": stat.st_size,
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        "sha256": sha256_file(path),
    }


def _git_commit(path: Path) -> str | None:
    if not (path / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _provider_record(name: str, config: dict[str, Any], root: Path) -> dict[str, Any]:
    configured_path = config.get("local_path")
    path = _resolve_path(configured_path, root)
    external_service = name == "ollama_vlm"
    reference_only = path is None and configured_path and configured_path.startswith("(")

    files: list[dict[str, Any]] = []
    repository_commit = None
    if path and path.exists():
        repository_commit = _git_commit(path) if path.is_dir() else None
        files = [_file_record(item, root) for item in _artifact_files(path)]

    if external_service:
        executable = shutil.which("ollama")
        installed = executable is not None
        status = "available" if installed else "missing"
        resolved_path = executable
    elif reference_only:
        installed = False
        status = "reference_only"
        resolved_path = None
    elif path and path.is_file():
        installed = True
        status = "available"
        resolved_path = str(path)
    elif path and path.is_dir() and (files or repository_commit):
        installed = True
        status = "available"
        resolved_path = str(path)
    else:
        installed = False
        status = "missing"
        resolved_path = str(path) if path else None

    return {
        "provider": name,
        "status": status,
        "installed": installed,
        "degraded": status != "available",
        "fallback_providers": FALLBACKS.get(name, []),
        "configured_path": configured_path,
        "resolved_path": resolved_path,
        "version": config.get("version"),
        "output_type": config.get("output_type"),
        "role": config.get("role"),
        "authority_level": config.get("authority_level"),
        "provenance": {
            "source_url": config.get("source_url"),
            "repo": config.get("repo"),
            "license": config.get("license"),
            "verify_license": bool(config.get("verify_license", False)),
            "repository_commit": repository_commit,
        },
        "files": files,
    }


def _workflow_records(path: Path) -> tuple[str | None, list[dict[str, Any]]]:
    if not path.exists():
        return None, []
    raw = path.read_bytes()
    source = json.loads(raw)
    records = []
    for record in source.get("records", []):
        records.append(
            {
                "id": record["id"],
                "name": record["name"],
                "version": record.get("version"),
                "file_name": record["file_name"],
                "classification": record["classification"],
                "download_status": record["download_status"],
                "source_url": record.get("source_url"),
                "sha256": record.get("sha256"),
                "authority": record["authority"],
            }
        )
    return hashlib.sha256(raw).hexdigest(), records


def probe_external_sources(
    *,
    config_path: Path = DEFAULT_CONFIG,
    workflow_path: Path = DEFAULT_WORKFLOWS,
    output_path: Path = DEFAULT_OUTPUT,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Inspect configured providers and write a JSON evidence report."""
    config_bytes = config_path.read_bytes()
    config = yaml.safe_load(config_bytes)
    policy = validate_external_source_registry(config)
    providers = []
    for name, provider_config in config.get("providers", {}).items():
        record = _provider_record(name, provider_config, root)
        record["activation"] = {}
        for lane in ("adult_nonexplicit", "consensual_explicit_adult"):
            blockers = provider_activation_issues(provider_config, content_lane=lane)
            record["activation"][lane] = {
                "eligible": not blockers,
                "blockers": list(blockers),
            }
        providers.append(record)
    workflow_config_sha256, workflows = _workflow_records(workflow_path)
    counts = {
        status: sum(provider["status"] == status for provider in providers)
        for status in ("available", "missing", "reference_only")
    }
    report = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "downloads_attempted": 0,
        "governance": policy,
        "config_path": str(config_path),
        "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "workflow_config_path": str(workflow_path),
        "workflow_config_sha256": workflow_config_sha256,
        "summary": {"provider_count": len(providers), **counts},
        "providers": providers,
        "workflow_references": workflows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    return report
