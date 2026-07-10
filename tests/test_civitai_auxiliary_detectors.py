from hashlib import sha256
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "configs" / "civitai_auxiliary_detectors.yaml"
CLASSIFICATION = ROOT / "Plan" / "Civitai" / "adult_body_resource_classification.yaml"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_registry_covers_every_provider_vote_with_local_artifact():
    registry = _load_yaml(REGISTRY)
    classification = _load_yaml(CLASSIFICATION)

    provider_vote_ids = {
        int(entry["id"]) for entry in classification["role_groups"]["provider_vote"]
    }
    registered_ids = {int(entry["civitai_id"]) for entry in registry["detectors"]}

    assert registered_ids == provider_vote_ids
    assert len(registry["detectors"]) == len(provider_vote_ids)


def test_detector_artifacts_and_payload_hashes_match_disk():
    registry = _load_yaml(REGISTRY)

    for detector in registry["detectors"]:
        artifact = ROOT / detector["artifact_path"]
        payload = ROOT / detector["payload_path"]

        assert artifact.exists(), detector["key"]
        assert payload.exists(), detector["key"]
        assert _digest(artifact) == detector["artifact_sha256"]
        assert _digest(payload) == detector["payload_sha256"]


def test_required_detector_coverage_buckets_are_present():
    registry = _load_yaml(REGISTRY)
    coverage = {bucket for detector in registry["detectors"] for bucket in detector["coverage"]}

    required = {
        "shoes_footwear",
        "feet",
        "hair",
        "lips",
        "socks",
        "hands",
        "face_bands",
        "armpits",
        "nails",
        "mouth",
        "rear_body",
        "accessories",
        "body_boundary",
    }
    assert required <= coverage


def test_install_targets_are_adetailer_ultralytics_paths():
    registry = _load_yaml(REGISTRY)

    for detector in registry["detectors"]:
        target = detector["install_target"]
        assert target.startswith("ComfyUI/models/ultralytics/")
        assert "/bbox/" in target or "/segm/" in target
        assert target.endswith(".pt")


def test_auxiliary_detector_policy_blocks_authority_and_gold_use():
    registry = _load_yaml(REGISTRY)

    assert registry["policy"]["role_required"] == "provider_vote"
    assert registry["policy"]["no_detector_is_mask_authority"] is True
    assert registry["policy"]["no_detector_is_training_or_gold_data"] is True
