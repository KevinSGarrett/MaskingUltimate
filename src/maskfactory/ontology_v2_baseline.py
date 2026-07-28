"""Freeze and verify the active v1 authority before any ontology-v2 activation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT = ROOT / "qa" / "evidence" / "ontology_v2" / "v1_baseline.json"
DEFAULT_REPRESENTATIVE = (
    ROOT
    / "data"
    / "packages"
    / "img_2ca794d19be9"
    / "instances"
    / "p0"
    / "annotations"
    / "draft_baseline"
)


class V1BaselineError(ValueError):
    """Raised when the v1 baseline cannot be frozen or no longer verifies."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise V1BaselineError(f"baseline path escapes workspace: {path}") from exc


def _files(root: Path, paths: Iterable[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(paths, key=lambda candidate: candidate.as_posix()):
        if not path.is_file():
            raise V1BaselineError(f"required v1 baseline file is missing: {path}")
        result[_relative(root, path)] = sha256_file(path)
    return result


def _tree(root: Path, directory: Path) -> dict[str, Any]:
    if not directory.is_dir():
        raise V1BaselineError(f"representative v1 package is missing: {directory}")
    files = _files(root, (path for path in directory.rglob("*") if path.is_file()))
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "root": _relative(root, directory),
        "file_count": len(files),
        "tree_sha256": hashlib.sha256(canonical).hexdigest(),
        "files": files,
    }


def _load_json(path: Path, description: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise V1BaselineError(f"cannot load {description} {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise V1BaselineError(f"{description} root must be an object")
    return document


def build_v1_baseline(
    *,
    root: Path | str = ROOT,
    representative: Path | str | None = None,
) -> dict[str, Any]:
    workspace = Path(root).resolve()
    representative_root = (
        Path(representative).resolve()
        if representative is not None
        else workspace
        / "data"
        / "packages"
        / "img_2ca794d19be9"
        / "instances"
        / "p0"
        / "annotations"
        / "draft_baseline"
    )
    ontology_path = workspace / "configs" / "ontology.yaml"
    try:
        ontology = yaml.safe_load(ontology_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise V1BaselineError(f"cannot load active v1 ontology: {exc}") from exc
    if not isinstance(ontology, dict) or ontology.get("mask_ontology_version") != "body_parts_v1":
        raise V1BaselineError("active ontology is not body_parts_v1")
    labels = ontology.get("labels")
    if not isinstance(labels, list):
        raise V1BaselineError("active ontology labels are invalid")
    part_mapping = [
        {"id": label["id"], "name": label["name"]}
        for label in labels
        if isinstance(label, dict) and label.get("map") == "part"
    ]
    if [entry["id"] for entry in part_mapping] != list(range(56)):
        raise V1BaselineError("active v1 PART IDs are not contiguous 0..55")

    authority_paths = (
        ontology_path,
        workspace / "configs" / "derived.yaml",
        workspace / "configs" / "viz.yaml",
        workspace / "configs" / "cvat.yaml",
        workspace / "data" / "cvat" / "label_mapping.json",
        workspace / "models" / "model_registry.json",
    )
    schema_paths = tuple(sorted((workspace / "src" / "maskfactory" / "schemas").glob("*.json")))
    if not schema_paths:
        raise V1BaselineError("no active v1 schemas found")
    registry = _load_json(workspace / "models" / "model_registry.json", "model registry")
    models = registry.get("models")
    if not isinstance(models, list):
        raise V1BaselineError("model registry models must be a list")
    champion_pointers = [
        {
            "key": model.get("key"),
            "role": model.get("role"),
            "sha256": model.get("sha256"),
        }
        for model in models
        if isinstance(model, dict) and str(model.get("role", "")).startswith("champion_")
    ]
    return {
        "schema_version": "1.0.0",
        "purpose": "pre_body_parts_v2_compatibility_authority",
        "active_ontology": "body_parts_v1",
        "activation_status": "v2_not_active",
        "part_class_count_including_background": 56,
        "part_mapping": part_mapping,
        "authority_files": _files(workspace, authority_paths),
        "schema_files": _files(workspace, schema_paths),
        "champion_pointers": champion_pointers,
        "representative_package": _tree(workspace, representative_root),
    }


def write_v1_baseline(
    path: Path | str = DEFAULT_SNAPSHOT,
    *,
    root: Path | str = ROOT,
    representative: Path | str | None = None,
) -> Path:
    output = Path(path)
    document = build_v1_baseline(root=root, representative=representative)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def verify_v1_baseline(
    path: Path | str = DEFAULT_SNAPSHOT,
    *,
    root: Path | str = ROOT,
) -> dict[str, Any]:
    workspace = Path(root).resolve()
    snapshot = _load_json(Path(path), "v1 baseline")
    mismatches: list[str] = []
    for section in ("authority_files", "schema_files"):
        records = snapshot.get(section)
        if not isinstance(records, dict):
            raise V1BaselineError(f"v1 baseline {section} must be an object")
        for relative, expected in records.items():
            candidate = (workspace / relative).resolve()
            if not candidate.is_relative_to(workspace):
                raise V1BaselineError(f"v1 baseline path escapes workspace: {relative}")
            actual = sha256_file(candidate) if candidate.is_file() else None
            if actual != expected:
                mismatches.append(relative)
    representative = snapshot.get("representative_package")
    if not isinstance(representative, dict) or not isinstance(representative.get("root"), str):
        raise V1BaselineError("v1 baseline representative_package is invalid")
    current_tree = _tree(workspace, workspace / representative["root"])
    if current_tree["tree_sha256"] != representative.get("tree_sha256"):
        mismatches.append(representative["root"])
    result = {
        "valid": not mismatches,
        "mismatches": sorted(mismatches),
        "snapshot_sha256": sha256_file(Path(path)),
    }
    if mismatches:
        raise V1BaselineError(f"v1 compatibility baseline mismatch: {', '.join(mismatches)}")
    return result
