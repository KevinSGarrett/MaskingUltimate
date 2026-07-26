"""One immutable adoption boundary for a real 25-mission runtime campaign."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from .continuous_contract import canonical_sha256
from .engineering_campaign_runtime import (
    BINDING_NAME,
    CAMPAIGN_SIZE,
    TERMINAL_NAME,
    validate_engineering_campaign_runtime_terminal,
)

SCHEMA_VERSION = "maskfactory.engineering_campaign_runtime_packet.v1"
PACKET_NAME = "engineering_campaign_runtime_packet.json"
ZERO_SHA256 = "0" * 64
DECISIONS = frozenset({"ADOPT", "PARTIALLY_ADOPT", "REJECT"})
AUTHORITY = {
    "apply_patch": False,
    "credentials": False,
    "final_adoption": False,
    "git": False,
    "github": False,
    "infrastructure": False,
    "runpod": False,
    "tracker": False,
}


class EngineeringCampaignRuntimePacketError(RuntimeError):
    """The real campaign evidence is incomplete, contradictory, or unsafe."""


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
        raise EngineeringCampaignRuntimePacketError(
            f"campaign evidence is unreadable: {path.name}"
        ) from exc
    if not isinstance(value, dict):
        raise EngineeringCampaignRuntimePacketError(
            f"campaign evidence is not an object: {path.name}"
        )
    return value


def _text(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > 4096
    ):
        raise EngineeringCampaignRuntimePacketError(f"{field} is invalid")
    return value.strip()


def _strings(values: Sequence[str], *, field: str) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise EngineeringCampaignRuntimePacketError(f"{field} must be a sequence")
    normalized = [_text(value, field=field) for value in values]
    if len(normalized) != len(set(normalized)):
        raise EngineeringCampaignRuntimePacketError(f"{field} must be unique")
    return normalized


def _seal(value: Mapping[str, Any]) -> dict[str, Any]:
    sealed = deepcopy(dict(value))
    sealed["packet_sha256"] = ZERO_SHA256
    sealed["packet_sha256"] = canonical_sha256(sealed)
    return sealed


def _verify_embedded_self_hash(
    value: Mapping[str, Any],
    *,
    field: str,
) -> str:
    declared = value.get(field)
    if not isinstance(declared, str) or len(declared) != 64:
        raise EngineeringCampaignRuntimePacketError(
            f"{field} is missing or invalid"
        )
    zeroed = deepcopy(dict(value))
    zeroed[field] = ZERO_SHA256
    if canonical_sha256(zeroed) != declared:
        raise EngineeringCampaignRuntimePacketError(f"{field} mismatch")
    return declared


def _runtime_counts(database: Path) -> dict[str, int]:
    uri = f"{database.resolve(strict=True).as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        mission = connection.execute(
            """
            SELECT
                COUNT(*),
                SUM(state = 'completed'),
                COUNT(DISTINCT job_id),
                COUNT(DISTINCT request_sha256),
                SUM(LENGTH(release_sha256) = 64)
            FROM steward_missions
            """
        ).fetchone()
        runs = connection.execute(
            """
            SELECT
                COUNT(*),
                COUNT(DISTINCT job_id),
                COUNT(DISTINCT request_sha256),
                COUNT(DISTINCT response_sha256),
                COUNT(DISTINCT proposal_sha256),
                COUNT(DISTINCT proposal_canonical_sha256)
            FROM steward_runs
            """
        ).fetchone()
        replay = connection.execute(
            """
            SELECT MIN(run_count), MAX(run_count)
            FROM (
                SELECT COUNT(*) AS run_count
                FROM steward_runs
                GROUP BY job_id
            )
            """
        ).fetchone()
        mismatch = connection.execute(
            """
            SELECT COUNT(*)
            FROM steward_runs AS runs
            JOIN steward_missions AS missions
              ON runs.session_id = missions.session_id
             AND runs.job_id = missions.job_id
            WHERE runs.request_sha256 != missions.request_sha256
            """
        ).fetchone()
    finally:
        connection.close()
    if mission is None or runs is None or replay is None or mismatch is None:
        raise EngineeringCampaignRuntimePacketError("runtime ledger is incomplete")
    return {
        "mission_count": int(mission[0]),
        "completed_mission_count": int(mission[1] or 0),
        "unique_job_count": int(mission[2]),
        "unique_request_count": int(mission[3]),
        "released_mission_count": int(mission[4] or 0),
        "real_request_count": int(runs[0]),
        "run_job_count": int(runs[1]),
        "run_request_count": int(runs[2]),
        "unique_response_count": int(runs[3]),
        "accepted_artifact_count": int(runs[1]),
        "unique_proposal_file_count": int(runs[4]),
        "unique_proposal_canonical_count": int(runs[5]),
        "minimum_runs_per_mission": int(replay[0] or 0),
        "maximum_runs_per_mission": int(replay[1] or 0),
        "request_binding_mismatch_count": int(mismatch[0]),
    }


def _validate_counts(counts: Mapping[str, int]) -> None:
    expected = {
        "mission_count": CAMPAIGN_SIZE,
        "completed_mission_count": CAMPAIGN_SIZE,
        "unique_job_count": CAMPAIGN_SIZE,
        "unique_request_count": CAMPAIGN_SIZE,
        "released_mission_count": CAMPAIGN_SIZE,
        "real_request_count": CAMPAIGN_SIZE * 2,
        "run_job_count": CAMPAIGN_SIZE,
        "run_request_count": CAMPAIGN_SIZE,
        "accepted_artifact_count": CAMPAIGN_SIZE,
        "minimum_runs_per_mission": 2,
        "maximum_runs_per_mission": 2,
        "request_binding_mismatch_count": 0,
    }
    observed = dict(counts)
    unique_responses = observed.pop("unique_response_count", 0)
    unique_files = observed.pop("unique_proposal_file_count", 0)
    unique_canonical = observed.pop("unique_proposal_canonical_count", 0)
    if (
        observed != expected
        or not 1 <= unique_responses <= CAMPAIGN_SIZE * 2
        or not 1 <= unique_files <= CAMPAIGN_SIZE
        or not 1 <= unique_canonical <= CAMPAIGN_SIZE
    ):
        raise EngineeringCampaignRuntimePacketError(
            "runtime ledger does not prove the exact 25-mission replay contract"
        )


def _validate_grammar(
    grammar: Mapping[str, Any],
    *,
    campaign_id: str,
) -> str:
    if (
        grammar.get("status") != "PASS"
        or grammar.get("campaign_id") != campaign_id
        or grammar.get("request_count") != CAMPAIGN_SIZE
        or grammar.get("all_schemas_unmodified_from_request_json") is not True
        or grammar.get("cuda_visible_devices") != ""
        or not isinstance(grammar.get("results"), list)
        or len(grammar["results"]) != CAMPAIGN_SIZE
        or any(row.get("status") != "PASS" for row in grammar["results"])
    ):
        raise EngineeringCampaignRuntimePacketError(
            "CPU grammar preflight does not cover all 25 exact requests"
        )
    declared = grammar.get("canonical_sha256")
    if not isinstance(declared, str) or len(declared) != 64:
        raise EngineeringCampaignRuntimePacketError(
            "CPU grammar preflight canonical digest is invalid"
        )
    return declared


def _validate_release(
    release: Mapping[str, Any],
    *,
    campaign_id: str,
    binding_sha256: str,
) -> str:
    declared = _verify_embedded_self_hash(release, field="self_sha256")
    if (
        release.get("job_id") != campaign_id
        or release.get("payload_sha256") != binding_sha256
        or release.get("lease_state") != "completed"
        or release.get("disposition") != "completed"
        or release.get("child_returncode") != 0
    ):
        raise EngineeringCampaignRuntimePacketError(
            "shared-GPU lease release does not prove successful handoff"
        )
    return declared


def _validate_handoff(handoff: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "captured_at",
        "pod_id",
        "volume_id",
        "gpu_name",
        "gpu_memory_used_mib",
        "gpu_utilization_percent",
        "compute_app_count",
        "ports_open",
        "active_lease_session_id",
        "active_lease_job_id",
        "campaign_lease_active",
        "foreign_lease_active",
        "lease_queue_count",
        "owned_process_count",
        "owner_token_present",
        "authority_claimed",
    }
    if set(handoff) != required:
        raise EngineeringCampaignRuntimePacketError(
            "resource handoff field set mismatch"
        )
    ports = handoff.get("ports_open")
    if (
        not isinstance(ports, dict)
        or set(ports) != {"8188", "18008", "18125"}
        or any(not isinstance(value, bool) for value in ports.values())
        or handoff.get("gpu_name") != "NVIDIA RTX 6000 Ada Generation"
        or not isinstance(handoff.get("gpu_memory_used_mib"), int)
        or handoff.get("gpu_memory_used_mib") < 0
        or not isinstance(handoff.get("gpu_utilization_percent"), int)
        or handoff.get("gpu_utilization_percent") < 0
        or not isinstance(handoff.get("compute_app_count"), int)
        or handoff.get("compute_app_count") < 0
        or handoff.get("campaign_lease_active") is not False
        or not isinstance(handoff.get("foreign_lease_active"), bool)
        or not isinstance(handoff.get("lease_queue_count"), int)
        or handoff.get("lease_queue_count") < 0
        or handoff.get("owned_process_count") != 0
        or handoff.get("owner_token_present") is not False
        or handoff.get("authority_claimed") is not False
    ):
        raise EngineeringCampaignRuntimePacketError(
            "resource handoff is not clean"
        )
    foreign_busy = (
        handoff["compute_app_count"] > 0
        or any(ports.values())
        or handoff["gpu_memory_used_mib"] > 4
        or handoff["gpu_utilization_percent"] > 0
    )
    if foreign_busy and (
        handoff["foreign_lease_active"] is not True
        or not handoff["active_lease_session_id"]
        or not handoff["active_lease_job_id"]
    ):
        raise EngineeringCampaignRuntimePacketError(
            "post-release GPU occupancy lacks a foreign lease"
        )
    return deepcopy(dict(handoff))


def _tracker_proposals(
    values: Sequence[Mapping[str, Any]],
    *,
    decision: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in values:
        if set(row) != {"item_id", "status", "percent", "evidence"}:
            raise EngineeringCampaignRuntimePacketError(
                "tracker proposal field set mismatch"
            )
        normalized = {
            "item_id": _text(row["item_id"], field="tracker item"),
            "status": _text(row["status"], field="tracker status"),
            "percent": row["percent"],
            "evidence": _text(row["evidence"], field="tracker evidence"),
        }
        if (
            not isinstance(normalized["percent"], int)
            or isinstance(normalized["percent"], bool)
            or not 0 <= normalized["percent"] <= 100
            or (
                normalized["status"] == "complete"
                and (decision != "ADOPT" or normalized["percent"] != 100)
            )
        ):
            raise EngineeringCampaignRuntimePacketError(
                "tracker proposal overclaims the campaign decision"
            )
        result.append(normalized)
    if len({row["item_id"] for row in result}) != len(result):
        raise EngineeringCampaignRuntimePacketError(
            "tracker proposal identities must be unique"
        )
    return sorted(result, key=lambda row: row["item_id"])


def _expected_packet(
    *,
    campaign_root: Path,
    contract_path: Path,
    database: Path,
    handoff: Mapping[str, Any],
    decision: str,
    decision_reason: str,
    limitations: Sequence[str],
    tracker_proposals: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    root = campaign_root.resolve(strict=True)
    terminal_path = root / TERMINAL_NAME
    binding_path = root / BINDING_NAME
    grammar_path = root / "cpu_grammar_preflight_25.json"
    release_path = root / "local_gpu_lease_release.json"
    database_path = database.resolve(strict=True)
    terminal = validate_engineering_campaign_runtime_terminal(
        terminal_path,
        campaign_root=root,
        contract_path=contract_path,
        database=database_path,
    )
    if decision not in DECISIONS:
        raise EngineeringCampaignRuntimePacketError("decision is unsupported")
    if decision == "ADOPT" and terminal["outcome"] != "SUCCESS":
        raise EngineeringCampaignRuntimePacketError(
            "ADOPT overclaims a non-successful campaign"
        )
    normalized_limitations = _strings(limitations, field="limitations")
    if decision != "ADOPT" and not normalized_limitations:
        raise EngineeringCampaignRuntimePacketError(
            "non-ADOPT decision requires a limitation"
        )
    grammar = _read_json(grammar_path)
    release = _read_json(release_path)
    counts = _runtime_counts(database_path)
    _validate_counts(counts)
    grammar_sha256 = _validate_grammar(
        grammar,
        campaign_id=terminal["campaign_id"],
    )
    release_sha256 = _validate_release(
        release,
        campaign_id=terminal["campaign_id"],
        binding_sha256=terminal["binding_sha256"],
    )
    mission_outcomes = deepcopy(terminal["mission_outcomes"])
    if (
        len(mission_outcomes) != CAMPAIGN_SIZE
        or len({row["job_id"] for row in mission_outcomes}) != CAMPAIGN_SIZE
        or len({row["request_sha256"] for row in mission_outcomes})
        != CAMPAIGN_SIZE
        or any(
            row["state"] != "completed" or row["handoff_ready"] is not True
            for row in mission_outcomes
        )
    ):
        raise EngineeringCampaignRuntimePacketError(
            "terminal does not bind 25 unique successful mission outcomes"
        )
    return _seal(
        {
            "schema_version": SCHEMA_VERSION,
            "campaign_id": terminal["campaign_id"],
            "session_id": _read_json(binding_path)["session_id"],
            "decision": decision,
            "decision_reason": _text(decision_reason, field="decision reason"),
            "limitations": normalized_limitations,
            "authority": deepcopy(AUTHORITY),
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
                "service_generation_count": terminal[
                    "service_generation_count"
                ],
            },
            "runtime_database": {
                "path": database_path.name,
                "raw_sha256": _file_sha256(database_path),
                "counts": counts,
            },
            "grammar_preflight": {
                "path": grammar_path.name,
                "raw_sha256": _file_sha256(grammar_path),
                "canonical_sha256": grammar_sha256,
            },
            "guard_execution": {
                "launcher_path": "run_guarded_campaign_once.sh",
                "launcher_raw_sha256": _file_sha256(
                    root / "run_guarded_campaign_once.sh"
                ),
                "stdout_path": "guarded_campaign_stdout.log",
                "stdout_raw_sha256": _file_sha256(
                    root / "guarded_campaign_stdout.log"
                ),
            },
            "lease_release": {
                "path": release_path.name,
                "raw_sha256": _file_sha256(release_path),
                "self_sha256": release_sha256,
                "request_id": release["request_id"],
            },
            "resource_handoff": _validate_handoff(handoff),
            "mission_outcomes": mission_outcomes,
            "tracker_proposals": _tracker_proposals(
                tracker_proposals,
                decision=decision,
            ),
            "packet_sha256": ZERO_SHA256,
        }
    )


def build_engineering_campaign_runtime_packet(
    *,
    campaign_root: Path,
    contract_path: Path,
    database: Path,
    output_root: Path,
    handoff: Mapping[str, Any],
    decision: str,
    decision_reason: str,
    limitations: Sequence[str],
    tracker_proposals: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build one packet binding all 25 real outcomes and clean GPU release."""

    packet = _expected_packet(
        campaign_root=campaign_root,
        contract_path=contract_path,
        database=database,
        handoff=handoff,
        decision=decision,
        decision_reason=decision_reason,
        limitations=limitations,
        tracker_proposals=tracker_proposals,
    )
    destination = output_root.resolve(strict=False)
    if destination.exists() or not destination.parent.is_dir():
        raise EngineeringCampaignRuntimePacketError(
            "output root must be an absent child of an existing directory"
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
        validate_engineering_campaign_runtime_packet(
            temporary,
            campaign_root=campaign_root,
            contract_path=contract_path,
            database=database,
        )
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return packet


def validate_engineering_campaign_runtime_packet(
    packet_root: Path,
    *,
    campaign_root: Path,
    contract_path: Path,
    database: Path,
) -> dict[str, Any]:
    """Replay a packet against runtime terminal, ledger, and release evidence."""

    root = packet_root.resolve(strict=True)
    files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if files != {PACKET_NAME}:
        raise EngineeringCampaignRuntimePacketError(
            "exactly one runtime campaign packet is required"
        )
    packet = _read_json(root / PACKET_NAME)
    declared = packet.get("packet_sha256")
    if not isinstance(declared, str) or len(declared) != 64:
        raise EngineeringCampaignRuntimePacketError(
            "runtime campaign packet self hash is invalid"
        )
    zeroed = deepcopy(packet)
    zeroed["packet_sha256"] = ZERO_SHA256
    if canonical_sha256(zeroed) != declared:
        raise EngineeringCampaignRuntimePacketError(
            "runtime campaign packet self hash mismatch"
        )
    expected = _expected_packet(
        campaign_root=campaign_root,
        contract_path=contract_path,
        database=database,
        handoff=packet["resource_handoff"],
        decision=packet["decision"],
        decision_reason=packet["decision_reason"],
        limitations=packet["limitations"],
        tracker_proposals=packet["tracker_proposals"],
    )
    if packet != expected:
        raise EngineeringCampaignRuntimePacketError(
            "runtime campaign packet drifted from terminal evidence"
        )
    return packet


__all__ = [
    "EngineeringCampaignRuntimePacketError",
    "PACKET_NAME",
    "build_engineering_campaign_runtime_packet",
    "validate_engineering_campaign_runtime_packet",
]
