"""Create and seal one bounded split-person recomposition candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.nude_split_person_recomposition import build_split_person_recomposition


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--parents", type=Path, nargs="+", required=True)
    parser.add_argument("--parent-confidences", type=float, nargs="+", required=True)
    parser.add_argument("--detector-box-xyxy", type=int, nargs=4, required=True)
    parser.add_argument("--detector-person-count", type=int, required=True)
    parser.add_argument("--catalog-batch-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output-relative-path", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--runtime-fingerprint", required=True)
    parser.add_argument("--batch-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args()
    batch, report = build_split_person_recomposition(
        sample_id=args.sample_id,
        source_path=args.source,
        parent_paths=args.parents,
        parent_confidences=args.parent_confidences,
        detector_box_xyxy=args.detector_box_xyxy,
        detector_person_count=args.detector_person_count,
        catalog_batch_sha256=args.catalog_batch_sha256,
        output_root=args.output_root,
        output_relative_path=args.output_relative_path,
        source_commit=args.source_commit,
        runtime_fingerprint=args.runtime_fingerprint,
    )
    for path, document in (
        (args.batch_output, batch),
        (args.report_output, report),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "draft_candidate_created",
                "batch_self_sha256": batch["self_sha256"],
                "report_self_sha256": report["self_sha256"],
                "artifact_sha256": batch["records"][0]["candidates"][0]["artifact_sha256"],
                "authority": "draft_machine_candidate_only",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
