from __future__ import annotations

from pathlib import Path

import pytest

from maskfactory.nude_batch_queue import NudeBatchQueue, NudeBatchQueueError


def _descriptors() -> list[dict[str, object]]:
    return [
        {
            "platform": "runpod",
            "path": f"runpod/lane.{index:04d}.json",
            "lane": "polygon_external_supervision",
            "self_sha256": f"{index:064x}",
            "sample_count": 2,
        }
        for index in (1, 2)
    ]


def _outcome(index: int, *, sample: str, outcome: str = "accepted") -> dict[str, object]:
    return {
        "sample_index": index,
        "sample_id": sample,
        "source_sha256": "a" * 64,
        "evidence_sha256": "b" * 64,
        "outcome": outcome,
        "provider_lineage": ["fixture-provider"],
    }


def test_seed_is_idempotent_and_descriptor_drift_fails(tmp_path: Path) -> None:
    queue = NudeBatchQueue(tmp_path / "queue.sqlite")
    assert queue.seed(_descriptors(), platform="runpod") == {
        "inserted": 2,
        "retained": 0,
        "selected": 2,
    }
    assert queue.seed(_descriptors(), platform="runpod")["retained"] == 2
    drifted = _descriptors()
    drifted[0]["self_sha256"] = "f" * 64
    with pytest.raises(NudeBatchQueueError, match="descriptor drift"):
        queue.seed(drifted, platform="runpod")


def test_claims_are_exclusive_and_checkpoint_resumes_by_index(tmp_path: Path) -> None:
    queue = NudeBatchQueue(tmp_path / "queue.sqlite")
    queue.seed(_descriptors(), platform="runpod")
    first = queue.claim(platform="runpod", owner="worker-a")
    second = queue.claim(platform="runpod", owner="worker-b")
    assert first is not None and second is not None
    assert first["shard_path"] != second["shard_path"]
    checkpoint = queue.checkpoint(
        platform="runpod",
        shard_path=first["shard_path"],
        lease_token=first["lease_token"],
        outcomes=[_outcome(0, sample="sample-a")],
    )
    assert checkpoint == {"inserted": 1, "next_sample_index": 1, "complete": False}
    replay = queue.checkpoint(
        platform="runpod",
        shard_path=first["shard_path"],
        lease_token=first["lease_token"],
        outcomes=[_outcome(0, sample="sample-a")],
    )
    assert replay["idempotent_replay"] is True
    conflict = _outcome(0, sample="sample-a", outcome="rejected")
    with pytest.raises(NudeBatchQueueError, match="idempotency conflict"):
        queue.checkpoint(
            platform="runpod",
            shard_path=first["shard_path"],
            lease_token=first["lease_token"],
            outcomes=[conflict],
        )
    queue.heartbeat(
        platform="runpod",
        shard_path=first["shard_path"],
        lease_token=first["lease_token"],
    )
    done = queue.checkpoint(
        platform="runpod",
        shard_path=first["shard_path"],
        lease_token=first["lease_token"],
        outcomes=[_outcome(1, sample="sample-b", outcome="repaired")],
    )
    assert done["complete"] is True
    assert queue.summary(platform="runpod")["checkpointed_records"] == 2


def test_checkpoint_rejects_gaps_bad_hashes_and_idempotency_conflicts(tmp_path: Path) -> None:
    queue = NudeBatchQueue(tmp_path / "queue.sqlite")
    queue.seed(_descriptors()[:1], platform="runpod")
    lease = queue.claim(platform="runpod", owner="worker")
    assert lease is not None
    with pytest.raises(NudeBatchQueueError, match="contiguous"):
        queue.checkpoint(
            platform="runpod",
            shard_path=lease["shard_path"],
            lease_token=lease["lease_token"],
            outcomes=[_outcome(1, sample="gap")],
        )
    invalid = _outcome(0, sample="bad-hash")
    invalid["evidence_sha256"] = "short"
    with pytest.raises(NudeBatchQueueError, match="hash binding"):
        queue.checkpoint(
            platform="runpod",
            shard_path=lease["shard_path"],
            lease_token=lease["lease_token"],
            outcomes=[invalid],
        )


def test_submitted_unknown_must_reconcile_before_retry(tmp_path: Path) -> None:
    queue = NudeBatchQueue(tmp_path / "queue.sqlite")
    queue.seed(_descriptors()[:1], platform="runpod")
    lease = queue.claim(platform="runpod", owner="worker")
    assert lease is not None
    queue.mark_submitted_unknown(
        platform="runpod",
        shard_path=lease["shard_path"],
        lease_token=lease["lease_token"],
        submission_id="submission-1",
    )
    assert queue.claim(platform="runpod", owner="other") is None
    queue.reconcile_submitted_unknown(
        platform="runpod",
        shard_path=lease["shard_path"],
        submission_id="submission-1",
        observed="not_submitted",
    )
    assert queue.claim(platform="runpod", owner="other") is not None


def test_retry_cap_turns_expired_work_terminal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    now = [1_000.0]
    monkeypatch.setattr("maskfactory.nude_batch_queue.time.time", lambda: now[0])
    queue = NudeBatchQueue(tmp_path / "queue.sqlite", max_attempts=2)
    queue.seed(_descriptors()[:1], platform="runpod")
    assert queue.claim(platform="runpod", owner="one", lease_seconds=1) is not None
    now[0] += 2
    assert queue.claim(platform="runpod", owner="two", lease_seconds=1) is not None
    now[0] += 2
    assert queue.claim(platform="runpod", owner="three", lease_seconds=1) is None
    assert queue.summary(platform="runpod")["states"] == {"failed": 1}
