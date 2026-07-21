from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.daz.scenes.engineering_fixtures import (
    COVERAGE_VALUE_SETS,
    MIN_FIXTURES,
    POSE_FAMILIES,
    SCHEMA_VERSION,
    EngineeringFixtureError,
    build_engineering_fixture_set,
    publish_engineering_fixture_set,
    validate_engineering_fixture_set,
)
from maskfactory.daz.scenes.recipe import REQUIRED_RANDOM_STREAMS, validate_resolved_scene_recipe
from maskfactory.validation import validate_document


def test_build_engineering_fixture_set_is_deterministic_and_schema_valid() -> None:
    first = build_engineering_fixture_set()
    second = build_engineering_fixture_set()
    assert first == second
    assert validate_document(first, "daz_engineering_fixture_set") == ()
    assert first["schema_version"] == SCHEMA_VERSION
    assert first["fixture_count"] == MIN_FIXTURES
    assert first["curriculum_stage"] == "engineering"
    assert first["rendered"] is False
    assert first["accepted"] is False
    assert first["training_eligible"] is False
    assert first["mapping_authority"] is False
    assert first["live_daz_execution"] is False
    assert first["live_qualified_assets"] is False
    assert first["person_count"] == 1
    assert first["stream_contract"] == list(REQUIRED_RANDOM_STREAMS)
    assert first["coverage_summary"]["full_marginal_coverage"] is True
    assert len(first["fixtures"]) == MIN_FIXTURES
    assert first["fixtures"][0]["scene_id"] == "daz_scene_eng_000"
    assert len({item["recipe_sha256"] for item in first["fixtures"]}) == MIN_FIXTURES
    assert len({item["resolved_recipe_sha256"] for item in first["fixtures"]}) == MIN_FIXTURES


def test_coverage_uses_policy_vocab_and_full_marginal_coverage() -> None:
    document = build_engineering_fixture_set()
    for dimension, allowed in COVERAGE_VALUE_SETS.items():
        observed = {item["coverage"][dimension] for item in document["fixtures"]}
        assert observed == set(allowed)
    assert document["fixtures"][0]["coverage"]["pose_family"] == POSE_FAMILIES[0]
    streams = document["fixtures"][0]["recipe_stub"]["named_random_streams"]
    assert set(streams.keys()) == set(REQUIRED_RANDOM_STREAMS)


def test_each_fixture_embeds_sealable_synthetic_resolved_recipe() -> None:
    document = build_engineering_fixture_set()
    for fixture in document["fixtures"]:
        report = validate_resolved_scene_recipe(fixture["resolved_recipe"])
        assert report["valid"] is True
        assert report["recipe_sha256"] == fixture["resolved_recipe_sha256"]
        assert fixture["resolved_recipe"]["render_profile_id"] == (
            "engineering_unrendered_static_v1"
        )
        assert fixture["live_qualified_assets"] is False


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
    with pytest.raises(EngineeringFixtureError):
        validate_engineering_fixture_set(training)

    live_assets = copy.deepcopy(document)
    live_assets["live_qualified_assets"] = True
    with pytest.raises(EngineeringFixtureError, match="fixture_set_schema_invalid"):
        validate_engineering_fixture_set(live_assets)


def test_recipe_hash_drift_and_resolved_recipe_tamper_fail_closed() -> None:
    document = build_engineering_fixture_set()
    drifted = copy.deepcopy(document)
    drifted["fixtures"][0]["recipe_stub"]["coverage"]["pose_family"] = "locomotion"
    with pytest.raises(EngineeringFixtureError, match="recipe_hash_drift|set_digest"):
        validate_engineering_fixture_set(drifted)

    resolved_tamper = copy.deepcopy(document)
    resolved_tamper["fixtures"][0]["resolved_recipe"]["camera"]["focal_length_mm"] = 99.0
    with pytest.raises(EngineeringFixtureError, match="resolved_recipe"):
        validate_engineering_fixture_set(resolved_tamper)

    duplicated = copy.deepcopy(document)
    duplicated["fixtures"][1]["scene_id"] = duplicated["fixtures"][0]["scene_id"]
    duplicated["fixtures"][1]["recipe_stub"]["scene_id"] = duplicated["fixtures"][0]["scene_id"]
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


def test_engineering_fixture_set_cli_build_validate_replay(tmp_path: Path) -> None:
    output = tmp_path / "fixtures"
    runner = CliRunner()
    first = runner.invoke(
        main,
        [
            "daz",
            "recipes",
            "build-engineering-fixture-set",
            "--fixture-count",
            "24",
            "--master-seed",
            "20260719",
            "--output",
            str(output),
        ],
    )
    assert first.exit_code == 0, first.output
    first_envelope = json.loads(first.output)
    assert first_envelope["reason"] == "daz_engineering_fixture_set_built"
    assert first_envelope["data"]["publication"]["published"] is True
    assert first_envelope["data"]["accepted"] is False
    assert first_envelope["data"]["live_qualified_assets"] is False
    path = first_envelope["data"]["publication"]["path"]

    second = runner.invoke(
        main,
        [
            "daz",
            "recipes",
            "build-engineering-fixture-set",
            "--fixture-count",
            "24",
            "--master-seed",
            "20260719",
            "--output",
            str(output),
        ],
    )
    assert second.exit_code == 0, second.output
    assert json.loads(second.output)["data"]["publication"]["published"] is False

    validated = runner.invoke(main, ["daz", "recipes", "validate-engineering-fixture-set", path])
    assert validated.exit_code == 0, validated.output
    payload = json.loads(validated.output)
    assert payload["reason"] == "daz_engineering_fixture_set_valid"
    assert payload["data"]["full_marginal_coverage"] is True
    assert payload["data"]["schema_version"] == SCHEMA_VERSION
