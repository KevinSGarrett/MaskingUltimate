from pathlib import Path
from types import SimpleNamespace

import numpy as np
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.datasets.active_learning import run_active_learning
from maskfactory.datasets.builder import build_dataset
from maskfactory.fusion.consensus import fuse_consensus as public_fuse_consensus
from maskfactory.fusion.zorder import ZOrderDecision, apply_zorder
from maskfactory.intake import ingest_one
from maskfactory.io.hashing import sha256_bytes, sha256_file, sha256_file_map, verify_file_map
from maskfactory.io.readers import read_json, read_label_map, read_rgb
from maskfactory.io.writers import write_json_atomic, write_label_map
from maskfactory.packager import approve_package
from maskfactory.qa.production import run_s10_production
from maskfactory.review_package import assemble_review_package
from maskfactory.stages.s00_intake import run_s00
from maskfactory.stages.s09_fusion import fuse_consensus
from maskfactory.stages.s10_autoqa import run_s10
from maskfactory.stages.s11_vlmqa import run_s11
from maskfactory.stages.s12_review import run_s12
from maskfactory.stages.s13_export import run_s13
from maskfactory.stages.s14_dataset import run_s14
from maskfactory.stages.s15_active_learning import run_s15
from maskfactory.vlm.production import run_s11_production


def test_stage_boundary_entries_delegate_to_production_implementations() -> None:
    assert run_s00 is ingest_one
    assert run_s10 is run_s10_production
    assert run_s11 is run_s11_production
    assert run_s12 is assemble_review_package
    assert run_s13 is approve_package
    assert run_s14 is build_dataset
    assert run_s15 is run_active_learning
    assert public_fuse_consensus is fuse_consensus


def test_vlmqa_group_exposes_production_commands_without_scaffold_output() -> None:
    result = CliRunner().invoke(main, ["vlmqa"])
    assert result.exit_code == 0
    assert "build-calibration" in result.output
    assert "eval" in result.output
    assert "stub" not in result.output.lower()


def test_public_zorder_boundary_arbitrates_and_records_contested_pixels() -> None:
    stack = np.full((2, 3, 3), 0.8, dtype=np.float32)
    contested = np.zeros((3, 3), dtype=bool)
    contested[1, 1] = True

    class Authority:
        @staticmethod
        def label(name: str):
            if name not in {"left_forearm", "right_forearm"}:
                raise KeyError(name)
            return SimpleNamespace(name=name)

    records = apply_zorder(
        stack,
        ("left_forearm", "right_forearm"),
        contested,
        (ZOrderDecision("left_forearm", "right_forearm", "depth_cue"),),
        Authority(),
    )

    assert stack[0, 1, 1] > 1
    assert stack[1, 1, 1] == np.float32(0.8)
    assert len(records) == 1
    assert records[0].occluding_part == "left_forearm"
    assert records[0].occluded_part == "right_forearm"
    assert records[0].contested_pixels == 1


def test_public_zorder_boundary_rejects_geometry_and_missing_labels() -> None:
    stack = np.ones((2, 2, 2), dtype=np.float32)
    authority = SimpleNamespace(label=lambda name: SimpleNamespace(name=name))
    with np.testing.assert_raises_regex(ValueError, "geometry"):
        apply_zorder(stack, ("left", "right"), np.zeros((3, 3), bool), (), authority)
    with np.testing.assert_raises_regex(ValueError, "missing from evidence"):
        apply_zorder(
            stack,
            ("left", "right"),
            np.ones((2, 2), bool),
            (ZOrderDecision("missing", "right", "bad"),),
            authority,
        )


def test_io_boundaries_hash_explicit_package_files_and_detect_drift(tmp_path: Path) -> None:
    first = tmp_path / "a.bin"
    second = tmp_path / "nested" / "b.bin"
    second.parent.mkdir()
    first.write_bytes(b"alpha")
    second.write_bytes(b"beta")

    hashes = sha256_file_map(tmp_path, (second, first))

    assert list(hashes) == ["a.bin", "nested/b.bin"]
    assert hashes["a.bin"] == sha256_bytes(b"alpha") == sha256_file(first)
    assert verify_file_map(tmp_path, hashes) == ()
    second.write_bytes(b"changed")
    assert verify_file_map(tmp_path, hashes) == ("hash_mismatch:nested/b.bin",)
    with np.testing.assert_raises_regex(ValueError, "escapes root"):
        sha256_file_map(tmp_path, (tmp_path.parent / "outside.bin",))


def test_io_boundaries_roundtrip_atomic_json_maps_and_rgb(tmp_path: Path) -> None:
    document_path = write_json_atomic(tmp_path / "state" / "document.json", {"value": 7})
    assert read_json(document_path, require_object=True) == {"value": 7}
    assert not tuple(document_path.parent.glob("*.tmp"))

    map8 = np.asarray([[0, 1], [2, 255]], dtype=np.uint8)
    map16 = np.asarray([[0, 256], [55, 65535]], dtype=np.uint16)
    write_label_map(tmp_path / "map8.png", map8, bits=8)
    write_label_map(tmp_path / "map16.png", map16, bits=16)
    assert np.array_equal(read_label_map(tmp_path / "map8.png", bits=8), map8)
    assert np.array_equal(read_label_map(tmp_path / "map16.png", bits=16), map16)

    Image.new("RGB", (3, 2), (10, 20, 30)).save(tmp_path / "source.png")
    rgb = read_rgb(tmp_path / "source.png")
    assert rgb.shape == (2, 3, 3)
    assert rgb[0, 0].tolist() == [10, 20, 30]
