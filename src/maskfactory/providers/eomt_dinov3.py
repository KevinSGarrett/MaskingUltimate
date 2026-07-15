"""Frozen EoMT-DINOv3 trainable challenger contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from ..training.bodypart.v2_contract import V2_CLASS_NAMES
from .contracts import ProviderIdentity

ROOT = Path(__file__).resolve().parents[3]
EOMT_REVISION = "602edaa2839daf6cb3de3ad46c176098c3be9090"
EOMT_RUNTIME_FINGERPRINT = "8591a6ad543d35b49ebc10191e89eb7a3732016621ba092a0e3bddbb4c2f6913"
EOMT_FILES = {
    "model.safetensors": "1fed3231445cce739e368c1828f49215459ca33ba56b6712d48e3058274c5d6f",
    "config.json": "8baa79f9cc2d41a4e01f575efb97b0aad1353ce955c9e95b7da4c8f61f1034d3",
    "preprocessor_config.json": "ce1554014d6dcea56b2f352e564275c9ec4a07c5efee704742fe3ed128550e2e",
    "README.md": "1e13062ee2842cd1e92206b7a7ecd3944a243b169d0da8f43e04d94a31794165",
}
V2_VOCABULARY_SHA256 = "7f78e0c3405c8bd05e23522ccb453faa7f4a2bbba0a9b29493c7e7d0d19a6124"


class EomtDinov3ContractError(ValueError):
    """EoMT snapshot or MaskFactory head contract drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _vocabulary_hash(names: tuple[str, ...]) -> str:
    return hashlib.sha256(json.dumps(list(names), separators=(",", ":")).encode()).hexdigest()


class EomtDinov3TrainingContract:
    identity = ProviderIdentity(
        provider_key="eomt_dinov3_small_640",
        role="custom_segmenter",
        model_family="eomt_dinov3",
        source_commit=EOMT_REVISION,
        runtime_fingerprint=EOMT_RUNTIME_FINGERPRINT,
    )

    def __init__(
        self,
        *,
        snapshot: Path = ROOT / "models/runtime_cache/eomt_dinov3_small_602edaa",
        training_config: Path = ROOT / "configs/training/eomt_dinov3_small_v2.yaml",
    ) -> None:
        self.snapshot = Path(snapshot)
        self.training_config = Path(training_config)

    def validate(self) -> dict[str, Any]:
        for filename, expected in EOMT_FILES.items():
            path = self.snapshot / filename
            if not path.is_file() or _sha256(path) != expected:
                raise EomtDinov3ContractError(f"EoMT snapshot drift: {filename}")
        config = yaml.safe_load(self.training_config.read_text(encoding="utf-8"))
        if (
            config.get("lifecycle_state") != "installed"
            or config.get("authority") != "trainable_shadow_challenger_only"
        ):
            raise EomtDinov3ContractError("EoMT lifecycle/authority drift")
        snapshot = config.get("snapshot", {})
        if (
            snapshot.get("revision") != EOMT_REVISION
            or snapshot.get("checkpoint_sha256") != EOMT_FILES["model.safetensors"]
        ):
            raise EomtDinov3ContractError("EoMT configured snapshot drift")
        pretraining = config.get("pretraining", {})
        if pretraining != {
            "vocabulary": "COCO-panoptic-133",
            "label_count": 133,
            "maskfactory_label_authority": False,
        }:
            raise EomtDinov3ContractError("EoMT pretraining authority drift")
        target = config.get("target_head", {})
        if (
            target.get("ontology_version") != "body_parts_v2"
            or target.get("class_count") != len(V2_CLASS_NAMES)
            or target.get("class_names_sha256") != V2_VOCABULARY_SHA256
            or target.get("ignore_index") != 255
            or target.get("initialization") != "random_new_segmentation_head"
        ):
            raise EomtDinov3ContractError("EoMT target head contract drift")
        if _vocabulary_hash(V2_CLASS_NAMES) != V2_VOCABULARY_SHA256:
            raise EomtDinov3ContractError("active v2 ontology vocabulary drift")
        selection = config.get("selection", {})
        if selection.get("active") is not None or selection.get("rollback") is not None:
            raise EomtDinov3ContractError("untrained EoMT cannot hold active/rollback authority")
        if selection.get("baselines") != ["segformer_b3", "mask2former_swin_b"]:
            raise EomtDinov3ContractError("EoMT baseline preservation drift")
        if selection.get("pretraining_output_may_author_gold") is not False:
            raise EomtDinov3ContractError("EoMT pretraining output cannot author gold")
        return self.compile_head_spec()

    def compile_head_spec(self) -> dict[str, Any]:
        return {
            "provider_key": self.identity.provider_key,
            "model_family": self.identity.model_family,
            "source_commit": self.identity.source_commit,
            "runtime_fingerprint": self.identity.runtime_fingerprint,
            "architecture": "EomtDinov3ForUniversalSegmentation",
            "pretrained_checkpoint": str(self.snapshot / "model.safetensors"),
            "pretrained_head_disposition": "discard_coco_panoptic_head",
            "target_head_initialization": "random",
            "num_classes": len(V2_CLASS_NAMES),
            "class_names": list(V2_CLASS_NAMES),
            "class_names_sha256": V2_VOCABULARY_SHA256,
            "ignore_index": 255,
            "authority": "training_and_shadow_evaluation_only",
        }


__all__ = [
    "EOMT_FILES",
    "EOMT_REVISION",
    "EOMT_RUNTIME_FINGERPRINT",
    "EomtDinov3ContractError",
    "EomtDinov3TrainingContract",
    "V2_VOCABULARY_SHA256",
]
