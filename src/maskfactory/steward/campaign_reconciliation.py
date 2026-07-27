"""Read-only reconciliation of campaign telemetry, ledger, and artifact bytes."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

from .campaign_slo import evaluate_campaign_slo, validate_campaign_slo_replay
from .campaign_telemetry import validate_campaign_telemetry_replay
from .continuous_ledger import canonical_sha256, validate_continuous_binding

ARTIFACT_MANIFEST_SCHEMA = "maskfactory_campaign_artifact_manifest.v1"
RECONCILIATION_SCHEMA = "maskfactory_closed_campaign_reconciliation.v1"
RECONCILED_SLO_SCHEMA = "maskfactory_reconciled_campaign_slo_gate.v1"
ZERO_SHA256 = "0" * 64
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LEDGER_ROUTE_TO_TELEMETRY = {
    "local_pod": "local_pod",
    "serverless": "serverless",
    "serverless_overflow": "serverless",
    "openrouter_advisory": "openrouter_advisory",
    "cpu_safe": "cpu_safe",
}


class CampaignReconciliationError(RuntimeError):
    """Closed campaign evidence is missing, contradictory, or drifted."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise CampaignReconciliationError(f"{field} must be lowercase SHA-256")
    return value


def _identifier(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 200
        or any(character in value for character in "/\\\0")
    ):
        raise CampaignReconciliationError(f"{field} is invalid")
    return value


def _relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise CampaignReconciliationError("artifact relative_path is invalid")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.as_posix() != value:
        raise CampaignReconciliationError("artifact relative_path escapes its root")
    return value


def _seal(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    sealed = deepcopy(dict(value))
    sealed[field] = ZERO_SHA256
    sealed[field] = _canonical_sha256(sealed)
    return sealed


def seal_artifact_manifest(
    *,
    campaign_id: str,
    artifacts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return a canonical manifest for a namespaced campaign artifact root."""

    payload = {
        "schema_version": ARTIFACT_MANIFEST_SCHEMA,
        "campaign_id": campaign_id,
        "artifacts": [dict(row) for row in artifacts],
        "manifest_sha256": ZERO_SHA256,
    }
    _validate_artifact_manifest(payload, verify_hash=False)
    return _seal(payload, "manifest_sha256")


def _validate_artifact_manifest(
    manifest: Mapping[str, Any],
    *,
    verify_hash: bool,
) -> list[dict[str, Any]]:
    if not isinstance(manifest, Mapping) or set(manifest) != {
        "schema_version",
        "campaign_id",
        "artifacts",
        "manifest_sha256",
    }:
        raise CampaignReconciliationError("artifact manifest field set mismatch")
    if manifest.get("schema_version") != ARTIFACT_MANIFEST_SCHEMA:
        raise CampaignReconciliationError("artifact manifest schema mismatch")
    _identifier(manifest.get("campaign_id"), field="artifact campaign_id")
    rows = manifest.get("artifacts")
    if (
        not isinstance(rows, Sequence)
        or isinstance(rows, (str, bytes))
        or not rows
    ):
        raise CampaignReconciliationError("artifact manifest must be non-empty")
    normalized: list[dict[str, Any]] = []
    subjects: set[str] = set()
    paths: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping) or set(raw) != {
            "mission_id",
            "subject_id",
            "relative_path",
            "bytes",
            "sha256",
            "accepted",
        }:
            raise CampaignReconciliationError("artifact row field set mismatch")
        mission_id = _identifier(raw["mission_id"], field="artifact mission_id")
        subject_id = _identifier(raw["subject_id"], field="artifact subject_id")
        relative_path = _relative_path(raw["relative_path"])
        byte_count = raw["bytes"]
        if (
            not isinstance(byte_count, int)
            or isinstance(byte_count, bool)
            or byte_count < 0
        ):
            raise CampaignReconciliationError("artifact bytes must be nonnegative")
        if not isinstance(raw["accepted"], bool):
            raise CampaignReconciliationError("artifact accepted must be boolean")
        if subject_id in subjects:
            raise CampaignReconciliationError("artifact subject IDs must be unique")
        if relative_path in paths:
            raise CampaignReconciliationError("artifact paths must be unique")
        subjects.add(subject_id)
        paths.add(relative_path)
        normalized.append(
            {
                "mission_id": mission_id,
                "subject_id": subject_id,
                "relative_path": relative_path,
                "bytes": byte_count,
                "sha256": _sha256(raw["sha256"], field="artifact sha256"),
                "accepted": raw["accepted"],
            }
        )
    if normalized != sorted(normalized, key=lambda row: row["subject_id"]):
        raise CampaignReconciliationError(
            "artifact rows must be sorted by subject_id"
        )
    if verify_hash:
        declared = _sha256(
            manifest.get("manifest_sha256"),
            field="artifact manifest sha256",
        )
        zeroed = deepcopy(dict(manifest))
        zeroed["manifest_sha256"] = ZERO_SHA256
        if _canonical_sha256(zeroed) != declared:
            raise CampaignReconciliationError(
                "artifact manifest self-hash mismatch"
            )
    return normalized


def _read_ledger(
    database: Path,
    *,
    session_id: str,
    campaign_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]]]:
    resolved = database.resolve(strict=True)
    connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        campaign_row = connection.execute(
            """
            SELECT * FROM continuous_work
            WHERE session_id = ? AND work_kind = 'campaign' AND work_id = ?
            """,
            (session_id, campaign_id),
        ).fetchone()
        if campaign_row is None:
            raise CampaignReconciliationError("campaign ledger row is missing")
        mission_rows = connection.execute(
            """
            SELECT * FROM continuous_work
            WHERE session_id = ? AND work_kind = 'mission' AND campaign_id = ?
            ORDER BY work_id
            """,
            (session_id, campaign_id),
        ).fetchall()
        transitions: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for work_kind, work_id in [
            ("campaign", campaign_id),
            *(("mission", row["work_id"]) for row in mission_rows),
        ]:
            rows = connection.execute(
                """
                SELECT * FROM continuous_transitions
                WHERE session_id = ? AND work_kind = ? AND work_id = ?
                ORDER BY sequence
                """,
                (session_id, work_kind, work_id),
            ).fetchall()
            transitions[(work_kind, work_id)] = [dict(row) for row in rows]
    except sqlite3.DatabaseError as exc:
        raise CampaignReconciliationError("ledger database is unreadable") from exc
    finally:
        connection.close()
    return (
        dict(campaign_row),
        [dict(row) for row in mission_rows],
        transitions,
    )


def _validate_ledger_row(
    row: Mapping[str, Any],
    *,
    expected_kind: str,
    expected_id: str,
    expected_campaign_id: str | None,
) -> dict[str, Any]:
    try:
        binding = validate_continuous_binding(json.loads(row["binding_json"]))
    except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
        raise CampaignReconciliationError("ledger binding is invalid") from exc
    if (
        row.get("work_kind") != expected_kind
        or row.get("work_id") != expected_id
        or row.get("campaign_id") != expected_campaign_id
        or binding["work_kind"] != expected_kind
        or binding["work_id"] != expected_id
        or binding["campaign_id"] != expected_campaign_id
        or row.get("session_id") != binding["session_id"]
        or row.get("payload_sha256") != binding["payload_sha256"]
        or row.get("binding_sha256") != binding["binding_sha256"]
    ):
        raise CampaignReconciliationError("ledger row and binding disagree")
    if row.get("state") != "terminal" or not row.get("terminal_outcome"):
        raise CampaignReconciliationError("closed campaign has nonterminal ledger work")
    return binding


def _validate_transition_chain(
    transitions: Sequence[Mapping[str, Any]],
    *,
    session_id: str,
    work_kind: str,
    work_id: str,
) -> list[str]:
    if not transitions:
        raise CampaignReconciliationError("ledger transition chain is missing")
    previous = ZERO_SHA256
    previous_state: str | None = None
    hashes: list[str] = []
    for sequence, raw in enumerate(transitions, start=1):
        row = dict(raw)
        if (
            row.get("session_id") != session_id
            or row.get("work_kind") != work_kind
            or row.get("work_id") != work_id
            or row.get("sequence") != sequence
            or row.get("from_state") != previous_state
            or row.get("previous_event_sha256") != previous
        ):
            raise CampaignReconciliationError("ledger transition chain drifted")
        _sha256(row.get("evidence_sha256"), field="transition evidence sha256")
        declared = _sha256(row.get("event_sha256"), field="transition event sha256")
        zeroed = dict(row)
        zeroed["event_sha256"] = ZERO_SHA256
        if canonical_sha256(zeroed) != declared:
            raise CampaignReconciliationError("ledger transition event hash drifted")
        previous = declared
        previous_state = row.get("to_state")
        hashes.append(declared)
    if previous_state != "terminal":
        raise CampaignReconciliationError("ledger transition chain is not terminal")
    return hashes


def _event_maps(
    events: Sequence[Mapping[str, Any]],
) -> tuple[
    set[str],
    dict[str, str],
    dict[str, tuple[str, str]],
    set[str],
]:
    mission_sets: dict[str, set[str]] = {}
    for kind in ("planned", "eligible", "completed", "admitted", "terminal_reconciled"):
        mission_sets[kind] = {
            str(event["mission_id"]) for event in events if event.get("kind") == kind
        }
    planned = mission_sets["planned"]
    if any(mission_sets[kind] != planned for kind in mission_sets):
        raise CampaignReconciliationError(
            "closed campaign mission event sets do not reconcile"
        )
    route_by_mission = {
        str(event["mission_id"]): str(event["route"])
        for event in events
        if event.get("kind") == "route_selected"
    }
    produced = {
        str(event["subject_id"]): (
            str(event["mission_id"]),
            str(event["event_sha256"]),
        )
        for event in events
        if event.get("kind") == "artifact_produced"
    }
    accepted = {
        str(event["subject_id"])
        for event in events
        if event.get("kind") == "artifact_accepted"
    }
    return planned, route_by_mission, produced, accepted


def reconcile_closed_campaign(
    *,
    repo_root: Path,
    source: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    telemetry: Mapping[str, Any],
    ledger_database: Path,
    session_id: str,
    artifact_root: Path,
    artifact_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Reconcile one closed campaign without mutating ledger or artifacts."""

    validate_campaign_telemetry_replay(
        telemetry,
        repo_root=repo_root,
        source=source,
        events=events,
    )
    campaign_id = _identifier(source.get("campaign_id"), field="campaign_id")
    session = _identifier(session_id, field="session_id")
    manifest_rows = _validate_artifact_manifest(
        artifact_manifest,
        verify_hash=True,
    )
    if artifact_manifest.get("campaign_id") != campaign_id:
        raise CampaignReconciliationError("artifact campaign binding mismatch")

    campaign_row, mission_rows, transitions = _read_ledger(
        Path(ledger_database),
        session_id=session,
        campaign_id=campaign_id,
    )
    campaign_binding = _validate_ledger_row(
        campaign_row,
        expected_kind="campaign",
        expected_id=campaign_id,
        expected_campaign_id=None,
    )
    if campaign_binding["payload_sha256"] != source.get("campaign_payload_sha256"):
        raise CampaignReconciliationError("campaign payload binding mismatch")
    campaign_transition_hashes = _validate_transition_chain(
        transitions[("campaign", campaign_id)],
        session_id=session,
        work_kind="campaign",
        work_id=campaign_id,
    )

    planned, route_by_mission, produced_events, accepted_events = _event_maps(events)
    ledger_mission_ids = {str(row["work_id"]) for row in mission_rows}
    if ledger_mission_ids != planned:
        raise CampaignReconciliationError(
            "planned missions and ledger missions differ"
        )
    mission_evidence: list[dict[str, Any]] = []
    for row in mission_rows:
        mission_id = str(row["work_id"])
        binding = _validate_ledger_row(
            row,
            expected_kind="mission",
            expected_id=mission_id,
            expected_campaign_id=campaign_id,
        )
        route = LEDGER_ROUTE_TO_TELEMETRY.get(str(row.get("selected_route")))
        if route is None or route_by_mission.get(mission_id) != route:
            raise CampaignReconciliationError("ledger and telemetry routes differ")
        transition_hashes = _validate_transition_chain(
            transitions[("mission", mission_id)],
            session_id=session,
            work_kind="mission",
            work_id=mission_id,
        )
        mission_evidence.append(
            {
                "mission_id": mission_id,
                "payload_sha256": binding["payload_sha256"],
                "binding_sha256": binding["binding_sha256"],
                "route": route,
                "terminal_outcome": str(row["terminal_outcome"]),
                "transition_event_sha256": transition_hashes,
            }
        )

    cells_by_mission = Counter(
        str(event["mission_id"])
        for event in events
        if event.get("kind") == "local_gpu_work_cell"
    )
    releases_by_mission = Counter(
        str(event["mission_id"])
        for event in events
        if event.get("kind") == "local_gpu_release"
    )
    for mission_id, route in route_by_mission.items():
        expected = 1 if route == "local_pod" else 0
        if (
            cells_by_mission[mission_id] != expected
            or releases_by_mission[mission_id] != expected
        ):
            raise CampaignReconciliationError(
                "local route work-cell release evidence is incomplete"
            )

    artifact_base = Path(artifact_root).resolve(strict=True)
    actual_paths = {
        path.relative_to(artifact_base).as_posix()
        for path in artifact_base.rglob("*")
        if path.is_file()
    }
    manifest_paths = {row["relative_path"] for row in manifest_rows}
    if actual_paths != manifest_paths:
        raise CampaignReconciliationError(
            "artifact root and manifest path sets differ"
        )
    manifest_by_subject = {row["subject_id"]: row for row in manifest_rows}
    if set(manifest_by_subject) != set(produced_events):
        raise CampaignReconciliationError(
            "artifact manifest and produced events differ"
        )
    artifact_evidence: list[dict[str, Any]] = []
    for subject_id, row in sorted(manifest_by_subject.items()):
        mission_id, produced_event_sha256 = produced_events[subject_id]
        path = artifact_base / row["relative_path"]
        if (
            row["mission_id"] != mission_id
            or row["accepted"] != (subject_id in accepted_events)
            or path.stat().st_size != row["bytes"]
            or _file_sha256(path) != row["sha256"]
        ):
            raise CampaignReconciliationError(
                "artifact bytes or event binding drifted"
            )
        artifact_evidence.append(
            {
                **row,
                "produced_event_sha256": produced_event_sha256,
            }
        )

    receipt = _seal(
        {
            "schema_version": RECONCILIATION_SCHEMA,
            "session_id": session,
            "campaign_id": campaign_id,
            "campaign_payload_sha256": campaign_binding["payload_sha256"],
            "telemetry_canonical_sha256": _canonical_sha256(telemetry),
            "telemetry_event_sha256": [
                str(event["event_sha256"])
                for event in sorted(events, key=lambda event: event["sequence"])
            ],
            "ledger_database_sha256": _file_sha256(Path(ledger_database)),
            "campaign_binding_sha256": campaign_binding["binding_sha256"],
            "campaign_transition_event_sha256": campaign_transition_hashes,
            "missions": mission_evidence,
            "artifact_manifest_sha256": artifact_manifest["manifest_sha256"],
            "artifact_tree_sha256": _canonical_sha256(artifact_evidence),
            "artifacts": artifact_evidence,
            "counts": {
                "planned_missions": len(planned),
                "terminal_ledger_missions": len(mission_evidence),
                "produced_artifacts": len(artifact_evidence),
                "accepted_artifacts": len(accepted_events),
                "local_work_cells": sum(cells_by_mission.values()),
                "local_releases": sum(releases_by_mission.values()),
            },
            "authority_claimed": False,
            "limitations": [
                "Read-only reconciliation proves exact closed evidence; it does not grant adoption, tracker, mask, Git, provider, or infrastructure authority."
            ],
            "receipt_sha256": ZERO_SHA256,
        },
        "receipt_sha256",
    )
    return receipt


def validate_closed_campaign_reconciliation(
    receipt: Mapping[str, Any],
    **kwargs: Any,
) -> None:
    """Reject a stored receipt whose replay differs from current exact bytes."""

    expected = reconcile_closed_campaign(**kwargs)
    if dict(receipt) != expected:
        raise CampaignReconciliationError(
            "closed campaign reconciliation replay mismatch"
        )


def evaluate_reconciled_campaign_slo(
    *,
    reconciliation: Mapping[str, Any],
    repo_root: Path,
    source: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    telemetry: Mapping[str, Any],
    ledger_database: Path,
    session_id: str,
    artifact_root: Path,
    artifact_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate Plan-27 targets only after exact evidence reconciliation."""

    evidence = {
        "repo_root": repo_root,
        "source": source,
        "events": events,
        "telemetry": telemetry,
        "ledger_database": ledger_database,
        "session_id": session_id,
        "artifact_root": artifact_root,
        "artifact_manifest": artifact_manifest,
    }
    validate_closed_campaign_reconciliation(reconciliation, **evidence)
    slo = evaluate_campaign_slo(telemetry, repo_root=repo_root)
    validate_campaign_slo_replay(
        slo,
        telemetry=telemetry,
        repo_root=repo_root,
    )
    telemetry_sha256 = _canonical_sha256(telemetry)
    if (
        reconciliation.get("campaign_id") != slo["campaign_id"]
        or reconciliation.get("telemetry_canonical_sha256") != telemetry_sha256
    ):
        raise CampaignReconciliationError(
            "SLO and reconciliation campaign bindings differ"
        )
    return _seal(
        {
            "schema_version": RECONCILED_SLO_SCHEMA,
            "campaign_id": slo["campaign_id"],
            "campaign_kind": slo["campaign_kind"],
            "telemetry_canonical_sha256": telemetry_sha256,
            "reconciliation_receipt_sha256": reconciliation["receipt_sha256"],
            "slo_result_sha256": slo["result_sha256"],
            "metrics": slo["metrics"],
            "gates": slo["gates"],
            "passed": slo["passed"],
            "authority_claimed": False,
            "limitations": [
                "The gate proves one reconciled campaign; sustained production acceptance still requires three consecutive real mixed campaigns."
            ],
            "gate_sha256": ZERO_SHA256,
        },
        "gate_sha256",
    )


def validate_reconciled_campaign_slo_replay(
    result: Mapping[str, Any],
    **kwargs: Any,
) -> None:
    """Reject a reconciled target gate that differs from exact current evidence."""

    expected = evaluate_reconciled_campaign_slo(**kwargs)
    if dict(result) != expected:
        raise CampaignReconciliationError(
            "reconciled campaign SLO replay mismatch"
        )


__all__ = [
    "ARTIFACT_MANIFEST_SCHEMA",
    "CampaignReconciliationError",
    "RECONCILIATION_SCHEMA",
    "RECONCILED_SLO_SCHEMA",
    "evaluate_reconciled_campaign_slo",
    "reconcile_closed_campaign",
    "seal_artifact_manifest",
    "validate_closed_campaign_reconciliation",
    "validate_reconciled_campaign_slo_replay",
]
