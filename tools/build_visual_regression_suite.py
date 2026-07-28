"""Build the deterministic frozen visual-regression v1 suite."""

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

from maskfactory.vlm.panel_renderer import render_target_panels, transform_sha256
from maskfactory.vlm.regression_suite import (
    REQUIRED_DOMAINS,
    regression_case_sha256,
    regression_suite_sha256,
    validate_regression_suite_files,
)
from maskfactory.vlm.target_contract import target_contract_sha256

DOMAINS = {
    "clothing_skin_boundary": ("torso_skin", "boundary"),
    "feet": ("left_foot", "anatomy"),
    "hair": ("hair", "boundary"),
    "hands": ("left_hand", "anatomy"),
    "multi_person_ownership": ("left_arm", "ownership"),
    "occlusion_contact": ("right_hand", "protected_region"),
    "visible_anatomy": ("face_skin", "anatomy"),
}


def _png(array: np.ndarray, mode: str) -> bytes:
    stream = io.BytesIO()
    Image.fromarray(array, mode=mode).save(stream, format="PNG", optimize=False, compress_level=9)
    return stream.getvalue()


def _scene(index: int, domain: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    image = Image.new("RGB", (128, 128), (18 + index * 3, 28 + index, 44))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 119, 119), outline=(80, 100, 125), width=2)
    draw.ellipse((30, 14, 58, 42), fill=(195, 146, 112))
    draw.rectangle((31, 42, 57, 91), fill=(65, 125, 185))
    draw.rectangle((18, 46, 31, 82), fill=(195, 146, 112))
    draw.rectangle((57, 46, 70, 82), fill=(195, 146, 112))
    draw.rectangle((33, 91, 43, 116), fill=(120, 90, 75))
    draw.rectangle((48, 91, 58, 116), fill=(120, 90, 75))
    draw.ellipse((17, 78, 33, 94), fill=(215, 165, 125))
    draw.ellipse((56, 78, 72, 94), fill=(215, 165, 125))
    draw.polygon(((28, 18), (60, 18), (55, 8), (35, 7)), fill=(45, 28, 24))
    draw.ellipse((84, 22, 108, 46), fill=(155, 110, 90))
    draw.rectangle((86, 46, 105, 98), fill=(130, 82, 150))
    good = np.zeros((128, 128), dtype=np.bool_)
    if domain == "hands":
        good[78:94, 17:33] = True
    elif domain == "feet":
        good[108:120, 30:45] = True
    elif domain == "hair":
        good[7:20, 28:61] = True
    elif domain == "clothing_skin_boundary":
        good[42:65, 31:58] = True
    elif domain == "visible_anatomy":
        good[16:42, 32:57] = True
    elif domain == "occlusion_contact":
        good[70:87, 56:73] = True
    elif domain == "multi_person_ownership":
        good[46:83, 18:31] = True
    neighbor = np.zeros_like(good)
    neighbor[55:92, 82:108] = True
    return np.asarray(image, dtype=np.uint8), good, neighbor


def _candidate(good: np.ndarray, neighbor: np.ndarray, defect: str | None) -> np.ndarray:
    if defect is None:
        return good.copy()
    if defect == "boundary":
        return np.roll(good, 5, axis=1)
    if defect == "ownership":
        return neighbor.copy()
    if defect == "protected_region":
        result = good.copy()
        result[55:73, 72:88] = True
        return result
    result = good.copy()
    ys, xs = np.where(good)
    result[max(0, ys.min() - 4) : ys.max() + 5, max(0, xs.min() - 5) : xs.max() + 6] = True
    return result


def build(root: Path) -> dict:
    root = Path(root)
    if root.exists():
        raise ValueError(f"visual regression suite already exists: {root}")
    stage = root.with_name(f".{root.name}.tmp-{uuid.uuid4().hex}")
    try:
        stage.mkdir(parents=True)
        cases = []
        case_index = 0
        for domain in REQUIRED_DOMAINS:
            label, defect = DOMAINS[domain]
            for outcome in ("valid_mask", "serious_defect"):
                case_index += 1
                case_id = (
                    f"vr_{case_index:03d}_{domain}_{'valid' if outcome == 'valid_mask' else defect}"
                )
                source, good, neighbor = _scene(case_index, domain)
                candidate = _candidate(good, neighbor, None if outcome == "valid_mask" else defect)
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
                        "label_id": label,
                        "expected_presence": "visible_nonempty",
                        "minimum_area_pixels": 1,
                        "maximum_area_pixels": 8192,
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
                    "excluded_labels": ["other_person"],
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
                case_dir = stage / "panels" / case_id
                case_dir.mkdir(parents=True)
                panels, panel_files = {}, {}
                for name, content in rendered.png_bytes.items():
                    relative = Path("panels") / case_id / f"{name}.png"
                    (stage / relative).write_bytes(content)
                    panels[name] = hashlib.sha256(content).hexdigest()
                    panel_files[name] = relative.as_posix()
                case = {
                    "case_id": case_id,
                    "domain": domain,
                    "expected_outcome": outcome,
                    "defect_type": None if outcome == "valid_mask" else defect,
                    "target_contract": contract,
                    "panels": panels,
                    "panel_files": panel_files,
                    "panel_set_sha256": rendered.manifest["panel_set_sha256"],
                    "case_sha256": "",
                }
                case["case_sha256"] = regression_case_sha256(case)
                cases.append(case)
        manifest = {
            "schema_version": "1.0.0",
            "suite_id": "maskfactory_visual_regression_v1",
            "frozen_at": "2026-07-21T00:00:00Z",
            "required_domains": list(REQUIRED_DOMAINS),
            "cases": cases,
            "suite_sha256": "",
        }
        manifest["suite_sha256"] = regression_suite_sha256(manifest)
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        validate_regression_suite_files(manifest, stage)
        os.replace(stage, root)
        return manifest
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = build(args.output)
    print(
        json.dumps(
            {
                "status": "PASS",
                "case_count": len(manifest["cases"]),
                "suite_sha256": manifest["suite_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
