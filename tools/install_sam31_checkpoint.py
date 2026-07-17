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
DEFAULT_TARGET = ROOT / "models/runtime_cache/sam31_checkpoint_daa63191/sam3.1_multiplex.pt"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the frozen official SAM 3.1 checkpoint atomically."
    )
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    lock = json.loads((ROOT / "env/sam31_runtime.lock.json").read_text(encoding="utf-8"))
    checkpoint = lock["checkpoint"]
    token = resolve_huggingface_token()
    if token is None:
        print("SAM 3.1 install failed: Hugging Face authentication is unavailable", file=sys.stderr)
        return 1
    url = (
        f"https://huggingface.co/{checkpoint['repository']}/resolve/"
        f"{checkpoint['repository_revision']}/{checkpoint['filename']}"
    )
    last_reported = -1

    def report_progress(written: int, total: int) -> None:
        nonlocal last_reported
        percent = int(written * 100 / total)
        if percent >= last_reported + 5 or written == total:
            last_reported = percent
            print(json.dumps({"progress_percent": percent, "written_bytes": written}))

    try:
        result = install_checkpoint(
            url=url,
            destination=args.target,
            expected_size=checkpoint["size_bytes"],
            expected_sha256=checkpoint["sha256"],
            token=token,
            progress=report_progress,
        )
    except (CheckpointInstallError, OSError, ValueError) as exc:
        print(f"SAM 3.1 install failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"result": "installed", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
