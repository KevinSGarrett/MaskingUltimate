from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from jsonschema import Draft202012Validator

import maskfactory.daz.control as daz_control
import maskfactory.daz.storage as daz_storage
from maskfactory.cli import main
from maskfactory.daz import (
    DazControlError,
    apply_capacity_control,
    apply_retention_plan,
    build_retention_plan,
    initialize_daz_root,
    initialize_state_database,
    lease_next_job,
    load_control_configuration,
    load_retention_policy,
    read_control_state,
    register_retention_artifact,
    required_reservation_bytes,
    reserve_job_storage,
    set_control_state,
    storage_capacity_decision,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "daz"
POLICY = CONFIG / "retention.yaml"
SCHEMA = ROOT / "src" / "maskfactory" / "schemas" / "daz_retention.schema.json"
GIB = 1024**3
AS_OF = datetime(2026, 7, 19, 4, 30, tzinfo=UTC)
OLD = datetime(2026, 1, 1, tzinfo=UTC)


def _fixture_configuration(tmp_path: Path):
    config = tmp_path / "configs"
    shutil.copytree(CONFIG, config)
    daz_root = tmp_path / "DAZ Root"
    paths_file = config / "paths.yaml"
    paths = yaml.safe_load(paths_file.read_text(encoding="utf-8"))
    paths.update(
        {
            "root": str(daz_root),
            "root_identity": str(daz_root / "00_control" / "root_identity.json"),
            "acquisition_database": str(daz_root / "00_control" / "acquisition.sqlite3"),
            "state_database": str(daz_root / "10_queue" / "queue.sqlite"),
        }
    )
    paths_file.write_text(yaml.safe_dump(paths, sort_keys=False), encoding="utf-8")
    capacity_file = config / "acquisition_capacity.yaml"
    capacity = yaml.safe_load(capacity_file.read_text(encoding="utf-8"))
    capacity["root"] = str(daz_root)
    capacity_file.write_text(yaml.safe_dump(capacity, sort_keys=False), encoding="utf-8")
    initialize_daz_root(daz_root, apply=True)
    configuration = load_control_configuration(config)
    initialize_state_database(configuration.paths.state_database)
    return config, configuration


def _queue_job(configuration, job_id: str) -> None:
    with sqlite3.connect(configuration.paths.state_database) as connection:
        connection.execute(
            "INSERT INTO scene_recipes VALUES (?,?,?,?)",
            (f"scene_{job_id}", "fixture_family", "ready", "{}"),
        )
        connection.execute(
            "INSERT INTO jobs(job_id,scene_id,state,attempt) VALUES (?,?,?,0)",
            (job_id, f"scene_{job_id}", "pending"),
        )


def _artifact(
    configuration,
    artifact_id: str,
    retention_class: str,
    content: bytes,
    *,
    created_at: datetime = OLD,
    protected_reference_count: int = 0,
    live_lease_id: str | None = None,
) -> Path:
    path = configuration.paths.root / "20_tmp" / f"{artifact_id}.bin"
    path.write_bytes(content)
    register_retention_artifact(
        configuration,
        artifact_id=artifact_id,
        path=path,
        retention_class=retention_class,
        created_at=created_at,
        protected_reference_count=protected_reference_count,
        live_lease_id=live_lease_id,
    )
    return path


def test_retention_policy_schema_and_exact_integer_reservation_formula() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    policy = load_retention_policy(POLICY)
    assert tuple(policy.classes) == ("R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7")
    assert policy.numerator == 5 and policy.denominator == 4
    assert required_reservation_bytes(100, 99) == 125
    assert required_reservation_bytes(99, 101) == 127
    with pytest.raises(DazControlError, match="cannot be zero"):
        required_reservation_bytes(0, 0)


def test_state_v4_contains_reservation_and_retention_tables(tmp_path: Path) -> None:
    _, configuration = _fixture_configuration(tmp_path)
    with sqlite3.connect(configuration.paths.state_database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {
        "storage_reservations",
        "retention_artifacts",
        "retention_plans",
        "retention_plan_items",
    } <= tables


def test_exact_fill_states_pause_drain_and_stop_without_live_process_action(tmp_path: Path) -> None:
    _, configuration = _fixture_configuration(tmp_path)
    set_control_state(configuration, "enable", reason="fixture", apply=True, free_gib=200)
    assert storage_capacity_decision(configuration, observed_free_bytes=150 * GIB)["action"] == (
        "none"
    )
    soft = apply_capacity_control(
        configuration, observed_free_bytes=149 * GIB, reason="fixture", apply=True
    )
    assert soft["data"]["decision"]["action"] == "pause"
    assert read_control_state(configuration)["paused"] is True
    set_control_state(configuration, "resume", reason="fixture", apply=True, free_gib=200)
    hard = apply_capacity_control(
        configuration, observed_free_bytes=99 * GIB, reason="fixture", apply=True
    )
    assert hard["data"]["decision"]["action"] == "drain"
    assert read_control_state(configuration)["drain"] is True
    set_control_state(configuration, "resume", reason="fixture", apply=True, free_gib=200)
    emergency = apply_capacity_control(
        configuration, observed_free_bytes=59 * GIB, reason="fixture", apply=True
    )
    assert emergency["data"]["decision"]["action"] == "stop"
    assert read_control_state(configuration)["stop_requested"] is True


def test_reservation_is_required_before_lease_and_projected_soft_floor_refuses(
    tmp_path: Path,
) -> None:
    _, configuration = _fixture_configuration(tmp_path)
    policy = load_retention_policy(POLICY)
    _queue_job(configuration, "job_a")
    _queue_job(configuration, "job_b")
    set_control_state(configuration, "enable", reason="fixture", apply=True, free_gib=200)
    assert lease_next_job(configuration, owner_pid=100, lease_seconds=60)["reason"] == (
        "scheduler_idle"
    )
    reservation = reserve_job_storage(
        configuration,
        policy,
        job_id="job_a",
        profile_id="standard",
        profile_estimate_bytes=8 * GIB,
        profile_p95_bytes=10 * GIB,
        observed_free_bytes=200 * GIB,
        reservation_id="reservation_a",
        event_id="evt_reservation_a",
        now=AS_OF,
    )
    assert reservation["data"]["required_bytes"] == 12.5 * GIB
    leased = lease_next_job(
        configuration,
        owner_pid=100,
        lease_seconds=60,
        lease_id="lease_a",
        event_id="evt_lease_a",
        now=AS_OF,
    )
    assert leased["data"]["job_id"] == "job_a"
    with sqlite3.connect(configuration.paths.state_database) as connection:
        assert (
            connection.execute(
                "SELECT state FROM storage_reservations WHERE reservation_id='reservation_a'"
            ).fetchone()[0]
            == "consumed"
        )

    _queue_job(configuration, "job_c")
    with pytest.raises(DazControlError, match="reservation refused"):
        reserve_job_storage(
            configuration,
            policy,
            job_id="job_c",
            profile_id="oversized",
            profile_estimate_bytes=40 * GIB,
            profile_p95_bytes=40 * GIB,
            observed_free_bytes=200 * GIB,
        )


def test_retention_dry_runs_are_identical_and_protect_r0_references_and_live_leases(
    tmp_path: Path,
) -> None:
    _, configuration = _fixture_configuration(tmp_path)
    policy = load_retention_policy(POLICY)
    _artifact(configuration, "r0", "R0", b"permanent")
    _artifact(configuration, "r5_b", "R5", b"bb")
    _artifact(configuration, "r5_a", "R5", b"aaa")
    _artifact(
        configuration,
        "protected",
        "R5",
        b"protected",
        protected_reference_count=1,
    )
    _queue_job(configuration, "lease_job")
    with sqlite3.connect(configuration.paths.state_database) as connection:
        connection.execute(
            "INSERT INTO leases VALUES (?,?,?,?)",
            ("lease_live", "lease_job", 4242, "2026-07-19T05:30:00Z"),
        )
    _artifact(
        configuration,
        "leased",
        "R5",
        b"leased",
        live_lease_id="lease_live",
    )
    first = build_retention_plan(
        configuration,
        policy,
        observed_free_bytes=1000,
        target_free_bytes=1004,
        as_of=AS_OF,
        persist=False,
    )
    second = build_retention_plan(
        configuration,
        policy,
        observed_free_bytes=1000,
        target_free_bytes=1004,
        as_of=AS_OF,
        persist=False,
    )
    assert first == second
    assert [row["artifact_id"] for row in first["items"]] == ["r5_a", "r5_b"]
    exclusions = {row["artifact_id"]: row["reason"] for row in first["exclusions"]}
    assert exclusions == {
        "leased": "active_lease",
        "protected": "protected_reference",
        "r0": "protected_retention_class",
    }


def test_retention_apply_is_dry_run_default_then_deletes_only_exact_planned_files(
    tmp_path: Path,
) -> None:
    _, configuration = _fixture_configuration(tmp_path)
    policy = load_retention_policy(POLICY)
    selected = _artifact(configuration, "cache", "R5", b"cache")
    permanent = _artifact(configuration, "permanent", "R0", b"permanent")
    plan = build_retention_plan(
        configuration,
        policy,
        observed_free_bytes=1000,
        target_free_bytes=1005,
        as_of=AS_OF,
        persist=True,
    )
    dry = apply_retention_plan(configuration, plan_id=plan["plan_id"], dry_run=True)
    assert dry["data"]["applicable"] is True
    assert selected.is_file() and permanent.is_file()
    applied = apply_retention_plan(configuration, plan_id=plan["plan_id"], dry_run=False, now=AS_OF)
    assert applied["data"]["deleted_artifact_ids"] == ["cache"]
    assert not selected.exists() and permanent.is_file()
    with sqlite3.connect(configuration.paths.state_database) as connection:
        assert (
            connection.execute(
                "SELECT status FROM retention_plans WHERE plan_id=?", (plan["plan_id"],)
            ).fetchone()[0]
            == "applied"
        )
        assert (
            connection.execute(
                "SELECT state FROM retention_artifacts WHERE artifact_id='cache'"
            ).fetchone()[0]
            == "deleted"
        )


def test_retention_apply_refuses_hash_drift_without_marking_or_deleting(tmp_path: Path) -> None:
    _, configuration = _fixture_configuration(tmp_path)
    policy = load_retention_policy(POLICY)
    candidate = _artifact(configuration, "cache", "R5", b"cache")
    plan = build_retention_plan(
        configuration,
        policy,
        observed_free_bytes=1000,
        target_free_bytes=1005,
        as_of=AS_OF,
        persist=True,
    )
    candidate.write_bytes(b"drift")
    with pytest.raises(DazControlError, match="size drifted|hash drifted"):
        apply_retention_plan(configuration, plan_id=plan["plan_id"], dry_run=False)
    assert candidate.is_file()
    with sqlite3.connect(configuration.paths.state_database) as connection:
        assert (
            connection.execute(
                "SELECT state FROM retention_artifacts WHERE artifact_id='cache'"
            ).fetchone()[0]
            == "active"
        )


def test_retention_apply_refuses_a_live_lease_acquired_after_initial_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, configuration = _fixture_configuration(tmp_path)
    policy = load_retention_policy(POLICY)
    candidate = _artifact(configuration, "cache", "R5", b"cache")
    plan = build_retention_plan(
        configuration,
        policy,
        observed_free_bytes=1000,
        target_free_bytes=1005,
        as_of=AS_OF,
        persist=True,
    )
    original_verify = daz_storage._verify_planned_artifact
    verification_count = 0

    def acquire_lease_after_first_verification(configuration, artifact, active_leases):
        nonlocal verification_count
        original_verify(configuration, artifact, active_leases)
        verification_count += 1
        if verification_count == 1:
            _queue_job(configuration, "late_job")
            with sqlite3.connect(configuration.paths.state_database) as connection:
                connection.execute(
                    "INSERT INTO leases VALUES (?,?,?,?)",
                    ("late_lease", "late_job", 4242, "2026-07-19T05:30:00Z"),
                )
                connection.execute(
                    "UPDATE retention_artifacts SET live_lease_id=? WHERE artifact_id='cache'",
                    ("late_lease",),
                )

    monkeypatch.setattr(
        daz_storage, "_verify_planned_artifact", acquire_lease_after_first_verification
    )
    result = apply_retention_plan(configuration, plan_id=plan["plan_id"], dry_run=False)
    assert result["reason"] == "retention_plan_partial"
    assert result["data"]["deleted_artifact_ids"] == []
    assert "live lease" in result["data"]["failures"][0]["reason"]
    assert candidate.is_file()
    with sqlite3.connect(configuration.paths.state_database) as connection:
        assert (
            connection.execute(
                "SELECT state FROM retention_artifacts WHERE artifact_id='cache'"
            ).fetchone()[0]
            == "marked"
        )


def test_retention_plan_items_are_immutable_and_outside_paths_fail_closed(tmp_path: Path) -> None:
    _, configuration = _fixture_configuration(tmp_path)
    policy = load_retention_policy(POLICY)
    _artifact(configuration, "cache", "R5", b"cache")
    plan = build_retention_plan(
        configuration,
        policy,
        observed_free_bytes=1000,
        target_free_bytes=1005,
        as_of=AS_OF,
        persist=True,
    )
    with sqlite3.connect(configuration.paths.state_database) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE"):
            connection.execute(
                "UPDATE retention_plan_items SET bytes=0 WHERE plan_id=?", (plan["plan_id"],)
            )
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    with pytest.raises(DazControlError, match="escapes"):
        register_retention_artifact(
            configuration,
            artifact_id="outside",
            path=outside,
            retention_class="R5",
            created_at=OLD,
        )


def test_retention_cli_plan_persists_and_apply_defaults_to_dry_run(tmp_path: Path) -> None:
    config, configuration = _fixture_configuration(tmp_path)
    _artifact(configuration, "cache", "R5", b"cache")
    runner = CliRunner()
    planned = runner.invoke(
        main,
        [
            "daz",
            "retention",
            "plan",
            "--config-root",
            str(config),
            "--policy",
            str(POLICY),
            "--observed-free-bytes",
            "1000",
            "--target-free-gib",
            str(1005 / GIB),
            "--as-of",
            "2026-07-19T04:30:00Z",
            "--persist",
        ],
    )
    assert planned.exit_code == 0, planned.output
    plan = json.loads(planned.output)
    dry = runner.invoke(
        main,
        [
            "daz",
            "retention",
            "apply",
            "--config-root",
            str(config),
            "--plan",
            plan["plan_id"],
        ],
    )
    assert dry.exit_code == 0
    assert json.loads(dry.output)["data"]["dry_run"] is True
    assert (configuration.paths.root / "20_tmp" / "cache.bin").is_file()


def test_capacity_cli_or_storage_code_never_uses_live_control_in_fixtures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, configuration = _fixture_configuration(tmp_path)
    monkeypatch.setattr(daz_control, "_disk_free_gib", lambda _root: 200.0)
    before = read_control_state(configuration)
    decision = apply_capacity_control(
        configuration, observed_free_bytes=149 * GIB, reason="dry fixture", apply=False
    )
    assert decision["data"]["decision"]["action"] == "pause"
    assert read_control_state(configuration) == before
