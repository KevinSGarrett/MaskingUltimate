"""Seal or verify an immutable top-level provider benchmark matrix manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.providers.provider_matrix import seal_manifest, validate_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    document = json.loads(args.input.read_text(encoding="utf-8"))
    if args.verify:
        validate_manifest(document)
        sealed = document
    else:
        if args.output is None:
            parser.error("--output is required when sealing")
        sealed = seal_manifest(document)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(sealed, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"matrix_id": sealed["matrix_id"], "sha256": sealed["sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
