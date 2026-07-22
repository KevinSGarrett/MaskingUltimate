from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from maskfactory.vlm.critic_catalog import load_catalog
from maskfactory.vlm.live_calibration import (
    CHECK_KEYS,
    PROMPT_SHA256,
    LiveCalibrationError,
    build_case_prompt,
    build_prediction,
    build_qualification_evidence,
    critic_response_schema,
    materialize_case_composites,
    parse_critic_response,
    validate_live_calibration_inputs,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = ROOT / "qa/vlm_eval/visual_critic_calibration_v1"
CORPUS_ROOT_V2 = ROOT / "qa/vlm_eval/visual_critic_calibration_v2"


def _manifest() -> dict:
    return json.loads((CORPUS_ROOT / "manifest.json").read_text(encoding="utf-8"))


def test_prompt_and_schema_are_target_bound_without_expected_answer() -> None:
    manifest = _manifest()
    case = manifest["cases"][1]
    prompt = build_case_prompt(case, manifest["defect_taxonomy"])
    schema = critic_response_schema(case, manifest["defect_taxonomy"])
    assert case["target_contract"]["target"]["label_id"] in prompt
    assert "Allowed target ROI" in prompt
    assert "character's anatomical perspective" in prompt
    assert "Valid masks are expected" in prompt
    assert "rejecting every case is a failed reviewer" in prompt
    assert "output vocabulary, not a checklist" in prompt
    assert case["expected_outcome"] not in prompt
    assert str(case["defect_type"]) not in prompt.split("Allowed defect types:")[0]
    assert schema["schema"]["additionalProperties"] is False
    assert (
        schema["schema"]["properties"]["cited_context_tags"]["items"]["enum"]
        == case["context_tags"]
    )
    assert "uniqueItems" not in schema["schema"]["properties"]["cited_context_tags"]
    assert schema["schema"]["properties"]["checks"]["required"] == list(CHECK_KEYS)
    assert schema["schema"]["properties"]["cited_evidence_panels"]["minItems"] == 2
    assert len(PROMPT_SHA256) == 64


def test_strict_response_parser_accepts_only_bounded_exact_json() -> None:
    manifest = _manifest()
    case = manifest["cases"][1]
    value = {
        "verdict": "defect",
        "defect_type": "anatomy",
        "cited_context_tags": [case["context_tags"][0]],
        "checks": {key: "defect" if key == "anatomy" else "pass" for key in CHECK_KEYS},
        "cited_evidence_panels": ["source", "overlay"],
    }
    assert (
        parse_critic_response(
            "```json\n" + json.dumps(value) + "\n```", case, manifest["defect_taxonomy"]
        )
        == value
    )


def test_strict_response_parser_rejects_duplicate_context_tags_without_backend_hint() -> None:
    manifest = _manifest()
    case = manifest["cases"][0]
    value = {
        "verdict": "pass",
        "defect_type": None,
        "cited_context_tags": [case["context_tags"][0], case["context_tags"][0]],
        "checks": {key: "pass" for key in CHECK_KEYS},
        "cited_evidence_panels": ["source", "overlay"],
    }
    with pytest.raises(LiveCalibrationError, match="duplicated"):
        parse_critic_response(json.dumps(value), case, manifest["defect_taxonomy"])


@pytest.mark.parametrize(
    ("verdict", "defect_type", "changed_check", "changed_value", "message"),
    [
        ("pass", None, "boundary", "defect", "non-pass check"),
        ("defect", "boundary", "boundary", "pass", "lacks a defect check"),
        ("abstain", None, "boundary", "pass", "lacks an uncertain check"),
    ],
)
def test_response_parser_rejects_verdict_check_contradictions(
    verdict: str,
    defect_type: str | None,
    changed_check: str,
    changed_value: str,
    message: str,
) -> None:
    manifest = _manifest()
    case = manifest["cases"][1]
    baseline = "pass" if verdict != "abstain" else "defect"
    checks = {key: baseline for key in CHECK_KEYS}
    checks[changed_check] = changed_value
    value = {
        "verdict": verdict,
        "defect_type": defect_type,
        "cited_context_tags": [case["context_tags"][0]],
        "checks": checks,
        "cited_evidence_panels": ["source", "overlay"],
    }
    with pytest.raises(LiveCalibrationError, match=message):
        parse_critic_response(json.dumps(value), case, manifest["defect_taxonomy"])


@pytest.mark.parametrize(
    "value",
    [
        "not-json",
        json.dumps({"verdict": "pass"}),
        json.dumps(
            {
                "verdict": "pass",
                "defect_type": "boundary",
                "cited_context_tags": ["hand"],
            }
        ),
        json.dumps(
            {
                "verdict": "defect",
                "defect_type": "invented",
                "cited_context_tags": ["hand"],
            }
        ),
        json.dumps(
            {
                "verdict": "pass",
                "defect_type": None,
                "cited_context_tags": ["multi_person"],
            }
        ),
    ],
)
def test_response_parser_rejects_freeform_contradictory_or_widened_output(value: str) -> None:
    manifest = _manifest()
    with pytest.raises(LiveCalibrationError):
        parse_critic_response(value, manifest["cases"][1], manifest["defect_taxonomy"])


def test_composites_are_deterministic_and_retain_all_six_panels(tmp_path: Path) -> None:
    manifest = _manifest()
    case = manifest["cases"][0]
    first = materialize_case_composites(case, CORPUS_ROOT, tmp_path / "first")
    second = materialize_case_composites(case, CORPUS_ROOT, tmp_path / "second")
    assert [row["sha256"] for row in first] == [row["sha256"] for row in second]
    assert [name for row in first for name in row["panel_names"]] == [
        "source",
        "binary_mask",
        "overlay",
        "contour",
        "full_context",
        "uncertainty_zoom",
    ]
    assert all(row["bytes"] > 0 for row in first)
    with Image.open(first[0]["path"]) as composite:
        assert composite.size == (1536, 1592)
    assert len(first) == 1


def test_prediction_fails_closed_on_malformed_or_nondeterministic_response() -> None:
    case = _manifest()["cases"][0]
    prediction = build_prediction(
        case=case,
        parsed=None,
        raw_response="malformed",
        replay_response="different",
        latency_ms=12.5,
        peak_vram_bytes=123,
    )
    assert prediction["verdict"] == "abstain"
    assert prediction["schema_valid"] is False
    assert prediction["cited_context_tags"] == []
    assert set(prediction["checks"].values()) == {"uncertain"}
    assert prediction["cited_evidence_panels"] == []
    assert prediction["deterministic_replay"] is False


def test_qualification_evidence_uses_exact_catalog_and_runtime_bindings() -> None:
    manifest = _manifest()
    catalog = load_catalog()
    evidence = build_qualification_evidence(
        corpus=manifest,
        catalog=catalog,
        role_id="independent_juror",
        model_id="internvl3_5_8b_bf16",
        runtime_sha256="a" * 64,
        predictions=[],
    )
    model = next(row for row in catalog["models"] if row["model_id"] == "internvl3_5_8b_bf16")
    assert evidence["artifact_tree_sha256"] == model["artifact_sha256"]
    assert evidence["prompt_sha256"] == PROMPT_SHA256
    assert len(evidence["evidence_sha256"]) == 64

    with pytest.raises(LiveCalibrationError, match="not a candidate"):
        build_qualification_evidence(
            corpus=manifest,
            catalog=catalog,
            role_id="primary_visual_critic",
            model_id="internvl3_5_8b_bf16",
            runtime_sha256="a" * 64,
            predictions=[],
        )


def test_live_input_preflight_rejects_panel_hash_drift(tmp_path: Path) -> None:
    validate_live_calibration_inputs(_manifest(), CORPUS_ROOT)
    copied = tmp_path / "corpus"
    import shutil

    shutil.copytree(CORPUS_ROOT, copied)
    panel = next((copied / "panels").rglob("*.png"))
    panel.write_bytes(b"drift")
    with pytest.raises(Exception, match="hash drifted"):
        validate_live_calibration_inputs(_manifest(), copied)


def test_v2_corpus_corrects_side_owner_and_protected_region_grounding() -> None:
    manifest = json.loads((CORPUS_ROOT_V2 / "manifest.json").read_text(encoding="utf-8"))
    validate_live_calibration_inputs(manifest, CORPUS_ROOT_V2)
    cases = {case["defect_type"] or "valid": case for case in manifest["cases"]}
    valid = cases["valid"]
    wrong_side = cases["wrong_side"]
    ownership = cases["ownership"]
    assert valid["target_contract"]["target"]["label_id"] == "right_hand"
    assert valid["target_contract"]["excluded_labels"] == ["left_hand"]
    assert valid["target_contract"]["protected_regions"][0]["label_id"] == "face"

    def x_bounds(case: dict) -> tuple[int, int]:
        path = CORPUS_ROOT_V2 / case["panel_files"]["binary_mask"]
        with Image.open(path) as mask:
            bounds = mask.getbbox()
        assert bounds is not None
        return bounds[0], bounds[2]

    assert x_bounds(valid)[1] <= 33
    assert 52 <= x_bounds(wrong_side)[0] < 68
    assert x_bounds(ownership)[0] >= 68
