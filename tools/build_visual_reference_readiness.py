"""Build source-bound, reference-only readiness evidence for MF-P4-11.23."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from maskfactory.steward.visual_reference_readiness import (
    build_visual_reference_readiness,
    validate_visual_reference_readiness,
)


def _atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory-summary", type=Path, required=True)
    parser.add_argument("--inventory-database", type=Path, required=True)
    parser.add_argument("--library-database", type=Path, required=True)
    parser.add_argument("--dataset-registry", type=Path, required=True)
    parser.add_argument("--ontology-crosswalk", type=Path, required=True)
    parser.add_argument(
        "--critic-catalog",
        type=Path,
        default=Path("configs/visual_critic_catalog.yaml"),
    )
    parser.add_argument("--observed-at-utc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = build_visual_reference_readiness(
        inventory_summary=args.inventory_summary,
        inventory_database=args.inventory_database,
        library_database=args.library_database,
        dataset_registry=args.dataset_registry,
        ontology_crosswalk=args.ontology_crosswalk,
        critic_catalog_path=args.critic_catalog,
        observed_at_utc=args.observed_at_utc,
    )
    validate_visual_reference_readiness(receipt)
    _atomic_write(args.output, receipt)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "self_sha256": receipt["self_sha256"],
                "promotion_allowed": False,
                "ready_for_visual_qualification": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
