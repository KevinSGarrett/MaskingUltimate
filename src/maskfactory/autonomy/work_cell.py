"""Durable RunPod-resident mission controller for autonomous MaskFactory batches.

The controller owns orchestration, not mask authority.  It persists an immutable
mission contract and advances records only through explicit stage receipts.  A
visual model can diagnose and request bounded repair, but it cannot author pixels,
clear hard QA, or issue a certificate.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from jsonschema import Draft202012Validator


class WorkCellError(RuntimeError):
    """The mission contract, state transition, or lease failed closed."""


STAGES = (
    "source_decode",
    "detection_ownership",
    "provider_tournament",
    "hard_qc",
    "primary_visual_review",
    "independent_visual_review",
    "repair_planning",
    "repair_execution",
    "package_freeze",
    "certification",
)
TERMINAL_STAGES = frozenset({"completed", "abstained", "quarantined", "rejected"})
TERMINAL_OUTCOMES = frozenset({"accepted", "abstained", "quarantined", "rejected"})
VISUAL_STAGES = frozenset({"primary_visual_review", "independent_visual_review"})
REQUIRED_BULK_SCOPE = frozenset(
    {
        "source_decode",
        "person_ownership",
        "mask_generation",
        "deterministic_hard_qa",
        "strict_visual_review",
        "bounded_repair",
        "mask_correction",
        "package_freeze",
        "certification",
        "milestone_reporting",
    }
)
REQUIRED_TERMINAL_OUTCOMES = frozenset({"accepted", "abstained", "quarantined", "rejected"})

PASS_NEXT = {
    "source_decode": "detection_ownership",
    "detection_ownership": "provider_tournament",
    "provider_tournament": "hard_qc",
    "hard_qc": "primary_visual_review",
    "primary_visual_review": "independent_visual_review",
    "independent_visual_review": "package_freeze",
    "repair_planning": "repair_execution",
    "repair_execution": "hard_qc",
    "package_freeze": "certification",
    "certification": "completed",
}

ALLOWED_ACTORS = {
    "source_decode": frozenset({"deterministic_qa"}),
    "detection_ownership": frozenset({"deterministic_qa", "segmentation_provider"}),
    "provider_tournament": frozenset({"segmentation_provider"}),
    "hard_qc": frozenset({"deterministic_qa"}),
    "primary_visual_review": frozenset({"visual_critic"}),
    "independent_visual_review": frozenset({"visual_critic"}),
    "repair_planning": frozenset({"visual_critic", "deterministic_qa"}),
    "repair_execution": frozenset({"segmentation_provider"}),
    "package_freeze": frozenset({"deterministic_qa"}),
    "certification": frozenset({"certificate_service"}),
}


def canonical_sha256(value: Mapping[str, Any]) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _require_sha(detail: Mapping[str, Any], field: str) -> str:
    value = detail.get(field)
    if not isinstance(value, str) or len(value) != 64:
        raise WorkCellError(f"stage detail {field} sha256 required")
    return value


def _require_int(detail: Mapping[str, Any], field: str, *, minimum: int = 0) -> int:
    value = detail.get(field)
    if not isinstance(value, int) or value < minimum:
        raise WorkCellError(f"stage detail {field} integer required")
    return value


def _require_enum(detail: Mapping[str, Any], field: str, allowed: set[str]) -> str:
    value = detail.get(field)
    if not isinstance(value, str) or value not in allowed:
        raise WorkCellError(f"stage detail {field} enum invalid")
    return value


def seal_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = canonical_sha256(result)
    return result


def validate_mission_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    manifest = dict(value)
    schema_path = Path(__file__).parents[1] / "schemas" / "runpod_autonomous_mission.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    problems = sorted(
        Draft202012Validator(schema).iter_errors(manifest), key=lambda item: list(item.path)
    )
    if problems:
        pointer = "/".join(str(part) for part in problems[0].path)
        raise WorkCellError(
            f"mission schema invalid at {pointer or '<root>'}: {problems[0].message}"
        )
    expected = canonical_sha256({k: v for k, v in manifest.items() if k != "manifest_sha256"})
    if manifest["manifest_sha256"] != expected:
        raise WorkCellError("mission manifest seal mismatch")

    providers = manifest["provider_bindings"]
    if len({row["family"] for row in providers}) < 2:
        raise WorkCellError("provider tournament requires at least two distinct families")

    roles = manifest["role_bindings"]
    for name, role in roles.items():
        qualified_fields = (
            role["model_id"],
            role["family"],
            role["revision_sha256"],
            role["role_certificate_sha256"],
        )
        if role["status"] == "qualified":
            if not all(qualified_fields) or role["revoked"]:
                raise WorkCellError(f"qualified role binding invalid: {name}")
        elif any(value is not None for value in qualified_fields) or role["revoked"]:
            raise WorkCellError(f"unavailable role must not retain authority fields: {name}")

    if manifest["authority_ceiling"] != "machine_verified_candidate":
        primary = roles["primary_visual_critic"]
        juror = roles["independent_juror"]
        if primary["status"] != "qualified" or juror["status"] != "qualified":
            raise WorkCellError("certified authority requires two qualified visual roles")
        if primary["family"] == juror["family"]:
            raise WorkCellError("visual quorum requires independent model families")
    bulk_policy = manifest["bulk_policy"]
    missing_scope = sorted(REQUIRED_BULK_SCOPE - set(bulk_policy["workload_scope"]))
    if missing_scope:
        raise WorkCellError(f"bulk mission scope incomplete: {missing_scope}")
    if set(bulk_policy["terminal_outcomes"]) != REQUIRED_TERMINAL_OUTCOMES:
        raise WorkCellError("bulk mission terminal outcomes incomplete")
    if bulk_policy["material_incident_threshold_fraction"] > 0.25:
        raise WorkCellError("material incident threshold too loose for autonomous batch work")
    return manifest


class AutonomousWorkCell:
    """SQLite-backed mission and per-record state machine."""

    def __init__(self, root: Path, *, clock: Callable[[], float] = time.time) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "work_cell.sqlite"
        self._clock = clock
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS missions (
                    mission_id TEXT PRIMARY KEY,
                    manifest_sha256 TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    expected_records INTEGER NOT NULL CHECK(expected_records > 0),
                    state TEXT NOT NULL CHECK(state IN ('admitted','running','complete','failed')),
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS records (
                    mission_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    input_payload_sha256 TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    outcome TEXT,
                    repair_attempt_count INTEGER NOT NULL DEFAULT 0,
                    processing_attempt_count INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_token TEXT,
                    lease_expires_at REAL,
                    last_error TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(mission_id, record_id),
                    FOREIGN KEY(mission_id) REFERENCES missions(mission_id)
                );
                CREATE TABLE IF NOT EXISTS stage_receipts (
                    mission_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    repair_cycle INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    actor_kind TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at REAL NOT NULL,
                    PRIMARY KEY(mission_id, record_id, stage, repair_cycle),
                    FOREIGN KEY(mission_id, record_id) REFERENCES records(mission_id, record_id)
                );
                CREATE TABLE IF NOT EXISTS mission_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    mission_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    recorded_at REAL NOT NULL,
                    FOREIGN KEY(mission_id) REFERENCES missions(mission_id)
                );
                """
            )

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        mission_id: str,
        event: str,
        detail: Mapping[str, Any],
        now: float,
    ) -> None:
        connection.execute(
            "INSERT INTO mission_events(mission_id,event,detail_json,recorded_at) VALUES(?,?,?,?)",
            (mission_id, event, json.dumps(dict(detail), sort_keys=True), now),
        )

    def admit(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        document = validate_mission_manifest(manifest)
        mission_id = str(document["mission_id"])
        mission_root = self.root / "missions" / mission_id
        mission_root.mkdir(parents=True, exist_ok=True)
        manifest_path = mission_root / "manifest.json"
        encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
        now = self._clock()
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT manifest_sha256 FROM missions WHERE mission_id=?", (mission_id,)
            ).fetchone()
            if existing:
                if existing["manifest_sha256"] != document["manifest_sha256"]:
                    raise WorkCellError("mission id already admitted with different bytes")
                return {"mission_id": mission_id, "admitted": False, "idempotent": True}
            if manifest_path.exists():
                raise WorkCellError("unledgered mission manifest already exists")
            temporary = manifest_path.with_suffix(".json.tmp")
            temporary.write_text(encoded, encoding="utf-8")
            temporary.replace(manifest_path)
            connection.execute(
                "INSERT INTO missions(mission_id,manifest_sha256,manifest_json,expected_records,"
                "state,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (
                    mission_id,
                    document["manifest_sha256"],
                    json.dumps(document, sort_keys=True),
                    int(document["input"]["record_count"]),
                    "admitted",
                    now,
                    now,
                ),
            )
            self._event(connection, mission_id, "admitted", {}, now)
        return {"mission_id": mission_id, "admitted": True, "idempotent": False}

    def seed_records(self, mission_id: str, records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
        if not records:
            raise WorkCellError("empty record seed")
        now = self._clock()
        inserted = 0
        retained = 0
        with self._transaction() as connection:
            mission = connection.execute(
                "SELECT expected_records,state FROM missions WHERE mission_id=?", (mission_id,)
            ).fetchone()
            if mission is None:
                raise WorkCellError("admitted mission required")
            for item in records:
                record_id = str(item.get("record_id", ""))
                source_sha256 = str(item.get("source_sha256", ""))
                payload_sha256 = str(item.get("input_payload_sha256", ""))
                if not record_id or any(
                    len(value) != 64 for value in (source_sha256, payload_sha256)
                ):
                    raise WorkCellError("record identity and hashes required")
                existing = connection.execute(
                    "SELECT source_sha256,input_payload_sha256 FROM records "
                    "WHERE mission_id=? AND record_id=?",
                    (mission_id, record_id),
                ).fetchone()
                if existing:
                    if tuple(existing) != (source_sha256, payload_sha256):
                        raise WorkCellError("record seed drift")
                    retained += 1
                    continue
                connection.execute(
                    "INSERT INTO records(mission_id,record_id,source_sha256,input_payload_sha256,"
                    "stage,updated_at) VALUES(?,?,?,?,?,?)",
                    (mission_id, record_id, source_sha256, payload_sha256, "source_decode", now),
                )
                inserted += 1
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM records WHERE mission_id=?", (mission_id,)
                ).fetchone()[0]
            )
            expected = int(mission["expected_records"])
            if total > expected:
                raise WorkCellError("record seed exceeds manifest count")
            state = "running" if total == expected else "admitted"
            connection.execute(
                "UPDATE missions SET state=?,updated_at=? WHERE mission_id=?",
                (state, now, mission_id),
            )
            self._event(
                connection,
                mission_id,
                "records_seeded",
                {"inserted": inserted, "retained": retained, "total": total},
                now,
            )
        return {"inserted": inserted, "retained": retained, "total": total}

    def recover_expired(self, mission_id: str) -> dict[str, int]:
        now = self._clock()
        requeued = 0
        abstained = 0
        with self._transaction() as connection:
            mission = self._mission(connection, mission_id)
            max_attempts = int(mission["execution"]["max_record_attempts"])
            rows = connection.execute(
                "SELECT record_id,processing_attempt_count FROM records WHERE mission_id=? "
                "AND lease_token IS NOT NULL AND lease_expires_at<=?",
                (mission_id, now),
            ).fetchall()
            for row in rows:
                if int(row["processing_attempt_count"]) >= max_attempts:
                    connection.execute(
                        "UPDATE records SET stage='abstained',outcome='abstained',lease_owner=NULL,"
                        "lease_token=NULL,lease_expires_at=NULL,last_error='lease_retry_cap_exhausted',"
                        "updated_at=? WHERE mission_id=? AND record_id=?",
                        (now, mission_id, row["record_id"]),
                    )
                    abstained += 1
                else:
                    connection.execute(
                        "UPDATE records SET lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,"
                        "last_error='expired_lease_requeued',updated_at=? "
                        "WHERE mission_id=? AND record_id=?",
                        (now, mission_id, row["record_id"]),
                    )
                    requeued += 1
            if rows:
                self._event(
                    connection,
                    mission_id,
                    "expired_leases_recovered",
                    {"requeued": requeued, "abstained": abstained},
                    now,
                )
            self._refresh_mission_state(connection, mission_id, now)
        return {"requeued": requeued, "abstained": abstained}

    def claim(self, mission_id: str, *, owner: str) -> dict[str, Any] | None:
        if not owner:
            raise ValueError("owner required")
        self.recover_expired(mission_id)
        now = self._clock()
        with self._transaction() as connection:
            manifest = self._mission(connection, mission_id)
            if self._mission_state(connection, mission_id) != "running":
                return None
            row = connection.execute(
                "SELECT * FROM records WHERE mission_id=? AND stage NOT IN "
                "('completed','abstained','quarantined','rejected') AND lease_token IS NULL "
                "ORDER BY updated_at,record_id LIMIT 1",
                (mission_id,),
            ).fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            expires = now + int(manifest["execution"]["lease_seconds"])
            connection.execute(
                "UPDATE records SET lease_owner=?,lease_token=?,lease_expires_at=?,"
                "processing_attempt_count=processing_attempt_count+1,updated_at=? "
                "WHERE mission_id=? AND record_id=?",
                (owner, token, expires, now, mission_id, row["record_id"]),
            )
            return {
                "mission_id": mission_id,
                "record_id": row["record_id"],
                "source_sha256": row["source_sha256"],
                "input_payload_sha256": row["input_payload_sha256"],
                "stage": row["stage"],
                "repair_attempt_count": int(row["repair_attempt_count"]),
                "lease_token": token,
                "lease_expires_at": expires,
            }

    def heartbeat(self, mission_id: str, record_id: str, lease_token: str) -> float:
        now = self._clock()
        with self._transaction() as connection:
            manifest = self._mission(connection, mission_id)
            self._owned_record(connection, mission_id, record_id, lease_token, now)
            expires = now + int(manifest["execution"]["lease_seconds"])
            connection.execute(
                "UPDATE records SET lease_expires_at=?,updated_at=? "
                "WHERE mission_id=? AND record_id=?",
                (expires, now, mission_id, record_id),
            )
        return expires

    def release(
        self,
        mission_id: str,
        record_id: str,
        lease_token: str,
        *,
        reason: str,
    ) -> None:
        """Release one owned lease without advancing or weakening the record stage."""

        if not reason.strip():
            raise ValueError("release reason required")
        now = self._clock()
        with self._transaction() as connection:
            self._owned_record(connection, mission_id, record_id, lease_token, now)
            connection.execute(
                "UPDATE records SET lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,"
                "last_error=?,updated_at=? WHERE mission_id=? AND record_id=?",
                (reason, now, mission_id, record_id),
            )
            self._event(
                connection,
                mission_id,
                "lease_released",
                {"record_id": record_id, "reason": reason},
                now,
            )

    def terminalize_system_failure(
        self,
        mission_id: str,
        record_id: str,
        lease_token: str,
        *,
        reason: str,
        evidence_sha256: str,
    ) -> dict[str, Any]:
        """Abstain one record for a typed executor failure without forging a stage receipt."""

        if not reason.strip() or len(evidence_sha256) != 64:
            raise WorkCellError("typed failure reason and evidence hash required")
        now = self._clock()
        with self._transaction() as connection:
            self._mission(connection, mission_id)
            self._owned_record(connection, mission_id, record_id, lease_token, now)
            terminal_before = self._terminal_count(connection, mission_id)
            connection.execute(
                "UPDATE records SET stage='abstained',outcome='abstained',lease_owner=NULL,"
                "lease_token=NULL,lease_expires_at=NULL,last_error=?,updated_at=? "
                "WHERE mission_id=? AND record_id=?",
                (reason, now, mission_id, record_id),
            )
            manifest = self._mission(connection, mission_id)
            terminal_after = self._terminal_count(connection, mission_id)
            interval = int(manifest["execution"]["milestone_records"])
            for boundary in range(
                ((terminal_before // interval) + 1) * interval,
                terminal_after + 1,
                interval,
            ):
                self._event(
                    connection,
                    mission_id,
                    "terminal_record_milestone",
                    {"terminal_record_count": boundary},
                    now,
                )
            self._event(
                connection,
                mission_id,
                "system_failure_abstention",
                {
                    "record_id": record_id,
                    "reason": reason,
                    "evidence_sha256": evidence_sha256,
                },
                now,
            )
            self._refresh_mission_state(connection, mission_id, now)
        return {"record_id": record_id, "stage": "abstained", "outcome": "abstained"}

    def apply_result(
        self,
        mission_id: str,
        record_id: str,
        lease_token: str,
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = dict(result)
        required = {"stage", "status", "actor_kind", "evidence_sha256"}
        if set(payload) - (required | {"detail"}) or not required <= set(payload):
            raise WorkCellError("stage result fields invalid")
        stage = str(payload["stage"])
        status = str(payload["status"])
        actor = str(payload["actor_kind"])
        evidence_sha = str(payload["evidence_sha256"])
        if stage not in STAGES or status not in {
            "pass",
            "repairable",
            "abstain",
            "quarantine",
            "reject",
        }:
            raise WorkCellError("stage result enum invalid")
        if actor not in ALLOWED_ACTORS[stage]:
            raise WorkCellError(f"actor {actor} cannot execute {stage}")
        if len(evidence_sha) != 64:
            raise WorkCellError("stage evidence hash invalid")
        now = self._clock()
        with self._transaction() as connection:
            manifest = self._mission(connection, mission_id)
            row = self._owned_record(connection, mission_id, record_id, lease_token, now)
            if row["stage"] != stage:
                raise WorkCellError("stage result does not match claimed stage")
            cycle = int(row["repair_attempt_count"])
            payload_sha = canonical_sha256(payload)
            existing = connection.execute(
                "SELECT payload_sha256 FROM stage_receipts WHERE mission_id=? AND record_id=? "
                "AND stage=? AND repair_cycle=?",
                (mission_id, record_id, stage, cycle),
            ).fetchone()
            if existing:
                if existing["payload_sha256"] != payload_sha:
                    raise WorkCellError("stage receipt idempotency conflict")
                return {
                    "record_id": record_id,
                    "stage": row["stage"],
                    "outcome": row["outcome"],
                    "idempotent": True,
                }

            self._validate_authority_for_result(manifest, stage, status, actor)
            self._validate_stage_detail(manifest, stage, status, payload.get("detail"))
            next_stage, outcome, next_cycle = self._transition(manifest, stage, status, cycle)
            connection.execute(
                "INSERT INTO stage_receipts(mission_id,record_id,stage,repair_cycle,status,"
                "actor_kind,evidence_sha256,payload_sha256,payload_json,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    mission_id,
                    record_id,
                    stage,
                    cycle,
                    status,
                    actor,
                    evidence_sha,
                    payload_sha,
                    json.dumps(payload, sort_keys=True),
                    now,
                ),
            )
            terminal_before = self._terminal_count(connection, mission_id)
            connection.execute(
                "UPDATE records SET stage=?,outcome=?,repair_attempt_count=?,lease_owner=NULL,"
                "lease_token=NULL,lease_expires_at=NULL,last_error=NULL,updated_at=? "
                "WHERE mission_id=? AND record_id=?",
                (next_stage, outcome, next_cycle, now, mission_id, record_id),
            )
            terminal_after = self._terminal_count(connection, mission_id)
            interval = int(manifest["execution"]["milestone_records"])
            for boundary in range(
                ((terminal_before // interval) + 1) * interval,
                terminal_after + 1,
                interval,
            ):
                self._event(
                    connection,
                    mission_id,
                    "terminal_record_milestone",
                    {"terminal_record_count": boundary},
                    now,
                )
            self._event(
                connection,
                mission_id,
                "stage_applied",
                {"record_id": record_id, "stage": stage, "status": status, "next": next_stage},
                now,
            )
            self._refresh_mission_state(connection, mission_id, now)
        return {
            "record_id": record_id,
            "stage": next_stage,
            "outcome": outcome,
            "repair_attempt_count": next_cycle,
            "idempotent": False,
        }

    @staticmethod
    def _validate_authority_for_result(
        manifest: Mapping[str, Any], stage: str, status: str, actor: str
    ) -> None:
        if stage in VISUAL_STAGES and status == "pass":
            role_name = (
                "primary_visual_critic" if stage == "primary_visual_review" else "independent_juror"
            )
            role = manifest["role_bindings"][role_name]
            if role["status"] != "qualified" or role["revoked"]:
                raise WorkCellError(f"unqualified visual role cannot pass: {role_name}")
        if actor == "visual_critic" and stage in {"repair_execution", "certification"}:
            raise WorkCellError("visual critic cannot author pixels or certificates")
        if stage == "certification" and status == "pass":
            if manifest["authority_ceiling"] == "machine_verified_candidate":
                raise WorkCellError("mission authority ceiling forbids certification")

    @staticmethod
    def _validate_stage_detail(
        manifest: Mapping[str, Any], stage: str, status: str, detail: Any
    ) -> None:
        if not isinstance(detail, dict):
            raise WorkCellError("stage detail object required")
        if stage == "source_decode":
            _require_sha(detail, "decoded_pixel_sha256")
            _require_enum(detail, "alpha_policy", {"absent", "discarded", "premultiplied"})
            _require_int(detail, "width", minimum=1)
            _require_int(detail, "height", minimum=1)
        elif stage == "detection_ownership":
            _require_sha(detail, "target_contract_sha256")
            _require_int(detail, "person_count", minimum=1)
            _require_enum(detail, "ownership_status", {"verified", "ambiguous"})
            if status == "pass" and detail["ownership_status"] != "verified":
                raise WorkCellError("ownership must be verified to pass")
        elif stage == "provider_tournament":
            _require_sha(detail, "tournament_report_sha256")
            family_count = _require_int(detail, "family_count", minimum=1)
            candidate_count = _require_int(detail, "candidate_count", minimum=1)
            if status == "pass":
                if family_count < 2 or candidate_count < 2:
                    raise WorkCellError("provider pass requires two families and candidates")
                _require_sha(detail, "winner_mask_sha256")
        elif stage == "hard_qc":
            _require_sha(detail, "qa_vector_sha256")
            hard_veto_count = _require_int(detail, "hard_veto_count", minimum=0)
            if status == "pass" and hard_veto_count != 0:
                raise WorkCellError("hard QA pass cannot retain hard vetoes")
        elif stage in VISUAL_STAGES:
            _require_sha(detail, "panel_sha256")
            _require_sha(detail, "critic_report_sha256")
            verdict = _require_enum(detail, "verdict", {"pass", "repairable", "abstain", "reject"})
            if status == "pass" and verdict != "pass":
                raise WorkCellError("visual pass requires pass verdict")
        elif stage == "repair_planning":
            _require_sha(detail, "defect_hypothesis_sha256")
            _require_sha(detail, "roi_sha256")
            _require_enum(
                detail,
                "operation",
                {
                    "box_refine",
                    "point_refine",
                    "mask_prompt_refine",
                    "roi_regenerate",
                    "component_prune",
                    "hole_fill_bounded",
                },
            )
        elif stage == "repair_execution":
            _require_sha(detail, "parent_mask_sha256")
            _require_sha(detail, "new_mask_sha256")
            changed = detail.get("changed_pixel_fraction")
            if not isinstance(changed, (int, float)) or changed < 0:
                raise WorkCellError("repair changed_pixel_fraction invalid")
            maximum = float(manifest["repair_policy"]["max_changed_pixel_fraction"])
            if changed > maximum:
                raise WorkCellError("repair changed_pixel_fraction exceeds mission policy")
        elif stage == "package_freeze":
            _require_sha(detail, "package_sha256")
            _require_int(detail, "active_label_count", minimum=1)
        elif stage == "certification":
            _require_sha(detail, "certificate_sha256")
            tier = _require_enum(
                detail,
                "authority_tier",
                {
                    "operationally_certified_artifact",
                    "autonomous_certified_gold",
                },
            )
            if status == "pass" and tier != manifest["authority_ceiling"]:
                raise WorkCellError("certificate authority tier must match mission ceiling")

    @staticmethod
    def _transition(
        manifest: Mapping[str, Any], stage: str, status: str, repair_cycle: int
    ) -> tuple[str, str | None, int]:
        if status == "pass":
            next_stage = PASS_NEXT[stage]
            return next_stage, "accepted" if next_stage == "completed" else None, repair_cycle
        if status == "repairable":
            if stage not in {
                "provider_tournament",
                "hard_qc",
                "primary_visual_review",
                "independent_visual_review",
            }:
                raise WorkCellError(f"repairable is not valid for {stage}")
            max_repairs = int(manifest["repair_policy"]["max_attempts"])
            if repair_cycle >= max_repairs:
                return "abstained", "abstained", repair_cycle
            return "repair_planning", None, repair_cycle + 1
        terminal = {
            "abstain": ("abstained", "abstained"),
            "quarantine": ("quarantined", "quarantined"),
            "reject": ("rejected", "rejected"),
        }[status]
        return terminal[0], terminal[1], repair_cycle

    def report(self, mission_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            mission_row = connection.execute(
                "SELECT * FROM missions WHERE mission_id=?", (mission_id,)
            ).fetchone()
            if mission_row is None:
                raise WorkCellError("unknown mission")
            manifest = json.loads(mission_row["manifest_json"])
            rows = connection.execute(
                "SELECT record_id,source_sha256,input_payload_sha256,stage,outcome,"
                "repair_attempt_count,processing_attempt_count,lease_owner,lease_expires_at,"
                "last_error "
                "FROM records WHERE mission_id=? ORDER BY record_id",
                (mission_id,),
            ).fetchall()
            milestones = connection.execute(
                "SELECT sequence,detail_json FROM mission_events WHERE mission_id=? "
                "AND event='terminal_record_milestone' ORDER BY sequence",
                (mission_id,),
            ).fetchall()
            receipt_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM stage_receipts WHERE mission_id=?", (mission_id,)
                ).fetchone()[0]
            )
            receipt_rows = connection.execute(
                "SELECT stage,status,COUNT(*) AS count FROM stage_receipts WHERE mission_id=? "
                "GROUP BY stage,status ORDER BY stage,status",
                (mission_id,),
            ).fetchall()
        stage_counts = Counter(str(row["stage"]) for row in rows)
        outcome_counts = Counter(str(row["outcome"]) for row in rows if row["outcome"])
        last_error_counts = Counter(str(row["last_error"]) for row in rows if row["last_error"])
        stage_status_counts = {
            f"{row['stage']}:{row['status']}": int(row["count"]) for row in receipt_rows
        }
        terminal_count = sum(stage_counts[stage] for stage in TERMINAL_STAGES)
        errors: list[str] = []
        if len(rows) > int(mission_row["expected_records"]):
            errors.append("record_count_exceeds_manifest")
        if terminal_count != sum(outcome_counts.values()):
            errors.append("terminal_outcome_count_mismatch")
        if mission_row["state"] == "complete" and terminal_count != len(rows):
            errors.append("complete_mission_has_nonterminal_records")
        material_incidents: list[dict[str, Any]] = []
        system_failure_count = sum(
            1 for row in rows if str(row["last_error"] or "").startswith("stage_executor_failure:")
        )
        material_threshold = float(manifest["bulk_policy"]["material_incident_threshold_fraction"])
        if rows and system_failure_count / len(rows) >= material_threshold:
            material_incidents.append(
                {
                    "incident_type": "stage_executor_failure_rate",
                    "count": system_failure_count,
                    "record_count": len(rows),
                    "fraction": system_failure_count / len(rows),
                    "threshold_fraction": material_threshold,
                }
            )
        canonical_state = {
            "mission": {
                "mission_id": mission_row["mission_id"],
                "manifest_sha256": mission_row["manifest_sha256"],
                "state": mission_row["state"],
            },
            "records": [dict(row) for row in rows],
            "receipt_count": receipt_count,
        }
        report: dict[str, Any] = {
            "schema_version": "maskfactory.runpod_autonomous_mission_report.v1",
            "mission_id": mission_id,
            "manifest_sha256": mission_row["manifest_sha256"],
            "mission_state": mission_row["state"],
            "record_count": len(rows),
            "terminal_record_count": terminal_count,
            "remaining_record_count": len(rows) - terminal_count,
            "stage_counts": dict(sorted(stage_counts.items())),
            "outcome_counts": dict(sorted(outcome_counts.items())),
            "stage_status_counts": stage_status_counts,
            "last_error_counts": dict(sorted(last_error_counts.items())),
            "stage_receipt_count": receipt_count,
            "repair_attempt_count": sum(int(row["repair_attempt_count"]) for row in rows),
            "bulk_policy_sha256": canonical_sha256(manifest["bulk_policy"]),
            "reporting_mode": manifest["bulk_policy"]["reporting_mode"],
            "material_incidents": material_incidents,
            "milestones": [
                {
                    "sequence": int(row["sequence"]),
                    "terminal_record_count": int(
                        json.loads(row["detail_json"])["terminal_record_count"]
                    ),
                }
                for row in milestones
            ],
            "integrity_errors": errors,
            "queue_state_sha256": canonical_sha256(canonical_state),
        }
        report["self_sha256"] = canonical_sha256(report)
        return report

    def write_report(self, mission_id: str, output_path: Path) -> dict[str, Any]:
        output_path = Path(output_path)
        if output_path.exists():
            raise WorkCellError("report already exists")
        report = self.report(mission_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(output_path)
        return report

    @staticmethod
    def _owned_record(
        connection: sqlite3.Connection,
        mission_id: str,
        record_id: str,
        lease_token: str,
        now: float,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM records WHERE mission_id=? AND record_id=?", (mission_id, record_id)
        ).fetchone()
        if row is None or row["lease_token"] != lease_token:
            raise WorkCellError("owned record lease required")
        if float(row["lease_expires_at"] or 0) <= now:
            raise WorkCellError("record lease expired")
        return row

    @staticmethod
    def _mission(connection: sqlite3.Connection, mission_id: str) -> dict[str, Any]:
        row = connection.execute(
            "SELECT manifest_json FROM missions WHERE mission_id=?", (mission_id,)
        ).fetchone()
        if row is None:
            raise WorkCellError("unknown mission")
        return json.loads(row["manifest_json"])

    @staticmethod
    def _mission_state(connection: sqlite3.Connection, mission_id: str) -> str:
        row = connection.execute(
            "SELECT state FROM missions WHERE mission_id=?", (mission_id,)
        ).fetchone()
        if row is None:
            raise WorkCellError("unknown mission")
        return str(row["state"])

    @staticmethod
    def _terminal_count(connection: sqlite3.Connection, mission_id: str) -> int:
        placeholders = ",".join("?" for _ in TERMINAL_STAGES)
        return int(
            connection.execute(
                f"SELECT COUNT(*) FROM records WHERE mission_id=? AND stage IN ({placeholders})",
                (mission_id, *sorted(TERMINAL_STAGES)),
            ).fetchone()[0]
        )

    @staticmethod
    def _refresh_mission_state(connection: sqlite3.Connection, mission_id: str, now: float) -> None:
        counts = connection.execute(
            "SELECT COUNT(*) AS total,SUM(CASE WHEN stage IN "
            "('completed','abstained','quarantined','rejected') THEN 1 ELSE 0 END) AS terminal "
            "FROM records WHERE mission_id=?",
            (mission_id,),
        ).fetchone()
        expected = int(
            connection.execute(
                "SELECT expected_records FROM missions WHERE mission_id=?", (mission_id,)
            ).fetchone()[0]
        )
        total = int(counts["total"])
        terminal = int(counts["terminal"] or 0)
        state = "complete" if total == expected and terminal == expected else "running"
        connection.execute(
            "UPDATE missions SET state=?,updated_at=? WHERE mission_id=?", (state, now, mission_id)
        )
