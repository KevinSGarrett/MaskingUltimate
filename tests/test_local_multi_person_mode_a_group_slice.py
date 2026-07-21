"""Hermetic guard for Mode A + contact QC on multi-body LV-MHP-shaped groups."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

TOOL_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "run_local_multi_person_mode_a_group_slice.py"
)


def _load_harness():
    spec = importlib.util.spec_from_file_location("_lmpmag_harness", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_mask(path: Path, array: np.ndarray) -> None:
    Image.fromarray((array.astype(np.uint8) * 15)).save(path)


def _write_image(path: Path, size: tuple[int, int]) -> None:
    Image.new("RGB", size, (32, 64, 96)).save(path)


def _block(rows: slice, cols: slice, shape=(64, 96)) -> np.ndarray:
    mask = np.zeros(shape, dtype=bool)
    mask[rows, cols] = True
    return mask


def _build_dataset(root: Path) -> None:
    content = root / "LV-MHP-v1"
    annotations = content / "annotations"
    images = content / "images"
    annotations.mkdir(parents=True)
    images.mkdir(parents=True)

    # Duo 0103: adjacent (contact) pixel-disjoint blocks.
    _write_mask(annotations / "0103_02_01.png", _block(slice(8, 56), slice(8, 46)))
    _write_mask(annotations / "0103_02_02.png", _block(slice(8, 56), slice(50, 88)))

    # Trio 0101: p0-p1 touch; p2 far.
    _write_mask(annotations / "0101_03_01.png", _block(slice(8, 56), slice(4, 28)))
    _write_mask(annotations / "0101_03_02.png", _block(slice(8, 56), slice(30, 54)))
    _write_mask(annotations / "0101_03_03.png", _block(slice(8, 56), slice(80, 94)))

    # Quad 0102: 2x2 grid with multiple contacts.
    _write_mask(annotations / "0102_04_01.png", _block(slice(6, 30), slice(4, 28)))
    _write_mask(annotations / "0102_04_02.png", _block(slice(6, 30), slice(30, 54)))
    _write_mask(annotations / "0102_04_03.png", _block(slice(34, 58), slice(4, 28)))
    _write_mask(annotations / "0102_04_04.png", _block(slice(34, 58), slice(30, 54)))

    # Solo must be ignored.
    _write_mask(annotations / "0104_01_01.png", _block(slice(8, 56), slice(8, 88)))

    for stem in ("0101", "0102", "0103", "0104"):
        _write_image(images / f"{stem}.jpg", (96, 64))


def test_mode_a_group_slice_runtime_pass_across_sizes(tmp_path: Path) -> None:
    harness = _load_harness()
    _build_dataset(tmp_path)

    document = harness.run_local_multi_person_mode_a_group_slice(
        tmp_path,
        sizes=(2, 3, 4),
        limit_per_size=8,
        workdir=tmp_path / "_work",
        prefer_contact=False,
    )

    assert document["proof_tier"] == "RUNTIME_PASS_BOUNDED"
    assert document["small_group_context_exercised"] is True
    assert document["group_count_processed"] == 3
    assert document["group_pass_count"] == 3
    assert document["mode_a_reads_all_accepted_count"] == 3
    assert document["multi_person_gate_pass_count"] == 3
    assert document["bounded_ownership_integrity_count"] == 3

    per_size = document["per_size_breakdown"]
    assert per_size["2"]["group_pass"] == 1
    assert per_size["3"]["group_pass"] == 1
    assert per_size["4"]["group_pass"] == 1

    seeded = document["seeded_faults_all_blocked"]
    assert seeded["wrong_person_wrong_owner"] is True
    assert seeded["cross_instance_instance_mismatch"] is True
    assert seeded["exclusivity_overlap_qc035"] is True
    assert seeded["cross_instance_bleed_qc036"] is True
    assert seeded["bleed_containment_aut_mp_001"] is True
    assert seeded["contact_nonreciprocity_aut_mp_002"] is True

    trio = next(record for record in document["records"] if record["size"] == 3)
    assert trio["mode_a_reads"]["all_accepted"] is True
    assert trio["mode_a_reads"]["accepted_count"] == 3
    assert trio["multi_person_gate"]["instance_context"] == "small_group"
    assert trio["contact_pair_count"] == 1

    quad = next(record for record in document["records"] if record["size"] == 4)
    assert quad["mode_a_reads"]["accepted_count"] == 4
    assert quad["contact_pair_count"] >= 2

    assert all(record["image_id"] != "0104" for record in document["records"])

    for flag in (
        "mf_p6_12_02_prerequisite_complete",
        "mf_p6_12_03_complete",
        "main_adapter_execution_complete",
        "mf_p8_11_07_demo_complete",
        "gold_claimed",
        "champions_claimed",
        "doctor_green_claimed",
        "production_evidence_pass_claimed",
        "independent_real_accuracy_claim",
        "kevin_governed_multi_person_sources_used",
    ):
        assert document[flag] is False
    assert document["package_authority_tier"] == "fixture_authority"

    recomputed = harness._sha_doc(
        {key: value for key, value in document.items() if key != "sha256"}
    )
    assert recomputed == document["sha256"]


def test_no_groups_raises(tmp_path: Path) -> None:
    harness = _load_harness()
    content = tmp_path / "LV-MHP-v1"
    (content / "annotations").mkdir(parents=True)
    (content / "images").mkdir(parents=True)
    _write_mask(
        content / "annotations" / "0001_01_01.png",
        _block(slice(4, 60), slice(4, 60), shape=(64, 64)),
    )
    _write_image(content / "images" / "0001.jpg", (64, 64))

    with pytest.raises(RuntimeError):
        harness.run_local_multi_person_mode_a_group_slice(
            tmp_path,
            sizes=(2, 3, 4),
            limit_per_size=4,
            workdir=tmp_path / "_work",
        )
