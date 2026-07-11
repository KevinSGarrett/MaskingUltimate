"""Transactional model downloads and the only supported checkpoint resolver.

Spec: doc 06 section 3 and doc 04 section 3 (MF-P0-06.01).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import yaml

from ..ontology import get_ontology

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CATALOG = PROJECT_ROOT / "models" / "model_sources.yaml"
DEFAULT_REGISTRY = PROJECT_ROOT / "models" / "model_registry.json"
DEFAULT_MODELS_ROOT = PROJECT_ROOT / "models"
CHUNK_SIZE = 1024 * 1024
OLLAMA_MODEL_NAMES = (
    "qwen2.5vl:7b",
    "llama3.2-vision:11b",
    "qwen2.5:7b-instruct",
)
SERVING_CHAMPION_ROLES = {"champion_bodypart", "champion_hand", "champion_clothing"}

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
            raise ModelRegistryError(f"ollama list failed: {process.stderr.strip()}")
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
            "role": ("local_vlm" if "vision" in name or "vl" in name else "manifest_linter"),
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
        results.append({"key": key, "sha256": entry.get("sha256"), "output_sha256": expected})
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


def promote_model_role(
    candidate_key: str,
    role: str,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
    history_path: Path | None = None,
) -> dict[str, Any]:
    """Atomically swap a verified challenger into a champion role and record rollback data."""
    if not role.startswith("champion_"):
        raise ModelRegistryError("promotion target must be a champion_* role")
    registry = _load_registry(registry_path)
    candidate = next(
        (item for item in registry["models"] if item.get("key") == candidate_key), None
    )
    if (
        candidate is None
        or candidate.get("managed") is True
        or candidate.get("verified") is not True
    ):
        raise ModelRegistryError(
            f"promotion candidate is not a verified checkpoint: {candidate_key}"
        )
    resolve_registered_model(candidate_key, registry_path=registry_path, models_root=models_root)
    if role in SERVING_CHAMPION_ROLES:
        _validate_serving_champion_metadata(candidate, role=role, models_root=models_root)
    incumbents = [item for item in registry["models"] if item.get("role") == role]
    if len(incumbents) > 1:
        raise ModelRegistryError(f"multiple incumbent models already claim {role}")
    incumbent = incumbents[0] if incumbents else None
    if incumbent is candidate:
        raise ModelRegistryError(f"candidate already owns {role}")
    candidate_previous_role = str(candidate["role"])
    candidate["role"] = role
    if incumbent is not None:
        incumbent["role"] = candidate_previous_role
    record = {
        "schema_version": "1.0.0",
        "candidate_key": candidate_key,
        "candidate_previous_role": candidate_previous_role,
        "incumbent_key": incumbent.get("key") if incumbent else None,
        "champion_role": role,
    }
    _atomic_json(registry_path, registry)
    if history_path is not None:
        _append_jsonl(Path(history_path), record)
    return record


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
    expected_map = "material" if role == "champion_clothing" else "part"
    ontology = get_ontology()
    for name in class_names:
        if name == "background":
            continue
        try:
            label = ontology.label(name)
        except Exception as exc:
            raise ModelRegistryError(f"serving champion declares unknown class: {name}") from exc
        if label.map != expected_map:
            raise ModelRegistryError(
                f"serving champion class {name} belongs to {label.map}, expected {expected_map}"
            )


def rollback_model_role(record: dict[str, Any], *, registry_path: Path = DEFAULT_REGISTRY) -> None:
    """Reverse exactly one recorded promotion, refusing if roles changed meanwhile."""
    registry = _load_registry(registry_path)
    by_key = {str(item["key"]): item for item in registry["models"]}
    candidate = by_key.get(str(record["candidate_key"]))
    if candidate is None or candidate.get("role") != record["champion_role"]:
        raise ModelRegistryError("cannot rollback: candidate no longer owns the recorded role")
    incumbent_key = record.get("incumbent_key")
    incumbent = by_key.get(str(incumbent_key)) if incumbent_key else None
    if incumbent is not None and incumbent.get("role") != record["candidate_previous_role"]:
        raise ModelRegistryError("cannot rollback: incumbent role changed after promotion")
    candidate["role"] = record["candidate_previous_role"]
    if incumbent is not None:
        incumbent["role"] = record["champion_role"]
    _atomic_json(registry_path, registry)


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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
