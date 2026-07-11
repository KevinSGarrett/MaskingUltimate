import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "src" / "maskfactory" / "schemas" / "coverage_matrix.schema.json"
ATTRIBUTES = {
    "hands_visible": 41,
    "feet_visible": 42,
    "hand_body_contact": 40,
    "hair_occlusion": 44,
    "clothing_boundary": 52,
    "bare_skin_dominant": 43,
    "tight_clothing": 48,
    "loose_clothing": 46,
    "back_visible": 45,
    "fingers_spread": 40,
    "fingers_merged": 40,
    "props_present": 47,
}


def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def matrix() -> dict:
    return {
        "schema_version": "1.0.0",
        "generated_at": "2026-07-11T00:20:00Z",
        "cells": [
            {
                "view": "front",
                "pose": "arms_down",
                "instance_context": "solo",
                "approved_gold_count": 8,
            },
            {
                "view": "left_3_4",
                "pose": "leg_overlap",
                "instance_context": "duo",
                "approved_gold_count": 9,
            },
        ],
        "attribute_totals": copy.deepcopy(ATTRIBUTES),
    }


def test_coverage_matrix_schema_accepts_closed_vocab_and_instance_dimension() -> None:
    assert list(validator().iter_errors(matrix())) == []


def test_coverage_matrix_schema_rejects_unknown_pose_attribute_and_context() -> None:
    invalid = matrix()
    invalid["cells"][0]["pose"] = "invented_pose"
    invalid["cells"][0]["instance_context"] = "crowd"
    invalid["attribute_totals"]["invented_attribute"] = 1
    paths = {tuple(error.absolute_path) for error in validator().iter_errors(invalid)}
    assert paths == {
        ("attribute_totals",),
        ("cells", 0, "instance_context"),
        ("cells", 0, "pose"),
    }
