"""Pre-commit entry point for the MaskFactory DAZ source-asset exclusion gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from maskfactory.daz.control import DazErrorCode, result_envelope
from maskfactory.daz.source_guard import find_prohibited_source_assets

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    paths = list(sys.argv[1:] if argv is None else argv)
    violations = find_prohibited_source_assets(paths, workspace=ROOT)
    if violations:
        print(
            json.dumps(
                result_envelope(
                    code=int(DazErrorCode.ASSET_SOURCE_IN_GIT),
                    reason="DAZ source assets and bulk geometry/textures are prohibited in Git",
                    entity_ids=violations,
                    retryable=False,
                ),
                sort_keys=True,
            )
        )
        return int(DazErrorCode.ASSET_SOURCE_IN_GIT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
