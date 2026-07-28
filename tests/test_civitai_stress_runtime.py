import json
from pathlib import Path

from maskfactory.datasets.civitai_stress import build_civitai_stress_plan


def test_all_pose_packs_become_deterministic_stress_inputs(tmp_path: Path) -> None:
    first = build_civitai_stress_plan(output_path=tmp_path / "first.json", verify_archives=False)
    second = build_civitai_stress_plan(output_path=tmp_path / "second.json", verify_archives=False)
    assert first.read_bytes() == second.read_bytes()
    document = json.loads(first.read_text())
    assert document["fixture_count"] == 22
    assert set(document["required_coverage"]) <= set(document["covered"])
    assert all(entry["sample_assets"] for entry in document["fixtures"])
    assert all(entry["gold_authority"] is False for entry in document["fixtures"])
