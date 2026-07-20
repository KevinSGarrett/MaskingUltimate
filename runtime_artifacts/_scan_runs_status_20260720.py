"""Honest status distribution scan of the production runs/ lifecycle pool."""

from __future__ import annotations

import collections
import json
import pathlib

STATUS_KEYS = ("status", "decision_status")
TARGET = {"machine_verified_candidate", "calibrated_auto_accepted"}


def main() -> int:
    root = pathlib.Path("runs")
    status = collections.Counter()
    artifact = collections.Counter()
    files = 0
    parse_errors = 0
    for path in root.rglob("*.json"):
        if not path.is_file():
            continue
        files += 1
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            parse_errors += 1
            continue
        if not isinstance(doc, dict):
            continue
        for key in STATUS_KEYS:
            if key in doc:
                status[f"{key}={doc[key]}"] += 1
        if "artifact_type" in doc:
            artifact[str(doc["artifact_type"])] += 1

    target_hits = sum(v for k, v in status.items() if any(k == f"status={t}" for t in TARGET))
    print(
        json.dumps(
            {
                "runs_json_files": files,
                "parse_errors": parse_errors,
                "machine_verified_candidate_or_calibrated_auto_accepted": target_hits,
                "top_status": status.most_common(15),
                "top_artifact_type": artifact.most_common(15),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
