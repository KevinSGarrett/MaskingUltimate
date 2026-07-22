from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from maskfactory.nude_training_role_gate import (
    NudeTrainingRoleError,
    build_nude_training_role_population,
    require_nude_pixel_training_role,
)


def _candidate() -> dict[str, object]:
    return {
        "sample_id": "nude_fixture",
        "source_role": "polygon_external_supervision",
        "assigned_partition": "train",
        "source_sha256": "a" * 64,
        "mask_sha256": "b" * 64,
        "raw_label": "female_breast",
        "candidate_label": "breast_region",
        "candidate_kind": "coarse_anatomy",
    }


def test_polygon_train_role_is_only_a_non_authoritative_admission_prerequisite() -> None:
    result = require_nude_pixel_training_role(_candidate())
    assert result["pixel_training_role_eligible"] is True
    assert result["training_authority_granted"] is False
    assert "strict_per_record_visual_review" in result["remaining_required_gates"]


@pytest.mark.parametrize(
    "source_role",
    (
        "bbox_prompt_supervision",
        "bbox_prompt_and_action_tag_supervision",
        "reference_and_tournament_input",
        "bbox_evaluation_only",
    ),
)
def test_boxes_actions_references_and_holdout_roles_cannot_enter_pixel_training(
    source_role: str,
) -> None:
    candidate = _candidate()
    candidate["source_role"] = source_role
    with pytest.raises(NudeTrainingRoleError, match="non_pixel_source_role"):
        require_nude_pixel_training_role(candidate)


@pytest.mark.parametrize("partition", ("validation", "test", "holdout"))
def test_non_training_partitions_cannot_enter_training(partition: str) -> None:
    candidate = _candidate()
    candidate["assigned_partition"] = partition
    with pytest.raises(NudeTrainingRoleError, match="non_training_partition"):
        require_nude_pixel_training_role(candidate)


@pytest.mark.parametrize(
    "kind",
    ("context_object", "context_garment", "context_scene", "context_state", "action_scene"),
)
def test_context_and_action_semantics_cannot_become_pixel_anatomy(kind: str) -> None:
    candidate = _candidate()
    candidate["candidate_kind"] = kind
    with pytest.raises(NudeTrainingRoleError, match="non_pixel_mapping_kind"):
        require_nude_pixel_training_role(candidate)


def test_coarse_source_cannot_invent_fine_anatomy_at_export() -> None:
    candidate = deepcopy(_candidate())
    candidate["candidate_label"] = "left_nipple"
    with pytest.raises(NudeTrainingRoleError, match="coarse_source_invented_fine_label"):
        require_nude_pixel_training_role(candidate)


@pytest.mark.parametrize("field", ("source_sha256", "mask_sha256"))
def test_unbound_source_or_mask_bytes_fail_closed(field: str) -> None:
    candidate = _candidate()
    candidate[field] = "not-a-sha"
    with pytest.raises(NudeTrainingRoleError, match=f"{field}_invalid"):
        require_nude_pixel_training_role(candidate)


def test_population_builder_exports_only_train_polygon_hard_qc_candidates(tmp_path: Path) -> None:
    rows = []
    for sample, role, partition, outcome in (
        ("eligible", "polygon_external_supervision", "train", "hard_qc_pass_candidate"),
        ("validation", "polygon_external_supervision", "validation", "hard_qc_pass_candidate"),
        ("quarantined", "polygon_external_supervision", "train", "quarantined_input"),
    ):
        rows.append(
            {
                "sample_id": sample,
                "dataset_id": "fixture",
                "source_role": role,
                "assigned_partition": partition,
                "source_sha256": "a" * 64,
                "split_group_id": f"group-{sample}",
                "outcome": outcome,
                "masks": [
                    {
                        "mask_sha256": "b" * 64,
                        "raw_label": "breast",
                        "candidate_label": "breast_region",
                        "candidate_kind": "coarse_anatomy",
                    }
                ],
            }
        )
    source = tmp_path / "records.jsonl"
    source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    summary = build_nude_training_role_population(source, tmp_path / "output")
    assert summary["input_record_count"] == 3
    assert summary["input_mask_count"] == 3
    assert summary["role_eligible_mask_count"] == 1
    assert summary["training_authority_granted"] is False
