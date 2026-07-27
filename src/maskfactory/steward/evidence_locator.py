"""Fail-closed, compact index for completion-critical MaskFactory evidence.

The locator stores only identities, hashes, relative locations, and replay
instructions.  It deliberately does not copy runtime artifacts, credentials,
or provider payloads.  A locator may record blocked or historical evidence,
but only an ``accepted`` entry may be used as an accepted-milestone index.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = "maskfactory.completion_evidence_locator.v1"
ZERO_SHA256 = "0" * 64
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
GIT_OBJECT_RE = re.compile(r"^[a-f0-9]{40}$")
TRACKER_ITEM_RE = re.compile(r"^MF-P[0-9]+-[0-9]+\.[0-9]+$")
ARTIFACT_ROLES = frozenset({"input", "runtime", "output", "terminal", "release"})
DISPOSITIONS = frozenset(
    {"accepted", "blocked", "historical_provenance_only", "rejected"}
)


class EvidenceLocatorError(RuntimeError):
    """Raised when an evidence locator is incomplete, mutable, or ambiguous."""


def canonical_sha256(value: Any) -> str:
    """Return the repository's stable canonical JSON SHA-256."""

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _safe_relative_path(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise EvidenceLocatorError(f"{field} must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) == ".":
        raise EvidenceLocatorError(f"{field} escapes its declared evidence root")
    return value


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise EvidenceLocatorError(f"{field} must be a lowercase SHA-256")
    return value


def seal_evidence_locator(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy with a zero-self canonical hash."""

    sealed = copy.deepcopy(dict(value))
    sealed["self_sha256"] = ZERO_SHA256
    sealed["self_sha256"] = canonical_sha256(sealed)
    return sealed


def _validate_artifacts(value: object, *, disposition: str) -> None:
    if not isinstance(value, list) or not value:
        raise EvidenceLocatorError("artifact bindings are absent")
    seen: set[tuple[str, str]] = set()
    roles: set[str] = set()
    for artifact in value:
        if not isinstance(artifact, Mapping) or set(artifact) != {
            "role",
            "name",
            "sha256",
            "bytes",
            "location",
        }:
            raise EvidenceLocatorError("artifact binding schema is not closed")
        role = artifact.get("role")
        name = artifact.get("name")
        if role not in ARTIFACT_ROLES or not isinstance(name, str) or not name:
            raise EvidenceLocatorError("artifact role or name is invalid")
        if (role, name) in seen:
            raise EvidenceLocatorError("artifact role/name bindings must be unique")
        seen.add((role, name))
        roles.add(role)
        _require_sha256(artifact.get("sha256"), field=f"artifact {role}/{name} sha256")
        if not isinstance(artifact.get("bytes"), int) or artifact["bytes"] < 0:
            raise EvidenceLocatorError("artifact bytes must be a non-negative integer")
        _safe_relative_path(artifact.get("location"), field=f"artifact {role}/{name} location")
    if disposition == "accepted" and not {"output", "terminal"}.issubset(roles):
        raise EvidenceLocatorError("accepted evidence requires output and terminal bindings")


def _validate_locations(value: object) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "repository_relative",
        "pod_relative",
        "compact_recovery_relative",
    }:
        raise EvidenceLocatorError("evidence locations schema is not closed")
    total = 0
    for kind, locations in value.items():
        if not isinstance(locations, list):
            raise EvidenceLocatorError(f"{kind} locations must be a list")
        if locations != sorted(locations) or len(locations) != len(set(locations)):
            raise EvidenceLocatorError(f"{kind} locations must be sorted and unique")
        for location in locations:
            _safe_relative_path(location, field=f"{kind} location")
        total += len(locations)
    if not total:
        raise EvidenceLocatorError("an entry must retain at least one evidence location")


def _validate_entry(entry: object) -> tuple[str, str | None]:
    required = {
        "tracker_item",
        "parent_campaign_id",
        "disposition",
        "source",
        "artifacts",
        "locations",
        "replay_command",
        "limitations",
        "supersedes",
    }
    if not isinstance(entry, Mapping) or set(entry) != required:
        raise EvidenceLocatorError("evidence entry schema is not closed")
    tracker_item = entry.get("tracker_item")
    if not isinstance(tracker_item, str) or not TRACKER_ITEM_RE.fullmatch(tracker_item):
        raise EvidenceLocatorError("entry tracker item is invalid")
    parent = entry.get("parent_campaign_id")
    if parent is not None and (not isinstance(parent, str) or not parent):
        raise EvidenceLocatorError("parent campaign identity is invalid")
    disposition = entry.get("disposition")
    if disposition not in DISPOSITIONS:
        raise EvidenceLocatorError("entry disposition is unsupported")
    source = entry.get("source")
    if not isinstance(source, Mapping) or set(source) != {"commit_sha", "tree_sha", "path"}:
        raise EvidenceLocatorError("source binding schema is not closed")
    for field in ("commit_sha", "tree_sha"):
        value = source.get(field)
        if not isinstance(value, str) or not GIT_OBJECT_RE.fullmatch(value):
            raise EvidenceLocatorError(f"source {field} is invalid")
    _safe_relative_path(source.get("path"), field="source path")
    _validate_artifacts(entry.get("artifacts"), disposition=str(disposition))
    _validate_locations(entry.get("locations"))
    command = entry.get("replay_command")
    if not isinstance(command, str) or not command.strip() or "\x00" in command:
        raise EvidenceLocatorError("replay command is invalid")
    limitations = entry.get("limitations")
    if (
        not isinstance(limitations, list)
        or not limitations
        or any(not isinstance(item, str) or not item.strip() for item in limitations)
    ):
        raise EvidenceLocatorError("entry limitations are absent")
    supersedes = entry.get("supersedes")
    if not isinstance(supersedes, list):
        raise EvidenceLocatorError("entry supersession list is invalid")
    for prior in supersedes:
        if not isinstance(prior, Mapping) or set(prior) != {"path", "raw_sha256", "self_sha256"}:
            raise EvidenceLocatorError("supersession binding schema is not closed")
        _safe_relative_path(prior.get("path"), field="supersession path")
        _require_sha256(prior.get("raw_sha256"), field="supersession raw sha256")
        _require_sha256(prior.get("self_sha256"), field="supersession self sha256")
    return tracker_item, parent


def validate_evidence_locator(value: Mapping[str, Any]) -> None:
    """Validate an immutable, non-secret completion-evidence locator."""

    required = {
        "schema_version",
        "tracker_item",
        "authority_file_sha256",
        "entries",
        "completion_credit_claimed",
        "limitations",
        "self_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise EvidenceLocatorError("evidence locator schema is not closed")
    if value.get("schema_version") != SCHEMA_VERSION or value.get("tracker_item") != "MF-P6-21.01":
        raise EvidenceLocatorError("evidence locator authority binding is invalid")
    if value.get("completion_credit_claimed") is not False:
        raise EvidenceLocatorError("evidence locator cannot claim completion credit")
    expected = value.get("self_sha256")
    zeroed = copy.deepcopy(dict(value))
    zeroed["self_sha256"] = ZERO_SHA256
    if not isinstance(expected, str) or canonical_sha256(zeroed) != expected:
        raise EvidenceLocatorError("evidence locator self hash mismatch")
    authority = value.get("authority_file_sha256")
    if (
        not isinstance(authority, Mapping)
        or not authority
        or any(
            not isinstance(path, str)
            or not path
            or not SHA256_RE.fullmatch(str(digest))
            for path, digest in authority.items()
        )
    ):
        raise EvidenceLocatorError("locator authority hashes are invalid")
    entries = value.get("entries")
    if not isinstance(entries, list) or not entries:
        raise EvidenceLocatorError("evidence locator entries are absent")
    keys = [_validate_entry(entry) for entry in entries]
    if keys != sorted(keys, key=lambda item: (item[0], item[1] or "")) or len(keys) != len(set(keys)):
        raise EvidenceLocatorError("entries must be sorted and unique by tracker item and parent")
    limitations = value.get("limitations")
    if (
        not isinstance(limitations, list)
        or not limitations
        or any(not isinstance(item, str) or not item.strip() for item in limitations)
    ):
        raise EvidenceLocatorError("locator limitations are absent")


def build_evidence_locator(
    *,
    entries: Sequence[Mapping[str, Any]],
    authority_file_sha256: Mapping[str, str],
    limitations: Sequence[str],
) -> dict[str, Any]:
    """Build and validate a compact locator without asserting milestone completion."""

    locator = {
        "schema_version": SCHEMA_VERSION,
        "tracker_item": "MF-P6-21.01",
        "authority_file_sha256": dict(sorted(authority_file_sha256.items())),
        "entries": [copy.deepcopy(dict(entry)) for entry in entries],
        "completion_credit_claimed": False,
        "limitations": list(limitations),
        "self_sha256": ZERO_SHA256,
    }
    sealed = seal_evidence_locator(locator)
    validate_evidence_locator(sealed)
    return sealed


def write_evidence_locator(path: Path, value: Mapping[str, Any]) -> None:
    """Atomically persist a validated locator with newline-normalized JSON."""

    validate_evidence_locator(value)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "EvidenceLocatorError",
    "SCHEMA_VERSION",
    "build_evidence_locator",
    "canonical_sha256",
    "seal_evidence_locator",
    "validate_evidence_locator",
    "write_evidence_locator",
]
