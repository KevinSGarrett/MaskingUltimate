import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from maskfactory.datasets.builder import _approved_packages
from maskfactory.ontology_v2 import build_ontology_v2
from maskfactory.ontology_v2_manifest import (
    DEFAULT_SCHEMA_V1,
    DEFAULT_SCHEMA_V2,
    OntologyV2ManifestError,
    build_manifest_v2_schema,
    manifest_v2_schema_is_current,
    migrate_v1_manifest_document,
    migrate_v1_manifest_file,
    require_v2_supervision_eligible,
    rollback_v2_manifest_file,
    v2_manifest_issues,
    v2_supervision_ineligibility,
)
from maskfactory.packager import _stamp_gold_manifest

SHA = "a" * 64
OTHER_SHA = "b" * 64


def _v1_manifest() -> dict:
    part_labels = [label for label in build_ontology_v2()["labels"] if label["map"] == "part"][:56]
    parts = {
        label["name"]: {
            "mask_type": label["mask_type"],
            "visibility": "n/a" if label["name"] == "background" else "not_visible",
            "mask_file": None,
            "mask_sha256": None,
            "mask_area_px": 0,
            "mask_bbox": None,
            "components": 0,
            "status": "n/a",
        }
        for label in part_labels
    }
    parts["left_forearm"].update(
        {
            "visibility": "visible",
            "mask_file": "masks/left_forearm.png",
            "mask_sha256": SHA,
            "mask_area_px": 4,
            "mask_bbox": [1, 1, 2, 2],
            "components": 1,
            "status": "human_approved_gold",
        }
    )
    return {
        "schema_version": "1.0.0",
        "image_id": "img_a3f9c2e17b04",
        "mask_ontology_version": "body_parts_v1",
        "left_right_convention": "character_perspective",
        "workflow_status": "approved_gold",
        "workflow_updated_at": "2026-07-09T15:03:22Z",
        "source": {
            "source_file": "source.png",
            "source_sha256": SHA,
            "parent_source_sha256": SHA,
            "source_width": 4,
            "source_height": 4,
            "source_origin": "generated",
            "origin_note": "fixture",
            "ingested_at": "2026-07-09T14:03:22Z",
            "exif_stripped": True,
        },
        "person": {
            "primary_person_bbox": [0, 0, 4, 4],
            "person_count": 1,
            "view": "front",
            "pose_tags": ["standing"],
            "estimated_person_height_px": 4,
        },
        "interperson": [],
        "parts": parts,
        "inpaint_derivatives": [],
        "tooling": {
            "annotation_tool": "cvat",
            "annotation_tool_version": "2.24.0",
            "pipeline_version": "maskfactory-test",
            "model_versions_used": {},
            "config_hashes": {"ontology.yaml": SHA},
        },
        "review": {
            "reviewer": "kevin",
            "approved_at": "2026-07-11T02:11:09Z",
            "second_review": {
                "required": False,
                "reviewer": None,
                "result": "not_required",
                "at": None,
            },
            "review_time_sec": 60,
        },
        "qa": {"qa_report_file": "qa_report.json", "qa_overall": "pass", "qa_score": 1.0},
        "files": {"source.png": SHA, "masks/left_forearm.png": SHA},
    }


def _fully_reviewed_v2() -> dict:
    manifest = migrate_v1_manifest_document(_v1_manifest())
    for name, entry in manifest["parts"].items():
        if entry["visibility"] in {"unreviewed_for_v2", "n/a"}:
            entry["visibility"] = "not_visible"
            entry["mask_file"] = None
            entry["mask_sha256"] = None
            entry["mask_area_px"] = 0
            entry["mask_bbox"] = None
            entry["components"] = 0
            entry["status"] = "n/a"
        entry["review_authority"] = {
            "reviewed": True,
            "reviewer": "kevin",
            "reviewed_at": "2026-07-13T20:00:00Z",
            "source": "human_review",
            "ontology_version": "body_parts_v2",
        }
    manifest["reviewed_ontology_version"] = "body_parts_v2"
    manifest["workflow_status"] = "approved_gold"
    return manifest


def test_v2_schema_is_separate_generated_and_v1_states_remain_unchanged() -> None:
    v1 = json.loads(DEFAULT_SCHEMA_V1.read_text(encoding="utf-8"))
    v2 = json.loads(DEFAULT_SCHEMA_V2.read_text(encoding="utf-8"))
    assert manifest_v2_schema_is_current()
    assert v2 == build_manifest_v2_schema()
    assert v2["properties"]["schema_version"] == {"const": "2.0.0"}
    assert v2["properties"]["mask_ontology_version"] == {"const": "body_parts_v2"}
    assert "reviewed_ontology_version" in v2["required"]
    for state in ("occluded_by_clothing", "not_applicable", "unreviewed_for_v2"):
        assert state in v2["$defs"]["visibility"]["enum"]
        assert state not in v1["$defs"]["visibility"]["enum"]


def test_v1_to_v2_migration_is_append_only_idempotent_and_non_authoritative() -> None:
    source = _v1_manifest()
    original = copy.deepcopy(source)
    migrated = migrate_v1_manifest_document(source)
    assert source == original
    assert migrated["schema_version"] == "2.0.0"
    assert migrated["mask_ontology_version"] == "body_parts_v2"
    assert migrated["reviewed_ontology_version"] == "body_parts_v1"
    assert migrated["workflow_status"] == "in_review"
    assert migrated["files"] == source["files"]
    assert v2_manifest_issues(migrated) == ()
    assert migrate_v1_manifest_document(migrated) == migrated
    additions = migrated["ontology_migration"]["added_labels"]
    assert len(additions) == 10
    for name in additions:
        entry = migrated["parts"][name]
        assert entry["visibility"] == "unreviewed_for_v2"
        assert entry["status"] == "unreviewed_for_v2"
        assert entry["mask_file"] is entry["mask_sha256"] is None
        assert entry["review_authority"] == {
            "reviewed": False,
            "reviewer": None,
            "reviewed_at": None,
            "source": "migrated_unreviewed",
            "ontology_version": "body_parts_v2",
        }
    assert migrated["parts"]["left_forearm"]["review_authority"]["ontology_version"] == (
        "body_parts_v1"
    )

    without_disabled_ears = _v1_manifest()
    del without_disabled_ears["parts"]["left_ear"]
    del without_disabled_ears["parts"]["right_ear"]
    ear_safe = migrate_v1_manifest_document(without_disabled_ears)
    assert ear_safe["parts"]["left_ear"]["visibility"] == "n/a"
    assert ear_safe["parts"]["left_ear"]["review_authority"]["reviewed"] is False


def test_v2_state_and_mask_invariants_fail_closed() -> None:
    migrated = migrate_v1_manifest_document(_v1_manifest())

    visible = copy.deepcopy(migrated)
    entry = visible["parts"]["left_areola"]
    entry.update(
        {
            "visibility": "visible",
            "mask_file": "masks/left_areola.png",
            "mask_sha256": OTHER_SHA,
            "mask_area_px": 1,
            "mask_bbox": [0, 0, 1, 1],
            "components": 1,
            "status": "draft_model_generated",
        }
    )
    visible["files"]["masks/left_areola.png"] = OTHER_SHA
    assert v2_manifest_issues(visible) == ()

    leaked = copy.deepcopy(migrated)
    leaked["parts"]["left_areola"].update(
        {"mask_file": "masks/leak.png", "mask_sha256": OTHER_SHA, "mask_area_px": 1}
    )
    assert any("null-mask state contains" in issue for issue in v2_manifest_issues(leaked))

    ambiguous = copy.deepcopy(migrated)
    ambiguous_entry = ambiguous["parts"]["left_areola"]
    ambiguous_entry.update(
        {
            "visibility": "ambiguous_do_not_use",
            "status": "n/a",
            "ambiguity_file": "masks_ignore/left_areola.png",
            "ambiguity_sha256": OTHER_SHA,
        }
    )
    ambiguous["files"]["masks_ignore/left_areola.png"] = OTHER_SHA
    assert v2_manifest_issues(ambiguous) == ()
    del ambiguous["files"]["masks_ignore/left_areola.png"]
    assert any("ignore mask is absent" in issue for issue in v2_manifest_issues(ambiguous))

    inferred = copy.deepcopy(migrated)
    inferred_entry = inferred["parts"]["vulva"]
    inferred_entry.update({"visibility": "not_applicable", "status": "n/a"})
    assert any(
        "not_applicable lacks human evidence" in issue for issue in v2_manifest_issues(inferred)
    )


@pytest.mark.parametrize(
    "state",
    [
        "visible",
        "partially_visible",
        "occluded",
        "occluded_by_clothing",
        "cropped_out",
        "not_visible",
        "not_applicable",
        "unreviewed_for_v2",
        "ambiguous_do_not_use",
    ],
)
def test_every_v2_review_state_has_an_explicit_valid_contract(state: str) -> None:
    manifest = migrate_v1_manifest_document(_v1_manifest())
    entry = manifest["parts"]["left_areola"]
    if state in {"visible", "partially_visible"}:
        entry.update(
            {
                "visibility": state,
                "mask_file": "masks/left_areola.png",
                "mask_sha256": OTHER_SHA,
                "mask_area_px": 1,
                "mask_bbox": [0, 0, 1, 1],
                "components": 1,
                "status": "draft_model_generated",
            }
        )
        manifest["files"]["masks/left_areola.png"] = OTHER_SHA
    elif state == "ambiguous_do_not_use":
        entry.update(
            {
                "visibility": state,
                "status": "n/a",
                "ambiguity_file": "masks_ignore/left_areola.png",
                "ambiguity_sha256": OTHER_SHA,
            }
        )
        manifest["files"]["masks_ignore/left_areola.png"] = OTHER_SHA
    elif state == "not_applicable":
        entry.update({"visibility": state, "status": "n/a"})
        entry["review_authority"] = {
            "reviewed": True,
            "reviewer": "kevin",
            "reviewed_at": "2026-07-13T20:00:00Z",
            "source": "human_review",
            "ontology_version": "body_parts_v2",
        }
    elif state != "unreviewed_for_v2":
        entry.update({"visibility": state, "status": "n/a"})
    assert v2_manifest_issues(manifest) == ()

    if state == "unreviewed_for_v2":
        entry["visibility"] = "n/a"
        assert any("unknown v2 review state" in issue for issue in v2_manifest_issues(manifest))


def test_v2_supervision_refuses_unreviewed_and_accepts_only_complete_human_authority() -> None:
    migrated = migrate_v1_manifest_document(_v1_manifest())
    reasons = v2_supervision_ineligibility(migrated)
    assert any("remains unreviewed_for_v2" in reason for reason in reasons)
    assert any("reviewed_ontology_version" in reason for reason in reasons)
    with pytest.raises(OntologyV2ManifestError, match="v2 supervision refused"):
        require_v2_supervision_eligible(migrated)

    reviewed = _fully_reviewed_v2()
    assert v2_supervision_ineligibility(reviewed) == ()
    require_v2_supervision_eligible(reviewed)
    reviewed["parts"]["left_areola"]["review_authority"]["reviewed"] = False
    with pytest.raises(OntologyV2ManifestError, match="left_areola"):
        require_v2_supervision_eligible(reviewed)


def test_alias_collision_dry_run_apply_tamper_refusal_and_exact_rollback(tmp_path: Path) -> None:
    colliding = _v1_manifest()
    colliding["parts"]["left_areola"] = copy.deepcopy(colliding["parts"]["left_forearm"])
    with pytest.raises(OntologyV2ManifestError, match="append-only label collision"):
        migrate_v1_manifest_document(colliding)

    manifest_path = tmp_path / "manifest.json"
    report_path = tmp_path / "migration_report.json"
    source_bytes = (json.dumps(_v1_manifest(), indent=2, sort_keys=True) + "\n").encode()
    manifest_path.write_bytes(source_bytes)
    dry = migrate_v1_manifest_file(manifest_path, report_path=report_path, dry_run=True)
    assert dry["mode"] == "dry_run"
    assert dry["pixel_files_changed"] is False
    assert manifest_path.read_bytes() == source_bytes

    applied = migrate_v1_manifest_file(manifest_path, report_path=report_path, dry_run=False)
    assert applied["applied"] is True
    target_bytes = manifest_path.read_bytes()
    assert target_bytes != source_bytes
    manifest_path.write_bytes(target_bytes + b" ")
    with pytest.raises(OntologyV2ManifestError, match="changed after migration"):
        rollback_v2_manifest_file(manifest_path, report_path=report_path)
    manifest_path.write_bytes(target_bytes)
    rolled_back = rollback_v2_manifest_file(manifest_path, report_path=report_path)
    assert rolled_back["rollback_result"] == "exact_source_bytes_restored"
    assert manifest_path.read_bytes() == source_bytes


def test_packager_and_dataset_paths_refuse_unreviewed_v2_authority(tmp_path: Path) -> None:
    package = tmp_path / "packages" / "p0"
    package.mkdir(parents=True)
    manifest_path = package / "manifest.json"
    migrated = migrate_v1_manifest_document(_v1_manifest())
    source_bytes = (json.dumps(migrated, indent=2, sort_keys=True) + "\n").encode()
    manifest_path.write_bytes(source_bytes)
    (package / ".maskfactory_frozen.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(OntologyV2ManifestError, match="v2 supervision refused"):
        _stamp_gold_manifest(
            package,
            "kevin",
            1.0,
            datetime(2026, 7, 13, 20, 0, tzinfo=UTC),
        )
    assert manifest_path.read_bytes() == source_bytes
    with pytest.raises(ValueError, match="frozen v2 package is ineligible"):
        _approved_packages(tmp_path / "packages")

    reviewed = _fully_reviewed_v2()
    reviewed["workflow_status"] = "in_review"
    manifest_path.write_text(
        json.dumps(reviewed, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _stamp_gold_manifest(
        package,
        "kevin",
        1.0,
        datetime(2026, 7, 13, 20, 0, tzinfo=UTC),
    )
    stamped = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert stamped["workflow_status"] == "approved_gold"
    require_v2_supervision_eligible(stamped)
    assert _approved_packages(tmp_path / "packages") == (package,)
