from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from maskfactory.daz.scenes.engineering_fixtures import (
    MIN_FIXTURES,
    EngineeringFixtureError,
    build_engineering_fixture_set,
    publish_engineering_fixture_set,
    validate_engineering_fixture_set,
)
from maskfactory.validation import validate_document


def test_build_engineering_fixture_set_is_deterministic_and_schema_valid() -> None:
    first = build_engineering_fixture_set()
    second = build_engineering_fixture_set()
    assert first == second
    assert validate_document(first, "daz_engineering_fixture_set") == ()
    assert first["fixture_count"] == MIN_FIXTURES
    assert first["rendered"] is False
    assert first["accepted"] is False
    assert first["training_eligible"] is False
    assert first["mapping_authority"] is False
    assert first["live_daz_execution"] is False
    assert first["person_count"] == 1
    assert len(first["fixtures"]) == MIN_FIXTURES
    assert first["fixtures"][0]["scene_id"] == "daz_scene_eng_000"
    assert len({item["recipe_sha256"] for item in first["fixtures"]}) == MIN_FIXTURES


def test_fixture_count_bounds_and_acceptance_claims_fail_closed() -> None:
    with pytest.raises(EngineeringFixtureError, match="fixture_count_out_of_range"):
        build_engineering_fixture_set(fixture_count=23)
    with pytest.raises(EngineeringFixtureError, match="fixture_count_out_of_range"):
        build_engineering_fixture_set(fixture_count=101)

    document = build_engineering_fixture_set()
    tampered = copy.deepcopy(document)
    tampered["accepted"] = True
    with pytest.raises(EngineeringFixtureError, match="fixture_set_schema_invalid"):
        validate_engineering_fixture_set(tampered)

    training = copy.deepcopy(document)
    training["fixtures"][0]["training_eligible"] = True
    # digest/schema will fail; either is fail-closed
    with pytest.raises(EngineeringFixtureError):
        validate_engineering_fixture_set(training)


def test_recipe_hash_drift_and_duplicate_scene_fail_closed() -> None:
    document = build_engineering_fixture_set()
    drifted = copy.deepcopy(document)
    drifted["fixtures"][0]["recipe_stub"]["coverage"]["pose_family"] = "tampered"
    with pytest.raises(EngineeringFixtureError, match="recipe_hash_drift|set_digest"):
        validate_engineering_fixture_set(drifted)

    duplicated = copy.deepcopy(document)
    duplicated["fixtures"][1]["scene_id"] = duplicated["fixtures"][0]["scene_id"]
    duplicated["fixtures"][1]["recipe_stub"]["scene_id"] = duplicated["fixtures"][0][
        "scene_id"
    ]
    with pytest.raises(EngineeringFixtureError):
        validate_engineering_fixture_set(duplicated)


def test_publish_engineering_fixture_set_immutable_and_idempotent(tmp_path: Path) -> None:
    document = build_engineering_fixture_set(fixture_count=24)
    target, published = publish_engineering_fixture_set(document, tmp_path)
    assert published is True
    assert json.loads(target.read_text(encoding="utf-8")) == document
    assert publish_engineering_fixture_set(document, tmp_path) == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(EngineeringFixtureError, match="immutable_conflict"):
        publish_engineering_fixture_set(document, tmp_path)
