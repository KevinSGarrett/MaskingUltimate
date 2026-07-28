from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.daz.assets.cms import (
    CmsObservationError,
    build_offline_cms_fallback,
    compare_cms_with_inventory,
    load_cms_connection,
    query_cms_snapshot,
)
from maskfactory.daz.assets.filesystem_inventory import (
    ContentRoot,
    scan_inventory_chunk,
)


def _config(tmp_path: Path, port: int = 17237) -> Path:
    path = tmp_path / "cmscfg.json"
    path.write_text(
        json.dumps({"DatabaseClusterPath": str(tmp_path / "cluster"), "Port": port}),
        encoding="utf-8",
    )
    return path


def _roots(tmp_path: Path) -> tuple[ContentRoot, ...]:
    legacy = tmp_path / "legacy"
    primary = tmp_path / "primary"
    legacy.mkdir()
    primary.mkdir()
    return (
        ContentRoot("legacy_dim", legacy, 30, "legacy_dim"),
        ContentRoot("content_primary", primary, 10, "governed"),
    )


def test_cms_config_is_closed_and_never_contains_credentials(tmp_path: Path) -> None:
    connection = load_cms_connection(_config(tmp_path))
    assert connection.port == 17237
    assert len(connection.cluster_path_fingerprint) == 64
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"DatabaseClusterPath": "x", "Port": 1, "Password": "no"}))
    with pytest.raises(CmsObservationError, match="cms_config_shape"):
        load_cms_connection(bad)


def test_online_cms_query_is_local_read_only_and_canonical(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    psql = tmp_path / "psql.exe"
    psql.write_bytes(b"fixture")
    captured: dict[str, object] = {}

    def runner(
        command: Sequence[str], sql: str, environment: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        captured.update(command=list(command), sql=sql, environment=dict(environment))
        rows = [
            "root\t" + json.dumps({"cms_root_id": 1, "base_path": str(roots[0].path)}),
            "product\t"
            + json.dumps(
                {
                    "cms_product_id": 9,
                    "guid": "00000000-0000-0000-0000-000000000009",
                    "name": "Fixture",
                    "artists": "Artist",
                    "date_installed": "2026-07-16",
                }
            ),
            "content\t"
            + json.dumps(
                {
                    "cms_content_id": 4,
                    "cms_product_id": 9,
                    "relative_path": "People/Genesis 9/A #1.duf",
                    "content_type_id": 2,
                    "compatibility_base_id": 3,
                    "user_facing": True,
                }
            ),
        ]
        return subprocess.CompletedProcess(command, 0, "\n".join(rows), "")

    snapshot = query_cms_snapshot(
        registered_roots=roots,
        config_path=_config(tmp_path),
        psql_path=psql,
        runner=runner,
    )
    assert snapshot["cms_available"] is True
    assert snapshot["content_roots"][0]["registered_root_id"] == "legacy_dim"
    assert snapshot["contents"][0]["logical_uri"] == "/People/Genesis%209/A%20%231.duf"
    assert snapshot["contents"][0]["registered_root_id"] == "legacy_dim"
    assert "BEGIN TRANSACTION READ ONLY" in captured["sql"]
    assert captured["command"][captured["command"].index("-h") + 1] == "127.0.0.1"
    assert "default_transaction_read_only=on" in captured["environment"]["PGOPTIONS"]
    assert snapshot["connection"]["credentials_stored"] is False


def test_cms_failure_is_safe_and_offline_fallback_declares_gaps(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    psql = tmp_path / "psql.exe"
    psql.write_bytes(b"fixture")

    def failing(
        command: Sequence[str], sql: str, environment: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "connection refused")

    with pytest.raises(CmsObservationError, match="connection_failed"):
        query_cms_snapshot(
            registered_roots=roots,
            config_path=_config(tmp_path),
            psql_path=psql,
            runner=failing,
        )
    state = tmp_path / "inventory.sqlite"
    while not scan_inventory_chunk(state, roots, max_entries=100, max_seconds=10).complete:
        pass
    offline = build_offline_cms_fallback(
        registered_roots=roots,
        inventory_state=state,
        failure_reason_code="connection_failed",
    )
    assert offline["cms_available"] is False
    assert offline["filesystem_inventory"]["complete"] is True
    assert len(offline["metadata_gaps"]) == 4


def test_online_offline_comparison_uses_root_and_canonical_path(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    target = roots[0].path / "People" / "Genesis 9" / "pose.duf"
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    state = tmp_path / "inventory.sqlite"
    while not scan_inventory_chunk(state, roots, max_entries=100, max_seconds=10).complete:
        pass
    cms = {
        "contents": [
            {
                "registered_root_id": "legacy_dim",
                "canonical_path": "people/genesis 9/pose.duf",
            },
            {"registered_root_id": None, "canonical_path": "unresolved.duf"},
        ]
    }
    assert compare_cms_with_inventory(cms, state) == {
        "cms_content_rows": 2,
        "matched_filesystem_paths": 1,
        "missing_filesystem_paths": 0,
        "unresolved_cms_roots": 1,
    }


def test_offline_cms_cli_publishes_explicit_fallback(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    state = tmp_path / "inventory.sqlite"
    while not scan_inventory_chunk(state, roots, max_entries=100, max_seconds=10).complete:
        pass
    output = tmp_path / "cms_snapshots"
    config = _config(tmp_path)
    result = CliRunner().invoke(
        main,
        [
            "daz",
            "assets",
            "cms-scan",
            "--root",
            f"legacy_dim={roots[0].path}",
            "--root",
            f"content_primary={roots[1].path}",
            "--config",
            str(config),
            "--inventory-state",
            str(state),
            "--offline",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["data"]["cms_available"] is False
    assert Path(payload["data"]["publication"]["path"]).is_file()
