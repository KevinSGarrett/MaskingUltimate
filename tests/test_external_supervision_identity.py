import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from maskfactory.external_supervision_evidence import seal_payload
from maskfactory.external_supervision_identity import (
    ExternalIdentityError,
    build_lv_mhp_identity_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (
    ROOT / "src" / "maskfactory" / "schemas" / "external_supervision_identity_evidence.schema.json"
)


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "LV-MHP-v1"
    (root / "images").mkdir(parents=True)
    (root / "annotations").mkdir()
    (root / "images" / "0001.jpg").write_bytes(b"one")
    (root / "images" / "0002.jpg").write_bytes(b"two")
    for name in ("0001_02_01.png", "0001_02_02.png", "0002_01_01.png"):
        (root / "annotations" / name).write_bytes(b"mask")
    return root


def test_identity_evidence_is_deterministic_sealed_and_schema_valid(tmp_path: Path):
    root = _fixture(tmp_path)
    first = build_lv_mhp_identity_evidence(root)
    second = build_lv_mhp_identity_evidence(root)

    assert first == second
    assert first["image_count"] == 2
    assert first["annotation_count"] == 3
    assert first["person_count_distribution"] == {"1": 1, "2": 1}
    assert first["seal_sha256"] == seal_payload(first)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(first)


def test_missing_image_or_annotation_fails_closed(tmp_path: Path):
    root = _fixture(tmp_path)
    (root / "annotations" / "0002_01_01.png").unlink()
    with pytest.raises(ExternalIdentityError, match="identity sets differ"):
        build_lv_mhp_identity_evidence(root)


def test_conflicting_declared_counts_fail_closed(tmp_path: Path):
    root = _fixture(tmp_path)
    (root / "annotations" / "0001_02_02.png").rename(root / "annotations" / "0001_03_02.png")
    with pytest.raises(ExternalIdentityError, match="conflicting person counts"):
        build_lv_mhp_identity_evidence(root)


def test_missing_instance_index_fails_closed(tmp_path: Path):
    root = _fixture(tmp_path)
    (root / "annotations" / "0001_02_02.png").rename(root / "annotations" / "0001_02_03.png")
    with pytest.raises(ExternalIdentityError, match="incomplete person identity sequence"):
        build_lv_mhp_identity_evidence(root)


def test_malformed_annotation_name_fails_closed(tmp_path: Path):
    root = _fixture(tmp_path)
    (root / "annotations" / "ambiguous.png").write_bytes(b"mask")
    with pytest.raises(ExternalIdentityError, match="malformed annotation identity"):
        build_lv_mhp_identity_evidence(root)
