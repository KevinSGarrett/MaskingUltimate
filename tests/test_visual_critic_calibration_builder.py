from __future__ import annotations

from pathlib import Path

import pytest
from tools.build_visual_critic_calibration_corpus import build

from maskfactory.vlm.calibration_corpus import (
    CONTEXT_TAGS,
    DEFECT_TYPES,
    validate_calibration_corpus_files,
)


def test_builder_materializes_frozen_balanced_disjoint_corpus(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    manifest = build(root)
    validate_calibration_corpus_files(manifest, root)
    assert len(manifest["cases"]) == 12
    assert {case["defect_type"] for case in manifest["cases"] if case["defect_type"]} == set(
        DEFECT_TYPES
    )
    assert {tag for case in manifest["cases"] for tag in case["context_tags"]} == set(CONTEXT_TAGS)
    assert len(list((root / "panels").rglob("*.png"))) == 72


def test_builder_is_immutable_and_file_tamper_fails(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    manifest = build(root)
    with pytest.raises(ValueError, match="already exists"):
        build(root)
    target = root / manifest["cases"][0]["panel_files"]["overlay"]
    target.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="file hash drifted"):
        validate_calibration_corpus_files(manifest, root)
