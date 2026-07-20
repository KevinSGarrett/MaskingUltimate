"""Assemble a frozen image-disjoint autonomous-verification corpus from runs/.

Discovers ``*.corpus_record.json`` envelopes written beside production
``machine_verified_candidate`` / ``calibrated_auto_accepted`` lifecycle sidecars.
Fails closed when envelopes are missing or images are not disjoint — never
fabricates independence/stability claims.

Usage:
  python tools/assemble_autonomous_verification_corpus.py \\
      --machine-root runs \\
      --output qa/autonomy/corpora/autonomous_verification_<ts>.json \\
      [--label torso] [--context solo] [--pipeline-fingerprint <fp>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from maskfactory.autonomy.corpus import (  # noqa: E402
    AutonomousCorpusError,
    assemble_autonomous_verification_corpus,
    scan_lifecycle_pool,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--machine-root", type=Path, default=REPO_ROOT / "runs")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", default=None)
    parser.add_argument("--context", default=None)
    parser.add_argument("--pipeline-fingerprint", default=None)
    parser.add_argument("--minimum-records", type=int, default=1)
    args = parser.parse_args()

    pool = scan_lifecycle_pool(args.machine_root)
    try:
        summary = assemble_autonomous_verification_corpus(
            args.machine_root,
            args.output,
            label=args.label,
            context=args.context,
            pipeline_fingerprint=args.pipeline_fingerprint,
            minimum_records=args.minimum_records,
        )
    except AutonomousCorpusError as exc:
        print(
            json.dumps(
                {"status": "insufficient_or_invalid", "error": str(exc), "pool": pool},
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps({"status": "assembled", **summary, "pool": pool}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
