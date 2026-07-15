"""Freeze or verify the pre-v2 body_parts_v1 compatibility authority."""

from __future__ import annotations

import argparse

from maskfactory.ontology_v2_baseline import verify_v1_baseline, write_v1_baseline


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        result = verify_v1_baseline()
        print(f"v1 baseline verified: {result['snapshot_sha256']}")
        return 0
    print(write_v1_baseline())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
