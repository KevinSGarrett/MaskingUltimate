"""Seal the governed P8 multi-instance count fixture registry."""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maskfactory.qa.multi_instance_fixtures import seal_multi_instance_fixture_set  # noqa: E402

if __name__ == "__main__":
    config = yaml.safe_load((ROOT / "configs/pipeline.yaml").read_text(encoding="utf-8"))
    document = seal_multi_instance_fixture_set(
        ROOT / "qa/multi_instance_fixtures/source_registry.json",
        ROOT / "qa/multi_instance_fixtures/manifest.json",
        project_root=ROOT,
        max_instances_per_image=int(config["stages"]["S01"]["max_instances_per_image"]),
        work_root=Path("work"),
    )
    print(f"sealed {document['fixture_count']} multi-instance fixtures")
