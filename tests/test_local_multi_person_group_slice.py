"""Hermetic guard for the real-source multi-body group bounded-runtime harness.

Builds a tiny synthetic LV-MHP-shaped dataset with a duo, a trio, and a quad
(each with real contact geometry plus a non-contact neighbor) so the group
harness logic (small-group gate execution over N>2 promoted instances, pairwise
contact-band derivation, seeded-fault blocking, self-seal) is regression-locked
without requiring the on-disk MaskedWarehouse dataset.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "run_local_multi_person_group_slice.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("_lmpg_harness", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_mask(path: Path, array: np.ndarray) -> None:
    Image.fromarray((array.astype(np.uint8) * 15)).save(path)


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

    # Trio 0101: p0-p1 touch; p2 is far (chain with one non-contact pair).
    _write_mask(annotations / "0101_03_01.png", _block(slice(8, 56), slice(4, 28)))
    _write_mask(annotations / "0101_03_02.png", _block(slice(8, 56), slice(30, 54)))
    _write_mask(annotations / "0101_03_03.png", _block(slice(8, 56), slice(80, 94)))

    # Quad 0102: 2x2 grid of pixel-disjoint blocks with multiple contacts.
    _write_mask(annotations / "0102_04_01.png", _block(slice(6, 30), slice(4, 28)))
    _write_mask(annotations / "0102_04_02.png", _block(slice(6, 30), slice(30, 54)))
    _write_mask(annotations / "0102_04_03.png", _block(slice(34, 58), slice(4, 28)))
    _write_mask(annotations / "0102_04_04.png", _block(slice(34, 58), slice(30, 54)))

    # A single-person image that must be ignored by every requested group size.
    _write_mask(annotations / "0104_01_01.png", _block(slice(8, 56), slice(8, 88)))

    for stem in ("0101", "0102", "0103", "0104"):
        (images / f"{stem}.jpg").write_bytes(b"\xff\xd8\xff\xd9")


def test_group_slice_runtime_pass_across_sizes(tmp_path: Path) -> None:
    harness = _load_harness()
    _build_dataset(tmp_path)

    document = harness.run_local_multi_person_group_slice(
        tmp_path, sizes=(2, 3, 4), limit_per_size=8
    )

    assert document["proof_tier"] == "RUNTIME_PASS_BOUNDED"
    assert document["small_group_context_exercised"] is True
    assert document["group_count_processed"] == 3
    assert document["clean_gate_pass_count"] == 3

    per_size = document["per_size_breakdown"]
    assert per_size["2"] == {"processed": 1, "clean_gate_pass": 1, "contact_clean_pass": 1}
    assert per_size["3"] == {"processed": 1, "clean_gate_pass": 1, "contact_clean_pass": 1}
    assert per_size["4"] == {"processed": 1, "clean_gate_pass": 1, "contact_clean_pass": 1}

    seeded = document["seeded_faults_all_blocked"]
    assert seeded["exclusivity_overlap_qc035"] is True
    assert seeded["cross_instance_bleed_qc036"] is True
    assert seeded["bleed_containment_aut_mp_001"] is True
    assert seeded["contact_nonreciprocity_aut_mp_002"] is True

    # The trio must expose exactly one contacting pair (p0-p1) and one non-contact pair.
    trio = next(record for record in document["records"] if record["size"] == 3)
    assert trio["contact_pair_count"] == 1
    assert len(trio["pair_metrics"]) == 3

    # The quad exercises the small-group context with more than one contact pair.
    quad = next(record for record in document["records"] if record["size"] == 4)
    assert quad["contact_pair_count"] >= 2
    assert len(quad["annotation_sha256"]) == 4

    # Solo image must never be treated as a group of any requested size.
    assert all(record["image_id"] != "0104" for record in document["records"])

    for flag in (
        "mf_p8_11_07_demo_complete",
        "gold_claimed",
        "champions_claimed",
        "doctor_green_claimed",
        "production_evidence_pass_claimed",
        "kevin_governed_multi_person_sources_used",
    ):
        assert document[flag] is False

    recomputed = harness._sha_doc(
        {key: value for key, value in document.items() if key != "sha256"}
    )
    assert recomputed == document["sha256"]


def test_group_slice_no_groups_raises(tmp_path: Path) -> None:
    harness = _load_harness()
    content = tmp_path / "LV-MHP-v1"
    (content / "annotations").mkdir(parents=True)
    (content / "images").mkdir(parents=True)
    _write_mask(
        content / "annotations" / "0001_01_01.png", _block(slice(4, 28), slice(4, 28), (32, 32))
    )
    (content / "images" / "0001.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    with pytest.raises(RuntimeError):
        harness.run_local_multi_person_group_slice(tmp_path, sizes=(2, 3, 4), limit_per_size=8)
