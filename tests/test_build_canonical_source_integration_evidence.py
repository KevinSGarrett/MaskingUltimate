from __future__ import annotations

import importlib.util
from pathlib import Path

TOOL = (
    Path(__file__).resolve().parents[1] / "tools" / "build_canonical_source_integration_evidence.py"
)
SPEC = importlib.util.spec_from_file_location("canonical_source_evidence", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_module_name_covers_packages_and_modules() -> None:
    assert MODULE.module_name("src/maskfactory/__init__.py") == "maskfactory"
    assert (
        MODULE.module_name("src/maskfactory/steward/supervisor.py")
        == "maskfactory.steward.supervisor"
    )
    assert MODULE.module_name("tests/test_cli.py") is None


def test_classification_keeps_source_control_and_evidence_distinct() -> None:
    assert MODULE.classify_path("src/maskfactory/cli.py") == "PRODUCT_OR_AUTONOMY_SOURCE"
    assert (
        MODULE.classify_path("Plan/Tracker/tracker.json")
        == "PLAN_ITEM_INSTRUCTION_TRACKER_AUTHORITY"
    )
    assert (
        MODULE.classify_path("runtime_artifacts/example/report.json")
        == "TRACKED_ACCEPTANCE_EVIDENCE"
    )


def test_requirement_rows_fail_closed_on_missing_path() -> None:
    rows = MODULE.requirement_rows({"pyproject.toml"}, authority_matrix_ok=True)
    by_name = {row["requirement"]: row for row in rows}
    assert by_name["package_metadata"]["status"] == "PASS"
    assert by_name["product_package"]["status"] == "FAIL"
    assert by_name["historical_stash_row_authority"]["status"] == "PASS"


def test_hygiene_detects_tracked_model_and_secret() -> None:
    entries = [
        {"path": "models/weights.safetensors", "oid": "a"},
        {"path": "src/maskfactory/config.py", "oid": "b"},
    ]
    blobs = {
        "a": b"not a real model",
        "b": b'TOKEN = "' + b"ghp_" + (b"a" * 32) + b'"',
    }
    result = MODULE.scan_hygiene(entries, blobs, [], [])
    assert result["status"] == "FAIL"
    assert result["tracked_model_binaries"] == ["models/weights.safetensors"]
    assert result["high_confidence_secret_candidates"][0]["pattern"] == ("github_token")


def test_hygiene_accepts_only_hash_pinned_test_secret_shape(monkeypatch) -> None:
    path = "tests/example_secret_shape.py"
    payload = b"AKIA" + b"ABCDEFGHIJKLMNOP"
    approved = dict(MODULE.APPROVED_TEST_FIXTURE_SECRET_SHAPES)
    approved[(path, "aws_access_key")] = MODULE.sha256_bytes(payload)
    monkeypatch.setattr(MODULE, "APPROVED_TEST_FIXTURE_SECRET_SHAPES", approved)

    result = MODULE.scan_hygiene(
        [{"path": path, "oid": "a"}],
        {"a": payload},
        [],
        [],
    )
    assert result["status"] == "PASS"
    assert result["high_confidence_secret_candidates"] == []
    assert result["approved_test_fixture_secret_shapes"] == [
        {
            "path": path,
            "pattern": "aws_access_key",
            "sha256": MODULE.sha256_bytes(payload),
            "classification": "STATIC_NON_PRODUCTION_TEST_FIXTURE",
        }
    ]


def test_canonical_json_is_stable_and_newline_terminated() -> None:
    first = MODULE.canonical_json_bytes({"b": 2, "a": 1})
    second = MODULE.canonical_json_bytes({"a": 1, "b": 2})
    assert first == second
    assert first.endswith(b"\n")


def test_canonical_path_key_normalizes_git_separator_spelling(tmp_path: Path) -> None:
    native = tmp_path / "repo"
    native.mkdir()
    git_spelling = str(native).replace("\\", "/")
    assert MODULE.canonical_path_key(native) == MODULE.canonical_path_key(git_spelling)


def test_build_frontend_targets_clean_export_from_external_working_directory(
    tmp_path: Path,
) -> None:
    export = tmp_path / "export"
    output = tmp_path / "dist"
    command = MODULE.build_frontend_command(["python"], export, output)
    assert command[-1] == str(export)
    assert command[1:5] == ["-I", "-B", "-m", "build"]
    assert "--no-isolation" not in command
