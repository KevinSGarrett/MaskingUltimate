from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.daz.render import load_instance_pass_policy
from maskfactory.daz.scenes import (
    PIndexAssignmentError,
    build_p_index_assignment,
    load_duo_recipe_policy,
    load_p_index_assignment_policy,
    publish_p_index_assignment,
    select_duo_recipe,
    validate_p_index_assignment,
    validate_p_index_assignment_policy,
)
from maskfactory.validation import ArtifactValidationError

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "daz" / "p_index_assignment.yaml"
DUO_POLICY_PATH = ROOT / "configs" / "daz" / "duo_recipe_selection.yaml"


def _selection() -> dict:
    return select_duo_recipe(
        load_duo_recipe_policy(DUO_POLICY_PATH),
        selection_seed=23,
        anatomy_family="MF",
        relationship_family="overlap_no_contact",
    )


def _observation(selection: dict, owners: list[dict] | None = None) -> dict:
    camera = {
        "projection": "perspective",
        "focal_length_mm": 65.0,
        "transform": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
    }
    return {
        "schema_version": "1.0.0",
        "scene_id": "daz_scene_p_index_fixture",
        "resolved_state_id": "dcrs_fixture_001",
        "resolved_state_sha256": "a" * 64,
        "scene_state_sha256": "b" * 64,
        "resolution": [20, 20],
        "crop": [0, 0, 20, 20],
        "final_camera": camera,
        "camera_readback": deepcopy(camera),
        "promotion_required": True,
        "framing_retry_attempt": 0,
        "construction_owners": owners
        or [
            {
                "slot_id": row["slot_id"],
                "construction_id": row["construction_id"],
                "source_instance_id": index + 1,
            }
            for index, row in enumerate(selection["slots"])
        ],
    }


def _write_map(
    path: Path, c0_id: int, c1_id: int, c0_pixels: int = 60, c1_pixels: int = 100
) -> None:
    raster = np.zeros((20, 20), dtype=np.uint16)
    flat = raster.reshape(-1)
    flat[:c0_pixels] = c0_id
    flat[200 : 200 + c1_pixels] = c1_id
    Image.fromarray(raster).save(path, format="PNG")


def test_policy_is_closed_and_matches_live_instance_prominence() -> None:
    policy = load_p_index_assignment_policy(POLICY_PATH)
    instance_policy = load_instance_pass_policy(ROOT / "configs" / "daz" / "instance_pass.yaml")
    validate_p_index_assignment_policy(policy)
    assert policy["minimum_visible_area_fraction"] == 0.04
    assert (
        policy["minimum_visible_area_fraction"]
        == instance_policy["namespace"]["minimum_visible_area_fraction"]
    )
    assert policy["deterministic_tie_break"] == [
        "prominence_desc",
        "visible_area_desc",
        "construction_id_asc",
    ]
    invalid = deepcopy(policy)
    invalid["minimum_visible_area_fraction"] = 0.03
    with pytest.raises(PIndexAssignmentError, match="policy_identity_invalid"):
        validate_p_index_assignment_policy(invalid)


def test_final_camera_raster_assigns_prominence_not_construction_order(tmp_path: Path) -> None:
    selection = _selection()
    raster = tmp_path / "construction.png"
    _write_map(raster, 1, 2)
    assignment = build_p_index_assignment(
        selection,
        _observation(selection),
        raster,
        load_p_index_assignment_policy(POLICY_PATH),
    )
    assert [(row["construction_id"], row["p_index"]) for row in assignment["mapping"]] == [
        ("c1", "p0"),
        ("c0", "p1"),
    ]
    assert assignment["persons"][0]["visible_pixels"] == 60
    assert assignment["persons"][1]["visible_pixels"] == 100
    assert assignment["final_frame"]["camera_readback_matches"] is True
    assert assignment["summary"] == {
        "accepted": True,
        "person_count": 2,
        "mapping_count": 2,
        "all_declared_people_retained": True,
    }
    validate_p_index_assignment(assignment)


def test_construction_order_and_source_id_permutations_preserve_result(tmp_path: Path) -> None:
    selection = _selection()
    first_raster = tmp_path / "first.png"
    second_raster = tmp_path / "second.png"
    _write_map(first_raster, 1, 2)
    _write_map(second_raster, 91, 17)
    first = build_p_index_assignment(
        selection,
        _observation(selection),
        first_raster,
        load_p_index_assignment_policy(POLICY_PATH),
    )
    owners = [
        {"slot_id": "b", "construction_id": "c1", "source_instance_id": 17},
        {"slot_id": "a", "construction_id": "c0", "source_instance_id": 91},
    ]
    second = build_p_index_assignment(
        selection,
        _observation(selection, owners),
        second_raster,
        load_p_index_assignment_policy(POLICY_PATH),
    )
    assert second["mapping"] == first["mapping"]
    assert [
        (row["construction_id"], row["visible_pixels"], row["prominence_score"])
        for row in second["persons"]
    ] == [
        (row["construction_id"], row["visible_pixels"], row["prominence_score"])
        for row in first["persons"]
    ]


def test_equal_prominence_uses_construction_id_tie_break(tmp_path: Path) -> None:
    selection = _selection()
    raster = tmp_path / "tie.png"
    _write_map(raster, 1, 2, c0_pixels=40, c1_pixels=40)
    assignment = build_p_index_assignment(
        selection,
        _observation(selection),
        raster,
        load_p_index_assignment_policy(POLICY_PATH),
    )
    assert [row["construction_id"] for row in assignment["mapping"]] == ["c0", "c1"]


def test_below_floor_never_emits_partial_mapping_and_uses_bounded_retry(tmp_path: Path) -> None:
    selection = _selection()
    raster = tmp_path / "below.png"
    _write_map(raster, 1, 2, c0_pixels=15, c1_pixels=100)
    observation = _observation(selection)
    retry = build_p_index_assignment(
        selection,
        observation,
        raster,
        load_p_index_assignment_policy(POLICY_PATH),
    )
    assert retry["promotion"]["disposition"] == "retry_framing"
    assert retry["promotion"]["below_minimum_construction_ids"] == ["c0"]
    assert retry["mapping"] == []
    assert all(row["p_index"] is None for row in retry["persons"])
    exhausted = deepcopy(observation)
    exhausted["framing_retry_attempt"] = 2
    rejected = build_p_index_assignment(
        selection,
        exhausted,
        raster,
        load_p_index_assignment_policy(POLICY_PATH),
    )
    assert rejected["promotion"]["disposition"] == "reject_resample"
    assert rejected["mapping"] == []


def test_all_background_map_yields_honest_retry_without_partial_people(tmp_path: Path) -> None:
    selection = _selection()
    raster = tmp_path / "empty.png"
    Image.fromarray(np.zeros((20, 20), dtype=np.uint16)).save(raster, format="PNG")
    assignment = build_p_index_assignment(
        selection,
        _observation(selection),
        raster,
        load_p_index_assignment_policy(POLICY_PATH),
    )
    assert assignment["final_frame"]["observed_source_instance_ids"] == []
    assert assignment["promotion"]["below_minimum_construction_ids"] == ["c0", "c1"]
    assert assignment["promotion"]["disposition"] == "retry_framing"
    assert assignment["mapping"] == []
    validate_p_index_assignment(assignment)


def test_camera_unknown_ids_resolution_and_owner_contract_fail_closed(tmp_path: Path) -> None:
    selection = _selection()
    policy = load_p_index_assignment_policy(POLICY_PATH)
    raster = tmp_path / "construction.png"
    _write_map(raster, 1, 2)
    mismatch = _observation(selection)
    mismatch["camera_readback"]["focal_length_mm"] = 64.0
    with pytest.raises(PIndexAssignmentError, match="camera_readback_mismatch"):
        build_p_index_assignment(selection, mismatch, raster, policy)
    unknown = np.zeros((20, 20), dtype=np.uint16)
    unknown[:4, :4] = 99
    Image.fromarray(unknown).save(raster, format="PNG")
    with pytest.raises(PIndexAssignmentError, match="unknown_construction_ids"):
        build_p_index_assignment(selection, _observation(selection), raster, policy)
    wrong_size = np.zeros((19, 20), dtype=np.uint16)
    Image.fromarray(wrong_size).save(raster, format="PNG")
    with pytest.raises(PIndexAssignmentError, match="resolution_mismatch"):
        build_p_index_assignment(selection, _observation(selection), raster, policy)
    invalid_owners = _observation(selection)
    invalid_owners["construction_owners"][0]["construction_id"] = "c1"
    with pytest.raises(PIndexAssignmentError, match="construction_owners_invalid"):
        build_p_index_assignment(selection, invalid_owners, raster, policy)


def test_schema_hash_and_atomic_publication_fail_closed(tmp_path: Path) -> None:
    selection = _selection()
    raster = tmp_path / "construction.png"
    _write_map(raster, 1, 2)
    assignment = build_p_index_assignment(
        selection,
        _observation(selection),
        raster,
        load_p_index_assignment_policy(POLICY_PATH),
    )
    tampered = deepcopy(assignment)
    tampered["undeclared"] = True
    with pytest.raises(ArtifactValidationError, match="Additional properties"):
        validate_p_index_assignment(tampered)
    tampered = deepcopy(assignment)
    tampered["mapping"].reverse()
    with pytest.raises(PIndexAssignmentError, match="document_hash_invalid"):
        validate_p_index_assignment(tampered)
    published, created = publish_p_index_assignment(assignment, tmp_path / "published")
    assert created is True
    assert publish_p_index_assignment(assignment, tmp_path / "published") == (
        published,
        False,
    )
    published.write_text("{}\n", encoding="utf-8")
    with pytest.raises(PIndexAssignmentError, match="publication_conflict"):
        publish_p_index_assignment(assignment, tmp_path / "published")


def test_cli_assigns_and_replays_immutable_artifact(tmp_path: Path) -> None:
    selection = _selection()
    observation = _observation(selection)
    selection_path = tmp_path / "selection.json"
    observation_path = tmp_path / "observation.json"
    raster = tmp_path / "construction.png"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    observation_path.write_text(json.dumps(observation), encoding="utf-8")
    _write_map(raster, 1, 2)
    output = tmp_path / "assignments"
    arguments = [
        "daz",
        "recipes",
        "assign-p-indices",
        "--selection",
        str(selection_path),
        "--observation",
        str(observation_path),
        "--construction-map",
        str(raster),
        "--policy",
        str(POLICY_PATH),
        "--output",
        str(output),
    ]
    runner = CliRunner()
    first = runner.invoke(main, arguments)
    assert first.exit_code == 0, first.output
    result = json.loads(first.output)
    assert result["reason"] == "daz_p_indices_assigned"
    assert result["data"]["publication"]["published"] is True
    assert result["data"]["mapping"][0]["construction_id"] == "c1"
    replay = runner.invoke(main, arguments)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
