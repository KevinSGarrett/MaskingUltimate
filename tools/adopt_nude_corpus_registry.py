#!/usr/bin/env python3
"""Generate the compact project-owned adoption of the supplied adult registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.nude_corpus_intake import build_project_registry_manifest, load_adopted_intake


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--intake",
        type=Path,
        default=Path(r"C:\Comfy_UI_Main\MaskedWarehouse\Nude\_MASKFACTORY_INTAKE"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("configs/nude_corpus_registry.generated.json"),
    )
    args = parser.parse_args()
    manifest = build_project_registry_manifest(load_adopted_intake(args.intake))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "dataset_count": manifest["dataset_count"],
                "record_count": manifest["record_count"],
                "self_sha256": manifest["self_sha256"],
                "output": str(args.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
