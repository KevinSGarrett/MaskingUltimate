"""Build or verify the signed matrix-bound interactive promotion prerequisite."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from maskfactory.providers.interactive_promotion import (
    build_interactive_promotion_certificate,
    verify_interactive_promotion_certificate,
)


def _object(path: Path, name: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-bundle", type=Path, required=True)
    parser.add_argument("--benchmark-certificate", type=Path, required=True)
    parser.add_argument("--rollback-evidence", type=Path, required=True)
    parser.add_argument("--candidate-key", required=True)
    parser.add_argument("--incumbent-key", required=True)
    parser.add_argument("--candidate-artifact-key", required=True)
    parser.add_argument("--incumbent-artifact-key", required=True)
    parser.add_argument("--candidate-checkpoint-sha256", required=True)
    parser.add_argument("--incumbent-checkpoint-sha256", required=True)
    parser.add_argument("--candidate-runtime-lock-sha256", required=True)
    parser.add_argument("--private-key", type=Path)
    parser.add_argument("--reviewer")
    parser.add_argument("--issued-at")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--certificate", type=Path)
    parser.add_argument("--verify", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    common = {
        "matrix_bundle_root": args.matrix_bundle,
        "benchmark_certificate": _object(args.benchmark_certificate, "benchmark certificate"),
        "rollback_evidence": _object(args.rollback_evidence, "rollback evidence"),
        "candidate_key": args.candidate_key,
        "incumbent_key": args.incumbent_key,
        "candidate_artifact_key": args.candidate_artifact_key,
        "incumbent_artifact_key": args.incumbent_artifact_key,
        "candidate_checkpoint_sha256": args.candidate_checkpoint_sha256,
        "incumbent_checkpoint_sha256": args.incumbent_checkpoint_sha256,
        "candidate_runtime_lock_sha256": args.candidate_runtime_lock_sha256,
    }
    if args.verify:
        if args.certificate is None:
            raise ValueError("--verify requires --certificate")
        summary = verify_interactive_promotion_certificate(
            _object(args.certificate, "interactive promotion certificate"), **common
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.private_key is None or not args.reviewer or args.output is None:
        raise ValueError("build requires --private-key, --reviewer, and --output")
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite certificate: {args.output}")
    issued_at = (
        datetime.fromisoformat(args.issued_at.replace("Z", "+00:00")) if args.issued_at else None
    )
    certificate = build_interactive_promotion_certificate(
        reviewer=args.reviewer,
        private_key_path=args.private_key,
        issued_at=issued_at,
        **common,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(certificate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(certificate, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
