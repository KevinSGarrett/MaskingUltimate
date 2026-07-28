"""Generate a dedicated Ed25519 keypair for one provider-role promotion event."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.providers.matrix_promotion import generate_matrix_promotion_signing_key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("private_key", type=Path)
    parser.add_argument("public_key", type=Path)
    args = parser.parse_args()
    digest = generate_matrix_promotion_signing_key(args.private_key, args.public_key)
    print(json.dumps({"signer_public_key_sha256": digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
