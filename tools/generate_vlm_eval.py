"""Build production VLM calibration panels from explicit known mask pairs."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maskfactory.vlm.eval import build_calibration_from_seed_manifest  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-manifest", type=Path, required=True)
    args = parser.parse_args()
    cases = build_calibration_from_seed_manifest(args.seed_manifest, ROOT / "qa" / "vlm_eval")
    print(f"generated {len(cases)} cases under qa/vlm_eval")
