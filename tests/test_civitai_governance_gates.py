from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CLASSIFICATION = ROOT / "Plan" / "Civitai" / "adult_body_resource_classification.yaml"
DETECTORS = ROOT / "configs" / "civitai_auxiliary_detectors.yaml"
FIXTURES = ROOT / "configs" / "civitai_pose_stress_fixtures.yaml"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_classification_blocks_training_gold_and_mask_authority():
    classification = _load_yaml(CLASSIFICATION)

    assert classification["policy"]["no_civitai_asset_is_gold_authority"] is True
    assert classification["policy"]["no_civitai_asset_is_training_data_without_rights"] is True
    assert (
        classification["policy"]["require_provenance_license_consent_before_training_or_gold"]
        is True
    )

    for defaults in classification["role_defaults"].values():
        assert defaults["training_gold_gate"].startswith("Blocked")
        authority_gate = defaults["authority_gate"].lower()
        assert "not" in authority_gate or authority_gate.startswith("rejected")


def test_detector_registry_is_provider_vote_only_and_never_gold():
    detectors = _load_yaml(DETECTORS)

    assert detectors["policy"]["role_required"] == "provider_vote"
    assert detectors["policy"]["no_detector_is_mask_authority"] is True
    assert detectors["policy"]["no_detector_is_training_or_gold_data"] is True

    for detector in detectors["detectors"]:
        assert detector["artifact_path"].startswith("Plan/Civitai/")
        assert detector["payload_path"].startswith("Plan/Civitai/")
        assert detector["install_target"].startswith("ComfyUI/models/ultralytics/")


def test_pose_fixtures_are_not_source_images_training_or_gold():
    fixtures = _load_yaml(FIXTURES)

    assert fixtures["policy"]["role_required"] == "stress_fixture"
    assert fixtures["policy"]["no_fixture_is_training_data"] is True
    assert fixtures["policy"]["no_fixture_is_gold_reference"] is True
    assert fixtures["policy"]["no_fixture_is_mask_authority"] is True

    for fixture in fixtures["fixtures"]:
        assert fixture["archive_path"].startswith("Plan/Civitai/")
        assert fixture["extracted_path"].startswith("Plan/Civitai/")


def test_no_civitai_registry_path_targets_training_or_gold_dirs():
    detectors = _load_yaml(DETECTORS)
    fixtures = _load_yaml(FIXTURES)
    forbidden_prefixes = ("data/gold", "data/packages", "datasets", "runs", "models/training")

    paths = []
    for detector in detectors["detectors"]:
        paths.extend([detector["artifact_path"], detector["payload_path"]])
    for fixture in fixtures["fixtures"]:
        paths.extend([fixture["archive_path"], fixture["extracted_path"]])

    for path in paths:
        normalized = path.replace("\\", "/")
        assert not normalized.startswith(forbidden_prefixes), path
