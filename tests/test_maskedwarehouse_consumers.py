from __future__ import annotations

import json
from pathlib import Path

import pytest

from maskfactory.maskedwarehouse_consumers import (
    MaskedWarehouseConsumerError,
    verify_maskedwarehouse_consumers,
)

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = ROOT / "configs/maskedwarehouse_provenance.yaml"
BINDINGS = ROOT / "configs/maskedwarehouse_consumer_bindings.json"


def test_live_bindings_cover_every_eligible_source() -> None:
    report = verify_maskedwarehouse_consumers(
        project_root=ROOT, provenance_path=PROVENANCE, binding_path=BINDINGS
    )
    assert report["status"] == "PASS"
    assert report["eligible_source_count"] == 3
    assert report["consumed_eligible_source_count"] == 3
    assert report["policy_blocked_source_count"] == 2
    assert report["authority_limits"]["consumer_binding_grants_gold"] is False


def _mutated_bindings(tmp_path: Path, mutate) -> Path:
    payload = json.loads(BINDINGS.read_text(encoding="utf-8"))
    mutate(payload)
    path = tmp_path / "bindings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_inventory_only_eligible_source_fails(tmp_path: Path) -> None:
    path = _mutated_bindings(tmp_path, lambda p: p["sources"][0].update(consumers=[]))
    with pytest.raises(MaskedWarehouseConsumerError, match="inventory-only"):
        verify_maskedwarehouse_consumers(
            project_root=ROOT, provenance_path=PROVENANCE, binding_path=path
        )


def test_downstream_artifact_hash_drift_fails(tmp_path: Path) -> None:
    path = _mutated_bindings(
        tmp_path,
        lambda p: p["sources"][0]["consumers"][0].update(artifact_sha256="0" * 64),
    )
    with pytest.raises(MaskedWarehouseConsumerError, match="artifact drift"):
        verify_maskedwarehouse_consumers(
            project_root=ROOT, provenance_path=PROVENANCE, binding_path=path
        )


def test_policy_blocked_source_cannot_claim_consumer(tmp_path: Path) -> None:
    def mutate(payload):
        payload["sources"][3]["consumers"] = payload["sources"][0]["consumers"]

    path = _mutated_bindings(tmp_path, mutate)
    with pytest.raises(MaskedWarehouseConsumerError, match="blocked source has consumer"):
        verify_maskedwarehouse_consumers(
            project_root=ROOT, provenance_path=PROVENANCE, binding_path=path
        )
