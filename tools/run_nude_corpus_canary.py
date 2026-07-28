#!/usr/bin/env python3
"""Run one hash-bound representative shard from every adult-corpus intake lane."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.nude_corpus_intake import run_representative_canary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--intake",
        type=Path,
        default=Path(r"C:\Comfy_UI_Main\MaskedWarehouse\Nude\_MASKFACTORY_INTAKE"),
    )
    parser.add_argument("--platform", choices=("local", "runpod"), default="local")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-source-hashes", action="store_true")
    args = parser.parse_args()
    report = run_representative_canary(
        args.intake,
        platform=args.platform,
        verify_source_hashes=not args.skip_source_hashes,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
