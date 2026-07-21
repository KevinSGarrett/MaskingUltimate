"""STATIC binders for MF-P1-09 ops-bootstrap residuals beyond ops_static_contracts.

Covers fixture hash-manifest (QC-006) integrity, multi-package reindex rebuild-clean,
and DVC wiring honesty without any AWS/S3 push. Never completes MF-P1-07.09 or claims
live B1 restore / doctor-green / gold / PRODUCTION_EVIDENCE_PASS.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .dvc_runtime import DvcRuntimeError, resolve_dvc_executable, run_dvc
from .qa.checks import _qc006
from .reindex import reindex_packages
from .state import initialize_database
from .validation import validate_document

PROOF_TIER = "STATIC_PASS"
ARTIFACT_TYPE = "ops_bootstrap_static_report"
AUTHORITY = (
    "ops_bootstrap_static_only_no_dvc_s3_push_no_b1_restore_no_human_anchor_package_authority"
)
SCHEMA_VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parents[2]
DVC_CONFIG = ROOT / ".dvc" / "config"
GITIGNORE = ROOT / ".gitignore"
BOOTSTRAP_DVC = ROOT / "tools" / "bootstrap_dvc.ps1"
REQUIREMENTS_LOCK = ROOT / "env" / "requirements.lock.txt"
EXPECTED_REMOTE_NAME = "maskfactory-dvc-dev"
EXPECTED_REMOTE_URL = "s3://maskfactory-dvc-dev"

HASH_MANIFEST_CHECKS = (
    "fixture_qc006_hash_integrity_pass",
    "fixture_qc006_tamper_detected",
    "fixture_qc006_untracked_detected",
)
PACKAGE_REINDEX_CHECKS = (
    "multi_package_reindex_missing_before_rebuild",
    "multi_package_reindex_rebuild_clean",
    "multi_package_reindex_dry_run_zero_diff",
)
DVC_WIRING_CHECKS = (
    "dvc_config_remote_bound",
    "dvc_resolver_available",
    "dvc_remote_list_matches_config",
    "dvc_gitignore_descriptor_exceptions",
    "dvc_bootstrap_pins_match_lock",
    "dvc_push_not_attempted",
    "mf_p1_07_09_overclaim_refused",
)

HONEST_NON_CLAIMS = (
    "mf_p1_07_09_complete",
    "mf_p1_09_05_complete",
    "dvc_s3_push_succeeded",
    "aws_credentials_present",
    "b1_mirror_present",
    "human_anchor_package_present",
    "doctor_green",
    "gold",
    "PRODUCTION_EVIDENCE_PASS",
)


class OpsBootstrapStaticError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha(document: Mapping[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refuse_bootstrap_overclaim(document: Mapping[str, Any]) -> None:
    """Fail closed on DVC S3 completion / B1 restore / gold overclaims."""
    forbidden_true = (
        "mf_p1_07_09_complete",
        "mf_p1_09_05_complete",
        "dvc_s3_push_succeeded",
        "dvc_push_attempted",
        "b1_mirror_present",
        "human_anchor_package_present",
        "doctor_green_claimed",
        "gold_claimed",
        "production_evidence_pass_claimed",
    )
    for key in forbidden_true:
        if document.get(key) is True:
            raise OpsBootstrapStaticError(f"ops_bootstrap_overclaim:{key}")


def _fixture_manifest(image_id: str, files: Mapping[str, str]) -> dict[str, Any]:
    """Schema-valid v1 manifest for STATIC fixtures (not live gold authority)."""
    sha = "a" * 64
    return {
        "schema_version": "1.0.0",
        "image_id": image_id,
        "mask_ontology_version": "body_parts_v1",
        "left_right_convention": "character_perspective",
        "workflow_status": "approved_gold",
        "workflow_updated_at": "2026-07-09T15:03:22Z",
        "source": {
            "source_file": "source.png",
            "source_sha256": files.get("source.png", sha),
            "parent_source_sha256": files.get("source.png", sha),
            "source_width": 64,
            "source_height": 64,
            "source_origin": "generated",
            "origin_note": "ops_bootstrap_static_fixture",
            "ingested_at": "2026-07-09T14:03:22Z",
            "exif_stripped": True,
        },
        "person": {
            "primary_person_bbox": [1, 2, 60, 60],
            "person_count": 1,
            "view": "front",
            "pose_tags": ["arms_down", "standing"],
            "estimated_person_height_px": 58,
        },
        "interperson": [],
        "parts": {
            "left_forearm": {
                "mask_type": "atomic_exclusive",
                "visibility": "visible",
                "mask_file": "masks/left_forearm.png",
                "mask_sha256": files.get("masks/left_forearm.png", sha),
                "mask_area_px": 16,
                "mask_bbox": [8, 8, 16, 16],
                "components": 1,
                "status": "human_corrected",
                "annotated_on": "full",
                "occlusion": {"occluded_by": [], "occludes": [], "layer": "front_layer"},
                "provenance": {
                    "draft_source": "fusion_v1",
                    "sam2_prompt_id": "p_0142",
                    "human_edit": True,
                },
                "notes": "",
            },
            "left_toes": {
                "mask_type": "atomic_exclusive",
                "visibility": "cropped_out",
                "mask_file": None,
                "status": "n/a",
            },
        },
        "inpaint_derivatives": [],
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
        "files": dict(files),
        "truth_tier": "human_anchor_gold",
        "truth_partition": "train",
        "training_loss_weight": 1.0,
    }


def _write_fixture_package(package_root: Path, image_id: str, marker: bytes) -> dict[str, str]:
    package_root.mkdir(parents=True, exist_ok=True)
    source = package_root / "source.png"
    mask = package_root / "masks" / "left_forearm.png"
    mask.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"PNG\r\nSTATIC-SOURCE-" + marker)
    mask.write_bytes(b"PNG\r\nSTATIC-MASK-" + marker)
    files = {
        "source.png": _file_sha(source),
        "masks/left_forearm.png": _file_sha(mask),
    }
    manifest = _fixture_manifest(image_id, files)
    (package_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return files


def run_fixture_hash_manifest_integrity(tmp_root: Path) -> dict[str, Any]:
    """Prove QC-006 pass on a fixture package and fail-closed on tamper/untracked."""
    package = tmp_root / "hash_pkg"
    _write_fixture_package(package, "img_b00700000001", b"hash-ok")
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    passed = _qc006(package, manifest)
    if not passed.passed:
        raise OpsBootstrapStaticError(f"fixture_qc006_expected_pass:{passed.detail}")

    (package / "source.png").write_bytes(b"PNG\r\nTAMPERED")
    tampered = _qc006(package, manifest)
    if tampered.passed:
        raise OpsBootstrapStaticError("fixture_qc006_tamper_not_detected")
    # Restore for untracked probe.
    (package / "source.png").write_bytes(b"PNG\r\nSTATIC-SOURCE-hash-ok")
    # Recompute expected hash after restore so only untracked triggers.
    manifest["files"]["source.png"] = _file_sha(package / "source.png")
    (package / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (package / "orphan.bin").write_bytes(b"untracked")
    untracked = _qc006(package, manifest)
    if untracked.passed or "untracked" not in untracked.detail:
        raise OpsBootstrapStaticError(f"fixture_qc006_untracked_not_detected:{untracked.detail}")

    return {
        "fixture_qc006_hash_integrity_pass": True,
        "fixture_qc006_tamper_detected": True,
        "fixture_qc006_untracked_detected": True,
        "qc006_pass_detail": passed.detail,
        "qc006_tamper_detail": tampered.detail,
        "qc006_untracked_detail": untracked.detail,
    }


def run_fixture_multi_package_reindex(tmp_root: Path) -> dict[str, Any]:
    """Rebuild SQLite from two fixture packages and prove dry-run zero-diff."""
    packages = tmp_root / "packages"
    database = tmp_root / "state.sqlite"
    for index, image_id in enumerate(("img_b00700000011", "img_b00700000012"), start=1):
        package = packages / image_id / "instances" / "p0"
        _write_fixture_package(package, image_id, f"pkg-{index}".encode())
    initialize_database(database)

    before = reindex_packages(packages_root=packages, database=database, dry_run=True)
    if before.clean or len(before.missing_in_db) != 2:
        raise OpsBootstrapStaticError(
            f"reindex_expected_two_missing_before_rebuild:missing={before.missing_in_db}"
        )
    reindex_packages(packages_root=packages, database=database, dry_run=False)
    after = reindex_packages(packages_root=packages, database=database, dry_run=True)
    if not after.clean:
        raise OpsBootstrapStaticError(f"reindex_not_clean_after_rebuild:{after.as_dict()}")
    if after.missing_in_db or after.extra_in_db or after.stale_rows:
        raise OpsBootstrapStaticError(f"reindex_nonzero_diff:{after.as_dict()}")

    return {
        "multi_package_reindex_missing_before_rebuild": True,
        "multi_package_reindex_rebuild_clean": True,
        "multi_package_reindex_dry_run_zero_diff": True,
        "package_count": 2,
        "missing_before": list(before.missing_in_db),
    }


def evaluate_dvc_config_wiring(config_path: Path = DVC_CONFIG) -> dict[str, Any]:
    """Bind default remote name/URL from repository .dvc/config without pushing."""
    text = config_path.read_text(encoding="utf-8")
    if f"remote = {EXPECTED_REMOTE_NAME}" not in text:
        raise OpsBootstrapStaticError("dvc_default_remote_missing")
    if EXPECTED_REMOTE_URL not in text:
        raise OpsBootstrapStaticError("dvc_remote_url_missing")
    if f"['remote \"{EXPECTED_REMOTE_NAME}\"']" not in text:
        raise OpsBootstrapStaticError("dvc_remote_section_missing")
    return {
        "dvc_config_remote_bound": True,
        "remote_name": EXPECTED_REMOTE_NAME,
        "remote_url": EXPECTED_REMOTE_URL,
    }


def evaluate_dvc_descriptor_gitignore(gitignore_path: Path = GITIGNORE) -> dict[str, bool]:
    rules = gitignore_path.read_text(encoding="utf-8").splitlines()
    required = (
        "/data/*",
        "!/data/.gitignore",
        "!/data/packages.dvc",
        "/datasets/*",
        "!/datasets/.gitignore",
        "!/datasets/*.dvc",
    )
    for rule in required:
        if rule not in rules:
            raise OpsBootstrapStaticError(f"gitignore_missing:{rule}")
    if "/data/" in rules or "/datasets/" in rules:
        raise OpsBootstrapStaticError("gitignore_overbroad_data_or_datasets_rule")
    return {"dvc_gitignore_descriptor_exceptions": True}


def evaluate_dvc_bootstrap_pins(
    bootstrap_path: Path = BOOTSTRAP_DVC,
    lock_path: Path = REQUIREMENTS_LOCK,
) -> dict[str, bool]:
    script = bootstrap_path.read_text(encoding="utf-8")
    lock = lock_path.read_text(encoding="utf-8")
    for requirement in (
        "dvc==3.67.1",
        "dvc-s3==3.3.0",
        "fsspec==2026.4.0",
        "s3fs==2026.4.0",
    ):
        if requirement not in script or requirement not in lock:
            raise OpsBootstrapStaticError(f"dvc_pin_drift:{requirement}")
    return {"dvc_bootstrap_pins_match_lock": True}


def evaluate_dvc_runtime_honesty(*, root: Path = ROOT) -> dict[str, Any]:
    """Resolve DVC + remote list; never invoke push; refuse S3-complete overclaim."""
    executable = resolve_dvc_executable(root=root)
    version = run_dvc(("version",), root=root, timeout=60)
    if version.returncode != 0:
        raise OpsBootstrapStaticError(f"dvc_version_failed:{version.stderr.strip()}")
    remote_list = run_dvc(("remote", "list"), root=root, timeout=60)
    if remote_list.returncode != 0:
        raise OpsBootstrapStaticError(f"dvc_remote_list_failed:{remote_list.stderr.strip()}")
    remote_text = remote_list.stdout
    if EXPECTED_REMOTE_NAME not in remote_text or EXPECTED_REMOTE_URL not in remote_text:
        raise OpsBootstrapStaticError(f"dvc_remote_list_mismatch:{remote_text!r}")

    aws_present = any(
        os.environ.get(key)
        for key in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_PROFILE",
        )
    )
    try:
        refuse_bootstrap_overclaim({"mf_p1_07_09_complete": True})
        raise OpsBootstrapStaticError("mf_p1_07_09_overclaim_negative_passed")
    except OpsBootstrapStaticError as exc:
        if "mf_p1_07_09_complete" not in exc.reason:
            raise

    # Extract a short version token if present.
    version_match = re.search(r"DVC version:\s*([0-9.]+)", version.stdout)
    return {
        "dvc_resolver_available": True,
        "dvc_remote_list_matches_config": True,
        "dvc_push_not_attempted": True,
        "mf_p1_07_09_overclaim_refused": True,
        "executable": str(executable),
        "dvc_version_token": version_match.group(1) if version_match else "unknown",
        "aws_credentials_present": bool(aws_present),
        "dvc_push_attempted": False,
        "dvc_s3_push_succeeded": False,
    }


def run_ops_bootstrap_static_suite(*, workspace: Path | None = None) -> dict[str, Any]:
    """Execute P1-09 residual STATIC binders and seal a schema-valid report."""
    config = evaluate_dvc_config_wiring()
    gitignore = evaluate_dvc_descriptor_gitignore()
    pins = evaluate_dvc_bootstrap_pins()

    if workspace is not None:
        tmp_root = Path(workspace)
        tmp_root.mkdir(parents=True, exist_ok=True)
        hash_checks = run_fixture_hash_manifest_integrity(tmp_root / "hash")
        reindex_checks = run_fixture_multi_package_reindex(tmp_root / "reindex")
    else:
        with tempfile.TemporaryDirectory(
            prefix="mf_ops_bootstrap_static_", ignore_cleanup_errors=True
        ) as tmp:
            tmp_root = Path(tmp)
            hash_checks = run_fixture_hash_manifest_integrity(tmp_root / "hash")
            reindex_checks = run_fixture_multi_package_reindex(tmp_root / "reindex")

    try:
        runtime = evaluate_dvc_runtime_honesty()
    except DvcRuntimeError as exc:
        raise OpsBootstrapStaticError(f"dvc_runtime_unavailable:{exc}") from exc

    hash_manifest_checks = {
        "fixture_qc006_hash_integrity_pass": hash_checks["fixture_qc006_hash_integrity_pass"],
        "fixture_qc006_tamper_detected": hash_checks["fixture_qc006_tamper_detected"],
        "fixture_qc006_untracked_detected": hash_checks["fixture_qc006_untracked_detected"],
    }
    package_reindex_checks = {
        "multi_package_reindex_missing_before_rebuild": reindex_checks[
            "multi_package_reindex_missing_before_rebuild"
        ],
        "multi_package_reindex_rebuild_clean": reindex_checks[
            "multi_package_reindex_rebuild_clean"
        ],
        "multi_package_reindex_dry_run_zero_diff": reindex_checks[
            "multi_package_reindex_dry_run_zero_diff"
        ],
    }
    dvc_wiring_checks = {
        "dvc_config_remote_bound": config["dvc_config_remote_bound"],
        "dvc_resolver_available": runtime["dvc_resolver_available"],
        "dvc_remote_list_matches_config": runtime["dvc_remote_list_matches_config"],
        "dvc_gitignore_descriptor_exceptions": gitignore["dvc_gitignore_descriptor_exceptions"],
        "dvc_bootstrap_pins_match_lock": pins["dvc_bootstrap_pins_match_lock"],
        "dvc_push_not_attempted": runtime["dvc_push_not_attempted"],
        "mf_p1_07_09_overclaim_refused": runtime["mf_p1_07_09_overclaim_refused"],
    }
    if set(hash_manifest_checks) != set(HASH_MANIFEST_CHECKS) or not all(
        hash_manifest_checks.values()
    ):
        raise OpsBootstrapStaticError("hash_manifest_checks_incomplete_or_failed")
    if set(package_reindex_checks) != set(PACKAGE_REINDEX_CHECKS) or not all(
        package_reindex_checks.values()
    ):
        raise OpsBootstrapStaticError("package_reindex_checks_incomplete_or_failed")
    if set(dvc_wiring_checks) != set(DVC_WIRING_CHECKS) or not all(dvc_wiring_checks.values()):
        raise OpsBootstrapStaticError("dvc_wiring_checks_incomplete_or_failed")

    draft: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "items": [
            "MF-P1-09.03",
            "MF-P1-09.05",
            "MF-P1-07.09",
            "MF-P7-03.04",
        ],
        "hash_manifest_checks": dict(sorted(hash_manifest_checks.items())),
        "package_reindex_checks": dict(sorted(package_reindex_checks.items())),
        "dvc_wiring_checks": dict(sorted(dvc_wiring_checks.items())),
        "checks": {
            "hash_manifest_integrity_binder": "pass",
            "package_reindex_static_binder": "pass",
            "dvc_wiring_honesty_binder": "pass",
        },
        "mf_p1_07_09_complete": False,
        "mf_p1_09_05_complete": False,
        "dvc_s3_push_succeeded": False,
        "dvc_push_attempted": False,
        "aws_credentials_present": bool(runtime["aws_credentials_present"]),
        "b1_mirror_present": False,
        "human_anchor_package_present": False,
        "kevin_dvc_s3_push_required": True,
        "kevin_b1_restore_required": True,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "production_evidence_pass_claimed": False,
        "honest_non_claims": list(HONEST_NON_CLAIMS),
        "dvc_runtime": {
            "remote_name": config["remote_name"],
            "remote_url": config["remote_url"],
            "dvc_version_token": runtime["dvc_version_token"],
            "executable_basename": Path(runtime["executable"]).name,
        },
        "implementation": {
            "module": "src/maskfactory/ops_bootstrap_static.py",
            "scripts": [
                "tools/bootstrap_dvc.ps1",
                ".dvc/config",
            ],
            "tests": ["tests/test_ops_bootstrap_static.py"],
        },
    }
    refuse_bootstrap_overclaim(draft)
    digest = _sha(draft)
    draft["report_id"] = f"obs_{digest[:24]}"
    draft["seal_sha256"] = digest
    draft["sha256"] = _sha({key: value for key, value in draft.items() if key != "sha256"})

    issues = validate_document(draft, "ops_bootstrap_static_report")
    if issues:
        detail = "; ".join(
            f"{getattr(issue, 'pointer', None) or '/'}: {issue.message}" for issue in issues
        )
        raise OpsBootstrapStaticError(f"schema_validation_failed:{detail}")
    return draft


__all__ = [
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "DVC_WIRING_CHECKS",
    "HASH_MANIFEST_CHECKS",
    "HONEST_NON_CLAIMS",
    "PACKAGE_REINDEX_CHECKS",
    "PROOF_TIER",
    "SCHEMA_VERSION",
    "OpsBootstrapStaticError",
    "evaluate_dvc_bootstrap_pins",
    "evaluate_dvc_config_wiring",
    "evaluate_dvc_descriptor_gitignore",
    "evaluate_dvc_runtime_honesty",
    "refuse_bootstrap_overclaim",
    "run_fixture_hash_manifest_integrity",
    "run_fixture_multi_package_reindex",
    "run_ops_bootstrap_static_suite",
]
