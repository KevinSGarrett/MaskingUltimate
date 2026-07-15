"""Transactional model downloads and the only supported checkpoint resolver.

Spec: doc 06 section 3 and doc 04 section 3 (MF-P0-06.01).
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import yaml

from ..fs_atomic import replace_with_retry
from ..governance import ACTIVE_REGISTRY_SCHEMA_VERSION, USE_PROFILE, validate_model_registry
from ..ontology import get_ontology
from ..validation import validate_document
from .ontology_contract import (
    ModelOntologyContractError,
    ontology_for_version,
    validate_bodypart_model_contract,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CATALOG = PROJECT_ROOT / "models" / "model_sources.yaml"
DEFAULT_REGISTRY = PROJECT_ROOT / "models" / "model_registry.json"
DEFAULT_MODELS_ROOT = PROJECT_ROOT / "models"
CHUNK_SIZE = 1024 * 1024
OLLAMA_MODEL_NAMES = (
    "qwen2.5vl:7b",
    "llava:13b",
    "qwen2.5:7b-instruct",
)
SERVING_CHAMPION_ROLES = {"champion_bodypart", "champion_hand", "champion_clothing"}
SPECIALIST_CHAMPION_MATRIX_ROLES = {
    "champion_hand": "hand_finger_segmentation",
    "champion_clothing": "clothing_accessory_segmentation",
}
CHAMPION_HAND_CLASS_NAMES = (
    "background",
    "left_hand_base",
    "right_hand_base",
    "left_thumb",
    "right_thumb",
    "left_index_finger",
    "right_index_finger",
    "left_middle_finger",
    "right_middle_finger",
    "left_ring_finger",
    "right_ring_finger",
    "left_pinky",
    "right_pinky",
    "finger_occlusion_boundary",
)
TRAINED_CANDIDATE_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{2,79}$")

SmokeRunner = Callable[[Path, Path], dict[str, Any]]
ServingSmokeRunner = Callable[[Path, Path, str, str], dict[str, Any]]
_SMOKE_RUNNERS: dict[str, SmokeRunner] = {}
_ALLOWED_CONTENT_COMPATIBILITY = {
    "adult_nonexplicit": "allowed",
    "consensual_explicit_adult": "allowed",
}
_UNCLEAR_CONTENT_COMPATIBILITY = {
    "adult_nonexplicit": "unclear",
    "consensual_explicit_adult": "unclear",
}


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
        return {
            "schema_version": ACTIVE_REGISTRY_SCHEMA_VERSION,
            "use_profile": USE_PROFILE,
            "distribution_allowed": False,
            "commercial_deployment": False,
            "content_compatibility": dict(_ALLOWED_CONTENT_COMPATIBILITY),
            "models": [],
        }
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelRegistryError(f"cannot read model registry {path}: {exc}") from exc
    _validate_registry_document(registry, path=path)
    return registry


def _validate_registry_document(registry: dict[str, Any], *, path: Path) -> None:
    """Apply the structural schema and governance policy through one fail-closed path."""
    if not isinstance(registry.get("models"), list):
        raise ModelRegistryError(f"model registry {path} must contain a models list")
    schema_issues = validate_document(registry, "model_registry")
    if schema_issues:
        detail = "; ".join(
            f"{issue.pointer or '/'} [{issue.validator}] {issue.message}" for issue in schema_issues
        )
        raise ModelRegistryError(f"model registry schema is invalid: {detail}")
    try:
        validate_model_registry(registry)
    except ValueError as exc:
        raise ModelRegistryError(f"model registry governance is invalid: {exc}") from exc


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
    parsed = urlparse(url)
    if parsed.netloc.lower() in {"drive.google.com", "docs.google.com"}:
        import gdown

        handle, companion_name = tempfile.mkstemp(suffix=".gdrive")
        os.close(handle)
        companion = Path(companion_name)
        try:
            downloaded = gdown.download(url=url, output=str(companion), quiet=True, fuzzy=True)
            if downloaded is None or not companion.is_file() or companion.stat().st_size == 0:
                raise ModelFetchError(f"Google Drive download failed for {url}")
            with companion.open("rb") as source:
                shutil.copyfileobj(source, output, length=CHUNK_SIZE)
            return
        except (OSError, RuntimeError) as exc:
            raise ModelFetchError(f"Google Drive download failed for {url}: {exc}") from exc
        finally:
            companion.unlink(missing_ok=True)
    request = Request(url, headers={"User-Agent": "MaskFactory/0.0.1"})
    try:
        with urlopen(request, timeout=120) as response:  # noqa: S310 - catalog is trusted input
            shutil.copyfileobj(response, output, length=CHUNK_SIZE)
    except OSError as exc:
        raise ModelFetchError(f"download failed for {url}: {exc}") from exc


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    _validate_registry_document(document, path=path)
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


def _canonical_sha256(document: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _registry_sha256(document: dict[str, Any]) -> str:
    return _canonical_sha256(document)


@contextmanager
def _registry_write_lock(registry_path: Path, *, timeout_seconds: float = 10.0):
    """Serialize governed role transactions across concurrent MaskFactory sessions."""
    lock_path = Path(f"{registry_path}.promotion.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                stale = time.time() - lock_path.stat().st_mtime > 300
            except FileNotFoundError:
                continue
            if stale:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise ModelRegistryError("timed out waiting for the model promotion lock")
            time.sleep(0.05)
    try:
        os.write(descriptor, f"pid={os.getpid()} started={time.time()}\n".encode())
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def _smoke_proposed_registry(
    document: dict[str, Any],
    *,
    registry_path: Path,
    models_root: Path,
    role: str,
    expected_key: str,
    smoke_runner: ServingSmokeRunner,
) -> dict[str, Any]:
    """Validate and smoke an exact proposed registry without activating it."""
    _validate_registry_document(document, path=registry_path)
    registry_path = Path(registry_path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{registry_path.name}.smoke.", suffix=".json", dir=registry_path.parent
    )
    proposed_path = Path(temporary)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        result = smoke_runner(proposed_path, Path(models_root), role, expected_key)
        if not isinstance(result, dict) or result.get("result") != "pass":
            raise ModelRegistryError("serving smoke did not return a passing result")
        json.dumps(result, sort_keys=True)
        return result
    except ModelRegistryError:
        raise
    except Exception as exc:
        raise ModelRegistryError(f"serving smoke failed: {exc}") from exc
    finally:
        proposed_path.unlink(missing_ok=True)


def registry_resolution_smoke(
    registry_path: Path,
    models_root: Path,
    role: str,
    expected_key: str,
) -> dict[str, Any]:
    """Smoke the serving registry contract and exact checkpoint resolution."""
    registry = _load_registry(Path(registry_path))
    owners = [entry for entry in registry["models"] if entry.get("role") == role]
    if len(owners) != 1 or owners[0].get("key") != expected_key:
        raise ModelRegistryError(f"serving smoke expected {expected_key} to own {role}")
    resolved = resolve_registered_role(
        role, registry_path=Path(registry_path), models_root=Path(models_root)
    )
    entry = owners[0]
    if role in SERVING_CHAMPION_ROLES:
        _validate_serving_champion_metadata(entry, role=role, models_root=Path(models_root))
    return {
        "result": "pass",
        "smoke": "registry_resolution_and_serving_contract",
        "role": role,
        "model_key": expected_key,
        "checkpoint_sha256": _sha256(resolved),
    }


def production_bodypart_serving_smoke(
    registry_path: Path,
    models_root: Path,
    role: str,
    expected_key: str,
) -> dict[str, Any]:
    """Run an actual fixed-image inference through the production body-part loader."""
    if role != "champion_bodypart":
        raise ModelRegistryError("production body-part smoke received the wrong role")
    contract = registry_resolution_smoke(registry_path, models_root, role, expected_key)
    fixture = PROJECT_ROOT / "qa" / "fixtures" / "smoke" / "ultralytics_bus_adults.jpg"
    if not fixture.is_file():
        raise ModelRegistryError("production body-part smoke fixture is missing")
    from ..stages.s03_parsing import ParsingError, run_champion_bodypart_prediction

    try:
        with tempfile.TemporaryDirectory(prefix="maskfactory-champion-smoke-") as directory:
            output_dir = Path(directory)
            result = run_champion_bodypart_prediction(
                fixture,
                output_dir,
                registry_path=Path(registry_path),
                models_root=Path(models_root),
            )
            if result is None or result.model_key != expected_key:
                raise ModelRegistryError("production body-part smoke returned the wrong model")
            map_hash = _sha256(result.map_path)
            provenance_hash = _sha256(result.provenance_path)
    except ParsingError as exc:
        raise ModelRegistryError(f"production body-part smoke failed: {exc}") from exc
    return {
        **contract,
        "smoke": "production_fixed_image_inference",
        "fixture": "qa/fixtures/smoke/ultralytics_bus_adults.jpg",
        "output_map_sha256": map_hash,
        "output_provenance_sha256": provenance_hash,
    }


def production_specialist_serving_smoke(
    registry_path: Path,
    models_root: Path,
    role: str,
    expected_key: str,
) -> dict[str, Any]:
    """Load a promoted specialist in its production slot and run fixed-image inference."""
    if role not in SPECIALIST_CHAMPION_MATRIX_ROLES:
        raise ModelRegistryError("production specialist smoke received an unsupported role")
    contract = registry_resolution_smoke(registry_path, models_root, role, expected_key)
    fixture = PROJECT_ROOT / "qa" / "fixtures" / "smoke" / "ultralytics_bus_adults.jpg"
    if not fixture.is_file():
        raise ModelRegistryError("production specialist smoke fixture is missing")
    try:
        import numpy as np
        from PIL import Image

        from ..serve.providers import ServingProviderError, load_production_mmseg_slot
    except ImportError as exc:
        raise ModelRegistryError(
            f"production specialist smoke runtime is unavailable: {exc}"
        ) from exc

    try:
        checkpoint = resolve_registered_role(
            role, registry_path=Path(registry_path), models_root=Path(models_root)
        )
        slot = load_production_mmseg_slot(
            role,
            checkpoint,
            registry_path=Path(registry_path),
            models_root=Path(models_root),
        )
        image = np.asarray(Image.open(fixture).convert("RGB"))
        label = next(name for name in slot.class_names if name != "background")
        masks = slot(image, (label,))
        mask = np.asarray(masks[label])
        if mask.shape != image.shape[:2] or mask.dtype != np.bool_:
            raise ModelRegistryError("production specialist smoke returned an invalid mask")
        output_sha256 = hashlib.sha256(mask.astype(np.uint8).tobytes()).hexdigest()
    except (OSError, ServingProviderError, StopIteration) as exc:
        raise ModelRegistryError(f"production specialist smoke failed: {exc}") from exc
    finally:
        if "slot" in locals():
            slot.close()
    return {
        **contract,
        "smoke": "production_fixed_image_specialist_inference",
        "fixture": "qa/fixtures/smoke/ultralytics_bus_adults.jpg",
        "requested_label": label,
        "output_mask_sha256": output_sha256,
    }


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


def _ollama_key(name: str) -> str:
    return "ollama_" + "".join(
        character if character.isalnum() else "_" for character in name
    ).strip("_")


def _ollama_list_ids(output: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in output.splitlines()[1:]:
        columns = line.split()
        if len(columns) >= 2:
            rows[columns[0]] = columns[1]
    return rows


def register_ollama_models(
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    api_url: str = "http://127.0.0.1:11434/api/tags",
    expected_names: Iterable[str] = OLLAMA_MODEL_NAMES,
    inventory: dict[str, Any] | None = None,
    list_output: str | None = None,
    now: Callable[[], datetime] | None = None,
) -> list[dict[str, Any]]:
    """Cross-check Ollama API manifests against ``ollama list`` and register them."""
    if inventory is None:
        request = Request(api_url, headers={"User-Agent": "MaskFactory/0.0.1"})
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - local Ollama endpoint
                inventory = json.load(response)
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelRegistryError(f"cannot read Ollama inventory from {api_url}: {exc}") from exc
    if list_output is None:
        process = subprocess.run(
            ["docker", "exec", "ollama", "ollama", "list"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if process.returncode != 0:
            process = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        if process.returncode != 0:
            raise ModelRegistryError(
                f"ollama list failed through Docker and native CLI: {process.stderr.strip()}"
            )
        list_output = process.stdout

    api_models = {
        item.get("name"): item
        for item in inventory.get("models", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    cli_ids = _ollama_list_ids(list_output)
    registry = _load_registry(registry_path)
    clock = now or (lambda: datetime.now(UTC))
    timestamp = clock().astimezone(UTC).isoformat().replace("+00:00", "Z")
    results: list[dict[str, Any]] = []

    for name in expected_names:
        model = api_models.get(name)
        if model is None:
            raise ModelRegistryError(f"required Ollama model is missing: {name}")
        digest = model.get("digest")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ModelRegistryError(f"Ollama model has invalid manifest digest: {name}")
        list_id = cli_ids.get(name)
        if not list_id or not digest.startswith(list_id):
            raise ModelRegistryError(
                f"Ollama API/list digest mismatch for {name}: api={digest}, list={list_id}"
            )
        details = model.get("details") if isinstance(model.get("details"), dict) else {}
        entry = {
            "key": _ollama_key(name),
            "role": (
                "local_vlm"
                if "vision" in name or "vl" in name or "llava" in name
                else "manifest_linter"
            ),
            "lifecycle_state": "installed",
            "content_compatibility": dict(_UNCLEAR_CONTENT_COMPATIBILITY),
            "license_review": {"status": "pending"},
            "managed": True,
            "manager": "ollama",
            "ollama_name": name,
            "digest": digest,
            "ollama_list_id": list_id,
            "sha256": digest,
            "size": model.get("size"),
            "format": details.get("format"),
            "family": details.get("family"),
            "parameter_size": details.get("parameter_size"),
            "quantization": details.get("quantization_level"),
            "registered_at": timestamp,
            "availability_check": "api_tags+ollama_list_digest_match",
            "verified": True,
        }
        existing = next(
            (item for item in registry["models"] if item.get("key") == entry["key"]),
            None,
        )
        stable_fields = set(entry) - {"registered_at"}
        if existing and all(existing.get(field) == entry[field] for field in stable_fields):
            results.append({**existing, "register_status": "cached"})
            continue
        registry["models"] = [
            item for item in registry["models"] if item.get("key") != entry["key"]
        ]
        registry["models"].append(entry)
        results.append({**entry, "register_status": "registered"})

    registry["models"].sort(key=lambda item: item["key"])
    _atomic_json(registry_path, registry)
    return results


def resolve_registered_managed_model(
    key: str,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
) -> dict[str, Any]:
    """Return verified metadata for a manager-owned model without inventing a file path."""
    registry = _load_registry(registry_path)
    entry = next((item for item in registry["models"] if item.get("key") == key), None)
    if entry is None:
        raise ModelRegistryError(f"managed model is not registered: {key}")
    if entry.get("managed") is not True or entry.get("manager") != "ollama":
        raise ModelRegistryError(f"registry entry is not an Ollama-managed model: {key}")
    if entry.get("verified") is not True:
        raise ModelRegistryError(f"managed model is not verified: {key}")
    return entry


def verify_registered_model_smokes(
    *,
    catalog_path: Path = DEFAULT_CATALOG,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
    smoke_runners: dict[str, SmokeRunner] | None = None,
) -> list[dict[str, Any]]:
    """Re-run every file-backed model smoke and require its recorded output hash."""
    catalog = _load_catalog(catalog_path)
    registry = _load_registry(registry_path)
    runners = {**_SMOKE_RUNNERS, **(smoke_runners or {})}
    results: list[dict[str, Any]] = []
    for entry in registry["models"]:
        if entry.get("managed") is True:
            continue
        key = entry.get("key")
        if key not in catalog:
            raise ModelRegistryError(f"registered model is absent from catalog: {key}")
        source = catalog[key]
        path = resolve_registered_model(
            str(key), registry_path=registry_path, models_root=models_root
        )
        runner_name = entry.get("smoke_test", {}).get("runner")
        runner = runners.get(runner_name)
        if runner is None:
            raise ModelRegistryError(f"registered model has unavailable smoke runner: {key}")
        smoke_image = (PROJECT_ROOT / str(source.get("smoke_image", ""))).resolve()
        if catalog_path != DEFAULT_CATALOG:
            smoke_image = (catalog_path.parent / str(source.get("smoke_image", ""))).resolve()
        result = runner(path, smoke_image)
        expected = entry.get("smoke_test", {}).get("output_sha256")
        if result.get("passed") is not True or result.get("output_sha256") != expected:
            raise ModelRegistryError(
                f"model smoke mismatch for {key}: expected {expected}, got {result}"
            )
        results.append(
            {
                "key": key,
                "lifecycle_state": entry.get("lifecycle_state"),
                "sha256": entry.get("sha256"),
                "output_sha256": expected,
            }
        )
    return results


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
        cache_metadata_matches = bool(
            existing
            and existing.get("source_url") == source["url"]
            and existing.get("version_tag") == source["version_tag"]
            and existing.get("license") == source["license"]
            and existing.get("smoke_test", {}).get("runner") == source["smoke_test"]
            and existing.get("smoke_test", {}).get("image") == source.get("smoke_image")
        )
        if cache_metadata_matches and existing.get("verified") is True and target.exists():
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
            prefix=f".{target.stem}.download.", suffix=target.suffix, dir=target.parent
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
            "lifecycle_state": "installed",
            "content_compatibility": dict(
                source.get("content_compatibility", _UNCLEAR_CONTENT_COMPATIBILITY)
            ),
            "license_review": dict(source.get("license_review", {"status": "pending"})),
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
    entry = next(
        (item for item in registry["models"] if item.get("key") == str(key_or_path)),
        None,
    )
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
    if entry.get("managed") is True:
        raise ModelRegistryError(
            f"managed model has no checkpoint path; use its {entry.get('manager')} runtime: "
            f"{entry.get('key')}"
        )
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


def resolve_registered_role(
    role: str,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
) -> Path:
    """Resolve exactly one verified file-backed model by authoritative runtime role."""
    registry = _load_registry(registry_path)
    matches = [
        item
        for item in registry["models"]
        if item.get("role") == role and item.get("managed") is not True
    ]
    if len(matches) != 1:
        raise ModelRegistryError(
            f"expected exactly one registered model for role {role!r}, found {len(matches)}"
        )
    return resolve_registered_model(
        str(matches[0]["key"]), registry_path=registry_path, models_root=models_root
    )


def resolve_registered_role_contract(
    role: str,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
) -> tuple[Path, dict[str, Any]]:
    """Resolve one role plus immutable ontology/vocabulary metadata for serving."""
    registry = _load_registry(registry_path)
    matches = [
        item
        for item in registry["models"]
        if item.get("role") == role and item.get("managed") is not True
    ]
    if len(matches) != 1:
        raise ModelRegistryError(
            f"expected exactly one registered model for role {role!r}, found {len(matches)}"
        )
    entry = matches[0]
    path = resolve_registered_model(
        str(entry["key"]), registry_path=registry_path, models_root=models_root
    )
    contract: dict[str, Any] = {"ontology_version": None}
    if role == "champion_bodypart":
        try:
            contract = validate_bodypart_model_contract(entry)
        except ModelOntologyContractError as exc:
            raise ModelRegistryError(str(exc)) from exc
    certificate = entry.get("benchmark_certificate")
    license_review = entry.get("license_review")
    contract.update(
        {
            "model_key": entry["key"],
            "role": entry["role"],
            "lifecycle_state": entry["lifecycle_state"],
            "content_compatibility": dict(entry["content_compatibility"]),
            "license_eligibility": {
                "status": (
                    license_review.get("status") if isinstance(license_review, dict) else "missing"
                ),
                "eligible": isinstance(license_review, dict)
                and license_review.get("status") in {"verified", "not_required"},
            },
            "benchmark_certificate": (
                {
                    "status": "current",
                    "target_role": certificate.get("target_role"),
                    "issued_at": certificate.get("issued_at"),
                    "sha256": certificate.get("sha256"),
                }
                if isinstance(certificate, dict)
                else {
                    "status": "missing",
                    "target_role": None,
                    "issued_at": None,
                    "sha256": None,
                }
            ),
            "rollback": {
                "status": (
                    "declared" if isinstance(entry.get("rollback_provider"), str) else "missing"
                ),
                "provider_key": entry.get("rollback_provider"),
            },
        }
    )
    return path, contract


def register_training_candidate(
    run_root: Path,
    candidate_key: str,
    *,
    candidate_role: str = "challenger_bodypart",
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Atomically copy a sealed completed-run artifact into the verified model registry."""
    if not TRAINED_CANDIDATE_KEY.fullmatch(candidate_key):
        raise ModelRegistryError("training candidate key must be a safe 3-80 character slug")
    if candidate_role.startswith("champion_") or candidate_role != "challenger_bodypart":
        raise ModelRegistryError("completed body-part runs register only as challenger_bodypart")
    root = Path(run_root).resolve()
    try:
        run = json.loads((root / "run.json").read_text(encoding="utf-8"))
        artifact = json.loads((root / "candidate_artifact.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelRegistryError(f"training candidate evidence is unreadable: {exc}") from exc
    if run.get("status") != "complete" or artifact.get("run_id") != run.get("run_id"):
        raise ModelRegistryError("training candidate requires one matching completed run")
    if artifact.get("target_champion_role") != "champion_bodypart":
        raise ModelRegistryError("training candidate target champion role is unsupported")
    for field in ("model", "dataset_ref", "dataset_dvc_md5"):
        if artifact.get(field) != run.get(field):
            raise ModelRegistryError(f"training candidate {field} differs from run.json")
    checkpoint = _safe_run_artifact(root, artifact.get("checkpoint"), expected_parent="ckpts")
    config = _safe_run_artifact(root, artifact.get("inference_config"))
    if _sha256(checkpoint) != artifact.get("checkpoint_sha256"):
        raise ModelRegistryError("training candidate checkpoint hash mismatch")
    if _sha256(config) != artifact.get("inference_config_sha256"):
        raise ModelRegistryError("training candidate inference config hash mismatch")
    class_names = artifact.get("class_names")
    ontology_version = artifact.get("ontology_version")
    class_names_digest = artifact.get("class_names_sha256")
    artifact_hashes = artifact.get("artifact_hashes")
    registry = _load_registry(Path(registry_path))
    if any(item.get("key") == candidate_key for item in registry["models"]):
        raise ModelRegistryError(f"training candidate key already exists: {candidate_key}")
    destination = (Path(models_root).resolve() / "trained" / candidate_key).resolve()
    models_root_resolved = Path(models_root).resolve()
    if models_root_resolved not in destination.parents or destination.exists():
        raise ModelRegistryError(f"training candidate destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{candidate_key}.", dir=destination.parent))
    installed = False
    try:
        target_checkpoint = staging / checkpoint.name
        target_config = staging / "inference_config.py"
        shutil.copy2(checkpoint, target_checkpoint)
        shutil.copy2(config, target_config)
        if _sha256(target_checkpoint) != artifact["checkpoint_sha256"]:
            raise ModelRegistryError("copied training checkpoint failed hash verification")
        if _sha256(target_config) != artifact["inference_config_sha256"]:
            raise ModelRegistryError("copied training config failed hash verification")
        replace_with_retry(staging, destination)
        installed = True
        timestamp = (
            (now or (lambda: datetime.now(UTC)))()
            .astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
        entry = {
            "key": candidate_key,
            "role": candidate_role,
            "lifecycle_state": "installed",
            "content_compatibility": dict(_ALLOWED_CONTENT_COMPATIBILITY),
            "license_review": {"status": "not_required"},
            "target_champion_role": artifact["target_champion_role"],
            "file": _relative_registry_path(destination / checkpoint.name, models_root_resolved),
            "sha256": artifact["checkpoint_sha256"],
            "inference_config": _relative_registry_path(
                destination / "inference_config.py", models_root_resolved
            ),
            "inference_config_sha256": artifact["inference_config_sha256"],
            "class_names": class_names,
            "class_names_sha256": class_names_digest,
            "ontology_version": ontology_version,
            "artifact_hashes": artifact_hashes,
            "version_tag": run["run_id"],
            "training_run": run["run_id"],
            "dataset_ref": run["dataset_ref"],
            "dataset_dvc_md5": run["dataset_dvc_md5"],
            "git_sha": run.get("git_sha"),
            "runtime": "OpenMMLab MMSeg governed training run",
            "license": "MaskFactory-internal",
            "registered_at": timestamp,
            "verified": True,
        }
        _validate_serving_champion_metadata(
            entry, role=str(artifact["target_champion_role"]), models_root=models_root_resolved
        )
        registry["models"].append(entry)
        registry["models"].sort(key=lambda item: str(item.get("key", "")))
        _atomic_json(Path(registry_path), registry)
        return entry
    except Exception:
        if installed:
            shutil.rmtree(destination, ignore_errors=True)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _safe_run_artifact(root: Path, value: Any, *, expected_parent: str | None = None) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ModelRegistryError("training candidate artifact path is invalid")
    path = (root / Path(value.replace("\\", "/"))).resolve()
    if root not in path.parents or not path.is_file():
        raise ModelRegistryError("training candidate artifact is missing or escapes its run")
    if expected_parent is not None and path.parent != root / expected_parent:
        raise ModelRegistryError(f"training candidate artifact must be under {expected_parent}")
    return path


def _validate_serving_champion_metadata(
    entry: dict[str, Any], *, role: str, models_root: Path
) -> None:
    """Refuse promotion of a checkpoint the production MMSeg loader cannot reproduce."""
    config_value = entry.get("inference_config")
    expected_digest = entry.get("inference_config_sha256")
    class_names = entry.get("class_names")
    if not isinstance(config_value, str) or not isinstance(expected_digest, str):
        raise ModelRegistryError("serving champion lacks hashed inference_config metadata")
    normalized = Path(config_value.replace("\\", "/"))
    if normalized.parts and normalized.parts[0].lower() == "models":
        normalized = Path(*normalized.parts[1:])
    root = Path(models_root).resolve()
    config_path = (root / normalized).resolve()
    if config_path == root or root not in config_path.parents or not config_path.is_file():
        raise ModelRegistryError("serving champion inference_config is missing or unsafe")
    actual_digest = _sha256(config_path)
    if actual_digest != expected_digest:
        raise ModelRegistryError(
            "serving champion inference_config hash mismatch: "
            f"expected {expected_digest}, got {actual_digest}"
        )
    if (
        not isinstance(class_names, list)
        or not class_names
        or not all(isinstance(name, str) and name for name in class_names)
        or len(class_names) != len(set(class_names))
    ):
        raise ModelRegistryError("serving champion class_names must be non-empty and unique")
    if role == "champion_hand" and tuple(class_names) != CHAMPION_HAND_CLASS_NAMES:
        raise ModelRegistryError(
            "champion_hand class_names differ from the governed 14-class crop contract"
        )
    if role == "champion_bodypart":
        try:
            contract = validate_bodypart_model_contract(entry, require_explicit=True)
        except ModelOntologyContractError as exc:
            raise ModelRegistryError(str(exc)) from exc
        ontology = ontology_for_version(str(contract["ontology_version"]))
    else:
        ontology = get_ontology()
    expected_map = "material" if role == "champion_clothing" else "part"
    for name in class_names:
        if name == "background" or (
            role == "champion_hand" and name == "finger_occlusion_boundary"
        ):
            continue
        try:
            label = ontology.label(name)
        except Exception as exc:
            raise ModelRegistryError(f"serving champion declares unknown class: {name}") from exc
        if label.map != expected_map:
            raise ModelRegistryError(
                f"serving champion class {name} belongs to {label.map}, expected {expected_map}"
            )


def _validate_promotion_certificate(entry: dict[str, Any], *, role: str) -> None:
    """Require a hash-bound average win and hard-bucket non-inferiority evidence."""
    certificate = entry.get("benchmark_certificate")
    required = {
        "schema_version",
        "target_role",
        "primary_win_or_labor_reduction",
        "hard_bucket_results",
        "frozen_eval_sha256",
        "issued_at",
        "sha256",
    }
    if not isinstance(certificate, dict) or set(certificate) != required:
        raise ModelRegistryError("promotion requires a complete benchmark certificate")
    if (
        certificate["schema_version"] != "1.0.0"
        or certificate["target_role"] != role
        or certificate["primary_win_or_labor_reduction"] is not True
    ):
        raise ModelRegistryError(
            "promotion benchmark certificate scope or primary result is invalid"
        )
    frozen_hash = certificate["frozen_eval_sha256"]
    if (
        not isinstance(frozen_hash, str)
        or len(frozen_hash) != 64
        or any(character not in "0123456789abcdef" for character in frozen_hash)
    ):
        raise ModelRegistryError("promotion benchmark frozen-evaluation hash is invalid")
    results = certificate["hard_bucket_results"]
    if not isinstance(results, list) or not results:
        raise ModelRegistryError("promotion benchmark has no hard-bucket results")
    for result in results:
        if (
            not isinstance(result, dict)
            or set(result) != {"bucket", "observed_delta", "noninferiority_margin", "passed"}
            or not isinstance(result["bucket"], str)
            or not result["bucket"]
            or not isinstance(result["observed_delta"], (int, float))
            or not isinstance(result["noninferiority_margin"], (int, float))
            or float(result["noninferiority_margin"]) < 0
            or result["passed"] is not True
            or float(result["observed_delta"]) < -float(result["noninferiority_margin"])
        ):
            raise ModelRegistryError("promotion benchmark hard-bucket non-inferiority failed")
    try:
        issued_at = datetime.fromisoformat(str(certificate["issued_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ModelRegistryError("promotion benchmark issued_at is invalid") from exc
    if issued_at.tzinfo is None:
        raise ModelRegistryError("promotion benchmark issued_at must include a timezone")
    claimed = certificate["sha256"]
    payload = {key: value for key, value in certificate.items() if key != "sha256"}
    actual = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if claimed != actual:
        raise ModelRegistryError("promotion benchmark certificate hash mismatch")


def _validate_specialist_transaction_record(record: dict[str, Any]) -> None:
    schema_issues = validate_document(record, "specialist_champion_transaction")
    if schema_issues:
        detail = "; ".join(
            f"{issue.pointer or '/'} [{issue.validator}] {issue.message}" for issue in schema_issues
        )
        raise ModelRegistryError(f"specialist transaction schema is invalid: {detail}")
    required = {
        "schema_version",
        "action",
        "transaction_kind",
        "transaction_id",
        "recorded_at",
        "candidate_key",
        "candidate_previous_role",
        "candidate_previous_lifecycle_state",
        "incumbent_key",
        "incumbent_previous_role",
        "incumbent_previous_lifecycle_state",
        "champion_role",
        "matrix_role",
        "matrix_certificate_id",
        "matrix_certificate_sha256",
        "specialist_packet_sha256",
        "benchmark_certificate_sha256",
        "candidate_checkpoint_sha256",
        "incumbent_checkpoint_sha256",
        "registry_before_sha256",
        "registry_after_sha256",
        "serving_smoke",
        "sha256",
    }
    if set(record) != required or record.get("schema_version") != "2.0.0":
        raise ModelRegistryError("specialist transaction record is incomplete")
    champion_role = record.get("champion_role")
    if (
        record.get("action") != "promote"
        or record.get("transaction_kind") != "specialist_champion"
        or champion_role not in SPECIALIST_CHAMPION_MATRIX_ROLES
        or record.get("matrix_role") != SPECIALIST_CHAMPION_MATRIX_ROLES.get(champion_role)
        or record.get("candidate_previous_lifecycle_state") != "benchmarked"
        or record.get("incumbent_previous_role") != champion_role
        or record.get("incumbent_previous_lifecycle_state") != "promoted"
        or not isinstance(record.get("transaction_id"), str)
        or not re.fullmatch(r"[a-f0-9]{32}", record["transaction_id"])
    ):
        raise ModelRegistryError("specialist transaction record scope is invalid")
    if (
        not isinstance(record.get("candidate_key"), str)
        or not record["candidate_key"]
        or not isinstance(record.get("incumbent_key"), str)
        or not record["incumbent_key"]
        or record["candidate_key"] == record["incumbent_key"]
        or not isinstance(record.get("candidate_previous_role"), str)
        or not record["candidate_previous_role"]
        or record["candidate_previous_role"] == champion_role
    ):
        raise ModelRegistryError("specialist transaction providers are invalid")
    if not isinstance(record.get("matrix_certificate_id"), str) or not re.fullmatch(
        r"[a-f0-9]{24}", record["matrix_certificate_id"]
    ):
        raise ModelRegistryError("specialist transaction matrix certificate id is invalid")
    for field in (
        "matrix_certificate_sha256",
        "specialist_packet_sha256",
        "benchmark_certificate_sha256",
        "candidate_checkpoint_sha256",
        "incumbent_checkpoint_sha256",
        "registry_before_sha256",
        "registry_after_sha256",
    ):
        if not isinstance(record.get(field), str) or not re.fullmatch(
            r"[a-f0-9]{64}", record[field]
        ):
            raise ModelRegistryError(f"specialist transaction {field} is invalid")
    smoke = record.get("serving_smoke")
    if (
        not isinstance(smoke, dict)
        or smoke.get("result") != "pass"
        or smoke.get("role") != champion_role
        or smoke.get("model_key") != record["candidate_key"]
    ):
        raise ModelRegistryError("specialist transaction serving smoke is invalid")
    try:
        recorded_at = datetime.fromisoformat(str(record["recorded_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ModelRegistryError("specialist transaction timestamp is invalid") from exc
    if recorded_at.tzinfo is None:
        raise ModelRegistryError("specialist transaction timestamp lacks timezone")
    payload = {key: value for key, value in record.items() if key != "sha256"}
    if record["sha256"] != _canonical_sha256(payload):
        raise ModelRegistryError("specialist transaction record hash mismatch")


def _validate_specialist_rollback_record(record: dict[str, Any]) -> None:
    schema_issues = validate_document(record, "specialist_champion_rollback")
    if schema_issues:
        detail = "; ".join(
            f"{issue.pointer or '/'} [{issue.validator}] {issue.message}" for issue in schema_issues
        )
        raise ModelRegistryError(f"specialist rollback schema is invalid: {detail}")
    required = {
        "schema_version",
        "action",
        "transaction_kind",
        "transaction_id",
        "promotion_transaction_id",
        "recorded_at",
        "candidate_key",
        "incumbent_key",
        "champion_role",
        "registry_before_sha256",
        "registry_after_sha256",
        "serving_smoke",
        "sha256",
    }
    if set(record) != required or record.get("schema_version") != "2.0.0":
        raise ModelRegistryError("specialist rollback record is incomplete")
    if (
        record.get("action") != "rollback"
        or record.get("transaction_kind") != "specialist_champion"
        or record.get("champion_role") not in SPECIALIST_CHAMPION_MATRIX_ROLES
        or not isinstance(record.get("transaction_id"), str)
        or not re.fullmatch(r"[a-f0-9]{32}", record["transaction_id"])
        or not isinstance(record.get("promotion_transaction_id"), str)
        or not re.fullmatch(r"[a-f0-9]{32}", record["promotion_transaction_id"])
        or record["transaction_id"] == record["promotion_transaction_id"]
        or not isinstance(record.get("candidate_key"), str)
        or not record["candidate_key"]
        or not isinstance(record.get("incumbent_key"), str)
        or not record["incumbent_key"]
        or record["candidate_key"] == record["incumbent_key"]
    ):
        raise ModelRegistryError("specialist rollback record scope is invalid")
    for field in ("registry_before_sha256", "registry_after_sha256"):
        if not isinstance(record.get(field), str) or not re.fullmatch(
            r"[a-f0-9]{64}", record[field]
        ):
            raise ModelRegistryError(f"specialist rollback {field} is invalid")
    smoke = record.get("serving_smoke")
    if (
        not isinstance(smoke, dict)
        or smoke.get("result") != "pass"
        or smoke.get("role") != record["champion_role"]
        or smoke.get("model_key") != record["incumbent_key"]
    ):
        raise ModelRegistryError("specialist rollback serving smoke is invalid")
    try:
        recorded_at = datetime.fromisoformat(str(record["recorded_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ModelRegistryError("specialist rollback timestamp is invalid") from exc
    if recorded_at.tzinfo is None:
        raise ModelRegistryError("specialist rollback timestamp lacks timezone")
    payload = {key: value for key, value in record.items() if key != "sha256"}
    if record["sha256"] != _canonical_sha256(payload):
        raise ModelRegistryError("specialist rollback record hash mismatch")


def _promote_specialist_role_unlocked(
    candidate_key: str,
    role: str,
    *,
    matrix_bundle_root: Path,
    registry_path: Path,
    models_root: Path,
    history_path: Path,
    smoke_runner: ServingSmokeRunner,
    promoted_at: str | None,
) -> dict[str, Any]:
    from ..providers.matrix_promotion import (
        MatrixPromotionCertificateError,
        load_and_verify_matrix_promotion_bundle,
    )

    matrix_role = SPECIALIST_CHAMPION_MATRIX_ROLES.get(role)
    if matrix_role is None:
        raise ModelRegistryError("strict specialist promotion supports hand or clothing champions")
    try:
        bundle = load_and_verify_matrix_promotion_bundle(matrix_bundle_root)
    except MatrixPromotionCertificateError as exc:
        raise ModelRegistryError(str(exc)) from exc
    certificate = bundle["certificate"]
    packet = bundle["specialist_packets"][matrix_role]
    bindings = [row for row in certificate["role_bindings"] if row["role"] == matrix_role]
    if len(bindings) != 1:
        raise ModelRegistryError(
            "matrix certificate specialist role binding is missing or ambiguous"
        )
    binding = bindings[0]

    registry_path = Path(registry_path)
    models_root = Path(models_root)
    history_path = Path(history_path)
    before = _load_registry(registry_path)
    proposed = copy.deepcopy(before)
    by_key = {str(entry["key"]): entry for entry in proposed["models"]}
    candidate = by_key.get(candidate_key)
    if (
        candidate is None
        or candidate.get("managed") is True
        or candidate.get("verified") is not True
        or candidate.get("lifecycle_state") != "benchmarked"
    ):
        raise ModelRegistryError("specialist promotion requires a verified benchmarked candidate")
    if candidate.get("role") == role:
        raise ModelRegistryError(f"candidate already owns {role}")
    incumbents = [entry for entry in proposed["models"] if entry.get("role") == role]
    if len(incumbents) != 1 or incumbents[0].get("lifecycle_state") != "promoted":
        raise ModelRegistryError("specialist promotion requires exactly one promoted incumbent")
    incumbent = incumbents[0]
    if (
        packet.get("candidate_key") != candidate_key
        or binding.get("candidate_key") != candidate_key
        or packet.get("rollback_evidence", {}).get("incumbent_provider") != incumbent.get("key")
        or binding.get("incumbent_provider") != incumbent.get("key")
        or binding.get("prerequisite_sha256") != packet.get("sha256")
    ):
        raise ModelRegistryError("matrix promotion candidate or incumbent binding is stale")
    identities = packet.get("identity_hashes", {})
    if identities.get("checkpoint_sha256") != candidate.get("sha256"):
        raise ModelRegistryError("specialist packet checkpoint differs from registry candidate")
    artifact_hashes = candidate.get("artifact_hashes")
    if not isinstance(artifact_hashes, dict) or any(
        artifact_hashes.get(field) != identities.get(field)
        for field in (
            "source_tree_sha256",
            "runtime_lock_sha256",
            "license_evidence_sha256",
            "content_decision_sha256",
        )
    ):
        raise ModelRegistryError("specialist registry artifact hashes differ from signed packet")
    if candidate.get("content_compatibility") != packet.get("content_compatibility"):
        raise ModelRegistryError("specialist registry content decision differs from signed packet")
    resolve_registered_model(candidate_key, registry_path=registry_path, models_root=models_root)
    _validate_serving_champion_metadata(candidate, role=role, models_root=models_root)
    _validate_promotion_certificate(candidate, role=role)
    benchmark_certificate = candidate["benchmark_certificate"]

    candidate_previous_role = str(candidate["role"])
    candidate["role"] = role
    candidate["lifecycle_state"] = "promoted"
    incumbent["role"] = candidate_previous_role
    incumbent["lifecycle_state"] = "benchmarked"
    smoke = _smoke_proposed_registry(
        proposed,
        registry_path=registry_path,
        models_root=models_root,
        role=role,
        expected_key=candidate_key,
        smoke_runner=smoke_runner,
    )
    timestamp = promoted_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    record: dict[str, Any] = {
        "schema_version": "2.0.0",
        "action": "promote",
        "transaction_kind": "specialist_champion",
        "transaction_id": uuid.uuid4().hex,
        "recorded_at": timestamp,
        "candidate_key": candidate_key,
        "candidate_previous_role": candidate_previous_role,
        "candidate_previous_lifecycle_state": "benchmarked",
        "incumbent_key": str(incumbent["key"]),
        "incumbent_previous_role": role,
        "incumbent_previous_lifecycle_state": "promoted",
        "champion_role": role,
        "matrix_role": matrix_role,
        "matrix_certificate_id": str(certificate["certificate_id"]),
        "matrix_certificate_sha256": str(certificate["certificate_sha256"]),
        "specialist_packet_sha256": str(packet["sha256"]),
        "benchmark_certificate_sha256": str(benchmark_certificate["sha256"]),
        "candidate_checkpoint_sha256": str(candidate["sha256"]),
        "incumbent_checkpoint_sha256": str(incumbent["sha256"]),
        "registry_before_sha256": _registry_sha256(before),
        "registry_after_sha256": _registry_sha256(proposed),
        "serving_smoke": smoke,
    }
    record["sha256"] = _canonical_sha256(record)
    _validate_specialist_transaction_record(record)
    _atomic_json(registry_path, proposed)
    try:
        _append_jsonl(history_path, record)
    except Exception as exc:
        try:
            _atomic_json(registry_path, before)
        except Exception as restore_exc:
            raise ModelRegistryError(
                "specialist promotion history failed and registry restoration also failed: "
                f"history={exc}; restore={restore_exc}"
            ) from restore_exc
        raise ModelRegistryError(
            f"specialist promotion history failed; registry restored: {exc}"
        ) from exc
    return record


def promote_model_role(
    candidate_key: str,
    role: str,
    *,
    matrix_bundle_root: Path | None = None,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
    history_path: Path = PROJECT_ROOT / "runs" / "champion_history.jsonl",
    smoke_runner: ServingSmokeRunner | None = None,
    promoted_at: str | None = None,
) -> dict[str, Any]:
    """Transactionally promote a signed matrix-bound hand or clothing specialist."""
    if role == "champion_bodypart":
        raise ModelRegistryError(
            "champion_bodypart requires the strict custom-segmenter promotion transaction"
        )
    if matrix_bundle_root is None:
        raise ModelRegistryError("specialist promotion requires a verified matrix bundle")
    with _registry_write_lock(Path(registry_path)):
        return _promote_specialist_role_unlocked(
            candidate_key,
            role,
            matrix_bundle_root=matrix_bundle_root,
            registry_path=registry_path,
            models_root=models_root,
            history_path=history_path,
            smoke_runner=smoke_runner or production_specialist_serving_smoke,
            promoted_at=promoted_at,
        )


def _rollback_specialist_role_unlocked(
    record: dict[str, Any],
    *,
    registry_path: Path,
    models_root: Path,
    history_path: Path,
    smoke_runner: ServingSmokeRunner,
    rolled_back_at: str | None,
) -> dict[str, Any]:
    _validate_specialist_transaction_record(record)
    registry_path = Path(registry_path)
    before = _load_registry(registry_path)
    if _registry_sha256(before) != record["registry_after_sha256"]:
        raise ModelRegistryError("cannot rollback specialist: registry changed after promotion")
    proposed = copy.deepcopy(before)
    by_key = {str(entry["key"]): entry for entry in proposed["models"]}
    candidate = by_key.get(str(record["candidate_key"]))
    incumbent = by_key.get(str(record["incumbent_key"]))
    if candidate is None or incumbent is None:
        raise ModelRegistryError("cannot rollback specialist: recorded provider is missing")
    if (
        candidate.get("role") != record["champion_role"]
        or candidate.get("lifecycle_state") != "promoted"
        or incumbent.get("role") != record["candidate_previous_role"]
        or incumbent.get("lifecycle_state") != "benchmarked"
    ):
        raise ModelRegistryError("cannot rollback specialist: role or lifecycle changed")
    candidate["role"] = record["candidate_previous_role"]
    candidate["lifecycle_state"] = record["candidate_previous_lifecycle_state"]
    incumbent["role"] = record["incumbent_previous_role"]
    incumbent["lifecycle_state"] = record["incumbent_previous_lifecycle_state"]
    if _registry_sha256(proposed) != record["registry_before_sha256"]:
        raise ModelRegistryError(
            "cannot rollback specialist: original registry is not reproducible"
        )
    smoke = _smoke_proposed_registry(
        proposed,
        registry_path=registry_path,
        models_root=Path(models_root),
        role=str(record["champion_role"]),
        expected_key=str(record["incumbent_key"]),
        smoke_runner=smoke_runner,
    )
    rollback: dict[str, Any] = {
        "schema_version": "2.0.0",
        "action": "rollback",
        "transaction_kind": "specialist_champion",
        "transaction_id": uuid.uuid4().hex,
        "promotion_transaction_id": record["transaction_id"],
        "recorded_at": rolled_back_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "candidate_key": record["candidate_key"],
        "incumbent_key": record["incumbent_key"],
        "champion_role": record["champion_role"],
        "registry_before_sha256": record["registry_after_sha256"],
        "registry_after_sha256": record["registry_before_sha256"],
        "serving_smoke": smoke,
    }
    rollback["sha256"] = _canonical_sha256(rollback)
    _validate_specialist_rollback_record(rollback)
    _atomic_json(registry_path, proposed)
    try:
        _append_jsonl(Path(history_path), rollback)
    except Exception as exc:
        try:
            _atomic_json(registry_path, before)
        except Exception as restore_exc:
            raise ModelRegistryError(
                "specialist rollback history failed and promoted registry restoration also failed: "
                f"history={exc}; restore={restore_exc}"
            ) from restore_exc
        raise ModelRegistryError(
            f"specialist rollback history failed; promoted registry restored: {exc}"
        ) from exc
    return rollback


def rollback_model_role(
    record: dict[str, Any],
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
    history_path: Path = PROJECT_ROOT / "runs" / "champion_history.jsonl",
    smoke_runner: ServingSmokeRunner | None = None,
    rolled_back_at: str | None = None,
) -> dict[str, Any]:
    """Rollback one strict specialist transaction with smoke-before-activation."""
    with _registry_write_lock(Path(registry_path)):
        return _rollback_specialist_role_unlocked(
            record,
            registry_path=registry_path,
            models_root=models_root,
            history_path=history_path,
            smoke_runner=smoke_runner or production_specialist_serving_smoke,
            rolled_back_at=rolled_back_at,
        )


def load_specialist_promotion_transaction(
    transaction_id: str, *, history_path: Path
) -> dict[str, Any]:
    """Load one unused strict specialist promotion from append-only history."""
    if not transaction_id or not re.fullmatch(r"[a-f0-9]{32}", transaction_id):
        raise ModelRegistryError("specialist promotion transaction id is invalid")
    records: list[dict[str, Any]] = []
    for number, line in enumerate(Path(history_path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ModelRegistryError(f"invalid champion history row {number}: {exc}") from exc
        if isinstance(value, dict):
            records.append(value)
    matches = [
        value
        for value in records
        if value.get("action") == "promote"
        and value.get("transaction_kind") == "specialist_champion"
        and value.get("transaction_id") == transaction_id
    ]
    if len(matches) != 1:
        raise ModelRegistryError("specialist promotion transaction id is missing or ambiguous")
    rollback_matches = [
        value
        for value in records
        if value.get("action") == "rollback"
        and value.get("transaction_kind") == "specialist_champion"
        and value.get("promotion_transaction_id") == transaction_id
    ]
    for rollback in rollback_matches:
        _validate_specialist_rollback_record(rollback)
    if rollback_matches:
        raise ModelRegistryError("specialist promotion transaction was already rolled back")
    record = matches[0]
    _validate_specialist_transaction_record(record)
    return record


def _promote_custom_segmenter_role_unlocked(
    candidate_key: str,
    certificate: dict[str, Any],
    expected_identity_hashes: dict[str, Any],
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
    history_path: Path = PROJECT_ROOT / "runs" / "champion_history.jsonl",
    smoke_runner: ServingSmokeRunner | None = None,
    promoted_at: str | None = None,
) -> dict[str, Any]:
    """Promote one benchmarked custom segmenter with an atomic, smoke-first swap.

    Certificate validation grants prerequisites only.  This function is the
    separate authority boundary that mutates the body-part champion role.
    """
    from ..training.promotion_policy import (
        CustomSegmenterPromotionError,
        validate_custom_segmenter_promotion_certificate,
    )

    try:
        summary = validate_custom_segmenter_promotion_certificate(
            certificate,
            expected_identity_hashes=expected_identity_hashes,
        )
    except CustomSegmenterPromotionError as exc:
        raise ModelRegistryError(str(exc)) from exc
    if summary["candidate_key"] != candidate_key:
        raise ModelRegistryError("promotion candidate differs from the validated certificate")
    if smoke_runner is None:
        smoke_runner = production_bodypart_serving_smoke

    registry_path = Path(registry_path)
    models_root = Path(models_root)
    history_path = Path(history_path)
    before = _load_registry(registry_path)
    proposed = copy.deepcopy(before)
    by_key = {str(entry["key"]): entry for entry in proposed["models"]}
    candidate = by_key.get(candidate_key)
    if (
        candidate is None
        or candidate.get("managed") is True
        or candidate.get("verified") is not True
    ):
        raise ModelRegistryError(
            f"promotion candidate is not a verified checkpoint: {candidate_key}"
        )
    if candidate.get("lifecycle_state") != "benchmarked":
        raise ModelRegistryError("custom segmenter promotion requires lifecycle benchmarked")
    if candidate.get("role") == "champion_bodypart":
        raise ModelRegistryError("custom segmenter candidate already owns champion_bodypart")
    resolve_registered_model(candidate_key, registry_path=registry_path, models_root=models_root)
    _validate_serving_champion_metadata(
        candidate, role="champion_bodypart", models_root=models_root
    )
    checkpoint_hash = expected_identity_hashes.get("checkpoint_sha256")
    if checkpoint_hash != candidate.get("sha256"):
        raise ModelRegistryError("current checkpoint identity differs from the registry candidate")

    incumbents = [entry for entry in proposed["models"] if entry.get("role") == "champion_bodypart"]
    if len(incumbents) != 1:
        raise ModelRegistryError("custom segmenter promotion requires exactly one incumbent")
    incumbent = incumbents[0]
    if incumbent.get("key") != summary["rollback_provider"]:
        raise ModelRegistryError("certificate rollback provider differs from the incumbent")
    if incumbent.get("lifecycle_state") != "promoted":
        raise ModelRegistryError("custom segmenter incumbent must have lifecycle promoted")

    candidate_previous_role = str(candidate["role"])
    candidate["role"] = "champion_bodypart"
    candidate["lifecycle_state"] = "promoted"
    incumbent["role"] = candidate_previous_role
    incumbent["lifecycle_state"] = "benchmarked"
    smoke = _smoke_proposed_registry(
        proposed,
        registry_path=registry_path,
        models_root=models_root,
        role="champion_bodypart",
        expected_key=candidate_key,
        smoke_runner=smoke_runner,
    )
    timestamp = promoted_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    record: dict[str, Any] = {
        "schema_version": "2.0.0",
        "action": "promote",
        "transaction_id": uuid.uuid4().hex,
        "recorded_at": timestamp,
        "candidate_key": candidate_key,
        "candidate_previous_role": candidate_previous_role,
        "candidate_previous_lifecycle_state": "benchmarked",
        "incumbent_key": str(incumbent["key"]),
        "incumbent_previous_role": "champion_bodypart",
        "incumbent_previous_lifecycle_state": "promoted",
        "champion_role": "champion_bodypart",
        "certificate_sha256": str(certificate["sha256"]),
        "registry_before_sha256": _registry_sha256(before),
        "registry_after_sha256": _registry_sha256(proposed),
        "serving_smoke": smoke,
    }
    record["sha256"] = _canonical_sha256(record)

    _atomic_json(registry_path, proposed)
    try:
        _append_jsonl(history_path, record)
    except Exception as exc:
        try:
            _atomic_json(registry_path, before)
        except Exception as restore_exc:
            raise ModelRegistryError(
                "promotion history failed and exact registry restoration also failed: "
                f"history={exc}; restore={restore_exc}"
            ) from restore_exc
        raise ModelRegistryError(f"promotion history failed; registry restored: {exc}") from exc
    return record


def promote_custom_segmenter_role(
    candidate_key: str,
    certificate: dict[str, Any],
    expected_identity_hashes: dict[str, Any],
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
    history_path: Path = PROJECT_ROOT / "runs" / "champion_history.jsonl",
    smoke_runner: ServingSmokeRunner | None = None,
    promoted_at: str | None = None,
) -> dict[str, Any]:
    """Serialize and execute the strict custom-segmenter promotion transaction."""
    with _registry_write_lock(Path(registry_path)):
        return _promote_custom_segmenter_role_unlocked(
            candidate_key,
            certificate,
            expected_identity_hashes,
            registry_path=registry_path,
            models_root=models_root,
            history_path=history_path,
            smoke_runner=smoke_runner,
            promoted_at=promoted_at,
        )


def _validate_custom_segmenter_transaction_record(record: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "action",
        "transaction_id",
        "recorded_at",
        "candidate_key",
        "candidate_previous_role",
        "candidate_previous_lifecycle_state",
        "incumbent_key",
        "incumbent_previous_role",
        "incumbent_previous_lifecycle_state",
        "champion_role",
        "certificate_sha256",
        "registry_before_sha256",
        "registry_after_sha256",
        "serving_smoke",
        "sha256",
    }
    if set(record) != required or record.get("schema_version") != "2.0.0":
        raise ModelRegistryError("custom segmenter transaction record is incomplete")
    if (
        record.get("action") != "promote"
        or record.get("champion_role") != "champion_bodypart"
        or record.get("candidate_previous_lifecycle_state") != "benchmarked"
        or record.get("incumbent_previous_role") != "champion_bodypart"
        or record.get("incumbent_previous_lifecycle_state") != "promoted"
        or not isinstance(record.get("transaction_id"), str)
        or not record["transaction_id"]
    ):
        raise ModelRegistryError("custom segmenter transaction record scope is invalid")
    if not re.fullmatch(r"[a-f0-9]{32}", record["transaction_id"]):
        raise ModelRegistryError("custom segmenter transaction id is invalid")
    if (
        not isinstance(record.get("candidate_key"), str)
        or not record["candidate_key"]
        or not isinstance(record.get("incumbent_key"), str)
        or not record["incumbent_key"]
        or record["candidate_key"] == record["incumbent_key"]
        or not isinstance(record.get("candidate_previous_role"), str)
        or not record["candidate_previous_role"]
        or record["candidate_previous_role"] == "champion_bodypart"
    ):
        raise ModelRegistryError("custom segmenter transaction providers are invalid")
    for field in (
        "certificate_sha256",
        "registry_before_sha256",
        "registry_after_sha256",
    ):
        if not isinstance(record.get(field), str) or not re.fullmatch(
            r"[a-f0-9]{64}", record[field]
        ):
            raise ModelRegistryError(f"custom segmenter transaction {field} is invalid")
    smoke = record.get("serving_smoke")
    if (
        not isinstance(smoke, dict)
        or smoke.get("result") != "pass"
        or smoke.get("model_key") != record["candidate_key"]
    ):
        raise ModelRegistryError("custom segmenter transaction serving smoke is invalid")
    try:
        recorded_at = datetime.fromisoformat(str(record["recorded_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ModelRegistryError("custom segmenter transaction timestamp is invalid") from exc
    if recorded_at.tzinfo is None:
        raise ModelRegistryError("custom segmenter transaction timestamp lacks timezone")
    claimed = record["sha256"]
    payload = {key: value for key, value in record.items() if key != "sha256"}
    if claimed != _canonical_sha256(payload):
        raise ModelRegistryError("custom segmenter transaction record hash mismatch")


def _rollback_custom_segmenter_role_unlocked(
    record: dict[str, Any],
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
    history_path: Path = PROJECT_ROOT / "runs" / "champion_history.jsonl",
    smoke_runner: ServingSmokeRunner | None = None,
    rolled_back_at: str | None = None,
) -> dict[str, Any]:
    """Restore the exact incumbent role/lifecycle after a smoke-first check."""
    _validate_custom_segmenter_transaction_record(record)
    if smoke_runner is None:
        smoke_runner = production_bodypart_serving_smoke
    registry_path = Path(registry_path)
    models_root = Path(models_root)
    history_path = Path(history_path)
    before = _load_registry(registry_path)
    if _registry_sha256(before) != record["registry_after_sha256"]:
        raise ModelRegistryError("cannot rollback: registry changed after the promotion")
    proposed = copy.deepcopy(before)
    by_key = {str(entry["key"]): entry for entry in proposed["models"]}
    candidate = by_key.get(str(record["candidate_key"]))
    incumbent = by_key.get(str(record["incumbent_key"]))
    if candidate is None or incumbent is None:
        raise ModelRegistryError("cannot rollback: recorded provider is missing")
    if (
        candidate.get("role") != "champion_bodypart"
        or candidate.get("lifecycle_state") != "promoted"
        or incumbent.get("role") != record["candidate_previous_role"]
        or incumbent.get("lifecycle_state") != "benchmarked"
    ):
        raise ModelRegistryError("cannot rollback: role or lifecycle changed after promotion")
    candidate["role"] = record["candidate_previous_role"]
    candidate["lifecycle_state"] = record["candidate_previous_lifecycle_state"]
    incumbent["role"] = record["incumbent_previous_role"]
    incumbent["lifecycle_state"] = record["incumbent_previous_lifecycle_state"]
    if _registry_sha256(proposed) != record["registry_before_sha256"]:
        raise ModelRegistryError(
            "cannot rollback: exact pre-promotion registry is not reproducible"
        )
    smoke = _smoke_proposed_registry(
        proposed,
        registry_path=registry_path,
        models_root=models_root,
        role="champion_bodypart",
        expected_key=str(record["incumbent_key"]),
        smoke_runner=smoke_runner,
    )
    timestamp = rolled_back_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    rollback_record: dict[str, Any] = {
        "schema_version": "2.0.0",
        "action": "rollback",
        "transaction_id": uuid.uuid4().hex,
        "promotion_transaction_id": record["transaction_id"],
        "recorded_at": timestamp,
        "candidate_key": record["candidate_key"],
        "incumbent_key": record["incumbent_key"],
        "champion_role": "champion_bodypart",
        "registry_before_sha256": record["registry_after_sha256"],
        "registry_after_sha256": record["registry_before_sha256"],
        "serving_smoke": smoke,
    }
    rollback_record["sha256"] = _canonical_sha256(rollback_record)
    _atomic_json(registry_path, proposed)
    try:
        _append_jsonl(history_path, rollback_record)
    except Exception as exc:
        try:
            _atomic_json(registry_path, before)
        except Exception as restore_exc:
            raise ModelRegistryError(
                "rollback history failed and promoted registry restoration also failed: "
                f"history={exc}; restore={restore_exc}"
            ) from restore_exc
        raise ModelRegistryError(
            f"rollback history failed; promoted registry restored: {exc}"
        ) from exc
    return rollback_record


def rollback_custom_segmenter_role(
    record: dict[str, Any],
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
    history_path: Path = PROJECT_ROOT / "runs" / "champion_history.jsonl",
    smoke_runner: ServingSmokeRunner | None = None,
    rolled_back_at: str | None = None,
) -> dict[str, Any]:
    """Serialize and execute one exact custom-segmenter rollback transaction."""
    with _registry_write_lock(Path(registry_path)):
        return _rollback_custom_segmenter_role_unlocked(
            record,
            registry_path=registry_path,
            models_root=models_root,
            history_path=history_path,
            smoke_runner=smoke_runner,
            rolled_back_at=rolled_back_at,
        )


def load_promotion_transaction(transaction_id: str, *, history_path: Path) -> dict[str, Any]:
    """Load one unrolled custom-segmenter promotion by immutable transaction id."""
    if not transaction_id:
        raise ModelRegistryError("promotion transaction id is required")
    records: list[dict[str, Any]] = []
    for number, line in enumerate(Path(history_path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ModelRegistryError(f"invalid champion history row {number}: {exc}") from exc
        if isinstance(value, dict):
            records.append(value)
    matches = [
        value
        for value in records
        if value.get("action") == "promote" and value.get("transaction_id") == transaction_id
    ]
    if len(matches) != 1:
        raise ModelRegistryError("promotion transaction id is missing or ambiguous")
    if any(
        value.get("action") == "rollback"
        and value.get("promotion_transaction_id") == transaction_id
        for value in records
    ):
        raise ModelRegistryError("promotion transaction was already rolled back")
    record = matches[0]
    _validate_custom_segmenter_transaction_record(record)
    return record


def champion_status(
    *, registry_path: Path = DEFAULT_REGISTRY, history_path: Path | None = None
) -> dict[str, Any]:
    """Expose current champion pointers and append-only promotion history."""
    registry = _load_registry(registry_path)
    champions = {
        str(item["role"]): {
            "key": item["key"],
            "version_tag": item.get("version_tag"),
            "sha256": item.get("sha256"),
            "ontology_version": item.get("ontology_version"),
            "class_names_sha256": item.get("class_names_sha256"),
        }
        for item in registry["models"]
        if str(item.get("role", "")).startswith("champion_")
    }
    history = []
    if history_path is not None and Path(history_path).is_file():
        for number, line in enumerate(
            Path(history_path).read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue
            try:
                history.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ModelRegistryError(f"invalid champion history row {number}: {exc}") from exc
    return {"champions": champions, "history": history}


def _append_jsonl(path: Path, document: dict[str, Any]) -> None:
    """Publish one append-only row by atomically replacing the complete preserved history."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_bytes() if path.is_file() else b""
    if existing and not existing.endswith(b"\n"):
        raise ModelRegistryError("champion history is not newline terminated")
    row = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(existing)
            stream.write(row)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
