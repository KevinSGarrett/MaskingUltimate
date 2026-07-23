#!/usr/bin/env python3
"""Materialize and verify exact CelebAMask-HQ control evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.vlm.celebamask_control_panels import (
    materialize_celebamask_control_panels,
    verify_celebamask_control_panel_report,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    report = materialize_celebamask_control_panels(
        source_root=args.source_root,
        candidate_document=candidates,
        output_root=args.output_root,
    )
    verify_celebamask_control_panel_report(report, args.output_root)
    print(
        json.dumps(
            {
                "output": str(args.output_root),
                "record_count": report["record_count"],
                "panel_count": report["panel_count"],
                "authority_claimed": report["authority_claimed"],
                "self_sha256": report["self_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
