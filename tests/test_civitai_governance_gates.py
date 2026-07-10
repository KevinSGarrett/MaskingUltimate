from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CLASSIFICATION = ROOT / "Plan" / "Civitai" / "adult_body_resource_classification.yaml"
DETECTORS = ROOT / "configs" / "civitai_auxiliary_detectors.yaml"
FIXTURES = ROOT / "configs" / "civitai_pose_stress_fixtures.yaml"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_classification_allows_governed_training_and_human_reviewed_gold():
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

    for defaults in classification["role_defaults"].values():
        assert defaults["training_gold_eligibility"]


def test_detector_outputs_are_eligible_for_governed_training_and_reviewed_gold():
    detectors = _load_yaml(DETECTORS)

    assert detectors["policy"]["role_required"] == "provider_vote"
    assert detectors["policy"]["detector_outputs_may_be_training_labels_when_governed"] is True
    assert (
        detectors["policy"]["detector_outputs_may_seed_human_reviewed_gold_when_governed"] is True
    )

    for detector in detectors["detectors"]:
        assert detector["artifact_path"].startswith("Plan/Civitai/")
        assert detector["payload_path"].startswith("Plan/Civitai/")
        assert detector["install_target"].startswith("ComfyUI/models/ultralytics/")


def test_pose_fixtures_are_eligible_for_governed_training_and_reviewed_gold():
    fixtures = _load_yaml(FIXTURES)

    assert fixtures["policy"]["role_required"] == "stress_fixture"
    assert fixtures["policy"]["fixtures_may_be_training_data_when_governed"] is True
    assert fixtures["policy"]["fixtures_may_seed_human_reviewed_gold_when_governed"] is True

    for fixture in fixtures["fixtures"]:
        assert fixture["archive_path"].startswith("Plan/Civitai/")
        assert fixture["extracted_path"].startswith("Plan/Civitai/")


def test_civitai_source_registries_retain_provenance_paths_before_promotion():
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
