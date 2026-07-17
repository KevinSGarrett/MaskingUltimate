from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.datasets.coverage import build_coverage_matrix
from maskfactory.datasets.coverage_v2 import build_v2_coverage_matrix
from maskfactory.daz.coverage import (
    RealDeficitSignalError,
    build_real_deficit_signal_report,
    load_deficit_adapter_policy,
    publish_real_deficit_signal_report,
    validate_deficit_adapter_policy,
    validate_real_deficit_signal_report,
)
from maskfactory.models.ontology_contract import V2_PART_CLASS_NAMES
from maskfactory.validation import ArtifactValidationError

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs" / "daz" / "deficit_signal_adapter.yaml"
VOCABULARY_REPORT = (
    ROOT / "qa" / "reports" / "daz_coverage_vocabulary" / "dcvr_f3b4c3927cc77cb389904bfc.json"
)


def _sha(document: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _rehash_report(report: dict) -> None:
    content = {
        key: value
        for key, value in report.items()
        if key not in {"schema_version", "report_id", "report_sha256"}
    }
    digest = _sha(content)
    report["report_id"] = f"drds_{digest[:24]}"
    report["report_sha256"] = digest


def _rehash_demand(demand: dict) -> None:
    content = {key: value for key, value in demand.items() if key != "demand_id"}
    demand["demand_id"] = f"drd_{_sha(content)[:24]}"


def _vocabulary() -> dict:
    return json.loads(VOCABULARY_REPORT.read_text(encoding="utf-8"))


def _v1_matrix() -> dict:
    return build_coverage_matrix(
        [
            {
                "status": "human_approved_gold",
                "view": "front",
                "pose_tags": ["arms_down"],
                "instance_context": "solo",
                "attributes": ["hands_visible"],
            }
        ],
        generated_at=datetime(2026, 7, 17, tzinfo=UTC),
    )


def _v2_matrix() -> dict:
    package = {
        "workflow_status": "approved_gold",
        "reviewed_ontology_version": "body_parts_v2",
        "person": {"view": "front", "pose_tags": ["arms_down"]},
        "parts": {
            label: {"visibility": "not_visible" if label == "background" else "visible"}
            for label in V2_PART_CLASS_NAMES
        },
        "coverage_contexts": {label: ["none_visible"] for label in V2_PART_CLASS_NAMES[1:]},
    }
    return build_v2_coverage_matrix([package], generated_at=datetime(2026, 7, 17, tzinfo=UTC))


def _build(source: dict, source_id: str = "real_coverage_snapshot") -> dict:
    return build_real_deficit_signal_report(
        source,
        source_id=source_id,
        source_sha256=_sha(source),
        policy=load_deficit_adapter_policy(POLICY),
        vocabulary_report=_vocabulary(),
    )


def test_policy_freezes_d5_targets_actionability_and_authority() -> None:
    policy = load_deficit_adapter_policy(POLICY)
    assert policy["supported_sources"]["coverage_matrix_v1"]["target_per_cell"] == 8
    assert policy["supported_sources"]["coverage_matrix_v1"]["target_per_attribute"] == 40
    assert (
        policy["supported_sources"]["coverage_matrix_v2"]["production_activation_granted"] is False
    )
    assert policy["authority"]["synthetic_counts_close_real_deficits"] is False


def test_v1_import_is_exact_ranked_read_only_and_does_not_close_real_coverage() -> None:
    source = _v1_matrix()
    original = copy.deepcopy(source)
    report = _build(source)
    validate_real_deficit_signal_report(report)
    assert source == original
    assert report["source"]["authority_namespace"] == "real_certified_coverage"
    assert (
        report["policy_sha256"]
        == "c6e03cca2f5427f5d5e8b79d61c7233b9667e909d27775188a3380cb01fac93c"
    )
    assert report["source"]["production_activation_granted"] is True
    assert report["summary"] == {
        "positive_deficit_count": 138,
        "eligible_count": 138,
        "inactive_ontology_observation_count": 0,
        "source_gate_only_count": 0,
        "total_deficit_units": 1486,
        "maximum_normalized_deficit": 1.0,
    }
    assert report["demands"][0]["normalized_deficit"] == 1.0
    assert all(row["actionability"] == "eligible" for row in report["demands"])
    assert report["authority"] == {
        "source_counts_are_read_only": True,
        "source_authority_is_preserved": True,
        "synthetic_counts_close_real_deficits": False,
        "imported_signals_create_gold": False,
        "imported_signals_create_recipes": False,
        "inactive_ontology_grants_production_activation": False,
    }


def test_v1_missing_duplicate_and_source_hash_drift_fail_closed() -> None:
    source = _v1_matrix()
    missing = copy.deepcopy(source)
    missing["cells"].pop()
    with pytest.raises(RealDeficitSignalError, match="cells_incomplete"):
        _build(missing)
    duplicated = copy.deepcopy(source)
    duplicated["cells"][-1] = copy.deepcopy(duplicated["cells"][0])
    with pytest.raises(RealDeficitSignalError, match="duplicate_cell"):
        _build(duplicated)
    with pytest.raises(RealDeficitSignalError, match="source_hash_mismatch"):
        build_real_deficit_signal_report(
            source,
            source_id="real_coverage_snapshot",
            source_sha256="0" * 64,
            policy=load_deficit_adapter_policy(POLICY),
            vocabulary_report=_vocabulary(),
        )


def test_v2_import_remains_inactive_and_maximum_violation_is_not_acquisition() -> None:
    source = _v2_matrix()
    unreviewed = next(
        row
        for row in source["cells"]
        if row["label"] == "hair"
        and row["dimension"] == "review_state"
        and row["value"] == "unreviewed_for_v2"
    )
    unreviewed["approved_gold_count"] = 1
    unreviewed["deficit"] = 1
    report = _build(source, "real_v2_coverage_snapshot")
    assert report["source"]["production_activation_granted"] is False
    assert report["summary"]["eligible_count"] == 0
    assert report["summary"]["inactive_ontology_observation_count"] > 0
    assert report["summary"]["source_gate_only_count"] == 1
    maximum = next(row for row in report["demands"] if row["target_kind"] == "maximum")
    assert maximum["actionability"] == "source_gate_only"
    assert maximum["synthetic_recipe_mapping_required"] is True
    assert all(
        row["closed_axis_projection"][0]
        == {"axis_id": "ontology_version", "value": "body_parts_v2"}
        for row in report["demands"]
    )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda p: p["supported_sources"]["coverage_matrix_v1"].__setitem__(
                "target_per_cell", 7
            ),
            "sources_invalid",
        ),
        (
            lambda p: p["actionability"].__setitem__("maximum_constraint_violation", "eligible"),
            "actionability_invalid",
        ),
        (
            lambda p: p["authority"].__setitem__("synthetic_counts_close_real_deficits", True),
            "authority_invalid",
        ),
    ],
)
def test_policy_weakening_fails_closed(mutation, reason: str) -> None:
    policy = load_deficit_adapter_policy(POLICY)
    mutation(policy)
    with pytest.raises(RealDeficitSignalError, match=reason):
        validate_deficit_adapter_policy(policy)


def test_report_schema_hash_demand_semantics_and_publication_fail_closed(
    tmp_path: Path,
) -> None:
    report = _build(_v1_matrix())
    unknown = copy.deepcopy(report)
    unknown["unknown"] = True
    with pytest.raises(ArtifactValidationError, match="Additional properties"):
        validate_real_deficit_signal_report(unknown)
    tampered = copy.deepcopy(report)
    tampered["demands"][0]["deficit"] += 1
    with pytest.raises(RealDeficitSignalError, match="hash_invalid"):
        validate_real_deficit_signal_report(tampered)
    coherently_rehashed = copy.deepcopy(report)
    coherently_rehashed["demands"][0]["target"] = 9
    coherently_rehashed["demands"][0]["normalized_deficit"] = (
        coherently_rehashed["demands"][0]["deficit"] / 9
    )
    _rehash_demand(coherently_rehashed["demands"][0])
    _rehash_report(coherently_rehashed)
    with pytest.raises(RealDeficitSignalError, match="v1_coordinates_invalid"):
        validate_real_deficit_signal_report(coherently_rehashed)
    target, published = publish_real_deficit_signal_report(report, tmp_path / "reports")
    assert published is True
    assert publish_real_deficit_signal_report(report, tmp_path / "reports") == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RealDeficitSignalError, match="publication_conflict"):
        publish_real_deficit_signal_report(report, tmp_path / "reports")


def test_cli_imports_and_replays_real_deficits_without_local_paths(tmp_path: Path) -> None:
    matrix = tmp_path / "coverage.json"
    matrix.write_text(json.dumps(_v1_matrix(), indent=2) + "\n", encoding="utf-8")
    command = [
        "daz",
        "coverage",
        "import-deficits",
        "--matrix",
        str(matrix),
        "--source-id",
        "real_coverage_snapshot",
        "--policy",
        str(POLICY),
        "--vocabulary-report",
        str(VOCABULARY_REPORT),
        "--output",
        str(tmp_path / "reports"),
    ]
    runner = CliRunner()
    first = runner.invoke(main, command)
    assert first.exit_code == 0, first.output
    payload = json.loads(first.output)
    assert payload["reason"] == "daz_real_deficit_signals_imported"
    assert payload["data"]["summary"]["eligible_count"] == 138
    target = Path(payload["data"]["publication"]["path"])
    published = json.loads(target.read_text(encoding="utf-8"))
    assert str(tmp_path) not in json.dumps(published)
    replay = runner.invoke(main, command)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
