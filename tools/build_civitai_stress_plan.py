"""Build the deterministic Civitai pose/control stress plan."""

from __future__ import annotations

import argparse
from pathlib import Path

from maskfactory.datasets.civitai_stress import build_civitai_stress_plan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--registry", type=Path, default=Path("configs/civitai_pose_stress_fixtures.yaml")
    )
    parser.add_argument("--skip-archive-hash", action="store_true")
    args = parser.parse_args()
    print(
        build_civitai_stress_plan(
            output_path=args.output,
            registry_path=args.registry,
            verify_archives=not args.skip_archive_hash,
        )
    )


if __name__ == "__main__":
    main()
