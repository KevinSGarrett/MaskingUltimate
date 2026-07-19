"""Clean release packaging checks plus install/rollback operations.

This module is additive to frozen release and capability documents.  It
provides two boundaries:

1. Publication-time checks over install/rollback artifacts and argv safety.
2. Runtime install/rollback operations with hash verification and atomic switch.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from maskfactory.validation import canonical_document_sha256, load_canonical_json

MANIFEST_SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas/maskfactory_clean_release_manifest.schema.json"
)

FORBIDDEN_EDITABLE_TOKENS = {"-e", "--editable"}
FORBIDDEN_SOURCE_TARGETS = {".", "./", "src", "./src"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_manifest_schema() -> Mapping[str, Any]:
    return load_canonical_json(MANIFEST_SCHEMA_PATH.read_bytes())


def _resolve_relative(root: Path, relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or "\\" in relative_path
        or ":" in pure.parts[0]
    ):
        raise ValueError(f"unsafe relative path: {relative_path!r}")
    resolved = root.joinpath(*pure.parts).resolve(strict=True)
    resolved.relative_to(root.resolve(strict=True))
    if not resolved.is_file():
        raise ValueError(f"required file missing: {relative_path}")
    return resolved


def argv_has_editable_or_source(argv: object) -> bool:
    if not isinstance(argv, list):
        return True
    seen_install = False
    for value in argv:
        token = str(value).strip().lower()
        if token in {"install", "pip", "pip3", "uv", "python", "python3", "-m"}:
            seen_install = seen_install or token == "install"
            continue
        if token in FORBIDDEN_EDITABLE_TOKENS:
            return True
        # Fail closed if source-target install appears in any install argv.
        if token in FORBIDDEN_SOURCE_TARGETS:
            return True
        if seen_install and token.startswith("-e"):
            return True
    return False


def validate_clean_release_manifest(
    evidence: Mapping[str, Any],
    catalog_by_path: Mapping[str, Mapping[str, Any]],
    *,
    release_root: Path,
) -> tuple[tuple[str, str, str], ...]:
    """Validate additive clean-release constraints from installation manifest."""
    issues: list[tuple[str, str, str]] = []
    installation = evidence.get("installation", {})
    rollback = evidence.get("rollback", {})
    manifest_binding = installation.get("manifest") if isinstance(installation, Mapping) else None
    if not isinstance(manifest_binding, Mapping):
        return (("/installation/manifest", "manifest_missing", "install manifest binding missing"),)
    manifest_relative = manifest_binding.get("relative_path")
    if not isinstance(manifest_relative, str):
        return (
            (
                "/installation/manifest/relative_path",
                "manifest_path_type",
                "install manifest path must be a string",
            ),
        )
    row = catalog_by_path.get(manifest_relative)
    if not isinstance(row, Mapping):
        return (
            (
                "/installation/manifest",
                "manifest_not_cataloged",
                "install manifest is not present in release catalog",
            ),
        )
    try:
        manifest_path = _resolve_relative(release_root, manifest_relative)
        manifest = load_canonical_json(manifest_path.read_bytes())
    except (OSError, ValueError) as exc:
        return (("/installation/manifest", "manifest_decode", str(exc)),)
    schema = _load_manifest_schema()
    for error in Draft202012Validator(schema).iter_errors(manifest):
        pointer = "/" + "/".join(str(part) for part in error.absolute_path)
        issues.append((f"/installation/manifest{pointer}", "manifest_schema", error.message))
    if issues:
        return tuple(sorted(set(issues)))
    assert isinstance(manifest, Mapping)
    expected_manifest_hash = canonical_document_sha256(
        manifest, excluded_top_level_fields=("manifest_sha256",)
    )
    if manifest.get("manifest_sha256") != expected_manifest_hash:
        issues.append(
            (
                "/installation/manifest/manifest_sha256",
                "manifest_hash",
                "manifest hash does not match canonical document hash",
            )
        )
    release_binding = evidence.get("release_binding", {})
    if manifest.get("release_id") != release_binding.get("release_id"):
        issues.append(
            (
                "/installation/manifest/release_id",
                "manifest_release_binding",
                "manifest release_id does not match release binding",
            )
        )
    if manifest.get("release_payload_sha256") != release_binding.get("release_payload_sha256"):
        issues.append(
            (
                "/installation/manifest/release_payload_sha256",
                "manifest_release_payload",
                "manifest release payload hash mismatch",
            )
        )
    package = manifest.get("package", {})
    package_relative = package.get("relative_path") if isinstance(package, Mapping) else None
    package_row = (
        catalog_by_path.get(package_relative) if isinstance(package_relative, str) else None
    )
    if not isinstance(package_row, Mapping):
        issues.append(
            (
                "/installation/manifest/package",
                "manifest_package_catalog",
                "package is not cataloged",
            )
        )
    elif package_row.get("sha256") != package.get("sha256"):
        issues.append(
            (
                "/installation/manifest/package/sha256",
                "manifest_package_hash",
                "manifest package hash does not match catalog",
            )
        )
    if argv_has_editable_or_source(installation.get("argv")):
        issues.append(
            (
                "/installation/argv",
                "editable_install_forbidden",
                "editable/source install is forbidden",
            )
        )
    if argv_has_editable_or_source(rollback.get("argv")):
        issues.append(
            (
                "/rollback/argv",
                "editable_rollback_forbidden",
                "editable/source rollback is forbidden",
            )
        )
    runtime = evidence.get("runtime_provenance", {})
    if isinstance(runtime, Mapping) and runtime.get("kind") == "native_venv":
        dist = runtime.get("installed_distribution", {})
        if isinstance(dist, Mapping) and isinstance(dist.get("relative_path"), str):
            if not str(dist["relative_path"]).endswith(".whl"):
                issues.append(
                    (
                        "/runtime_provenance/installed_distribution/relative_path",
                        "installed_distribution_not_wheel",
                        "installed distribution must be an immutable wheel artifact",
                    )
                )
    return tuple(sorted(set(issues)))


def _expected_runtime_files(manifest: Mapping[str, Any]) -> set[str]:
    expected = {"installed.json", "manifest.json", "wheel.whl"}
    for row in manifest.get("stale_detection", {}).get("expected_runtime_files", []):
        if isinstance(row, str) and row:
            expected.add(row)
    return expected


def _write_json_atomic(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def load_clean_release_manifest(path: Path) -> dict[str, Any]:
    """Load and validate clean-release manifest document."""
    manifest = load_canonical_json(path.read_bytes())
    if not isinstance(manifest, dict):
        raise ValueError("clean release manifest must be a JSON object")
    schema = _load_manifest_schema()
    errors = [error.message for error in Draft202012Validator(schema).iter_errors(manifest)]
    if errors:
        raise ValueError("; ".join(sorted(set(errors))))
    expected = canonical_document_sha256(manifest, excluded_top_level_fields=("manifest_sha256",))
    if manifest.get("manifest_sha256") != expected:
        raise ValueError("clean release manifest hash mismatch")
    return manifest


def install_clean_release(
    *,
    manifest_path: Path,
    release_root: Path,
    runtime_root: Path,
    proof_out: Path | None = None,
) -> dict[str, Any]:
    """Install a release by verified wheel copy and atomic pointer switch."""
    manifest = load_clean_release_manifest(manifest_path)
    package = manifest["package"]
    wheel_path = _resolve_relative(release_root, package["relative_path"])
    wheel_hash = _sha256(wheel_path)
    if wheel_hash != package["sha256"]:
        raise ValueError("package wheel hash mismatch")
    if manifest["source_authority"]["allow_dirty_source"]:
        raise ValueError("dirty-source publication authority is forbidden")
    if manifest["install_mode"] != "wheel":
        raise ValueError("only immutable wheel install mode is allowed")
    releases_root = runtime_root / "releases"
    releases_root.mkdir(parents=True, exist_ok=True)
    release_root_target = releases_root / manifest["release_id"]
    if release_root_target.exists():
        expected = _expected_runtime_files(manifest)
        actual = {
            path.relative_to(release_root_target).as_posix()
            for path in release_root_target.rglob("*")
            if path.is_file()
        }
        if actual != expected:
            stale = sorted(actual - expected)
            raise ValueError(f"stale runtime files detected: {stale}")
    stage_root = runtime_root / ".stage" / manifest["release_id"]
    if stage_root.exists():
        shutil.rmtree(stage_root)
    stage_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(wheel_path, stage_root / "wheel.whl")
    shutil.copy2(manifest_path, stage_root / "manifest.json")
    installed = {
        "release_id": manifest["release_id"],
        "wheel_sha256": wheel_hash,
        "manifest_sha256": canonical_document_sha256(manifest),
        "publication_payload_sha256": manifest["publication_payload_sha256"],
        "install_mode": manifest["install_mode"],
    }
    _write_json_atomic(stage_root / "installed.json", installed)
    if release_root_target.exists():
        shutil.rmtree(release_root_target)
    os.replace(stage_root, release_root_target)
    active_pointer = runtime_root / "active_release.json"
    previous = None
    if active_pointer.is_file():
        try:
            previous_doc = json.loads(active_pointer.read_text(encoding="utf-8"))
            if isinstance(previous_doc, Mapping):
                previous = previous_doc.get("release_id")
        except json.JSONDecodeError:
            previous = None
    active_doc = {
        "release_id": manifest["release_id"],
        "previous_release_id": previous,
        "activation_strategy": manifest["activation"]["strategy"],
        "pointer_sha256": "",
    }
    active_doc["pointer_sha256"] = canonical_document_sha256(
        active_doc, excluded_top_level_fields=("pointer_sha256",)
    )
    _write_json_atomic(active_pointer, active_doc)
    proof = {
        "record_type": "maskfactory_release_activation_proof",
        "action": "install",
        "release_id": manifest["release_id"],
        "previous_release_id": previous,
        "activation_strategy": manifest["activation"]["strategy"],
        "recovery_hook_id": manifest["proof_hooks"]["recovery_hook_id"],
        "rollback_hook_id": manifest["proof_hooks"]["rollback_hook_id"],
        "proof_sha256": "",
    }
    proof["proof_sha256"] = canonical_document_sha256(
        proof, excluded_top_level_fields=("proof_sha256",)
    )
    if proof_out is not None:
        _write_json_atomic(proof_out, proof)
    return proof


def rollback_clean_release(
    *,
    manifest_path: Path,
    runtime_root: Path,
    target_release_id: str | None = None,
    proof_out: Path | None = None,
) -> dict[str, Any]:
    """Rollback to prior release by atomic active-pointer replacement."""
    manifest = load_clean_release_manifest(manifest_path)
    active_pointer = runtime_root / "active_release.json"
    if not active_pointer.is_file():
        raise ValueError("active release pointer is missing")
    active = json.loads(active_pointer.read_text(encoding="utf-8"))
    if not isinstance(active, Mapping):
        raise ValueError("active release pointer is malformed")
    target = (
        target_release_id
        or active.get("previous_release_id")
        or manifest.get("rollback_target_release_id")
    )
    if not isinstance(target, str) or not target:
        raise ValueError("rollback target release is unresolved")
    target_dir = runtime_root / "releases" / target
    if not target_dir.is_dir() or not (target_dir / "installed.json").is_file():
        raise ValueError("rollback target release is unavailable")
    current = active.get("release_id")
    rollback_doc = {
        "release_id": target,
        "previous_release_id": current,
        "activation_strategy": manifest["activation"]["strategy"],
        "pointer_sha256": "",
    }
    rollback_doc["pointer_sha256"] = canonical_document_sha256(
        rollback_doc, excluded_top_level_fields=("pointer_sha256",)
    )
    _write_json_atomic(active_pointer, rollback_doc)
    proof = {
        "record_type": "maskfactory_release_activation_proof",
        "action": "rollback",
        "release_id": target,
        "previous_release_id": current,
        "activation_strategy": manifest["activation"]["strategy"],
        "recovery_hook_id": manifest["proof_hooks"]["recovery_hook_id"],
        "rollback_hook_id": manifest["proof_hooks"]["rollback_hook_id"],
        "proof_sha256": "",
    }
    proof["proof_sha256"] = canonical_document_sha256(
        proof, excluded_top_level_fields=("proof_sha256",)
    )
    if proof_out is not None:
        _write_json_atomic(proof_out, proof)
    return proof
