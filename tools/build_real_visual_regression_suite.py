#!/usr/bin/env python3
"""Build the frozen real-image visual-regression v2 suite from LV-MHP labels."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from maskfactory.vlm.critic_catalog import canonical_sha256
from maskfactory.vlm.panel_renderer import render_target_panels, transform_sha256
from maskfactory.vlm.regression_suite import (
    REQUIRED_DOMAINS,
    regression_case_sha256,
    regression_suite_sha256,
    validate_regression_suite_files,
)
from maskfactory.vlm.target_contract import target_contract_sha256

PANEL_NAMES = (
    "source",
    "binary_mask",
    "overlay",
    "contour",
    "full_context",
    "uncertainty_zoom",
    "disagreement",
)
MAX_PANEL_EDGE = 1280
DOMAIN_SPECS = {
    "clothing_skin_boundary": {
        "target_id": 18,
        "alternative_id": 4,
        "label": "torso_skin_external_reference",
        "defect": "wrong_label",
    },
    "feet": {
        "target_id": 9,
        "alternative_id": 10,
        "label": "left_foot_external_reference",
        "defect": "wrong_side",
    },
    "hair": {
        "target_id": 2,
        "alternative_id": 11,
        "label": "hair_external_reference",
        "defect": "boundary",
    },
    "hands": {
        "target_id": 14,
        "alternative_id": 15,
        "label": "left_hand_region_external_reference",
        "defect": "wrong_side",
    },
    "multi_person_ownership": {
        "target_id": 15,
        "alternative_id": 14,
        "label": "right_arm_external_reference",
        "defect": "ownership",
        "requires_neighbor": True,
    },
    "occlusion_contact": {
        "target_id": 15,
        "alternative_id": 11,
        "label": "right_arm_external_reference",
        "defect": "protected_region",
    },
    "visible_anatomy": {
        "target_id": 11,
        "alternative_id": 18,
        "label": "face_external_reference",
        "defect": "wrong_label",
    },
}


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _png(array: np.ndarray, mode: str) -> bytes:
    stream = io.BytesIO()
    Image.fromarray(array, mode=mode).save(stream, format="PNG", optimize=False, compress_level=9)
    return stream.getvalue()


def _qualification_sha256(project_root: Path) -> str:
    paths = (
        "configs/maskedwarehouse_provenance.yaml",
        "configs/maskedwarehouse_inventory.json",
        "configs/remap/lv_mhp_v1.yaml",
        "qa/external_supervision/lv_mhp_v1/official_license_recorded.json",
        "qa/external_supervision/lv_mhp_v1/deterministic_remap_tested.json",
        "qa/external_supervision/lv_mhp_v1/visual_alignment_qa_passed.json",
        "qa/live_verification/lv_mhp_full_source_hash_manifest_20260719.json",
    )
    bindings = {}
    for relative in paths:
        path = project_root / relative
        if not path.is_file():
            raise ValueError(f"required LV-MHP qualification evidence is missing: {relative}")
        bindings[relative] = _sha_file(path)
    return canonical_sha256(
        {
            "source": "lv_mhp_v1",
            "scope": "real_visual_regression",
            "authority": "external_labeled_reference",
            "evidence": bindings,
        }
    )


def _annotation_groups(content: Path) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = defaultdict(list)
    for path in sorted((content / "annotations").glob("*.png"), key=lambda item: item.name):
        groups[path.stem.split("_", 1)[0]].append(path)
    return groups


def _review_resolution(
    source: np.ndarray, maps: list[np.ndarray]
) -> tuple[np.ndarray, list[np.ndarray]]:
    """Bound committed review panels while preserving nearest-neighbor label pixels."""

    height, width = source.shape[:2]
    longest = max(height, width)
    if longest <= MAX_PANEL_EDGE:
        return source, maps
    scale = MAX_PANEL_EDGE / longest
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    resized_source = np.asarray(
        Image.fromarray(source, mode="RGB").resize(size, resample=Image.Resampling.LANCZOS),
        dtype=np.uint8,
    )
    resized_maps = [
        np.asarray(
            Image.fromarray(array, mode="L").resize(size, resample=Image.Resampling.NEAREST),
            dtype=np.uint8,
        )
        for array in maps
    ]
    return resized_source, resized_maps


def _select_scene(
    content: Path,
    groups: dict[str, list[Path]],
    spec: dict[str, Any],
    *,
    used_image_ids: set[str],
) -> dict[str, Any]:
    for image_id, annotation_paths in groups.items():
        if image_id in used_image_ids:
            continue
        source_path = content / "images" / f"{image_id}.jpg"
        if not source_path.is_file():
            continue
        maps: list[np.ndarray] = []
        for annotation_path in annotation_paths:
            with Image.open(annotation_path) as opened:
                maps.append(np.asarray(opened.convert("L"), dtype=np.uint8))
        if not maps or any(array.shape != maps[0].shape for array in maps):
            continue
        with Image.open(source_path) as opened:
            source = np.asarray(opened.convert("RGB"), dtype=np.uint8)
        if source.shape[:2] != maps[0].shape:
            continue
        source, maps = _review_resolution(source, maps)
        for owner_index, owner_map in enumerate(maps):
            target = owner_map == int(spec["target_id"])
            alternative = owner_map == int(spec["alternative_id"])
            if int(target.sum()) < 64 or int(alternative.sum()) < 64:
                continue
            neighbor_index = next(
                (
                    index
                    for index, array in enumerate(maps)
                    if index != owner_index and int((array == int(spec["target_id"])).sum()) >= 64
                ),
                None,
            )
            if spec.get("requires_neighbor") and neighbor_index is None:
                continue
            used_image_ids.add(image_id)
            return {
                "image_id": image_id,
                "source_path": source_path,
                "annotation_paths": annotation_paths,
                "source": source,
                "owner_index": owner_index,
                "owner": owner_map > 0,
                "target": target,
                "alternative": alternative,
                "neighbor": (
                    maps[neighbor_index] == int(spec["target_id"])
                    if neighbor_index is not None
                    else np.zeros_like(target)
                ),
                "protected": owner_map == 11,
            }
    raise ValueError(f"LV-MHP has no unused eligible scene for {spec['label']}")


def _translate(mask: np.ndarray, offset: int = 4) -> np.ndarray:
    shifted = np.zeros_like(mask)
    shifted[:, offset:] = mask[:, :-offset]
    return shifted


def _candidate(scene: dict[str, Any], defect: str | None) -> np.ndarray:
    if defect is None:
        return scene["target"].copy()
    if defect == "boundary":
        return _translate(scene["target"])
    if defect in {"wrong_label", "wrong_side"}:
        return scene["alternative"].copy()
    if defect == "ownership":
        return scene["neighbor"].copy()
    if defect == "protected_region":
        return scene["target"] | scene["protected"]
    raise ValueError(f"unsupported real regression defect: {defect}")


def _focus_crop(target: np.ndarray, candidate: np.ndarray) -> tuple[int, int, int, int]:
    focus = target | candidate
    rows, columns = np.nonzero(focus)
    height, width = focus.shape
    if not len(rows):
        return (0, 0, width, height)
    x0, x1 = int(columns.min()), int(columns.max()) + 1
    y0, y1 = int(rows.min()), int(rows.max()) + 1
    padding = max(16, round(max(x1 - x0, y1 - y0) * 0.3))
    return (
        max(0, x0 - padding),
        max(0, y0 - padding),
        min(width, x1 + padding),
        min(height, y1 + padding),
    )


def build(
    output_root: Path,
    *,
    maskedwarehouse_root: Path,
    reference_root: Path,
    project_root: Path,
) -> dict[str, Any]:
    """Materialize a real, image-disjoint positive/serious regression suite."""

    output_root = Path(output_root)
    if output_root.exists():
        raise ValueError(f"real visual regression suite already exists: {output_root}")
    warehouse = Path(maskedwarehouse_root).resolve(strict=True)
    content = warehouse / "Body" / "LV-MHP-v1" / "LV-MHP-v1"
    if not (content / "images").is_dir() or not (content / "annotations").is_dir():
        raise ValueError("LV-MHP content root is missing")
    reference = Path(reference_root).resolve(strict=True)
    reference_inventory = reference / "manifests" / "inventory_summary.json"
    if not reference_inventory.is_file():
        raise ValueError("reference-library inventory summary is missing")
    project = Path(project_root).resolve(strict=True)
    qualification_sha256 = _qualification_sha256(project)
    groups = _annotation_groups(content)
    used_image_ids: set[str] = set()
    stage = output_root.with_name(f".{output_root.name}.tmp-{uuid.uuid4().hex}")
    try:
        stage.mkdir(parents=True)
        cases: list[dict[str, Any]] = []
        case_index = 0
        for domain in REQUIRED_DOMAINS:
            spec = DOMAIN_SPECS[domain]
            for expected_outcome in ("valid_mask", "serious_defect"):
                case_index += 1
                scene = _select_scene(content, groups, spec, used_image_ids=used_image_ids)
                defect = spec["defect"] if expected_outcome == "serious_defect" else None
                candidate = _candidate(scene, defect)
                source_bytes = _png(scene["source"], "RGB")
                candidate_bytes = _png(candidate.astype(np.uint8) * 255, "L")
                source_panel_sha256 = hashlib.sha256(source_bytes).hexdigest()
                candidate_sha256 = hashlib.sha256(candidate_bytes).hexdigest()
                height, width = candidate.shape
                suffix = "valid" if defect is None else defect
                case_id = f"rvr_{case_index:03d}_{domain}_{suffix}"
                contract = {
                    "schema_version": "1.0.0",
                    "contract_id": f"target-{case_id}",
                    "source": {
                        "image_id": f"lv_mhp_v1-{scene['image_id']}",
                        "sha256": source_panel_sha256,
                        "width": width,
                        "height": height,
                    },
                    "owner": {
                        "person_index": int(scene["owner_index"]),
                        "character_instance_id": (
                            f"lv_mhp_v1-{scene['image_id']}-p{scene['owner_index']}"
                        ),
                        "person_mask_sha256": hashlib.sha256(scene["owner"].tobytes()).hexdigest(),
                    },
                    "target": {
                        "label_id": spec["label"],
                        "expected_presence": "visible_nonempty",
                        "minimum_area_pixels": 1,
                        "maximum_area_pixels": width * height,
                        "allowed_roi_xyxy": [0, 0, width, height],
                        "inclusion_rule": "visible_pixels_only",
                        "exclusion_rule": "exclude_occluded_outside_owner_and_named_labels",
                    },
                    "candidate": {
                        "mask_sha256": candidate_sha256,
                        "width": width,
                        "height": height,
                        "binary_values": [0, 255],
                    },
                    "excluded_labels": ["other_person"],
                    "protected_regions": [
                        {
                            "region_id": f"protected-face-{case_id}",
                            "label_id": "face_external_reference",
                            "owner_person_index": int(scene["owner_index"]),
                            "mask_sha256": hashlib.sha256(scene["protected"].tobytes()).hexdigest(),
                        }
                    ],
                    "transforms": {
                        "source_to_candidate": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                        "candidate_to_source": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                    },
                    "contract_sha256": "",
                }
                contract["contract_sha256"] = target_contract_sha256(contract)
                rendered = render_target_panels(
                    source_rgb=scene["source"],
                    candidate_mask=candidate,
                    disagreement_mask=np.logical_xor(scene["target"], candidate),
                    target_contract=contract,
                    source_file_sha256=source_panel_sha256,
                    candidate_file_sha256=candidate_sha256,
                    expected_target_contract_sha256=contract["contract_sha256"],
                    expected_transform_sha256=transform_sha256(contract),
                    crop_xyxy=_focus_crop(scene["target"], candidate),
                )
                panels: dict[str, str] = {}
                panel_files: dict[str, str] = {}
                for name in PANEL_NAMES:
                    relative = Path("panels") / case_id / f"{name}.png"
                    content_bytes = rendered.png_bytes[name]
                    path = stage / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content_bytes)
                    panels[name] = hashlib.sha256(content_bytes).hexdigest()
                    panel_files[name] = relative.as_posix()
                source_binding = {
                    "source_family": "maskedwarehouse",
                    "source_root_id": "maskedwarehouse",
                    "source_relative_path": scene["source_path"].relative_to(warehouse).as_posix(),
                    "source_file_sha256": _sha_file(scene["source_path"]),
                    "source_panel_sha256": source_panel_sha256,
                    "annotation_relative_paths": [
                        path.relative_to(warehouse).as_posix() for path in scene["annotation_paths"]
                    ],
                    "annotation_file_sha256s": [
                        _sha_file(path) for path in scene["annotation_paths"]
                    ],
                    "base_mask_pixel_sha256": hashlib.sha256(scene["target"].tobytes()).hexdigest(),
                    "source_authority": "external_labeled_reference",
                    "real_source_pixels": True,
                    "synthetic": False,
                    "production_draft": False,
                    "qualification_evidence_sha256": qualification_sha256,
                    "source_binding_sha256": "",
                }
                source_binding["source_binding_sha256"] = canonical_sha256(
                    {
                        key: value
                        for key, value in source_binding.items()
                        if key != "source_binding_sha256"
                    }
                )
                case = {
                    "case_id": case_id,
                    "domain": domain,
                    "expected_outcome": expected_outcome,
                    "defect_type": defect,
                    "target_contract": contract,
                    "panels": panels,
                    "panel_files": panel_files,
                    "panel_set_sha256": rendered.manifest["panel_set_sha256"],
                    "source_binding": source_binding,
                    "case_sha256": "",
                }
                case["case_sha256"] = regression_case_sha256(case)
                cases.append(case)
        manifest = {
            "schema_version": "2.0.0",
            "suite_id": "maskfactory_real_visual_regression_v2",
            "frozen_at": "2026-07-22T07:30:00Z",
            "required_domains": list(REQUIRED_DOMAINS),
            "truth_source": "real_image_external_labeled_reference",
            "reference_coverage": {
                "root_id": "reference_library",
                "inventory_relative_path": "manifests/inventory_summary.json",
                "inventory_sha256": _sha_file(reference_inventory),
                "role": "coverage_retrieval_only",
                "truth_authority": "none",
            },
            "source_bindings_sha256": canonical_sha256([case["source_binding"] for case in cases]),
            "cases": cases,
            "suite_sha256": "",
        }
        manifest["suite_sha256"] = regression_suite_sha256(manifest)
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        validate_regression_suite_files(manifest, stage)
        os.replace(stage, output_root)
        return manifest
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--maskedwarehouse-root",
        type=Path,
        default=Path(r"C:\Comfy_UI_Main\MaskedWarehouse"),
    )
    parser.add_argument(
        "--reference-root",
        type=Path,
        default=Path(r"F:\Reference_Images\Ultimate_Masking_Reference_Images"),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    manifest = build(
        args.output,
        maskedwarehouse_root=args.maskedwarehouse_root,
        reference_root=args.reference_root,
        project_root=args.project_root,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "case_count": len(manifest["cases"]),
                "suite_sha256": manifest["suite_sha256"],
                "source_bindings_sha256": manifest["source_bindings_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
