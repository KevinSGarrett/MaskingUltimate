from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from maskfactory.autonomy.development_bundle import (
    DevelopmentBundleError,
    seal_development_bundle,
    validate_development_bundle,
    write_development_bundle,
)

HEX = "a" * 64


def bundle(patch_sha256: str) -> dict:
    return seal_development_bundle(
        {
            "schema_version": "maskfactory.runpod_development_patch_bundle.v1",
            "mission_id": "development-mission-0001",
            "base_commit": "a" * 40,
            "repository_sha256": HEX,
            "model": {
                "model_id": "self-hosted-code-model",
                "family": "independent-code-family",
                "revision_sha256": HEX,
                "runtime_sha256": HEX,
            },
            "allowed_paths": ["src/maskfactory/reports", "tests/test_reports.py"],
            "changed_files": [
                {"path": "src/maskfactory/reports/batch.py", "sha256": HEX},
                {"path": "tests/test_reports.py", "sha256": HEX},
            ],
            "patch_path": "artifacts/change.patch",
            "patch_sha256": patch_sha256,
            "validators": [
                {
                    "validator_id": "focused-pytest",
                    "command": ["python", "-m", "pytest", "-q", "tests/test_reports.py"],
                    "status": "pass",
                    "output_sha256": HEX,
                },
                {
                    "validator_id": "ruff",
                    "command": ["ruff", "check", "src/maskfactory/reports"],
                    "status": "pass",
                    "output_sha256": HEX,
                },
            ],
            "risk": "low",
            "limitations": [],
            "authority": "prepared_patch_only_requires_codex_adoption",
        }
    )


def test_development_bundle_schema_is_closed() -> None:
    schema = json.loads(
        Path("src/maskfactory/schemas/runpod_development_patch_bundle.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False


def test_bundle_validates_patch_hash_and_remains_adoption_only(tmp_path: Path) -> None:
    patch = tmp_path / "artifacts" / "change.patch"
    patch.parent.mkdir(parents=True)
    patch.write_bytes(b"diff --git a/a b/a\n")
    document = bundle(hashlib.sha256(patch.read_bytes()).hexdigest())
    validated = validate_development_bundle(document, artifact_root=tmp_path)
    assert validated["authority"] == "prepared_patch_only_requires_codex_adoption"


def test_bundle_rejects_out_of_scope_file() -> None:
    document = bundle(HEX)
    document["changed_files"].append({"path": "Plan/Tracker/tracker.json", "sha256": HEX})
    document = seal_development_bundle(document)
    with pytest.raises(DevelopmentBundleError, match="outside allowed paths"):
        validate_development_bundle(document)


def test_bundle_rejects_git_validator_and_duplicate_validator() -> None:
    document = bundle(HEX)
    document["validators"][1]["command"] = ["git", "diff", "--check"]
    document = seal_development_bundle(document)
    with pytest.raises(DevelopmentBundleError, match="Git commands"):
        validate_development_bundle(document)

    document = bundle(HEX)
    document["validators"][1]["command"] = document["validators"][0]["command"]
    document = seal_development_bundle(document)
    with pytest.raises(DevelopmentBundleError, match="independent deterministic validators"):
        validate_development_bundle(document)


def test_bundle_is_immutable(tmp_path: Path) -> None:
    output = tmp_path / "bundle.json"
    document = bundle(HEX)
    write_development_bundle(document, output)
    with pytest.raises(DevelopmentBundleError, match="already exists"):
        write_development_bundle(document, output)
