"""Materialize explicitly prepared immutable Serverless workloads into the inbox.

The producer is deliberately CPU-only.  It never reserves or submits a job and
never invents GPU work from tracker prose.  Upstream preparation must place one
self-hashed ``serverless_workload.json`` beside its exact ``payload.json``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .fallback_dispatcher import (
    TERMINAL_NAME,
    WORK_ITEM_NAME,
    WORK_ITEM_SCHEMA,
    fallback_child_mission_id,
    seal_fallback_work_item,
)
from .route_control import PARENT_CHILD_ROUTES

LEGACY_WORKLOAD_SCHEMA = "maskfactory.steward.serverless_prepared_workload.v1"
WORKLOAD_SCHEMA = "maskfactory.steward.serverless_prepared_workload.v2"
WORKLOAD_NAME = "serverless_workload.json"
PAYLOAD_NAME = "payload.json"
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


class ServerlessWorkProducerError(RuntimeError):
    """A prepared workload is malformed, contradictory, or unsafe."""


class LegacyServerlessWorkload(ServerlessWorkProducerError):
    """A historical unbound workload is preserved but cannot be reissued."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def seal_serverless_workload(value: Mapping[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(dict(value))
    sealed["self_sha256"] = "0" * 64
    sealed["self_sha256"] = canonical_sha256(sealed)
    return sealed


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _write_exclusive(path: Path, body: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


class ServerlessWorkProducer:
    """Discover prepared workloads and emit one immutable broker work item."""

    def __init__(self, *, ready_root: Path, inbox_root: Path) -> None:
        self.ready_root = Path(ready_root)
        self.inbox_root = Path(inbox_root)
        self.ready_root.mkdir(parents=True, exist_ok=True)
        self.inbox_root.mkdir(parents=True, exist_ok=True)

    def _load(self, root: Path) -> tuple[dict[str, Any], Path, dict[str, Any]]:
        manifest_path = root / WORKLOAD_NAME
        payload_path = root / PAYLOAD_NAME
        if not manifest_path.is_file() or not payload_path.is_file():
            raise ServerlessWorkProducerError(
                f"prepared workload is incomplete: {root.name}"
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ServerlessWorkProducerError(
                f"prepared workload is unreadable: {root.name}"
            ) from exc
        if not isinstance(manifest, dict) or not isinstance(payload, dict) or not payload:
            raise ServerlessWorkProducerError("prepared workload JSON is invalid")
        if manifest.get("schema_version") == LEGACY_WORKLOAD_SCHEMA:
            raise LegacyServerlessWorkload(
                "legacy Serverless workload has no immutable parent binding"
            )
        declared = manifest.get("self_sha256")
        zeroed = copy.deepcopy(manifest)
        zeroed["self_sha256"] = "0" * 64
        if (
            manifest.get("schema_version") != WORKLOAD_SCHEMA
            or not isinstance(declared, str)
            or not SHA256_RE.fullmatch(declared)
            or canonical_sha256(zeroed) != declared
        ):
            raise ServerlessWorkProducerError("prepared workload seal is invalid")
        if manifest.get("payload_file") != PAYLOAD_NAME:
            raise ServerlessWorkProducerError("payload_file must be payload.json")
        if manifest.get("payload_raw_sha256") != file_sha256(payload_path):
            raise ServerlessWorkProducerError("prepared payload raw hash mismatch")
        if manifest.get("payload_sha256") != canonical_sha256(payload):
            raise ServerlessWorkProducerError("prepared payload canonical hash mismatch")
        if manifest.get("profile") != "maskfactory":
            raise ServerlessWorkProducerError("prepared workload profile is invalid")
        if not isinstance(manifest.get("session_id"), str) or not manifest["session_id"]:
            raise ServerlessWorkProducerError("prepared workload session is invalid")
        for field in ("parent_campaign_id", "parent_contract_sha256"):
            if not isinstance(manifest.get(field), str) or not SHA256_RE.fullmatch(
                manifest[field]
            ):
                raise ServerlessWorkProducerError(
                    f"prepared workload {field} is invalid"
                )
        required_roles = manifest.get("required_child_roles")
        if (
            not isinstance(required_roles, list)
            or required_roles != sorted(set(required_roles))
            or any(role not in PARENT_CHILD_ROUTES for role in required_roles)
            or "serverless_execution" not in required_roles
        ):
            raise ServerlessWorkProducerError(
                "prepared workload required_child_roles are invalid"
            )
        if manifest.get("child_role") != "serverless_execution":
            raise ServerlessWorkProducerError(
                "prepared workload child_role is invalid"
            )
        seconds = manifest.get("requested_seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
            raise ServerlessWorkProducerError("requested_seconds must be positive")
        mission_id = fallback_child_mission_id(
            session_id=manifest["session_id"],
            parent_campaign_id=manifest["parent_campaign_id"],
            parent_contract_sha256=manifest["parent_contract_sha256"],
            required_child_roles=tuple(required_roles),
            child_role="serverless_execution",
            route="serverless_overflow",
        )
        if manifest.get("mission_id") != mission_id:
            raise ServerlessWorkProducerError("prepared workload mission mismatch")
        return manifest, payload_path, payload

    def produce(self) -> list[dict[str, Any]]:
        receipts: list[dict[str, Any]] = []
        for root in sorted(self.ready_root.iterdir()):
            if not root.is_dir() or not (root / WORKLOAD_NAME).is_file():
                continue
            try:
                manifest, payload_path, payload = self._load(root)
            except LegacyServerlessWorkload:
                receipts.append(
                    {
                        "source_root": root.name,
                        "created": False,
                        "legacy_unbound": True,
                    }
                )
                continue
            mission_id = manifest["mission_id"]
            mission_root = self.inbox_root / mission_id
            if mission_root.exists():
                receipts.append(
                    {
                        "mission_id": mission_id,
                        "created": False,
                        "terminal_reused": (mission_root / TERMINAL_NAME).is_file(),
                    }
                )
                continue
            temporary = self.inbox_root / f".{mission_id}.{os.getpid()}.tmp"
            temporary.mkdir(mode=0o700)
            try:
                shutil.copyfile(payload_path, temporary / PAYLOAD_NAME)
                work_item = seal_fallback_work_item(
                    {
                        "schema_version": WORK_ITEM_SCHEMA,
                        "mission_id": mission_id,
                        "session_id": manifest["session_id"],
                        "parent_campaign_id": manifest["parent_campaign_id"],
                        "parent_contract_sha256": manifest[
                            "parent_contract_sha256"
                        ],
                        "required_child_roles": manifest[
                            "required_child_roles"
                        ],
                        "child_role": manifest["child_role"],
                        "route": "serverless_overflow",
                        "profile": manifest["profile"],
                        "payload_sha256": canonical_sha256(payload),
                        "payload_file": PAYLOAD_NAME,
                        "requested_seconds": manifest["requested_seconds"],
                        "prepared_workload_sha256": manifest["self_sha256"],
                    }
                )
                _write_exclusive(temporary / WORK_ITEM_NAME, _json_bytes(work_item))
                os.replace(temporary, mission_root)
            except BaseException:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
            receipts.append(
                {
                    "mission_id": mission_id,
                    "created": True,
                    "payload_sha256": manifest["payload_sha256"],
                    "work_item_sha256": file_sha256(mission_root / WORK_ITEM_NAME),
                }
            )
        return receipts


__all__ = [
    "PAYLOAD_NAME",
    "ServerlessWorkProducer",
    "ServerlessWorkProducerError",
    "WORKLOAD_NAME",
    "WORKLOAD_SCHEMA",
    "canonical_sha256",
    "file_sha256",
    "seal_serverless_workload",
]
