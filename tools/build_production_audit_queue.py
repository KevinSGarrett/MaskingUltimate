"""CLI: build weekly audit queue from production runs/**/autonomy/*.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from maskfactory.autonomy.production_audit import build_production_weekly_audit_queue  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lifecycle-root", type=Path, default=REPO_ROOT / "runs")
    parser.add_argument("--period-id", required=True)
    parser.add_argument(
        "--config", type=Path, default=REPO_ROOT / "configs/autonomous_masks.yaml"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    queue = build_production_weekly_audit_queue(
        args.lifecycle_root,
        args.output,
        period_id=args.period_id,
        operations_policy=config["operations"],
    )
    print(json.dumps(queue, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
