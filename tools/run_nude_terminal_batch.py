"""Write immutable terminal qualification receipts for one prepared JSONL batch."""

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

from maskfactory.nude_terminal_batch import process_terminal_batch  # noqa: E402


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
    args = parser.parse_args()
    source_bytes = args.input_jsonl.read_bytes()
    summary = process_terminal_batch(
        _load_jsonl(args.input_jsonl),
        source_manifest_sha256=hashlib.sha256(source_bytes).hexdigest(),
        output_root=args.output_root,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
