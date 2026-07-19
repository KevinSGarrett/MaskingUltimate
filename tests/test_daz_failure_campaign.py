from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from jsonschema import Draft202012Validator

from maskfactory.cli import main
from maskfactory.daz import (
    DazControlError,
    build_oom_recovery_decision,
    initialize_daz_root,
    load_daz_runtime_profile,
    load_failure_campaign_policy,
    plan_failure_campaign,
    run_failure_campaign,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/daz"
POLICY = CONFIG / "failure_campaign.yaml"
RUNTIME = CONFIG / "runtime.yaml"
SCHEMAS = ROOT / "src/maskfactory/schemas"


def _fixture_config(tmp_path: Path) -> tuple[Path, Path]:
    config = tmp_path / "configs"
    shutil.copytree(CONFIG, config)
    live = tmp_path / "live_daz"
    paths_file = config / "paths.yaml"
    paths = yaml.safe_load(paths_file.read_text(encoding="utf-8"))
    paths.update(
        {
            "root": str(live),
            "root_identity": str(live / "00_control/root_identity.json"),
            "acquisition_database": str(live / "00_control/acquisition.sqlite3"),
            "state_database": str(live / "10_queue/queue.sqlite"),
        }
    )
    paths_file.write_text(yaml.safe_dump(paths, sort_keys=False), encoding="utf-8")
    acquisition = config / "acquisition_capacity.yaml"
    capacity = yaml.safe_load(acquisition.read_text(encoding="utf-8"))
    capacity["root"] = str(live)
    acquisition.write_text(yaml.safe_dump(capacity, sort_keys=False), encoding="utf-8")
    initialize_daz_root(live, apply=True)
    return config, live


def _render_recipe() -> dict:
    return {
        "schema_version": "1.0.0",
        "job_id": "job_oom",
        "recipe_id": "recipe_job_oom",
        "created_at": "2026-07-19T00:00:00Z",
        "bundle_version": "1.0.0",
        "operation": "render_scene",
        "requires_gpu": True,
        "content_directories": ["fixture/content"],
        "payload": {
            "renderer": "iray",
            "annotation_width": 1024,
            "annotation_height": 1024,
            "ontology_id": "maskfactory_v1",
            "render_samples": 64,
            "tile_size": 256,
        },
    }


def test_failure_campaign_schemas_and_policy_are_closed(tmp_path: Path) -> None:
    for name in ("daz_failure_campaign_policy", "daz_failure_campaign_report"):
        schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    policy = load_failure_campaign_policy(POLICY)
    assert policy.document["required_scenarios"] == [
        "drive_loss",
        "db_corruption",
        "crash",
        "popup",
        "oom",
    ]
    drift = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    drift["popup"]["ui_input_allowed"] = True
    invalid = tmp_path / "invalid_failure_policy.yaml"
    invalid.write_text(yaml.safe_dump(drift), encoding="utf-8")
    with pytest.raises(DazControlError, match="closed schema"):
        load_failure_campaign_policy(invalid)


def test_campaign_refuses_live_descendants_and_nonempty_workspaces(tmp_path: Path) -> None:
    live = tmp_path / "live"
    live.mkdir()
    policy = load_failure_campaign_policy(POLICY)
    with pytest.raises(DazControlError, match="outside the live"):
        plan_failure_campaign(
            policy,
            live / "campaign",
            live_root=live,
            campaign_id="failure_campaign_bad",
        )
    workspace = tmp_path / "campaign"
    workspace.mkdir()
    (workspace / "foreign.txt").write_text("owned", encoding="utf-8")
    with pytest.raises(DazControlError, match="not empty"):
        run_failure_campaign(
            policy,
            workspace,
            live_root=live,
            campaign_id="failure_campaign_nonempty",
            runtime_profile=load_daz_runtime_profile(RUNTIME),
        )


def test_oom_allows_one_lower_cost_retry_then_quarantines_without_semantic_drift() -> None:
    policy = load_failure_campaign_policy(POLICY)
    recipe = _render_recipe()
    first = build_oom_recovery_decision(
        policy,
        recipe,
        completed_lower_cost_retries=0,
        overrides={"render_samples": 32, "tile_size": 128},
    )
    assert first["action"] == "retry_lower_cost"
    assert first["retry_recipe"]["payload"]["renderer"] == "iray"
    assert first["retry_recipe"]["payload"]["annotation_width"] == 1024
    second = build_oom_recovery_decision(
        policy,
        first["retry_recipe"],
        completed_lower_cost_retries=1,
        overrides={"render_samples": 16},
    )
    assert second["action"] == "quarantine" and second["retry_recipe"] is None
    with pytest.raises(DazControlError, match="allowlist"):
        build_oom_recovery_decision(
            policy,
            recipe,
            completed_lower_cost_retries=0,
            overrides={"renderer": "filament"},
        )
    with pytest.raises(DazControlError, match="lower than"):
        build_oom_recovery_decision(
            policy,
            recipe,
            completed_lower_cost_retries=0,
            overrides={"render_samples": 128},
        )


def test_full_isolated_campaign_passes_all_five_scenarios_without_live_mutation(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    live.mkdir()
    sentinel = live / "sentinel.bin"
    sentinel.write_bytes(b"live-must-not-change")
    before = sentinel.read_bytes()
    report = run_failure_campaign(
        load_failure_campaign_policy(POLICY),
        tmp_path / "campaign",
        live_root=live,
        campaign_id="failure_campaign_fixture_a",
        runtime_profile=load_daz_runtime_profile(RUNTIME),
        captured_at=datetime(2026, 7, 19, 6, 0, tzinfo=UTC),
    )
    assert report["passed"] is True
    assert report["scenario_count"] == 5
    assert [row["scenario"] for row in report["scenarios"]] == [
        "drive_loss",
        "db_corruption",
        "crash",
        "popup",
        "oom",
    ]
    assert all(row["passed"] for row in report["scenarios"])
    assert all(Path(path).is_file() for row in report["scenarios"] for path in row["evidence"])
    assert sentinel.read_bytes() == before
    written = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
    sealed = {key: value for key, value in written.items() if key != "report_sha256"}
    expected_seal = hashlib.sha256(
        json.dumps(sealed, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    assert written["report_sha256"] == expected_seal


def test_failure_campaign_cli_is_dry_run_default_and_apply_is_explicit(tmp_path: Path) -> None:
    config, _live = _fixture_config(tmp_path)
    workspace = tmp_path / "campaign"
    runner = CliRunner()
    base = [
        "daz",
        "failure-campaign",
        "run",
        "--config-root",
        str(config),
        "--policy",
        str(POLICY),
        "--runtime-policy",
        str(RUNTIME),
        "--workspace",
        str(workspace),
        "--campaign-id",
        "failure_campaign_cli_a",
    ]
    planned = runner.invoke(main, base)
    assert planned.exit_code == 0, planned.output
    assert json.loads(planned.output)["data"]["campaign"]["apply"] is False
    assert not workspace.exists()
    applied = runner.invoke(main, [*base, "--apply"])
    assert applied.exit_code == 0, applied.output
    document = json.loads(applied.output)
    assert document["reason"] == "daz_failure_campaign_passed"
    assert document["data"]["campaign"]["passed"] is True
