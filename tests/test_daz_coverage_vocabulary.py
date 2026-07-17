from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.datasets.coverage import ATTRIBUTES, CONTEXTS, POSES, VIEWS
from maskfactory.daz.coverage import (
    CoverageVocabularyError,
    build_coverage_vocabulary_report,
    load_coverage_vocabulary,
    publish_coverage_vocabulary_report,
    validate_coverage_vocabulary,
    validate_coverage_vocabulary_report,
)
from maskfactory.validation import ArtifactValidationError

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs" / "daz" / "coverage_vocabulary.yaml"


def _rehash_report(report: dict) -> None:
    content = {
        key: value
        for key, value in report.items()
        if key not in {"schema_version", "report_id", "report_sha256"}
    }
    digest = hashlib.sha256(
        json.dumps(
            content,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    report["report_id"] = f"dcvr_{digest[:24]}"
    report["report_sha256"] = digest


def _axes(document: dict) -> dict[str, dict]:
    return {row["axis_id"]: row for row in document["axes"]}


def test_live_sources_build_closed_vocabulary_and_exact_canonical_crosswalk() -> None:
    policy = load_coverage_vocabulary(POLICY)
    report = build_coverage_vocabulary_report(policy, ROOT)
    validate_coverage_vocabulary_report(report)
    axes = _axes(report)
    assert axes["canonical_view"]["values"] == list(VIEWS)
    assert axes["canonical_pose"]["values"] == list(POSES)
    assert axes["instance_context"]["values"] == list(CONTEXTS)
    assert axes["canonical_attribute"]["values"] == list(ATTRIBUTES)
    assert report["summary"] == {
        "closed": True,
        "source_hashes_match": True,
        "canonical_crosswalk_exact": True,
        "fixed_axis_count": 55,
        "fixed_value_count": 381,
        "registry_axis_count": 8,
        "continuous_axis_count": 6,
        "high_risk_intersection_count": 18,
    }


def test_fixed_registry_and_continuous_axes_remain_distinct() -> None:
    report = build_coverage_vocabulary_report(load_coverage_vocabulary(POLICY), ROOT)
    fixed = {row["axis_id"] for row in report["axes"]}
    registry = {row["axis_id"] for row in report["registry_axes"]}
    continuous = {row["axis_id"] for row in report["continuous_axes"]}
    assert not fixed & registry
    assert not fixed & continuous
    assert not registry & continuous
    assert {"skin_tone_band", "relationship_family", "render_profile"} <= fixed
    assert {"hair_asset_id", "recipe_family_id"} <= registry
    assert {"body_morph_value", "prominence_score"} <= continuous


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda p: p["axes"].pop(), "axes_invalid"),
        (
            lambda p: p["axes"][0]["values"].__setitem__(0, "invented_view"),
            "canonical_crosswalk_invalid",
        ),
        (
            lambda p: p["registry_axes"][0].__setitem__("value_pattern", "["),
            "registry_pattern_invalid",
        ),
        (
            lambda p: p["continuous_axes"][0].__setitem__("maximum", -1.0),
            "continuous_axis_invalid",
        ),
        (
            lambda p: p["high_risk_intersections"][0]["axes"].append("invented_axis"),
            "intersections_invalid",
        ),
        (
            lambda p: p["reporting"].__setitem__("accepted_only_updates_accepted_coverage", False),
            "reporting_invalid",
        ),
        (
            lambda p: p["authority"].__setitem__("synthetic_counts_as_gold", True),
            "authority_invalid",
        ),
    ],
)
def test_policy_drift_fails_closed(mutation, reason: str) -> None:
    policy = load_coverage_vocabulary(POLICY)
    mutation(policy)
    with pytest.raises(CoverageVocabularyError, match=reason):
        validate_coverage_vocabulary(policy)


def test_source_hash_and_source_crosswalk_drift_fail_before_report() -> None:
    policy = load_coverage_vocabulary(POLICY)
    policy["source_snapshots"][0]["sha256"] = "0" * 64
    with pytest.raises(CoverageVocabularyError, match="source_hash_mismatch"):
        build_coverage_vocabulary_report(policy, ROOT)
    policy = load_coverage_vocabulary(POLICY)
    _axes(policy)["lighting_profile"]["values"].reverse()
    with pytest.raises(CoverageVocabularyError, match="source_crosswalk_invalid"):
        build_coverage_vocabulary_report(policy, ROOT)


def test_high_risk_intersections_are_closed_and_reference_declared_axes() -> None:
    report = build_coverage_vocabulary_report(load_coverage_vocabulary(POLICY), ROOT)
    all_axes = {row["axis_id"] for row in report["axes"] + report["registry_axes"]}
    intersections = {
        row["intersection_id"]: row["axes"] for row in report["high_risk_intersections"]
    }
    assert set(intersections) >= {
        "skin_lighting",
        "multi_crossed_similar",
        "anatomy_p_index_role",
        "prop_body_occlusion",
    }
    assert all(set(axes) <= all_axes for axes in intersections.values())
    assert all(2 <= len(axes) <= 4 for axes in intersections.values())


def test_report_schema_hash_policy_replay_and_publication_fail_closed(tmp_path: Path) -> None:
    report = build_coverage_vocabulary_report(load_coverage_vocabulary(POLICY), ROOT)
    unknown = copy.deepcopy(report)
    unknown["unknown"] = True
    with pytest.raises(ArtifactValidationError, match="Additional properties"):
        validate_coverage_vocabulary_report(unknown)
    tampered = copy.deepcopy(report)
    tampered["axes"][0]["values"][0] = "invented_view"
    _rehash_report(tampered)
    with pytest.raises(CoverageVocabularyError, match="canonical_crosswalk_invalid"):
        validate_coverage_vocabulary_report(tampered)
    target, published = publish_coverage_vocabulary_report(report, tmp_path / "reports")
    assert published is True
    assert publish_coverage_vocabulary_report(report, tmp_path / "reports") == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(CoverageVocabularyError, match="publication_conflict"):
        publish_coverage_vocabulary_report(report, tmp_path / "reports")


def test_reporting_and_authority_never_conflate_synthetic_with_gold() -> None:
    report = build_coverage_vocabulary_report(load_coverage_vocabulary(POLICY), ROOT)
    assert report["reporting"]["states"] == [
        "planned",
        "attempted",
        "rendered",
        "accepted",
        "packaged",
        "dataset_selected",
        "consumed_by_training",
    ]
    assert report["reporting"]["units"] == [
        "scene",
        "person_instance",
        "effective_training_weight",
    ]
    assert report["authority"] == {
        "synthetic_counts_as_gold": False,
        "synthetic_counts_as_real_accuracy": False,
        "synthetic_diagnostic_is_promotion_authority": False,
        "registry_values_require_versioned_snapshot": True,
        "unknown_values_fail_closed": True,
    }


def test_cli_publishes_and_replays_source_bound_vocabulary(tmp_path: Path) -> None:
    command = [
        "daz",
        "coverage",
        "vocabulary-report",
        "--policy",
        str(POLICY),
        "--repository-root",
        str(ROOT),
        "--output",
        str(tmp_path / "reports"),
    ]
    runner = CliRunner()
    first = runner.invoke(main, command)
    assert first.exit_code == 0, first.output
    payload = json.loads(first.output)
    assert payload["reason"] == "daz_coverage_vocabulary_report_built"
    assert payload["data"]["summary"]["closed"] is True
    assert payload["data"]["publication"]["published"] is True
    replay = runner.invoke(main, command)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
