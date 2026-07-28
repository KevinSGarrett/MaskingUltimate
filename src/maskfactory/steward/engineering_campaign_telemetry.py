"""Replay a terminal engineering campaign into frozen Plan-27 telemetry."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .campaign_slo import evaluate_campaign_slo, validate_campaign_slo_replay
from .campaign_telemetry import (
    build_telemetry_event,
    reconcile_campaign_telemetry,
    validate_campaign_telemetry_replay,
)
from .continuous_contract import canonical_sha256
from .engineering_campaign_runtime import CAMPAIGN_SIZE
from .engineering_campaign_runtime_packet import (
    PACKET_NAME,
    validate_engineering_campaign_runtime_packet,
)

SCHEMA_VERSION = "maskfactory.engineering_campaign_telemetry_bundle.v1"
BUNDLE_NAME = "engineering_campaign_telemetry_bundle.json"
ZERO_SHA256 = "0" * 64


class EngineeringCampaignTelemetryError(RuntimeError):
    """Terminal runtime evidence cannot be reconciled into campaign telemetry."""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EngineeringCampaignTelemetryError(
            f"campaign evidence is unreadable: {path.name}"
        ) from exc
    if not isinstance(value, dict):
        raise EngineeringCampaignTelemetryError(f"campaign evidence is not an object: {path.name}")
    return value


def _iso_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _runtime_rows(
    database: Path,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    uri = f"{database.resolve(strict=True).as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        missions = [
            dict(row)
            for row in connection.execute(
                """
                SELECT
                    session_id,
                    job_id,
                    state,
                    request_sha256,
                    request_started_at,
                    terminal_reason,
                    release_kind,
                    release_sha256,
                    created_at,
                    updated_at
                FROM steward_missions
                ORDER BY job_id
                """
            )
        ]
        runs_by_job: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in connection.execute(
            """
            SELECT
                session_id,
                job_id,
                run_number,
                request_sha256,
                response_sha256,
                proposal_sha256,
                proposal_canonical_sha256,
                created_at
            FROM steward_runs
            ORDER BY job_id, run_number
            """
        ):
            run = dict(row)
            runs_by_job[str(run["job_id"])].append(run)
    except sqlite3.Error as exc:
        raise EngineeringCampaignTelemetryError("runtime database schema is unavailable") from exc
    finally:
        connection.close()
    return missions, dict(runs_by_job)


def _validate_runtime_rows(
    *,
    campaign_root: Path,
    missions: Sequence[Mapping[str, Any]],
    runs_by_job: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    if len(missions) != CAMPAIGN_SIZE:
        raise EngineeringCampaignTelemetryError(
            "runtime ledger does not contain exactly 25 missions"
        )
    session_ids = {row["session_id"] for row in missions}
    job_ids = [str(row["job_id"]) for row in missions]
    if len(session_ids) != 1 or len(job_ids) != len(set(job_ids)):
        raise EngineeringCampaignTelemetryError(
            "runtime mission identity is duplicated or cross-session"
        )
    artifacts: list[dict[str, Any]] = []
    response_ids: set[str] = set()
    for mission in missions:
        job_id = str(mission["job_id"])
        runs = list(runs_by_job.get(job_id, []))
        if (
            mission["state"] != "completed"
            or mission["terminal_reason"] != "accepted_advisory_output"
            or not isinstance(mission["release_sha256"], str)
            or len(mission["release_sha256"]) != 64
            or len(runs) != 2
            or [row["run_number"] for row in runs] != [1, 2]
            or any(
                row["session_id"] != mission["session_id"]
                or row["request_sha256"] != mission["request_sha256"]
                for row in runs
            )
        ):
            raise EngineeringCampaignTelemetryError(
                f"runtime mission is not a released two-run success: {job_id}"
            )
        for run in runs:
            response_id = f"{job_id}:run-{run['run_number']}"
            if response_id in response_ids:
                raise EngineeringCampaignTelemetryError("runtime request identity is duplicated")
            response_ids.add(response_id)
        proposal_path = campaign_root / "missions" / job_id / "proposal.json"
        proposal_sha256 = _file_sha256(proposal_path)
        if any(row["proposal_sha256"] != proposal_sha256 for row in runs):
            raise EngineeringCampaignTelemetryError(
                f"accepted proposal bytes drifted from runtime ledger: {job_id}"
            )
        artifacts.append(
            {
                "mission_id": job_id,
                "subject_id": f"{job_id}:proposal",
                "relative_path": proposal_path.relative_to(campaign_root).as_posix(),
                "bytes": proposal_path.stat().st_size,
                "sha256": proposal_sha256,
                "proposal_canonical_sha256": runs[-1]["proposal_canonical_sha256"],
                "accepted": True,
            }
        )
    if set(runs_by_job) != set(job_ids) or len(response_ids) != CAMPAIGN_SIZE * 2:
        raise EngineeringCampaignTelemetryError(
            "runtime request population does not exactly match missions"
        )
    return artifacts


def _build_events(
    *,
    campaign_id: str,
    missions: Sequence[Mapping[str, Any]],
    runs_by_job: Mapping[str, Sequence[Mapping[str, Any]]],
    startup_seconds: float,
    inference_seconds: float,
    terminal_adoption_usage_units: float,
    terminal_adoption_review_seconds: float,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    def add(kind: str, mission_id: str | None = None, **kwargs: object) -> None:
        events.append(
            build_telemetry_event(
                campaign_id=campaign_id,
                sequence=len(events) + 1,
                kind=kind,
                mission_id=mission_id,
                **kwargs,
            )
        )

    first_job_id = str(missions[0]["job_id"])
    for mission in missions:
        job_id = str(mission["job_id"])
        add("planned", job_id)
        add("eligible", job_id)
        add("route_selected", job_id, route="local_pod")
        add("autonomously_prepared", job_id)
        add("admitted", job_id)
        if job_id == first_job_id:
            add(
                "local_gpu_work_cell",
                job_id,
                subject_id=f"{campaign_id}:owned-model-lifetime",
            )
            add("model_startup", job_id, duration_seconds=startup_seconds)
            add("inference", job_id, duration_seconds=inference_seconds)
        for run in runs_by_job[job_id]:
            add(
                "inference_submission",
                job_id,
                subject_id=f"{job_id}:run-{run['run_number']}",
            )
        add("completed", job_id)
        add("artifact_produced", job_id, subject_id=f"{job_id}:proposal")
        add("accepted", job_id)
        add("artifact_accepted", job_id, subject_id=f"{job_id}:proposal")
        add("terminal_reconciled", job_id)
    add(
        "local_gpu_release",
        first_job_id,
        subject_id=f"{campaign_id}:owned-model-lifetime",
    )
    add(
        "codex_intervention",
        value="terminal_adoption",
        duration_seconds=terminal_adoption_review_seconds,
        numeric_value=terminal_adoption_usage_units,
    )
    return events


def _expected_bundle(
    *,
    repo_root: Path,
    campaign_root: Path,
    contract_path: Path,
    database: Path,
    runtime_packet_root: Path,
    baseline_usage_units_per_accepted_artifact: float,
    terminal_adoption_usage_units: float,
    terminal_adoption_review_seconds: float,
    limitations: Sequence[str],
) -> dict[str, Any]:
    root = campaign_root.resolve(strict=True)
    database_path = database.resolve(strict=True)
    packet_root = runtime_packet_root.resolve(strict=True)
    packet = validate_engineering_campaign_runtime_packet(
        packet_root,
        campaign_root=root,
        contract_path=contract_path,
        database=database_path,
    )
    if packet["decision"] != "ADOPT":
        raise EngineeringCampaignTelemetryError("runtime campaign was not independently adopted")
    if (
        baseline_usage_units_per_accepted_artifact <= 0
        or terminal_adoption_usage_units < 0
        or terminal_adoption_review_seconds < 0
    ):
        raise EngineeringCampaignTelemetryError(
            "campaign usage and timing inputs must be nonnegative"
        )
    missions, runs_by_job = _runtime_rows(database_path)
    artifacts = _validate_runtime_rows(
        campaign_root=root,
        missions=missions,
        runs_by_job=runs_by_job,
    )
    started_at = min(float(row["created_at"]) for row in missions)
    first_request_at = min(float(row["request_started_at"]) for row in missions)
    ended_at = max(float(row["updated_at"]) for row in missions)
    if not started_at <= first_request_at <= ended_at:
        raise EngineeringCampaignTelemetryError("runtime campaign timestamps are contradictory")
    source_document = _read_json(root / "engineering_campaign_source.json")
    source = {
        "schema_version": "maskfactory.campaign-telemetry-source.v1",
        "campaign_id": packet["campaign_id"],
        "campaign_kind": "engineering",
        "campaign_payload_sha256": packet["campaign_binding"]["self_sha256"],
        "source_commit_sha256": source_document["source_sha256"],
        "started_at": _iso_timestamp(started_at),
        "ended_at": _iso_timestamp(ended_at),
        "baseline_usage_units_per_accepted_artifact": (baseline_usage_units_per_accepted_artifact),
        "limitations": list(limitations),
    }
    events = _build_events(
        campaign_id=packet["campaign_id"],
        missions=missions,
        runs_by_job=runs_by_job,
        startup_seconds=first_request_at - started_at,
        inference_seconds=ended_at - first_request_at,
        terminal_adoption_usage_units=terminal_adoption_usage_units,
        terminal_adoption_review_seconds=terminal_adoption_review_seconds,
    )
    telemetry = reconcile_campaign_telemetry(
        repo_root=repo_root,
        source=source,
        events=events,
    )
    slo = evaluate_campaign_slo(telemetry, repo_root=repo_root)
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "campaign_id": packet["campaign_id"],
        "authority_claimed": False,
        "runtime_packet": {
            "path": (packet_root / PACKET_NAME).as_posix(),
            "raw_sha256": _file_sha256(packet_root / PACKET_NAME),
            "self_sha256": packet["packet_sha256"],
        },
        "runtime_database": {
            "path": database_path.as_posix(),
            "raw_sha256": _file_sha256(database_path),
        },
        "measurement_contract": {
            "baseline_unit": "codex_campaign_intervention_per_accepted_artifact",
            "baseline_usage_units_per_accepted_artifact": (
                baseline_usage_units_per_accepted_artifact
            ),
            "terminal_adoption_usage_units": terminal_adoption_usage_units,
            "terminal_adoption_review_seconds": terminal_adoption_review_seconds,
            "startup_window": "first_runtime_row_to_first_request_intent",
            "inference_window": "first_request_intent_to_last_terminal_update",
            "idle_gpu_seconds": 0,
        },
        "artifacts": artifacts,
        "source": source,
        "events": events,
        "telemetry": telemetry,
        "slo": slo,
        "bundle_sha256": ZERO_SHA256,
    }
    bundle["bundle_sha256"] = canonical_sha256(bundle)
    return bundle


def build_engineering_campaign_telemetry_bundle(
    *,
    repo_root: Path,
    campaign_root: Path,
    contract_path: Path,
    database: Path,
    runtime_packet_root: Path,
    output_root: Path,
    baseline_usage_units_per_accepted_artifact: float,
    terminal_adoption_usage_units: float,
    terminal_adoption_review_seconds: float,
    limitations: Sequence[str],
) -> dict[str, Any]:
    """Write one immutable telemetry/SLO successor for a terminal campaign."""

    bundle = _expected_bundle(
        repo_root=repo_root,
        campaign_root=campaign_root,
        contract_path=contract_path,
        database=database,
        runtime_packet_root=runtime_packet_root,
        baseline_usage_units_per_accepted_artifact=(baseline_usage_units_per_accepted_artifact),
        terminal_adoption_usage_units=terminal_adoption_usage_units,
        terminal_adoption_review_seconds=terminal_adoption_review_seconds,
        limitations=limitations,
    )
    destination = output_root.resolve(strict=False)
    if destination.exists() or not destination.parent.is_dir():
        raise EngineeringCampaignTelemetryError(
            "output root must be an absent child of an existing directory"
        )
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent))
    try:
        payload = (
            json.dumps(
                bundle,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
            + b"\n"
        )
        with (temporary / BUNDLE_NAME).open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        validate_engineering_campaign_telemetry_bundle(
            temporary,
            repo_root=repo_root,
            campaign_root=campaign_root,
            contract_path=contract_path,
            database=database,
            runtime_packet_root=runtime_packet_root,
        )
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return bundle


def validate_engineering_campaign_telemetry_bundle(
    bundle_root: Path,
    *,
    repo_root: Path,
    campaign_root: Path,
    contract_path: Path,
    database: Path,
    runtime_packet_root: Path,
) -> dict[str, Any]:
    """Replay the telemetry bundle against exact terminal runtime bytes."""

    root = bundle_root.resolve(strict=True)
    files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if files != {BUNDLE_NAME}:
        raise EngineeringCampaignTelemetryError(
            "exactly one engineering telemetry bundle is required"
        )
    bundle = _read_json(root / BUNDLE_NAME)
    declared = bundle.get("bundle_sha256")
    zeroed = deepcopy(bundle)
    zeroed["bundle_sha256"] = ZERO_SHA256
    if not isinstance(declared, str) or canonical_sha256(zeroed) != declared:
        raise EngineeringCampaignTelemetryError("engineering telemetry bundle self hash mismatch")
    measurement = bundle.get("measurement_contract")
    if not isinstance(measurement, Mapping):
        raise EngineeringCampaignTelemetryError(
            "engineering telemetry measurement contract is missing"
        )
    expected = _expected_bundle(
        repo_root=repo_root,
        campaign_root=campaign_root,
        contract_path=contract_path,
        database=database,
        runtime_packet_root=runtime_packet_root,
        baseline_usage_units_per_accepted_artifact=measurement[
            "baseline_usage_units_per_accepted_artifact"
        ],
        terminal_adoption_usage_units=measurement["terminal_adoption_usage_units"],
        terminal_adoption_review_seconds=measurement["terminal_adoption_review_seconds"],
        limitations=bundle["source"]["limitations"],
    )
    if bundle != expected:
        raise EngineeringCampaignTelemetryError(
            "engineering telemetry bundle drifted from runtime evidence"
        )
    validate_campaign_telemetry_replay(
        bundle["telemetry"],
        repo_root=repo_root,
        source=bundle["source"],
        events=bundle["events"],
    )
    validate_campaign_slo_replay(
        bundle["slo"],
        telemetry=bundle["telemetry"],
        repo_root=repo_root,
    )
    return bundle


__all__ = [
    "BUNDLE_NAME",
    "EngineeringCampaignTelemetryError",
    "build_engineering_campaign_telemetry_bundle",
    "validate_engineering_campaign_telemetry_bundle",
]
