"""CLI: raise installed challenger_bodypart → lifecycle benchmarked (never champion_*)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from maskfactory.models.benchmark import mark_benchmarked_candidate  # noqa: E402
from maskfactory.models.registry import DEFAULT_REGISTRY, ModelRegistryError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_key")
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--models-root", type=Path, default=DEFAULT_REGISTRY.parent)
    args = parser.parse_args()
    try:
        entry = mark_benchmarked_candidate(
            args.candidate_key,
            certificate=args.certificate,
            registry_path=args.registry,
            models_root=args.models_root,
        )
    except (OSError, ValueError, json.JSONDecodeError, ModelRegistryError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "key": entry["key"],
                "role": entry["role"],
                "lifecycle_state": entry["lifecycle_state"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
