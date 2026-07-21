"""Generate or drift-check the inactive body_parts_v2 artifacts."""

from __future__ import annotations

import argparse

from maskfactory.ontology_v2 import generate_v2_artifacts, v2_artifacts_are_current


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        if v2_artifacts_are_current():
            print("ontology-v2 artifacts current (inactive)")
            return 0
        print("ontology-v2 artifact drift")
        return 1
    for path in generate_v2_artifacts():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
