#!/usr/bin/env python3
"""Materialize full-taxonomy calibration-only seeded defects from admitted masks."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from maskfactory.vlm.critic_catalog import canonical_sha256  # noqa: E402
from maskfactory.vlm.seeded_defect_controls import build_seeded_defect_controls  # noqa: E402

INPUT_KEYS = frozenset({"record", "positive_mask_path", "resources"})


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _safe_path(root: Path, relative: Any) -> Path:
    if (
        not isinstance(relative, str)
        or not relative
        or Path(relative).is_absolute()
        or ".." in Path(relative).parts
    ):
        raise ValueError("seeded-defect input path is unsafe")
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("seeded-defect input path escapes input root") from exc
    if not path.is_file():
        raise ValueError(f"seeded-defect input mask is missing: {relative}")
    return path


def _load_mask(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("L"))


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize(
    *, input_value: dict[str, Any], input_root: Path, output_dir: Path
) -> dict[str, Any]:
    """Write exact PNG negatives and a file-hash-bound manifest."""

    if set(input_value) != INPUT_KEYS or not isinstance(input_value["resources"], dict):
        raise ValueError("seeded-defect input fields are incomplete or unknown")
    root = input_root.resolve()
    positive_path = _safe_path(root, input_value["positive_mask_path"])
    resources = {
        key: _load_mask(_safe_path(root, relative))
        for key, relative in input_value["resources"].items()
    }
    result = build_seeded_defect_controls(
        record=input_value["record"],
        positive_mask=_load_mask(positive_path),
        resources=resources,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for row in result["negatives"]:
        filename = f"{row['operator_id']}.png"
        path = output_dir / filename
        Image.fromarray((row["mask"].astype(np.uint8) * 255), mode="L").save(path)
        files.append(
            {
                "operator_id": row["operator_id"],
                "path": filename,
                "file_sha256": _file_sha256(path),
                "mask_sha256": row["mask_sha256"],
            }
        )
    manifest = dict(result["manifest"])
    manifest["files"] = files
    manifest["materialization_sha256"] = canonical_sha256(manifest)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    args = _args()
    value = json.loads(args.input.read_text(encoding="utf-8"))
    manifest = materialize(
        input_value=value, input_root=args.input_root, output_dir=args.output_dir
    )
    print(
        json.dumps({"record_id": manifest["record_id"], "negative_count": len(manifest["files"])})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
