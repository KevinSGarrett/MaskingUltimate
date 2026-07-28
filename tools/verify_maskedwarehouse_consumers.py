from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.maskedwarehouse_consumers import verify_maskedwarehouse_consumers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.resolve()
    report = verify_maskedwarehouse_consumers(
        project_root=root,
        provenance_path=root / "configs/maskedwarehouse_provenance.yaml",
        binding_path=root / "configs/maskedwarehouse_consumer_bindings.json",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "seal_sha256": report["seal_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
