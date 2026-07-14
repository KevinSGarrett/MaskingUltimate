from hashlib import sha256
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "configs" / "civitai_pose_stress_fixtures.yaml"
CLASSIFICATION = ROOT / "Plan" / "Civitai" / "adult_body_resource_classification.yaml"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_registry_covers_every_stress_fixture_resource():
    registry = _load_yaml(REGISTRY)
    classification = _load_yaml(CLASSIFICATION)

    stress_ids = {int(entry["id"]) for entry in classification["role_groups"]["stress_fixture"]}
    fixture_ids = {int(entry["civitai_id"]) for entry in registry["fixtures"]}

    assert fixture_ids == stress_ids
    assert len(registry["fixtures"]) == len(stress_ids)


def test_fixture_archives_hash_and_extracted_paths_match_disk():
    registry = _load_yaml(REGISTRY)
    if not all((ROOT / fixture["archive_path"]).exists() for fixture in registry["fixtures"]):
        pytest.skip("external Plan/Civitai pose cache is not mounted in this checkout")

    for fixture in registry["fixtures"]:
        archive = ROOT / fixture["archive_path"]
        extracted = ROOT / fixture["extracted_path"]
        total_files = sum(1 for path in extracted.rglob("*") if path.is_file())

        assert archive.exists(), fixture["key"]
        assert extracted.exists(), fixture["key"]
        assert _digest(archive) == fixture["archive_sha256"]
        assert total_files == fixture["file_counts"]["total"]


def test_required_stress_coverage_is_present():
    registry = _load_yaml(REGISTRY)
    coverage = {tag for fixture in registry["fixtures"] for tag in fixture["coverage"]}

    assert set(registry["required_coverage"]) <= coverage


def test_fixture_policy_allows_governed_training_and_reviewed_gold():
    registry = _load_yaml(REGISTRY)

    assert registry["policy"]["role_required"] == "stress_fixture"
    assert registry["policy"]["fixtures_may_be_training_data_when_governed"] is True
    assert registry["policy"]["fixtures_may_seed_human_reviewed_gold_when_governed"] is True
