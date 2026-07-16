from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.reference_library import inspect_reference_database

DEFAULT_DATABASES = (
    Path(r"C:\Temp\MaskFactory_Reference_Library\reference_working.sqlite"),
    Path(
        r"F:\Reference_Images\Ultimate_Masking_Reference_Images"
        r"\manifests\reference_inventory.sqlite"
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report read-only state for the MaskFactory reference library."
    )
    parser.add_argument(
        "--db",
        action="append",
        type=Path,
        dest="databases",
        help="SQLite database to inspect; repeat to inspect more than one.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    databases = tuple(args.databases) if args.databases else DEFAULT_DATABASES
    print(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "databases": [inspect_reference_database(p) for p in databases],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
