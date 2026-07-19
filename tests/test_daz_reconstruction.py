from __future__ import annotations

import copy
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner
from jsonschema import Draft202012Validator

from maskfactory.cli import main
from maskfactory.daz.control import (
    DazControlError,
    append_event,
    build_event,
    initialize_daz_root,
    initialize_state_database,
    inspect_state_database,
)
from maskfactory.daz.reconstruction import (
    build_reconstruction_manifest_set,
    plan_history_reconstruction,
    publish_reconstruction_manifest_set,
    reconstruct_history_to_clean_database,
    validate_reconstruction_manifest_set,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "src/maskfactory/schemas/daz_reconstruction_manifest_set.schema.json"
CAPTURED_AT = datetime(2026, 7, 19, 7, 0, tzinfo=UTC)


def _source_fixture(tmp_path: Path, *, include_terminal_event: bool = True) -> tuple[Path, Path]:
    daz_root = tmp_path / "restored_daz"
    initialize_daz_root(daz_root, apply=True)
    database = daz_root / "10_queue/queue.sqlite"
    initialize_state_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO scene_recipes VALUES (?,?,?,?)",
            ("scene_a", "family_a", "ready", json.dumps({"seed": 101})),
        )
        connection.execute(
            "INSERT INTO scene_recipes VALUES (?,?,?,?)",
            ("scene_b", "family_b", "ready", json.dumps({"seed": 202})),
        )
        connection.execute("INSERT INTO jobs VALUES ('job_a','scene_a','complete',1)")
        connection.execute("INSERT INTO jobs VALUES ('job_b','scene_b','pending',0)")
        connection.execute(
            "INSERT INTO package_exports VALUES (?,?,?,?)",
            ("package_a", "scene_a", "accepted", json.dumps({"mask_count": 4})),
        )
        connection.commit()
    append_event(
        database,
        build_event(
            "scheduler.job_leased",
            "job",
            "job_a",
            {"lease_id": "lease_a", "prior_state": "pending"},
            job_id="job_a",
            attempt=1,
            timestamp="2026-07-19T06:58:00Z",
            event_id="evt_lease_a",
        ),
    )
    if include_terminal_event:
        append_event(
            database,
            build_event(
                "scheduler.job_complete",
                "job",
                "job_a",
                {"lease_id": "lease_a", "reason": "fixture accepted"},
                job_id="job_a",
                attempt=1,
                timestamp="2026-07-19T06:59:00Z",
                event_id="evt_complete_a",
            ),
        )
    return database, daz_root / "00_control/root_identity.json"


def _manifest(tmp_path: Path) -> tuple[Path, Path, dict]:
    database, registry = _source_fixture(tmp_path)
    manifest = build_reconstruction_manifest_set(
        database,
        registry,
        manifest_set_id="reconstruction_fixture_a",
        captured_at=CAPTURED_AT,
    )
    return database, registry, manifest


def test_reconstruction_schema_is_closed_and_manifest_is_deterministic(tmp_path: Path) -> None:
    Draft202012Validator.check_schema(json.loads(SCHEMA.read_text(encoding="utf-8")))
    database, registry, first = _manifest(tmp_path)
    second = build_reconstruction_manifest_set(
        database,
        registry,
        manifest_set_id="reconstruction_fixture_a",
        captured_at=CAPTURED_AT,
    )
    assert first == second
    validate_reconstruction_manifest_set(first)
    drifted = {**first, "unknown": True}
    with pytest.raises(DazControlError, match="closed schema"):
        validate_reconstruction_manifest_set(drifted)


def test_reconstruction_replays_exact_history_into_clean_wal_database(tmp_path: Path) -> None:
    source, registry, manifest = _manifest(tmp_path)
    target = tmp_path / "clean_restore/queue.sqlite"
    view = tmp_path / "clean_restore/registry_view.json"
    source_before = source.read_bytes()
    planned = plan_history_reconstruction(source, registry, target, manifest)
    assert planned["apply"] is False
    assert planned["replay_job_states"] == {
        "job_a": {"state": "complete", "attempt": 1},
        "job_b": {"state": "pending", "attempt": 0},
    }
    assert not target.exists() and source.read_bytes() == source_before

    result = reconstruct_history_to_clean_database(
        source,
        registry,
        target,
        manifest,
        registry_view_path=view,
    )
    assert result["passed"] is True
    assert result["duplicate_acceptance"] is False
    assert source.read_bytes() == source_before
    assert inspect_state_database(target)["passed"] is True
    with sqlite3.connect(target) as connection:
        assert connection.execute(
            "SELECT job_id,state,attempt FROM jobs ORDER BY job_id"
        ).fetchall() == [("job_a", "complete", 1), ("job_b", "pending", 0)]
        assert connection.execute("SELECT event_id FROM events ORDER BY rowid").fetchall() == [
            ("evt_lease_a",),
            ("evt_complete_a",),
        ]
    view_document = json.loads(view.read_text(encoding="utf-8"))
    assert view_document["manifest_set_sha256"] == manifest["manifest_set_sha256"]
    assert view_document["target_database_sha256"] == result["target_database_sha256"]


def test_reconstruction_manifest_publication_is_immutable_and_idempotent(
    tmp_path: Path,
) -> None:
    _, _, manifest = _manifest(tmp_path)
    output = tmp_path / "manifests/reconstruction.json"
    first = publish_reconstruction_manifest_set(manifest, output)
    second = publish_reconstruction_manifest_set(manifest, output)
    assert first["published"] is True and second["published"] is False
    output.write_text("{}\n", encoding="utf-8")
    with pytest.raises(DazControlError, match="exists with drift"):
        publish_reconstruction_manifest_set(manifest, output)


def test_reconstruction_rejects_bound_input_drift_and_existing_target(tmp_path: Path) -> None:
    source, registry, manifest = _manifest(tmp_path)
    registry.write_text('{"drift":true}\n', encoding="utf-8")
    with pytest.raises(DazControlError, match="path registry hash drift"):
        plan_history_reconstruction(source, registry, tmp_path / "target.sqlite", manifest)

    source, registry, manifest = _manifest(tmp_path / "second")
    target = tmp_path / "existing.sqlite"
    target.write_bytes(b"do not replace")
    with pytest.raises(DazControlError, match="must not exist"):
        reconstruct_history_to_clean_database(
            source,
            registry,
            target,
            manifest,
            registry_view_path=tmp_path / "view.json",
        )
    assert target.read_bytes() == b"do not replace"


def test_reconstruction_rejects_incomplete_event_replay_and_manifest_tamper(
    tmp_path: Path,
) -> None:
    source, registry = _source_fixture(tmp_path, include_terminal_event=False)
    rebuilt = build_reconstruction_manifest_set(
        source,
        registry,
        manifest_set_id="reconstruction_incomplete",
        captured_at=CAPTURED_AT,
    )
    with pytest.raises(DazControlError, match="event replay is incomplete"):
        plan_history_reconstruction(source, registry, tmp_path / "target.sqlite", rebuilt)

    tampered = copy.deepcopy(rebuilt)
    tampered["jobs"][0]["expected_attempt"] = 99
    with pytest.raises(DazControlError, match="manifest seal mismatch"):
        validate_reconstruction_manifest_set(tampered)


def test_reconstruction_requires_drained_source_and_valid_registry(tmp_path: Path) -> None:
    source, registry = _source_fixture(tmp_path)
    with sqlite3.connect(source) as connection:
        connection.execute(
            "INSERT INTO leases VALUES ('lease_active','job_b',4242,'2026-07-19T08:00:00Z')"
        )
        connection.commit()
    with pytest.raises(DazControlError, match="healthy drained"):
        build_reconstruction_manifest_set(
            source,
            registry,
            manifest_set_id="reconstruction_active_lease",
        )

    with sqlite3.connect(source) as connection:
        connection.execute("DELETE FROM leases")
        connection.commit()
    registry.write_text("[]\n", encoding="utf-8")
    with pytest.raises(DazControlError, match="must be a JSON object"):
        build_reconstruction_manifest_set(
            source,
            registry,
            manifest_set_id="reconstruction_bad_registry",
        )


def test_reconstruction_cli_is_read_only_by_default_and_applies_to_clean_paths(
    tmp_path: Path,
) -> None:
    source, registry = _source_fixture(tmp_path)
    target = tmp_path / "rebuilt/queue.sqlite"
    manifest_output = tmp_path / "rebuilt/reconstruction_manifest.json"
    view_output = tmp_path / "rebuilt/registry_view.json"
    command = [
        "daz",
        "recovery",
        "reconstruct-history",
        "--source-database",
        str(source),
        "--path-registry",
        str(registry),
        "--target-database",
        str(target),
        "--manifest-output",
        str(manifest_output),
        "--registry-view-output",
        str(view_output),
        "--manifest-set-id",
        "reconstruction_cli_fixture",
        "--captured-at",
        "2026-07-19T07:00:00Z",
    ]
    runner = CliRunner()
    planned = runner.invoke(main, command)
    assert planned.exit_code == 0, planned.output
    plan = json.loads(planned.output)
    assert plan["reason"] == "daz_history_reconstruction_plan"
    assert plan["data"]["reconstruction"]["apply"] is False
    assert not target.exists() and not manifest_output.exists() and not view_output.exists()

    applied = runner.invoke(main, [*command, "--apply"])
    assert applied.exit_code == 0, applied.output
    result = json.loads(applied.output)
    assert result["reason"] == "daz_history_reconstruction_passed"
    assert result["data"]["publication"]["published"] is True
    assert target.is_file() and manifest_output.is_file() and view_output.is_file()


def test_reconstruction_cli_requires_both_evidence_outputs_on_apply(tmp_path: Path) -> None:
    source, registry = _source_fixture(tmp_path)
    target = tmp_path / "rebuilt/queue.sqlite"
    result = CliRunner().invoke(
        main,
        [
            "daz",
            "recovery",
            "reconstruct-history",
            "--source-database",
            str(source),
            "--path-registry",
            str(registry),
            "--target-database",
            str(target),
            "--manifest-set-id",
            "reconstruction_cli_missing_outputs",
            "--captured-at",
            "2026-07-19T07:00:00Z",
            "--apply",
        ],
    )
    assert result.exit_code != 0
    assert not target.exists()
