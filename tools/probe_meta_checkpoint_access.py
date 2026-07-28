from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from maskfactory.providers.meta_checkpoint_access import (
    MetaCheckpointAccessError,
    probe_meta_checkpoint_access,
    resolve_huggingface_token,
    verify_meta_checkpoint_access_probe,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only access probe for official SAM3.1 and SAM 3D Body checkpoints."
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        document = probe_meta_checkpoint_access(token=resolve_huggingface_token())
        verify_meta_checkpoint_access_probe(document)
        rendered = json.dumps(document, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(rendered)
        else:
            print(rendered, end="")
    except (MetaCheckpointAccessError, OSError, ValueError) as exc:
        print(f"checkpoint access probe failed: {exc}", file=sys.stderr)
        return 1
    if document["result"] == "access_ready":
        return 0
    return 2 if document["result"] == "human_gate_pending" else 1


if __name__ == "__main__":
    raise SystemExit(main())
