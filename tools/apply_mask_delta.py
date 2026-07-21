"""Stage an add/subtract correction graph output into a canonical part map."""

from __future__ import annotations

import argparse
from pathlib import Path

from maskfactory.cvat_bridge.mask_delta import (
    apply_part_mask_delta,
    apply_review_package_mask_delta,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("label_map", type=Path, nargs="?")
    parser.add_argument("target_label")
    parser.add_argument("output", type=Path)
    parser.add_argument("--add", type=Path)
    parser.add_argument("--subtract", type=Path)
    parser.add_argument("--subtract-replacement")
    parser.add_argument("--silhouette", type=Path)
    parser.add_argument("--package", type=Path)
    args = parser.parse_args()
    if args.package:
        output = apply_review_package_mask_delta(
            package_root=args.package,
            target_label=args.target_label,
            add_mask_path=args.add,
            subtract_mask_path=args.subtract,
            subtract_replacement_label=args.subtract_replacement,
            silhouette_path=args.silhouette,
        )
    else:
        if args.label_map is None:
            parser.error("label_map is required unless --package is supplied")
        output = apply_part_mask_delta(
            label_map_path=args.label_map,
            target_label=args.target_label,
            output_path=args.output,
            add_mask_path=args.add,
            subtract_mask_path=args.subtract,
            subtract_replacement_label=args.subtract_replacement,
            silhouette_path=args.silhouette,
        )
    print(output)


if __name__ == "__main__":
    main()
