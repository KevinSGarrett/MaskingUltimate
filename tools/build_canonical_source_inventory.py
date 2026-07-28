#!/usr/bin/env python3
"""Build the MF-P6-20.01 full-product/autonomy path inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from maskfactory.steward.canonical_source_inventory import (  # noqa: E402
    build_inventory,
    write_inventory,
)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--full-product-ref",
        default="codex/fallback-dispatcher-podbase-20260726",
    )
    parser.add_argument("--autonomy-ref", default="HEAD")
    parser.add_argument("--resolution-evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    authorities = {
        "Plan/28_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION_AND_COMFYUI_ADOPTION.md": _file_sha256(
            repo_root / "Plan/28_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION_AND_COMFYUI_ADOPTION.md"
        ),
        "Plan/Items/24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md": _file_sha256(
            repo_root / "Plan/Items/24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md"
        ),
        "Plan/SELF_HOSTED_AUTONOMOUS_LLM_PURSUING_GOAL_MESSAGE.md": _file_sha256(
            repo_root / "Plan/SELF_HOSTED_AUTONOMOUS_LLM_PURSUING_GOAL_MESSAGE.md"
        ),
    }
    resolution_evidence = None
    resolution_path = None
    resolution_raw_sha256 = None
    if args.resolution_evidence is not None:
        resolution_file = args.resolution_evidence.resolve()
        try:
            resolution_path = resolution_file.relative_to(repo_root).as_posix()
        except ValueError as exc:
            raise SystemExit("resolution evidence must be inside the repository") from exc
        raw = resolution_file.read_bytes()
        resolution_raw_sha256 = hashlib.sha256(raw).hexdigest()
        resolution_evidence = json.loads(raw)
    inventory = build_inventory(
        repo_root=repo_root,
        full_product_ref=args.full_product_ref,
        autonomy_ref=args.autonomy_ref,
        authority_hashes=authorities,
        resolution_evidence=resolution_evidence,
        resolution_evidence_path=resolution_path,
        resolution_evidence_raw_sha256=resolution_raw_sha256,
    )
    write_inventory(args.output, inventory)
    print(
        f"{inventory['self_sha256']} "
        f"{inventory['summary']['union_path_count']} "
        f"{args.output.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
