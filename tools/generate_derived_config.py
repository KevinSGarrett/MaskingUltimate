"""Generate configs/derived.yaml from the audited doc-02 formula registry."""

from pathlib import Path

import yaml

from maskfactory.ontology_source import DERIVED_FORMULAS

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "configs" / "derived.yaml"


def main() -> int:
    document = {"config_version": "1.0.0", "formulas": DERIVED_FORMULAS}
    OUTPUT.write_text(yaml.safe_dump(document, sort_keys=False, width=200), encoding="utf-8")
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
