"""Build or verify the non-core legacy portfolio/research evidence index."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The tool is executable directly from any working directory. Resolve the
# repository's own source tree before importing ``maskfactory`` so an older
# editable/global installation cannot silently supply a different frozen policy.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from maskfactory.completion_bundle import build_report, load_policy, verify_report  # noqa: E402


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return value


def _write_atomic(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    document = _load(args.input)
    policy = (
        load_policy(args.policy, root=args.root) if args.policy else load_policy(root=args.root)
    )
    kwargs = {
        "policy": policy,
        "root": args.root,
        "artifact_root": args.artifact_root or args.root,
    }
    if args.verify:
        report = _load(args.output)
        verify_report(report, document, **kwargs)
    else:
        report = build_report(document, **kwargs)
        _write_atomic(args.output, report)
    print(json.dumps({"result": report["result"], "sha256": report["sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
