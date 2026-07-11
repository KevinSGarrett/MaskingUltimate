"""Production provider adapters for the Mode-B service."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np

from ..models.registry import DEFAULT_MODELS_ROOT, resolve_registered_role
from ..stages.s05_geometry import PromptPlan
from ..stages.s07_sam2 import Sam2Provider, WslSam2Provider, build_embedding

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = ROOT / "models/model_registry.json"
DEFAULT_WORK_DIR = ROOT / "runs/serve/sam2"
SAM2_CONFIGS = {
    "sam2.1_hiera_large": "configs/sam2.1/sam2.1_hiera_l.yaml",
    "sam2.1_hiera_base_plus": "configs/sam2.1/sam2.1_hiera_b+.yaml",
}
ProviderFactory = Callable[[dict[str, Path], dict[str, str], Path], Sam2Provider]


class ServingProviderError(ValueError):
    """A production serving provider cannot satisfy its strict contract."""


class Sam2InteractiveRefiner:
    """One-request SAM2 interactive adapter with primary-to-fallback OOM handling."""

    def __init__(self, provider: Sam2Provider) -> None:
        self.provider = provider

    def __call__(
        self, image: np.ndarray, label: str, clicks: tuple[dict[str, Any], ...]
    ) -> np.ndarray:
        source = np.asarray(image)
        if source.ndim != 3 or source.shape[2] != 3:
            raise ServingProviderError("SAM2 refine image must be RGB")
        positives, negatives = _validated_clicks(clicks, source.shape[:2])
        height, width = source.shape[:2]
        plan = PromptPlan(
            label=label,
            box_xyxy=(0, 0, width - 1, height - 1),
            positive_points=positives,
            negative_points=negatives,
            prior_quality="interactive_clicks",
            multimask_output=True,
        )
        embedding = None
        try:
            embedding, _model = build_embedding(self.provider, source)
            candidates = self.provider.predict(embedding, plan, multimask_output=True)
            if not candidates:
                raise ServingProviderError("SAM2 refine returned no candidates")
            ranked = []
            for index, candidate in enumerate(candidates):
                logits = np.asarray(candidate.logits)
                if logits.shape != (height, width) or not np.isfinite(logits).all():
                    raise ServingProviderError("SAM2 refine logits are invalid")
                if not 0 <= candidate.predicted_iou <= 1:
                    raise ServingProviderError("SAM2 refine predicted IoU is outside [0, 1]")
                ranked.append((candidate.predicted_iou, -index, logits))
            return max(ranked, key=lambda item: (item[0], item[1]))[2] >= 0
        finally:
            if embedding is not None:
                close = getattr(self.provider, "close", None)
                if callable(close):
                    close(embedding)

    def close(self) -> None:
        """The per-image embedding is already released at the end of each call."""


def load_production_sam2_refiner(
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
    work_dir: Path = DEFAULT_WORK_DIR,
    provider_factory: ProviderFactory = WslSam2Provider,
) -> Sam2InteractiveRefiner:
    """Resolve both verified SAM2 checkpoints and return a lazy interactive adapter."""
    checkpoints = {
        "sam2.1_hiera_large": resolve_registered_role(
            "primary_boundary_refiner",
            registry_path=registry_path,
            models_root=models_root,
        ),
        "sam2.1_hiera_base_plus": resolve_registered_role(
            "boundary_refiner_oom_fallback",
            registry_path=registry_path,
            models_root=models_root,
        ),
    }
    provider = provider_factory(checkpoints, dict(SAM2_CONFIGS), Path(work_dir))
    return Sam2InteractiveRefiner(provider)


def _validated_clicks(
    clicks: tuple[dict[str, Any], ...], shape: tuple[int, int]
) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]:
    if not clicks:
        raise ServingProviderError("SAM2 refine requires at least one click")
    height, width = shape
    positives = []
    negatives = []
    for index, click in enumerate(clicks):
        if not isinstance(click, Mapping):
            raise ServingProviderError(f"SAM2 refine click {index} must be an object")
        x, y, positive = click.get("x"), click.get("y"), click.get("positive")
        if (
            isinstance(x, bool)
            or isinstance(y, bool)
            or not isinstance(x, int)
            or not isinstance(y, int)
        ):
            raise ServingProviderError(f"SAM2 refine click {index} coordinates must be integers")
        if not 0 <= x < width or not 0 <= y < height:
            raise ServingProviderError(f"SAM2 refine click {index} is outside the image")
        if not isinstance(positive, bool):
            raise ServingProviderError(f"SAM2 refine click {index} positive must be boolean")
        (positives if positive else negatives).append((x, y))
    if not positives:
        raise ServingProviderError("SAM2 refine requires at least one positive click")
    return tuple(positives), tuple(negatives)
