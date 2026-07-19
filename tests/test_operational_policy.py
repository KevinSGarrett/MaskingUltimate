from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import numpy as np
import pytest

from maskfactory.authority import (
    OperationalPolicyError,
    evaluate_operational_policy,
    load_operational_policy,
    prepare_operational_policy_replay,
    verify_operational_policy_report,
)
from maskfactory.autonomy.risk_buckets import canonical_sha256
from maskfactory.autonomy.stability import evaluate_candidate_stability, load_stability_policy
from maskfactory.io.png_strict import write_binary_mask
from maskfactory.ontology import get_ontology
from maskfactory.validation import validate_document

EVALUATOR_ID = "maskfactory.operational_policy.v1"
EVALUATOR_SHA256 = hashlib.sha256(b"operational-policy-test-executor").hexdigest()


def _mask_fixture(tmp_path: Path, *, label: str = "left_hand") -> tuple[Path, np.ndarray]:
    mask = np.zeros((80, 72), dtype=bool)
    mask[17:65, 19:53] = True
    return write_binary_mask(tmp_path / "base.png", mask), mask


def _stability_evidence(
    tmp_path: Path,
    scope: dict,
    *,
    unstable: bool = False,
    side_inconsistent: bool = False,
) -> tuple[dict, list[dict]]:
    base_path, base = _mask_fixture(tmp_path)
    label = scope["label"]
    swap = get_ontology().label(label).swap_partner or label
    variants = []
    for perturbation in ("resize", "crop", "color", "prompt", "horizontal_flip"):
        mask = np.flip(base, axis=1) if perturbation == "horizontal_flip" else base
        if unstable and perturbation == "resize":
            mask = np.roll(mask, 8, axis=1)
        path = write_binary_mask(tmp_path / f"{perturbation}.png", mask)
        variants.append(
            {
                "perturbation": perturbation,
                "mask_path": path,
                "reported_label": (
                    label
                    if side_inconsistent and perturbation == "horizontal_flip"
                    else swap if perturbation == "horizontal_flip" else label
                ),
                "inverse_aligned": perturbation != "horizontal_flip",
            }
        )
    return (
        evaluate_candidate_stability(
            base_path,
            variants,
            candidate_id=scope["candidate_id"],
            pipeline_fingerprint=scope["pipeline_fingerprint"],
            risk_bucket=scope["risk_bucket"],
            label=label,
            policy=load_stability_policy(),
        ),
        variants,
    )


def _synthetic_cases(tmp_path: Path, *, label: str = "left_hand") -> list[dict]:
    truth = np.zeros((48, 48), dtype=bool)
    truth[12:36, 14:34] = True
    truth_path = write_binary_mask(tmp_path / "truth.png", truth)
    shifted = np.roll(truth, 3, axis=1)
    missing = truth.copy()
    missing[28:36, :] = False
    candidates = {
        "exact_truth": write_binary_mask(tmp_path / "exact.png", truth),
        "boundary_shift": write_binary_mask(tmp_path / "shifted.png", shifted),
        "missing_area": write_binary_mask(tmp_path / "missing.png", missing),
        "side_inconsistency": write_binary_mask(tmp_path / "side.png", truth),
    }
    swap = get_ontology().label(label).swap_partner or label
    return [
        {
            "case_id": f"synthetic-{kind}",
            "case_kind": kind,
            "truth_mask_path": truth_path,
            "candidate_mask_path": candidates[kind],
            "expected_label": label,
            "reported_label": swap if kind == "side_inconsistency" else label,
        }
        for kind in ("exact_truth", "boundary_shift", "missing_area", "side_inconsistency")
    ]


def _scope() -> dict:
    return {
        "candidate_id": "operational-candidate-1",
        "source_decoded_pixel_sha256": hashlib.sha256(b"source-pixels").hexdigest(),
        "output_artifact_identity_sha256s": [hashlib.sha256(b"output-mask").hexdigest()],
        "pipeline_fingerprint": hashlib.sha256(b"pipeline-stack").hexdigest(),
        "risk_bucket": "large_parts",
        "label": "left_hand",
        "seed": 1337,
    }


def _report(
    tmp_path: Path,
    *,
    unstable: bool = False,
    side_inconsistent: bool = False,
    mutate_second_replay: bool = False,
) -> dict:
    policy = load_operational_policy()
    stability_policy = load_stability_policy()
    scope = _scope()
    stability, _ = _stability_evidence(
        tmp_path / "stability",
        scope,
        unstable=unstable,
        side_inconsistent=side_inconsistent,
    )
    synthetic = _synthetic_cases(tmp_path / "synthetic")
    replay = list(
        prepare_operational_policy_replay(
            stability,
            synthetic,
            candidate_scope=scope,
            policy=policy,
            stability_policy=stability_policy,
        )
    )
    if mutate_second_replay:
        replay[1] = copy.deepcopy(replay[1])
        replay[1]["decision"]["output_artifact_identity_sha256s"] = [
            hashlib.sha256(b"nondeterministic-output").hexdigest()
        ]
        replay[1]["decision_sha256"] = canonical_sha256(replay[1]["decision"])
    return evaluate_operational_policy(
        stability,
        synthetic,
        replay,
        report_id="operational-policy-fixture",
        candidate_scope=scope,
        policy=policy,
        stability_policy=stability_policy,
        evaluator_id=EVALUATOR_ID,
        evaluator_sha256=EVALUATOR_SHA256,
    )


def test_stable_exact_truth_and_seeded_defects_pass_with_identical_replay(
    tmp_path: Path,
) -> None:
    first = _report(tmp_path / "first")
    second = _report(tmp_path / "second")
    assert first == second
    assert first["decision"]["status"] == "pass"
    assert first["decision"]["may_issue_certificate"] is True
    assert first["synthetic_truth"]["passed"] is True
    assert {row["case_kind"] for row in first["synthetic_truth"]["cases"]} == {
        "exact_truth",
        "boundary_shift",
        "missing_area",
        "side_inconsistency",
    }
    assert first["replay"]["reproducible"] is True
    assert not validate_document(first, "operational_policy_evidence")
    verify_operational_policy_report(first)


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"unstable": True}, "perturbation_instability"),
        ({"side_inconsistent": True}, "side_inconsistency"),
        ({"mutate_second_replay": True}, "deterministic_replay_mismatch"),
    ],
)
def test_unstable_side_inconsistent_or_nonreproducible_output_abstains(
    tmp_path: Path, kwargs: dict, code: str
) -> None:
    report = _report(tmp_path, **kwargs)
    assert report["decision"]["status"] == "autonomous_abstention"
    assert report["decision"]["may_issue_certificate"] is False
    assert code in report["decision"]["abstention_codes"]


def test_missing_synthetic_truth_coverage_and_tampered_report_fail_closed(tmp_path: Path) -> None:
    policy = load_operational_policy()
    stability_policy = load_stability_policy()
    scope = _scope()
    stability, _ = _stability_evidence(tmp_path / "stability", scope)
    synthetic = _synthetic_cases(tmp_path / "synthetic")[:-1]
    with pytest.raises(OperationalPolicyError, match="exactly four"):
        prepare_operational_policy_replay(
            stability,
            synthetic,
            candidate_scope=scope,
            policy=policy,
            stability_policy=stability_policy,
        )

    report = _report(tmp_path / "tamper")
    report["decision"]["may_issue_certificate"] = False
    with pytest.raises(OperationalPolicyError, match="hash mismatch"):
        verify_operational_policy_report(report)


def test_policy_rejects_nonfrozen_seed_or_incomplete_gate_set(tmp_path: Path) -> None:
    policy = load_operational_policy()
    assert policy["fixed_seed"] == 1337
    assert set(policy["required_gate_ids"]) == {
        "perturbation",
        "metamorphic",
        "stability_replay",
    }
    scope = _scope()
    scope["seed"] = 42
    stability, _ = _stability_evidence(tmp_path / "stability", scope)
    synthetic = _synthetic_cases(tmp_path / "synthetic")
    with pytest.raises(OperationalPolicyError, match="frozen seed"):
        prepare_operational_policy_replay(
            stability,
            synthetic,
            candidate_scope=scope,
            policy=policy,
            stability_policy=load_stability_policy(),
        )
