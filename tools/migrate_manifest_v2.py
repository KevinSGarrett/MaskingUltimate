"""Dry-run, apply, or roll back one body_parts_v1 manifest migration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.ontology_v2_manifest import (
    migrate_v1_manifest_file,
    rollback_v2_manifest_file,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    if args.rollback:
        result = rollback_v2_manifest_file(args.manifest, report_path=args.report)
    else:
        result = migrate_v1_manifest_file(
            args.manifest,
            report_path=args.report,
            dry_run=not args.apply,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
