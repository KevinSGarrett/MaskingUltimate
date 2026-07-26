"""Consolidated, authority-free adoption packets for patch/repair campaigns."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from maskfactory.steward.patch_repair_campaign import (
    BINDING_NAME,
    TERMINAL_NAME,
    verify_campaign_terminal,
)


SCHEMA_VERSION = "maskfactory_campaign_adoption_packet.v1"
PACKET_NAME = "adoption_packet.json"
ZERO_SHA256 = "0" * 64
DECISIONS = frozenset({"ADOPT", "PARTIALLY_ADOPT", "REJECT"})
TRACKER_STATUSES = frozenset(
    {
        "open",
        "in_progress",
        "partially_complete",
        "blocked",
        "complete",
        "failed",
        "deferred",
    }
)
_AUTHORITY_CEILING = {
    "apply_patch": False,
    "git": False,
    "github": False,
    "tracker": False,
    "final_adoption": False,
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_PACKET_FIELDS = {
    "schema_version",
    "mission_id",
    "source_packet_sha256",
    "campaign_binding",
    "campaign_terminal",
    "decision",
    "decision_reason",
    "changes",
    "focused_tests",
    "limitations",
    "exceptions",
    "tracker_proposals",
    "authority",
    "packet_sha256",
}


class CampaignAdoptionPacketError(RuntimeError):
    """Adoption evidence is missing, duplicated, unsupported, or overclaimed."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CampaignAdoptionPacketError(
            "adoption packet is not canonical JSON"
        ) from exc


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _seal(value: Mapping[str, Any]) -> dict[str, Any]:
    sealed = deepcopy(dict(value))
    sealed["packet_sha256"] = ZERO_SHA256
    sealed["packet_sha256"] = _canonical_sha256(sealed)
    return sealed


def _verify_self_hash(value: Mapping[str, Any]) -> None:
    declared = value.get("packet_sha256")
    if not isinstance(declared, str) or not _SHA256_RE.fullmatch(declared):
        raise CampaignAdoptionPacketError("adoption packet SHA-256 is invalid")
    zeroed = deepcopy(dict(value))
    zeroed["packet_sha256"] = ZERO_SHA256
    if _canonical_sha256(zeroed) != declared:
        raise CampaignAdoptionPacketError(
            "adoption packet canonical self-hash mismatch"
        )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CampaignAdoptionPacketError(f"evidence is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise CampaignAdoptionPacketError(f"evidence must be an object: {path}")
    return value


def _identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise CampaignAdoptionPacketError(f"{field} is invalid")
    return value


def _sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise CampaignAdoptionPacketError(f"{field} is invalid")
    return value


def _text(value: object, *, field: str, maximum_bytes: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise CampaignAdoptionPacketError(f"{field} is invalid")
    return value.strip()


def _strings(values: Sequence[str], *, field: str) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise CampaignAdoptionPacketError(f"{field} must be a sequence")
    normalized = [_text(value, field=field) for value in values]
    if len(normalized) != len(set(normalized)):
        raise CampaignAdoptionPacketError(f"{field} must be unique")
    return normalized


def _normalize_exceptions(values: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise CampaignAdoptionPacketError("exceptions must be a sequence")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in values:
        if not isinstance(row, Mapping) or set(row) != {
            "code",
            "detail",
            "evidence_sha256",
        }:
            raise CampaignAdoptionPacketError("exception field set mismatch")
        code = _identifier(row["code"], field="exception code")
        if code in seen:
            raise CampaignAdoptionPacketError("exception codes must be unique")
        seen.add(code)
        normalized.append(
            {
                "code": code,
                "detail": _text(row["detail"], field="exception detail"),
                "evidence_sha256": _sha256(
                    row["evidence_sha256"],
                    field="exception evidence SHA-256",
                ),
            }
        )
    return sorted(normalized, key=lambda row: row["code"])


def _normalize_tracker_proposals(
    values: Sequence[Mapping[str, Any]],
    *,
    decision: str,
    terminal_outcome: str,
) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise CampaignAdoptionPacketError("tracker proposals must be a sequence")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in values:
        if not isinstance(row, Mapping) or set(row) != {
            "item_id",
            "status",
            "percent",
            "evidence",
        }:
            raise CampaignAdoptionPacketError("tracker proposal field set mismatch")
        item_id = _identifier(row["item_id"], field="tracker item ID")
        if item_id in seen:
            raise CampaignAdoptionPacketError("tracker proposals must be unique")
        seen.add(item_id)
        status = row["status"]
        percent = row["percent"]
        if status not in TRACKER_STATUSES:
            raise CampaignAdoptionPacketError("tracker proposal status is unsupported")
        if (
            not isinstance(percent, int)
            or isinstance(percent, bool)
            or not 0 <= percent <= 100
        ):
            raise CampaignAdoptionPacketError("tracker proposal percent is invalid")
        if status == "complete" and (
            percent != 100
            or decision != "ADOPT"
            or terminal_outcome != "SUCCESS"
        ):
            raise CampaignAdoptionPacketError(
                "tracker completion proposal overclaims campaign evidence"
            )
        normalized.append(
            {
                "item_id": item_id,
                "status": status,
                "percent": percent,
                "evidence": _text(
                    row["evidence"],
                    field="tracker proposal evidence",
                ),
            }
        )
    return sorted(normalized, key=lambda row: row["item_id"])


def _derive_campaign_evidence(
    campaign_root: Path,
    terminal: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    changes: list[dict[str, Any]] = []
    focused_tests: list[dict[str, Any]] = []
    for row in terminal["attempts"]:
        attempt = row["attempt"]
        proposal_path = campaign_root / row["proposal_file"]
        proposal = _read_json(proposal_path)
        for edit in proposal["edits"]:
            changes.append(
                {
                    "attempt": attempt,
                    "path": edit["path"],
                    "expected_sha256": edit["expected_sha256"],
                    "replacement_sha256": edit["replacement_sha256"],
                    "proposal_file": row["proposal_file"],
                    "proposal_file_sha256": _file_sha256(proposal_path),
                    "proposal_sha256": row["proposal_sha256"],
                }
            )
        if row["result_file"] is None:
            focused_tests.append(
                {
                    "attempt": attempt,
                    "status": "NOT_RUN",
                    "diagnostic_code": "NOT_RUN",
                    "diagnostic": "focused test was not run",
                    "result_file": None,
                    "result_file_sha256": None,
                    "result_sha256": None,
                    "evidence": [],
                }
            )
            continue
        result_path = campaign_root / row["result_file"]
        result = _read_json(result_path)
        focused_tests.append(
            {
                "attempt": attempt,
                "status": "PASS" if result["passed"] else "FAIL",
                "diagnostic_code": result["diagnostic_code"],
                "diagnostic": result["diagnostic"],
                "result_file": row["result_file"],
                "result_file_sha256": _file_sha256(result_path),
                "result_sha256": row["result_sha256"],
                "evidence": result["evidence"],
            }
        )
    return changes, focused_tests


def build_campaign_adoption_packet(
    *,
    campaign_root: Path,
    output_root: Path,
    decision: str,
    decision_reason: str,
    limitations: Sequence[str],
    exceptions: Sequence[Mapping[str, Any]],
    tracker_proposals: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Create exactly one consolidated packet from verified campaign evidence."""

    campaign = campaign_root.resolve(strict=True)
    terminal = verify_campaign_terminal(campaign)
    if decision not in DECISIONS:
        raise CampaignAdoptionPacketError("adoption decision is unsupported")
    if decision == "ADOPT" and terminal["outcome"] != "SUCCESS":
        raise CampaignAdoptionPacketError(
            "ADOPT overclaims a non-successful campaign terminal"
        )
    normalized_limitations = _strings(limitations, field="limitations")
    if decision in {"PARTIALLY_ADOPT", "REJECT"} and not normalized_limitations:
        raise CampaignAdoptionPacketError(
            f"{decision} requires at least one limitation"
        )
    normalized_exceptions = _normalize_exceptions(exceptions)
    normalized_tracker = _normalize_tracker_proposals(
        tracker_proposals,
        decision=decision,
        terminal_outcome=terminal["outcome"],
    )
    binding_path = campaign / BINDING_NAME
    terminal_path = campaign / TERMINAL_NAME
    changes, focused_tests = _derive_campaign_evidence(campaign, terminal)
    packet = _seal(
        {
            "schema_version": SCHEMA_VERSION,
            "mission_id": terminal["mission_id"],
            "source_packet_sha256": terminal["packet_sha256"],
            "campaign_binding": {
                "path": BINDING_NAME,
                "raw_sha256": _file_sha256(binding_path),
                "self_sha256": terminal["binding_sha256"],
            },
            "campaign_terminal": {
                "path": TERMINAL_NAME,
                "raw_sha256": _file_sha256(terminal_path),
                "self_sha256": terminal["terminal_sha256"],
                "outcome": terminal["outcome"],
            },
            "decision": decision,
            "decision_reason": _text(
                decision_reason,
                field="decision reason",
            ),
            "changes": changes,
            "focused_tests": focused_tests,
            "limitations": normalized_limitations,
            "exceptions": normalized_exceptions,
            "tracker_proposals": normalized_tracker,
            "authority": dict(_AUTHORITY_CEILING),
            "packet_sha256": ZERO_SHA256,
        }
    )
    destination = output_root.resolve(strict=False)
    try:
        destination.relative_to(campaign)
    except ValueError:
        pass
    else:
        raise CampaignAdoptionPacketError(
            "adoption packet root must be outside the campaign evidence root"
        )
    if destination.exists():
        raise CampaignAdoptionPacketError("adoption packet root already exists")
    if not destination.parent.is_dir():
        raise CampaignAdoptionPacketError(
            "adoption packet parent must already exist"
        )
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent)
    )
    try:
        payload = json.dumps(
            packet,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8") + b"\n"
        with (temporary / PACKET_NAME).open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        validate_campaign_adoption_packet(temporary, campaign_root=campaign)
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return packet


def validate_campaign_adoption_packet(
    packet_root: Path,
    *,
    campaign_root: Path,
) -> dict[str, Any]:
    """Validate exact packet count, hashes, campaign bindings, and claim level."""

    root = packet_root.resolve(strict=True)
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if actual_files != {PACKET_NAME}:
        raise CampaignAdoptionPacketError(
            "exactly one consolidated adoption packet is required"
        )
    packet = _read_json(root / PACKET_NAME)
    if set(packet) != _PACKET_FIELDS:
        raise CampaignAdoptionPacketError("adoption packet field set mismatch")
    _verify_self_hash(packet)
    if (
        packet.get("schema_version") != SCHEMA_VERSION
        or packet.get("authority") != _AUTHORITY_CEILING
        or packet.get("decision") not in DECISIONS
    ):
        raise CampaignAdoptionPacketError(
            "adoption packet schema, decision, or authority mismatch"
        )
    campaign = campaign_root.resolve(strict=True)
    terminal = verify_campaign_terminal(campaign)
    if (
        packet.get("mission_id") != terminal["mission_id"]
        or packet.get("source_packet_sha256") != terminal["packet_sha256"]
        or packet.get("campaign_binding")
        != {
            "path": BINDING_NAME,
            "raw_sha256": _file_sha256(campaign / BINDING_NAME),
            "self_sha256": terminal["binding_sha256"],
        }
        or packet.get("campaign_terminal")
        != {
            "path": TERMINAL_NAME,
            "raw_sha256": _file_sha256(campaign / TERMINAL_NAME),
            "self_sha256": terminal["terminal_sha256"],
            "outcome": terminal["outcome"],
        }
    ):
        raise CampaignAdoptionPacketError("adoption packet campaign binding mismatch")
    if packet["decision"] == "ADOPT" and terminal["outcome"] != "SUCCESS":
        raise CampaignAdoptionPacketError(
            "ADOPT overclaims a non-successful campaign terminal"
        )
    changes, focused_tests = _derive_campaign_evidence(campaign, terminal)
    if packet.get("changes") != changes or packet.get("focused_tests") != focused_tests:
        raise CampaignAdoptionPacketError(
            "adoption packet proposal or test evidence mismatch"
        )
    limitations = _strings(packet.get("limitations"), field="limitations")
    if packet.get("limitations") != limitations:
        raise CampaignAdoptionPacketError(
            "adoption packet limitations are not canonical"
        )
    if packet["decision"] in {"PARTIALLY_ADOPT", "REJECT"} and not limitations:
        raise CampaignAdoptionPacketError(
            f"{packet['decision']} requires at least one limitation"
        )
    if packet.get("exceptions") != _normalize_exceptions(packet.get("exceptions")):
        raise CampaignAdoptionPacketError("adoption packet exceptions are not canonical")
    if packet.get("tracker_proposals") != _normalize_tracker_proposals(
        packet.get("tracker_proposals"),
        decision=packet["decision"],
        terminal_outcome=terminal["outcome"],
    ):
        raise CampaignAdoptionPacketError(
            "adoption packet tracker proposals are not canonical"
        )
    if packet.get("decision_reason") != _text(
        packet.get("decision_reason"),
        field="decision reason",
    ):
        raise CampaignAdoptionPacketError(
            "adoption packet decision reason is not canonical"
        )
    return packet


__all__ = [
    "CampaignAdoptionPacketError",
    "DECISIONS",
    "PACKET_NAME",
    "SCHEMA_VERSION",
    "build_campaign_adoption_packet",
    "validate_campaign_adoption_packet",
]
