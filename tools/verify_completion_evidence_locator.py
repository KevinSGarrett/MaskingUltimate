#!/usr/bin/env python3
"""Read-only reconstruction check for a sealed completion-evidence locator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from maskfactory.steward.evidence_locator import (  # noqa: E402
    EvidenceLocatorError,
    validate_evidence_locator,
    verify_repository_evidence,
)

DEFAULT_LOCATOR = "qa/live_verification/mf_p6_21_01_completion_evidence_locator_20260727.json"


def _root_bound_path(repository_root: Path, value: str) -> tuple[Path, str]:
    """Resolve a POSIX repository-relative path without allowing escape."""

    if not isinstance(value, str) or not value or "\\" in value:
        raise EvidenceLocatorError("locator path must be a non-empty POSIX relative path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or str(relative) == ".":
        raise EvidenceLocatorError("locator path escapes the repository root")
    candidate = repository_root.joinpath(*relative.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise EvidenceLocatorError("locator is absent or not a regular file")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(repository_root)
    except ValueError as error:
        raise EvidenceLocatorError("locator resolves outside the repository root") from error
    return candidate, relative.as_posix()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--locator", default=DEFAULT_LOCATOR)
    args = parser.parse_args(argv)
    try:
        root = args.repository_root.resolve()
        if not root.is_dir():
            raise EvidenceLocatorError("repository root is not a directory")
        locator_path, locator_relative_path = _root_bound_path(root, args.locator)
        locator = json.loads(locator_path.read_text(encoding="utf-8"))
        if not isinstance(locator, dict):
            raise EvidenceLocatorError("locator root must be a JSON object")
        validate_evidence_locator(locator)
        verify_repository_evidence(locator, root)
    except (EvidenceLocatorError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(error)}, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "status": "PASS",
                "locator": locator_relative_path,
                "tracker_item": locator["tracker_item"],
                "entry_count": len(locator["entries"]),
                "self_sha256": locator["self_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
