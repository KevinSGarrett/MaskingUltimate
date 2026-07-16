"""DAZ foundation policy, doctor, and synthetic-authority gates."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from ..truth_tiers import WEIGHTED_PSEUDO_LABEL

SYNTHETIC_ROLE = "synthetic_geometry_exact"
MAXIMUM_SYNTHETIC_SHARE = 0.30


class DazPolicyError(ValueError):
    """DAZ configuration or synthetic training authority is invalid."""


def load_yaml(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise DazPolicyError(f"DAZ configuration is not a mapping: {path}")
    return document


def validate_daz_configuration(config_root: Path) -> dict[str, dict[str, Any]]:
    root = Path(config_root)
    documents = {
        name: load_yaml(root / f"{name}.yaml")
        for name in ("paths", "operating_profile", "worker", "training_policy")
    }
    profile = documents["operating_profile"]
    required_profile = {
        "profile_id": "private_personal_local_v1",
        "execution_location": "local_machine",
        "commercial_deployment": False,
        "public_hosting": False,
        "distribution": False,
        "automatic_asset_purchase": False,
        "automatic_account_login": False,
    }
    for field, expected in required_profile.items():
        if profile.get(field) != expected:
            raise DazPolicyError(f"DAZ operating profile violates {field}")
    content = profile.get("content_policy", {})
    if content.get("adult_and_nsfw_assets_eligible") is not True:
        raise DazPolicyError("governed adult DAZ assets were incorrectly excluded")
    if content.get("known_or_suspected_minor_prohibited") is not True:
        raise DazPolicyError("DAZ adult-only age gate is missing")

    worker = documents["worker"]
    required_worker = {
        "enabled": False,
        "default_disabled": True,
        "launch_mode": "process_per_job",
        "window_visibility": "hidden",
        "automatic_purchase": False,
        "automatic_account_login": False,
    }
    for field, expected in required_worker.items():
        if worker.get(field) != expected:
            raise DazPolicyError(f"DAZ worker violates {field}")
    validate_synthetic_authority(documents["training_policy"])
    paths = documents["paths"]
    thresholds = paths.get("storage_thresholds_gib", {})
    if thresholds != {"healthy": 150, "soft": 150, "hard": 100, "emergency": 60}:
        raise DazPolicyError("DAZ storage thresholds do not match the blueprint")
    roots = paths.get("expected_top_level_roots")
    if not isinstance(roots, list) or len(roots) != 25 or len(set(roots)) != 25:
        raise DazPolicyError("DAZ top-level root contract must contain 25 unique roots")
    return documents


def validate_synthetic_authority(record: Mapping[str, Any]) -> None:
    required = {
        "source_origin": "synthetic",
        "source_role": SYNTHETIC_ROLE,
        "truth_tier": WEIGHTED_PSEUDO_LABEL,
        "truth_partition": "train",
        "holdout_eligible": False,
        "calibration_eligible": False,
        "dataset_volume_eligible": False,
        "counts_as_human_anchor_gold": False,
        "counts_as_autonomous_certified_gold": False,
    }
    for field, expected in required.items():
        if record.get(field) != expected:
            raise DazPolicyError(f"synthetic authority violates {field}")
    weight = record.get("training_loss_weight")
    if not isinstance(weight, (int, float)) or not 0.10 <= float(weight) <= 0.25:
        raise DazPolicyError("synthetic training weight must be 0.10..0.25")
    maximum_share = record.get("maximum_synthetic_image_fraction", MAXIMUM_SYNTHETIC_SHARE)
    if float(maximum_share) != MAXIMUM_SYNTHETIC_SHARE:
        raise DazPolicyError("synthetic image fraction ceiling must remain 0.30")
    forbidden = {"human_review", "certification", "certificate_id", "reviewer"} & set(record)
    if forbidden:
        raise DazPolicyError(f"synthetic record fabricates authority: {sorted(forbidden)}")


def validate_synthetic_share(records: Iterable[Mapping[str, Any]]) -> dict[str, int | float]:
    rows = tuple(records)
    synthetic = 0
    for row in rows:
        if row.get("source_origin") == "synthetic":
            validate_synthetic_authority(row)
            synthetic += 1
    share = synthetic / len(rows) if rows else 0.0
    if share > MAXIMUM_SYNTHETIC_SHARE + 1e-12:
        raise DazPolicyError(
            f"synthetic image share {share:.6f} exceeds {MAXIMUM_SYNTHETIC_SHARE:.2f}"
        )
    return {
        "total_images": len(rows),
        "synthetic_images": synthetic,
        "synthetic_image_share": share,
    }


def inspect_acquisition_queue(path: Path, *, query_counts: bool = False) -> dict[str, Any]:
    """Inspect acquisition state without reading per-asset manifests.

    The live downloader can hold its WAL on slow removable-storage I/O for long periods.
    The default probe therefore remains metadata-only and nonblocking.  Explicit count
    queries are intended for an idle queue or bounded fixture database.
    """
    path = Path(path)
    report: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        return report
    report["bytes"] = path.stat().st_size
    wal_path = path.with_name(path.name + "-wal")
    report["wal_exists"] = wal_path.is_file()
    report["count_query_skipped_while_live"] = not query_counts
    if not query_counts:
        return report
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3)
        try:
            connection.execute("PRAGMA query_only=ON")
            report["total_jobs"] = int(
                connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            )
            report["states"] = dict(
                connection.execute("SELECT state, COUNT(*) FROM jobs GROUP BY state")
            )
            report["stages"] = dict(
                connection.execute("SELECT stage, COUNT(*) FROM jobs GROUP BY stage")
            )
            report["count_query_skipped_while_live"] = False
        finally:
            connection.close()
    except sqlite3.Error as exc:
        report["error"] = f"sqlite_read_failed:{type(exc).__name__}:{exc}"
    return report


def daz_foundation_doctor(config_root: Path) -> dict[str, Any]:
    """Read-only D0/D1 foundation doctor; it never launches DAZ or alters the queue."""
    documents = validate_daz_configuration(config_root)
    paths = documents["paths"]
    root = Path(paths["root"])
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, details: Any) -> None:
        checks.append({"name": name, "passed": bool(passed), "details": details})

    check("root_exists", root.is_dir(), str(root))
    identity_path = Path(paths["root_identity"])
    try:
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        identity_ok = (
            identity.get("schema_version") == "1.0.0"
            and identity.get("canonical_path", "").casefold() == str(root).casefold()
            and isinstance(identity.get("root_uuid"), str)
            and len(identity["root_uuid"]) == 36
        )
        check("root_identity", identity_ok, identity)
    except (OSError, json.JSONDecodeError) as exc:
        check("root_identity", False, str(exc))
    missing_roots = [
        name for name in paths["expected_top_level_roots"] if not (root / name).is_dir()
    ]
    check("top_level_roots", not missing_roots, {"missing": missing_roots})

    executable = Path(paths["daz_studio_executable"])
    executable_sha = _sha256_file(executable) if executable.is_file() else None
    check(
        "daz_studio_executable",
        executable_sha == str(paths["daz_studio_executable_sha256"]).casefold(),
        {"path": str(executable), "sha256": executable_sha},
    )
    if root.is_dir():
        free_gib = shutil.disk_usage(root).free / (1024**3)
        thresholds = paths["storage_thresholds_gib"]
        if free_gib < float(thresholds["emergency"]):
            storage_level = "emergency"
        elif free_gib < float(thresholds["hard"]):
            storage_level = "hard"
        elif free_gib < float(thresholds["soft"]):
            storage_level = "soft"
        else:
            storage_level = "healthy"
        check(
            "storage_not_hard_blocked",
            free_gib >= float(thresholds["hard"]),
            {"free_gib": round(free_gib, 3), "level": storage_level},
        )
    acquisition = inspect_acquisition_queue(Path(paths["acquisition_database"]))
    check(
        "acquisition_queue_readable",
        acquisition.get("error") is None and acquisition["exists"],
        acquisition,
    )
    check(
        "generation_default_disabled", documents["worker"]["enabled"] is False, documents["worker"]
    )
    warnings = [
        "storage_soft_floor: do not start new large generation plans"
        for item in checks
        if item["name"] == "storage_not_hard_blocked" and item["details"].get("level") == "soft"
    ]
    return {
        "schema_version": "1.0.0",
        "passed": all(item["passed"] for item in checks),
        "warnings": warnings,
        "checks": checks,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "DazPolicyError",
    "MAXIMUM_SYNTHETIC_SHARE",
    "SYNTHETIC_ROLE",
    "daz_foundation_doctor",
    "inspect_acquisition_queue",
    "load_yaml",
    "validate_daz_configuration",
    "validate_synthetic_authority",
    "validate_synthetic_share",
]
