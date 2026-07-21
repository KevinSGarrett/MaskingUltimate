import hashlib
import json
from pathlib import Path

import pytest
import yaml

from maskfactory.governance import (
    GovernancePolicyError,
    provider_activation_issues,
    validate_external_source_registry,
    validate_model_registry,
)

ROOT = Path(__file__).resolve().parents[1]


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _policy() -> dict[str, object]:
    return {
        "schema_version": "2.0.0",
        "use_profile": "private_personal_noncommercial",
        "distribution_allowed": False,
        "commercial_deployment": False,
        "content_compatibility": {
            "adult_nonexplicit": "allowed",
            "consensual_explicit_adult": "allowed",
        },
    }


def test_live_external_and_model_registries_enforce_private_profile() -> None:
    external = yaml.safe_load(
        (ROOT / "configs" / "external_sources.yaml").read_text(encoding="utf-8")
    )
    models = json.loads((ROOT / "models" / "model_registry.json").read_text(encoding="utf-8"))

    assert validate_external_source_registry(external) == {
        "schema_version": "2.0.0",
        "legacy": False,
    }
    assert validate_model_registry(models) == {
        "schema_version": "2.0.0",
        "legacy": False,
    }
    assert "sapiens" in external["providers"]
    assert "sapiens2" not in external["providers"]
    assert external["hard_exclusions"]["sapiens2"]["production_allowed"] is False
    assert "sam3_1" in external["providers"]


def test_external_registry_has_unique_keys_and_structured_sam31_roles() -> None:
    external = yaml.load(
        (ROOT / "configs" / "external_sources.yaml").read_text(encoding="utf-8"),
        Loader=_UniqueKeyLoader,
    )
    sam31 = external["providers"]["sam3_1"]
    assert sam31["capabilities"] == [
        "concept_detection",
        "interactive_segmentation",
        "video_tracking",
    ]
    assert sam31["roles"] == [
        "concept_detector_challenger",
        "interactive_segmenter_challenger",
    ]
    assert len(sam31["authority_constraints"]) == 2


def test_v2_registries_fail_closed_without_exact_policy() -> None:
    document = _policy()
    document["models"] = []
    document["distribution_allowed"] = True

    with pytest.raises(GovernancePolicyError, match="distribution_allowed must be false"):
        validate_model_registry(document)


@pytest.mark.parametrize(
    "entry",
    [
        {"key": "sapiens2_seg", "source_url": "https://example.invalid/model"},
        {"key": "fixture", "source_url": "https://github.com/facebookresearch/sapiens2"},
    ],
)
def test_model_registry_rejects_every_sapiens2_artifact(entry: dict[str, str]) -> None:
    document = _policy()
    document["models"] = [entry]

    with pytest.raises(GovernancePolicyError, match="hard-excluded Sapiens2"):
        validate_model_registry(document)


def test_historical_v1_registry_remains_readable() -> None:
    assert validate_model_registry(
        {"schema_version": "1.0.0", "models": []}, allow_legacy=True
    ) == {
        "schema_version": "1.0.0",
        "legacy": True,
    }


def test_active_registry_rejects_legacy_or_missing_schema_version() -> None:
    with pytest.raises(GovernancePolicyError, match="historical-only"):
        validate_model_registry({"schema_version": "1.0.0", "models": []})
    with pytest.raises(GovernancePolicyError, match="schema_version is required"):
        validate_model_registry({"models": []})


def test_provider_requires_its_own_lifecycle_and_content_decision() -> None:
    external = yaml.safe_load(
        (ROOT / "configs" / "external_sources.yaml").read_text(encoding="utf-8")
    )
    del external["providers"]["sam2"]["content_compatibility"]
    with pytest.raises(GovernancePolicyError, match="provider sam2 content_compatibility"):
        validate_external_source_registry(external)

    external = yaml.safe_load(
        (ROOT / "configs" / "external_sources.yaml").read_text(encoding="utf-8")
    )
    del external["providers"]["sam2"]["lifecycle_state"]
    with pytest.raises(GovernancePolicyError, match="provider sam2 lifecycle_state"):
        validate_external_source_registry(external)


def test_unresolved_license_or_nonactive_lifecycle_blocks_activation() -> None:
    entry = {
        "lifecycle_state": "installed",
        "verify_license": True,
        "content_compatibility": {
            "adult_nonexplicit": "allowed",
            "consensual_explicit_adult": "allowed",
        },
    }
    assert provider_activation_issues(entry, content_lane="adult_nonexplicit") == (
        "license verification is unresolved",
    )
    entry["verify_license"] = False
    entry["lifecycle_state"] = "planned"
    entry["license_source"] = "https://example.invalid/license"
    entry["license_snapshot_sha256"] = "a" * 64
    entry["license_reviewed_at"] = "2026-07-14T00:00:00Z"
    assert provider_activation_issues(entry, content_lane="adult_nonexplicit") == (
        "lifecycle_state='planned' is not activatable",
    )


def test_checkpoint_license_overrides_permissive_repository_with_immutable_evidence() -> None:
    external = yaml.safe_load(
        (ROOT / "configs" / "external_sources.yaml").read_text(encoding="utf-8")
    )
    layers = {
        "repository": {
            "decision": "allowed",
            "source_url": "https://example.invalid/repository-license",
            "snapshot_sha256": "a" * 64,
            "reviewed_at": "2026-07-14T00:00:00Z",
        },
        "checkpoint": {
            "decision": "prohibited",
            "source_url": "https://example.invalid/checkpoint-terms",
            "snapshot_sha256": "b" * 64,
            "reviewed_at": "2026-07-14T00:01:00Z",
        },
        "effective_scope": "checkpoint",
    }
    layers["evidence_bundle_sha256"] = hashlib.sha256(
        json.dumps(layers, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    external["providers"]["sam2"]["license_layers"] = layers
    with pytest.raises(GovernancePolicyError, match="checkpoint-specific.*prohibited"):
        validate_external_source_registry(external)

    external["providers"]["sam2"]["license_layers"]["checkpoint"]["decision"] = "allowed"
    with pytest.raises(GovernancePolicyError, match="bundle hash mismatch"):
        validate_external_source_registry(external)
    canonical = {
        key: external["providers"]["sam2"]["license_layers"][key]
        for key in ("repository", "checkpoint", "effective_scope")
    }
    external["providers"]["sam2"]["license_layers"]["evidence_bundle_sha256"] = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    validate_external_source_registry(external)
