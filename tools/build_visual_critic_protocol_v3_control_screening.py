#!/usr/bin/env python3
"""Bind an admitted session-agent control board for protocol-v3 screening only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from maskfactory.vlm.critic_protocol_v3_control_screening import (
    build_control_screening_execution,
    validate_control_screening_execution,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission", type=Path, required=True)
    parser.add_argument("--panel-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite immutable execution: {args.output}")
    admission = json.loads(args.admission.read_text(encoding="utf-8"))
    registry = yaml.safe_load(args.registry.read_text(encoding="utf-8"))
    execution = build_control_screening_execution(
        admission=admission,
        admission_file_sha256=_sha256(args.admission),
        panel_root=args.panel_root,
        registry=registry,
    )
    validate_control_screening_execution(execution, registry)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(execution, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "case_count": execution["case_count"],
                "execution_manifest_sha256": execution["execution_manifest_sha256"],
                "authority_claimed": False,
                "calibration_fitting_allowed": False,
                "holdout_role_qualification_allowed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
