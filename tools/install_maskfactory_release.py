"""Install a clean MaskFactory release with hash and manifest verification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.bridge.clean_release_packaging import install_clean_release


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--proof-out", type=Path, required=False)
    args = parser.parse_args()
    proof = install_clean_release(
        manifest_path=args.manifest,
        release_root=args.release_root,
        runtime_root=args.runtime_root,
        proof_out=args.proof_out,
    )
    print(json.dumps(proof, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
