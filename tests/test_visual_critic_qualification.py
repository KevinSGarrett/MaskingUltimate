from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from maskfactory.vlm.critic_catalog import load_catalog
from maskfactory.vlm.critic_qualification import (
    CriticQualificationError,
    evaluate_critic_qualification,
)

ROOT = Path(__file__).resolve().parents[1]


def _corpus() -> dict:
    return json.loads(
        (ROOT / "qa/vlm_eval/visual_critic_calibration_v1/manifest.json").read_text(
            encoding="utf-8"
        )
    )


def _evidence(*, verdict: str = "correct") -> dict:
    corpus = _corpus()
    catalog = load_catalog()
    model = next(model for model in catalog["models"] if model["model_id"] == "qwen3_6_27b_fp8")
    predictions = []
    for index, case in enumerate(corpus["cases"]):
        is_defect = case["expected_outcome"] == "known_defect"
        if verdict == "reject_all":
            predicted_verdict, defect_type = "defect", case["defect_type"] or "boundary"
        else:
            predicted_verdict = "defect" if is_defect else "pass"
            defect_type = case["defect_type"] if is_defect else None
        predictions.append(
            {
                "case_id": case["case_id"],
                "target_contract_sha256": case["target_contract"]["contract_sha256"],
                "panel_set_sha256": case["panel_set_sha256"],
                "verdict": predicted_verdict,
                "defect_type": defect_type,
                "cited_context_tags": [case["context_tags"][0]],
                "schema_valid": True,
                "latency_ms": 1000 + index,
                "peak_vram_bytes": 40_000_000_000,
                "response_sha256": f"{index + 1:064x}",
                "deterministic_replay": True,
            }
        )
    return {
        "schema_version": "1.0.0",
        "role_id": "primary_visual_critic",
        "model_id": model["model_id"],
        "family_id": model["family_id"],
        "revision": model["revision"],
        "quantization": model["quantization"],
        "artifact_tree_sha256": "a" * 64,
        "prompt_sha256": "b" * 64,
        "runtime_sha256": "c" * 64,
        "corpus_sha256": corpus["corpus_sha256"],
        "hardware": {
            "gpu_name": catalog["current_hardware"]["gpu_name"],
            "gpu_count": 1,
            "vram_bytes": catalog["current_hardware"]["vram_bytes_per_gpu"],
        },
        "predictions": predictions,
    }


def test_exact_positive_and_negative_results_pass_measured_gate_without_claiming_authority() -> (
    None
):
    report = evaluate_critic_qualification(_evidence(), _corpus(), load_catalog())
    assert report["status"] == "pass"
    assert report["authority_claimed"] is False
    assert report["metrics"]["valid_mask_pass_rate"] == 1
    assert report["metrics"]["defect_recall"] == 1
    assert report["metrics"]["serious_false_pass_rate"] == 0
    assert len(report["report_sha256"]) == 64


def test_rejecting_everything_is_unavailable_not_qualified() -> None:
    report = evaluate_critic_qualification(
        _evidence(verdict="reject_all"), _corpus(), load_catalog()
    )
    assert report["status"] == "fail"
    assert "valid_mask_pass_rate_below_minimum" in report["failures"]


def test_abstaining_on_everything_is_unavailable_not_a_schema_error() -> None:
    evidence = _evidence()
    for prediction in evidence["predictions"]:
        prediction["verdict"] = "abstain"
        prediction["defect_type"] = None
    report = evaluate_critic_qualification(evidence, _corpus(), load_catalog())
    assert report["status"] == "fail"
    assert report["metrics"]["precision"] == 0
    assert "abstention_rate_above_maximum" in report["failures"]


def test_hallucinated_context_fails_role_qualification() -> None:
    evidence = _evidence()
    evidence["predictions"][0]["cited_context_tags"] = ["multi_person"]
    report = evaluate_critic_qualification(evidence, _corpus(), load_catalog())
    assert report["status"] == "fail"
    assert "context_binding_rate_below_minimum" in report["failures"]


@pytest.mark.parametrize(
    ("field", "value", "failure"),
    [
        ("schema_valid", False, "schema_compliance_rate_below_minimum"),
        ("deterministic_replay", False, "deterministic_replay_rate_below_minimum"),
        ("latency_ms", 6001, "p95_latency_ms_above_maximum"),
        ("peak_vram_bytes", 51_000_000_000, "peak_vram_fraction_above_maximum"),
    ],
)
def test_schema_replay_latency_and_resource_thresholds_fail(
    field: str, value: object, failure: str
) -> None:
    evidence = _evidence()
    for prediction in evidence["predictions"]:
        prediction[field] = value
    report = evaluate_critic_qualification(evidence, _corpus(), load_catalog())
    assert report["status"] == "fail"
    assert failure in report["failures"]


def test_serious_false_pass_fails_even_if_other_defects_are_detected() -> None:
    evidence = _evidence()
    serious = next(row for row in evidence["predictions"] if row["case_id"] == "vc_002_anatomy")
    serious["verdict"] = "pass"
    serious["defect_type"] = None
    report = evaluate_critic_qualification(evidence, _corpus(), load_catalog())
    assert report["status"] == "fail"
    assert "serious_false_pass_rate_above_maximum" in report["failures"]


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value.pop("runtime_sha256"), "fields or schema"),
        (lambda value: value.__setitem__("corpus_sha256", "f" * 64), "corpus hash drifted"),
        (
            lambda value: value["predictions"][0].__setitem__("panel_set_sha256", "f" * 64),
            "panel-set hash drifted",
        ),
    ],
)
def test_unbound_or_incomplete_evidence_is_rejected(mutator, message: str) -> None:
    evidence = deepcopy(_evidence())
    mutator(evidence)
    with pytest.raises(CriticQualificationError, match=message):
        evaluate_critic_qualification(evidence, _corpus(), load_catalog())
