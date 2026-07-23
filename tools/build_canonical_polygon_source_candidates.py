"""Select exact adult-polygon sources for later visual-control qualification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.vlm.canonical_polygon_source_candidates import (
    build_canonical_polygon_source_candidates,
    load_jsonl,
    sha256_file,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--hard-qc-summary", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-partition", type=int, default=16)
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    hard_qc_summary = json.loads(args.hard_qc_summary.read_text(encoding="utf-8"))
    document = build_canonical_polygon_source_candidates(
        records=load_jsonl(args.records),
        registry=registry,
        hard_qc_summary=hard_qc_summary,
        records_file_sha256=sha256_file(args.records),
        registry_file_sha256=sha256_file(args.registry),
        hard_qc_summary_file_sha256=sha256_file(args.hard_qc_summary),
        per_partition=args.per_partition,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "selected": document["selected_count"],
                "by_partition": document["selected_by_partition"],
                "self_sha256": document["self_sha256"],
                "authority_claimed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
