import copy
from pathlib import Path

import numpy as np
import pytest

from maskfactory.autonomy.risk_buckets import RISK_BUCKET_NAMES
from maskfactory.autonomy.stability import (
    StabilityError,
    evaluate_candidate_stability,
    load_stability_policy,
    verify_stability_evidence,
)
from maskfactory.io.png_strict import write_binary_mask
from maskfactory.ontology import get_ontology
from maskfactory.validation import validate_document


def _fixture(tmp_path: Path, *, label="left_forearm", risk_bucket="large_parts"):
    base = np.zeros((80, 72), dtype=bool)
    base[17:65, 19:53] = True
    base_path = write_binary_mask(tmp_path / "base.png", base)
    ontology_label = get_ontology().label(label)
    variants = []
    for perturbation in ("resize", "crop", "color", "prompt", "horizontal_flip"):
        mask = np.flip(base, axis=1) if perturbation == "horizontal_flip" else base
        path = write_binary_mask(tmp_path / f"{perturbation}.png", mask)
        variants.append(
            {
                "perturbation": perturbation,
                "mask_path": path,
                "reported_label": (
                    ontology_label.swap_partner or label
                    if perturbation == "horizontal_flip"
                    else label
                ),
                "inverse_aligned": perturbation != "horizontal_flip",
            }
        )
    evidence = evaluate_candidate_stability(
        base_path,
        variants,
        candidate_id="fixture-candidate",
        pipeline_fingerprint="pipeline-v1",
        risk_bucket=risk_bucket,
        label=label,
        policy=load_stability_policy(),
    )
    return evidence, base, variants


def test_stability_policy_covers_every_risk_bucket_and_required_perturbation():
    policy = load_stability_policy()
    assert set(policy["risk_bucket_thresholds"]) == RISK_BUCKET_NAMES
    assert set(policy["required_perturbations"]) == {
        "resize",
        "crop",
        "color",
        "prompt",
        "horizontal_flip",
    }
    assert policy["risk_bucket_thresholds"]["out_of_distribution"]["certifiable"] is False


@pytest.mark.parametrize("risk_bucket", sorted(RISK_BUCKET_NAMES - {"out_of_distribution"}))
def test_exactly_stable_candidate_passes_each_certifiable_bucket(tmp_path: Path, risk_bucket: str):
    evidence, _, _ = _fixture(tmp_path, risk_bucket=risk_bucket)
    assert evidence["passed"] is True
    assert not validate_document(evidence, "autonomy_stability")
    verify_stability_evidence(
        evidence,
        pipeline_fingerprint="pipeline-v1",
        risk_bucket=risk_bucket,
        policy=load_stability_policy(),
    )


def test_ood_candidate_abstains_even_when_pixel_stable(tmp_path: Path):
    evidence, _, _ = _fixture(tmp_path, risk_bucket="out_of_distribution")
    assert evidence["passed"] is False
    assert evidence["failures"] == ["risk_bucket_not_certifiable"]


def test_unstable_resize_fails_bucket_thresholds(tmp_path: Path):
    _, base, variants = _fixture(tmp_path / "baseline")
    shifted = np.roll(base, 8, axis=1)
    bad_path = write_binary_mask(tmp_path / "bad_resize.png", shifted)
    changed = [dict(row) for row in variants]
    next(row for row in changed if row["perturbation"] == "resize")["mask_path"] = bad_path
    evidence = evaluate_candidate_stability(
        tmp_path / "baseline/base.png",
        changed,
        candidate_id="unstable-resize",
        pipeline_fingerprint="pipeline-v1",
        risk_bucket="large_parts",
        label="left_forearm",
        policy=load_stability_policy(),
    )
    assert evidence["passed"] is False
    resize = next(row for row in evidence["variants"] if row["perturbation"] == "resize")
    assert "minimum_iou_failed" in resize["failures"]


def test_flip_requires_ontology_swap_partner_and_preinverse_geometry(tmp_path: Path):
    _, _, variants = _fixture(tmp_path / "baseline")
    changed = [dict(row) for row in variants]
    flip = next(row for row in changed if row["perturbation"] == "horizontal_flip")
    flip["reported_label"] = "left_forearm"
    evidence = evaluate_candidate_stability(
        tmp_path / "baseline/base.png",
        changed,
        candidate_id="bad-flip-label",
        pipeline_fingerprint="pipeline-v1",
        risk_bucket="large_parts",
        label="left_forearm",
        policy=load_stability_policy(),
    )
    assert "horizontal_flip:swap_partner_label_mismatch" in evidence["failures"]
    flip["inverse_aligned"] = True
    with pytest.raises(StabilityError, match="before inverse alignment"):
        evaluate_candidate_stability(
            tmp_path / "baseline/base.png",
            changed,
            candidate_id="bad-flip-geometry",
            pipeline_fingerprint="pipeline-v1",
            risk_bucket="large_parts",
            label="left_forearm",
            policy=load_stability_policy(),
        )


def test_tampered_or_wrong_scope_stability_evidence_fails(tmp_path: Path):
    evidence, _, _ = _fixture(tmp_path)
    tampered = copy.deepcopy(evidence)
    tampered["passed"] = False
    with pytest.raises(StabilityError, match="hash mismatch"):
        verify_stability_evidence(
            tampered,
            pipeline_fingerprint="pipeline-v1",
            risk_bucket="large_parts",
            policy=load_stability_policy(),
        )
    with pytest.raises(StabilityError, match="scope mismatch"):
        verify_stability_evidence(
            evidence,
            pipeline_fingerprint="pipeline-v2",
            risk_bucket="large_parts",
            policy=load_stability_policy(),
        )
