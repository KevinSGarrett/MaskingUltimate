from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "build_test_baseline_evidence.py"
SPEC = importlib.util.spec_from_file_location("build_test_baseline_evidence", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def _contract_document(reason: str) -> dict:
    return {
        "contracts": [
            {
                "contract_id": "fixture_asset",
                "skip_reason": reason,
                "minimum_observed": 1,
            }
        ]
    }


def _junit(path: Path, reason: str) -> None:
    path.write_text(
        (
            '<testsuites name="pytest tests"><testsuite tests="2" failures="0" '
            'errors="0" skipped="1">'
            '<testcase classname="tests.test_fixture" name="test_pass" time="0.1" />'
            '<testcase classname="tests.test_fixture" name="test_skip" time="0.0">'
            f'<skipped type="pytest.skip" message="{reason}" />'
            "</testcase></testsuite></testsuites>"
        ),
        encoding="utf-8",
    )


def test_parse_junit_classifies_every_case_and_binds_skip(tmp_path: Path) -> None:
    reason = "external fixture is absent"
    junit = tmp_path / "junit.xml"
    _junit(junit, reason)
    summary, rows, observed = TOOL.parse_junit(junit, _contract_document(reason))
    assert summary == {
        "tests": 2,
        "passed": 1,
        "governed_skips": 1,
        "failures": 0,
        "errors": 0,
    }
    assert [row["outcome"] for row in rows] == ["pass", "governed_skip"]
    assert rows[1]["absence_semantics"] == "skip_not_pass"
    assert observed == {"fixture_asset": 1}


def test_parse_junit_rejects_unknown_skip_and_failures(tmp_path: Path) -> None:
    junit = tmp_path / "unknown.xml"
    _junit(junit, "unknown prerequisite")
    with pytest.raises(TOOL.TestBaselineEvidenceError, match="ungoverned skip"):
        TOOL.parse_junit(junit, _contract_document("governed prerequisite"))

    failed = tmp_path / "failed.xml"
    failed.write_text(
        (
            '<testsuites><testsuite tests="1" failures="1" errors="0" skipped="0">'
            '<testcase classname="tests.test_fixture" name="test_fail">'
            '<failure message="boom" /></testcase></testsuite></testsuites>'
        ),
        encoding="utf-8",
    )
    with pytest.raises(TOOL.TestBaselineEvidenceError, match="failures/errors"):
        TOOL.parse_junit(failed, {"contracts": []})


def test_hashed_json_detects_contract_tamper(tmp_path: Path) -> None:
    pinned = tmp_path / "pinned.py"
    pinned.write_text("print('pinned')\n", encoding="utf-8")
    document = {
        "schema_version": "maskfactory.test_external_prerequisite_contracts.v1",
        "authority": {},
        "byte_pinned_formatter_exclusions": [
            {
                "path": "pinned.py",
                "sha256": TOOL.sha256_file(pinned),
                "reason": "fixture",
            }
        ],
        "contracts": [
            {
                "contract_id": "fixture",
                "skip_reason": "fixture absent",
                "minimum_observed": 0,
            }
        ],
    }
    document["self_sha256"] = TOOL.canonical_sha256(document)
    path = tmp_path / "contracts.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert TOOL.load_contracts(path, tmp_path)["self_sha256"] == document["self_sha256"]

    document["contracts"][0]["skip_reason"] = "tampered"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(TOOL.TestBaselineEvidenceError, match="self hash mismatch"):
        TOOL.load_contracts(path, tmp_path)
