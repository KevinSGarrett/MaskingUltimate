import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from maskfactory.autonomy.calibration import load_autonomy_config
from maskfactory.autonomy.lifecycle import certificate_stratum_is_revoked
from maskfactory.autonomy.operations import (
    build_multi_person_audit_queue,
    process_multi_person_audit_outcomes,
)
from maskfactory.autonomy.pseudo_dataset import build_weighted_pseudo_manifest
from maskfactory.io.hashing import sha256_file
from maskfactory.io.png_strict import write_binary_mask
from maskfactory.serve.routing import build_certificate_aware_serving_route


def _record(image: int, instance: int, *, bucket: str, priority: float) -> dict:
    return {
        "record_id": f"r-{image}-{instance}",
        "image_id": f"img_{image:012x}",
        "instance_id": f"p{instance}",
        "label": "hair",
        "context": "duo",
        "pipeline_fingerprint": "pipeline-v1",
        "risk_bucket": bucket,
        "risk_priority": priority,
    }


def _certificate(bucket: str = "contact") -> dict:
    document = {
        "schema_version": "2.0.0",
        "audit_authority": "human_anchor_gold",
        "passed": True,
        "risk_bucket": bucket,
        "instance_context": "duo",
        "covered_labels": ["hair"],
        "covered_contexts": ["duo"],
        "pipeline_fingerprint": "pipeline-v1",
        "expires_at": "2026-08-14T00:00:00Z",
    }
    document["sha256"] = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return document


def _lifecycle() -> dict:
    return {
        "schema_version": "2.0.0",
        "image_id": "img_000000000000",
        "instance_id": "p0",
        "label": "hair",
        "context": "duo",
        "pipeline_fingerprint": "pipeline-v1",
        "status": "calibrated_auto_accepted",
        "truth_tier": "autonomous_certified_gold",
        "training_loss_weight": 0.65,
        "holdout_eligible": False,
        "winner_id": "candidate",
        "winner_mask_path": "mask.png",
        "winner_mask_sha256": "a" * 64,
        "winner_score": 0.99,
        "certificate_valid": True,
        "certificate_reason": "certificate_valid",
        "human_audit_required": False,
        "authoritative_human_gold": False,
        "serve_eligible": True,
        "pseudo_train_eligible": True,
        "reason": "fixture",
        "ranking": [
            {
                "candidate_id": "candidate",
                "score": 0.99,
                "eligible": True,
                "vetoes": [],
                "mask_sha256": "a" * 64,
            }
        ],
    }


def test_mixed_multi_person_audit_selects_complete_images_and_risk_buckets(tmp_path: Path) -> None:
    config = load_autonomy_config()
    records = tuple(
        _record(
            image,
            instance,
            bucket="contact" if image < 5 else "occlusion",
            priority=0.9 if image >= 5 else 0.2,
        )
        for image in range(10)
        for instance in range(2)
    )
    queue = build_multi_person_audit_queue(
        records,
        tmp_path / "queue.json",
        period_id="2026-W29",
        operations_policy=config["operations"],
    )
    selected = set(queue["selected_image_ids"])
    assert set(queue["random_image_ids"]) <= selected
    assert set(queue["risk_image_ids"]) <= selected
    assert {row["image_id"] for row in queue["records"]} == selected
    assert all(
        {row["instance_id"] for row in queue["records"] if row["image_id"] == image_id}
        == {"p0", "p1"}
        for image_id in selected
    )


@pytest.mark.parametrize("failure_kind", ["cross_person_bleed", "identity", "contact", "occlusion"])
def test_serious_multi_person_failure_revokes_exact_stratum_immediately(
    tmp_path: Path, failure_kind: str
) -> None:
    config = load_autonomy_config()
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "records": [
                    _record(0, 0, bucket="contact", priority=1.0),
                    _record(0, 1, bucket="contact", priority=1.0),
                ],
            }
        ),
        encoding="utf-8",
    )
    outcomes_path = tmp_path / "outcomes.json"
    outcomes_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "records": [
                    {
                        "image_id": "img_000000000000",
                        "human_defect": True,
                        "serious_defect": True,
                        "distribution_drift": False,
                        "failure_kind": failure_kind,
                        "corrected_gold_sha256": "b" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    revocations = tmp_path / "revocations"
    result = process_multi_person_audit_outcomes(
        queue_path,
        outcomes_path,
        revocations_root=revocations,
        retraining_policy=config["retraining"],
        operations_policy=config["operations"],
        retraining_output_path=tmp_path / "retraining.json",
    )
    assert result["serving_and_certified_training_eligibility_removed"] is True
    assert certificate_stratum_is_revoked(
        revocations,
        risk_bucket="contact",
        instance_context="duo",
        pipeline_fingerprint="pipeline-v1",
    )
    assert not certificate_stratum_is_revoked(
        revocations,
        risk_bucket="occlusion",
        instance_context="duo",
        pipeline_fingerprint="pipeline-v1",
    )
    route = build_certificate_aware_serving_route(
        _lifecycle(),
        _certificate(),
        expected_pipeline_fingerprint="pipeline-v1",
        selected_for_audit=False,
        revocations_root=revocations,
        now=datetime(2026, 7, 14, 12, tzinfo=UTC),
    )
    assert route["serving_status"] == "withheld_for_residual_review"
    assert route["routing"]["residual_reason"] == ("certificate_multi_person_stratum_revoked")

    lifecycle_root = tmp_path / "lifecycle"
    lifecycle_root.mkdir()
    mask = np.zeros((12, 12), dtype=bool)
    mask[2:10, 3:9] = True
    mask_path = write_binary_mask(tmp_path / "mask.png", mask)
    lifecycle = _lifecycle()
    lifecycle["winner_mask_path"] = "mask.png"
    lifecycle["winner_mask_sha256"] = sha256_file(mask_path)
    lifecycle["ranking"][0]["mask_sha256"] = sha256_file(mask_path)
    (lifecycle_root / "hair.json").write_text(json.dumps(lifecycle), encoding="utf-8")
    certificate_root = tmp_path / "certificates"
    certificate_root.mkdir()
    (certificate_root / "hair__duo.json").write_text(json.dumps(_certificate()), encoding="utf-8")
    protected = tmp_path / "protected.txt"
    protected.write_text("", encoding="utf-8")
    manifest = build_weighted_pseudo_manifest(
        lifecycle_root,
        tmp_path / "training.json",
        certificate_root=certificate_root,
        revocations_root=revocations,
        protected_anchor_ids_path=protected,
        operations_policy=config["operations"],
    )
    assert manifest["record_count"] == 0
