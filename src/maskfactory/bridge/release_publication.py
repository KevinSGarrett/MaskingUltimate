"""Fail-closed observed release-publication validation.

This module is deliberately additive to the frozen bridge-v1 release snapshot.
It validates an observed publication record; it does not manufacture a release,
trust anchor, runtime result, or clean-build claim.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator, FormatChecker

from maskfactory.bridge.clean_release_packaging import validate_clean_release_manifest
from maskfactory.validation import canonical_document_sha256, load_canonical_json

SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas/maskfactory_release_publication_evidence.schema.json"
)
CANONICALIZATION_EXCLUDED_FIELDS = ("publication_payload_sha256", "signature")


@dataclass(frozen=True, order=True)
class PublicationIssue:
    pointer: str
    code: str
    message: str


def _issue(pointer: str, code: str, message: str) -> PublicationIssue:
    return PublicationIssue(pointer, code, message)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError:
        return None


def _safe_file(root: Path, relative_path: Any) -> tuple[Path | None, list[PublicationIssue]]:
    if not isinstance(relative_path, str):
        return None, [_issue("", "path_type", "catalog path must be a string")]
    pure = PurePosixPath(relative_path)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or "\\" in relative_path
        or ":" in pure.parts[0]
    ):
        return None, [_issue("", "unsafe_path", f"unsafe release path: {relative_path!r}")]
    try:
        root = root.resolve(strict=True)
        candidate = root.joinpath(*pure.parts)
        for parent in (candidate, *candidate.parents):
            if parent == root.parent:
                break
            if parent.exists() and parent.is_symlink():
                return None, [
                    _issue("", "path_indirection", f"symlink rejected: {relative_path!r}")
                ]
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, OSError, ValueError):
        return None, [_issue("", "path_containment", f"missing or escaped path: {relative_path!r}")]
    if not resolved.is_file() or resolved.is_symlink() or resolved.stat().st_nlink > 1:
        return None, [
            _issue("", "regular_file_required", f"unsafe catalog file: {relative_path!r}")
        ]
    return resolved, []


def _all_regular_files(root: Path) -> tuple[set[str], list[PublicationIssue]]:
    files: set[str] = set()
    issues: list[PublicationIssue] = []
    try:
        root = root.resolve(strict=True)
    except (OSError, FileNotFoundError):
        return files, [_issue("", "release_root", "release root does not exist")]
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            issues.append(
                _issue(f"/catalog/{relative}", "path_indirection", "release root contains symlink")
            )
        elif path.is_file():
            if path.stat().st_nlink > 1:
                issues.append(
                    _issue(
                        f"/catalog/{relative}",
                        "hardlink_rejected",
                        "release root contains hardlink",
                    )
                )
            files.add(relative)
    return files, issues


def _git(repository_root: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repository_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _schema_issues(evidence: Mapping[str, Any]) -> list[PublicationIssue]:
    try:
        schema = load_canonical_json(SCHEMA_PATH.read_bytes())
    except (OSError, ValueError) as exc:
        return [_issue("", "schema_load", str(exc))]
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        _issue(
            "/" + "/".join(str(part) for part in error.absolute_path),
            "schema",
            error.message,
        )
        for error in validator.iter_errors(evidence)
    ]


def _signature_issues(
    evidence: Mapping[str, Any],
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None,
) -> list[PublicationIssue]:
    signature = evidence.get("signature")
    if not isinstance(signature, Mapping):
        return [_issue("/signature", "signature_required", "publication signature is required")]
    key_id = signature.get("key_id")
    record = trusted_signing_keys.get(key_id) if isinstance(trusted_signing_keys, Mapping) else None
    if not isinstance(record, Mapping):
        return [_issue("/signature/key_id", "trust_anchor", "unknown release signing key")]
    issues: list[PublicationIssue] = []
    try:
        public_key = base64.b64decode(str(signature.get("public_key_base64")), validate=True)
        signature_value = base64.b64decode(str(signature.get("value_base64")), validate=True)
    except (ValueError, TypeError, binascii.Error):
        return [_issue("/signature", "signature_encoding", "invalid base64 signature material")]
    if record.get("public_key_sha256") != hashlib.sha256(public_key).hexdigest():
        issues.append(
            _issue("/signature", "key_substitution", "embedded key is not the trusted key")
        )
    if (
        record.get("status") != "active"
        or record.get("usage_scope") != "production"
        or "producer_release" not in set(record.get("roles") or ())
    ):
        issues.append(
            _issue(
                "/signature/key_id",
                "signer_authority",
                "key is not an active production release key",
            )
        )
    published_at = _utc(evidence.get("published_at"))
    valid_from, valid_until = _utc(record.get("valid_from")), _utc(record.get("valid_until"))
    if (
        not published_at
        or not valid_from
        or not valid_until
        or not valid_from <= published_at < valid_until
    ):
        issues.append(
            _issue("/signature/key_id", "signer_validity", "key is invalid at publication time")
        )
    expected_hash = canonical_document_sha256(
        evidence, excluded_top_level_fields=CANONICALIZATION_EXCLUDED_FIELDS
    )
    if evidence.get("publication_payload_sha256") != expected_hash:
        issues.append(
            _issue("/publication_payload_sha256", "canonical_hash", "publication hash mismatch")
        )
    if signature.get("signed_payload_sha256") != expected_hash:
        issues.append(
            _issue(
                "/signature/signed_payload_sha256", "signature_binding", "signature hash mismatch"
            )
        )
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature_value, bytes.fromhex(expected_hash)
        )
    except (ValueError, TypeError, InvalidSignature):
        issues.append(
            _issue("/signature/value_base64", "signature_verification", "invalid signature")
        )
    return issues


def _binding_rows(evidence: Mapping[str, Any]) -> Iterable[tuple[str, Mapping[str, Any]]]:
    yield "/release_binding", evidence.get("release_binding", {})
    yield "/crosswalk_binding", evidence.get("crosswalk_binding", {})
    runtime = evidence.get("runtime_provenance", {})
    if isinstance(runtime, Mapping) and runtime.get("kind") == "native_venv":
        yield "/runtime_provenance/environment_lock", runtime.get("environment_lock", {})
        yield (
            "/runtime_provenance/installed_distribution",
            runtime.get("installed_distribution", {}),
        )
    for section, names in (
        ("/installation", ("installer", "manifest", "verification_workflow")),
        ("/rollback", ("command", "verification_evidence")),
        (
            "/trust_checkpoint",
            ("key_registry", "rotation_policy", "revocation_state", "journal_checkpoint"),
        ),
    ):
        value = evidence.get(section[1:], {})
        if isinstance(value, Mapping):
            for name in names:
                yield f"{section}/{name}", value.get(name, {})


def _adopted_crosswalk_issues(
    evidence: Mapping[str, Any], *, release_root: Path
) -> list[PublicationIssue]:
    """Require publication evidence to bind the adopted executable crosswalk identity."""
    from maskfactory.bridge.crosswalk import CrosswalkError, load_crosswalk_definition

    binding = evidence.get("crosswalk_binding")
    if not isinstance(binding, Mapping):
        return [
            _issue(
                "/crosswalk_binding",
                "crosswalk_adoption",
                "publication must bind the adopted executable crosswalk",
            )
        ]
    try:
        adopted = load_crosswalk_definition()
    except CrosswalkError as exc:
        return [
            _issue(
                "/crosswalk_binding",
                "crosswalk_adoption",
                f"adopted crosswalk unavailable: {exc}",
            )
        ]
    issues: list[PublicationIssue] = []
    if binding.get("crosswalk_id") != adopted["crosswalk_id"]:
        issues.append(
            _issue(
                "/crosswalk_binding/crosswalk_id",
                "crosswalk_adoption",
                "crosswalk_id does not match adopted executable crosswalk",
            )
        )
    path, path_issues = _safe_file(release_root, binding.get("relative_path"))
    issues.extend(
        _issue("/crosswalk_binding" + item.pointer, item.code, item.message) for item in path_issues
    )
    if path is None:
        return issues
    if binding.get("sha256") != _sha256(path):
        issues.append(
            _issue(
                "/crosswalk_binding/sha256",
                "crosswalk_adoption",
                "crosswalk binding hash does not match cataloged bytes",
            )
        )
    try:
        document = load_canonical_json(path.read_bytes())
    except ValueError as exc:
        issues.append(_issue("/crosswalk_binding", "crosswalk_adoption", str(exc)))
        return issues
    if not isinstance(document, Mapping) or (
        document.get("crosswalk_id") != adopted["crosswalk_id"]
        or document.get("crosswalk_sha256") != adopted["crosswalk_sha256"]
    ):
        issues.append(
            _issue(
                "/crosswalk_binding",
                "crosswalk_adoption",
                "cataloged crosswalk document is not the adopted executable crosswalk",
            )
        )
    return issues


def validate_release_publication(
    evidence: Mapping[str, Any],
    *,
    release_root: Path,
    repository_root: Path,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None,
) -> tuple[PublicationIssue, ...]:
    """Validate closed evidence against actual Git, files, trust and release bytes."""
    issues = _schema_issues(evidence)
    if issues:
        return tuple(sorted(set(issues)))
    issues.extend(_signature_issues(evidence, trusted_signing_keys))

    catalog = evidence["catalog"]
    catalog_paths = [row["relative_path"] for row in catalog]
    if len(catalog_paths) != len(set(catalog_paths)) or len(
        {p.casefold() for p in catalog_paths}
    ) != len(catalog_paths):
        issues.append(
            _issue(
                "/catalog",
                "duplicate_catalog_path",
                "catalog has duplicate or case-colliding paths",
            )
        )
    actual_paths, root_issues = _all_regular_files(release_root)
    issues.extend(root_issues)
    if set(catalog_paths) != actual_paths:
        issues.append(
            _issue(
                "/catalog",
                "catalog_closure",
                "catalog does not exactly enumerate release-root files",
            )
        )
    catalog_by_path = {row["relative_path"]: row for row in catalog}
    for index, row in enumerate(catalog):
        path, file_issues = _safe_file(release_root, row["relative_path"])
        issues.extend(
            _issue(f"/catalog/{index}{item.pointer}", item.code, item.message)
            for item in file_issues
        )
        if path is not None and (
            _sha256(path) != row["sha256"] or path.stat().st_size != row["size_bytes"]
        ):
            issues.append(
                _issue(
                    f"/catalog/{index}", "catalog_bytes", "catalog hash or size differs from bytes"
                )
            )
    issues.extend(
        _issue(pointer, code, message)
        for pointer, code, message in validate_clean_release_manifest(
            evidence, catalog_by_path, release_root=release_root
        )
    )

    for pointer, binding in _binding_rows(evidence):
        path = binding.get("relative_path") if isinstance(binding, Mapping) else None
        row = catalog_by_path.get(path)
        expected_hash = (
            binding.get("document_sha256")
            if pointer == "/release_binding"
            else binding.get("sha256")
        )
        if not isinstance(row, Mapping) or row.get("sha256") != expected_hash:
            issues.append(
                _issue(pointer, "catalog_binding", "required evidence is not exactly cataloged")
            )

    issues.extend(_adopted_crosswalk_issues(evidence, release_root=release_root))

    release = evidence["release_binding"]
    release_path, release_issues = _safe_file(release_root, release["relative_path"])
    issues.extend(
        _issue("/release_binding" + item.pointer, item.code, item.message)
        for item in release_issues
    )
    if release_path:
        if _sha256(release_path) != release["document_sha256"]:
            issues.append(
                _issue(
                    "/release_binding", "release_document_hash", "release document hash mismatch"
                )
            )
        try:
            snapshot = load_canonical_json(release_path.read_bytes())
        except ValueError as exc:
            issues.append(_issue("/release_binding", "release_document_json", str(exc)))
        else:
            if not isinstance(snapshot, Mapping) or (
                snapshot.get("release_id") != release["release_id"]
                or snapshot.get("release_payload_sha256") != release["release_payload_sha256"]
            ):
                issues.append(
                    _issue(
                        "/release_binding", "release_payload_binding", "release identity mismatch"
                    )
                )
            producer = snapshot.get("producer")
            observed = evidence["repository_observation"]
            if not isinstance(producer, Mapping) or any(
                producer.get(field) != observed[field]
                for field in ("repository_id", "git_commit", "git_tree")
            ):
                issues.append(
                    _issue(
                        "/release_binding", "release_git_binding", "snapshot Git identity differs"
                    )
                )
            elif producer.get("dirty") is not False:
                issues.append(
                    _issue(
                        "/release_binding",
                        "dirty_source_publication_authority",
                        "release snapshot producer is not a clean-source authority",
                    )
                )
            if snapshot.get("fixture_only") is True or snapshot.get("release_status") == "fixture":
                issues.append(
                    _issue(
                        "/release_binding",
                        "fixture_authority",
                        "fixture release cannot authorize production publication",
                    )
                )
            schema_version = snapshot.get("schema_version")
            if isinstance(schema_version, str) and schema_version.split(".", 1)[0] != "1":
                issues.append(
                    _issue(
                        "/release_binding",
                        "incompatible_release_schema_version",
                        "release snapshot major schema version is incompatible",
                    )
                )

    observed = evidence["repository_observation"]
    commit, tree = (
        _git(repository_root, "rev-parse", "HEAD"),
        _git(repository_root, "rev-parse", "HEAD^{tree}"),
    )
    porcelain, remote = (
        _git(repository_root, "status", "--porcelain=v1", "--untracked-files=all"),
        _git(repository_root, "config", "--get", "remote.origin.url"),
    )
    if not commit or not tree or remote is None:
        issues.append(
            _issue(
                "/repository_observation",
                "git_observation",
                "Git HEAD/tree/origin cannot be observed",
            )
        )
    elif (
        observed["git_commit"] != commit
        or observed["git_tree"] != tree
        or observed["repository_id"] != remote
        or porcelain != ""
    ):
        issues.append(
            _issue(
                "/repository_observation", "git_drift", "repository is dirty or identity differs"
            )
        )
    return tuple(sorted(set(issues)))


def load_publication_evidence(path: Path) -> Mapping[str, Any]:
    """Load canonical JSON evidence, rejecting duplicate or non-finite JSON."""
    document = load_canonical_json(path.read_bytes())
    if not isinstance(document, Mapping):
        raise ValueError("publication evidence must be a JSON object")
    return document
