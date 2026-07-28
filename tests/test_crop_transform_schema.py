import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "src" / "maskfactory" / "schemas" / "crop_transform.schema.json"


def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def transform() -> dict:
    return {
        "part": "left_hand",
        "x0": 120,
        "y0": 340,
        "scale": 2.5,
        "crop_size": 1024,
        "source_sha256": "a" * 64,
    }


def test_crop_transform_schema_accepts_exact_affine_contract() -> None:
    assert list(validator().iter_errors(transform())) == []


def test_crop_transform_schema_rejects_negative_origin_and_zero_scale() -> None:
    invalid = copy.deepcopy(transform())
    invalid["x0"] = -1
    invalid["scale"] = 0
    paths = {tuple(error.absolute_path) for error in validator().iter_errors(invalid)}
    assert paths == {("scale",), ("x0",)}
