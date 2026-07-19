from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

import maskfactory.daz.control as daz_control
from maskfactory.cli import main
from maskfactory.daz import (
    DazControlError,
    finish_lease,
    initialize_daz_root,
    initialize_state_database,
    lease_next_job,
    load_control_configuration,
    load_retention_policy,
    read_control_state,
    reserve_job_storage,
    scheduler_status,
    set_control_state,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "daz"


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


def _queue_jobs(configuration, *job_ids: str) -> None:
    database = configuration.paths.state_database
    connection = sqlite3.connect(database)
    try:
        for job_id in job_ids:
            scene_id = f"scene_{job_id}"
            connection.execute(
                "INSERT INTO scene_recipes(scene_id,family_id,state,payload_json) VALUES (?,?,?,?)",
                (scene_id, "fixture_family", "ready", "{}"),
            )
            connection.execute(
                "INSERT INTO jobs(job_id,scene_id,state,attempt) VALUES (?,?,?,0)",
                (job_id, scene_id, "pending"),
            )
        connection.commit()
    finally:
        connection.close()
    policy = load_retention_policy(CONFIG / "retention.yaml")
    for index, job_id in enumerate(job_ids):
        reserve_job_storage(
            configuration,
            policy,
            job_id=job_id,
            profile_id="fixture_profile",
            profile_estimate_bytes=1024,
            profile_p95_bytes=2048,
            observed_free_bytes=200 * 1024**3,
            reservation_id=f"reservation_{job_id}",
            event_id=f"evt_reservation_{index}",
        )


def test_pause_resume_and_drain_are_hash_linked_dry_run_safe(tmp_path: Path):
    _, configuration = _fixture_configuration(tmp_path)
    set_control_state(configuration, "enable", reason="fixture enable", apply=True, free_gib=200)
    paused = set_control_state(configuration, "pause", reason="fixture pause", apply=True)
    assert {
        key: paused["data"]["after"][key]
        for key in ("enabled", "paused", "drain", "stop_requested")
    } == {"enabled": True, "paused": True, "drain": False, "stop_requested": False}
    revision = read_control_state(configuration)["revision"]
    planned = set_control_state(
        configuration, "resume", reason="fixture plan", apply=False, free_gib=200
    )
    assert planned["data"]["apply"] is False
    assert read_control_state(configuration)["revision"] == revision
    with pytest.raises(DazControlError, match="soft floor"):
        set_control_state(
            configuration, "resume", reason="fixture low disk", apply=False, free_gib=149
        )
    resumed = set_control_state(
        configuration, "resume", reason="fixture resume", apply=True, free_gib=200
    )
    assert resumed["data"]["after"]["paused"] is False
    drained = set_control_state(configuration, "drain", reason="fixture drain", apply=True)
    assert drained["data"]["after"]["enabled"] is True
    assert drained["data"]["after"]["paused"] is True
    assert drained["data"]["after"]["drain"] is True
    assert drained["data"]["after"]["previous_sha256"]


def test_scheduler_leases_deterministically_and_never_exceeds_worker_cap(tmp_path: Path):
    _, configuration = _fixture_configuration(tmp_path)
    _queue_jobs(configuration, "job_b", "job_a")
    set_control_state(configuration, "enable", reason="fixture enable", apply=True, free_gib=200)
    leased = lease_next_job(
        configuration,
        owner_pid=4242,
        lease_seconds=60,
        now=datetime(2026, 7, 19, 4, 0, tzinfo=UTC),
        lease_id="lease_fixture_a",
        event_id="evt_fixture_lease_a",
    )
    assert leased["data"] == {
        "leased": True,
        "job_id": "job_a",
        "lease_id": "lease_fixture_a",
        "attempt": 1,
        "owner_pid": 4242,
        "expires_at": "2026-07-19T04:01:00Z",
        "control_revision": 1,
    }
    capped = lease_next_job(configuration, owner_pid=4243, lease_seconds=60)
    assert capped["reason"] == "scheduler_capacity_no_lease"
    status = scheduler_status(configuration)["data"]
    assert status["active_lease_count"] == 1
    assert status["leasing_allowed"] is False

    connection = sqlite3.connect(configuration.paths.state_database)
    try:
        event = connection.execute(
            "SELECT event_type,data_json FROM events WHERE event_id='evt_fixture_lease_a'"
        ).fetchone()
        assert event[0] == "scheduler.job_leased"
        assert json.loads(event[1])["control_revision"] == 1
    finally:
        connection.close()


def test_pause_and_drain_block_new_leases_but_allow_active_job_to_finish(tmp_path: Path):
    _, configuration = _fixture_configuration(tmp_path)
    _queue_jobs(configuration, "job_a", "job_b")
    set_control_state(configuration, "enable", reason="fixture enable", apply=True, free_gib=200)
    lease_next_job(
        configuration,
        owner_pid=4242,
        lease_seconds=60,
        lease_id="lease_fixture_a",
        event_id="evt_fixture_lease_a",
    )
    set_control_state(configuration, "drain", reason="fixture drain", apply=True)
    blocked = lease_next_job(configuration, owner_pid=4243, lease_seconds=60)
    assert blocked["reason"] == "scheduler_controlled_no_lease"
    assert scheduler_status(configuration)["data"]["drained"] is False
    finished = finish_lease(
        configuration,
        lease_id="lease_fixture_a",
        terminal_state="complete",
        reason="fixture worker result committed",
        event_id="evt_fixture_complete_a",
    )
    assert finished["data"]["artifact_promoted"] is False
    status = scheduler_status(configuration)["data"]
    assert status["drained"] is True
    assert status["job_state_counts"] == {"complete": 1, "pending": 1}

    connection = sqlite3.connect(configuration.paths.state_database)
    try:
        assert connection.execute("SELECT count(*) FROM leases").fetchone()[0] == 0
        assert connection.execute("SELECT state FROM jobs WHERE job_id='job_b'").fetchone()[0] == (
            "pending"
        )
        reservation = connection.execute(
            "SELECT state,released_at FROM storage_reservations WHERE job_id='job_a'"
        ).fetchone()
        assert reservation[0] == "released"
        assert reservation[1] is not None
    finally:
        connection.close()


def test_disabled_worker_never_mutates_queue_or_creates_a_lease(tmp_path: Path):
    _, configuration = _fixture_configuration(tmp_path)
    _queue_jobs(configuration, "job_a")
    result = lease_next_job(configuration, owner_pid=4242, lease_seconds=60)
    assert result["reason"] == "scheduler_controlled_no_lease"
    connection = sqlite3.connect(configuration.paths.state_database)
    try:
        assert connection.execute("SELECT state,attempt FROM jobs").fetchone() == ("pending", 0)
        assert connection.execute("SELECT count(*) FROM leases").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == 1
    finally:
        connection.close()


def test_worker_cli_pause_resume_drain_and_status_are_json_and_dry_run_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config, configuration = _fixture_configuration(tmp_path)
    _queue_jobs(configuration, "job_a")
    set_control_state(configuration, "enable", reason="fixture enable", apply=True, free_gib=200)
    monkeypatch.setattr(daz_control, "_disk_free_gib", lambda _root: 200.0)
    runner = CliRunner()
    paused = runner.invoke(
        main,
        ["daz", "worker", "pause", "--config-root", str(config), "--reason", "fixture"],
    )
    assert paused.exit_code == 0
    assert json.loads(paused.output)["data"]["apply"] is False
    assert read_control_state(configuration)["paused"] is False
    applied = runner.invoke(
        main,
        [
            "daz",
            "worker",
            "pause",
            "--config-root",
            str(config),
            "--reason",
            "fixture",
            "--apply",
        ],
    )
    assert applied.exit_code == 0 and read_control_state(configuration)["paused"] is True
    status = runner.invoke(main, ["daz", "worker", "status", "--config-root", str(config)])
    assert status.exit_code == 0
    assert json.loads(status.output)["data"]["leasing_allowed"] is False
    resumed = runner.invoke(
        main,
        [
            "daz",
            "worker",
            "resume",
            "--config-root",
            str(config),
            "--reason",
            "fixture",
            "--apply",
        ],
    )
    assert resumed.exit_code == 0
    drained = runner.invoke(
        main,
        [
            "daz",
            "worker",
            "drain",
            "--config-root",
            str(config),
            "--reason",
            "fixture",
            "--apply",
        ],
    )
    assert drained.exit_code == 0
    assert read_control_state(configuration)["drain"] is True
