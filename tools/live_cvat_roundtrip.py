"""Run and record a disposable live CVAT unedited-mask round trip."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image

from maskfactory.cvat_bridge.client import CvatClient
from maskfactory.cvat_bridge.pull import pull_images
from maskfactory.cvat_bridge.push import push_images
from maskfactory.fusion.mapbuild import export_binaries
from maskfactory.io.png_strict import read_mask, write_label_map

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "qa" / "fixtures" / "smoke" / "ultralytics_bus_adults.jpg"
RUNTIME = ROOT / ".runtime_cvat_roundtrip"
EVIDENCE = ROOT / "qa" / "evidence" / "cvat_roundtrip.json"


def main() -> int:
    digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    image_id = f"img_{digest[:12]}"
    package = RUNTIME / "packages" / image_id / "instances" / "p0"
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    package.mkdir(parents=True)
    shutil.copyfile(FIXTURE, package / "source.jpg")
    (package / "overlays").mkdir()
    with Image.open(FIXTURE) as source:
        width, height = source.size
        source.convert("RGB").save(package / "overlays" / "all_parts.png")
    part = np.zeros((height, width), dtype=np.uint16)
    material = np.zeros((height, width), dtype=np.uint8)
    part[height // 3 : height // 2, width // 3 : width // 2] = 18
    material[part == 18] = 1
    write_label_map(package / "label_map_part.png", part, bits=16)
    write_label_map(package / "label_map_material.png", material, bits=8)
    export_binaries(package)
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "parts": {
                    "left_forearm": {
                        "visibility": "visible",
                        "status": "draft_model_generated",
                        "notes": "live roundtrip fixture",
                    }
                },
                "inpaint_derivatives": [],
                "files": {},
            }
        ),
        encoding="utf-8",
    )
    before = read_mask(package / "masks" / "left_forearm.png")
    client = CvatClient.from_config()
    task_ids: tuple[int, ...] = ()
    try:
        task_ids = push_images(
            client,
            (image_id,),
            packages_root=RUNTIME / "packages",
            task_records=RUNTIME / "tasks",
        )
        pulled = pull_images(
            client,
            (image_id,),
            task_records=RUNTIME / "tasks",
        )
        after = read_mask(package / "masks" / "left_forearm.png")
        pixel_identical = bool(np.array_equal(before, after))
        backup = package / "annotations" / "cvat_task_backup.zip"
        evidence = {
            "at": datetime.now(UTC).isoformat(),
            "image_id": image_id,
            "task_ids": list(task_ids),
            "pulled_task_ids": list(pulled),
            "pixel_identical": pixel_identical,
            "foreground_px": int(np.count_nonzero(after)),
            "backup_bytes": backup.stat().st_size,
            "qa_triggered": (package / "qa" / "cvat_pull_format.json").is_file(),
        }
        EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(evidence, sort_keys=True))
        return 0 if pixel_identical and evidence["backup_bytes"] > 0 else 1
    finally:
        for task_id in task_ids:
            client.request("DELETE", f"/api/tasks/{task_id}")


if __name__ == "__main__":
    raise SystemExit(main())
