"""Build the current exact 66-label visual-corpus source deficit evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from maskfactory.vlm.corpus_source_deficits import (
    build_visual_corpus_source_deficits,
    sha256_bytes,
)

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value, sha256_bytes(raw)


def build(output: Path) -> dict[str, Any]:
    ontology = ROOT / "configs" / "ontology_v2.yaml"
    regression_path = ROOT / "qa" / "vlm_eval" / "visual_regression_v2_real" / "manifest.json"
    pilot_path = ROOT / "configs" / "ontology_v2_authority_pilot.generated.json"
    historical_path = (
        ROOT / "qa" / "live_verification" / "historical_caa_641_to_220_reconciliation_20260722.json"
    )
    regression, regression_sha = _load(regression_path)
    pilot, pilot_sha = _load(pilot_path)
    historical, historical_sha = _load(historical_path)
    document = build_visual_corpus_source_deficits(
        regression_manifest=regression,
        authority_pilot=pilot,
        historical_caa_evidence=historical,
        input_file_sha256s={
            "ontology": sha256_bytes(ontology.read_bytes()),
            "regression_manifest": regression_sha,
            "authority_pilot": pilot_sha,
            "historical_caa_evidence": historical_sha,
        },
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=(ROOT / "qa" / "live_verification" / "visual_corpus_source_deficits_20260723.json"),
    )
    args = parser.parse_args()
    document = build(args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "required": document["required_canonical_label_count"],
                "eligible": document["eligible_canonical_label_count"],
                "missing": document["missing_canonical_label_count"],
                "self_sha256": document["self_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
