"""Publish a fail-closed capability qualification decision from local evidence.

Input evidence is JSON plus a `bytes` map whose values name files relative to
the evidence document.  This keeps paths out of the signed decision while
requiring the producer to resolve every actual byte before publication.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from maskfactory.bridge.capability_snapshot import (
    CapabilityQualificationError,
    build_capability_decision,
    validate_capability_decision,
)


def _load_evidence(path: Path) -> dict[str, Any]:
    evidence = json.loads(path.read_text(encoding="utf-8"))
    root = path.parent
    for key in ("artifact_bytes", "certificate_bytes"):
        values = evidence.get(key, {})
        if not isinstance(values, dict):
            raise CapabilityQualificationError(f"{key} must be an object")
        evidence[key] = {
            name: (root / relative).read_bytes()
            for name, relative in values.items()
            if isinstance(relative, str)
        }
    release = evidence.get("release_publication")
    if isinstance(release, dict) and isinstance(release.get("bytes"), str):
        release["bytes"] = (root / release["bytes"]).read_bytes()
    if isinstance(evidence.get("certificate_authority_bytes"), str):
        evidence["certificate_authority_bytes"] = (
            root / evidence["certificate_authority_bytes"]
        ).read_bytes()
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--decided-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    decision = build_capability_decision(
        snapshot, _load_evidence(args.evidence), decided_at=args.decided_at
    )
    issues = validate_capability_decision(decision)
    if issues:
        raise CapabilityQualificationError("; ".join(issues))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if decision["status"] == "accepted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
