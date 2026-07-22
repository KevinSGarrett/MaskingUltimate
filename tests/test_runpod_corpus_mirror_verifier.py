import hashlib
from pathlib import Path

from tools.verify_runpod_corpus_mirrors import (
    MASKEDWAREHOUSE_ROOT,
    REFERENCE_ROOT,
    REMOTE_SNAPSHOT,
    build_evidence,
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
