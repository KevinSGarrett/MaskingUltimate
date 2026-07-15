"""Build or verify the signed, matrix-bound provider-role prerequisite certificate."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from maskfactory.providers.benchmark_policy import SPECIALIST_ROLES
from maskfactory.providers.matrix_promotion import (
    build_matrix_promotion_certificate,
    verify_matrix_promotion_certificate,
)


def _json(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"expected JSON object: {path}")
    return document


def _inputs(args: argparse.Namespace) -> dict:
    return {
        "matrix_report": _json(args.report),
        "matrix_observations": _json(args.observations),
        "matrix_manifest": _json(args.manifest),
        "specialist_packets": {
            role: _json(args.specialist_packet_dir / f"{role}.json")
            for role in sorted(SPECIALIST_ROLES)
        },
        "custom_segmenter_certificate": _json(args.custom_segmenter_certificate),
        "custom_segmenter_expected_identity_hashes": _json(args.custom_segmenter_identities),
        "role_matrix_bindings": _json(args.role_matrix_bindings),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--specialist-packet-dir", type=Path, required=True)
    parser.add_argument("--custom-segmenter-certificate", type=Path, required=True)
    parser.add_argument("--custom-segmenter-identities", type=Path, required=True)
    parser.add_argument("--role-matrix-bindings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    key_group = parser.add_mutually_exclusive_group(required=True)
    key_group.add_argument("--private-key", type=Path)
    key_group.add_argument("--public-key", type=Path)
    parser.add_argument("--reviewer", default="maskfactory-provider-governance")
    parser.add_argument("--issued-at", type=str)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    inputs = _inputs(args)
    if args.verify:
        if args.public_key is None:
            parser.error("--verify requires --public-key")
        certificate = _json(args.output)
        summary = verify_matrix_promotion_certificate(
            certificate, public_key_path=args.public_key, **inputs
        )
    else:
        if args.private_key is None:
            parser.error("build requires --private-key")
        certificate = build_matrix_promotion_certificate(
            reviewer=args.reviewer,
            private_key_path=args.private_key,
            issued_at=(
                datetime.fromisoformat(args.issued_at.replace("Z", "+00:00"))
                if args.issued_at
                else None
            ),
            **inputs,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(certificate, indent=2) + "\n", encoding="utf-8")
        summary = {
            "certificate_id": certificate["certificate_id"],
            "certificate_sha256": certificate["certificate_sha256"],
            "role_count": len(certificate["role_bindings"]),
            "authority": certificate["authority"],
        }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
