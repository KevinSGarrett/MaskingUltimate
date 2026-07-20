"""Hermetic guard for the real-source multi-person bounded-runtime harness.

Builds a tiny synthetic LV-MHP-shaped duo dataset (contact + non-contact) so the
harness logic (real gate execution, contact-band derivation, seeded-fault
blocking, self-seal) is regression-locked without requiring the on-disk
MaskedWarehouse dataset.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "run_local_multi_person_source_slice.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("_lmps_harness", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_mask(path: Path, array: np.ndarray) -> None:
    Image.fromarray((array.astype(np.uint8) * 15)).save(path)


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

    # Duo 0002: far apart (no contact).
    q0 = np.zeros((64, 96), dtype=bool)
    q1 = np.zeros((64, 96), dtype=bool)
    q0[8:24, 4:20] = True
    q1[40:56, 76:92] = True
    _write_mask(annotations / "0002_02_01.png", q0)
    _write_mask(annotations / "0002_02_02.png", q1)

    # A non-duo (single person) image that must be ignored.
    solo = np.zeros((64, 96), dtype=bool)
    solo[8:56, 8:88] = True
    _write_mask(annotations / "0003_01_01.png", solo)

    for stem in ("0001", "0002", "0003"):
        (images / f"{stem}.jpg").write_bytes(b"\xff\xd8\xff\xd9")


def test_real_source_slice_runtime_pass(tmp_path: Path) -> None:
    harness = _load_harness()
    _build_dataset(tmp_path)

    document = harness.run_local_multi_person_source_slice(tmp_path, limit=12)

    assert document["proof_tier"] == "RUNTIME_PASS_BOUNDED"
    assert document["duo_count_processed"] == 2
    assert document["clean_gate_pass_count"] == 2
    assert document["contact_clean_pass_count"] == 1
    assert document["noncontact_clean_pass_count"] == 1

    seeded = document["seeded_faults_all_blocked"]
    assert seeded["exclusivity_overlap_qc035"] is True
    assert seeded["cross_instance_bleed_qc036"] is True
    assert seeded["bleed_containment_aut_mp_001"] is True
    assert seeded["contact_nonreciprocity_aut_mp_002"] is True

    # Solo image must never be treated as a duo.
    assert all(record["image_id"] != "0003" for record in document["records"])

    # Honest non-claims are always present and never inflated.
    for flag in (
        "mf_p8_11_07_demo_complete",
        "gold_claimed",
        "champions_claimed",
        "doctor_green_claimed",
        "production_evidence_pass_claimed",
        "kevin_governed_multi_person_sources_used",
    ):
        assert document[flag] is False

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
    solo = np.zeros((32, 32), dtype=bool)
    solo[4:28, 4:28] = True
    _write_mask(content / "annotations" / "0001_01_01.png", solo)
    (content / "images" / "0001.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    with pytest.raises(RuntimeError):
        harness.run_local_multi_person_source_slice(tmp_path, limit=12)
