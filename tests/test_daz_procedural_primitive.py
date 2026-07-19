from __future__ import annotations

import copy
import json
import os
from pathlib import Path

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"

import numpy as np
import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.daz.render.procedural_primitive import (
    DEFAULT_DEPTH_M,
    DEFAULT_PART_ID,
    NORMALS_EXPECTED,
    PRIMITIVE_KIND,
    ProceduralPrimitiveError,
    build_procedural_primitive_bundle,
    publish_procedural_primitive_bundle,
    synthesize_primitive_arrays,
    validate_procedural_primitive_bundle,
)
from maskfactory.validation import validate_document


def test_synthesize_and_build_are_deterministic_and_schema_valid(tmp_path: Path) -> None:
    first_arrays = synthesize_primitive_arrays()
    second_arrays = synthesize_primitive_arrays()
    for key in first_arrays:
        assert np.array_equal(first_arrays[key], second_arrays[key])

    first = build_procedural_primitive_bundle(tmp_path / "a")
    second = build_procedural_primitive_bundle(tmp_path / "b")
    assert first == second
    assert validate_document(first, "daz_procedural_primitive_bundle") == ()
    assert first["primitive_kind"] == PRIMITIVE_KIND
    assert first["executor"] == "host_procedural_primitive"
    assert first["live_daz_execution"] is False
    assert first["daz_assets_used"] is False
    assert first["training_eligible"] is False
    assert first["accepted"] is False
    assert first["gold_claimed"] is False
    assert first["depth_m"] == DEFAULT_DEPTH_M
    assert first["part_id"] == DEFAULT_PART_ID
    assert first["analytic_checks"]["normals_expected_vector"] == list(NORMALS_EXPECTED)
    assert first["analytic_checks"]["depth_unit"] == "meter"
    assert first["analytic_checks"]["visible_pixel_count"] > 0


def test_validate_roundtrips_artifacts_and_publish_is_idempotent(tmp_path: Path) -> None:
    from maskfactory.daz.render.procedural_primitive import republish_primitive_artifacts

    work = tmp_path / "work"
    bundle = build_procedural_primitive_bundle(work)
    validate_procedural_primitive_bundle(bundle, artifact_root=work)
    publish_root = tmp_path / "publish"
    first_path, first_published = publish_procedural_primitive_bundle(bundle, work, publish_root)
    second_path, second_published = publish_procedural_primitive_bundle(bundle, work, publish_root)
    assert first_published is True
    assert second_published is False
    assert first_path == second_path
    published = json.loads(first_path.read_text(encoding="utf-8"))
    assert published == bundle
    # Git publishes bundle JSON only; golden binaries are regenerated from seed.
    validate_procedural_primitive_bundle(published)
    republish_primitive_artifacts(published, tmp_path / "rebuild")


def test_authority_escalation_and_hash_drift_fail_closed(tmp_path: Path) -> None:
    work = tmp_path / "work"
    bundle = build_procedural_primitive_bundle(work)
    for field in ("accepted", "training_eligible", "gold_claimed", "live_daz_execution"):
        tampered = copy.deepcopy(bundle)
        tampered[field] = True
        with pytest.raises(ProceduralPrimitiveError):
            validate_procedural_primitive_bundle(tampered, artifact_root=work)

    (work / "rgb.png").write_bytes(b"not-a-png")
    with pytest.raises(ProceduralPrimitiveError, match="artifact_hash_mismatch:rgb"):
        validate_procedural_primitive_bundle(bundle, artifact_root=work)


def test_cli_build_and_verify(tmp_path: Path) -> None:
    runner = CliRunner()
    output = tmp_path / "out"
    built = runner.invoke(
        main,
        [
            "daz",
            "recipes",
            "build-procedural-primitive",
            "--output",
            str(output),
        ],
    )
    assert built.exit_code == 0, built.output
    envelope = json.loads(built.output)
    assert envelope["reason"] == "daz_procedural_primitive_built"
    assert envelope["data"]["live_daz_execution"] is False
    manifest = Path(envelope["evidence_paths"][0])
    assert manifest.is_file()

    verified = runner.invoke(
        main,
        ["daz", "recipes", "verify-procedural-primitive", str(manifest)],
    )
    assert verified.exit_code == 0, verified.output
    verify_envelope = json.loads(verified.output)
    assert verify_envelope["reason"] == "daz_procedural_primitive_verified"
    assert verify_envelope["data"]["gold_claimed"] is False
