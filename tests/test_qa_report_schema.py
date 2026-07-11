import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "src" / "maskfactory" / "schemas" / "qa_report.schema.json"


def valid_report() -> dict:
    return {
        "image_id": "img_a3f9c2e17b04",
        "run_id": "qa_20260709_1403_7f2a",
        "pipeline_version": "maskfactory 0.4.1+g8f21ac",
        "created_at": "2026-07-09T14:03:22Z",
        "checks": [
            {
                "id": "QC-001",
                "name": "dimensions_match_source",
                "scope": "package",
                "result": "pass",
                "severity": "BLOCK",
            },
            {
                "id": "QC-014",
                "name": "left_right_consistency",
                "scope": "left_hand_base",
                "result": "fail",
                "severity": "BLOCK",
                "value": "handedness_mismatch",
                "action": "route_human",
                "evidence": "qa_panels/left_hand_lr.png",
            },
        ],
        "metrics_per_part": {
            "left_forearm": {
                "iou_vs_consensus": 0.94,
                "boundary_f_2px": 0.88,
                "hole_ratio": 0.001,
                "components": 1,
                "mask_area_px": 48211,
                "mask_bbox": [100, 200, 150, 400],
                "disagreement_score": 0.06,
                "overlap_with_protected_regions": 0,
                "overlap_with_mutually_exclusive_parts": 0,
            }
        },
        "consensus": {
            "method": "weighted_vote_v1",
            "sources": ["sapiens_seg", "schp", "sam2", "geometry", "densepose"],
        },
        "vlm_review": {
            "model": "qwen2.5-vl:7b-q4",
            "verdicts": [
                {
                    "label": "left_forearm",
                    "panel_file": "qa_panels/left_forearm.png",
                    "model": "qwen2.5-vl:7b-q4",
                    "prompt_version": "p-part-v1",
                    "verdict": "fail",
                    "confidence": 0.91,
                    "problems": ["boundary_too_loose"],
                    "evidence": "Mask extends beyond the outer forearm edge.",
                    "correction_instruction": "Tighten the outer contour to the visible skin edge.",
                    "latency_ms": 832,
                }
            ],
        },
        "overall": "needs_human",
        "score": 0.84,
    }


def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_qa_report_schema_accepts_checks_metrics_consensus_and_vlm_verdicts() -> None:
    assert list(validator().iter_errors(valid_report())) == []


def test_qa_report_schema_rejects_unknown_qc_and_out_of_range_scores() -> None:
    report = copy.deepcopy(valid_report())
    report["checks"][0]["id"] = "QC-999"
    report["metrics_per_part"]["left_forearm"]["iou_vs_consensus"] = 1.1
    report["score"] = -0.1
    paths = {tuple(error.absolute_path) for error in validator().iter_errors(report)}
    assert paths == {
        ("checks", 0, "id"),
        ("metrics_per_part", "left_forearm", "iou_vs_consensus"),
        ("score",),
    }


def test_qa_report_schema_closes_vlm_problem_taxonomy() -> None:
    report = copy.deepcopy(valid_report())
    report["vlm_review"]["verdicts"][0]["problems"] = ["invented_problem"]
    errors = list(validator().iter_errors(report))
    assert len(errors) == 1
    assert tuple(errors[0].absolute_path) == ("vlm_review", "verdicts", 0, "problems", 0)
