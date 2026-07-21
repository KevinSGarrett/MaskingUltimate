"""Validate a proposed MaskFactory release-publication record without publishing it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.bridge.release_publication import (
    load_publication_evidence,
    validate_release_publication,
)
from maskfactory.validation import load_canonical_json


def _trusted_keys(path: Path) -> dict[str, dict]:
    document = load_canonical_json(path.read_bytes())
    if not isinstance(document, dict):
        raise ValueError("trusted-key registry must be a JSON object")
    keys = document.get("trusted_keys", document)
    if not isinstance(keys, dict) or not all(isinstance(value, dict) for value in keys.values()):
        raise ValueError("trusted-key registry must map key IDs to records")
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--release-root", required=True, type=Path)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--trusted-keys", required=True, type=Path)
    args = parser.parse_args()
    issues = validate_release_publication(
        load_publication_evidence(args.evidence),
        release_root=args.release_root,
        repository_root=args.repository_root,
        trusted_signing_keys=_trusted_keys(args.trusted_keys),
    )
    if issues:
        print(json.dumps([issue.__dict__ for issue in issues], indent=2))
        return 1
    print("VALID: publication evidence is closed and observed; no release was published.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
