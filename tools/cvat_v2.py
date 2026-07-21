"""Operate the isolated body_parts_v2 CVAT pilot bridge."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.cvat_bridge.client import CvatClient
from maskfactory.cvat_bridge.v2_common import DEFAULT_V2_CONFIG
from maskfactory.cvat_bridge.v2_project import init_v2_project
from maskfactory.cvat_bridge.v2_pull import pull_v2_images
from maskfactory.cvat_bridge.v2_push import push_v2_images


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--config", type=Path, default=DEFAULT_V2_CONFIG)
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="create or validate the separate v2 project")
    push = commands.add_parser("push", help="push migrated v2 package tasks")
    push.add_argument("image_ids", nargs="+")
    pull = commands.add_parser("pull", help="pull only fully reviewed v2 tasks")
    pull.add_argument("image_ids", nargs="+")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    client = CvatClient.from_config(args.config)
    if args.command == "init":
        result = init_v2_project(client, config_path=args.config)
    elif args.command == "push":
        result = {
            "task_ids": list(push_v2_images(client, tuple(args.image_ids), config_path=args.config))
        }
    else:
        result = {
            "task_ids": list(pull_v2_images(client, tuple(args.image_ids), config_path=args.config))
        }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
