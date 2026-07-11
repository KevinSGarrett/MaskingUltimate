import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.gc import GarbageCollectionError, apply_gc_plan, build_gc_plan, write_gc_log

NOW = datetime(2026, 7, 12, tzinfo=UTC)


def _package(root: Path, name: str, *, retain_until: str, referenced: bool = False) -> Path:
    package = root / name
    (package / "masks").mkdir(parents=True)
    (package / "masks/current.png").write_bytes(b"current")
    (package / "masks@v1").mkdir()
    (package / "masks@v1/old.png").write_bytes(b"old")
    (package / "mask_versions.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "active_version": 2,
                "versions": {
                    "1": {
                        "status": "deprecated",
                        "directory": "masks@v1",
                        "retain_until": retain_until,
                    },
                    "2": {"status": "human_approved_gold", "directory": "masks"},
                },
            }
        ),
        encoding="utf-8",
    )
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "files": {"masks@v1/old.png": "a" * 64}
                if referenced
                else {"masks/current.png": "b" * 64}
            }
        ),
        encoding="utf-8",
    )
    return package


def test_gc_only_selects_expired_unreferenced_deprecated_versions(tmp_path: Path) -> None:
    eligible = _package(tmp_path, "eligible", retain_until="2026-06-01T00:00:00+00:00")
    young = _package(tmp_path, "young", retain_until="2026-08-01T00:00:00+00:00")
    referenced = _package(
        tmp_path, "referenced", retain_until="2026-06-01T00:00:00+00:00", referenced=True
    )
    plan = build_gc_plan(tmp_path, now=NOW)
    assert len(plan.candidates) == 1
    assert plan.candidates[0].package_root == str(eligible.resolve())
    assert plan.candidates[0].relative_path == "masks@v1"
    assert plan.protected_count == 2
    assert (eligible / "masks@v1").is_dir()  # dry-run never deletes
    assert (young / "masks@v1").is_dir() and (referenced / "masks@v1").is_dir()
    removed = apply_gc_plan(plan, packages_root=tmp_path)
    assert removed == (eligible / "masks@v1",)
    assert not removed[0].exists()
    assert (eligible / "masks/current.png").read_bytes() == b"current"
    assert (young / "masks@v1").is_dir() and (referenced / "masks@v1").is_dir()
    log = write_gc_log(tmp_path / "gc.log", plan, applied=True, removed=removed)
    assert "REMOVED" in log.read_text() and plan.plan_hash in log.read_text()


def test_gc_refuses_changed_plan_and_cli_is_dry_run_by_default(tmp_path: Path) -> None:
    packages = tmp_path / "packages"
    package = _package(packages, "pkg", retain_until="2026-06-01T00:00:00+00:00")
    plan = build_gc_plan(packages, now=NOW)
    (package / "masks@v1/new.png").write_bytes(b"changed-after-review")
    with pytest.raises(GarbageCollectionError, match="changed after plan review"):
        apply_gc_plan(plan, packages_root=packages)

    runner = CliRunner()
    dry = runner.invoke(
        main, ["gc", "--packages-root", str(packages), "--logs-root", str(tmp_path / "logs")]
    )
    assert dry.exit_code == 0, dry.output
    assert "WOULD REMOVE" in dry.output and (package / "masks@v1").is_dir()
    applied = runner.invoke(
        main,
        [
            "gc",
            "--apply",
            "--yes",
            "--packages-root",
            str(packages),
            "--logs-root",
            str(tmp_path / "logs"),
        ],
    )
    assert applied.exit_code == 0, applied.output
    assert not (package / "masks@v1").exists()
    assert (package / "masks").is_dir()
