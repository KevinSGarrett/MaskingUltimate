"""Build or verify complete finite metrics for a sealed provider matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.providers.provider_matrix_metrics import build_report, verify_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("observations", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    observations = json.loads(args.observations.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.verify:
        report = json.loads(args.output.read_text(encoding="utf-8"))
        verify_report(report, observations, manifest)
    else:
        report = build_report(observations, manifest)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cell_count": report["cell_count"], "sha256": report["sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
