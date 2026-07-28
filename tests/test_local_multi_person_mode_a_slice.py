"""Hermetic guard for the real-source multi-person Mode A package-QC harness.

Builds a tiny synthetic LV-MHP-shaped duo dataset (contact + non-contact, with
real image rasters) so the harness logic (real Mode A package reads, ownership
binding, real gate execution, seeded fail-closed faults, zero-ownership-ambiguity
verdict, self-seal) is regression-locked without the on-disk MaskedWarehouse.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "run_local_multi_person_mode_a_slice.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("_lmpma_harness", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_mask(path: Path, array: np.ndarray) -> None:
    Image.fromarray((array.astype(np.uint8) * 15)).save(path)


def _write_image(path: Path, size: tuple[int, int]) -> None:
    Image.new("RGB", size, (32, 64, 96)).save(path)


def _build_dataset(root: Path) -> None:
    content = root / "LV-MHP-v1"
    annotations = content / "annotations"
    images = content / "images"
    annotations.mkdir(parents=True)
    images.mkdir(parents=True)

    # Duo 0001: adjacent (contact) but pixel-disjoint blocks.
    p0 = np.zeros((64, 96), dtype=bool)
    p1 = np.zeros((64, 96), dtype=bool)
    p0[8:56, 8:46] = True
    p1[8:56, 50:88] = True
    _write_mask(annotations / "0001_02_01.png", p0)
    _write_mask(annotations / "0001_02_02.png", p1)
    _write_image(images / "0001.jpg", (96, 64))

    # Duo 0002: far apart (no contact).
    q0 = np.zeros((64, 96), dtype=bool)
    q1 = np.zeros((64, 96), dtype=bool)
    q0[8:24, 4:20] = True
    q1[40:56, 76:92] = True
    _write_mask(annotations / "0002_02_01.png", q0)
    _write_mask(annotations / "0002_02_02.png", q1)
    _write_image(images / "0002.jpg", (96, 64))

    # A non-duo (single person) image that must be ignored.
    solo = np.zeros((64, 96), dtype=bool)
    solo[8:56, 8:88] = True
    _write_mask(annotations / "0003_01_01.png", solo)
    _write_image(images / "0003.jpg", (96, 64))


def test_real_source_mode_a_slice_runtime_pass(tmp_path: Path) -> None:
    harness = _load_harness()
    _build_dataset(tmp_path)

    document = harness.run_local_multi_person_mode_a_slice(
        tmp_path, limit=12, workdir=tmp_path / "_work"
    )

    assert document["proof_tier"] == "RUNTIME_PASS_BOUNDED"
    assert document["duo_count_processed"] == 2
    assert document["duo_pass_count"] == 2
    assert document["mode_a_reads_accepted_count"] == 2
    assert document["distinct_package_id_count"] == 2
    assert document["multi_person_gate_pass_count"] == 2
    assert document["bounded_ownership_integrity_count"] == 2
    # Synthetic fixtures are pixel-disjoint, so the stricter ideal also holds here.
    assert document["strict_zero_overlap_count"] == 2

    seeded = document["seeded_faults_all_blocked"]
    assert seeded["wrong_person_wrong_owner"] is True
    assert seeded["cross_instance_instance_mismatch"] is True

    # Every processed record must show real ownership distinctness and passing reads.
    for record in document["records"]:
        if record["status"] != "processed":
            continue
        assert record["distinct_ownership_masks"] is True
        assert record["bounded_ownership_integrity"] is True
        assert record["mode_a_reads"]["both_accepted"] is True
        assert record["mode_a_reads"]["transform_roundtrips_passed"] is True
        assert record["seeded_faults"]["wrong_person"]["rejected"] is True
        assert "wrong_owner" in record["seeded_faults"]["wrong_person"]["blocking_reason_codes"]
        assert record["seeded_faults"]["cross_instance"]["rejected"] is True
        assert (
            "instance_mismatch"
            in record["seeded_faults"]["cross_instance"]["blocking_reason_codes"]
        )
        assert record["overlap_px"] == 0

    # Solo image must never be treated as a duo.
    assert all(record["image_id"] != "0003" for record in document["records"])

    # Honest non-claims are always present and never inflated.
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

    # Self-seal must be internally consistent.
    recomputed = harness._sha_doc(
        {key: value for key, value in document.items() if key != "sha256"}
    )
    assert recomputed == document["sha256"]


def test_no_duos_raises(tmp_path: Path) -> None:
    harness = _load_harness()
    content = tmp_path / "LV-MHP-v1"
    (content / "annotations").mkdir(parents=True)
    (content / "images").mkdir(parents=True)
    solo = np.zeros((64, 64), dtype=bool)
    solo[4:60, 4:60] = True
    _write_mask(content / "annotations" / "0001_01_01.png", solo)
    _write_image(content / "images" / "0001.jpg", (64, 64))

    with pytest.raises(RuntimeError):
        harness.run_local_multi_person_mode_a_slice(tmp_path, limit=12, workdir=tmp_path / "_work")
