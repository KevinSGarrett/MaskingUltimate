"""Build a hash-bound candidate-batch plan for every missing canonical label."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from maskfactory.vlm.control_candidate_plan import build_visual_control_candidate_plan

ROOT = Path(__file__).resolve().parents[1]


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _load_array(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError(f"JSON root must be an array of objects: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-deficits",
        type=Path,
        default=ROOT / "qa/live_verification/visual_corpus_source_deficits_v2_20260723.json",
    )
    parser.add_argument("--candidate-catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    document = build_visual_control_candidate_plan(
        source_deficit_report=_load_object(args.source_deficits),
        candidate_catalog=_load_array(args.candidate_catalog),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "planned_deficit_labels": document["planned_deficit_label_count"],
                "unfilled_deficit_labels": document["unfilled_deficit_label_count"],
                "self_sha256": document["self_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
