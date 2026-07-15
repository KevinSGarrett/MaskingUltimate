"""MaskFactory segmentation dataset adapter with optional MMSeg registration."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Mapping

import numpy as np
from PIL import Image

from ..ontology import get_ontology
from .augmentations import IGNORE_INDEX, burn_ambiguous_to_ignore

DATASET_TARGETS = {
    "part": {
        "type": "MaskFactoryBodyPartDataset",
        "image_prefix": "part_seg/images",
        "annotation_prefix": "part_seg/annotations",
    },
    "material": {
        "type": "MaskFactoryMaterialDataset",
        "image_prefix": "material_seg/images",
        "annotation_prefix": "material_seg/annotations",
    },
}


class MaskFactorySegmentationDataset:
    """Load per-instance MMSeg exports while burning honest ambiguity to ignore 255."""

    METAINFO = {"ignore_index": IGNORE_INDEX, "reduce_zero_label": False}

    def __init__(self, dataset_root: Path, split: str) -> None:
        self.root = Path(dataset_root)
        split_path = self.root / f"{split}.txt"
        self.sample_ids = tuple(
            line.strip()
            for line in split_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if not self.sample_ids:
            raise ValueError(f"MaskFactory dataset split is empty: {split_path}")
        self.sample_weights = load_sample_weight_records(self.root, self.sample_ids)

    def __len__(self) -> int:
        return len(self.sample_ids)

    def load_sample(self, index: int) -> dict[str, np.ndarray | str | float]:
        sample_id = self.sample_ids[index]
        image = np.asarray(
            Image.open(self.root / "part_seg/images" / f"{sample_id}.png").convert("RGB")
        )
        part = np.asarray(Image.open(self.root / "part_seg/annotations" / f"{sample_id}.png"))
        material = np.asarray(
            Image.open(self.root / "material_seg/annotations" / f"{sample_id}.png")
        )
        if part.shape != image.shape[:2] or material.shape != image.shape[:2]:
            raise ValueError(f"MaskFactory dataset sample dimensions differ: {sample_id}")
        ambiguity_path = self.root / "ambiguous" / f"{sample_id}.png"
        if ambiguity_path.is_file():
            ambiguity = np.asarray(Image.open(ambiguity_path).convert("L")) > 0
            part = burn_ambiguous_to_ignore(part, ambiguity)
            material = burn_ambiguous_to_ignore(material, ambiguity)
        return {
            "sample_id": sample_id,
            "image": image,
            "part": part.astype(np.uint8),
            "material": material.astype(np.uint8),
            "truth_tier": self.sample_weights[sample_id]["truth_tier"],
            "training_loss_weight": float(self.sample_weights[sample_id]["training_loss_weight"]),
        }


def load_sample_weight_records(
    dataset_root: Path, sample_ids: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    """Load exact per-example truth/weight provenance, with legacy weight-one fallback."""
    path = Path(dataset_root) / "sample_weights.json"
    if not path.is_file():
        return {
            sample_id: {
                "truth_tier": "human_anchor_gold",
                "training_loss_weight": 1.0,
            }
            for sample_id in sample_ids
        }
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != "2.0.0" or not isinstance(document.get("samples"), dict):
        raise ValueError("MaskFactory sample weights require schema 2.0.0")
    records = document["samples"]
    missing = sorted(set(sample_ids) - set(records))
    if missing:
        raise ValueError(f"MaskFactory sample weights are missing split samples: {missing}")
    selected = {}
    for sample_id in sample_ids:
        row = records[sample_id]
        if not isinstance(row, dict):
            raise ValueError(f"MaskFactory sample weight record is invalid: {sample_id}")
        weight = float(row.get("training_loss_weight", -1))
        if not 0 <= weight <= 1 or not isinstance(row.get("truth_tier"), str):
            raise ValueError(f"MaskFactory sample weight authority is invalid: {sample_id}")
        selected[sample_id] = dict(row)
    return selected


def mmseg_dataset_config(dataset_root: Path, split: str, target: str) -> dict:
    """Return the exact BaseSegDataset config for one exported training target."""
    if target not in DATASET_TARGETS:
        raise ValueError(f"unknown MaskFactory MMSeg target: {target}")
    root = Path(dataset_root)
    split_path = root / f"{split}.txt"
    if not split_path.is_file():
        raise ValueError(f"MaskFactory dataset split is missing: {split_path}")
    layout = DATASET_TARGETS[target]
    config = {
        "type": layout["type"],
        "data_root": str(root),
        "ann_file": f"{split}.txt",
        "data_prefix": {
            "img_path": layout["image_prefix"],
            "seg_map_path": layout["annotation_prefix"],
        },
        "img_suffix": ".png",
        "seg_map_suffix": ".png",
        "reduce_zero_label": False,
        "ignore_index": IGNORE_INDEX,
    }
    if (root / "sample_weights.json").is_file():
        config["sample_weights_file"] = "sample_weights.json"
    return config


def mmseg_training_dataset_bundle(
    dataset_root: Path,
    split: str,
    target: str,
    training_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a dataset plus the mandatory custom imports and governed pipeline."""
    from .mmseg_transforms import mmseg_augmentation_config

    integration = mmseg_augmentation_config(training_config, map_name=target)
    dataset = mmseg_dataset_config(dataset_root, split, target)
    dataset["pipeline"] = integration["train_pipeline"]
    return {"custom_imports": integration["custom_imports"], "dataset": dataset}


def _class_names(map_name: str) -> tuple[str, ...]:
    labels = sorted(get_ontology().labels_for_map(map_name), key=lambda label: int(label.id))
    ids = [int(label.id) for label in labels]
    if ids != list(range(len(ids))):
        raise ValueError(f"{map_name} ontology IDs must be contiguous for MMSeg")
    return tuple(label.name for label in labels)


def _load_mmseg_components(
    importer: Callable[[str], ModuleType] = importlib.import_module,
) -> tuple[object | None, object | None]:
    """Allow an absent MMSeg install, but expose every broken partial install."""
    try:
        datasets_module = importer("mmseg.datasets")
        registry_module = importer("mmseg.registry")
    except ModuleNotFoundError as exc:
        if exc.name == "mmseg":
            return None, None
        raise
    return datasets_module.BaseSegDataset, registry_module.DATASETS


def _validated_base_dataset_kwargs(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Consume duplicated config contracts before calling BaseSegDataset."""
    forwarded = dict(kwargs)
    forwarded.pop("sample_weights_file", None)
    reduce_zero_label = forwarded.pop("reduce_zero_label", False)
    ignore_index = forwarded.pop("ignore_index", IGNORE_INDEX)
    if reduce_zero_label is not False:
        raise ValueError("MaskFactory MMSeg datasets require reduce_zero_label=false")
    if int(ignore_index) != IGNORE_INDEX:
        raise ValueError(f"MaskFactory MMSeg datasets require ignore_index={IGNORE_INDEX}")
    return forwarded


def _mmseg_weight_authority(kwargs: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Resolve MMSeg ann_file IDs to the same immutable weight records as local loading."""
    sample_weights_file = kwargs.get("sample_weights_file")
    data_root = Path(str(kwargs.get("data_root", "")))
    ann_file = Path(str(kwargs.get("ann_file", "")))
    if not ann_file.is_absolute():
        ann_file = data_root / ann_file
    sample_ids = tuple(
        line.strip() for line in ann_file.read_text(encoding="utf-8").splitlines() if line.strip()
    )
    if sample_weights_file is not None:
        configured = Path(str(sample_weights_file))
        weights_path = configured if configured.is_absolute() else data_root / configured
        if weights_path.resolve() != (data_root / "sample_weights.json").resolve():
            raise ValueError("MaskFactory MMSeg sample weight authority path drifted")
    return load_sample_weight_records(data_root, sample_ids)


class _WeightedDatasetMixin:
    """Attach immutable truth-tier loss metadata to every MMSeg data info."""

    def _initialize_weight_authority(self, kwargs: Mapping[str, Any]) -> None:
        self._maskfactory_sample_weights = _mmseg_weight_authority(kwargs)

    def load_data_list(self):
        data_list = super().load_data_list()
        if not self._maskfactory_sample_weights:
            return data_list
        for data_info in data_list:
            sample_id = Path(str(data_info.get("img_path", ""))).stem
            if sample_id not in self._maskfactory_sample_weights:
                raise ValueError(f"MMSeg data info lacks weight authority: {sample_id}")
            row = self._maskfactory_sample_weights[sample_id]
            data_info["sample_id"] = sample_id
            data_info["truth_tier"] = row["truth_tier"]
            data_info["training_loss_weight"] = float(row["training_loss_weight"])
        return data_list


BaseSegDataset, DATASETS = _load_mmseg_components()

if DATASETS is not None and BaseSegDataset is not None:

    @DATASETS.register_module()
    class MaskFactoryBodyPartDataset(_WeightedDatasetMixin, BaseSegDataset):
        """MMSeg adapter for the authoritative indexed part-map vocabulary."""

        METAINFO = {
            "classes": _class_names("part"),
            "reduce_zero_label": False,
            "ignore_index": IGNORE_INDEX,
        }

        def __init__(self, **kwargs) -> None:
            self._initialize_weight_authority(kwargs)
            super().__init__(
                reduce_zero_label=False,
                ignore_index=IGNORE_INDEX,
                **_validated_base_dataset_kwargs(kwargs),
            )

    @DATASETS.register_module()
    class MaskFactoryMaterialDataset(_WeightedDatasetMixin, BaseSegDataset):
        """MMSeg adapter for MaskFactory's indexed 16-class material maps."""

        METAINFO = {
            "classes": _class_names("material"),
            "reduce_zero_label": False,
            "ignore_index": IGNORE_INDEX,
        }

        def __init__(self, **kwargs) -> None:
            self._initialize_weight_authority(kwargs)
            super().__init__(
                reduce_zero_label=False,
                ignore_index=IGNORE_INDEX,
                **_validated_base_dataset_kwargs(kwargs),
            )
