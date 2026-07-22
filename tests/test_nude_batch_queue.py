from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from maskfactory.nude_batch_queue import NudeBatchQueue, NudeBatchQueueError
from maskfactory.nude_record_qualification import (
    qualify_input_terminal_record,
    qualify_nonacceptance_record,
    qualify_terminal_record,
    verify_complete_panel_evidence,
)
from maskfactory.providers.disagreement import binary_mask_sha256


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
    if outcome not in {"quarantined", "holdout"}:
        return {
            "sample_index": index,
            "sample_id": sample,
            "source_sha256": "a" * 64,
            "evidence_sha256": "b" * 64,
            "outcome": outcome,
            "provider_lineage": ["fixture-provider"],
        }
    receipt = qualify_input_terminal_record(
        {
            "sample_id": sample,
            "source_sha256": "a" * 64,
            "source_role": (
                "bbox_evaluation_only" if outcome == "holdout" else "polygon_external_supervision"
            ),
            "registry_sha256": "c" * 64,
            "shard_sha256": "d" * 64,
            "outcome": outcome,
            "reasons": ["fixture_terminal_reason"],
            "input_report_sha256": "e" * 64,
            **(
                {"holdout_policy_sha256": "f" * 64, "split_group_id": "holdout-group"}
                if outcome == "holdout"
                else {}
            ),
        }
    )
    receipt["sample_index"] = index
    return receipt


def _qualified_outcome(tmp_path: Path, index: int) -> dict[str, object]:
    source = np.full((48, 48, 3), 40 + index, dtype=np.uint8)
    source[12:36, 14:34] = [180, 130, 100]
    original = tmp_path / f"{index}-original.png"
    Image.fromarray(source).save(original)
    source_sha = hashlib.sha256(original.read_bytes()).hexdigest()
    mask = np.zeros((48, 48), dtype=bool)
    mask[12:36, 14:34] = True
    mask_rgb = np.repeat((mask.astype(np.uint8) * 255)[..., None], 3, axis=2)
    overlay = source.copy()
    overlay[mask] = [120, 20, 20]
    contour = source.copy()
    contours, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(contour, contours, -1, (255, 0, 0), 2)
    ownership_image = Image.fromarray(source.copy())
    ImageDraw.Draw(ownership_image).rectangle((14, 12, 34, 36), outline=(255, 0, 0), width=2)
    arrays = {
        "source": source,
        "mask": mask_rgb,
        "overlay": overlay,
        "contour": contour,
        "ownership": np.asarray(ownership_image),
    }
    panels = {}
    for kind, array in arrays.items():
        path = tmp_path / f"{index}-{kind}.png"
        Image.fromarray(array).save(path)
        panels[kind] = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    panels["source"]["original_source_path"] = str(original)
    bundle = verify_complete_panel_evidence(panels)

    def sha(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    selected = binary_mask_sha256(mask)
    result = qualify_terminal_record(
        {
            "sample_id": f"qualified-{index}",
            "source_sha256": source_sha,
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
    panels = {kind: dict(value) for kind, value in evidence["panel_evidence"]["panels"].items()}
    panels["source"]["original_source_path"] = evidence["pixel_semantic_visual_evidence"][
        "original_source_path"
    ]
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
        panels=panels,
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
    with pytest.raises(ValueError, match="evidence_sha256_mismatch"):
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


def test_holdout_receipt_is_evaluation_only_and_training_ineligible(tmp_path: Path) -> None:
    queue = NudeBatchQueue(tmp_path / "queue.sqlite")
    queue.seed(_descriptors()[:1], platform="runpod")
    lease = queue.claim(platform="runpod", owner="holdout-worker")
    assert lease is not None
    payload = _outcome(0, sample="holdout-sample", outcome="holdout")
    evidence = payload["qualification_evidence"]
    assert evidence["evaluation_only"] is True
    assert evidence["training_authority"] is False
    queue.checkpoint(
        platform="runpod",
        shard_path=lease["shard_path"],
        lease_token=lease["lease_token"],
        outcomes=[payload],
    )
