"""Transactional model downloads and the only supported checkpoint resolver.

Spec: doc 06 section 3 and doc 04 section 3 (MF-P0-06.01).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CATALOG = PROJECT_ROOT / "models" / "model_sources.yaml"
DEFAULT_REGISTRY = PROJECT_ROOT / "models" / "model_registry.json"
DEFAULT_MODELS_ROOT = PROJECT_ROOT / "models"
CHUNK_SIZE = 1024 * 1024

SmokeRunner = Callable[[Path, Path], dict[str, Any]]
_SMOKE_RUNNERS: dict[str, SmokeRunner] = {}


class ModelRegistryError(RuntimeError):
    """A checkpoint cannot be trusted through the verified registry."""


class ModelFetchError(RuntimeError):
    """A model could not be downloaded, hashed, or smoke-tested."""


def register_smoke_runner(name: str, runner: SmokeRunner) -> None:
    """Register a model-specific one-image smoke runner."""
    if not name or not callable(runner):
        raise ValueError("smoke runner requires a non-empty name and callable")
    _SMOKE_RUNNERS[name] = runner


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_catalog(path: Path) -> dict[str, dict[str, Any]]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ModelFetchError(f"cannot read model catalog {path}: {exc}") from exc
    models = document.get("models")
    if not isinstance(models, dict):
        raise ModelFetchError(f"model catalog {path} must contain a models mapping")
    return models


def catalog_model_keys(path: Path = DEFAULT_CATALOG) -> list[str]:
    """Return catalog keys in declared order after structural validation."""
    return list(_load_catalog(path))


def _load_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": "1.0.0", "models": []}
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelRegistryError(f"cannot read model registry {path}: {exc}") from exc
    if not isinstance(registry.get("models"), list):
        raise ModelRegistryError(f"model registry {path} must contain a models list")
    return registry


def _safe_target(models_root: Path, family: str, filename: str) -> Path:
    if not family or not filename or Path(filename).name != filename:
        raise ModelFetchError("catalog family and filename must be safe relative path components")
    target = (models_root / family / filename).resolve()
    root = models_root.resolve()
    if target == root or root not in target.parents:
        raise ModelFetchError(f"model target escapes models root: {target}")
    return target


def _download(url: str, output: BinaryIO) -> None:
    scheme = urlparse(url).scheme.lower()
    if scheme not in {"https", "http", "file"}:
        raise ModelFetchError(f"unsupported model URL scheme: {scheme or '(none)'}")
    request = Request(url, headers={"User-Agent": "MaskFactory/0.0.1"})
    try:
        with urlopen(request, timeout=120) as response:  # noqa: S310 - catalog is trusted input
            shutil.copyfileobj(response, output, length=CHUNK_SIZE)
    except OSError as exc:
        raise ModelFetchError(f"download failed for {url}: {exc}") from exc


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _registry_entry_path(entry: dict[str, Any], models_root: Path) -> Path:
    relative = entry.get("file")
    if not isinstance(relative, str):
        raise ModelRegistryError("registry entry has no file path")
    path = (PROJECT_ROOT / relative).resolve() if models_root == DEFAULT_MODELS_ROOT else None
    if path is None:
        normalized = Path(relative.replace("\\", "/"))
        parts = normalized.parts
        if parts and parts[0].lower() == "models":
            normalized = Path(*parts[1:])
        path = (models_root / normalized).resolve()
    root = models_root.resolve()
    if path == root or root not in path.parents:
        raise ModelRegistryError(f"registered path escapes models root: {relative}")
    return path


def _relative_registry_path(path: Path, models_root: Path) -> str:
    relative = path.resolve().relative_to(models_root.resolve()).as_posix()
    return f"models/{relative}"


def fetch_models(
    keys: Iterable[str],
    *,
    catalog_path: Path = DEFAULT_CATALOG,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
    smoke_runners: dict[str, SmokeRunner] | None = None,
    now: Callable[[], datetime] | None = None,
) -> list[dict[str, Any]]:
    """Fetch and verify catalog keys, returning entries in request order."""
    catalog = _load_catalog(catalog_path)
    registry = _load_registry(registry_path)
    runners = {**_SMOKE_RUNNERS, **(smoke_runners or {})}
    clock = now or (lambda: datetime.now(UTC))
    results: list[dict[str, Any]] = []

    for key in keys:
        if key not in catalog:
            raise ModelFetchError(f"unknown model key: {key}")
        source = catalog[key]
        required = {"url", "family", "filename", "version_tag", "license", "smoke_test"}
        missing = sorted(required - source.keys())
        if missing:
            raise ModelFetchError(f"catalog entry {key} missing: {', '.join(missing)}")
        target = _safe_target(models_root, str(source["family"]), str(source["filename"]))
        existing = next((item for item in registry["models"] if item.get("key") == key), None)
        if existing and existing.get("verified") is True and target.exists():
            if _sha256(target) == existing.get("sha256"):
                results.append({**existing, "fetch_status": "cached"})
                continue

        runner_name = str(source["smoke_test"])
        runner = runners.get(runner_name)
        if runner is None:
            raise ModelFetchError(f"model {key} requires unavailable smoke runner: {runner_name}")
        smoke_image = (PROJECT_ROOT / str(source.get("smoke_image", ""))).resolve()
        if catalog_path != DEFAULT_CATALOG and source.get("smoke_image"):
            smoke_image = (catalog_path.parent / str(source["smoke_image"])).resolve()
        if not smoke_image.is_file():
            raise ModelFetchError(f"model {key} smoke image is missing: {smoke_image}")

        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".download", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w+b") as output:
                _download(str(source["url"]), output)
                output.flush()
                os.fsync(output.fileno())
            digest = _sha256(temporary)
            expected = source.get("sha256")
            if expected and digest.lower() != str(expected).lower():
                raise ModelFetchError(
                    f"SHA-256 mismatch for {key}: expected {expected}, got {digest}"
                )
            smoke = runner(temporary, smoke_image)
            if smoke.get("passed") is not True or not smoke.get("output_sha256"):
                raise ModelFetchError(f"one-image smoke test failed for {key}: {smoke}")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

        timestamp = clock().astimezone(UTC).isoformat().replace("+00:00", "Z")
        entry = {
            "key": key,
            "role": source.get("role", "unspecified"),
            "source_url": source["url"],
            "file": _relative_registry_path(target, models_root),
            "sha256": digest,
            "version_tag": source["version_tag"],
            "license": source["license"],
            "runtime": source.get("runtime", "unspecified"),
            "vram_note": source.get("vram_note", ""),
            "downloaded_at": timestamp,
            "smoke_test": {
                "runner": runner_name,
                "image": str(source["smoke_image"]),
                "output_sha256": smoke["output_sha256"],
                "verified_at": timestamp,
            },
            "verified": True,
        }
        registry["models"] = [item for item in registry["models"] if item.get("key") != key]
        registry["models"].append(entry)
        registry["models"].sort(key=lambda item: item["key"])
        _atomic_json(registry_path, registry)
        results.append({**entry, "fetch_status": "downloaded"})
    return results


def resolve_registered_model(
    key_or_path: str | Path,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
) -> Path:
    """Resolve only a verified, present, hash-matching registered checkpoint."""
    registry = _load_registry(registry_path)
    entry = next((item for item in registry["models"] if item.get("key") == str(key_or_path)), None)
    requested = None
    if entry is None:
        candidate = Path(key_or_path)
        if isinstance(key_or_path, Path) or candidate.is_absolute() or len(candidate.parts) > 1:
            requested = candidate.resolve()
    if entry is None and requested is not None:
        entry = next(
            (
                item
                for item in registry["models"]
                if _registry_entry_path(item, models_root) == requested
            ),
            None,
        )
    if entry is None:
        raise ModelRegistryError(f"checkpoint is not registered: {key_or_path}")
    if entry.get("verified") is not True:
        raise ModelRegistryError(f"checkpoint is not verified: {entry.get('key')}")
    path = _registry_entry_path(entry, models_root)
    if not path.is_file():
        raise ModelRegistryError(f"registered checkpoint is missing: {path}")
    actual = _sha256(path)
    if actual != entry.get("sha256"):
        raise ModelRegistryError(
            f"checkpoint hash mismatch for {entry.get('key')}: expected {entry.get('sha256')}, got {actual}"
        )
    return path


def load_registered_model(
    key_or_path: str | Path,
    loader: Callable[[Path], Any],
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
) -> Any:
    """Invoke a framework loader only after verified registry resolution."""
    path = resolve_registered_model(
        key_or_path, registry_path=registry_path, models_root=models_root
    )
    return loader(path)
