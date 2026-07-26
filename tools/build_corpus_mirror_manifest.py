#!/usr/bin/env python3
"""Build or verify a byte-exact corpus-mirror migration manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.corpus_mirror_manifest import (
    build_corpus_mirror_manifest,
    verify_corpus_mirror_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--source-root", type=Path, required=True)
    build.add_argument("--destination-root", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--asset-id", required=True)
    build.add_argument("--batch-size", type=int, default=1000)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--destination-root", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "build":
        result = build_corpus_mirror_manifest(
            source_root=args.source_root,
            destination_root=args.destination_root,
            output_dir=args.output_dir,
            asset_id=args.asset_id,
            batch_size=args.batch_size,
        )
        document = {
            "manifest_path": str(result.manifest_path),
            "inventory_path": str(result.inventory_path),
            "entry_count": result.entry_count,
            "total_bytes": result.total_bytes,
            "tree_sha256": result.tree_sha256,
            "manifest_sha256": result.manifest_sha256,
            "inventory_sha256": result.inventory_sha256,
        }
    else:
        document = verify_corpus_mirror_manifest(
            args.manifest,
            args.destination_root,
        )
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0 if not document.get("issues") else 1


if __name__ == "__main__":
    raise SystemExit(main())
