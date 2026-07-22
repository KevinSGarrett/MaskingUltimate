"""Prove the isolated v2 project accepts 66 state tags plus mask drafts.

The fixture is a synthetic color field, not anatomy evidence.  The disposable
task is deleted and can never count as human review, gold, or pilot coverage.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from maskfactory.cvat_bridge.client import CvatClient
from maskfactory.cvat_bridge.v2_pull import CvatV2Error
from maskfactory.cvat_bridge.v2_push import push_v2_images
from maskfactory.io.hashing import sha256_file
from maskfactory.io.png_strict import write_binary_mask
from maskfactory.ontology_v2 import build_ontology_v2
from maskfactory.ontology_v2_manifest import migrate_v1_manifest_document

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime_cvat_v2_smoke"
IMAGE_ID = "img_c0a7c0a7c0a7"


def _manifest(source_sha: str, mask_sha: str) -> dict:
    part_labels = [label for label in build_ontology_v2()["labels"] if label["map"] == "part"][:56]
    parts = {
        label["name"]: {
            "mask_type": label["mask_type"],
            "visibility": "n/a" if label["name"] == "background" else "not_visible",
            "mask_file": None,
            "mask_sha256": None,
            "mask_area_px": 0,
            "mask_bbox": None,
            "components": 0,
            "status": "n/a",
        }
        for label in part_labels
    }
    parts["left_forearm"].update(
        {
            "visibility": "visible",
            "mask_file": "masks/left_forearm.png",
            "mask_sha256": mask_sha,
            "mask_area_px": 192,
            "mask_bbox": [8, 12, 24, 24],
            "components": 1,
            "status": "draft_model_generated",
        }
    )
    return {
        "schema_version": "1.0.0",
        "image_id": IMAGE_ID,
        "mask_ontology_version": "body_parts_v1",
        "left_right_convention": "character_perspective",
        "workflow_status": "in_review",
        "workflow_updated_at": "2026-07-13T00:00:00Z",
        "source": {
            "source_file": "source.png",
            "source_sha256": source_sha,
            "parent_source_sha256": source_sha,
            "source_width": 64,
            "source_height": 48,
            "source_origin": "generated",
            "origin_note": "synthetic CVAT v2 API mechanics fixture; no anatomy authority",
            "ingested_at": "2026-07-13T00:00:00Z",
            "exif_stripped": True,
        },
        "person": {
            "primary_person_bbox": [0, 0, 64, 48],
            "person_count": 1,
            "view": "front",
            "pose_tags": ["synthetic_smoke"],
            "estimated_person_height_px": 48,
        },
        "interperson": [],
        "parts": parts,
        "inpaint_derivatives": [],
        "tooling": {
            "annotation_tool": "cvat",
            "annotation_tool_version": "2.24.0",
            "pipeline_version": "maskfactory-v2-smoke",
            "model_versions_used": {},
            "config_hashes": {"ontology.yaml": "a" * 64},
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
        "qa": {"qa_report_file": "qa_report.json", "qa_overall": "pending", "qa_score": None},
        "files": {"source.png": source_sha, "masks/left_forearm.png": mask_sha},
    }


def main() -> int:
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    package = RUNTIME / "packages" / IMAGE_ID / "instances" / "p0"
    (package / "masks").mkdir(parents=True)
    source = np.zeros((48, 64, 3), dtype=np.uint8)
    source[:, :32] = (32, 96, 160)
    source[:, 32:] = (192, 96, 32)
    Image.fromarray(source).save(package / "source.png")
    mask = np.zeros((48, 64), dtype=np.uint8)
    mask[12:24, 8:24] = 255
    write_binary_mask(package / "masks" / "left_forearm.png", mask, source_size=(64, 48))
    migrated = migrate_v1_manifest_document(
        _manifest(
            sha256_file(package / "source.png"), sha256_file(package / "masks/left_forearm.png")
        )
    )
    (package / "manifest.json").write_text(
        json.dumps(migrated, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    config = yaml.safe_load((ROOT / "configs" / "cvat_v2.yaml").read_text(encoding="utf-8"))
    config["project"]["task_records_dir"] = str(RUNTIME / "tasks")
    config_path = RUNTIME / "cvat_v2.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    client = CvatClient.from_config(config_path)
    task_ids: tuple[int, ...] = ()
    try:
        task_ids = push_v2_images(
            client,
            (IMAGE_ID,),
            config_path=config_path,
            packages_root=RUNTIME / "packages",
        )
        if len(task_ids) != 1:
            raise CvatV2Error("live CVAT v2 smoke did not create exactly one task")
        annotations = client.request("GET", f"/api/tasks/{task_ids[0]}/annotations")
        result = {
            "schema_version": "1.0.0",
            "outcome": "pass",
            "project_id": 2,
            "task_id": task_ids[0],
            "tag_count": len(annotations.get("tags", [])),
            "shape_count": len(annotations.get("shapes", [])),
            "track_count": len(annotations.get("tracks", [])),
            "all_additions_unreviewed": all(
                migrated["parts"][name]["visibility"] == "unreviewed_for_v2"
                for name in migrated["ontology_migration"]["added_labels"]
            ),
            "synthetic_non_gold_fixture": True,
            "human_review_credit": False,
            "pilot_image_credit": False,
        }
        if result["tag_count"] != 66 or result["shape_count"] != 1 or result["track_count"] != 0:
            raise CvatV2Error(f"live CVAT v2 annotation round trip drifted: {result}")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    finally:
        for task_id in task_ids:
            client.request("DELETE", f"/api/tasks/{task_id}")
        shutil.rmtree(RUNTIME, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
