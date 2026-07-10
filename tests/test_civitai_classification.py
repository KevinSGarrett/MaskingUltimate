from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "Plan" / "Civitai" / "civitai_bootstrap_manifest.json"
CLASSIFICATION = ROOT / "Plan" / "Civitai" / "adult_body_resource_classification.yaml"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _manifest_ids() -> set[int]:
    import json

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    return {int(record["id"]) for record in manifest["records"]}


def _classified_entries(classification: dict) -> list[tuple[str, dict]]:
    entries: list[tuple[str, dict]] = []
    for role, role_entries in classification["role_groups"].items():
        entries.extend((role, entry) for entry in role_entries)
    return entries


def test_every_civitai_manifest_id_is_classified_once():
    classification = _load_yaml(CLASSIFICATION)
    classified = _classified_entries(classification)
    ids = [int(entry["id"]) for _, entry in classified]

    assert set(ids) == _manifest_ids()
    assert len(ids) == len(set(ids))
    assert len(ids) == classification["unique_civitai_id_count_at_classification"]


def test_classification_roles_are_allowed_and_define_training_eligibility():
    classification = _load_yaml(CLASSIFICATION)
    allowed_roles = set(classification["policy"]["allowed_primary_roles"])

    for role, entry in _classified_entries(classification):
        assert role in allowed_roles
        assert entry["name"]
        assert entry["rationale"]
        defaults = classification["role_defaults"][role]
        assert defaults["allowed_use"]
        assert defaults["authority_gate"]
        assert defaults["training_gold_eligibility"]


def test_adult_nsfw_assets_are_explicitly_eligible_for_training_and_reviewed_gold():
    classification = _load_yaml(CLASSIFICATION)

    assert classification["policy"]["adult_nsfw_assets_may_be_training_data_when_eligible"] is True
    assert (
        classification["policy"]["adult_nsfw_assets_may_seed_human_reviewed_gold_when_eligible"]
        is True
    )
    assert (
        classification["policy"]["require_provenance_license_consent_before_training_or_gold"]
        is True
    )


def test_explicit_nsfw_pose_resources_are_registered_for_stress_and_training_eligibility():
    classification = _load_yaml(CLASSIFICATION)
    stress_ids = {int(entry["id"]) for entry in classification["role_groups"]["stress_fixture"]}

    assert 264843 in stress_ids
    assert 297881 in stress_ids


def test_rejected_resources_cannot_be_used_as_provider_votes():
    classification = _load_yaml(CLASSIFICATION)
    provider_ids = {int(entry["id"]) for entry in classification["role_groups"]["provider_vote"]}
    rejected_ids = {int(entry["id"]) for entry in classification["role_groups"]["reject"]}

    assert provider_ids.isdisjoint(rejected_ids)
    assert rejected_ids == {1899226, 2731892}
