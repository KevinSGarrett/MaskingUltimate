"""Materialize exact visual evidence for selected canonical polygon sources."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.vlm.canonical_polygon_panels import materialize_candidate_panels


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    report = materialize_candidate_panels(
        intake_root=args.intake,
        candidate_document=candidates,
        output_root=args.output,
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "records": report["record_count"],
                "panels": report["panel_count"],
                "self_sha256": report["self_sha256"],
                "visual_alignment_qualification_complete": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
