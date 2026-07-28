"""Fail-closed direct LV-MHP auxiliary resources for hair control negatives.

The source supplies no governed hair laterality.  This module seals only the
four source-direct resource roles and refuses to emit a partial defect taxonomy.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .canonical_polygon_source_candidates import sha256_file
from .critic_catalog import canonical_sha256
from .lv_mhp_hair_control_candidates import (
    HAIR,
    _content,
    _identity,
    _inside,
    _manifest,
    _read,
    verify_lv_mhp_hair_control_candidates,
)
from .seeded_defect_controls import mask_sha256

FACE = 11
SCHEMA = "maskfactory.lv_mhp_v1_hair_auxiliary_resources.v1"
RESOURCE_ROLES = (
    "neighbor_mask",
    "other_owner_mask",
    "protected_region_mask",
    "wrong_label_mask",
)


class LvMhpHairAuxiliaryResourceError(ValueError):
    """An exact source binding or resource semantic constraint drifted."""


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    rows, cols = np.where(mask)
    if not len(rows):
        raise LvMhpHairAuxiliaryResourceError("resource mask is empty")
    return int(cols.min()), int(rows.min()), int(cols.max()), int(rows.max())


def _gap_squared(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> int:
    horizontal = max(0, max(first[0], second[0]) - min(first[2], second[2]) - 1)
    vertical = max(0, max(first[1], second[1]) - min(first[3], second[3]) - 1)
    return horizontal * horizontal + vertical * vertical


def _indexed(path: Path, dimensions: list[int]) -> np.ndarray:
    with Image.open(path) as image:
        value = np.asarray(image.convert("L"), dtype=np.uint8)
    if value.ndim != 2 or [int(value.shape[1]), int(value.shape[0])] != dimensions:
        raise LvMhpHairAuxiliaryResourceError(f"annotation geometry drift:{path}")
    if not set(int(item) for item in np.unique(value)).issubset(set(range(19))):
        raise LvMhpHairAuxiliaryResourceError(f"annotation encoding drift:{path}")
    return value


def _validate_remap(path: Path) -> None:
    document = _read(path, yaml_input=True)
    mappings = document.get("mappings")
    if not isinstance(mappings, Mapping) or document.get("source") != "lv_mhp_v1":
        raise LvMhpHairAuxiliaryResourceError("LV-MHP remap drift")
    hair = mappings.get(HAIR, mappings.get(str(HAIR)))
    face = mappings.get(FACE, mappings.get(str(FACE)))
    if (
        not isinstance(hair, Mapping)
        or not isinstance(face, Mapping)
        or hair.get("source_label") != "hair"
        or hair.get("action") != "direct"
        or hair.get("part") != ["hair"]
        or face.get("source_label") != "face"
        or face.get("action") != "direct"
        or face.get("part") != ["head_face"]
    ):
        raise LvMhpHairAuxiliaryResourceError("direct hair/face remap drift")


def _verify_candidate_inputs(
    candidate_document: Mapping[str, Any],
    source_hash_manifest_path: Path,
    identity_evidence_path: Path,
    remap_path: Path,
) -> None:
    bindings = candidate_document.get("input_bindings")
    expected = {
        "source_hash_manifest_sha256": sha256_file(source_hash_manifest_path),
        "identity_evidence_sha256": sha256_file(identity_evidence_path),
        "remap_sha256": sha256_file(remap_path),
    }
    if not isinstance(bindings, Mapping) or any(
        bindings.get(key) != value for key, value in expected.items()
    ):
        raise LvMhpHairAuxiliaryResourceError("candidate input binding drift")


def _build_plan(
    content: Path,
    candidate: Mapping[str, Any],
    identities: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, str],
) -> dict[str, Any]:
    image_id = Path(str(candidate["source_relative_path"])).stem
    identity = identities.get(image_id)
    if (
        identity is None
        or candidate.get("source_relative_path") != identity.get("image_path")
        or candidate.get("declared_person_count") != identity.get("person_count")
    ):
        raise LvMhpHairAuxiliaryResourceError(f"candidate identity drift:{candidate['sample_id']}")
    target_instance = int(candidate["source_instance_id"])
    annotations = identity.get("annotation_paths")
    instances = identity.get("instance_ids")
    if (
        target_instance not in instances
        or candidate.get("instance_annotation_relative_path") not in annotations
    ):
        raise LvMhpHairAuxiliaryResourceError(
            f"candidate annotation drift:{candidate['sample_id']}"
        )
    image_path = _inside(content, str(candidate["source_relative_path"]))
    if sha256_file(image_path) != candidate.get("source_sha256"):
        raise LvMhpHairAuxiliaryResourceError(f"source hash drift:{candidate['sample_id']}")
    with Image.open(image_path) as image:
        dimensions = [int(value) for value in image.size]
    if dimensions != candidate.get("source_dimensions"):
        raise LvMhpHairAuxiliaryResourceError(f"source geometry drift:{candidate['sample_id']}")
    indexed: dict[int, np.ndarray] = {}
    paths: dict[int, str] = {}
    for instance, relative in zip(instances, annotations, strict=True):
        if relative not in manifest:
            raise LvMhpHairAuxiliaryResourceError(f"source manifest omits:{relative}")
        annotation = _inside(content, relative)
        if sha256_file(annotation) != manifest[relative]:
            raise LvMhpHairAuxiliaryResourceError(f"annotation hash drift:{relative}")
        indexed[int(instance)] = _indexed(annotation, dimensions)
        paths[int(instance)] = relative
    target_indexed = indexed[target_instance]
    target = target_indexed == HAIR
    if (
        not target.any()
        or int(np.count_nonzero(target)) != candidate.get("mask_pixel_count")
        or paths[target_instance] != candidate.get("instance_annotation_relative_path")
        or manifest[paths[target_instance]] != candidate.get("instance_annotation_sha256")
    ):
        raise LvMhpHairAuxiliaryResourceError(f"target hair drift:{candidate['sample_id']}")
    face = target_indexed == FACE
    if not face.any() or not np.any(face & ~target):
        raise LvMhpHairAuxiliaryResourceError(
            f"direct face resource unavailable:{candidate['sample_id']}"
        )
    target_bbox = _bbox(target)
    available = []
    for instance, value in indexed.items():
        if instance == target_instance:
            continue
        hair = value == HAIR
        if hair.any() and np.any(hair & ~target):
            available.append((_gap_squared(target_bbox, _bbox(hair)), instance, hair))
    if not available:
        raise LvMhpHairAuxiliaryResourceError(
            f"direct other-person hair resource unavailable:{candidate['sample_id']}"
        )
    gap, neighbor_instance, neighbor = min(available, key=lambda row: (row[0], row[1]))
    return {
        "candidate": candidate,
        "target": target,
        "face": face,
        "neighbor": neighbor,
        "neighbor_instance": neighbor_instance,
        "neighbor_annotation": paths[neighbor_instance],
        "target_bbox": list(target_bbox),
        "neighbor_bbox": list(_bbox(neighbor)),
        "neighbor_gap_squared": gap,
    }


def _write_mask(
    stage: Path,
    sample_id: str,
    role: str,
    mask: np.ndarray,
    source_value: int,
    source_name: str,
    source_instance: int,
    annotation_path: str,
) -> dict[str, Any]:
    value = np.where(mask, 255, 0).astype(np.uint8)
    relative = Path(sample_id) / f"{role}.png"
    path = stage / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(value, mode="L").save(path, format="PNG", optimize=False, compress_level=9)
    return {
        "path": relative.as_posix(),
        "encoded_png_sha256": sha256_file(path),
        "raster_sha256": mask_sha256(value),
        "pixel_count": int(np.count_nonzero(value)),
        "dimensions": [int(value.shape[1]), int(value.shape[0])],
        "source_label_value": source_value,
        "source_label_name": source_name,
        "source_instance_id": source_instance,
        "source_annotation_relative_path": annotation_path,
    }


def materialize_lv_mhp_hair_auxiliary_resources(
    *,
    source_root: Path,
    candidate_document: Mapping[str, Any],
    source_hash_manifest_path: Path,
    identity_evidence_path: Path,
    remap_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    """Seal four exact resource roles while explicitly deferring hair laterality."""
    verify_lv_mhp_hair_control_candidates(candidate_document)
    _verify_candidate_inputs(
        candidate_document, source_hash_manifest_path, identity_evidence_path, remap_path
    )
    _validate_remap(remap_path)
    content = _content(source_root)
    manifest_document = _read(source_hash_manifest_path)
    identity_document = _read(identity_evidence_path)
    manifest, identities = _manifest(manifest_document), _identity(identity_document)
    output = Path(output_root)
    if output.exists():
        raise LvMhpHairAuxiliaryResourceError("auxiliary-resource output already exists")
    plans = [
        _build_plan(content, row, identities, manifest) for row in candidate_document["selected"]
    ]
    stage = output.with_name(f".{output.name}.tmp-{uuid.uuid4().hex}")
    try:
        stage.mkdir(parents=True)
        records = []
        for plan in plans:
            candidate = plan["candidate"]
            sample_id = str(candidate["sample_id"])
            target_instance = int(candidate["source_instance_id"])
            face_args = (
                stage,
                sample_id,
                plan["face"],
                FACE,
                "face",
                target_instance,
                str(candidate["instance_annotation_relative_path"]),
            )
            neighbor_args = (
                stage,
                sample_id,
                plan["neighbor"],
                HAIR,
                "hair",
                plan["neighbor_instance"],
                plan["neighbor_annotation"],
            )
            roles = {
                "neighbor_mask": _write_mask(
                    *neighbor_args[:2], "neighbor_mask", *neighbor_args[2:]
                ),
                "other_owner_mask": _write_mask(
                    *neighbor_args[:2], "other_owner_mask", *neighbor_args[2:]
                ),
                "protected_region_mask": _write_mask(
                    *face_args[:2], "protected_region_mask", *face_args[2:]
                ),
                "wrong_label_mask": _write_mask(*face_args[:2], "wrong_label_mask", *face_args[2:]),
            }
            records.append(
                {
                    "sample_id": sample_id,
                    "source_image_id": candidate["source_image_id"],
                    "source_relative_path": candidate["source_relative_path"],
                    "source_sha256": candidate["source_sha256"],
                    "target_instance_id": target_instance,
                    "target_hair_raster_sha256": mask_sha256(plan["target"]),
                    "target_hair_pixel_count": int(np.count_nonzero(plan["target"])),
                    "neighbor_selection": {
                        "policy": "nearest_other_person_hair_by_bbox_gap_then_instance_id",
                        "target_bbox_xyxy": plan["target_bbox"],
                        "neighbor_bbox_xyxy": plan["neighbor_bbox"],
                        "bbox_gap_squared": plan["neighbor_gap_squared"],
                        "neighbor_instance_id": plan["neighbor_instance"],
                    },
                    "resource_roles": roles,
                    "opposite_side_mask": {
                        "status": "DEFERRED_SOURCE_SEMANTICS",
                        "reason": "LV-MHP label 2 has no governed hair laterality; no heuristic inference.",
                    },
                    "seeded_defect_taxonomy_emission_allowed": False,
                    "authority_claimed": False,
                }
            )
        report: dict[str, Any] = {
            "schema_version": SCHEMA,
            "artifact_type": "lv_mhp_v1_hair_auxiliary_seeded_defect_resources",
            "status": "PARTIAL_RESOURCE_SET_SEALED",
            "candidate_set_sha256": candidate_document["self_sha256"],
            "input_bindings": {
                "source_hash_manifest_sha256": sha256_file(source_hash_manifest_path),
                "source_hash_manifest_seal_sha256": manifest_document["seal_sha256"],
                "identity_evidence_sha256": sha256_file(identity_evidence_path),
                "identity_evidence_seal_sha256": identity_document["seal_sha256"],
                "remap_sha256": sha256_file(remap_path),
            },
            "record_count": len(records),
            "materialized_resource_roles": list(RESOURCE_ROLES),
            "materialized_resource_count_per_record": len(RESOURCE_ROLES),
            "records": records,
            "unmaterialized_required_resources": {
                "opposite_side_mask": {
                    "status": "DEFERRED_SOURCE_SEMANTICS",
                    "reason": "No direct LV-MHP hair laterality label; pose/pixel/filename inference is forbidden.",
                }
            },
            "all_seeded_defect_resources_materialized": False,
            "seeded_defect_taxonomy_emission_allowed": False,
            "seeded_defect_controls_emitted": False,
            "authority_claimed": False,
            "gold_or_training_truth_allowed": False,
            "certificate_issuance_allowed": False,
            "next_required_stage": "seal a source-governed hair laterality resource before atomic ten-class emission",
        }
        report["self_sha256"] = canonical_sha256(report)
        (stage / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        verify_lv_mhp_hair_auxiliary_resource_report(report, stage)
        os.replace(stage, output)
        return report
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def verify_lv_mhp_hair_auxiliary_resource_report(document: Mapping[str, Any], root: Path) -> None:
    """Verify every resource byte and the immutable no-laterality ceiling."""
    expected = canonical_sha256(
        {key: value for key, value in document.items() if key != "self_sha256"}
    )
    if (
        document.get("schema_version") != SCHEMA
        or document.get("artifact_type") != "lv_mhp_v1_hair_auxiliary_seeded_defect_resources"
        or document.get("status") != "PARTIAL_RESOURCE_SET_SEALED"
        or document.get("self_sha256") != expected
        or document.get("all_seeded_defect_resources_materialized") is not False
        or document.get("seeded_defect_taxonomy_emission_allowed") is not False
        or document.get("seeded_defect_controls_emitted") is not False
        or document.get("authority_claimed") is not False
        or document.get("gold_or_training_truth_allowed") is not False
        or document.get("certificate_issuance_allowed") is not False
    ):
        raise LvMhpHairAuxiliaryResourceError("auxiliary-resource report contract drift")
    records = document.get("records")
    if (
        not isinstance(records, list)
        or document.get("record_count") != len(records)
        or document.get("materialized_resource_roles") != list(RESOURCE_ROLES)
        or document.get("materialized_resource_count_per_record") != len(RESOURCE_ROLES)
    ):
        raise LvMhpHairAuxiliaryResourceError("auxiliary-resource report count drift")
    output = Path(root).resolve(strict=True)
    for record in records:
        roles = record.get("resource_roles", {})
        if (
            record.get("authority_claimed") is not False
            or record.get("seeded_defect_taxonomy_emission_allowed") is not False
            or set(roles) != set(RESOURCE_ROLES)
            or record.get("opposite_side_mask", {}).get("status") != "DEFERRED_SOURCE_SEMANTICS"
        ):
            raise LvMhpHairAuxiliaryResourceError("auxiliary-resource record contract drift")
        for role, entry in roles.items():
            relative = Path(str(entry.get("path", "")))
            if relative.is_absolute() or ".." in relative.parts:
                raise LvMhpHairAuxiliaryResourceError("auxiliary-resource path escape")
            path = (output / relative).resolve(strict=True)
            try:
                path.relative_to(output)
            except ValueError as exc:
                raise LvMhpHairAuxiliaryResourceError("auxiliary-resource path escape") from exc
            expected_label = FACE if role in {"protected_region_mask", "wrong_label_mask"} else HAIR
            if entry.get("source_label_value") != expected_label or sha256_file(path) != entry.get(
                "encoded_png_sha256"
            ):
                raise LvMhpHairAuxiliaryResourceError("auxiliary-resource encoded hash drift")
            with Image.open(path) as image:
                value = np.asarray(image.convert("L"), dtype=np.uint8)
            if (
                value.ndim != 2
                or not np.isin(value, [0, 255]).all()
                or not np.count_nonzero(value)
                or [int(value.shape[1]), int(value.shape[0])] != entry.get("dimensions")
                or int(np.count_nonzero(value)) != entry.get("pixel_count")
                or mask_sha256(value) != entry.get("raster_sha256")
            ):
                raise LvMhpHairAuxiliaryResourceError("auxiliary-resource raster drift")
