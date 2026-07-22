#!/usr/bin/env python3
"""Build the full adult-corpus exact/perceptual/source-family split groups."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.nude_corpus_dedup import build_full_corpus_groups, write_group_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--intake",
        type=Path,
        default=Path(r"C:\Comfy_UI_Main\MaskedWarehouse\Nude\_MASKFACTORY_INTAKE"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--hamming-threshold", type=int, default=3)
    parser.add_argument("--phash-threshold", type=int, default=6)
    args = parser.parse_args()
    records, summary = build_full_corpus_groups(
        args.intake,
        workers=args.workers,
        hamming_threshold=args.hamming_threshold,
        phash_threshold=args.phash_threshold,
    )
    result = write_group_evidence(records, summary, args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
