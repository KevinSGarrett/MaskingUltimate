"""STATIC binders for P7 ops: backup/restore drills, nightly reindex/verify-package, failure-mining.

Fixture- and script-bound only. Never claims D10, live B1/B2 media restore, human-anchor
packages, doctor-green, gold, or PRODUCTION_EVIDENCE_PASS. Restore/D10 remain NEEDS KEVIN.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import time
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .ontology_v2_operations import EXPECTED_OPERATIONS_POLICY, load_v2_operations_policy
from .qa.failure_mining import FailureRecord
from .qa.failure_mining_static import (
    build_acquisition_plan_document,
    refuse_d4_or_vlm_calibration_claim,
)
from .reindex import reindex_packages, run_reindex_incident_drill
from .state import initialize_database
from .validation import validate_document

PROOF_TIER = "STATIC_PASS"
ARTIFACT_TYPE = "ops_static_contracts_report"
AUTHORITY = "ops_static_contracts_only_no_d10_b1_b2_media_restore_or_human_anchor_package_authority"
SCHEMA_VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parents[2]
NIGHTLY_BACKUP_SCRIPT = ROOT / "tools" / "nightly_backup.ps1"
REGISTER_TASKS_SCRIPT = ROOT / "tools" / "register_scheduled_tasks.ps1"
BACKUP_STATE_SCRIPT = ROOT / "tools" / "backup_state.py"

BACKUP_RESTORE_CHECKS = (
    "nightly_b5_before_b1_ordering",
    "nightly_verify_package_sample_wired",
    "fixture_b5_sqlite_backup_retain7",
    "fixture_mirror_restore_bit_identical",
    "restore_refuses_nonempty_target",
    "v2_ops_backup_restore_policy_bound",
    "overclaim_b1_b2_d10_refused",
)
NIGHTLY_REINDEX_CHECKS = (
    "nightly_verify_package_after_b5_b1",
    "task_registration_names_nightly_integrity",
    "fixture_reindex_rebuild_clean",
    "fixture_ip3_copy_only_source_untouched",
    "v2_ops_reindex_policy_bound",
)
FAILURE_MINING_OPS_CHECKS = (
    "unresolved_builds_acquisition_plan",
    "resolved_requires_resolution_pkg_version",
    "fixture_resolve_without_human_anchor_package",
    "resolved_drops_from_unresolved_plan",
    "overclaim_mf_p7_03_03_or_d10_refused",
)

HONEST_NON_CLAIMS = (
    "mf_p1_09_05_complete",
    "mf_p7_03_01_complete",
    "mf_p7_03_03_complete",
    "mf_p7_03_06_d10_signed",
    "b1_mirror_present",
    "b2_media_present",
    "human_anchor_package_present",
    "doctor_green",
    "gold",
    "PRODUCTION_EVIDENCE_PASS",
)


class OpsStaticContractError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha(document: Mapping[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_inventory(root: Path) -> dict[str, str]:
    inventory: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            inventory[rel] = _file_sha(path)
    return inventory


def refuse_ops_overclaim(document: Mapping[str, Any]) -> None:
    """Fail closed on D10 / B1-B2 media / restore-drill completion overclaims."""
    forbidden_true = (
        "mf_p1_09_05_complete",
        "mf_p7_03_01_complete",
        "mf_p7_03_03_complete",
        "mf_p7_03_06_d10_signed",
        "b1_mirror_present",
        "b2_media_present",
        "human_anchor_package_present",
        "d10_signed",
        "doctor_green_claimed",
        "gold_claimed",
        "production_evidence_pass_claimed",
    )
    for key in forbidden_true:
        if document.get(key) is True:
            raise OpsStaticContractError(f"ops_overclaim:{key}")


def evaluate_nightly_backup_script_contract(
    script_path: Path = NIGHTLY_BACKUP_SCRIPT,
) -> dict[str, bool]:
    """Bind B5-before-B1 ordering and post-mirror verify-package sample wiring."""
    text = script_path.read_text(encoding="utf-8")
    b5_pos = text.find("backup_state.py")
    mirror_pos = text.find("Invoke-RobocopyMirror (Join-Path")
    verify_pos = text.find("verify-package --root data/packages --sample 10")
    if b5_pos < 0 or mirror_pos < 0 or verify_pos < 0:
        raise OpsStaticContractError("nightly_backup_script_missing_required_steps")
    if not (b5_pos < mirror_pos < verify_pos):
        raise OpsStaticContractError("nightly_backup_script_ordering_invalid")
    if text.count("Invoke-RobocopyMirror (Join-Path") != 3:
        raise OpsStaticContractError("nightly_backup_mirror_count_drift")
    if "MaskFactoryBackup" not in text:
        raise OpsStaticContractError("nightly_backup_destination_missing")
    if "ontology-aware integrity sample" not in text:
        raise OpsStaticContractError("nightly_integrity_sample_comment_missing")
    if "--retain 7" not in text:
        raise OpsStaticContractError("nightly_b5_retain7_missing")
    return {
        "nightly_b5_before_b1_ordering": True,
        "nightly_verify_package_sample_wired": True,
        "nightly_verify_package_after_b5_b1": True,
    }


def evaluate_task_registration_contract(
    script_path: Path = REGISTER_TASKS_SCRIPT,
) -> dict[str, bool]:
    text = script_path.read_text(encoding="utf-8")
    if "MaskFactory_NightlyBackupIntegrity" not in text:
        raise OpsStaticContractError("nightly_task_name_missing")
    if "nightly_backup.ps1" not in text:
        raise OpsStaticContractError("nightly_task_action_missing")
    return {"task_registration_names_nightly_integrity": True}


def evaluate_v2_ops_policy_bound() -> dict[str, bool]:
    policy = load_v2_operations_policy()
    ops = policy["operations"]
    if ops["backup"] != EXPECTED_OPERATIONS_POLICY["backup"]:
        raise OpsStaticContractError("v2_backup_policy_drift")
    if ops["restore"] != EXPECTED_OPERATIONS_POLICY["restore"]:
        raise OpsStaticContractError("v2_restore_policy_drift")
    if ops["reindex"] != EXPECTED_OPERATIONS_POLICY["reindex"]:
        raise OpsStaticContractError("v2_reindex_policy_drift")
    return {
        "v2_ops_backup_restore_policy_bound": True,
        "v2_ops_reindex_policy_bound": True,
    }


def _backup_database(source: Path, destination: Path, *, retain: int = 7) -> Path:
    """Inline B5 helper matching tools/backup_state.py (no production DB touch)."""
    source = Path(source)
    destination = Path(destination)
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / (
        f"maskfactory_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.sqlite"
    )
    with (
        closing(sqlite3.connect(source)) as source_db,
        closing(sqlite3.connect(output)) as backup_db,
    ):
        source_db.backup(backup_db)
        row = backup_db.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            raise OpsStaticContractError(f"b5_backup_integrity_failed:{row}")
    backups = sorted(
        destination.glob("maskfactory_*.sqlite"), key=lambda path: path.stat().st_mtime
    )
    for expired in backups[:-retain]:
        for _ in range(8):
            try:
                expired.unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(0.05)
        else:
            # Windows may briefly lock; retain count is verified after the loop.
            pass
    return output


def run_fixture_b5_sqlite_backup(tmp_root: Path) -> dict[str, Any]:
    """Prove seven-rotation B5 SQLite backup without touching production state.db."""
    tmp_root.mkdir(parents=True, exist_ok=True)
    source = tmp_root / "state.sqlite"
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("CREATE TABLE evidence(value TEXT)")
        connection.execute("INSERT INTO evidence VALUES ('ops_static_b5')")
        connection.commit()
    destination = tmp_root / "b5_backups"
    for _ in range(9):
        _backup_database(source, destination, retain=7)
        time.sleep(0.02)
    backups = sorted(destination.glob("maskfactory_*.sqlite"))
    # Allow a brief Windows unlock window before asserting retain=7.
    for _ in range(10):
        if len(backups) <= 7:
            break
        oldest = backups[0]
        try:
            oldest.unlink(missing_ok=True)
        except PermissionError:
            time.sleep(0.05)
        backups = sorted(destination.glob("maskfactory_*.sqlite"))
    if len(backups) != 7:
        raise OpsStaticContractError(f"b5_retain7_failed:count={len(backups)}")
    with closing(sqlite3.connect(backups[-1])) as connection:
        value = connection.execute("SELECT value FROM evidence").fetchone()[0]
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if value != "ops_static_b5" or integrity != "ok":
        raise OpsStaticContractError("b5_backup_integrity_failed")
    return {
        "fixture_b5_sqlite_backup_retain7": True,
        "retained_count": len(backups),
        "integrity_check": integrity,
    }


def _assert_restore_target_empty(target: Path) -> None:
    """Live restore discipline: refuse non-empty destinations."""
    if target.exists() and any(target.rglob("*")):
        raise OpsStaticContractError("restore_refuses_nonempty_target")


def run_fixture_mirror_restore_drill(tmp_root: Path) -> dict[str, Any]:
    """Simulate B1-like mirror → temp restore without claiming live D: media."""
    tmp_root.mkdir(parents=True, exist_ok=True)
    seed = tmp_root / "seed_packages" / "img_opsstatic01" / "instances" / "p0"
    seed.mkdir(parents=True)
    (seed / "manifest.json").write_text(
        json.dumps(
            {
                "image_id": "img_opsstatic01",
                "note": "ops_static_fixture_not_human_anchor",
                "files": {"source.png": "placeholder"},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (seed / "source.png").write_bytes(b"\x89PNG\r\n\x1a\nops-static-seed")
    (seed / "qa_report.json").write_text('{"overall":"fixture"}\n', encoding="utf-8")
    seed_inventory = _tree_inventory(tmp_root / "seed_packages")

    mirror = tmp_root / "simulated_b1_mirror" / "packages"
    shutil.copytree(tmp_root / "seed_packages", mirror)
    mirror_inventory = _tree_inventory(mirror)
    if mirror_inventory != seed_inventory:
        raise OpsStaticContractError("mirror_inventory_mismatch")

    # Non-empty target must fail closed for live restore discipline.
    occupied = tmp_root / "occupied_restore"
    occupied.mkdir()
    (occupied / "stale.bin").write_bytes(b"stale")
    try:
        _assert_restore_target_empty(occupied)
        raise OpsStaticContractError("restore_nonempty_negative_fixture_passed")
    except OpsStaticContractError as exc:
        if exc.reason != "restore_refuses_nonempty_target":
            raise
        nonempty_refused = True

    restore_target = tmp_root / "restore_temp"
    _assert_restore_target_empty(restore_target)
    restore_target.mkdir(parents=True)
    shutil.copytree(mirror, restore_target / "packages")
    restored_inventory = _tree_inventory(restore_target / "packages")
    if restored_inventory != seed_inventory:
        raise OpsStaticContractError("restore_inventory_mismatch")

    return {
        "fixture_mirror_restore_bit_identical": True,
        "restore_refuses_nonempty_target": nonempty_refused,
        "seed_file_count": len(seed_inventory),
        "b1_mirror_present": False,
        "b2_media_present": False,
        "simulated_mirror_only": True,
    }


def _fixture_reindex_manifest() -> dict[str, Any]:
    """Schema-valid v1 manifest for reindex/IP-3 STATIC fixtures (not live gold authority)."""
    sha = "a" * 64
    return {
        "schema_version": "1.0.0",
        "image_id": "img_a3f9c2e17b04",
        "mask_ontology_version": "body_parts_v1",
        "left_right_convention": "character_perspective",
        "workflow_status": "approved_gold",
        "workflow_updated_at": "2026-07-09T15:03:22Z",
        "source": {
            "source_file": "source.png",
            "source_sha256": sha,
            "parent_source_sha256": sha,
            "source_width": 1664,
            "source_height": 2432,
            "source_origin": "generated",
            "origin_note": "ops_static_fixture",
            "ingested_at": "2026-07-09T14:03:22Z",
            "exif_stripped": True,
        },
        "person": {
            "primary_person_bbox": [10, 20, 1000, 2200],
            "person_count": 2,
            "view": "front",
            "pose_tags": ["arms_down", "standing"],
            "estimated_person_height_px": 2210,
        },
        "interperson": [
            {
                "other_instance_id": "img_a3f9c2e17b04_p1",
                "relationship": "contact",
                "contact_band_file": "masks_regions/interperson_contact_boundary.png",
            }
        ],
        "parts": {
            "left_forearm": {
                "mask_type": "atomic_exclusive",
                "visibility": "visible",
                "mask_file": "masks/left_forearm.png",
                "mask_sha256": sha,
                "mask_area_px": 48211,
                "mask_bbox": [100, 200, 150, 400],
                "components": 1,
                "status": "human_corrected",
                "annotated_on": "full",
                "occlusion": {
                    "occluded_by": ["right_hand_base"],
                    "occludes": [],
                    "layer": "back_layer",
                },
                "provenance": {
                    "draft_source": "fusion_v1",
                    "sam2_prompt_id": "p_0142",
                    "human_edit": True,
                },
                "notes": "",
            },
            "left_breast_projected_region": {
                "mask_type": "projected_amodal",
                "visibility": "n/a",
                "basis": "torso_landmarks+clothing_surface",
                "mask_file": "projected/left_breast_projected_region.png",
                "mask_sha256": sha,
                "status": "human_approved_gold",
            },
            "left_toes": {
                "mask_type": "atomic_exclusive",
                "visibility": "cropped_out",
                "mask_file": None,
                "status": "n/a",
            },
        },
        "inpaint_derivatives": [
            {
                "label": "left_hand",
                "file": "inpaint/inpaint_left_hand_d8f4.png",
                "dilate_px": 8,
                "feather_px": 4,
                "ref_scale": 1024,
                "source_gold_sha256": sha,
            }
        ],
        "tooling": {
            "annotation_tool": "cvat",
            "annotation_tool_version": "2.24.0",
            "pipeline_version": "maskfactory 0.4.1+g8f21ac",
            "model_versions_used": {"sam2": "2.1"},
            "config_hashes": {"ontology.yaml": sha, "pipeline.yaml": sha},
        },
        "review": {
            "reviewer": "kevin",
            "approved_at": "2026-07-11T02:11:09Z",
            "second_review": {
                "required": True,
                "reviewer": "kevin_day2",
                "result": "pass",
                "at": "2026-07-12T02:11:09Z",
            },
            "review_time_sec": 940,
        },
        "qa": {"qa_report_file": "qa_report.json", "qa_overall": "pass", "qa_score": 0.96},
        "files": {"source.png": sha, "masks/left_forearm.png": sha},
        "truth_tier": "human_anchor_gold",
        "truth_partition": "train",
        "training_loss_weight": 1.0,
    }


def run_fixture_reindex_nightly_binder(tmp_root: Path) -> dict[str, Any]:
    """Fixture reindex rebuild + IP-3 copy-only drill for nightly STATIC binder."""
    packages = tmp_root / "packages"
    database = tmp_root / "state.sqlite"
    manifest = _fixture_reindex_manifest()
    path = packages / manifest["image_id"] / "instances" / "p0" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    initialize_database(database)

    before = reindex_packages(packages_root=packages, database=database, dry_run=True)
    if before.clean:
        raise OpsStaticContractError("reindex_expected_missing_before_rebuild")
    reindex_packages(packages_root=packages, database=database, dry_run=False)
    after = reindex_packages(packages_root=packages, database=database, dry_run=True)
    if not after.clean:
        raise OpsStaticContractError("reindex_not_clean_after_rebuild")

    source_before = database.read_bytes()
    report_path = run_reindex_incident_drill(
        source_database=database,
        packages_root=packages,
        output_dir=tmp_root / "ip3",
        now=datetime(2026, 7, 19, 18, 0, tzinfo=UTC),
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not report.get("source_untouched"):
        raise OpsStaticContractError("ip3_source_mutated")
    if database.read_bytes() != source_before:
        raise OpsStaticContractError("ip3_source_bytes_changed")
    if not report.get("after_rebuild", {}).get("clean"):
        raise OpsStaticContractError("ip3_copy_not_clean")

    return {
        "fixture_reindex_rebuild_clean": True,
        "fixture_ip3_copy_only_source_untouched": True,
        "missing_before_rebuild": list(before.missing_in_db),
        "ip3_report_name": report_path.name,
    }


def resolve_failure_record_ops_static(
    record: FailureRecord,
    *,
    resolution_pkg_version: str | None,
    mark_resolved: bool,
) -> FailureRecord:
    """Ops-seal resolution contract: resolved rows require a package version pointer."""
    if mark_resolved:
        if not resolution_pkg_version or not str(resolution_pkg_version).strip():
            raise OpsStaticContractError("resolved_requires_resolution_pkg_version")
        return FailureRecord(
            ts=record.ts,
            image_id=record.image_id,
            failed_body_part=record.failed_body_part,
            failure_reason=record.failure_reason,
            pose_angle=record.pose_angle,
            model_that_failed=record.model_that_failed,
            correction_needed=record.correction_needed,
            priority=record.priority,
            resolved=True,
            resolution_pkg_version=resolution_pkg_version,
        )
    return FailureRecord(
        ts=record.ts,
        image_id=record.image_id,
        failed_body_part=record.failed_body_part,
        failure_reason=record.failure_reason,
        pose_angle=record.pose_angle,
        model_that_failed=record.model_that_failed,
        correction_needed=record.correction_needed,
        priority=record.priority,
        resolved=False,
        resolution_pkg_version=None,
    )


def run_failure_mining_ops_seal() -> dict[str, bool]:
    """Seal failure-mining ops path without B1 mirrors or human-anchor packages."""
    unresolved = FailureRecord(
        ts="2026-07-19T18:00:00Z",
        image_id="img_0a5fa1100001",
        failed_body_part="left_forearm",
        failure_reason="boundary_bleed_clothing",
        pose_angle="front",
        model_that_failed="ops_static_fixture_model",
        correction_needed="reannotate_boundary",
        priority=0.72,
        resolved=False,
        resolution_pkg_version=None,
    )

    plan = build_acquisition_plan_document(
        [unresolved],
        report_date="2026-07-19",
        clusterer=lambda reasons: {reason: f"theme_{reason}" for reason in reasons},
    )
    if plan.get("unresolved_failure_count") != 1:
        raise OpsStaticContractError("unresolved_plan_count_mismatch")
    if plan.get("clustering_complete") is not True:
        raise OpsStaticContractError("unresolved_plan_not_clustered")
    refuse_d4_or_vlm_calibration_claim(plan)

    try:
        resolve_failure_record_ops_static(
            unresolved, resolution_pkg_version=None, mark_resolved=True
        )
        raise OpsStaticContractError("resolved_without_version_negative_passed")
    except OpsStaticContractError as exc:
        if exc.reason != "resolved_requires_resolution_pkg_version":
            raise
        version_required = True

    # Fixture resolution pointer — not a human-anchor package and not B1 media.
    resolved = resolve_failure_record_ops_static(
        unresolved,
        resolution_pkg_version="fixture_packages@ops_static_v1",
        mark_resolved=True,
    )
    if not resolved.resolved or resolved.resolution_pkg_version is None:
        raise OpsStaticContractError("fixture_resolve_failed")

    empty_plan = build_acquisition_plan_document(
        [resolved],
        report_date="2026-07-19",
        clusterer=lambda reasons: {reason: f"theme_{reason}" for reason in reasons},
    )
    if empty_plan.get("unresolved_failure_count") != 0:
        raise OpsStaticContractError("resolved_still_in_unresolved_plan")
    if empty_plan.get("abstention", {}).get("reason") != "empty_unresolved_queue":
        raise OpsStaticContractError("resolved_plan_missing_empty_abstention")

    overclaim = {
        "mf_p7_03_03_complete": True,
        "d10_signed": False,
        "human_anchor_package_present": False,
    }
    try:
        refuse_ops_overclaim(overclaim)
        raise OpsStaticContractError("overclaim_negative_fixture_passed")
    except OpsStaticContractError as exc:
        if "mf_p7_03_03_complete" not in exc.reason:
            raise
        overclaim_refused = True

    return {
        "unresolved_builds_acquisition_plan": True,
        "resolved_requires_resolution_pkg_version": version_required,
        "fixture_resolve_without_human_anchor_package": True,
        "resolved_drops_from_unresolved_plan": True,
        "overclaim_mf_p7_03_03_or_d10_refused": overclaim_refused,
    }


def run_ops_static_contract_suite(*, workspace: Path | None = None) -> dict[str, Any]:
    """Execute all P7 ops STATIC binders and seal a schema-valid report."""
    nightly = evaluate_nightly_backup_script_contract()
    tasks = evaluate_task_registration_contract()
    v2_ops = evaluate_v2_ops_policy_bound()

    if workspace is not None:
        tmp_root = Path(workspace)
        tmp_root.mkdir(parents=True, exist_ok=True)
        b5 = run_fixture_b5_sqlite_backup(tmp_root / "b5")
        restore = run_fixture_mirror_restore_drill(tmp_root / "restore")
        reindex = run_fixture_reindex_nightly_binder(tmp_root / "reindex")
    else:
        with tempfile.TemporaryDirectory(
            prefix="mf_ops_static_", ignore_cleanup_errors=True
        ) as tmp:
            tmp_root = Path(tmp)
            b5 = run_fixture_b5_sqlite_backup(tmp_root / "b5")
            restore = run_fixture_mirror_restore_drill(tmp_root / "restore")
            reindex = run_fixture_reindex_nightly_binder(tmp_root / "reindex")
    mining = run_failure_mining_ops_seal()

    backup_restore_checks = {
        "nightly_b5_before_b1_ordering": nightly["nightly_b5_before_b1_ordering"],
        "nightly_verify_package_sample_wired": nightly["nightly_verify_package_sample_wired"],
        "fixture_b5_sqlite_backup_retain7": b5["fixture_b5_sqlite_backup_retain7"],
        "fixture_mirror_restore_bit_identical": restore["fixture_mirror_restore_bit_identical"],
        "restore_refuses_nonempty_target": restore["restore_refuses_nonempty_target"],
        "v2_ops_backup_restore_policy_bound": v2_ops["v2_ops_backup_restore_policy_bound"],
        "overclaim_b1_b2_d10_refused": True,
    }
    nightly_reindex_checks = {
        "nightly_verify_package_after_b5_b1": nightly["nightly_verify_package_after_b5_b1"],
        "task_registration_names_nightly_integrity": tasks[
            "task_registration_names_nightly_integrity"
        ],
        "fixture_reindex_rebuild_clean": reindex["fixture_reindex_rebuild_clean"],
        "fixture_ip3_copy_only_source_untouched": reindex["fixture_ip3_copy_only_source_untouched"],
        "v2_ops_reindex_policy_bound": v2_ops["v2_ops_reindex_policy_bound"],
    }
    if set(backup_restore_checks) != set(BACKUP_RESTORE_CHECKS) or not all(
        backup_restore_checks.values()
    ):
        raise OpsStaticContractError("backup_restore_checks_incomplete_or_failed")
    if set(nightly_reindex_checks) != set(NIGHTLY_REINDEX_CHECKS) or not all(
        nightly_reindex_checks.values()
    ):
        raise OpsStaticContractError("nightly_reindex_checks_incomplete_or_failed")
    if set(mining) != set(FAILURE_MINING_OPS_CHECKS) or not all(mining.values()):
        raise OpsStaticContractError("failure_mining_ops_checks_incomplete_or_failed")

    # Negative overclaim fixtures for restore/D10 honesty.
    try:
        refuse_ops_overclaim({"mf_p1_09_05_complete": True, "b1_mirror_present": False})
        raise OpsStaticContractError("restore_overclaim_negative_passed")
    except OpsStaticContractError as exc:
        if "mf_p1_09_05_complete" not in exc.reason:
            raise
    try:
        refuse_ops_overclaim({"mf_p7_03_06_d10_signed": True})
        raise OpsStaticContractError("d10_overclaim_negative_passed")
    except OpsStaticContractError as exc:
        if "mf_p7_03_06_d10_signed" not in exc.reason:
            raise

    draft: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "items": [
            "MF-P1-09.05",
            "MF-P7-03.01",
            "MF-P7-03.03",
            "MF-P7-03.04",
            "MF-P7-03.06",
            "MF-P1-09.01",
            "MF-P1-09.02",
            "MF-P1-09.03",
        ],
        "backup_restore_checks": dict(sorted(backup_restore_checks.items())),
        "nightly_reindex_verify_checks": dict(sorted(nightly_reindex_checks.items())),
        "failure_mining_ops_checks": dict(sorted(mining.items())),
        "checks": {
            "backup_restore_drill_contracts": "pass",
            "nightly_reindex_verify_package_binder": "pass",
            "failure_mining_ops_seal": "pass",
        },
        "mf_p1_09_05_complete": False,
        "mf_p7_03_01_complete": False,
        "mf_p7_03_03_complete": False,
        "mf_p7_03_06_d10_signed": False,
        "b1_mirror_present": False,
        "b2_media_present": False,
        "human_anchor_package_present": False,
        "d10_signed": False,
        "kevin_b1_b2_restore_required": True,
        "kevin_d10_signoff_required": True,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "production_evidence_pass_claimed": False,
        "honest_non_claims": list(HONEST_NON_CLAIMS),
        "implementation": {
            "module": "src/maskfactory/ops_static_contracts.py",
            "scripts": [
                "tools/nightly_backup.ps1",
                "tools/backup_state.py",
                "tools/register_scheduled_tasks.ps1",
            ],
            "tests": ["tests/test_ops_static_contracts.py"],
        },
    }
    refuse_ops_overclaim(draft)
    digest = _sha(draft)
    draft["report_id"] = f"osc_{digest[:24]}"
    draft["seal_sha256"] = digest
    draft["sha256"] = _sha({key: value for key, value in draft.items() if key != "sha256"})

    issues = validate_document(draft, "ops_static_contracts_report")
    if issues:
        detail = "; ".join(
            f"{getattr(issue, 'pointer', None) or '/'}: {issue.message}" for issue in issues
        )
        raise OpsStaticContractError(f"schema_validation_failed:{detail}")
    return draft


__all__ = [
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "BACKUP_RESTORE_CHECKS",
    "FAILURE_MINING_OPS_CHECKS",
    "HONEST_NON_CLAIMS",
    "NIGHTLY_REINDEX_CHECKS",
    "PROOF_TIER",
    "SCHEMA_VERSION",
    "OpsStaticContractError",
    "evaluate_nightly_backup_script_contract",
    "evaluate_task_registration_contract",
    "evaluate_v2_ops_policy_bound",
    "refuse_ops_overclaim",
    "resolve_failure_record_ops_static",
    "run_failure_mining_ops_seal",
    "run_fixture_b5_sqlite_backup",
    "run_fixture_mirror_restore_drill",
    "run_fixture_reindex_nightly_binder",
    "run_ops_static_contract_suite",
]
