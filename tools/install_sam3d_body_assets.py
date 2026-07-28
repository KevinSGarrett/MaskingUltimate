from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from maskfactory.providers.checkpoint_install import (
    CheckpointInstallError,
    install_checkpoint,
)
from maskfactory.providers.meta_checkpoint_access import resolve_huggingface_token

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "env/sam3d_body_runtime.lock.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the frozen official SAM 3D Body assets atomically."
    )
    parser.add_argument("--target-root", type=Path)
    args = parser.parse_args()
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    checkpoint = lock["checkpoint"]
    target_root = args.target_root or ROOT / checkpoint["local_root"]
    token = resolve_huggingface_token()
    if token is None:
        print(
            "SAM 3D Body install failed: Hugging Face authentication is unavailable",
            file=sys.stderr,
        )
        return 1
    repository = checkpoint["repository"]
    revision = checkpoint["repository_revision"]
    results = []
    try:
        for asset in checkpoint["assets"]:
            filename = asset["filename"]
            url = f"https://huggingface.co/{repository}/resolve/{revision}/{filename}"
            result = install_checkpoint(
                url=url,
                destination=target_root / filename,
                expected_size=asset["size_bytes"],
                expected_sha256=asset["sha256"],
                token=token,
            )
            results.append({"filename": filename, **result})
            print(
                json.dumps(
                    {
                        "filename": filename,
                        "result": "reused" if result["reused_existing"] else "installed",
                        "size_bytes": result["size_bytes"],
                        "sha256": result["sha256"],
                        "credential_redacted": result["credential_redacted"],
                    },
                    sort_keys=True,
                )
            )
    except (CheckpointInstallError, OSError, ValueError) as exc:
        print(f"SAM 3D Body install failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "result": "installed",
                "asset_count": len(results),
                "total_size_bytes": sum(item["size_bytes"] for item in results),
                "downloaded_bytes": sum(item["downloaded_bytes"] for item in results),
                "all_credentials_redacted": all(item["credential_redacted"] for item in results),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
