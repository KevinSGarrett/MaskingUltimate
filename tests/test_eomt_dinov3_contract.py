from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from maskfactory.providers.eomt_dinov3 import (
    V2_VOCABULARY_SHA256,
    EomtDinov3ContractError,
    EomtDinov3TrainingContract,
)
from maskfactory.training.bodypart.v2_contract import V2_CLASS_NAMES

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "training" / "eomt_dinov3_small_v2.yaml"
LOCK = ROOT / "env" / "eomt_dinov3_runtime.lock.json"


def test_eomt_contract_binds_exact_v2_vocabulary_and_discards_coco_head() -> None:
    contract = EomtDinov3TrainingContract()
    compiled = contract.validate()
    assert compiled["provider_key"] == "eomt_dinov3_small_640"
    assert compiled["num_classes"] == 66
    assert compiled["class_names"] == list(V2_CLASS_NAMES)
    assert compiled["class_names_sha256"] == V2_VOCABULARY_SHA256
    assert compiled["pretrained_head_disposition"] == "discard_coco_panoptic_head"
    assert compiled["target_head_initialization"] == "random"
    assert compiled["authority"] == "training_and_shadow_evaluation_only"


@pytest.mark.parametrize(
    ("section", "key", "value", "match"),
    [
        ("pretraining", "maskfactory_label_authority", True, "pretraining authority"),
        ("target_head", "class_count", 133, "target head"),
        ("target_head", "class_names_sha256", "0" * 64, "target head"),
        ("selection", "active", "eomt_dinov3_small_640", "active/rollback"),
        ("selection", "baselines", ["eomt"], "baseline preservation"),
        ("data", "seed", 42, "fair-training data"),
        ("training", "iterations", 1, "fair-training schedule"),
        ("evaluation", "interval_iters", 1, "fair-evaluation"),
        ("thermal", "max_celsius", 99, "thermal contract"),
    ],
)
def test_eomt_contract_fails_closed_on_authority_or_ontology_drift(
    tmp_path: Path, section: str, key: str, value, match: str
) -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    drifted = copy.deepcopy(config)
    drifted[section][key] = value
    path = tmp_path / "eomt.yaml"
    path.write_text(yaml.safe_dump(drifted, sort_keys=False), encoding="utf-8")
    with pytest.raises(EomtDinov3ContractError, match=match):
        EomtDinov3TrainingContract(training_config=path).validate()


def test_eomt_snapshot_hash_drift_is_rejected(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    for filename in ("README.md", "config.json", "preprocessor_config.json", "model.safetensors"):
        (snapshot / filename).write_bytes(b"drift")
    with pytest.raises(EomtDinov3ContractError, match="snapshot drift"):
        EomtDinov3TrainingContract(snapshot=snapshot).validate()


def test_eomt_lock_registry_and_live_evidence_are_bound() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    registry = yaml.safe_load(
        (ROOT / "configs" / "external_sources.yaml").read_text(encoding="utf-8")
    )["providers"]["eomt_dinov3"]
    assert registry["lifecycle_state"] == "installed"
    assert registry["verify_license"] is False
    assert registry["source_revision"] == lock["source"]["revision"]
    assert registry["checkpoint_sha256"] == lock["snapshot"]["checkpoint_sha256"]
    for key in ("training_config", "smoke_script", "contract"):
        path = ROOT / lock["reproduction"][key]
        assert (
            hashlib.sha256(path.read_bytes()).hexdigest() == lock["reproduction"][f"{key}_sha256"]
        )
    evidence_path = ROOT / lock["evidence"]["runtime"]
    assert (
        hashlib.sha256(evidence_path.read_bytes()).hexdigest() == lock["evidence"]["runtime_sha256"]
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    claimed = evidence.pop("sha256")
    assert (
        claimed
        == hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert evidence["authority"]["pretraining_labels_are_not_maskfactory_labels"] is True
