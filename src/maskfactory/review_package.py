"""Deterministic draft package assembly for S12 CVAT review."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage

from . import __version__
from .fs_atomic import replace_with_retry
from .fusion.mapbuild import export_binaries
from .io.hashing import sha256_file
from .io.png_strict import read_mask
from .io.writers import write_json_atomic
from .ontology import get_ontology
from .validation import ArtifactValidationError, validate_document


def assemble_review_package(
    *,
    image_id: str,
    instance_index: int,
    source_crop_path: Path,
    part_map_path: Path,
    material_map_path: Path,
    s09_dir: Path,
    s11_dir: Path,
    pose_path: Path,
    person_bbox_xyxy: tuple[int, int, int, int],
    context_bbox_xyxy: tuple[int, int, int, int],
    person_count: int,
    intake_source: dict[str, Any],
    package_root: Path,
    ambiguity_path: Path | None = None,
) -> Path:
    """Create the schema-valid draft instance consumed by cvat push/pull."""
    package_root = Path(package_root)
    existing_manifest = package_root / "manifest.json"
    if existing_manifest.is_file():
        existing = json.loads(existing_manifest.read_text(encoding="utf-8"))
        statuses = {
            entry.get("status")
            for entry in existing.get("parts", {}).values()
            if isinstance(entry, dict)
        }
        if statuses & {"human_corrected", "human_approved_gold"}:
            raise RuntimeError("refusing to overwrite a human-corrected or approved review package")
    package_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_crop_path, package_root / "source.png")
    shutil.copy2(part_map_path, package_root / "label_map_part.png")
    shutil.copy2(material_map_path, package_root / "label_map_material.png")
    snapshot_draft_baseline(
        package_root,
        image_id=image_id,
        instance_id=f"p{instance_index}",
        allow_replace=True,
    )
    export_binaries(package_root)
    overlays = package_root / "overlays"
    overlays.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(s11_dir) / "qa_panels/all_parts.png", overlays / "all_parts.png")
    shutil.copy2(
        Path(s09_dir) / "work/s09/disagreement.png",
        overlays / "disagreement_heatmap.png",
    )
    shutil.copy2(Path(s11_dir) / "qa_report.json", package_root / "qa_report.json")
    if (Path(s09_dir) / "masks_regions").is_dir():
        shutil.copytree(
            Path(s09_dir) / "masks_regions",
            package_root / "masks_regions",
            dirs_exist_ok=True,
        )
    if (Path(s11_dir) / "qa_panels").is_dir():
        shutil.copytree(
            Path(s11_dir) / "qa_panels",
            package_root / "qa_panels",
            dirs_exist_ok=True,
        )
    pose = json.loads(Path(pose_path).read_text(encoding="utf-8"))
    report = json.loads((package_root / "qa_report.json").read_text(encoding="utf-8"))
    source_sha = _sha256(package_root / "source.png")
    with Image.open(package_root / "source.png") as source_image:
        width, height = source_image.size
    full_x1, full_y1, full_x2, full_y2 = person_bbox_xyxy
    ctx_x1, ctx_y1, _, _ = context_bbox_xyxy
    crop_bbox = [
        max(0, full_x1 - ctx_x1),
        max(0, full_y1 - ctx_y1),
        min(width, full_x2 - ctx_x1),
        min(height, full_y2 - ctx_y1),
    ]
    authority = get_ontology()
    ambiguity = (
        read_mask(ambiguity_path) > 0
        if ambiguity_path is not None and Path(ambiguity_path).is_file()
        else np.zeros((height, width), dtype=bool)
    )
    if ambiguity.shape != (height, width):
        raise ValueError("S12 ambiguity mask dimensions differ from source crop")
    parts = {}
    for label in authority.labels_for_map("part", enabled_only=True):
        if label.id == 0:
            continue
        directory = "protected" if label.mask_type == "protected_qa" else "masks"
        relative = Path(directory) / f"{label.name}.png"
        mask = read_mask(package_root / relative) > 0
        ys, xs = np.nonzero(mask)
        visible = bool(len(xs))
        ambiguous = bool(np.any(mask & ambiguity))
        authoritative_mask = visible and not (ambiguous and label.mask_type == "atomic_exclusive")
        parts[label.name] = {
            "mask_type": label.mask_type,
            "visibility": "ambiguous_do_not_use"
            if ambiguous
            else "visible"
            if visible
            else "not_visible",
            "mask_file": relative.as_posix() if authoritative_mask else None,
            "mask_sha256": (_sha256(package_root / relative) if authoritative_mask else None),
            "mask_area_px": int(mask.sum()) if authoritative_mask else None,
            "mask_bbox": (
                [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
                if authoritative_mask
                else None
            ),
            "components": int(ndimage.label(mask)[1]) if authoritative_mask else None,
            "status": "draft_model_generated" if authoritative_mask else "n/a",
            "annotated_on": "full",
            "occlusion": {"occluded_by": [], "occludes": [], "layer": "unknown"},
            "provenance": {
                "draft_source": "s09_weighted_consensus",
                "sam2_prompt_id": label.name if authoritative_mask else None,
                "human_edit": False,
            },
            "notes": "Co-subject overlap requires careful human review." if ambiguous else "",
        }
    manifest = {
        "schema_version": "1.0.0",
        "image_id": image_id,
        "mask_ontology_version": authority.version,
        "left_right_convention": "character_perspective",
        "workflow_status": "drafted",
        "workflow_updated_at": report["created_at"],
        "source": {
            "source_file": "source.png",
            "source_sha256": source_sha,
            "parent_source_sha256": intake_source["source_sha256"],
            "source_width": width,
            "source_height": height,
            "source_origin": intake_source["source_origin"],
            "origin_note": f"governed instance crop of {intake_source.get('original_name', 'source')}",
            "ingested_at": intake_source["ingested_at"],
            "exif_stripped": True,
            **(
                {"phash64": intake_source["phash64"]}
                if intake_source.get("phash64") is not None
                else {}
            ),
        },
        "person": {
            "primary_person_bbox": crop_bbox,
            "person_count": person_count,
            "view": pose["view"],
            "pose_tags": pose["pose_tags"],
            "estimated_person_height_px": max(1, crop_bbox[3] - crop_bbox[1]),
        },
        "interperson": [],
        "parts": parts,
        "inpaint_derivatives": [],
        "tooling": {
            "annotation_tool": "cvat",
            "annotation_tool_version": "2.24.0",
            "pipeline_version": f"maskfactory {__version__}",
            "model_versions_used": {
                "sam2": "2.1_hiera_large_or_base_plus",
                "densepose": "R_50_FPN_s1x",
            },
            "config_hashes": {
                name: _sha256(Path("configs") / name)
                for name in (
                    "ontology.yaml",
                    "pipeline.yaml",
                    "prompting.yaml",
                    "qa.yaml",
                    "vlm.yaml",
                )
            },
        },
        "review": {
            "reviewer": None,
            "approved_at": None,
            "second_review": {
                "required": False,
                "reviewer": None,
                "result": "not_required",
                "at": None,
            },
            "review_time_sec": None,
        },
        "qa": {
            "qa_report_file": "qa_report.json",
            "qa_overall": report["overall"],
            "qa_score": report["score"],
        },
        "files": {},
    }
    manifest["files"] = {
        path.relative_to(package_root).as_posix(): _sha256(path)
        for path in sorted(package_root.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }
    issues = validate_document(manifest, "manifest")
    if issues:
        raise ArtifactValidationError(issues)
    (package_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return package_root


def ensure_parent_source_identity(package_root: Path, parent_source_sha256: str) -> bool:
    """Seal image-level identity into a legacy instance package without touching annotations."""
    package_root = Path(package_root)
    manifest_path = package_root / "manifest.json"
    if not manifest_path.is_file():
        return False
    if len(parent_source_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in parent_source_sha256
    ):
        raise ValueError("parent source SHA-256 must be 64 lowercase hex characters")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_path = package_root / manifest["source"]["source_file"]
    if not source_path.is_file() or sha256_file(source_path) != manifest["source"]["source_sha256"]:
        raise RuntimeError("instance source crop hash does not match its manifest")
    existing = manifest["source"].get("parent_source_sha256")
    if existing is not None:
        if existing != parent_source_sha256:
            raise RuntimeError("refusing to replace conflicting parent source identity")
        return False
    manifest["source"]["parent_source_sha256"] = parent_source_sha256
    issues = validate_document(manifest, "manifest")
    if issues:
        raise RuntimeError(f"parent source identity migration produced invalid manifest: {issues}")
    write_json_atomic(manifest_path, manifest)
    return True


def update_package_workflow_status(
    package_root: Path,
    target_status: str,
    *,
    updated_at: str | None = None,
) -> bool:
    """Advance package-level workflow authority without mutating per-part review state."""
    ranks = {
        "drafted": 0,
        "auto_qa": 1,
        "vlm_qa": 2,
        "in_review": 3,
        "corrected": 4,
        "approved_gold": 5,
        "exported": 6,
        "deprecated": 7,
    }
    if target_status not in ranks:
        raise ValueError(f"invalid package workflow status: {target_status}")
    package_root = Path(package_root)
    manifest_path = package_root / "manifest.json"
    if not manifest_path.is_file():
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    current = manifest.get("workflow_status", "drafted")
    if current not in ranks:
        raise RuntimeError(f"invalid existing package workflow status: {current}")
    if ranks[current] >= ranks[target_status]:
        return False
    manifest["workflow_status"] = target_status
    manifest["workflow_updated_at"] = updated_at or datetime.now(UTC).isoformat()
    issues = validate_document(manifest, "manifest")
    if issues:
        raise RuntimeError(f"workflow status update produced invalid manifest: {issues}")
    write_json_atomic(manifest_path, manifest)
    return True


def snapshot_draft_baseline(
    package_root: Path,
    *,
    image_id: str,
    instance_id: str,
    allow_replace: bool = False,
) -> Path:
    """Seal the pre-human S09 maps used later by S15 edit-delta mining."""
    package_root = Path(package_root)
    if not instance_id.startswith("p") or not instance_id[1:].isdigit():
        raise ValueError("draft baseline instance_id must be pN")
    part_source = package_root / "label_map_part.png"
    material_source = package_root / "label_map_material.png"
    if not part_source.is_file() or not material_source.is_file():
        raise FileNotFoundError("draft baseline requires both authoritative label maps")
    destination = package_root / "annotations" / "draft_baseline"
    manifest_path = destination / "baseline_manifest.json"
    part_sha = _sha256(part_source)
    material_sha = _sha256(material_source)
    if manifest_path.is_file() and not allow_replace:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            document.get("image_id") != image_id
            or document.get("instance_id") != instance_id
            or document.get("source_stage") != "S09_weighted_consensus"
        ):
            raise ValueError(f"sealed draft baseline identity is invalid: {manifest_path}")
        for name, digest in (
            ("label_map_part.png", document.get("part_map_sha256")),
            ("label_map_material.png", document.get("material_map_sha256")),
        ):
            path = destination / name
            if not path.is_file() or _sha256(path) != digest:
                raise ValueError(f"sealed draft baseline is corrupt: {path}")
        return manifest_path
    staging = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    backup = destination.with_name(f".{destination.name}.old-{uuid.uuid4().hex}")
    try:
        staging.mkdir(parents=True)
        shutil.copy2(part_source, staging / "label_map_part.png")
        shutil.copy2(material_source, staging / "label_map_material.png")
        document = {
            "schema_version": "1.0.0",
            "image_id": image_id,
            "instance_id": instance_id,
            "source_stage": "S09_weighted_consensus",
            "part_map_sha256": part_sha,
            "material_map_sha256": material_sha,
        }
        (staging / "baseline_manifest.json").write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if destination.exists():
            replace_with_retry(destination, backup)
        try:
            replace_with_retry(staging, destination)
        except Exception:
            if backup.exists():
                replace_with_retry(backup, destination)
            raise
        shutil.rmtree(backup, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return manifest_path


def finalize_image_package_index(
    image_root: Path,
    reconciliation_manifest_path: Path,
) -> Path:
    """Install S09.5 relationships into finalized per-instance package manifests."""
    image_root = Path(image_root)
    reconciliation = json.loads(Path(reconciliation_manifest_path).read_text(encoding="utf-8"))
    image_id = str(reconciliation["image_id"])
    promoted = tuple(str(value) for value in reconciliation["promoted_instances"])
    if not promoted or promoted != tuple(f"p{index}" for index in range(len(promoted))):
        raise ValueError("promoted instances must be contiguous p0..pN in rank order")

    entries: dict[str, list[dict[str, str]]] = {instance_id: [] for instance_id in promoted}
    for relationship in reconciliation.get("interperson_relationships", []):
        a = str(relationship["a"])
        b = str(relationship["b"])
        if a not in entries or b not in entries or a == b:
            raise ValueError("interperson relationship references an invalid instance")
        kind = str(relationship["relationship"])
        reciprocal = {"contact": "contact", "occludes": "occluded_by", "occluded_by": "occludes"}
        if kind not in reciprocal:
            raise ValueError(f"unsupported interperson relationship: {kind}")
        entries[a].append(
            {
                "other_instance_id": f"{image_id}_{b}",
                "relationship": kind,
                "contact_band_file": _instance_relative_band(
                    relationship["contact_band_file_a"], a
                ),
            }
        )
        entries[b].append(
            {
                "other_instance_id": f"{image_id}_{a}",
                "relationship": reciprocal[kind],
                "contact_band_file": _instance_relative_band(
                    relationship["contact_band_file_b"], b
                ),
            }
        )

    for instance_id in promoted:
        package_root = image_root / "instances" / instance_id
        manifest_path = package_root / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"missing package manifest for {instance_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("image_id") != image_id:
            raise ValueError(f"{instance_id} manifest image_id mismatch")
        manifest["interperson"] = sorted(
            entries[instance_id], key=lambda item: item["other_instance_id"]
        )
        for entry in manifest["interperson"]:
            if not (package_root / entry["contact_band_file"]).is_file():
                raise FileNotFoundError(
                    f"{instance_id} contact band missing: {entry['contact_band_file']}"
                )
        manifest["files"] = {
            path.relative_to(package_root).as_posix(): _sha256(path)
            for path in sorted(package_root.rglob("*"))
            if path.is_file() and path.name != "manifest.json"
        }
        issues = validate_document(manifest, "manifest")
        if issues:
            raise ArtifactValidationError(issues)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    destination = image_root / "image_manifest.json"
    destination.write_text(
        json.dumps(reconciliation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return destination


def _instance_relative_band(value: Any, instance_id: str) -> str:
    path = Path(str(value))
    expected = Path("instances") / instance_id
    try:
        relative = path.relative_to(expected)
    except ValueError as exc:
        raise ValueError(f"contact band is not owned by {instance_id}: {path}") from exc
    if relative.as_posix() != "masks_regions/interperson_contact_boundary.png":
        raise ValueError(f"unexpected contact band path for {instance_id}: {relative}")
    return relative.as_posix()


def _sha256(path: Path) -> str:
    return sha256_file(path)
