"""Evaluate Mode A immutable package-read evidence from JSON inputs."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any

from maskfactory.bridge.mode_a_package_read import (
    ModeAPackageReadError,
    evaluate_mode_a_package_read,
    validate_mode_a_package_read_evidence,
)


def _decode_bytes(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"encoding", "data"} and value.get("encoding") == "base64":
            return base64.b64decode(value["data"])
        return {key: _decode_bytes(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_bytes(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--decided-at", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    request = json.loads(args.request.read_text(encoding="utf-8"))
    evidence = _decode_bytes(json.loads(args.evidence.read_text(encoding="utf-8")))
    decision = evaluate_mode_a_package_read(request, evidence, decided_at=args.decided_at)
    issues = validate_mode_a_package_read_evidence(decision)
    if issues:
        raise ModeAPackageReadError("; ".join(issues))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if decision["status"] == "accepted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
