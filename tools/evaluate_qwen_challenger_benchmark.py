"""Build or verify the frozen local-Qwen challenger benchmark report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.vlm.qwen_benchmark import build_report, load_policy, verify_report


def _load(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return document


def _write_atomic(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--allow-failed-result", action="store_true")
    args = parser.parse_args()
    cases = _load(args.cases)
    policy = (
        load_policy(args.policy, root=args.root) if args.policy else load_policy(root=args.root)
    )
    if args.verify:
        report = _load(args.output)
        verify_report(
            report,
            cases,
            policy=policy,
            root=args.root,
            artifact_root=args.artifact_root,
            require_pass=not args.allow_failed_result,
        )
    else:
        report = build_report(
            cases,
            policy=policy,
            root=args.root,
            artifact_root=args.artifact_root,
        )
        _write_atomic(args.output, report)
        if report["result"] != "pass" and not args.allow_failed_result:
            return 1
    print(
        json.dumps(
            {
                "result": report["result"],
                "sha256": report["sha256"],
                "winner": report["winner"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
