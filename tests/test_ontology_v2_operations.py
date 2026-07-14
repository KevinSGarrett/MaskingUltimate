import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.datasets.coverage_v2 import (
    DEFAULT_POLICY,
    FAILURE_ACQUISITION_CATEGORIES,
    OCCLUSION_CONTEXTS,
    OntologyV2OperationsError,
    acquisition_action_for_v2_failure,
    build_v2_coverage_matrix,
    coverage_v2_deficit_report,
    load_v2_operations_policy,
    write_v2_coverage_matrix,
)
from maskfactory.models.ontology_contract import V2_PART_CLASS_NAMES
from maskfactory.qa.failure_mining import (
    append_failure,
    make_failure_record,
    write_acquisition_plan,
)
from maskfactory.vlm.text import cluster_failure_reasons


def _approved_package() -> dict:
    return {
        "image_id": "img_a3f9c2e17b04",
        "workflow_status": "approved_gold",
        "reviewed_ontology_version": "body_parts_v2",
        "person": {"view": "front", "pose_tags": ["arms_down"]},
        "parts": {
            label: {"visibility": "not_visible" if label == "background" else "visible"}
            for label in V2_PART_CLASS_NAMES
        },
        "coverage_contexts": {label: ["none_visible"] for label in V2_PART_CLASS_NAMES[1:]},
    }


def test_v2_policy_covers_every_class_dimension_and_failure_action(tmp_path: Path) -> None:
    policy = load_v2_operations_policy()
    assert policy["coverage"]["foreground_class_ids"] == [1, 64]
    assert policy["coverage"]["excluded_class_ids"] == {
        0: "background_is_not_a_body_part_acquisition_target"
    }
    assert set(policy["coverage"]["dimensions"]) == {
        "review_state",
        "view",
        "pose",
        "occlusion_context",
    }
    assert set(policy["coverage"]["dimensions"]["occlusion_context"]) == set(OCCLUSION_CONTEXTS)
    assert set(policy["failure_acquisition"]) == set(FAILURE_ACQUISITION_CATEGORIES)

    drifted = deepcopy(policy)
    drifted["coverage"]["dimensions"]["review_state"]["unreviewed_for_v2"] = 1
    path = tmp_path / "drifted.yaml"
    path.write_text(yaml.safe_dump(drifted, sort_keys=False), encoding="utf-8")
    with pytest.raises(OntologyV2OperationsError, match="target must remain zero"):
        load_v2_operations_policy(path)


def test_v2_matrix_is_exact_per_class_state_view_pose_and_occlusion(tmp_path: Path) -> None:
    matrix = build_v2_coverage_matrix(
        [_approved_package()], generated_at=datetime(2026, 7, 14, tzinfo=UTC)
    )
    assert matrix["approved_package_count"] == 1
    assert matrix["foreground_class_count"] == 64
    assert len(matrix["cells"]) == 64 * (9 + 6 + 7 + 8)
    assert len(matrix["new_class_positive_targets"]) == 9
    assert next(
        row for row in matrix["new_class_positive_targets"] if row["label"] == "glans_penis"
    ) == {
        "label": "glans_penis",
        "clear_positive_count": 1,
        "minimum_required": 50,
        "target": 100,
        "minimum_deficit": 49,
        "target_deficit": 99,
    }
    by_key = {(cell["label"], cell["dimension"], cell["value"]): cell for cell in matrix["cells"]}
    assert by_key[("glans_penis", "review_state", "visible")]["approved_gold_count"] == 1
    assert by_key[("glans_penis", "view", "front")]["approved_gold_count"] == 1
    assert by_key[("glans_penis", "pose", "arms_down")]["approved_gold_count"] == 1
    assert by_key[("glans_penis", "occlusion_context", "none_visible")]["approved_gold_count"] == 1
    assert by_key[("glans_penis", "review_state", "unreviewed_for_v2")] == {
        "label": "glans_penis",
        "dimension": "review_state",
        "value": "unreviewed_for_v2",
        "approved_gold_count": 0,
        "target": 0,
        "deficit": 0,
        "target_kind": "maximum",
    }
    output = write_v2_coverage_matrix(tmp_path / "coverage_v2.json", matrix)
    report = coverage_v2_deficit_report(json.loads(output.read_text(encoding="utf-8")))
    assert report["production_activation_granted"] is False
    assert report["deficit_cell_count"] > 0

    invocation = CliRunner().invoke(main, ["coverage", "v2-report", "--matrix", str(output)])
    assert invocation.exit_code == 0, invocation.output
    assert json.loads(invocation.output)["approved_package_count"] == 1

    drifted = deepcopy(matrix)
    drifted["cells"][0]["target"] += 1
    with pytest.raises(OntologyV2OperationsError, match="target/deficit drift"):
        coverage_v2_deficit_report(drifted)
    duplicated = deepcopy(matrix)
    duplicated["cells"][0] = deepcopy(duplicated["cells"][1])
    with pytest.raises(OntologyV2OperationsError, match="duplicate"):
        coverage_v2_deficit_report(duplicated)


def test_v2_matrix_refuses_unreviewed_and_inconsistent_occlusion_contexts() -> None:
    unreviewed = _approved_package()
    unreviewed["parts"]["left_areola"]["visibility"] = "unreviewed_for_v2"
    with pytest.raises(OntologyV2OperationsError, match="state is unsafe"):
        build_v2_coverage_matrix([unreviewed])

    clothed = _approved_package()
    clothed["parts"]["left_areola"]["visibility"] = "occluded_by_clothing"
    with pytest.raises(OntologyV2OperationsError, match="requires only clothing"):
        build_v2_coverage_matrix([clothed])
    clothed["coverage_contexts"]["left_areola"] = ["clothing"]
    assert build_v2_coverage_matrix([clothed])["approved_package_count"] == 1


def test_v2_failure_reasons_return_canonical_fail_closed_acquisition_actions(
    tmp_path: Path,
) -> None:
    action = acquisition_action_for_v2_failure("v2_clothing_false_positive", label="left_areola")
    assert action["category"] == "clothing"
    assert action["action"] == "collect_reviewed_clothed_negatives"
    assert action["required_review_states"] == ["occluded_by_clothing"]
    assert action["required_occlusion_contexts"] == ["clothing"]
    assert action["destination"] == "hard_case_holdout"
    assert action["human_review_required"] is True
    assert action["fabricated_positive_allowed"] is False
    assert action["production_activation_granted"] is False
    with pytest.raises(OntologyV2OperationsError, match="not canonical"):
        acquisition_action_for_v2_failure("v2_lr_swap", label="penis head")
    with pytest.raises(OntologyV2OperationsError, match="unknown"):
        acquisition_action_for_v2_failure("boundary_problem", label="left_areola")

    invocation = CliRunner().invoke(
        main,
        [
            "coverage",
            "v2-acquisition",
            "--reason",
            "v2_lr_swap",
            "--label",
            "left_scrotal_region",
        ],
    )
    assert invocation.exit_code == 0, invocation.output
    assert json.loads(invocation.output)["action"] == "collect_character_side_views"

    record = make_failure_record(
        image_id="img_a3f9c2e17b04",
        body_part="left_areola",
        reason="v2_clothing_false_positive",
        pose="front",
        model="bodypart_v2_challenger",
        correction="collect_reviewed_clothed_negatives",
        class_error_rate=1.0,
        coverage_deficit=1.0,
        use_weight=1.0,
        event_time=datetime(2026, 7, 14, tzinfo=UTC),
        now=datetime(2026, 7, 14, tzinfo=UTC),
    )
    queue = tmp_path / "failure_queue.jsonl"
    append_failure(queue, record)
    assert json.loads(queue.read_text(encoding="utf-8"))["failure_reason"] == (
        "v2_clothing_false_positive"
    )
    plan = write_acquisition_plan(
        [record],
        output_dir=tmp_path,
        clusterer=lambda reasons: {reason: "clothing_boundary" for reason in reasons},
        report_date="2026-07-14",
    ).read_text(encoding="utf-8")
    assert "collect_reviewed_clothed_negatives" in plan
    assert "occluded_by_clothing" in plan
    assert "hard_case_holdout" in plan
    assert "never fabricate hidden positives" in plan


def test_non_gold_records_never_inflate_v2_coverage() -> None:
    draft = _approved_package()
    draft["workflow_status"] = "in_review"
    matrix = build_v2_coverage_matrix([draft])
    assert matrix["approved_package_count"] == 0
    assert all(cell["approved_gold_count"] == 0 for cell in matrix["cells"])
    assert matrix["policy_sha256"] == hashlib.sha256(DEFAULT_POLICY.read_bytes()).hexdigest()


def test_v2_coverage_and_failure_schemas_bind_exact_canonical_vocabularies() -> None:
    coverage_schema = json.loads(
        Path("src/maskfactory/schemas/coverage_matrix_v2.schema.json").read_text(encoding="utf-8")
    )
    assert coverage_schema["$defs"]["label"]["enum"] == list(V2_PART_CLASS_NAMES[1:])
    assert coverage_schema["$defs"]["newClassLabel"]["enum"] == list(V2_PART_CLASS_NAMES[56:])
    failure_schema = json.loads(
        Path("src/maskfactory/schemas/failure_queue.schema.json").read_text(encoding="utf-8")
    )
    reasons = set(failure_schema["properties"]["failure_reason"]["enum"])
    assert set(FAILURE_ACQUISITION_CATEGORIES) <= reasons


def test_local_text_clustering_accepts_only_governed_v2_themes_and_targets(
    tmp_path: Path,
) -> None:
    class Client:
        def generate(self, **_kwargs) -> str:
            return json.dumps(
                {
                    "clusters": {"v2_clothing_false_positive": "anatomy_clothing_negative"},
                    "coverage_targets": ["occluded_by_clothing", "clothing"],
                    "weekly_summary": "Acquire reviewed clothed negatives.",
                }
            )

    mapping = cluster_failure_reasons(
        ("v2_clothing_false_positive",),
        client=Client(),
        model="fixture",
        prompt_version="failure-cluster-v2-doc18",
        output_path=tmp_path / "cluster.json",
    )
    assert mapping == {"v2_clothing_false_positive": "anatomy_clothing_negative"}
    evidence = json.loads((tmp_path / "cluster.json").read_text(encoding="utf-8"))
    assert evidence["coverage_targets"] == ["occluded_by_clothing", "clothing"]
