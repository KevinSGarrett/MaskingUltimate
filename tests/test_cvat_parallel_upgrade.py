from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OVERRIDE_PATH = ROOT / "configs" / "cvat-compose.parallel-v269.yml"
EVIDENCE_PATH = ROOT / "qa" / "live_verification" / "cvat_parallel_upgrade_v269_20260714.json"


def _load_override() -> dict:
    # Compose merge tags do not change the represented value; discard only the
    # tag so this unit test can inspect the fail-closed isolation contract.
    class Loader(yaml.SafeLoader):
        pass

    def construct_override(loader: Loader, node: yaml.Node):
        if isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node, deep=True)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node, deep=True)
        return loader.construct_scalar(node)

    Loader.add_constructor("!override", construct_override)
    return yaml.load(OVERRIDE_PATH.read_text(encoding="utf-8"), Loader=Loader)


def test_parallel_compose_cannot_reuse_production_names_or_ports() -> None:
    config = _load_override()
    assert config["name"] == "cvat269"
    services = config["services"]
    assert len(services) == 18
    assert all(service["container_name"].startswith("cvat269_") for service in services.values())
    assert services["traefik"]["ports"] == [
        "127.0.0.1:18080:8080",
        "127.0.0.1:18090:8090",
    ]


def test_parallel_traefik_routes_are_globally_unique() -> None:
    services = _load_override()["services"]
    server_labels = services["cvat_server"]["labels"]
    ui_labels = services["cvat_ui"]["labels"]
    assert "traefik.http.routers.cvat.rule" not in server_labels
    assert "traefik.http.routers.cvat-ui.rule" not in ui_labels
    assert "cvat269.localhost" in server_labels["traefik.http.routers.cvat269.rule"]
    assert "cvat269.localhost" in ui_labels["traefik.http.routers.cvat269-ui.rule"]


def test_parallel_migration_evidence_proves_copy_and_rollback() -> None:
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert evidence["result"] == "pass"
    assert evidence["parallel_target"]["production_volumes_reused"] is False
    verification = evidence["migration_verification"]
    assert verification["django_migrate_check_exit"] == 0
    assert verification["database"]["source_sha256"] == verification["database"]["target_sha256"]
    assert verification["media"]["source_sha256"] == verification["media"]["target_sha256"]
    assert (
        verification["authenticated_task_api"]["source_sha256"]
        == verification["authenticated_task_api"]["target_sha256"]
    )
    rollback = evidence["rollback_verification"]
    assert rollback["source_about_while_target_stopped_http"] == 200
    assert rollback["source_sam2_while_target_stopped"] == "running_healthy"
    assert rollback["parallel_restart_reported_version"] == "2.69.0"
