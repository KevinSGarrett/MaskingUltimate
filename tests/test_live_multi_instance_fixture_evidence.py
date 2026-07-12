import json
from pathlib import Path


def test_live_multi_instance_fixture_set_has_exact_completed_fanout() -> None:
    manifest = json.loads(
        Path("qa/multi_instance_fixtures/manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["fixture_count"] == 2
    assert manifest["max_instances_per_image"] == 4
    assert manifest["downstream_status"] == "verified_exact_promoted_draft_packages"
    expected = {
        "supplied_adult_triptych_3": (3, ["p0", "p1", "p2"]),
        "supplied_adult_four_view_4": (4, ["p0", "p1", "p2", "p3"]),
    }
    for fixture in manifest["fixtures"]:
        count, promoted = expected[fixture["key"]]
        assert fixture["manual_visible_instance_count"] == count
        assert fixture["raw_detection_count"] == count
        assert fixture["promoted_instances"] == promoted
        assert fixture["promoted_instance_count"] == len(promoted)
        assert fixture["downstream_package_count_verified"] is True
        assert fixture["source_path"].startswith("data/images/img_")
        assert fixture["s01_evidence_path"].startswith("work/s01/img_")
        assert len(fixture["source_sha256"]) == 64
        assert len(fixture["s01_evidence_sha256"]) == 64
