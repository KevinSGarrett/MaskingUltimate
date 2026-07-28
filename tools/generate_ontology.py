"""Generate or check configs/ontology.yaml."""

from __future__ import annotations

import argparse
from pathlib import Path

from maskfactory.ontology_generator import DEFAULT_OUTPUT, generate_ontology, ontology_is_current


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        if ontology_is_current(args.output):
            print(f"ontology current: {args.output}")
            return 0
        print(f"ontology drift: {args.output}")
        return 1
    print(generate_ontology(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
