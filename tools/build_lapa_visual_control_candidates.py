#!/usr/bin/env python3
"""Build immutable LaPa candidate selection and exact panel evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.external_supervision_evidence import publish_immutable_evidence
from maskfactory.vlm.canonical_polygon_source_candidates import sha256_file
from maskfactory.vlm.lapa_control_candidates import (
    build_lapa_control_candidates,
    materialize_lapa_control_panels,
    verify_lapa_control_panel_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--remap", type=Path, required=True)
    parser.add_argument("--qualification-evidence", type=Path, required=True)
    parser.add_argument("--source-hash-manifest", type=Path, required=True)
    parser.add_argument("--split-dedup", type=Path, required=True)
    parser.add_argument("--candidate-output", type=Path, required=True)
    parser.add_argument("--panel-output", type=Path, required=True)
    parser.add_argument("--per-partition", type=int, default=8)
    args = parser.parse_args()
    candidates = build_lapa_control_candidates(
        source_root=args.source_root, project_root=args.project_root,
        provenance_path=args.provenance, inventory_path=args.inventory,
        remap_path=args.remap, qualification_evidence_path=args.qualification_evidence,
        source_hash_manifest_path=args.source_hash_manifest, split_dedup_path=args.split_dedup,
        per_partition=args.per_partition,
    )
    candidate_file_sha256 = publish_immutable_evidence(candidates, args.candidate_output)
    if args.panel_output.exists():
        report = json.loads((args.panel_output / "report.json").read_text(encoding="utf-8"))
        verify_lapa_control_panel_report(report, args.panel_output)
        if report.get("candidate_set_sha256") != candidates["self_sha256"]:
            raise ValueError("existing panels bind a different candidate set")
    else:
        report = materialize_lapa_control_panels(
            source_root=args.source_root, candidate_document=candidates, output_root=args.panel_output
        )
    print(json.dumps({
        "status": "PASS", "candidate_output": str(args.candidate_output.resolve()),
        "candidate_file_sha256": candidate_file_sha256, "candidate_set_sha256": candidates["self_sha256"],
        "panel_output": str(args.panel_output.resolve()), "panel_report_sha256": sha256_file(args.panel_output / "report.json"),
        "record_count": report["record_count"], "panel_count": report["panel_count"], "authority_claimed": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
