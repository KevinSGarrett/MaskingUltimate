import json
from pathlib import Path

import pytest

from maskfactory.validation import validate_document

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "schemas" / "invalid"


@pytest.mark.parametrize(
    ("schema_name", "expected_pointer"),
    [
        ("manifest", "/image_id"),
        ("qa_report", "/score"),
        ("model_registry", "/models/0"),
        ("failure_queue", "/failure_reason"),
        ("coverage_matrix", "/cells/0/pose"),
        ("crop_transform", "/scale"),
    ],
)
def test_each_schema_has_a_pointer_asserted_invalid_fixture(
    schema_name: str, expected_pointer: str
) -> None:
    fixture = json.loads((FIXTURES / f"{schema_name}.json").read_text(encoding="utf-8"))
    issues = validate_document(fixture, schema_name)
    assert issues, f"{schema_name} invalid fixture unexpectedly passed"
    assert {issue.pointer for issue in issues} == {expected_pointer}
