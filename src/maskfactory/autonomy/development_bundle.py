"""Validate self-hosted development output without granting repository authority."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator


class DevelopmentBundleError(RuntimeError):
    """A development bundle exceeded its scope or lacked deterministic proof."""


SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "runpod_development_patch_bundle.schema.json"


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def seal_development_bundle(value: Mapping[str, Any]) -> dict[str, Any]:
    document = dict(value)
    document.pop("bundle_sha256", None)
    document["bundle_sha256"] = _canonical_sha256(document)
    return document


def _is_within(path: str, allowed_paths: Sequence[str]) -> bool:
    candidate = PurePosixPath(path)
    for raw in allowed_paths:
        allowed = PurePosixPath(raw)
        if candidate == allowed or allowed in candidate.parents:
            return True
    return False


def validate_development_bundle(
    value: Mapping[str, Any],
    *,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Validate scope, independent validators, hashes, and the no-adoption ceiling."""

    document = dict(value)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    problems = sorted(
        Draft202012Validator(schema).iter_errors(document), key=lambda item: list(item.path)
    )
    if problems:
        pointer = "/".join(str(part) for part in problems[0].path)
        raise DevelopmentBundleError(
            f"development bundle schema invalid at {pointer or '<root>'}: {problems[0].message}"
        )
    expected = _canonical_sha256({k: v for k, v in document.items() if k != "bundle_sha256"})
    if document["bundle_sha256"] != expected:
        raise DevelopmentBundleError("development bundle seal mismatch")

    allowed = list(document["allowed_paths"])
    changed = [str(item["path"]) for item in document["changed_files"]]
    outside = sorted(path for path in changed if not _is_within(path, allowed))
    if outside:
        raise DevelopmentBundleError(f"changed files outside allowed paths: {outside}")

    validator_ids = [str(item["validator_id"]) for item in document["validators"]]
    commands = [tuple(item["command"]) for item in document["validators"]]
    if len(set(validator_ids)) != len(validator_ids) or len(set(commands)) < 2:
        raise DevelopmentBundleError("two independent deterministic validators required")
    if any(command[0].lower() in {"git", "gh"} for command in commands):
        raise DevelopmentBundleError("Git commands are Codex-owned and cannot be worker validators")

    if artifact_root is not None:
        root = Path(artifact_root).resolve()
        patch = (root / document["patch_path"]).resolve()
        try:
            patch.relative_to(root)
        except ValueError as exc:
            raise DevelopmentBundleError("patch path escapes artifact root") from exc
        if not patch.is_file():
            raise DevelopmentBundleError("patch artifact missing")
        if hashlib.sha256(patch.read_bytes()).hexdigest() != document["patch_sha256"]:
            raise DevelopmentBundleError("patch artifact hash mismatch")
    return document


def write_development_bundle(value: Mapping[str, Any], output_path: Path) -> dict[str, Any]:
    """Write one immutable, schema-valid prepared patch packet."""

    document = validate_development_bundle(value)
    output_path = Path(output_path)
    if output_path.exists():
        raise DevelopmentBundleError("development bundle already exists")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    return document
