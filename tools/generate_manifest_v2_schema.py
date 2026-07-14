"""Generate or drift-check the inactive body_parts_v2 manifest schema."""

from __future__ import annotations

import argparse

from maskfactory.ontology_v2_manifest import (
    generate_manifest_v2_schema,
    manifest_v2_schema_is_current,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        if manifest_v2_schema_is_current():
            print("manifest-v2 schema current (inactive)")
            return 0
        print("manifest-v2 schema drift")
        return 1
    print(generate_manifest_v2_schema())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
