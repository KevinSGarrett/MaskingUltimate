from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from tools.build_visual_regression_suite import build

from maskfactory.vlm.regression_suite import (
    REQUIRED_DOMAINS,
    VisualRegressionError,
    evaluate_visual_regression,
    regression_case_sha256,
    regression_suite_sha256,
    require_current_passing_regression,
    validate_regression_suite_files,
)

ROOT = Path(__file__).resolve().parents[1]


def _built(tmp_path: Path) -> tuple[Path, dict]:
    root = tmp_path / "suite"
    return root, build(root)


def test_repository_frozen_suite_is_complete_and_exact() -> None:
    root = ROOT / "qa/vlm_eval/visual_regression_v1"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    validate_regression_suite_files(manifest, root)
    assert manifest["suite_sha256"] == (
        "22001e0769d2fe7f36077e0f23affd9b975e3987b43d73fb87781c25e09b7781"
    )


def _change(manifest: dict) -> dict:
    return {
        "schema_version": "1.0.0",
        "suite_sha256": manifest["suite_sha256"],
        "promoted_role": "primary_visual_critic",
        "model_artifact_sha256": "1" * 64,
        "provider_set_sha256": "2" * 64,
        "prompt_sha256": "3" * 64,
        "runtime_sha256": "4" * 64,
        "renderer_sha256": "5" * 64,
        "target_contract_schema_sha256": "6" * 64,
    }


def _results(manifest: dict) -> list[dict]:
    values = []
    for index, case in enumerate(manifest["cases"]):
        defect = case["expected_outcome"] == "serious_defect"
        values.append(
            {
                "case_id": case["case_id"],
                "panel_set_sha256": case["panel_set_sha256"],
                "verdict": "defect" if defect else "pass",
                "defect_type": case["defect_type"] if defect else None,
                "response_sha256": f"{index + 1:064x}",
                "deterministic_replay": True,
            }
        )
    return values


def test_builder_materializes_image_disjoint_valid_and_serious_cases_per_domain(
    tmp_path: Path,
) -> None:
    root, manifest = _built(tmp_path)
    validate_regression_suite_files(manifest, root)
    assert len(manifest["cases"]) == len(REQUIRED_DOMAINS) * 2
    assert sum(path.stat().st_size for path in root.rglob("*.png")) > 0


@pytest.mark.parametrize(
    "field",
    [
        "model_artifact_sha256",
        "provider_set_sha256",
        "prompt_sha256",
        "runtime_sha256",
        "renderer_sha256",
        "target_contract_schema_sha256",
    ],
)
def test_exact_current_change_passes_and_any_changed_fingerprint_requires_rerun(
    tmp_path: Path, field: str
) -> None:
    _, manifest = _built(tmp_path)
    change = _change(manifest)
    report = evaluate_visual_regression(change, _results(manifest), manifest)
    assert report["status"] == "pass"
    assert report["promotion_allowed"] is True
    require_current_passing_regression(report, change, manifest)
    changed = deepcopy(change)
    changed[field] = "f" * 64
    with pytest.raises(VisualRegressionError, match="current promotion fingerprint"):
        require_current_passing_regression(report, changed, manifest)


def test_any_serious_regression_or_replay_drift_blocks_promotion(tmp_path: Path) -> None:
    _, manifest = _built(tmp_path)
    results = _results(manifest)
    results[1]["verdict"] = "pass"
    results[1]["defect_type"] = None
    results[2]["deterministic_replay"] = False
    report = evaluate_visual_regression(_change(manifest), results, manifest)
    assert report["status"] == "fail"
    assert report["promotion_allowed"] is False
    assert set(report["failures"]) == {
        "serious_visual_regression",
        "deterministic_replay_failure",
    }


def test_missing_domain_or_panel_hash_drift_fails_closed(tmp_path: Path) -> None:
    root, manifest = _built(tmp_path)
    missing = deepcopy(manifest)
    missing["cases"] = [case for case in missing["cases"] if case["domain"] != "feet"]
    missing["suite_sha256"] = regression_suite_sha256(missing)
    with pytest.raises(VisualRegressionError, match="every regression domain"):
        validate_regression_suite_files(missing, root)

    drifted = deepcopy(manifest)
    drifted["cases"][0]["panels"]["overlay"] = "f" * 64
    drifted["cases"][0]["case_sha256"] = regression_case_sha256(drifted["cases"][0])
    drifted["suite_sha256"] = regression_suite_sha256(drifted)
    with pytest.raises(VisualRegressionError, match="panel hash drifted"):
        validate_regression_suite_files(drifted, root)
