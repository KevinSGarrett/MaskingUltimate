"""Gold-volume tournament input path map + compose RO mount wiring."""

from __future__ import annotations

from pathlib import Path

import yaml

from maskfactory.autonomy.gold_volume_paths import (
    DEFAULT_MAP_PATH,
    GoldVolumePathError,
    load_gold_volume_map,
    probe_gold_volume_paths,
    resolve_gold_volume_roots,
)
from maskfactory.serve.docker_contract import probe_docker_serve_contract
from maskfactory.training.docker_contract import probe_docker_train_contract

REPO = Path(__file__).resolve().parents[1]
COMPOSE_GPU = REPO / "docker" / "compose.gpu.yml"
COMPOSE_GOLD = REPO / "docker" / "compose.gold-volumes.yml"


def test_gold_volume_map_loads_read_only() -> None:
    document = load_gold_volume_map(DEFAULT_MAP_PATH)
    assert document["access_mode"] == "read_only"
    assert set(document["volumes"]) >= {"maskedwarehouse", "reference", "daz"}
    for key in ("maskedwarehouse", "reference", "daz"):
        assert document["volumes"][key]["mount_mode"] == "ro"


def test_gold_volume_map_rejects_writable(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        DEFAULT_MAP_PATH.read_text(encoding="utf-8").replace(
            "access_mode: read_only", "access_mode: read_write", 1
        ),
        encoding="utf-8",
    )
    try:
        load_gold_volume_map(bad)
        raise AssertionError("expected GoldVolumePathError")
    except GoldVolumePathError as exc:
        assert "read_only" in str(exc)


def test_resolve_host_roots_match_config(monkeypatch) -> None:
    monkeypatch.delenv("MASKFACTORY_CONTAINER_RUNTIME", raising=False)
    roots = resolve_gold_volume_roots(DEFAULT_MAP_PATH)
    document = load_gold_volume_map(DEFAULT_MAP_PATH)
    assert roots.access_mode == "read_only"
    assert not roots.using_container_roots
    assert str(roots.maskedwarehouse) == document["volumes"]["maskedwarehouse"]["host_root"]
    assert str(roots.reference) == document["volumes"]["reference"]["host_root"]
    assert str(roots.daz) == document["volumes"]["daz"]["host_root"]


def test_compose_gold_overlay_wires_ro_mounts_and_env() -> None:
    document = yaml.safe_load(COMPOSE_GOLD.read_text(encoding="utf-8"))
    expected_mounts = {
        "C:/Comfy_UI_Main/MaskedWarehouse:/gold/maskedwarehouse:ro",
        "F:/Reference_Images:/gold/reference:ro",
        "F:/DAZ:/gold/daz:ro",
    }
    for service_name in ("maskfactory-train", "maskfactory-serve"):
        service = document["services"][service_name]
        volumes = set(service["volumes"])
        assert expected_mounts <= volumes
        env = service["environment"]
        assert env["MASKFACTORY_GOLD_MASKEDWAREHOUSE"] == "/gold/maskedwarehouse"
        assert env["MASKFACTORY_GOLD_REFERENCE"] == "/gold/reference"
        assert env["MASKFACTORY_GOLD_DAZ"] == "/gold/daz"
        assert env["MASKFACTORY_GOLD_VOLUME_MAP"].endswith(
            "configs/gold_volume_tournament_inputs.yaml"
        )


def test_docker_gpu_contracts_still_ready() -> None:
    assert COMPOSE_GPU.is_file()
    train = probe_docker_train_contract()
    serve = probe_docker_serve_contract()
    assert train.ready, train.issues
    assert serve.ready, serve.issues


def test_live_probe_reports_required_roots_when_present() -> None:
    report = probe_gold_volume_paths(DEFAULT_MAP_PATH)
    assert report["access_mode"] == "read_only"
    # Host probe: when the governed roots exist on this machine, all three must be present.
    mw = Path(r"C:\Comfy_UI_Main\MaskedWarehouse")
    ref = Path(r"F:\Reference_Images")
    daz = Path(r"F:\DAZ")
    if mw.is_dir() and ref.is_dir() and daz.is_dir():
        assert report["required_roots_present"] is True
        assert report["probes"]["maskedwarehouse_root"]["readable"] is True
        assert report["probes"]["reference_root"]["readable"] is True
        assert report["probes"]["daz_root"]["readable"] is True
        assert report["probes"]["daz_root_identity"]["exists"] is True
        assert report["probes"]["reference_database"]["exists"] is True
