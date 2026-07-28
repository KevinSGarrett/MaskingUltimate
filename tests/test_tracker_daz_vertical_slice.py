from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACKER_SOURCE = ROOT / "Plan" / "Tracker" / "tracker.py"


def _tracker_module() -> dict:
    return runpy.run_path(str(TRACKER_SOURCE))


def test_daz_vertical_slice_defaults_are_explicit_and_fail_closed() -> None:
    metrics = _tracker_module()["DEFAULT_METRICS"]
    assert metrics["daz_asset_identity_hashes_complete"] == 0
    assert metrics["daz_asset_identity_hashes_total"] == 0
    assert metrics["daz_live_compatibility_graph_status"] == "unpublished"
    assert metrics["daz_live_qualified_asset_count"] == 0
    assert metrics["daz_live_smoke_certificate_count"] == 0
    assert metrics["daz_live_assembled_scene_count"] == 0
    assert metrics["daz_live_exact_synthetic_package_count"] == 0
    assert metrics["daz_synthetic_trained_challenger_count"] == 0
    assert metrics["daz_measured_real_image_improvement_status"] == "not_measured"
    assert metrics["daz_storage_new_work_allowed"] is False


def test_daz_vertical_slice_rows_separate_execution_from_implementation() -> None:
    module = _tracker_module()
    metrics = dict(module["DEFAULT_METRICS"])
    metrics.update(
        {
            "daz_asset_identity_hashes_complete": 2859,
            "daz_asset_identity_hashes_total": 41094,
            "daz_storage_free_gib": 140.4066,
            "daz_storage_new_work_floor_gib": 150.0,
            "daz_storage_new_work_allowed": False,
        }
    )
    rows = module["daz_vertical_slice_rows"]({"metrics": metrics})
    rendered = "\n".join(" | ".join(row) for row in rows)
    assert "2,859/41,094 hashes (7.0%)" in rendered
    assert "0 qualified assets / 0 live certificates" in rendered
    assert "0 live assembled scenes" in rendered
    assert "0 verified live packages" in rendered
    assert "real-image improvement: not_measured" in rendered
    assert "new acquisition/major hashing/render work paused" in rendered
