"""Evaluate additive bridge failure-control evidence from an observation document."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.bridge.failure_control import (
    FailureControlError,
    build_failure_control_evidence,
    validate_failure_control_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation", required=True, type=Path)
    parser.add_argument("--decided-at", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    observation = json.loads(args.observation.read_text(encoding="utf-8"))
    evidence = build_failure_control_evidence(observation, decided_at=args.decided_at)
    issues = validate_failure_control_evidence(evidence)
    if issues:
        raise FailureControlError("; ".join(issues))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if evidence["status"] == "accepted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
