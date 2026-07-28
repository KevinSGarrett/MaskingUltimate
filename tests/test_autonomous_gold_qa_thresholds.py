import copy
from pathlib import Path

import pytest
import yaml

from maskfactory.autonomy.qa_thresholds import (
    QaThresholdRegistryError,
    expand_registry,
    load_qa_threshold_registry,
    require_gold_authority,
    resolve_qa_thresholds,
)
from maskfactory.ontology import load_ontology
from maskfactory.validation import validate_document


def _write(tmp_path: Path, document: dict) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def _plain_policy() -> dict:
    policy = load_qa_threshold_registry()
    policy.pop("registry_file_sha256")
    return policy


def test_registry_expands_every_enabled_ontology_label_and_is_hash_bound():
    expanded = expand_registry()
    enabled = [label for label in load_ontology("configs/ontology_v2.yaml").labels if label.enabled]
    assert expanded["enabled_label_count"] == len(enabled) == 146
    assert {row["label"] for row in expanded["labels"]} == {label.name for label in enabled}
    assert len(expanded["resolved_registry_sha256"]) == 64
    assert expanded["authority_eligible"] is False
    assert all(
        not validate_document(row, "autonomous_gold_qa_threshold_resolution")
        for row in expanded["labels"]
    )


@pytest.mark.parametrize("label", ["hair", "left_index_finger", "right_toes"])
def test_thin_structure_labels_resolve_to_distinct_preservation_contract(label: str):
    resolved = resolve_qa_thresholds(label, contexts=("default", "thin_structure"))
    ordinary = resolve_qa_thresholds("chest_upper_torso")
    assert resolved["thin_structure"] is True
    assert resolved["maximum_components"] > ordinary["maximum_components"]
    assert resolved["hard_invariants"]["cross_person_bleed_ceiling"] == 0


def test_profiles_and_contexts_are_not_collapsed_to_one_global_rule():
    atomic = resolve_qa_thresholds("left_breast")
    material = resolve_qa_thresholds("skin")
    amodal = resolve_qa_thresholds("left_breast_projected_region")
    assert atomic["mask_type"] != material["mask_type"] != amodal["mask_type"]
    assert atomic["thresholds"] != material["thresholds"]
    cropped = resolve_qa_thresholds("left_breast", contexts=("default", "crop_edge"))
    assert cropped["maximum_components"] > atomic["maximum_components"]
    assert cropped["maximum_p95_edge_error_px"] > atomic["maximum_p95_edge_error_px"]


def test_unknown_missing_or_duplicate_context_fails_closed():
    with pytest.raises(QaThresholdRegistryError, match="empty"):
        resolve_qa_thresholds("hair", contexts=())
    with pytest.raises(QaThresholdRegistryError, match="duplicated"):
        resolve_qa_thresholds("hair", contexts=("default", "default"))
    with pytest.raises(QaThresholdRegistryError, match="unregistered"):
        resolve_qa_thresholds("hair", contexts=("moonlight",))


def test_incomplete_metric_or_mask_type_coverage_fails(tmp_path: Path):
    policy = _plain_policy()
    policy["metric_catalog"].remove("cross_person_bleed")
    with pytest.raises(QaThresholdRegistryError, match="metric coverage"):
        load_qa_threshold_registry(_write(tmp_path / "metric", policy))
    policy = _plain_policy()
    del policy["profiles"]["material"]
    with pytest.raises(QaThresholdRegistryError, match="profile coverage"):
        load_qa_threshold_registry(_write(tmp_path / "profile", policy))


def test_cross_person_bleed_cannot_be_relaxed(tmp_path: Path):
    policy = _plain_policy()
    policy["contexts"]["multi_person_overlap"]["cross_person_bleed_ceiling"] = 0.001
    with pytest.raises(QaThresholdRegistryError, match="safety ceiling"):
        load_qa_threshold_registry(_write(tmp_path, policy))


def test_unknown_thin_structure_label_fails_closed(tmp_path: Path):
    policy = _plain_policy()
    policy["thin_structure_labels"].append("invented_finger")
    with pytest.raises(QaThresholdRegistryError, match="not enabled"):
        load_qa_threshold_registry(_write(tmp_path, policy))


def test_uncalibrated_registry_cannot_authorize_gold():
    policy = load_qa_threshold_registry()
    with pytest.raises(QaThresholdRegistryError, match="not qualified"):
        require_gold_authority(policy)
    forged = copy.deepcopy(policy)
    forged["authority_eligible"] = True
    with pytest.raises(QaThresholdRegistryError, match="not qualified"):
        require_gold_authority(forged)
