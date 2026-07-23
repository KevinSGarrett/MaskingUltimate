#!/usr/bin/env python3
"""Freeze qualified, identity-isolated CelebAMask critic controls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.external_supervision_evidence import publish_immutable_evidence
from maskfactory.vlm.celebamask_control_admission import (
    build_celebamask_control_admission,
)


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object:{path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--panel-report", type=Path, required=True)
    parser.add_argument("--panel-root", type=Path, required=True)
    parser.add_argument("--semantic-review", type=Path, required=True)
    parser.add_argument("--qualification-bundle", type=Path, required=True)
    parser.add_argument("--split-dedup", type=Path, required=True)
    parser.add_argument("--hq-mapping", type=Path, required=True)
    parser.add_argument("--identity-metadata", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    document = build_celebamask_control_admission(
        candidates=_load(args.candidates),
        panel_report=_load(args.panel_report),
        panel_root=args.panel_root,
        semantic_review=_load(args.semantic_review),
        qualification_bundle=_load(args.qualification_bundle),
        split_dedup_evidence=_load(args.split_dedup),
        hq_mapping_path=args.hq_mapping,
        identity_path=args.identity_metadata,
        project_root=args.project_root,
    )
    file_sha256 = publish_immutable_evidence(document, args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "file_sha256": file_sha256,
                "self_sha256": document["self_sha256"],
                "admitted_count": document["admitted_count"],
                "admitted_by_outcome": document["admitted_by_outcome"],
                "admitted_by_partition": document["admitted_by_partition"],
                "excluded_count": document["excluded_count"],
                "critic_role_authority_granted": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
