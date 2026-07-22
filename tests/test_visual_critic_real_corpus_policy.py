from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from tools.build_real_visual_critic_calibration_corpus import _focus_crop_xyxy, build

from maskfactory.vlm.real_corpus_policy import (
    RealCorpusPolicyError,
    bindings_sha256,
    load_real_corpus_policy,
    validate_real_source_bindings,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs" / "visual_critic_real_corpus.yaml"
RUNNER = ROOT / "tools" / "run_visual_critic_calibration.py"


def _fixture_roots(tmp_path: Path) -> tuple[Path, Path]:
    warehouse = tmp_path / "MaskedWarehouse"
    content = warehouse / "Body" / "LV-MHP-v1" / "LV-MHP-v1"
    images = content / "images"
    annotations = content / "annotations"
    images.mkdir(parents=True)
    annotations.mkdir(parents=True)
    train_ids: list[str] = []
    test_ids: list[str] = []
    for index in range(1, 13):
        image_id = f"{index:04d}"
        (train_ids if index <= 6 else test_ids).append(f"{image_id}.jpg")
        source = np.zeros((64, 64, 3), dtype=np.uint8)
        source[:, :, 0] = 10 + index * 15
        source[:, :, 1] = 5 + index * 7
        source[4:60, 4:30] = (160, 110, 90)
        source[4:60, 34:60] = (90, 130, 170)
        Image.fromarray(source, mode="RGB").save(images / f"{image_id}.jpg")
        for person in (1, 2):
            label = np.zeros((64, 64), dtype=np.uint8)
            x = 5 if person == 1 else 35
            label[5:15, x + 6 : x + 16] = 11
            label[16:50, x + 8 : x + 18] = 4
            label[18:45, x + 1 : x + 6] = 14
            label[18:45, x + 20 : x + 25] = 15
            Image.fromarray(label, mode="L").save(annotations / f"{image_id}_02_{person:02d}.png")
    (content / "train_list.txt").write_text("\n".join(train_ids) + "\n", encoding="utf-8")
    (content / "test_list.txt").write_text("\n".join(test_ids) + "\n", encoding="utf-8")
    reference = tmp_path / "Ultimate_Masking_Reference_Images"
    manifests = reference / "manifests"
    manifests.mkdir(parents=True)
    (manifests / "inventory_summary.json").write_text(
        json.dumps({"valid_images": 12}) + "\n", encoding="utf-8"
    )
    (manifests / "reference_library.sqlite").write_bytes(b"fixture")
    return warehouse, reference


def test_policy_locks_both_real_roots_and_forbids_synthetic_controls() -> None:
    policy = load_real_corpus_policy(POLICY)
    semantic = policy["semantic_role_qualification"]
    assert set(policy["roots"]) == {"maskedwarehouse", "reference_library"}
    assert semantic["require_real_source_pixels"] is True
    assert semantic["allow_synthetic_positive_controls"] is False
    assert semantic["allow_draft_package_positive_controls"] is False


def test_real_builder_binds_every_case_to_real_source_annotation_and_reference_inventory(
    tmp_path: Path,
) -> None:
    warehouse, reference = _fixture_roots(tmp_path)
    output = tmp_path / "corpus"
    manifest, bindings = build(
        output,
        maskedwarehouse_root=warehouse,
        reference_root=reference,
        project_root=ROOT,
        policy_path=POLICY,
    )
    assert len(manifest["cases"]) == 12
    assert len(bindings["cases"]) == 12
    assert {row["source_family"] for row in bindings["cases"]} == {"maskedwarehouse"}
    assert all(row["real_source_pixels"] for row in bindings["cases"])
    assert all(not row["synthetic"] for row in bindings["cases"])
    assert bindings["reference_library"]["root_id"] == "reference_library"
    assert manifest["corpus_id"] == "maskfactory_real_visual_critic_calibration_v2"

    valid = manifest["cases"][0]
    contract = valid["target_contract"]
    assert contract["schema_version"] == "2.0.0"
    assert contract["target"]["laterality"] == "right"
    assert contract["target"]["perspective"] == "character_perspective"
    assert any("hand" in rule for rule in contract["target"]["inclusions"])
    assert contract["source"]["encoded_sha256"] == valid["panels"]["source"]
    assert contract["source"]["decoded_pixel_sha256"] != contract["source"]["encoded_sha256"]
    assert contract["candidate"]["decoded_pixel_sha256"] != contract["candidate"]["encoded_sha256"]
    with Image.open(output / valid["panel_files"]["source"]) as source:
        source_size = source.size
    with Image.open(output / valid["panel_files"]["uncertainty_zoom"]) as zoom:
        zoom_size = zoom.size
    assert zoom_size[0] < source_size[0]
    assert zoom_size[1] < source_size[1]
    assert valid["panels"]["uncertainty_zoom"] != valid["panels"]["overlay"]

    validate_real_source_bindings(
        corpus=manifest,
        corpus_root=output,
        bindings=bindings,
        policy=load_real_corpus_policy(POLICY),
        root_overrides={"maskedwarehouse": warehouse, "reference_library": reference},
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("synthetic", True, "not an eligible real semantic control"),
        ("production_draft", True, "not an eligible real semantic control"),
        ("source_authority", "draft_model_generated", "not an eligible real semantic control"),
    ],
)
def test_semantic_source_binding_rejects_synthetic_draft_or_weak_authority(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    warehouse, reference = _fixture_roots(tmp_path)
    output = tmp_path / "corpus"
    manifest, bindings = build(
        output,
        maskedwarehouse_root=warehouse,
        reference_root=reference,
        project_root=ROOT,
        policy_path=POLICY,
    )
    changed = deepcopy(bindings)
    changed["cases"][0][field] = value
    changed["bindings_sha256"] = bindings_sha256(changed)
    with pytest.raises(RealCorpusPolicyError, match=message):
        validate_real_source_bindings(
            corpus=manifest,
            corpus_root=output,
            bindings=changed,
            policy=load_real_corpus_policy(POLICY),
            root_overrides={"maskedwarehouse": warehouse, "reference_library": reference},
        )


def test_semantic_source_binding_rejects_source_or_reference_hash_drift(tmp_path: Path) -> None:
    warehouse, reference = _fixture_roots(tmp_path)
    output = tmp_path / "corpus"
    manifest, bindings = build(
        output,
        maskedwarehouse_root=warehouse,
        reference_root=reference,
        project_root=ROOT,
        policy_path=POLICY,
    )
    source = warehouse / bindings["cases"][0]["source_relative_path"]
    source.write_bytes(b"drift")
    with pytest.raises(RealCorpusPolicyError, match="source_file hash drifted"):
        validate_real_source_bindings(
            corpus=manifest,
            corpus_root=output,
            bindings=bindings,
            policy=load_real_corpus_policy(POLICY),
            root_overrides={"maskedwarehouse": warehouse, "reference_library": reference},
        )


def test_calibration_cli_requires_real_source_bindings_before_provider_invocation(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--backend",
            "openai",
            "--model-id",
            "must-not-load",
            "--role",
            "primary",
            "--runtime-sha256",
            "0" * 64,
            "--manifest",
            str(tmp_path / "missing.json"),
            "--corpus-root",
            str(tmp_path),
            "--output",
            str(tmp_path / "output.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert result.returncode == 2
    assert "--source-bindings" in result.stderr
    assert not (tmp_path / "output.json").exists()


def test_focus_crop_is_padded_bounded_and_includes_target_plus_candidate() -> None:
    target = np.zeros((100, 120), dtype=bool)
    candidate = np.zeros_like(target)
    target[30:50, 20:40] = True
    candidate[45:70, 55:75] = True
    x0, y0, x1, y1 = _focus_crop_xyxy(target, candidate)
    assert (x0, y0) == (4, 14)
    assert (x1, y1) == (91, 86)
    assert x0 <= 20 < 40 <= x1
    assert x0 <= 55 < 75 <= x1
