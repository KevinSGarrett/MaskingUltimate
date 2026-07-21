"""Verify and atomically assemble one qualified AWS-to-RunPod transfer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.aws_runpod_transfer import assemble_transfer, verify_transfer_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--allowed-root", type=Path, default=Path("/workspace"))
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    verified = verify_transfer_manifest(args.manifest, allowed_root=args.allowed_root)
    if args.verify_only:
        result = {
            "status": "verified_complete_chunk_set",
            "transfer_id": verified.transfer_id,
            "manifest_sha256": verified.manifest_sha256,
            "chunks": len(verified.chunk_paths),
            "bytes": verified.expected_bytes,
        }
    else:
        result = assemble_transfer(verified)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
