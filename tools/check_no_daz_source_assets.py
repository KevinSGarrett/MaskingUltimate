"""Pre-commit entry point for the MaskFactory DAZ source-asset exclusion gate.

Loads ``source_guard`` via file path so the hook does not import the heavy
``maskfactory.daz`` package ``__init__`` (numpy / package_qc), which can fail
under low Windows commit-time pagefile pressure.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET_SOURCE_IN_GIT = 80


def _load_find_prohibited_source_assets():
    path = ROOT / "src" / "maskfactory" / "daz" / "source_guard.py"
    spec = importlib.util.spec_from_file_location("maskfactory_daz_source_guard_hook", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load DAZ source guard from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.find_prohibited_source_assets


def main(argv: list[str] | None = None) -> int:
    find_prohibited_source_assets = _load_find_prohibited_source_assets()
    paths = list(sys.argv[1:] if argv is None else argv)
    violations = find_prohibited_source_assets(paths, workspace=ROOT)
    if violations:
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": ASSET_SOURCE_IN_GIT,
                    "reason": (
                        "DAZ source assets and bulk geometry/textures are " "prohibited in Git"
                    ),
                    "entity_ids": list(violations),
                    "retryable": False,
                },
                sort_keys=True,
            )
        )
        return ASSET_SOURCE_IN_GIT
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
