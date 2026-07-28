import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.derive import derive_package
from maskfactory.fusion.mapbuild import export_binaries
from maskfactory.io.png_strict import read_mask, write_binary_mask, write_label_map
from maskfactory.ontology import get_ontology
from maskfactory.qa.checks import run_qc001_010
from maskfactory.state import initialize_database, reader_connection, writer_connection
from maskfactory.versioning import (
    VersioningError,
    begin_correction,
    promote_correction,
    refresh_correction_branch,
)
from test_manifest_schema import valid_manifest


def _refresh_hashes(package: Path) -> None:
    path = package / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["files"] = {
        file.relative_to(package).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in package.rglob("*")
        if file.is_file() and file.name != "manifest.json"
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")


def _frozen_package(tmp_path: Path) -> Path:
    package = tmp_path / "package"
    package.mkdir()
    source = package / "source.png"
    Image.fromarray(np.zeros((48, 64, 3), dtype=np.uint8)).save(source)
    part = np.zeros((48, 64), dtype=np.uint16)
    material = np.zeros((48, 64), dtype=np.uint8)
    part[10:35, 15:28] = 18
    material[10:35, 15:28] = 1
    write_label_map(package / "label_map_part.png", part, bits=16)
    write_label_map(package / "label_map_material.png", material, bits=8)
    export_binaries(package)
    derive_package(package)
    manifest = valid_manifest()
    manifest["source"].update(
        {
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "parent_source_sha256": "a" * 64,
            "source_width": 64,
            "source_height": 48,
        }
    )
    manifest["person"].update(
        {"primary_person_bbox": [5, 5, 55, 43], "estimated_person_height_px": 38}
    )
    manifest["interperson"] = []
    manifest["inpaint_derivatives"] = []
    manifest["parts"] = {
        label.name: {
            "mask_type": label.mask_type,
            "visibility": "not_visible",
            "mask_file": None,
            "status": "n/a",
        }
        for label in get_ontology().labels
        if label.enabled and label.map != "material"
    }
    left = package / "masks/left_forearm.png"
    manifest["parts"]["left_forearm"] = {
        "mask_type": "atomic_exclusive",
        "visibility": "visible",
        "mask_file": "masks/left_forearm.png",
        "mask_sha256": hashlib.sha256(left.read_bytes()).hexdigest(),
        "mask_area_px": 325,
        "mask_bbox": [15, 10, 28, 35],
        "components": 1,
        "status": "human_approved_gold",
        "annotated_on": "full",
        "occlusion": {"occluded_by": [], "occludes": [], "layer": "front_layer"},
        "provenance": {
            "draft_source": "fusion_v1",
            "sam2_prompt_id": None,
            "human_edit": False,
        },
        "notes": "",
    }
    manifest["files"] = {}
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (package / ".maskfactory_frozen.json").write_text(
        json.dumps({"schema_version": "1.0.0", "active_mask_version": 1}), encoding="utf-8"
    )
    _refresh_hashes(package)
    results = run_qc001_010(package)
    assert all(result.passed for result in results), results
    return package


def _database(path: Path, *, status: str = "exported") -> None:
    initialize_database(path)
    with writer_connection(path) as connection:
        connection.execute(
            "INSERT INTO images "
            "(image_id, source_sha256, status, current_stage, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("img_a3f9c2e17b04", "a" * 64, status, "S14", "t0", "t0"),
        )


def _edit_candidate_map(candidate: Path) -> None:
    part = read_mask(candidate / "label_map_part.png").astype(np.uint16)
    part[10, 15] = 0
    write_label_map(candidate / "label_map_part.png", part, bits=16)


def test_real_map_correction_promotes_reseals_and_synchronizes_sqlite(tmp_path: Path) -> None:
    package = _frozen_package(tmp_path)
    database = tmp_path / "state.sqlite"
    _database(database)
    original = read_mask(package / "label_map_part.png")
    candidate = begin_correction(package, now=datetime(2026, 7, 11, tzinfo=UTC))
    assert (candidate / "label_map_part.png").is_file()
    assert (candidate / "masks/left_forearm.png").is_file()
    _edit_candidate_map(candidate)
    refresh_correction_branch(package, 2)
    dvc_paths = []
    promoted_at = datetime(2026, 7, 12, tzinfo=UTC)
    promote_correction(
        package,
        2,
        human_approved=True,
        reviewer="kevin",
        review_minutes=4.5,
        database=database,
        dvc_add=dvc_paths.append,
        now=promoted_at,
    )

    active = read_mask(package / "label_map_part.png")
    assert not np.array_equal(active, original) and active[10, 15] == 0
    assert np.array_equal(read_mask(package / "masks@v1/label_map_part.png"), original)
    registry = json.loads((package / "mask_versions.json").read_text(encoding="utf-8"))
    assert registry["active_version"] == 2
    assert registry["versions"]["1"]["status"] == "deprecated"
    assert registry["versions"]["1"]["retain_until"] == "2026-08-11T00:00:00+00:00"
    assert registry["versions"]["2"]["status"] == "human_approved_gold"
    assert registry["versions"]["1"]["files"]["label_map_part.png"]
    assert registry["versions"]["2"]["files"]["label_map_part.png"]
    assert not (package / "masks@v2").exists()
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["workflow_status"] == "approved_gold"
    assert manifest["review"]["reviewer"] == "kevin"
    assert manifest["review"]["review_time_sec"] == 270
    assert manifest["parts"]["left_forearm"]["provenance"]["human_edit"] is True
    assert all(result.passed for result in run_qc001_010(package))
    assert dvc_paths == [package]
    with reader_connection(database) as connection:
        row = connection.execute(
            "SELECT status, current_stage, updated_at FROM images WHERE image_id = ?",
            ("img_a3f9c2e17b04",),
        ).fetchone()
    assert tuple(row) == ("approved_gold", "S13", "2026-07-12T00:00:00+00:00")


def test_binary_tamper_is_rejected_before_promotion(tmp_path: Path) -> None:
    package = _frozen_package(tmp_path)
    candidate = begin_correction(package)
    tampered = read_mask(candidate / "masks/left_forearm.png")
    tampered[0, 0] = 255
    write_binary_mask(candidate / "masks/left_forearm.png", tampered)
    assert all(result.passed for result in run_qc001_010(package))
    before = {
        path.relative_to(package).as_posix(): path.read_bytes()
        for path in package.rglob("*")
        if path.is_file()
    }
    with pytest.raises(VersioningError, match="candidate correction branch is invalid"):
        promote_correction(package, 2, human_approved=True)
    after = {
        path.relative_to(package).as_posix(): path.read_bytes()
        for path in package.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_dvc_failure_restores_package_and_rolls_back_sqlite(tmp_path: Path) -> None:
    package = _frozen_package(tmp_path)
    database = tmp_path / "state.sqlite"
    _database(database, status="approved_gold")
    candidate = begin_correction(package)
    _edit_candidate_map(candidate)
    refresh_correction_branch(package, 2)
    before = {
        path.relative_to(package).as_posix(): path.read_bytes()
        for path in package.rglob("*")
        if path.is_file()
    }

    def fail_dvc(_path: Path) -> None:
        raise RuntimeError("seeded DVC failure")

    with pytest.raises(RuntimeError, match="seeded DVC failure"):
        promote_correction(
            package,
            2,
            human_approved=True,
            database=database,
            dvc_add=fail_dvc,
        )
    after = {
        path.relative_to(package).as_posix(): path.read_bytes()
        for path in package.rglob("*")
        if path.is_file()
    }
    assert after == before
    with reader_connection(database) as connection:
        status = connection.execute(
            "SELECT status FROM images WHERE image_id = ?", ("img_a3f9c2e17b04",)
        ).fetchone()[0]
    assert status == "approved_gold"


def test_correction_cli_runs_the_governed_operator_flow(tmp_path: Path, monkeypatch) -> None:
    packages = tmp_path / "packages"
    package = _frozen_package(tmp_path)
    target = packages / "img_a3f9c2e17b04" / "instances" / "p0"
    target.parent.mkdir(parents=True)
    package.rename(target)
    database = tmp_path / "state.sqlite"
    _database(database, status="approved_gold")
    runner = CliRunner()
    common = ["--instance", "p0", "--root", str(packages)]
    begun = runner.invoke(main, ["correction", "begin", "img_a3f9c2e17b04", *common])
    assert begun.exit_code == 0, begun.output
    _edit_candidate_map(target / "masks@v2")
    refreshed = runner.invoke(
        main,
        [
            "correction",
            "refresh",
            "img_a3f9c2e17b04",
            *common,
            "--version",
            "2",
        ],
    )
    assert refreshed.exit_code == 0, refreshed.output
    dvc_calls = []

    def run_dvc(args, **kwargs):
        dvc_calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("maskfactory.dvc_runtime.run_dvc", run_dvc)
    promoted = runner.invoke(
        main,
        [
            "correction",
            "promote",
            "img_a3f9c2e17b04",
            *common,
            "--version",
            "2",
            "--reviewer",
            "kevin",
            "--minutes",
            "3",
            "--database",
            str(database),
        ],
        input="y\n",
    )
    assert promoted.exit_code == 0, promoted.output
    assert dvc_calls[0][0][0] == "add"
    assert dvc_calls[0][1]["timeout"] == 300
