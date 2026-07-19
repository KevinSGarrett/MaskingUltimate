from __future__ import annotations

import copy

import pytest

from maskfactory.external_supervision import EXTERNAL_LABEL_ROLE
from maskfactory.external_supervision_holdout_ablation import (
    ExternalHoldoutAblationError,
    assert_only_ablation_active_external_rows,
    decide_active_external_supervision,
    evaluate_source_label_ablation,
    filter_active_selections,
    require_frozen_human_anchor_holdout,
)
from maskfactory.external_supervision_packages import (
    ExternalSupervisionPackageError,
    assert_builder_accepts_only_gated_external_rows,
)

FINGERPRINT = "a" * 64


def _holdout() -> dict:
    return {
        "frozen_holdout_id": "human_anchor_holdout_fixture_v1",
        "fingerprint_sha256": FINGERPRINT,
        "truth_tier": "human_anchor_gold",
        "truth_partition": "holdout",
        "source_role": "owned_photo",
        "external_labels_may_enter_holdout": False,
    }


def _passing_buckets() -> dict:
    return {
        name: {"passed": True, "observed_delta": 0.0, "noninferiority_margin": 0.01}
        for name in ("hard_bucket", "identity", "boundary", "calibration")
    }


def _row(
    *,
    source: str = "lapa",
    labels: list[str] | None = None,
    delta: float = 0.02,
    margin: float = 0.01,
    buckets: dict | None = None,
) -> dict:
    return {
        "source": source,
        "label_scope": labels or ["head_face", "hair"],
        "primary_metric": "miou",
        "observed_delta": delta,
        "noninferiority_margin": margin,
        "frozen_holdout_fingerprint_sha256": FINGERPRINT,
        "truth_tier": "weighted_pseudo_label",
        "counts_as_human_anchor_gold": False,
        "regression_buckets": buckets if buckets is not None else _passing_buckets(),
    }


def test_frozen_holdout_required_and_rejects_external_authority() -> None:
    require_frozen_human_anchor_holdout(_holdout())
    with pytest.raises(ExternalHoldoutAblationError, match="human_anchor_gold"):
        require_frozen_human_anchor_holdout({**_holdout(), "truth_tier": "weighted_pseudo_label"})
    with pytest.raises(ExternalHoldoutAblationError, match="external or synthetic"):
        require_frozen_human_anchor_holdout(
            {**_holdout(), "source_role": EXTERNAL_LABEL_ROLE}
        )


def test_non_regressing_source_label_remains_active() -> None:
    decision = evaluate_source_label_ablation(_row(), holdout=_holdout())
    assert decision.active is True
    report = decide_active_external_supervision(holdout=_holdout(), ablations=[_row()])
    assert report["active_count"] == 1
    assert report["inactive_count"] == 0
    assert report["live_holdout_executed"] is False
    assert report["admission_ready"] is False
    assert report["proof_tier"] == "STATIC_PASS"


def test_primary_and_bucket_regressions_deactivate() -> None:
    primary_fail = evaluate_source_label_ablation(
        _row(delta=-0.05, margin=0.01), holdout=_holdout()
    )
    assert primary_fail.active is False
    assert "primary metric" in primary_fail.reason

    buckets = _passing_buckets()
    buckets["identity"] = {
        "passed": False,
        "observed_delta": -0.2,
        "noninferiority_margin": 0.01,
    }
    identity_fail = evaluate_source_label_ablation(
        _row(buckets=buckets), holdout=_holdout()
    )
    assert identity_fail.active is False
    assert "identity" in identity_fail.reason

    report = decide_active_external_supervision(
        holdout=_holdout(),
        ablations=[
            _row(source="lapa", labels=["head_face", "hair"], delta=0.01),
            _row(source="lv_mhp", labels=["coarse_limb_region"], delta=-0.2),
        ],
    )
    assert report["active_count"] == 1
    assert report["inactive_count"] == 1
    assert report["inactive_source_label_scopes"][0]["source"] == "lv_mhp"


def test_builder_refuses_ablation_active_without_report() -> None:
    rows = [
        {
            "image_id": "ext_1",
            "source_role": EXTERNAL_LABEL_ROLE,
            "truth_tier": "weighted_pseudo_label",
            "truth_partition": "train",
            "external_qualification_admitted": True,
            "dataset_volume_eligible": False,
            "training_loss_weight": 0.15,
            "external_source": "lapa",
            "label_names": ["head_face", "hair"],
            "ablation_active": True,
        }
    ]
    with pytest.raises(ExternalSupervisionPackageError, match="without sealed"):
        assert_builder_accepts_only_gated_external_rows(rows)


def test_builder_accepts_only_active_scopes_from_report() -> None:
    report = decide_active_external_supervision(
        holdout=_holdout(),
        ablations=[_row(source="lapa", labels=["head_face", "hair"])],
    )
    active_row = {
        "image_id": "ext_1",
        "source_role": EXTERNAL_LABEL_ROLE,
        "truth_tier": "weighted_pseudo_label",
        "truth_partition": "train",
        "external_qualification_admitted": True,
        "dataset_volume_eligible": False,
        "training_loss_weight": 0.15,
        "external_source": "lapa",
        "label_names": ["head_face", "hair"],
        "ablation_active": True,
    }
    assert_builder_accepts_only_gated_external_rows([active_row], ablation_report=report)

    inactive_claim = copy.deepcopy(active_row)
    inactive_claim["external_source"] = "lv_mhp"
    inactive_claim["label_names"] = ["coarse_limb_region"]
    with pytest.raises(ExternalSupervisionPackageError, match="ablation-inactive"):
        assert_builder_accepts_only_gated_external_rows(
            [inactive_claim], ablation_report=report
        )


def test_filter_active_selections_and_assert_helpers() -> None:
    report = decide_active_external_supervision(
        holdout=_holdout(),
        ablations=[
            _row(source="lapa", labels=["head_face", "hair"]),
            _row(source="celebamask_hq", labels=["head_face"], delta=-0.5),
        ],
    )
    kept = filter_active_selections(
        [
            {"source": "lapa", "label_names": ["hair", "head_face"]},
            {"source": "celebamask_hq", "label_names": ["head_face"]},
        ],
        report,
    )
    assert len(kept) == 1
    assert kept[0]["source"] == "lapa"

    assert_only_ablation_active_external_rows(
        [
            {
                "source_role": EXTERNAL_LABEL_ROLE,
                "external_source": "lapa",
                "label_names": ["head_face", "hair"],
                "ablation_active": True,
            }
        ],
        report,
    )
