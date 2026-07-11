"""Seal the governed P8 multi-instance count fixture registry."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maskfactory.qa.multi_instance_fixtures import seal_multi_instance_fixture_set  # noqa: E402

if __name__ == "__main__":
    document = seal_multi_instance_fixture_set(
        ROOT / "qa/multi_instance_fixtures/source_registry.json",
        ROOT / "qa/multi_instance_fixtures/manifest.json",
        project_root=ROOT,
    )
    print(f"sealed {document['fixture_count']} multi-instance fixtures")
