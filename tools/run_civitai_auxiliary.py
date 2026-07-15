"""Run the governed auxiliary-specialist lane on one person context crop."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.providers.civitai_auxiliary import run_auxiliary_providers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--priors", type=Path, required=True)
    parser.add_argument("--pose", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--registry", type=Path, default=Path("configs/civitai_auxiliary_detectors.yaml")
    )
    parser.add_argument(
        "--runtime", type=Path, default=Path("configs/civitai_auxiliary_runtime.yaml")
    )
    parser.add_argument("--domain", choices=("photo", "illustration"), default="photo")
    args = parser.parse_args()
    result = run_auxiliary_providers(
        image_path=args.image,
        priors_dir=args.priors,
        pose_path=args.pose,
        output_dir=args.output,
        registry_path=args.registry,
        runtime_path=args.runtime,
        domain=args.domain,
    )
    print(
        json.dumps(
            {
                "summary": str(result.summary_path),
                "selected": list(result.selected_keys),
                "successful": list(result.successful_keys),
                "failed": list(result.failed_keys),
                "detections": result.detection_count,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
