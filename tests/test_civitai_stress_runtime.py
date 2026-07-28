import json
from pathlib import Path

import pytest

from maskfactory.datasets.civitai_stress import build_civitai_stress_plan

POSE_PACK_CACHE_AVAILABLE = Path(
    "Plan/Civitai/extracted/"
    "203686_OpenPose_Adjusting_hair_Hand_in_own_hair_v229310_OpenposeAdjustingHair_v10"
).is_dir()


@pytest.mark.skipif(
    not POSE_PACK_CACHE_AVAILABLE,
    reason="external Civitai pose-pack cache is not present in this source checkout",
)
def test_all_pose_packs_become_deterministic_stress_inputs(tmp_path: Path) -> None:
    first = build_civitai_stress_plan(output_path=tmp_path / "first.json", verify_archives=False)
    second = build_civitai_stress_plan(output_path=tmp_path / "second.json", verify_archives=False)
    assert first.read_bytes() == second.read_bytes()
    document = json.loads(first.read_text())
    assert document["fixture_count"] == 22
    assert set(document["required_coverage"]) <= set(document["covered"])
    assert all(entry["sample_assets"] for entry in document["fixtures"])
    assert all(entry["gold_authority"] is False for entry in document["fixtures"])
