import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from maskfactory.autonomy.lifecycle import revocation_marker_path
from maskfactory.serve.routing import (
    build_certificate_aware_serving_route,
    build_multi_person_image_routes,
)
from maskfactory.validation import validate_document


def _certificate() -> dict:
    document = {
        "schema_version": "2.0.0",
        "audit_authority": "human_anchor_gold",
        "passed": True,
        "risk_bucket": "hands",
        "covered_labels": ["left_hand_base"],
        "covered_contexts": ["solo"],
        "pipeline_fingerprint": "pipeline-v1",
        "issued_at": "2026-07-14T00:00:00Z",
        "expires_at": "2026-08-14T00:00:00Z",
    }
    document["sha256"] = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return document


def _lifecycle(*, status: str = "calibrated_auto_accepted") -> dict:
    certified = status == "calibrated_auto_accepted"
    return {
        "schema_version": "2.0.0",
        "image_id": "img_012345abcdef",
        "instance_id": "p0",
        "label": "left_hand_base",
        "context": "solo",
        "pipeline_fingerprint": "pipeline-v1",
        "status": status,
        "truth_tier": "autonomous_certified_gold" if certified else "machine_candidate",
        "training_loss_weight": 0.65 if certified else 0.0,
        "holdout_eligible": False,
        "winner_id": "candidate-1",
        "winner_mask_path": "masks/left_hand_base.png",
        "winner_mask_sha256": "a" * 64,
        "winner_score": 0.95,
        "certificate_valid": certified,
        "certificate_reason": "certificate_valid" if certified else "not_certified",
        "human_audit_required": not certified,
        "authoritative_human_gold": False,
        "serve_eligible": certified,
        "pseudo_train_eligible": certified,
        "reason": "fixture",
        "ranking": [
            {
                "candidate_id": "candidate-1",
                "score": 0.95,
                "eligible": True,
                "vetoes": [],
                "mask_sha256": "a" * 64,
            }
        ],
    }


def _route(tmp_path: Path, lifecycle: dict, certificate: dict, **overrides) -> dict:
    return build_certificate_aware_serving_route(
        lifecycle,
        certificate,
        expected_pipeline_fingerprint=overrides.get("expected_pipeline_fingerprint", "pipeline-v1"),
        selected_for_audit=overrides.get("selected_for_audit", False),
        revocations_root=tmp_path / "revocations",
        now=datetime(2026, 7, 14, 12, tzinfo=UTC),
    )


def test_current_certificate_routes_without_routine_review_but_never_as_human_gold(
    tmp_path: Path,
) -> None:
    route = _route(tmp_path, _lifecycle(), _certificate())
    assert validate_document(route, "serving_route") == ()
    assert route["serving_status"] == "certified_output"
    assert route["truth_tier"] == "autonomous_certified_gold"
    assert route["authoritative_human_gold"] is False
    assert route["certificate"]["scope"] == {
        "risk_bucket": "hands",
        "covered_labels": ["left_hand_base"],
        "covered_contexts": ["solo"],
        "pipeline_fingerprint": "pipeline-v1",
    }
    assert route["routing"] == {
        "destination": "served_without_routine_review",
        "residual_reason": None,
        "audit_reason": None,
    }


def test_preselected_audit_is_withheld_to_cvat_without_downgrading_history(
    tmp_path: Path,
) -> None:
    route = _route(tmp_path, _lifecycle(), _certificate(), selected_for_audit=True)
    assert route["serving_status"] == "withheld_for_preselected_audit"
    assert route["truth_tier"] == "autonomous_certified_gold"
    assert route["routing"]["destination"] == "cvat_preselected_audit"
    assert route["routing"]["audit_reason"] == "preselected_random_or_risk_audit"


def test_stale_tampered_revoked_and_residual_cases_cannot_emit_certified_metadata(
    tmp_path: Path,
) -> None:
    stale = _route(
        tmp_path,
        _lifecycle(),
        _certificate(),
        expected_pipeline_fingerprint="pipeline-v2",
    )
    assert stale["truth_tier"] == "machine_candidate"
    assert stale["routing"]["residual_reason"] == ("lifecycle_pipeline_fingerprint_mismatch")

    tampered_certificate = copy.deepcopy(_certificate())
    tampered_certificate["covered_labels"].append("right_hand_base")
    tampered = _route(tmp_path, _lifecycle(), tampered_certificate)
    assert tampered["certificate"]["status"] == "invalid"
    assert tampered["routing"]["residual_reason"] == "certificate_hash_mismatch"

    marker = revocation_marker_path(
        tmp_path / "revocations",
        label="left_hand_base",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
    )
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"pipeline_fingerprint": "pipeline-v1"}), encoding="utf-8")
    revoked = _route(tmp_path, _lifecycle(), _certificate())
    assert revoked["routing"]["residual_reason"] == "certificate_scope_revoked"

    marker.unlink()
    residual = _route(
        tmp_path,
        _lifecycle(status="residual_human_queue"),
        _certificate(),
    )
    assert residual["serving_status"] == "withheld_for_residual_review"
    assert residual["truth_tier"] == "machine_candidate"
    assert residual["authoritative_human_gold"] is False
    assert residual["routing"]["destination"] == "cvat_residual_review"


def _multi_certificate(instance_id: str) -> dict:
    document = _certificate()
    document.update(
        {
            "risk_bucket": "contact",
            "instance_context": "duo",
            "covered_contexts": ["duo"],
        }
    )
    document["sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in document.items() if key != "sha256"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return document


def _multi_lifecycle(instance_id: str, *, certified: bool = True) -> dict:
    document = _lifecycle(
        status="calibrated_auto_accepted" if certified else "residual_human_queue"
    )
    document["instance_id"] = instance_id
    document["context"] = "duo"
    return document


def test_multi_person_image_routes_only_residual_or_preselected_audits_to_cvat(
    tmp_path: Path,
) -> None:
    lifecycles = {"p0": _multi_lifecycle("p0"), "p1": _multi_lifecycle("p1")}
    certificates = {"p0": _multi_certificate("p0"), "p1": _multi_certificate("p1")}
    automatic = build_multi_person_image_routes(
        lifecycles,
        certificates,
        expected_pipeline_fingerprint="pipeline-v1",
        selected_for_audit=False,
        revocations_root=tmp_path / "revocations",
        now=datetime(2026, 7, 14, 12, tzinfo=UTC),
    )
    assert automatic["cvat_instance_ids"] == []
    assert automatic["truth_partition"] == "train"
    assert {route["routing"]["destination"] for route in automatic["routes"].values()} == {
        "served_without_routine_review"
    }

    audited = build_multi_person_image_routes(
        lifecycles,
        certificates,
        expected_pipeline_fingerprint="pipeline-v1",
        selected_for_audit=True,
        revocations_root=tmp_path / "revocations",
        now=datetime(2026, 7, 14, 12, tzinfo=UTC),
    )
    assert audited["audit_instance_ids"] == ["p0", "p1"]
    assert audited["cvat_instance_ids"] == ["p0", "p1"]
    assert audited["residual_instance_ids"] == []


def test_multi_person_residual_route_never_splits_image_truth_partition(tmp_path: Path) -> None:
    lifecycles = {
        "p0": _multi_lifecycle("p0"),
        "p1": _multi_lifecycle("p1", certified=False),
    }
    certificates = {"p0": _multi_certificate("p0"), "p1": _multi_certificate("p1")}
    result = build_multi_person_image_routes(
        lifecycles,
        certificates,
        expected_pipeline_fingerprint="pipeline-v1",
        selected_for_audit=False,
        revocations_root=tmp_path / "revocations",
        now=datetime(2026, 7, 14, 12, tzinfo=UTC),
    )
    assert result["cvat_instance_ids"] == ["p1"]
    assert result["truth_partition"] == "residual"
    assert set(result["instance_truth_partitions"].values()) == {"residual"}
    assert result["routes"]["p0"]["routing"]["destination"] == ("served_without_routine_review")
