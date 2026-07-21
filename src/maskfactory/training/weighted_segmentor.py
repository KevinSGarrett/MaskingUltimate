"""MMSeg segmentor that applies truth-tier loss weights per training example."""

from __future__ import annotations

import importlib
import math
from collections.abc import Mapping, Sequence
from types import ModuleType
from typing import Any, Callable


def weighted_mean_loss_dicts(
    losses: Sequence[Mapping[str, Any]], weights: Sequence[float]
) -> dict[str, Any]:
    """Combine per-example MMSeg loss dictionaries using an exact weighted mean."""
    if not losses or len(losses) != len(weights):
        raise ValueError("weighted MMSeg loss inputs must be non-empty and aligned")
    if any(not math.isfinite(float(weight)) or not 0 < float(weight) <= 1 for weight in weights):
        raise ValueError("MMSeg training loss weights must be finite in (0, 1]")
    keys = set(losses[0])
    if any(set(item) != keys for item in losses):
        raise ValueError("per-example MMSeg loss dictionaries have inconsistent keys")
    denominator = float(sum(weights))
    combined: dict[str, Any] = {}
    for key in sorted(keys):
        values = [item[key] for item in losses]
        if isinstance(values[0], (list, tuple)):
            if any(len(value) != len(values[0]) for value in values):
                raise ValueError(f"per-example MMSeg list loss length drifted: {key}")
            combined[key] = [
                sum(value[index] * weight for value, weight in zip(values, weights, strict=True))
                / denominator
                for index in range(len(values[0]))
            ]
        else:
            combined[key] = (
                sum(value * weight for value, weight in zip(values, weights, strict=True))
                / denominator
            )
    return combined


def _load_mmseg_segmentor_components(
    importer: Callable[[str], ModuleType] = importlib.import_module,
) -> tuple[object | None, object | None]:
    try:
        encoder_decoder = importer("mmseg.models.segmentors").EncoderDecoder
        models = importer("mmseg.registry").MODELS
    except ModuleNotFoundError as exc:
        if exc.name == "mmseg":
            return None, None
        raise
    return encoder_decoder, models


def _slice_features(features: Any, index: int) -> Any:
    if isinstance(features, tuple):
        return tuple(value[index : index + 1] for value in features)
    if isinstance(features, list):
        return [value[index : index + 1] for value in features]
    return features[index : index + 1]


EncoderDecoder, MODELS = _load_mmseg_segmentor_components()

if EncoderDecoder is not None and MODELS is not None:

    @MODELS.register_module()
    class MaskFactoryWeightedEncoderDecoder(EncoderDecoder):
        """Evaluate each sample loss independently, then apply its governed tier weight."""

        def loss(self, inputs, data_samples):
            features = self.extract_feat(inputs)
            per_sample_losses = []
            weights = []
            for index, data_sample in enumerate(data_samples):
                weight = float(data_sample.metainfo.get("training_loss_weight", -1))
                sample_features = _slice_features(features, index)
                losses = self._decode_head_forward_train(sample_features, [data_sample])
                if self.with_auxiliary_head:
                    losses.update(
                        self._auxiliary_head_forward_train(sample_features, [data_sample])
                    )
                per_sample_losses.append(losses)
                weights.append(weight)
            return weighted_mean_loss_dicts(per_sample_losses, weights)


__all__ = ["weighted_mean_loss_dicts"]
