"""Process prepared terminal records and checkpoint their valid contiguous prefix."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from maskfactory.nude_batch_queue import NudeBatchQueue  # noqa: E402
from maskfactory.nude_terminal_queue_bridge import bridge_terminal_batch_to_queue  # noqa: E402


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"line_{line_number}_must_be_object")
        entries.append(value)
    if not entries:
        raise ValueError("input_jsonl_is_empty")
    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--shard-path", required=True)
    parser.add_argument("--lease-token", required=True)
    parser.add_argument("--registry-records", type=Path)
    parser.add_argument("--ontology-crosswalk", type=Path)
    args = parser.parse_args()
    source_bytes = args.input_jsonl.read_bytes()
    result = bridge_terminal_batch_to_queue(
        _load_jsonl(args.input_jsonl),
        source_manifest_sha256=hashlib.sha256(source_bytes).hexdigest(),
        output_root=args.output_root,
        queue=NudeBatchQueue(args.queue),
        platform=args.platform,
        shard_path=args.shard_path,
        lease_token=args.lease_token,
        registry_records=args.registry_records,
        ontology_crosswalk=args.ontology_crosswalk,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
