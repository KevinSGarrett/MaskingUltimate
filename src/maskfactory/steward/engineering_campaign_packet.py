"""One immutable Codex boundary for a 25-mission engineering campaign.

The per-mission patch/repair controller intentionally owns only one mission.
This module closes the campaign-level gap: it verifies exactly 25 terminal
mission roots, replays the campaign ledger/telemetry/artifact reconciliation
and SLO gate, and emits one authority-free adoption recommendation.
"""

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

from .campaign_reconciliation import (
    validate_closed_campaign_reconciliation,
    validate_reconciled_campaign_slo_replay,
)
from .continuous_contract import canonical_sha256
from .patch_repair_campaign import (
    BINDING_NAME,
    TERMINAL_NAME,
    verify_campaign_terminal,
)

SCHEMA_VERSION = "maskfactory.engineering_campaign_packet.v1"
PACKET_NAME = "engineering_campaign_packet.json"
ENGINEERING_MISSION_COUNT = 25
ZERO_SHA256 = "0" * 64
RECOMMENDATIONS = frozenset({"ADOPT", "PARTIALLY_ADOPT", "REJECT"})
AUTHORITY = {
    "apply_patch": False,
    "git": False,
    "github": False,
    "credentials": False,
    "infrastructure": False,
    "runpod": False,
    "tracker": False,
    "final_adoption": False,
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_PACKET_FIELDS = {
    "schema_version",
    "campaign_id",
    "session_id",
    "campaign_kind",
    "campaign_payload_sha256",
    "source_commit_sha256",
    "mission_count",
    "mission_order",
    "missions",
    "telemetry_sha256",
    "reconciliation_receipt_sha256",
    "reconciled_slo_gate_sha256",
    "artifact_manifest_sha256",
    "recommendation",
    "recommendation_reason",
    "limitations",
    "exceptions",
    "tracker_proposals",
    "authority",
    "packet_sha256",
}


class EngineeringCampaignPacketError(RuntimeError):
    """Campaign evidence is incomplete, contradictory, or overclaims authority."""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise EngineeringCampaignPacketError(f"{field} must be lowercase SHA-256")
    return value


def _identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise EngineeringCampaignPacketError(f"{field} is invalid")
    return value


def _text(value: object, *, field: str, maximum_bytes: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise EngineeringCampaignPacketError(f"{field} is invalid")
    return value.strip()


def _strings(values: Sequence[str], *, field: str) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise EngineeringCampaignPacketError(f"{field} must be a sequence")
    normalized = [_text(value, field=field) for value in values]
    if len(normalized) != len(set(normalized)):
        raise EngineeringCampaignPacketError(f"{field} must be unique")
    return normalized


def _file_tree(root: Path) -> tuple[list[dict[str, Any]], str]:
    rows = [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _file_sha256(path),
        }
        for path in sorted(
            (candidate for candidate in root.rglob("*") if candidate.is_file()),
            key=lambda candidate: candidate.relative_to(root).as_posix(),
        )
    ]
    return rows, canonical_sha256({"files": rows})


def _mission_evidence(
    mission_roots: Sequence[Path],
) -> list[dict[str, Any]]:
    if (
        not isinstance(mission_roots, Sequence)
        or isinstance(mission_roots, (str, bytes))
        or len(mission_roots) != ENGINEERING_MISSION_COUNT
    ):
        raise EngineeringCampaignPacketError(
            "engineering campaign requires exactly 25 mission roots"
        )
    evidence: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_roots: set[str] = set()
    for raw_root in mission_roots:
        root = Path(raw_root).resolve(strict=True)
        root_name = root.name
        if not root_name or root_name in seen_roots:
            raise EngineeringCampaignPacketError("mission evidence root names must be unique")
        seen_roots.add(root_name)
        terminal = verify_campaign_terminal(root)
        mission_id = terminal["mission_id"]
        if mission_id in seen_ids:
            raise EngineeringCampaignPacketError("mission identities must be unique")
        seen_ids.add(mission_id)
        rows, tree_sha256 = _file_tree(root)
        evidence.append(
            {
                "mission_id": mission_id,
                "evidence_root_name": root_name,
                "source_packet_sha256": terminal["packet_sha256"],
                "outcome": terminal["outcome"],
                "attempt_count": terminal["attempt_count"],
                "binding": {
                    "path": BINDING_NAME,
                    "raw_sha256": _file_sha256(root / BINDING_NAME),
                    "self_sha256": terminal["binding_sha256"],
                },
                "terminal": {
                    "path": TERMINAL_NAME,
                    "raw_sha256": _file_sha256(root / TERMINAL_NAME),
                    "self_sha256": terminal["terminal_sha256"],
                },
                "evidence_file_count": len(rows),
                "evidence_tree_sha256": tree_sha256,
            }
        )
    return evidence


def _exceptions(values: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise EngineeringCampaignPacketError("exceptions must be a sequence")
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in values:
        if not isinstance(row, Mapping) or set(row) != {
            "mission_id",
            "code",
            "detail",
            "evidence_sha256",
        }:
            raise EngineeringCampaignPacketError("exception field set mismatch")
        normalized = {
            "mission_id": _identifier(row["mission_id"], field="exception mission"),
            "code": _identifier(row["code"], field="exception code"),
            "detail": _text(row["detail"], field="exception detail"),
            "evidence_sha256": _sha256(
                row["evidence_sha256"],
                field="exception evidence",
            ),
        }
        identity = (normalized["mission_id"], normalized["code"])
        if identity in seen:
            raise EngineeringCampaignPacketError("exceptions must be unique")
        seen.add(identity)
        result.append(normalized)
    return sorted(result, key=lambda row: (row["mission_id"], row["code"]))


def _tracker_proposals(
    values: Sequence[Mapping[str, Any]],
    *,
    recommendation: str,
) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise EngineeringCampaignPacketError("tracker_proposals must be a sequence")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in values:
        if not isinstance(row, Mapping) or set(row) != {
            "item_id",
            "status",
            "percent",
            "evidence",
        }:
            raise EngineeringCampaignPacketError("tracker proposal field set mismatch")
        item_id = _identifier(row["item_id"], field="tracker item")
        if item_id in seen:
            raise EngineeringCampaignPacketError("tracker proposal identities must be unique")
        seen.add(item_id)
        status = row["status"]
        percent = row["percent"]
        if status not in {
            "open",
            "in_progress",
            "partially_complete",
            "blocked",
            "complete",
            "failed",
            "deferred",
        }:
            raise EngineeringCampaignPacketError("tracker proposal status is unsupported")
        if not isinstance(percent, int) or isinstance(percent, bool) or not 0 <= percent <= 100:
            raise EngineeringCampaignPacketError("tracker proposal percent is invalid")
        if status == "complete" and (recommendation != "ADOPT" or percent != 100):
            raise EngineeringCampaignPacketError(
                "tracker completion proposal overclaims the recommendation"
            )
        result.append(
            {
                "item_id": item_id,
                "status": status,
                "percent": percent,
                "evidence": _text(row["evidence"], field="tracker evidence"),
            }
        )
    return sorted(result, key=lambda row: row["item_id"])


def _validate_campaign_sources(
    *,
    repo_root: Path,
    source: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    telemetry: Mapping[str, Any],
    ledger_database: Path,
    session_id: str,
    artifact_root: Path,
    artifact_manifest: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    reconciled_slo_gate: Mapping[str, Any],
) -> None:
    kwargs = {
        "repo_root": Path(repo_root),
        "source": source,
        "events": events,
        "telemetry": telemetry,
        "ledger_database": Path(ledger_database),
        "session_id": session_id,
        "artifact_root": Path(artifact_root),
        "artifact_manifest": artifact_manifest,
    }
    validate_closed_campaign_reconciliation(reconciliation, **kwargs)
    validate_reconciled_campaign_slo_replay(
        reconciled_slo_gate,
        reconciliation=reconciliation,
        **kwargs,
    )


def _packet(
    *,
    mission_roots: Sequence[Path],
    source: Mapping[str, Any],
    telemetry: Mapping[str, Any],
    session_id: str,
    artifact_manifest: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    reconciled_slo_gate: Mapping[str, Any],
    recommendation: str,
    recommendation_reason: str,
    limitations: Sequence[str],
    exceptions: Sequence[Mapping[str, Any]],
    tracker_proposals: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if recommendation not in RECOMMENDATIONS:
        raise EngineeringCampaignPacketError("recommendation is unsupported")
    mission_evidence = _mission_evidence(mission_roots)
    campaign_id = _identifier(source.get("campaign_id"), field="campaign_id")
    session = _identifier(session_id, field="session_id")
    if (
        source.get("campaign_kind") != "engineering"
        or reconciliation.get("campaign_id") != campaign_id
        or reconciled_slo_gate.get("campaign_id") != campaign_id
    ):
        raise EngineeringCampaignPacketError("campaign source bindings differ")
    reconciliation_ids = [row.get("mission_id") for row in reconciliation.get("missions", [])]
    mission_order = [row["mission_id"] for row in mission_evidence]
    if reconciliation_ids != mission_order:
        raise EngineeringCampaignPacketError("mission roots and reconciled ledger order differ")
    all_success = all(row["outcome"] == "SUCCESS" for row in mission_evidence)
    if recommendation == "ADOPT" and (
        not all_success or reconciled_slo_gate.get("passed") is not True
    ):
        raise EngineeringCampaignPacketError(
            "ADOPT requires 25 successful missions and a passing reconciled SLO"
        )
    normalized_limitations = _strings(limitations, field="limitations")
    if recommendation != "ADOPT" and not normalized_limitations:
        raise EngineeringCampaignPacketError("non-ADOPT recommendation requires a limitation")
    packet = {
        "schema_version": SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "session_id": session,
        "campaign_kind": "engineering",
        "campaign_payload_sha256": _sha256(
            source.get("campaign_payload_sha256"),
            field="campaign payload",
        ),
        "source_commit_sha256": _sha256(
            source.get("source_commit_sha256"),
            field="source commit",
        ),
        "mission_count": len(mission_evidence),
        "mission_order": mission_order,
        "missions": mission_evidence,
        "telemetry_sha256": canonical_sha256(telemetry),
        "reconciliation_receipt_sha256": _sha256(
            reconciliation.get("receipt_sha256"),
            field="reconciliation receipt",
        ),
        "reconciled_slo_gate_sha256": _sha256(
            reconciled_slo_gate.get("gate_sha256"),
            field="reconciled SLO gate",
        ),
        "artifact_manifest_sha256": _sha256(
            artifact_manifest.get("manifest_sha256"),
            field="artifact manifest",
        ),
        "recommendation": recommendation,
        "recommendation_reason": _text(
            recommendation_reason,
            field="recommendation reason",
        ),
        "limitations": normalized_limitations,
        "exceptions": _exceptions(exceptions),
        "tracker_proposals": _tracker_proposals(
            tracker_proposals,
            recommendation=recommendation,
        ),
        "authority": dict(AUTHORITY),
        "packet_sha256": ZERO_SHA256,
    }
    packet["packet_sha256"] = canonical_sha256(packet)
    return packet


def build_engineering_campaign_packet(
    *,
    repo_root: Path,
    source: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    telemetry: Mapping[str, Any],
    ledger_database: Path,
    session_id: str,
    artifact_root: Path,
    artifact_manifest: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    reconciled_slo_gate: Mapping[str, Any],
    mission_roots: Sequence[Path],
    output_root: Path,
    recommendation: str,
    recommendation_reason: str,
    limitations: Sequence[str],
    exceptions: Sequence[Mapping[str, Any]],
    tracker_proposals: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Replay all campaign evidence and write one immutable adoption boundary."""

    _validate_campaign_sources(
        repo_root=repo_root,
        source=source,
        events=events,
        telemetry=telemetry,
        ledger_database=ledger_database,
        session_id=session_id,
        artifact_root=artifact_root,
        artifact_manifest=artifact_manifest,
        reconciliation=reconciliation,
        reconciled_slo_gate=reconciled_slo_gate,
    )
    packet = _packet(
        mission_roots=mission_roots,
        source=source,
        telemetry=telemetry,
        session_id=session_id,
        artifact_manifest=artifact_manifest,
        reconciliation=reconciliation,
        reconciled_slo_gate=reconciled_slo_gate,
        recommendation=recommendation,
        recommendation_reason=recommendation_reason,
        limitations=limitations,
        exceptions=exceptions,
        tracker_proposals=tracker_proposals,
    )
    destination = Path(output_root).resolve(strict=False)
    if destination.exists() or not destination.parent.is_dir():
        raise EngineeringCampaignPacketError(
            "output root must be an absent child of an existing directory"
        )
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent))
    try:
        payload = (
            json.dumps(
                packet,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
            + b"\n"
        )
        with (temporary / PACKET_NAME).open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        validate_engineering_campaign_packet(
            temporary,
            repo_root=repo_root,
            source=source,
            events=events,
            telemetry=telemetry,
            ledger_database=ledger_database,
            session_id=session_id,
            artifact_root=artifact_root,
            artifact_manifest=artifact_manifest,
            reconciliation=reconciliation,
            reconciled_slo_gate=reconciled_slo_gate,
            mission_roots=mission_roots,
        )
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return packet


def validate_engineering_campaign_packet(
    packet_root: Path,
    *,
    repo_root: Path,
    source: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    telemetry: Mapping[str, Any],
    ledger_database: Path,
    session_id: str,
    artifact_root: Path,
    artifact_manifest: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    reconciled_slo_gate: Mapping[str, Any],
    mission_roots: Sequence[Path],
) -> dict[str, Any]:
    """Reject packet, source, mission-tree, ledger, telemetry, or SLO drift."""

    root = Path(packet_root).resolve(strict=True)
    actual_paths = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if actual_paths != {PACKET_NAME}:
        raise EngineeringCampaignPacketError("exactly one engineering campaign packet is required")
    try:
        packet = json.loads((root / PACKET_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EngineeringCampaignPacketError("campaign packet is unreadable") from exc
    if (
        not isinstance(packet, dict)
        or set(packet) != _PACKET_FIELDS
        or packet.get("schema_version") != SCHEMA_VERSION
        or packet.get("authority") != AUTHORITY
    ):
        raise EngineeringCampaignPacketError("campaign packet field, schema, or authority mismatch")
    declared = _sha256(packet.get("packet_sha256"), field="packet self hash")
    zeroed = deepcopy(packet)
    zeroed["packet_sha256"] = ZERO_SHA256
    if canonical_sha256(zeroed) != declared:
        raise EngineeringCampaignPacketError("campaign packet self-hash mismatch")
    _validate_campaign_sources(
        repo_root=repo_root,
        source=source,
        events=events,
        telemetry=telemetry,
        ledger_database=ledger_database,
        session_id=session_id,
        artifact_root=artifact_root,
        artifact_manifest=artifact_manifest,
        reconciliation=reconciliation,
        reconciled_slo_gate=reconciled_slo_gate,
    )
    expected = _packet(
        mission_roots=mission_roots,
        source=source,
        telemetry=telemetry,
        session_id=session_id,
        artifact_manifest=artifact_manifest,
        reconciliation=reconciliation,
        reconciled_slo_gate=reconciled_slo_gate,
        recommendation=packet["recommendation"],
        recommendation_reason=packet["recommendation_reason"],
        limitations=packet["limitations"],
        exceptions=packet["exceptions"],
        tracker_proposals=packet["tracker_proposals"],
    )
    if packet != expected:
        raise EngineeringCampaignPacketError(
            "engineering campaign packet deterministic replay mismatch"
        )
    return packet


__all__ = [
    "ENGINEERING_MISSION_COUNT",
    "EngineeringCampaignPacketError",
    "PACKET_NAME",
    "SCHEMA_VERSION",
    "build_engineering_campaign_packet",
    "validate_engineering_campaign_packet",
]
