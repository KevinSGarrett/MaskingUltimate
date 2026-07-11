"""MaskFactory segmentation dataset adapter with optional MMSeg registration."""

from __future__ import annotations

import importlib
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

    def __len__(self) -> int:
        return len(self.sample_ids)

    def load_sample(self, index: int) -> dict[str, np.ndarray | str]:
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
        }


def mmseg_dataset_config(dataset_root: Path, split: str, target: str) -> dict:
    """Return the exact BaseSegDataset config for one exported training target."""
    if target not in DATASET_TARGETS:
        raise ValueError(f"unknown MaskFactory MMSeg target: {target}")
    root = Path(dataset_root)
    split_path = root / f"{split}.txt"
    if not split_path.is_file():
        raise ValueError(f"MaskFactory dataset split is missing: {split_path}")
    layout = DATASET_TARGETS[target]
    return {
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


BaseSegDataset, DATASETS = _load_mmseg_components()

if DATASETS is not None and BaseSegDataset is not None:

    @DATASETS.register_module()
    class MaskFactoryBodyPartDataset(BaseSegDataset):
        """MMSeg adapter for the authoritative indexed part-map vocabulary."""

        METAINFO = {
            "classes": _class_names("part"),
            "reduce_zero_label": False,
            "ignore_index": IGNORE_INDEX,
        }

        def __init__(self, **kwargs) -> None:
            super().__init__(reduce_zero_label=False, ignore_index=IGNORE_INDEX, **kwargs)

    @DATASETS.register_module()
    class MaskFactoryMaterialDataset(BaseSegDataset):
        """MMSeg adapter for MaskFactory's indexed 16-class material maps."""

        METAINFO = {
            "classes": _class_names("material"),
            "reduce_zero_label": False,
            "ignore_index": IGNORE_INDEX,
        }

        def __init__(self, **kwargs) -> None:
            super().__init__(reduce_zero_label=False, ignore_index=IGNORE_INDEX, **kwargs)
