from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.daz.scenes import (
    DuoRecipeSelectionError,
    load_duo_recipe_policy,
    publish_duo_recipe_selection,
    select_duo_recipe,
    validate_duo_recipe_policy,
    validate_duo_recipe_selection,
)
from maskfactory.validation import ArtifactValidationError

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs" / "daz" / "duo_recipe_selection.yaml"
ANATOMY = ("MM", "MF", "FF")
RELATIONSHIPS = ("no_contact", "overlap_no_contact", "contact_support")


@pytest.mark.parametrize("anatomy_family", ANATOMY)
@pytest.mark.parametrize("relationship_family", RELATIONSHIPS)
def test_complete_duo_matrix_is_deterministic_and_defers_p_indices(
    anatomy_family: str, relationship_family: str
) -> None:
    policy = load_duo_recipe_policy(POLICY)
    first = select_duo_recipe(
        policy,
        selection_seed=17,
        anatomy_family=anatomy_family,
        relationship_family=relationship_family,
    )
    replay = select_duo_recipe(policy, **first["request"])
    assert replay == first
    assert [row["construction_id"] for row in first["slots"]] == ["c0", "c1"]
    assert first["evidence_requirements"]["slot_names_are_not_p_indices"] is True
    assert first["evidence_requirements"]["contact_not_yet_claimed"] is True
    assert first["evidence_requirements"]["contact_solver_required"] == (
        relationship_family == "contact_support"
    )
    validate_duo_recipe_selection(first, policy)


def test_policy_requires_all_three_relationship_families() -> None:
    policy = load_duo_recipe_policy(POLICY)
    invalid = deepcopy(policy)
    invalid["templates"].pop()
    with pytest.raises(DuoRecipeSelectionError, match="matrix_incomplete"):
        validate_duo_recipe_policy(invalid)


def test_no_contact_overlap_and_contact_constraints_fail_closed() -> None:
    policy = load_duo_recipe_policy(POLICY)
    invalid = deepcopy(policy)
    invalid["templates"][0]["slots"]["b"]["root_transform"]["translation_cm"] = [0, 0, 0]
    with pytest.raises(DuoRecipeSelectionError, match="no_contact_invalid"):
        validate_duo_recipe_policy(invalid)
    invalid = deepcopy(policy)
    invalid["templates"][1]["slots"]["b"]["root_transform"]["translation_cm"][2] = 24
    with pytest.raises(DuoRecipeSelectionError, match="overlap_invalid"):
        validate_duo_recipe_policy(invalid)
    invalid = deepcopy(policy)
    invalid["templates"][2]["relationship"]["a_site"] = "left_hand"
    with pytest.raises(DuoRecipeSelectionError, match="contact_invalid"):
        validate_duo_recipe_policy(invalid)


def test_selection_tamper_and_policy_activation_weakening_reject() -> None:
    policy = load_duo_recipe_policy(POLICY)
    selection = select_duo_recipe(
        policy, selection_seed=2, anatomy_family="MF", relationship_family="contact_support"
    )
    tampered = deepcopy(selection)
    tampered["slots"][0]["anatomy_configuration"] = (
        "adult_male"
        if selection["slots"][0]["anatomy_configuration"] == "adult_female"
        else "adult_female"
    )
    with pytest.raises(DuoRecipeSelectionError, match="replay_mismatch"):
        validate_duo_recipe_selection(tampered, policy)
    invalid = deepcopy(policy)
    invalid["contact"]["solver_activation"] = "active"
    with pytest.raises(DuoRecipeSelectionError, match="contact_policy_invalid"):
        validate_duo_recipe_policy(invalid)


def test_mixed_anatomy_occupies_both_slots_without_assigning_p_indices() -> None:
    policy = load_duo_recipe_policy(POLICY)
    orders = {
        tuple(row["anatomy_configuration"] for row in selection["slots"])
        for seed in range(32)
        for selection in [
            select_duo_recipe(
                policy,
                selection_seed=seed,
                anatomy_family="MF",
                relationship_family="overlap_no_contact",
            )
        ]
    }
    assert orders == {("adult_male", "adult_female"), ("adult_female", "adult_male")}


def test_schema_is_closed_and_publication_is_idempotent(tmp_path: Path) -> None:
    policy = load_duo_recipe_policy(POLICY)
    selection = select_duo_recipe(
        policy, selection_seed=9, anatomy_family="FF", relationship_family="no_contact"
    )
    tampered = deepcopy(selection)
    tampered["relationship"]["undeclared"] = True
    with pytest.raises(ArtifactValidationError, match="Additional properties"):
        validate_duo_recipe_selection(tampered, policy)
    path, created = publish_duo_recipe_selection(selection, policy, tmp_path)
    assert created is True
    assert publish_duo_recipe_selection(selection, policy, tmp_path) == (path, False)
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(DuoRecipeSelectionError, match="publication_conflict"):
        publish_duo_recipe_selection(selection, policy, tmp_path)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("maximum_translation_cm", float("nan"), "transform_bounds_invalid"),
        ("minimum_scale", 1.1, "transform_bounds_invalid"),
        ("maximum_scale", 1.2, "transform_bounds_invalid"),
    ],
)
def test_nonfinite_or_inverted_numeric_policy_rejects(
    field: str, value: float, reason: str
) -> None:
    policy = load_duo_recipe_policy(POLICY)
    invalid = deepcopy(policy)
    invalid["root_transform_bounds"][field] = value
    with pytest.raises(DuoRecipeSelectionError, match=reason):
        validate_duo_recipe_policy(invalid)


def test_cli_selects_and_replays_immutable_duo_recipe(tmp_path: Path) -> None:
    runner = CliRunner()
    arguments = [
        "daz",
        "recipes",
        "select-duo",
        "--selection-seed",
        "41",
        "--anatomy-family",
        "MF",
        "--relationship-family",
        "contact_support",
        "--policy",
        str(POLICY),
        "--output",
        str(tmp_path),
    ]
    first = runner.invoke(main, arguments)
    assert first.exit_code == 0, first.output
    document = json.loads(first.output)
    assert document["reason"] == "daz_duo_recipe_selected"
    assert document["data"]["publication"]["published"] is True
    assert document["data"]["evidence_requirements"]["contact_not_yet_claimed"] is True
    replay = runner.invoke(main, arguments)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
