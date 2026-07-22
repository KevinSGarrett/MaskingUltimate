import hashlib
from pathlib import Path

from tools.verify_runpod_corpus_mirrors import (
    MASKEDWAREHOUSE_ROOT,
    REFERENCE_ROOT,
    REMOTE_SNAPSHOT,
    build_evidence,
    inventory_seal,
    maskedwarehouse_sample_bindings,
)


def _source() -> dict[str, object]:
    return {
        "verified_at_utc": "20260721T060440Z",
        "sanity_counts": {
            "masked_warehouse": {"file_count": 489638, "bytes": 6866153864},
            "ultimate_masking_reference": {
                "file_count": 3711,
                "bytes": 11539355704,
            },
        },
    }


def _remote() -> dict[str, object]:
    return {
        "maskedwarehouse": {
            "path": MASKEDWAREHOUSE_ROOT,
            "exists": True,
            "top_level": ["Body", "CelebAMask-HQ", "LaPa"],
        },
        "ultimate_reference_library": {
            "path": REFERENCE_ROOT,
            "exists": True,
            "top_level": ["benchmark_reference", "manifests"],
        },
        "snapshot": {
            "path": REMOTE_SNAPSHOT,
            "exists": True,
            "sha256": None,
        },
    }


def test_exact_corpus_snapshot_passes(tmp_path: Path) -> None:
    source_path = tmp_path / "source.json"
    source_path.write_text("{}\n", encoding="utf-8")
    remote = _remote()
    remote["snapshot"]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    evidence = build_evidence(
        pod={"id": "pod", "desiredStatus": "RUNNING"},
        remote=remote,
        source=_source(),
        source_path=source_path,
    )
    assert evidence["status"] == "RUNTIME_PASS_HASH_BOUND_SNAPSHOT"
    assert all(evidence["checks"].values())
    assert evidence["authority"]["mutating_api_calls"] is False


def test_missing_or_drifted_corpus_fails_closed(tmp_path: Path) -> None:
    source_path = tmp_path / "source.json"
    source_path.write_text("{}\n", encoding="utf-8")
    remote = _remote()
    remote["snapshot"]["sha256"] = "0" * 64
    evidence = build_evidence(
        pod={"id": "pod", "desiredStatus": "RUNNING"},
        remote=remote,
        source=_source(),
        source_path=source_path,
    )
    assert evidence["status"] == "RUNTIME_DRIFT"
    assert evidence["checks"]["remote_snapshot_hash_matches"] is False


def _local_inventory() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "sample_hash_policy": "lexicographically smallest 5 files per role",
        "sources": [
            {
                "source": "lapa",
                "counts": {"total_files": 489638},
                "extensions": {"image": {".jpg": 1}},
                "image_samples": [{"path": "images/a.jpg", "sha256": "a" * 64}],
                "mask_samples": [{"path": "labels/a.png", "sha256": "b" * 64}],
            }
        ],
    }


def test_local_remote_sample_hashes_and_inventory_seal_pass(tmp_path: Path) -> None:
    source_path = tmp_path / "source.json"
    source_path.write_text("{}\n", encoding="utf-8")
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text("{}\n", encoding="utf-8")
    remote = _remote()
    remote["snapshot"]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    bindings = maskedwarehouse_sample_bindings(_local_inventory())
    remote["maskedwarehouse"]["sample_hashes"] = bindings
    evidence = build_evidence(
        pod={"id": "pod", "desiredStatus": "RUNNING"},
        remote=remote,
        source=_source(),
        source_path=source_path,
        local_inventory=_local_inventory(),
        local_inventory_path=inventory_path,
    )
    assert evidence["status"] == "RUNTIME_PASS_HASH_BOUND_SNAPSHOT"
    assert evidence["maskedwarehouse_local_remote_reconciliation"]["sample_count"] == 2
    assert evidence["maskedwarehouse_local_remote_reconciliation"][
        "inventory_seal_sha256"
    ] == inventory_seal(_local_inventory())


def test_one_remote_sample_hash_drift_fails_before_provider_use(tmp_path: Path) -> None:
    source_path = tmp_path / "source.json"
    source_path.write_text("{}\n", encoding="utf-8")
    remote = _remote()
    remote["snapshot"]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    bindings = maskedwarehouse_sample_bindings(_local_inventory())
    bindings[next(iter(bindings))] = "0" * 64
    remote["maskedwarehouse"]["sample_hashes"] = bindings
    evidence = build_evidence(
        pod={"id": "pod", "desiredStatus": "RUNNING"},
        remote=remote,
        source=_source(),
        source_path=source_path,
        local_inventory=_local_inventory(),
    )
    assert evidence["status"] == "RUNTIME_DRIFT"
    assert evidence["checks"]["maskedwarehouse_sample_hashes_match"] is False
