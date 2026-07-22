from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from maskfactory.nude_batch_queue import NudeBatchQueue, NudeBatchQueueError
from maskfactory.nude_record_qualification import (
    qualify_nonacceptance_record,
    qualify_terminal_record,
    verify_complete_panel_evidence,
)


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


def _outcome(index: int, *, sample: str, outcome: str = "quarantined") -> dict[str, object]:
    return {
        "sample_index": index,
        "sample_id": sample,
        "source_sha256": "a" * 64,
        "evidence_sha256": "b" * 64,
        "outcome": outcome,
        "provider_lineage": ["fixture-provider"],
    }


def _qualified_outcome(tmp_path: Path, index: int) -> dict[str, object]:
    panels = {}
    for kind in ("source", "mask", "overlay", "contour", "ownership"):
        path = tmp_path / f"{index}-{kind}.png"
        path.write_bytes(f"{index}:{kind}".encode())
        panels[kind] = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    bundle = verify_complete_panel_evidence(panels)

    def sha(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    selected = sha(f"selected-{index}")
    result = qualify_terminal_record(
        {
            "sample_id": f"qualified-{index}",
            "source_sha256": sha(f"source-{index}"),
            "mask_sha256": selected,
            "outcome": "accepted",
            "provider_comparison": {
                "status": "pass",
                "selected_mask_sha256": selected,
                "report_sha256": sha("comparison"),
                "candidates": [
                    {
                        "provider_id": "one",
                        "family_id": "family-one",
                        "revision": "r1",
                        "artifact_sha256": sha("artifact-one"),
                        "mask_sha256": selected,
                    },
                    {
                        "provider_id": "two",
                        "family_id": "family-two",
                        "revision": "r2",
                        "artifact_sha256": sha("artifact-two"),
                        "mask_sha256": sha("other"),
                    },
                ],
            },
            "hard_qc": {
                "status": "pass",
                "mask_sha256": selected,
                "policy_sha256": sha("hard-policy"),
                "report_sha256": sha("hard-report"),
            },
            "strict_reviews": [
                {
                    "role": role,
                    "model_id": family,
                    "family_id": family,
                    "revision": "r1",
                    "certificate_sha256": sha(f"cert-{family}"),
                    "prompt_sha256": sha("prompt"),
                    "mask_sha256": selected,
                    "panel_bundle_sha256": bundle["panel_bundle_sha256"],
                    "verdict": "pass",
                    "confidence": 0.9,
                    "evidence": "Boundary, target ownership, and background exclusion agree.",
                }
                for role, family in (
                    ("primary_visual_critic", "critic-one"),
                    ("independent_juror", "critic-two"),
                )
            ],
        },
        panels=panels,
    )
    result["sample_index"] = index
    return result


def _abstained_outcome(tmp_path: Path, index: int) -> dict[str, object]:
    accepted = _qualified_outcome(tmp_path, index)
    evidence = accepted["qualification_evidence"]
    reviews = [dict(review) for review in evidence["strict_reviews"]]
    reviews[0]["verdict"] = "uncertain"
    result = qualify_nonacceptance_record(
        {
            "sample_id": accepted["sample_id"],
            "source_sha256": accepted["source_sha256"],
            "mask_sha256": accepted["mask_sha256"],
            "outcome": "abstained",
            "failure_stage": "strict_review",
            "reasons": ["primary_review_uncertain"],
            "provider_comparison": evidence["provider_comparison"],
            "hard_qc": evidence["hard_qc"],
            "strict_reviews": reviews,
        },
        panels=evidence["panel_evidence"]["panels"],
    )
    result["sample_index"] = index
    return result


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
        outcomes=[_outcome(1, sample="sample-b", outcome="quarantined")],
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


def test_qualified_checkpoint_revalidates_receipt_before_mutation(tmp_path: Path) -> None:
    queue = NudeBatchQueue(tmp_path / "queue.sqlite")
    queue.seed(_descriptors()[:1], platform="runpod")
    lease = queue.claim(platform="runpod", owner="qualified-worker")
    assert lease is not None
    payload = _qualified_outcome(tmp_path, 0)
    result = queue.checkpoint_qualified(
        platform="runpod",
        shard_path=lease["shard_path"],
        lease_token=lease["lease_token"],
        outcomes=[payload],
    )
    assert result["next_sample_index"] == 1
    tampered = _qualified_outcome(tmp_path, 1)
    tampered["qualification_evidence"]["production_mask_authority"] = True
    with pytest.raises(ValueError, match="evidence_hash_mismatch"):
        queue.checkpoint_qualified(
            platform="runpod",
            shard_path=lease["shard_path"],
            lease_token=lease["lease_token"],
            outcomes=[tampered],
        )


def test_low_level_checkpoint_cannot_bypass_accepted_receipt_gate(tmp_path: Path) -> None:
    queue = NudeBatchQueue(tmp_path / "queue.sqlite")
    queue.seed(_descriptors()[:1], platform="runpod")
    lease = queue.claim(platform="runpod", owner="bypass-attempt")
    assert lease is not None
    unsafe = _outcome(0, sample="unsafe", outcome="accepted")
    with pytest.raises(ValueError, match="qualification_evidence_required"):
        queue.checkpoint(
            platform="runpod",
            shard_path=lease["shard_path"],
            lease_token=lease["lease_token"],
            outcomes=[unsafe],
        )


def test_low_level_checkpoint_accepts_valid_abstention_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    queue = NudeBatchQueue(tmp_path / "queue.sqlite")
    queue.seed(_descriptors()[:1], platform="runpod")
    lease = queue.claim(platform="runpod", owner="failure-receipt")
    assert lease is not None
    payload = _abstained_outcome(tmp_path, 0)
    result = queue.checkpoint(
        platform="runpod",
        shard_path=lease["shard_path"],
        lease_token=lease["lease_token"],
        outcomes=[payload],
    )
    assert result["next_sample_index"] == 1
    tampered = _abstained_outcome(tmp_path, 1)
    tampered["qualification_evidence"]["authority"] = "machine_verified_candidate"
    with pytest.raises(ValueError, match="nonacceptance_evidence_drift"):
        queue.checkpoint(
            platform="runpod",
            shard_path=lease["shard_path"],
            lease_token=lease["lease_token"],
            outcomes=[tampered],
        )
