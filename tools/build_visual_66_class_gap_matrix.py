"""Build the current 66-class source/truth/critic gap matrix."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from maskfactory.steward.visual_66_class_gap_matrix import (
    build_visual_66_class_gap_matrix,
)


def _git_bytes(repo: Path, revision: str, path: str) -> tuple[bytes, str, str]:
    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"{revision}^{{commit}}"],
        check=True,
        capture_output=True,
    ).stdout.decode("ascii").strip()
    blob = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"{commit}:{path}"],
        check=True,
        capture_output=True,
    ).stdout.decode("ascii").strip()
    value = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", blob],
        check=True,
        capture_output=True,
    ).stdout
    return value, commit, blob


def _atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--ontology-revision", required=True)
    parser.add_argument("--ontology-path", required=True)
    parser.add_argument("--readiness", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path, required=True)
    parser.add_argument("--observed-at-utc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ontology, commit, blob = _git_bytes(
        args.repo, args.ontology_revision, args.ontology_path
    )
    receipt = build_visual_66_class_gap_matrix(
        ontology_bytes=ontology,
        ontology_git_commit=commit,
        ontology_git_path=args.ontology_path,
        ontology_git_blob=blob,
        readiness_bytes=args.readiness.read_bytes(),
        crosswalk_bytes=args.crosswalk.read_bytes(),
        observed_at_utc=args.observed_at_utc,
    )
    _atomic_write(args.output, receipt)
    print(
        json.dumps(
            {
                "class_count": receipt["class_count"],
                "output": str(args.output.resolve()),
                "promotion_allowed": False,
                "self_sha256": receipt["self_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
