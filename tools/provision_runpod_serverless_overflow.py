#!/usr/bin/env python3
"""Create the two zero-idle RunPod Serverless overflow endpoints."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from maskfactory.autonomy.serverless_overflow import OverflowConfig  # noqa: E402
from maskfactory.runpod_serverless_provisioning import (  # noqa: E402
    RunPodRestClient,
    endpoint_spec,
    provision,
    template_spec,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "runpod_serverless_overflow.yaml",
    )
    parser.add_argument("--comfyui-image", required=True)
    parser.add_argument("--maskfactory-image", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    config = OverflowConfig.load(args.config)
    images = {
        "comfyui": args.comfyui_image,
        "maskfactory": args.maskfactory_image,
    }
    if args.apply:
        result = provision(
            RunPodRestClient(os.environ.get("RUNPOD_API_KEY", "")),
            config,
            images,
        )
    else:
        result = {
            "schema_version": "maskfactory.runpod_serverless_overflow_plan.v1",
            "templates": {
                profile: template_spec(profile, image) for profile, image in images.items()
            },
            "endpoints": {
                profile: endpoint_spec(profile, f"<{profile}-template-id>", config)
                for profile in images
            },
        }
    body = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")
    print(body, end="")


if __name__ == "__main__":
    main()
