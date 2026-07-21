"""Seal or verify a complete specialist evidence package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.providers.benchmark_policy import load_specialist_margin_manifest
from maskfactory.providers.specialist_evidence import seal_package, validate_package


def _load_results(directory: Path) -> dict[str, dict]:
    results = {}
    for path in sorted(Path(directory).glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        role = document.get("role")
        if not isinstance(role, str) or role in results:
            raise ValueError(f"invalid or duplicate specialist result role: {path}")
        results[role] = document
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("document", type=Path)
    parser.add_argument("--benchmark-results", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify and args.output is not None:
        parser.error("--output is not valid with --verify")
    if not args.verify and args.output is None:
        parser.error("--output is required when sealing")

    document = json.loads(args.document.read_text(encoding="utf-8"))
    results = _load_results(args.benchmark_results)
    margin_manifest, _ = load_specialist_margin_manifest()
    if args.verify:
        validate_package(
            document,
            benchmark_results=results,
            margin_manifest=margin_manifest,
            artifact_root=args.artifact_root,
        )
        sealed = document
    else:
        sealed = seal_package(
            document,
            benchmark_results=results,
            margin_manifest=margin_manifest,
            artifact_root=args.artifact_root,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(args.output.name + ".tmp")
        temporary.write_text(json.dumps(sealed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(args.output)
    print(json.dumps({"package_id": sealed["package_id"], "sha256": sealed["sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
