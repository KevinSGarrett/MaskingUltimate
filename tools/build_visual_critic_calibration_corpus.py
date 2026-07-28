"""Build the deterministic frozen v1 visual-critic calibration corpus."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from maskfactory.vlm.calibration_corpus import (
    DEFECT_TYPES,
    calibration_corpus_sha256,
    panel_set_sha256,
    validate_calibration_corpus_files,
)
from maskfactory.vlm.panel_renderer import render_target_panels, transform_sha256
from maskfactory.vlm.target_contract import target_contract_sha256

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
PANEL_NAMES = (
    "source",
    "binary_mask",
    "overlay",
    "contour",
    "full_context",
    "uncertainty_zoom",
)


def _png(array: np.ndarray, mode: str) -> bytes:
    stream = io.BytesIO()
    Image.fromarray(array, mode=mode).save(stream, format="PNG", optimize=False, compress_level=9)
    return stream.getvalue()


def _scene(seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    image = Image.new("RGB", (128, 128), (24 + seed, 32, 48))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 119, 119), outline=(80, 90, 110), width=2)
    draw.ellipse((27, 16, 55, 44), fill=(190, 145, 115))
    draw.rectangle((31, 43, 53, 96), fill=(80, 130, 190))
    draw.rectangle((18, 48, 31, 83), fill=(190, 145, 115))
    draw.rectangle((53, 48, 66, 83), fill=(190, 145, 115))
    draw.ellipse((17, 78, 32, 93), fill=(215, 165, 125))
    draw.ellipse((52, 78, 67, 93), fill=(215, 165, 125))
    draw.ellipse((75, 20, 101, 46), fill=(155, 110, 90))
    draw.rectangle((78, 45, 99, 98), fill=(135, 85, 155))
    draw.ellipse((68, 69, 82, 84), fill=(165, 120, 95))
    source = np.asarray(image, dtype=np.uint8)
    target = np.zeros((128, 128), dtype=np.bool_)
    target[78:94, 17:33] = True
    neighbor = np.zeros((128, 128), dtype=np.bool_)
    neighbor[69:85, 68:83] = True
    return source, target, neighbor


def _defect(good: np.ndarray, neighbor: np.ndarray, defect: str | None) -> np.ndarray:
    candidate = good.copy()
    if defect is None:
        return candidate
    if defect == "boundary":
        candidate = np.roll(candidate, 2, axis=1)
    elif defect == "leakage":
        candidate[65:78, 33:48] = True
    elif defect == "missing_area":
        candidate[86:94] = False
    elif defect == "flood":
        candidate[50:112, 5:72] = True
    elif defect == "wrong_label" or defect == "ownership":
        candidate = neighbor.copy()
    elif defect == "wrong_side":
        candidate = np.fliplr(good)
    elif defect == "anatomy":
        candidate[75:98, 14:38] = True
    elif defect == "protected_region":
        candidate |= neighbor
    elif defect == "transform":
        candidate = np.roll(candidate, 12, axis=0)
    else:
        raise ValueError(f"unsupported defect {defect}")
    return candidate


def _scene_v2(
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return an asymmetric, spatially grounded two-person scene for corpus v2."""

    image = Image.new("RGB", (128, 128), (24 + seed, 32, 48))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 119, 119), outline=(80, 90, 110), width=2)
    draw.ellipse((27, 16, 55, 44), fill=(190, 145, 115))
    draw.rectangle((31, 43, 53, 96), fill=(80, 130, 190))
    draw.rectangle((18, 48, 31, 83), fill=(190, 145, 115))
    draw.rectangle((53, 48, 66, 83), fill=(190, 145, 115))
    draw.ellipse((17, 78, 32, 93), fill=(225, 175, 125))
    draw.ellipse((52, 78, 67, 93), fill=(205, 150, 115))
    draw.ellipse((75, 20, 101, 46), fill=(155, 110, 90))
    draw.rectangle((78, 45, 99, 98), fill=(135, 85, 155))
    draw.ellipse((68, 69, 82, 84), fill=(165, 120, 95))
    draw.text((35, 25), "P0", fill=(255, 255, 255))
    draw.text((80, 26), "P1", fill=(255, 255, 255))

    def mask() -> tuple[Image.Image, ImageDraw.ImageDraw]:
        value = Image.new("L", (128, 128), 0)
        return value, ImageDraw.Draw(value)

    owner_image, owner_draw = mask()
    owner_draw.ellipse((27, 16, 55, 44), fill=255)
    owner_draw.rectangle((31, 43, 53, 96), fill=255)
    owner_draw.rectangle((18, 48, 31, 83), fill=255)
    owner_draw.rectangle((53, 48, 66, 83), fill=255)
    owner_draw.ellipse((17, 78, 32, 93), fill=255)
    owner_draw.ellipse((52, 78, 67, 93), fill=255)

    right_image, right_draw = mask()
    right_draw.ellipse((17, 78, 32, 93), fill=255)
    left_image, left_draw = mask()
    left_draw.ellipse((52, 78, 67, 93), fill=255)
    neighbor_image, neighbor_draw = mask()
    neighbor_draw.ellipse((68, 69, 82, 84), fill=255)
    face_image, face_draw = mask()
    face_draw.ellipse((27, 16, 55, 44), fill=255)
    forearm_image, forearm_draw = mask()
    forearm_draw.rectangle((18, 48, 31, 77), fill=255)

    return tuple(
        (
            np.asarray(value, dtype=np.uint8)
            if index == 0
            else np.asarray(value, dtype=np.uint8).astype(bool)
        )
        for index, value in enumerate(
            (
                image,
                right_image,
                left_image,
                neighbor_image,
                owner_image,
                face_image,
                forearm_image,
            )
        )
    )  # type: ignore[return-value]


def _defect_v2(
    good: np.ndarray,
    opposite_hand: np.ndarray,
    neighbor_hand: np.ndarray,
    owner: np.ndarray,
    protected_face: np.ndarray,
    owner_forearm: np.ndarray,
    defect: str | None,
) -> np.ndarray:
    candidate = good.copy()
    if defect is None:
        return candidate
    if defect == "boundary":
        candidate = np.roll(candidate, 2, axis=1)
        candidate[:, :2] = False
    elif defect == "leakage":
        candidate[82:89, 8:18] = True
    elif defect == "missing_area":
        candidate[86:94] = False
    elif defect == "flood":
        candidate = owner.copy()
    elif defect == "wrong_label":
        candidate = owner_forearm.copy()
    elif defect == "ownership":
        candidate = neighbor_hand.copy()
    elif defect == "wrong_side":
        candidate = opposite_hand.copy()
    elif defect == "anatomy":
        candidate[72:100, 12:40] = True
    elif defect == "protected_region":
        candidate |= protected_face
    elif defect == "transform":
        shifted = np.zeros_like(candidate)
        shifted[10:, 6:] = candidate[:-10, :-6]
        candidate = shifted
    else:
        raise ValueError(f"unsupported defect {defect}")
    return candidate


def build_v2(root: Path) -> dict:
    """Build corrected, target-grounded v2 without mutating frozen v1 bytes."""

    root = Path(root)
    if root.exists():
        raise ValueError(f"calibration corpus already exists: {root}")
    stage = root.with_name(f".{root.name}.tmp-{uuid.uuid4().hex}")
    try:
        stage.mkdir(parents=True)
        defects = sorted(DEFECT_TYPES)
        specs = [("calibration", None, ["contact", "occlusion"])]
        specs += [("calibration", defect, CONTEXT_BY_DEFECT[defect]) for defect in defects[:5]]
        specs += [("qualification_holdout", None, ["hair", "crop"])]
        specs += [
            ("qualification_holdout", defect, CONTEXT_BY_DEFECT[defect]) for defect in defects[5:]
        ]
        cases = []
        for index, (partition, defect, context_tags) in enumerate(specs, start=1):
            case_id = f"vc2_{index:03d}_{'valid' if defect is None else defect}"
            case_dir = stage / "panels" / case_id
            case_dir.mkdir(parents=True)
            (
                source,
                good,
                opposite_hand,
                neighbor_hand,
                owner,
                protected_face,
                owner_forearm,
            ) = _scene_v2(index)
            candidate = _defect_v2(
                good,
                opposite_hand,
                neighbor_hand,
                owner,
                protected_face,
                owner_forearm,
                defect,
            )
            source_bytes = _png(source, "RGB")
            candidate_bytes = _png(candidate.astype(np.uint8) * 255, "L")
            source_sha = hashlib.sha256(source_bytes).hexdigest()
            candidate_sha = hashlib.sha256(candidate_bytes).hexdigest()
            contract = {
                "schema_version": "1.0.0",
                "contract_id": f"target-{case_id}",
                "source": {
                    "image_id": f"image-{case_id}",
                    "sha256": source_sha,
                    "width": 128,
                    "height": 128,
                },
                "owner": {
                    "person_index": 0,
                    "character_instance_id": f"character-{case_id}",
                    "person_mask_sha256": hashlib.sha256(owner.tobytes()).hexdigest(),
                },
                "target": {
                    "label_id": "right_hand",
                    "expected_presence": "visible_nonempty",
                    "minimum_area_pixels": 1,
                    "maximum_area_pixels": 4096,
                    "allowed_roi_xyxy": [0, 0, 128, 128],
                    "inclusion_rule": "visible_pixels_only",
                    "exclusion_rule": "exclude_occluded_outside_owner_and_named_labels",
                },
                "candidate": {
                    "mask_sha256": candidate_sha,
                    "width": 128,
                    "height": 128,
                    "binary_values": [0, 255],
                },
                "excluded_labels": ["left_hand"],
                "protected_regions": [
                    {
                        "region_id": f"protected-face-{case_id}",
                        "label_id": "face",
                        "owner_person_index": 0,
                        "mask_sha256": hashlib.sha256(protected_face.tobytes()).hexdigest(),
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
                disagreement_mask=np.logical_xor(good, candidate),
                target_contract=contract,
                source_file_sha256=source_sha,
                candidate_file_sha256=candidate_sha,
                expected_target_contract_sha256=contract["contract_sha256"],
                expected_transform_sha256=transform_sha256(contract),
                crop_xyxy=(0, 0, 128, 128),
            )
            assert rendered.png_bytes["source"] == source_bytes
            assert rendered.png_bytes["binary_mask"] == candidate_bytes
            panel_hashes = {}
            panel_files = {}
            for name in PANEL_NAMES:
                relative = Path("panels") / case_id / f"{name}.png"
                content = rendered.png_bytes[name]
                (stage / relative).write_bytes(content)
                panel_files[name] = relative.as_posix()
                panel_hashes[name] = hashlib.sha256(content).hexdigest()
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
        manifest = {
            "schema_version": "1.0.0",
            "corpus_id": "maskfactory_visual_critic_calibration_v2",
            "frozen_at": "2026-07-22T00:00:00Z",
            "partitions": ["calibration", "qualification_holdout"],
            "defect_taxonomy": defects,
            "cases": cases,
            "corpus_sha256": "",
        }
        manifest["corpus_sha256"] = calibration_corpus_sha256(manifest)
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        validate_calibration_corpus_files(manifest, stage)
        os.replace(stage, root)
        return manifest
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def build(root: Path) -> dict:
    root = Path(root)
    if root.exists():
        raise ValueError(f"calibration corpus already exists: {root}")
    stage = root.with_name(f".{root.name}.tmp-{uuid.uuid4().hex}")
    try:
        stage.mkdir(parents=True)
        defects = sorted(DEFECT_TYPES)
        specs = [("calibration", None, ["contact", "occlusion"])]
        specs += [("calibration", defect, CONTEXT_BY_DEFECT[defect]) for defect in defects[:5]]
        specs += [("qualification_holdout", None, ["hair", "crop"])]
        specs += [
            ("qualification_holdout", defect, CONTEXT_BY_DEFECT[defect]) for defect in defects[5:]
        ]
        cases = []
        for index, (partition, defect, context_tags) in enumerate(specs, start=1):
            case_id = f"vc_{index:03d}_{'valid' if defect is None else defect}"
            case_dir = stage / "panels" / case_id
            case_dir.mkdir(parents=True)
            source, good, neighbor = _scene(index)
            candidate = _defect(good, neighbor, defect)
            source_bytes = _png(source, "RGB")
            candidate_bytes = _png(candidate.astype(np.uint8) * 255, "L")
            source_sha = hashlib.sha256(source_bytes).hexdigest()
            candidate_sha = hashlib.sha256(candidate_bytes).hexdigest()
            contract = {
                "schema_version": "1.0.0",
                "contract_id": f"target-{case_id}",
                "source": {
                    "image_id": f"image-{case_id}",
                    "sha256": source_sha,
                    "width": 128,
                    "height": 128,
                },
                "owner": {
                    "person_index": 0,
                    "character_instance_id": f"character-{case_id}",
                    "person_mask_sha256": hashlib.sha256(good.tobytes()).hexdigest(),
                },
                "target": {
                    "label_id": "left_hand",
                    "expected_presence": "visible_nonempty",
                    "minimum_area_pixels": 1,
                    "maximum_area_pixels": 4096,
                    "allowed_roi_xyxy": [0, 0, 128, 128],
                    "inclusion_rule": "visible_pixels_only",
                    "exclusion_rule": "exclude_occluded_outside_owner_and_named_labels",
                },
                "candidate": {
                    "mask_sha256": candidate_sha,
                    "width": 128,
                    "height": 128,
                    "binary_values": [0, 255],
                },
                "excluded_labels": ["right_hand"],
                "protected_regions": [],
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
                disagreement_mask=np.logical_xor(good, candidate),
                target_contract=contract,
                source_file_sha256=source_sha,
                candidate_file_sha256=candidate_sha,
                expected_target_contract_sha256=contract["contract_sha256"],
                expected_transform_sha256=transform_sha256(contract),
                crop_xyxy=(0, 0, 128, 128),
            )
            assert rendered.png_bytes["source"] == source_bytes
            assert rendered.png_bytes["binary_mask"] == candidate_bytes
            panel_hashes = {}
            panel_files = {}
            for name in PANEL_NAMES:
                relative = Path("panels") / case_id / f"{name}.png"
                content = rendered.png_bytes[name]
                (stage / relative).write_bytes(content)
                panel_files[name] = relative.as_posix()
                panel_hashes[name] = hashlib.sha256(content).hexdigest()
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
        manifest = {
            "schema_version": "1.0.0",
            "corpus_id": "maskfactory_visual_critic_calibration_v1",
            "frozen_at": "2026-07-21T00:00:00Z",
            "partitions": ["calibration", "qualification_holdout"],
            "defect_taxonomy": defects,
            "cases": cases,
            "corpus_sha256": "",
        }
        manifest["corpus_sha256"] = calibration_corpus_sha256(manifest)
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        validate_calibration_corpus_files(manifest, stage)
        os.replace(stage, root)
        return manifest
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", choices=("v1", "v2"), default="v1")
    args = parser.parse_args()
    manifest = build(args.output) if args.version == "v1" else build_v2(args.output)
    print(
        json.dumps(
            {
                "status": "PASS",
                "case_count": len(manifest["cases"]),
                "corpus_sha256": manifest["corpus_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
