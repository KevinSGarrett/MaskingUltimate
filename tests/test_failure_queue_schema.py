import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "src" / "maskfactory" / "schemas" / "failure_queue.schema.json"


def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def record() -> dict:
    return {
        "ts": "2026-07-11T00:20:00Z",
        "image_id": "img_a3f9c2e17b04",
        "failed_body_part": "left_index_finger",
        "failure_reason": "finger_merge",
        "pose_angle": "left_3_4",
        "model_that_failed": "sam2_hand_lane",
        "correction_needed": "manual_crop_repaint",
        "priority": 0.82,
        "resolved": False,
        "resolution_pkg_version": None,
    }


def test_failure_queue_schema_accepts_normative_jsonl_record() -> None:
    assert list(validator().iter_errors(record())) == []


def test_failure_queue_schema_closes_reason_enum_and_priority_range() -> None:
    invalid = copy.deepcopy(record())
    invalid["failure_reason"] = "made_up"
    invalid["priority"] = 1.1
    paths = {tuple(error.absolute_path) for error in validator().iter_errors(invalid)}
    assert paths == {("failure_reason",), ("priority",)}
