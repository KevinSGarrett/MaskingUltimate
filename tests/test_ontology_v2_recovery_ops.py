import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.datasets.builder import (
    _approved_packages,
    plan_dataset_publication,
)
from maskfactory.gc import apply_gc_plan, build_gc_plan
from maskfactory.ontology_v2_operations import (
    EXPECTED_OPERATIONS_POLICY,
    load_v2_operations_policy,
    run_v2_restore_integrity,
)
from maskfactory.packager import verify_packages
from maskfactory.reindex import reindex_packages, run_reindex_incident_drill
from maskfactory.state import initialize_database
from test_ontology_v2_migration import _fully_reviewed_v2

NOW = datetime(2026, 7, 13, tzinfo=UTC)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_v2_package(root: Path) -> tuple[Path, dict]:
    package = root / "img_a3f9c2e17b04" / "instances" / "p0"
    (package / "masks").mkdir(parents=True)
    Image.new("RGB", (4, 4), "gray").save(package / "source.png")
    mask = np.zeros((4, 4), dtype=np.uint8)
    mask[1:3, 1:3] = 255
    Image.fromarray(mask, mode="L").save(package / "masks/left_forearm.png")
    (package / "qa_report.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "ontology_version": "body_parts_v2",
                "activation_status": "approved_design_not_active",
                "overall": "pass",
                "production_activation_granted": False,
            }
        ),
        encoding="utf-8",
    )
    (package / ".maskfactory_frozen.json").write_text(
        json.dumps({"policy": "fixture immutable"}), encoding="utf-8"
    )
    manifest = _fully_reviewed_v2()
    source_sha = _sha(package / "source.png")
    mask_sha = _sha(package / "masks/left_forearm.png")
    manifest["source"].update(
        {
            "source_file": "source.png",
            "source_sha256": source_sha,
            "parent_source_sha256": source_sha,
            "source_width": 4,
            "source_height": 4,
        }
    )
    manifest["parts"]["left_forearm"].update(
        {
            "mask_file": "masks/left_forearm.png",
            "mask_sha256": mask_sha,
            "mask_area_px": 4,
            "mask_bbox": [1, 1, 2, 2],
            "components": 1,
            "status": "human_approved_gold",
        }
    )
    manifest["qa"].update(
        {"qa_report_file": "qa_report.json", "qa_overall": "pass", "qa_score": 1.0}
    )
    manifest["files"] = {
        path.relative_to(package).as_posix(): _sha(path)
        for path in sorted(package.rglob("*"))
        if path.is_file()
    }
    (package / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return package, manifest


def test_v2_operations_policy_is_exact_and_inactive() -> None:
    policy = load_v2_operations_policy()
    assert policy["operations"] == EXPECTED_OPERATIONS_POLICY
    assert policy["activation_status"] == "approved_design_not_active"
    assert policy["operations"]["incident_drills"]["production_mutation_allowed"] is False


def test_v2_restore_verifier_dispatches_and_detects_tampering(tmp_path: Path) -> None:
    package, _ = _write_v2_package(tmp_path / "packages")
    results = run_v2_restore_integrity(package)
    assert tuple(result.qc_id for result in results) == tuple(
        f"OPS-V2-{index:03d}" for index in range(1, 6)
    )
    assert all(result.passed for result in results), [result.detail for result in results]
    dispatched = verify_packages(package)
    assert dispatched[0].passed is True
    assert dispatched[0].results == results

    (package / "masks/left_forearm.png").write_bytes(b"tampered")
    failed = run_v2_restore_integrity(package)
    assert failed[1].passed is False
    assert "mismatch=['masks/left_forearm.png']" in failed[1].detail
    assert failed[2].passed is False


def test_v2_reindex_and_copy_only_incident_drill_use_manifest_v2(tmp_path: Path) -> None:
    packages = tmp_path / "packages"
    package, manifest = _write_v2_package(packages)
    database = tmp_path / "state.sqlite"
    initialize_database(database)
    before = reindex_packages(packages_root=packages, database=database, dry_run=True)
    assert before.missing_in_db == (manifest["image_id"],)
    reindex_packages(packages_root=packages, database=database, dry_run=False)
    assert reindex_packages(packages_root=packages, database=database, dry_run=True).clean

    source_before = database.read_bytes()
    report_path = run_reindex_incident_drill(
        source_database=database,
        packages_root=packages,
        output_dir=tmp_path / "incident",
        now=NOW,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["source_untouched"] is True
    assert report["after_rebuild"]["clean"] is True
    assert database.read_bytes() == source_before
    assert package.is_dir()


def test_gc_sandbox_removes_only_expired_deprecated_v2_mask_version(tmp_path: Path) -> None:
    package, _ = _write_v2_package(tmp_path / "packages")
    (package / "masks_ignore").mkdir()
    (package / "masks_ignore/ambiguous.png").write_bytes(b"protected ambiguity")
    (package / "masks@v1").mkdir()
    (package / "masks@v1/old.png").write_bytes(b"expired old version")
    (package / "mask_versions.json").write_text(
        json.dumps(
            {
                "active_version": 2,
                "versions": {
                    "1": {
                        "status": "deprecated",
                        "directory": "masks@v1",
                        "retain_until": "2026-06-01T00:00:00+00:00",
                    },
                    "2": {"status": "human_approved_gold", "directory": "masks"},
                },
            }
        ),
        encoding="utf-8",
    )
    plan = build_gc_plan(tmp_path / "packages", now=NOW)
    assert [(item.relative_path, item.version) for item in plan.candidates] == [("masks@v1", 1)]
    removed = apply_gc_plan(plan, packages_root=tmp_path / "packages")
    assert removed == (package / "masks@v1",)
    assert (package / "masks/left_forearm.png").is_file()
    assert (package / "masks_ignore/ambiguous.png").is_file()
    assert (package / "manifest.json").is_file()


def test_dataset_selection_is_ontology_specific_and_publication_never_reuses_tag(
    tmp_path: Path,
) -> None:
    packages = tmp_path / "packages"
    v2_package, _ = _write_v2_package(packages)
    v1_package = packages / "img_b3f9c2e17b04/instances/p0"
    v1_package.mkdir(parents=True)
    (v1_package / ".maskfactory_frozen.json").write_text("{}", encoding="utf-8")
    (v1_package / "manifest.json").write_text(
        json.dumps(
            {
                "image_id": "img_b3f9c2e17b04",
                "mask_ontology_version": "body_parts_v1",
                "parts": {"left_forearm": {"status": "human_approved_gold"}},
            }
        ),
        encoding="utf-8",
    )
    assert _approved_packages(packages, ontology_version="body_parts_v2") == (v2_package,)
    assert _approved_packages(packages, ontology_version="body_parts_v1") == (v1_package,)

    output = tmp_path / "datasets"
    (output / "bodyparts@v1").mkdir(parents=True)
    plan = plan_dataset_publication(output, ontology_version="body_parts_v2")
    assert plan.version == 2
    assert plan.destination.name == "bodyparts@v2"
    assert plan.git_tag == "dataset/bodyparts-v2"
    try:
        plan_dataset_publication(
            output,
            ontology_version="body_parts_v2",
            existing_tags=("dataset/bodyparts-v2",),
        )
    except FileExistsError as exc:
        assert "cannot be rewritten" in str(exc)
    else:
        raise AssertionError("existing immutable dataset tag was accepted")


def test_dataset_cli_accepts_explicit_v2_without_activation_or_publish(
    tmp_path: Path, monkeypatch
) -> None:
    captured = {}
    monkeypatch.setattr(
        "maskfactory.datasets.builder.approved_package_count",
        lambda _root, *, ontology_version=None: 200 if ontology_version == "body_parts_v2" else 0,
    )

    def fake_build_dataset(**kwargs):
        captured.update(kwargs)
        return kwargs["output_root"] / f"bodyparts@v{kwargs['version']}"

    monkeypatch.setattr("maskfactory.datasets.builder.build_dataset", fake_build_dataset)
    result = CliRunner().invoke(
        main,
        [
            "dataset",
            "build",
            "--ontology",
            "body_parts_v2",
            "--packages-root",
            str(tmp_path / "packages"),
            "--output-root",
            str(tmp_path / "datasets"),
            "--no-publish",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["ontology_version"] == "body_parts_v2"
    assert captured["version"] == 1
    assert "bodyparts@v1" in result.output
