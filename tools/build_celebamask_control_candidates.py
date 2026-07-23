#!/usr/bin/env python3
"""Select exact direct-label CelebAMask-HQ control candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.vlm.celebamask_control_candidates import (
    build_celebamask_control_candidates,
    verify_celebamask_control_candidates,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--remap", type=Path, required=True)
    parser.add_argument("--per-label-partition", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_celebamask_control_candidates(
        root=args.root,
        provenance_path=args.provenance,
        remap_path=args.remap,
        per_label_partition=args.per_label_partition,
    )
    verify_celebamask_control_candidates(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "selected_count": result["selected_count"],
                "selected_by_label": result["selected_by_label"],
                "selected_by_partition": result["selected_by_partition"],
                "authority_claimed": result["authority_claimed"],
                "self_sha256": result["self_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
