#!/usr/bin/env python3
"""Audit the current active transferred-asset registry on the selected Pod."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.transferred_asset_durability import audit_registry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--allowed-root", type=Path, default=Path("/workspace"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit_registry(args.registry, allowed_root=args.allowed_root)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists():
            raise SystemExit("refusing to overwrite existing audit")
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "RUNTIME_PASS_DURABILITY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
