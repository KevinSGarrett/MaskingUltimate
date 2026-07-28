#!/usr/bin/env python3
"""Build the hash-bound real-image ontology-v2 authority-pilot selection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.ontology_v2_authority_pilot import build_authority_pilot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--intake",
        type=Path,
        default=Path(r"C:\Comfy_UI_Main\MaskedWarehouse\Nude\_MASKFACTORY_INTAKE"),
    )
    parser.add_argument("--hard-qc-records", type=Path, required=True)
    parser.add_argument(
        "--reference-root",
        type=Path,
        default=Path(r"F:\Reference_Images\Ultimate_Masking_Reference_Images"),
    )
    parser.add_argument("--ontology", type=Path, default=Path("configs/ontology_v2.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    document = build_authority_pilot(
        intake_root=args.intake,
        hard_qc_records_path=args.hard_qc_records,
        reference_root=args.reference_root,
        ontology_path=args.ontology,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": document["selection_status"],
                "images": document["image_count"],
                "coverage_targets": document["coverage_target_count"],
                "resolved_states": document["resolved_states"],
                "pilot_complete": document["pilot_complete"],
                "self_sha256": document["self_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
