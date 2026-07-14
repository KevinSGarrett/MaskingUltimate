"""Hard-blocked approval, freeze, and verification for gold packages."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image

from . import __version__
from .dvc_runtime import DvcRuntimeError, run_dvc
from .inpaint import derive_inpaint
from .io.hashing import sha256_file_map
from .io.png_strict import read_mask
from .ontology import get_ontology
from .ontology_v2_manifest import require_v2_supervision_eligible
from .qa.autofix import run_autofix_once
from .qa.checks import QcResult, run_qc001_010
from .qa.panels import render_boundary_panel, render_part_overlays
from .validation import require_valid_document


class PackageBlockedError(RuntimeError):
    """At least one BLOCK check failed; approval is structurally impossible."""

    def __init__(self, results: tuple[QcResult, ...], panels: tuple[str, ...]) -> None:
        self.results = results
        self.panels = panels
        failed = ", ".join(result.qc_id for result in results if not result.passed)
        super().__init__(f"package blocked by {failed}; panels={list(panels)}")


class ApprovalRequiredError(RuntimeError):
    """QA passed but the explicit human approval confirmation was not supplied."""


@dataclass(frozen=True)
class PackageVerification:
    package_root: Path
    passed: bool
    results: tuple[QcResult, ...]


DvcAdd = Callable[[Path], None]


def approve_package(
    package_root: Path,
    *,
    reviewer: str,
    review_minutes: float,
    approved: bool,
    dvc_add: DvcAdd | None = None,
    now: Callable[[], datetime] | None = None,
) -> PackageVerification:
    """Run gates, require confirmation, stamp gold, freeze, hash, and DVC-add."""
    package_root = Path(package_root)
    if not reviewer.strip() or review_minutes < 0:
        raise ValueError("reviewer is required and review_minutes must be non-negative")
    if (package_root / ".maskfactory_frozen.json").is_file():
        raise RuntimeError(f"package is already frozen: {package_root}")
    dvc_callback = dvc_add or _dvc_add

    existing_blocks = _existing_report_blocks(package_root)
    if existing_blocks:
        raise PackageBlockedError(existing_blocks, _failing_panels(package_root, existing_blocks))
    manifest = json.loads((package_root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("workflow_status") != "corrected":
        raise ApprovalRequiredError("CVAT pull/correction must complete before gold approval")

    run_autofix_once(package_root)
    _refresh_files(package_root)
    first_results = run_qc001_010(package_root)
    failed = tuple(result for result in first_results if not result.passed)
    if failed:
        _bounce(package_root, first_results)
        raise PackageBlockedError(first_results, _failing_panels(package_root, failed))
    if not approved:
        raise ApprovalRequiredError("QA passed; explicit human approval confirmation required")
    if dvc_add is None:
        _require_dvc()
    backup = _snapshot_directory(package_root, "approval")
    try:
        result = _finalize_approval(
            package_root,
            reviewer=reviewer,
            review_minutes=review_minutes,
            first_results=first_results,
            dvc_callback=dvc_callback,
            now=now,
        )
    except BaseException:
        _restore_directory_snapshot(package_root, backup)
        raise
    shutil.rmtree(backup)
    return result


def approve_packages_atomically(
    package_roots: tuple[Path, ...],
    *,
    reviewer: str,
    review_minutes: float,
    approved: bool,
    dvc_add: DvcAdd | None = None,
    now: Callable[[], datetime] | None = None,
) -> tuple[PackageVerification, ...]:
    """Approve every pN for one image or restore every package byte-for-byte."""
    roots = tuple(Path(root) for root in package_roots)
    if not roots or len(set(roots)) != len(roots):
        raise ValueError("atomic approval requires one or more distinct package roots")
    for root in roots:
        try:
            approve_package(
                root,
                reviewer=reviewer,
                review_minutes=review_minutes,
                approved=False,
                dvc_add=lambda _path: None,
                now=now,
            )
        except ApprovalRequiredError:
            continue
    if not approved:
        raise ApprovalRequiredError("all package gates passed; explicit approval required")
    tracked_root = _common_image_root(roots)
    callback = dvc_add or _dvc_add
    if dvc_add is None:
        _require_dvc()
    backups: dict[Path, Path] = {}
    try:
        for root in roots:
            backups[root] = _snapshot_directory(root, "image-approval")
    except BaseException:
        for backup in backups.values():
            shutil.rmtree(backup, ignore_errors=True)
        raise
    try:
        results = tuple(
            approve_package(
                root,
                reviewer=reviewer,
                review_minutes=review_minutes,
                approved=True,
                dvc_add=lambda _path: None,
                now=now,
            )
            for root in roots
        )
        callback(tracked_root)
    except BaseException:
        for root in reversed(roots):
            _restore_directory_snapshot(root, backups[root])
        raise
    for backup in backups.values():
        shutil.rmtree(backup)
    return results


def _finalize_approval(
    package_root: Path,
    *,
    reviewer: str,
    review_minutes: float,
    first_results: tuple[QcResult, ...],
    dvc_callback: DvcAdd,
    now: Callable[[], datetime] | None,
) -> PackageVerification:
    _regenerate_final_artifacts(package_root)
    _refresh_files(package_root)
    prepared_results = run_qc001_010(package_root)
    prepared_failed = tuple(result for result in prepared_results if not result.passed)
    if prepared_failed:
        _bounce(package_root, prepared_results)
        raise PackageBlockedError(prepared_results, _failing_panels(package_root, prepared_failed))

    timestamp = (now or (lambda: datetime.now(UTC)))().astimezone(UTC)
    _stamp_gold_manifest(package_root, reviewer, review_minutes, timestamp)
    qa_report = _qa_report(package_root, first_results, timestamp)
    require_valid_document(qa_report, "qa_report")
    _write_json_atomic(package_root / "qa_report.json", qa_report)
    _write_json_atomic(
        package_root / ".maskfactory_frozen.json",
        {
            "schema_version": "1.0.0",
            "frozen_at": timestamp.isoformat(),
            "reviewer": reviewer,
            "policy": "immutable; corrections require a new mask version",
        },
    )
    _refresh_files(package_root)
    final_results = run_qc001_010(package_root)
    final_failed = tuple(result for result in final_results if not result.passed)
    if final_failed:
        (package_root / ".maskfactory_frozen.json").unlink(missing_ok=True)
        _bounce(package_root, final_results)
        raise PackageBlockedError(final_results, _failing_panels(package_root, final_failed))
    dvc_callback(package_root)
    return PackageVerification(package_root, True, final_results)


def _snapshot_directory(root: Path, purpose: str) -> Path:
    backup = root.parent / f".{root.name}.{purpose}-{uuid.uuid4().hex}"
    shutil.copytree(root, backup, copy_function=shutil.copy2)
    return backup


def _restore_directory_snapshot(root: Path, backup: Path) -> None:
    failed = root.parent / f".{root.name}.failed-{uuid.uuid4().hex}"
    os.replace(root, failed)
    try:
        os.replace(backup, root)
    except BaseException:
        os.replace(failed, root)
        raise
    shutil.rmtree(failed)


def _common_image_root(roots: tuple[Path, ...]) -> Path:
    if len(roots) == 1 and roots[0].parent.name != "instances":
        return roots[0]
    parents = {root.parent.resolve() for root in roots}
    if len(parents) != 1 or next(iter(parents)).name != "instances":
        raise ValueError("multi-package approval roots must share one image instances directory")
    names = {root.name for root in roots}
    if names != {f"p{index}" for index in range(len(names))}:
        raise ValueError("multi-package approval roots must be contiguous p0..pN")
    return next(iter(parents)).parent


def _existing_report_blocks(package_root: Path) -> tuple[QcResult, ...]:
    path = package_root / "qa_report.json"
    if not path.is_file():
        return ()
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (QcResult("QC-005", "qa_report_readable", False, str(exc), "BLOCK"),)
    return tuple(
        QcResult(
            str(check["id"]),
            str(check["name"]),
            False,
            str(check.get("message", "existing hard block")),
            "BLOCK",
        )
        for check in report.get("checks", ())
        if check.get("severity") == "BLOCK" and check.get("result") == "fail"
    )


def _regenerate_final_artifacts(package_root: Path) -> None:
    """Rebuild S13 derivatives and review visuals from the corrected authority maps."""
    derive_inpaint(package_root)
    part_map = read_mask(package_root / "label_map_part.png").astype(np.uint16)
    source_path = next(
        (
            path
            for path in (package_root / "source.png", package_root / "source.jpg")
            if path.is_file()
        ),
        None,
    )
    if source_path is None:
        raise FileNotFoundError("S13 package source image is missing")
    with Image.open(source_path) as opened:
        source = opened.convert("RGB")
    viz = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "configs/viz.yaml").read_text(encoding="utf-8")
    )
    render_part_overlays(
        source, part_map, package_root / "overlays", label_colors=viz["label_colors"]
    )
    authority = get_ontology()
    masks = {
        label.name: part_map == int(label.id)
        for label in authority.labels_for_map("part", enabled_only=True)
        if label.id and np.any(part_map == int(label.id))
    }
    for name, mask in masks.items():
        neighbor = np.zeros(mask.shape, dtype=bool)
        for other, other_mask in masks.items():
            if other != name:
                neighbor |= other_mask
        render_boundary_panel(source, mask, neighbor, package_root / "qa_panels" / f"{name}.png")


def verify_packages(root: Path, *, sample: int | None = None) -> tuple[PackageVerification, ...]:
    """Verify one package or every per-instance package beneath a restore/package root."""
    root = Path(root)
    if sample is not None and sample < 1:
        raise ValueError("sample must be a positive integer")
    candidates = (
        [root]
        if (root / "manifest.json").is_file()
        else sorted(
            {path.parent for path in root.rglob("manifest.json") if _is_package_manifest(path)}
        )
    )
    if sample is not None:
        candidates = sorted(
            candidates,
            key=lambda path: hashlib.sha256(str(path.resolve()).encode()).hexdigest(),
        )[:sample]
    if not candidates:
        raise FileNotFoundError(f"no package manifests under {root}")
    verifications = []
    for package in candidates:
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("mask_ontology_version") == "body_parts_v2":
            from .ontology_v2_operations import run_v2_restore_integrity

            results = run_v2_restore_integrity(package)
        else:
            results = run_qc001_010(package)
        verifications.append(
            PackageVerification(package, all(result.passed for result in results), results)
        )
    return tuple(verifications)


def _is_package_manifest(path: Path) -> bool:
    """Exclude nested derived-artifact manifests from restore/package discovery."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return all(key in document for key in ("image_id", "source", "parts", "files"))


def _stamp_gold_manifest(
    package_root: Path, reviewer: str, review_minutes: float, timestamp: datetime
) -> None:
    path = package_root / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for entry in manifest.get("parts", {}).values():
        if isinstance(entry, dict) and entry.get("status") != "n/a":
            entry["status"] = "human_approved_gold"
    review = manifest.setdefault("review", {})
    review.update(
        {
            "reviewer": reviewer,
            "approved_at": timestamp.isoformat(),
            "review_time_sec": round(review_minutes * 60),
        }
    )
    review.setdefault(
        "second_review",
        {"required": False, "reviewer": None, "result": "not_required", "at": None},
    )
    manifest["qa"] = {"qa_report_file": "qa_report.json", "qa_overall": "pass", "qa_score": 1.0}
    manifest["workflow_status"] = "approved_gold"
    manifest["workflow_updated_at"] = timestamp.isoformat()
    if manifest.get("mask_ontology_version") == "body_parts_v2":
        require_v2_supervision_eligible(manifest)
    _write_json_atomic(path, manifest)


def _bounce(package_root: Path, results: tuple[QcResult, ...]) -> None:
    path = package_root / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    for entry in manifest.get("parts", {}).values():
        if isinstance(entry, dict) and entry.get("status") != "n/a":
            entry["status"] = "rejected_needs_fix"
    manifest.setdefault("qa", {}).update({"qa_overall": "fail", "qa_score": 0.0})
    manifest["workflow_status"] = "in_review"
    manifest["workflow_updated_at"] = datetime.now(UTC).isoformat()
    _write_json_atomic(path, manifest)
    _write_json_atomic(
        package_root / "qa" / "package_block.json",
        {
            "results": [asdict(result) for result in results],
            "panels": _failing_panels(package_root, results),
        },
    )


def _qa_report(
    package_root: Path, results: tuple[QcResult, ...], timestamp: datetime
) -> dict[str, Any]:
    manifest = json.loads((package_root / "manifest.json").read_text(encoding="utf-8"))
    image_id = str(manifest["image_id"])
    return {
        "image_id": image_id,
        "run_id": f"qa_{timestamp:%Y%m%d_%H%M}_package",
        "pipeline_version": __version__,
        "created_at": timestamp.isoformat(),
        "checks": [
            {
                "id": result.qc_id,
                "name": result.name,
                "scope": "package",
                "result": "pass" if result.passed else "fail",
                "severity": result.severity,
                "action": "none" if result.passed else "block_package",
                "message": result.detail,
                "auto_fix_attempted": True,
                "auto_fix_succeeded": result.passed,
            }
            for result in results
        ],
        "metrics_per_part": {},
        "consensus": {"method": "p1_human_cvat", "sources": ["cvat"]},
        "vlm_review": {"model": "not_run_p1", "verdicts": []},
        "overall": "pass",
        "score": 1.0,
    }


def _refresh_files(package_root: Path) -> None:
    path = package_root / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    files = tuple(
        file
        for file in package_root.rglob("*")
        if file.is_file()
        and file.name != "manifest.json"
        and not file.relative_to(package_root).parts[0].startswith("masks@v")
    )
    manifest["files"] = sha256_file_map(package_root, files)
    _write_json_atomic(path, manifest)


def _failing_panels(package_root: Path, results: tuple[QcResult, ...]) -> tuple[str, ...]:
    panels = sorted((package_root / "qa_panels").glob("*.png"))
    return tuple(path.relative_to(package_root).as_posix() for path in panels)


def _require_dvc() -> None:
    try:
        process = run_dvc(("version",), timeout=30)
    except (DvcRuntimeError, OSError) as exc:
        raise RuntimeError(f"DVC is required before package approval: {exc}") from exc
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        raise RuntimeError(f"DVC is required before package approval: {detail}")


def _dvc_add(path: Path) -> None:
    try:
        process = run_dvc(("add", str(Path(path).resolve())), timeout=300)
    except (DvcRuntimeError, OSError) as exc:
        raise RuntimeError(f"dvc add failed: {exc}") from exc
    if process.returncode != 0:
        raise RuntimeError(f"dvc add failed: {process.stderr.strip()}")


def _write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
