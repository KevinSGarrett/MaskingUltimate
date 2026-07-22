#!/usr/bin/env python3
"""Build a real-image semantic critic corpus from governed MaskedWarehouse labels."""

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
from PIL import Image, ImageFilter

from maskfactory.vlm.calibration_corpus import (
    DEFECT_TYPES,
    calibration_corpus_sha256,
    panel_set_sha256,
    validate_calibration_corpus_files,
)
from maskfactory.vlm.critic_catalog import canonical_sha256
from maskfactory.vlm.panel_renderer import render_target_panels, transform_sha256
from maskfactory.vlm.real_corpus_policy import (
    bindings_sha256,
    load_real_corpus_policy,
    validate_real_source_bindings,
)
from maskfactory.vlm.target_contract import target_contract_sha256

PANEL_NAMES = (
    "source",
    "binary_mask",
    "overlay",
    "contour",
    "full_context",
    "uncertainty_zoom",
)
CONTEXT_BY_DEFECT = {
    "anatomy": ["hand"],
    "boundary": ["hair"],
    "flood": ["crop"],
    "leakage": ["multi_person"],
    "missing_area": ["small_part"],
    "ownership": ["multi_person"],
    "protected_region": ["contact"],
    "transform": ["occlusion"],
    "wrong_label": ["hand"],
    "wrong_side": ["hand"],
}
LV_MHP_LABELS = {"hair": 2, "face": 11, "left_arm": 14, "right_arm": 15}


def _png(array: np.ndarray, mode: str) -> bytes:
    stream = io.BytesIO()
    Image.fromarray(array, mode=mode).save(stream, format="PNG", optimize=False, compress_level=9)
    return stream.getvalue()


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _project_evidence_sha256(project_root: Path) -> str:
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
            "scope": "semantic_visual_critic_calibration",
            "authority": "external_labeled_reference",
            "evidence": bindings,
        }
    )


def _annotation_groups(content_root: Path) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = defaultdict(list)
    for path in sorted((content_root / "annotations").glob("*.png"), key=lambda value: value.name):
        groups[path.stem.split("_", 1)[0]].append(path)
    return groups


def _eligible_scenes(
    content_root: Path, required: int, *, allowed_image_ids: set[str]
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for image_id, annotation_paths in _annotation_groups(content_root).items():
        if image_id not in allowed_image_ids:
            continue
        if len(annotation_paths) < 2:
            continue
        source_path = content_root / "images" / f"{image_id}.jpg"
        if not source_path.is_file():
            continue
        maps = []
        for annotation in annotation_paths:
            with Image.open(annotation) as opened:
                maps.append(np.asarray(opened.convert("L"), dtype=np.uint8))
        if any(value.shape != maps[0].shape for value in maps):
            continue
        for owner_index, owner_map in enumerate(maps):
            target = owner_map == LV_MHP_LABELS["right_arm"]
            opposite = owner_map == LV_MHP_LABELS["left_arm"]
            face = owner_map == LV_MHP_LABELS["face"]
            if min(int(target.sum()), int(opposite.sum()), int(face.sum())) < 64:
                continue
            neighbor_index = next(
                (
                    index
                    for index, value in enumerate(maps)
                    if index != owner_index
                    and int((value == LV_MHP_LABELS["right_arm"]).sum()) >= 64
                ),
                None,
            )
            if neighbor_index is None:
                continue
            with Image.open(source_path) as opened:
                source = np.asarray(opened.convert("RGB"), dtype=np.uint8)
            if source.shape[:2] != owner_map.shape:
                continue
            selected.append(
                {
                    "image_id": image_id,
                    "source_path": source_path,
                    "annotation_paths": annotation_paths,
                    "source": source,
                    "target": target,
                    "opposite": opposite,
                    "face": face,
                    "owner": owner_map > 0,
                    "neighbor": maps[neighbor_index] == LV_MHP_LABELS["right_arm"],
                    "owner_index": owner_index,
                }
            )
            break
        if len(selected) == required:
            return selected
    raise ValueError(f"LV-MHP lacks {required} distinct eligible real multi-person scenes")


def _split_ids(content_root: Path, filename: str) -> set[str]:
    path = content_root / filename
    if not path.is_file():
        raise ValueError(f"LV-MHP upstream split list is missing: {filename}")
    values = {Path(line.strip()).stem for line in path.read_text(encoding="utf-8").splitlines()}
    values.discard("")
    if not values:
        raise ValueError(f"LV-MHP upstream split list is empty: {filename}")
    return values


def _translate(mask: np.ndarray, *, x: int, y: int) -> np.ndarray:
    shifted = np.zeros_like(mask)
    source_y0, source_y1 = max(0, -y), mask.shape[0] - max(0, y)
    source_x0, source_x1 = max(0, -x), mask.shape[1] - max(0, x)
    dest_y0, dest_y1 = max(0, y), mask.shape[0] - max(0, -y)
    dest_x0, dest_x1 = max(0, x), mask.shape[1] - max(0, -x)
    shifted[dest_y0:dest_y1, dest_x0:dest_x1] = mask[source_y0:source_y1, source_x0:source_x1]
    return shifted


def _candidate(scene: dict[str, Any], defect: str | None) -> np.ndarray:
    target = scene["target"].copy()
    if defect is None:
        return target
    if defect == "boundary":
        return _translate(target, x=3, y=0)
    if defect == "leakage":
        return target | scene["neighbor"]
    if defect == "flood":
        return scene["owner"].copy()
    if defect == "wrong_label":
        return scene["face"].copy()
    if defect == "wrong_side":
        return scene["opposite"].copy()
    if defect == "ownership":
        return scene["neighbor"].copy()
    if defect == "protected_region":
        return target | scene["face"]
    if defect == "transform":
        return _translate(target, x=12, y=10)
    if defect == "anatomy":
        expanded = Image.fromarray(target.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(9))
        return np.asarray(expanded, dtype=np.uint8) > 0
    if defect == "missing_area":
        rows = np.flatnonzero(target.any(axis=1))
        if len(rows) < 2:
            raise ValueError("target is too small for deterministic missing-area defect")
        target[rows[len(rows) // 2] :] = False
        return target
    raise ValueError(f"unsupported defect: {defect}")


def _focus_crop_xyxy(target: np.ndarray, candidate: np.ndarray) -> tuple[int, int, int, int]:
    """Return a deterministic padded source crop that keeps the target evidence legible."""

    if target.shape != candidate.shape or target.ndim != 2:
        raise ValueError("focus-crop masks must share two-dimensional geometry")
    focus = np.logical_or(target, candidate)
    rows, columns = np.nonzero(focus)
    height, width = focus.shape
    if not len(rows):
        return (0, 0, width, height)
    x0, x1 = int(columns.min()), int(columns.max()) + 1
    y0, y1 = int(rows.min()), int(rows.max()) + 1
    extent = max(x1 - x0, y1 - y0)
    padding = max(16, int(round(extent * 0.25)))
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
    policy_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Materialize a frozen real-image corpus and its exact source bindings."""

    output_root = Path(output_root)
    if output_root.exists():
        raise ValueError(f"calibration corpus already exists: {output_root}")
    warehouse = Path(maskedwarehouse_root).resolve(strict=True)
    content = warehouse / "Body" / "LV-MHP-v1" / "LV-MHP-v1"
    if not (content / "images").is_dir() or not (content / "annotations").is_dir():
        raise ValueError("LV-MHP content root is missing")
    reference = Path(reference_root).resolve(strict=True)
    reference_inventory = reference / "manifests" / "inventory_summary.json"
    if not reference_inventory.is_file():
        raise ValueError("reference-library inventory summary is missing")
    qualification_sha = _project_evidence_sha256(Path(project_root).resolve(strict=True))

    defects = sorted(DEFECT_TYPES)
    specs = [("calibration", None, ["contact", "occlusion"])]
    specs += [("calibration", defect, CONTEXT_BY_DEFECT[defect]) for defect in defects[:5]]
    specs += [("qualification_holdout", None, ["hair", "crop"])]
    specs += [
        ("qualification_holdout", defect, CONTEXT_BY_DEFECT[defect]) for defect in defects[5:]
    ]
    train_ids = _split_ids(content, "train_list.txt")
    test_ids = _split_ids(content, "test_list.txt")
    if train_ids & test_ids:
        raise ValueError("LV-MHP upstream train/test split overlaps")
    calibration_count = sum(partition == "calibration" for partition, _, _ in specs)
    scenes = _eligible_scenes(
        content, calibration_count, allowed_image_ids=train_ids
    ) + _eligible_scenes(content, len(specs) - calibration_count, allowed_image_ids=test_ids)
    stage = output_root.with_name(f".{output_root.name}.tmp-{uuid.uuid4().hex}")
    try:
        stage.mkdir(parents=True)
        cases: list[dict[str, Any]] = []
        source_bindings: list[dict[str, Any]] = []
        for index, ((partition, defect, context_tags), scene) in enumerate(
            zip(specs, scenes), start=1
        ):
            case_id = f"vcr_{index:03d}_{'valid' if defect is None else defect}"
            candidate = _candidate(scene, defect)
            source = scene["source"]
            source_bytes = _png(source, "RGB")
            candidate_bytes = _png(candidate.astype(np.uint8) * 255, "L")
            source_panel_sha = hashlib.sha256(source_bytes).hexdigest()
            candidate_sha = hashlib.sha256(candidate_bytes).hexdigest()
            height, width = candidate.shape
            contract = {
                "schema_version": "1.0.0",
                "contract_id": f"target-{case_id}",
                "source": {
                    "image_id": f"lv_mhp_v1-{scene['image_id']}",
                    "sha256": source_panel_sha,
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
                    "label_id": "right_arm_external_reference",
                    "expected_presence": "visible_nonempty",
                    "minimum_area_pixels": 1,
                    "maximum_area_pixels": width * height,
                    "allowed_roi_xyxy": [0, 0, width, height],
                    "inclusion_rule": "visible_pixels_only",
                    "exclusion_rule": "exclude_occluded_outside_owner_and_named_labels",
                },
                "candidate": {
                    "mask_sha256": candidate_sha,
                    "width": width,
                    "height": height,
                    "binary_values": [0, 255],
                },
                "excluded_labels": ["left_arm_external_reference"],
                "protected_regions": [
                    {
                        "region_id": f"protected-face-{case_id}",
                        "label_id": "face",
                        "owner_person_index": int(scene["owner_index"]),
                        "mask_sha256": hashlib.sha256(scene["face"].tobytes()).hexdigest(),
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
                source_rgb=source,
                candidate_mask=candidate,
                disagreement_mask=np.logical_xor(scene["target"], candidate),
                target_contract=contract,
                source_file_sha256=source_panel_sha,
                candidate_file_sha256=candidate_sha,
                expected_target_contract_sha256=contract["contract_sha256"],
                expected_transform_sha256=transform_sha256(contract),
                crop_xyxy=_focus_crop_xyxy(scene["target"], candidate),
            )
            panel_hashes, panel_files = {}, {}
            for name in PANEL_NAMES:
                relative = Path("panels") / case_id / f"{name}.png"
                content_bytes = rendered.png_bytes[name]
                path = stage / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content_bytes)
                panel_files[name] = relative.as_posix()
                panel_hashes[name] = hashlib.sha256(content_bytes).hexdigest()
            case = {
                "case_id": case_id,
                "partition": partition,
                "expected_outcome": "valid_mask" if defect is None else "known_defect",
                "defect_type": defect,
                "target_contract": contract,
                "panels": panel_hashes,
                "panel_files": panel_files,
                "context_tags": context_tags,
                "panel_set_sha256": "",
            }
            case["panel_set_sha256"] = panel_set_sha256(case)
            cases.append(case)

            source_relative = scene["source_path"].relative_to(warehouse).as_posix()
            annotation_relative = [
                path.relative_to(warehouse).as_posix() for path in scene["annotation_paths"]
            ]
            source_bindings.append(
                {
                    "case_id": case_id,
                    "source_family": "maskedwarehouse",
                    "source_root_id": "maskedwarehouse",
                    "source_relative_path": source_relative,
                    "source_file_sha256": _sha_file(scene["source_path"]),
                    "source_panel_sha256": source_panel_sha,
                    "annotation_relative_paths": annotation_relative,
                    "annotation_file_sha256s": [
                        _sha_file(path) for path in scene["annotation_paths"]
                    ],
                    "base_mask_pixel_sha256": hashlib.sha256(scene["target"].tobytes()).hexdigest(),
                    "source_authority": "external_labeled_reference",
                    "qualification_scope": "semantic_visual_critic_calibration",
                    "upstream_split": "train" if partition == "calibration" else "test",
                    "real_source_pixels": True,
                    "synthetic": False,
                    "production_draft": False,
                    "qualification_evidence_sha256": qualification_sha,
                }
            )
        manifest = {
            "schema_version": "1.0.0",
            "corpus_id": "maskfactory_real_visual_critic_calibration_v2",
            "frozen_at": "2026-07-22T07:00:00Z",
            "partitions": ["calibration", "qualification_holdout"],
            "defect_taxonomy": defects,
            "cases": cases,
            "corpus_sha256": "",
        }
        manifest["corpus_sha256"] = calibration_corpus_sha256(manifest)
        bindings = {
            "schema_version": "1.0.0",
            "artifact_type": "visual_critic_real_source_bindings",
            "corpus_id": manifest["corpus_id"],
            "corpus_sha256": manifest["corpus_sha256"],
            "reference_library": {
                "root_id": "reference_library",
                "inventory_relative_path": "manifests/inventory_summary.json",
                "inventory_sha256": _sha_file(reference_inventory),
                "role": "real_reference_retrieval_benchmark",
                "truth_authority": "none",
            },
            "cases": source_bindings,
            "bindings_sha256": "",
        }
        bindings["bindings_sha256"] = bindings_sha256(bindings)
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (stage / "source_bindings.json").write_text(
            json.dumps(bindings, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        validate_calibration_corpus_files(manifest, stage)
        validate_real_source_bindings(
            corpus=manifest,
            corpus_root=stage,
            bindings=bindings,
            policy=load_real_corpus_policy(policy_path),
            root_overrides={
                "maskedwarehouse": warehouse,
                "reference_library": reference,
            },
        )
        os.replace(stage, output_root)
        return manifest, bindings
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
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("configs/visual_critic_real_corpus.yaml"),
    )
    args = parser.parse_args()
    manifest, bindings = build(
        args.output,
        maskedwarehouse_root=args.maskedwarehouse_root,
        reference_root=args.reference_root,
        project_root=args.project_root,
        policy_path=args.policy,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "case_count": len(manifest["cases"]),
                "corpus_sha256": manifest["corpus_sha256"],
                "source_bindings_sha256": bindings["bindings_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
