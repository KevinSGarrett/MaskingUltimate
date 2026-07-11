"""Production provider adapters for the Mode-B service."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np

from ..models.registry import DEFAULT_MODELS_ROOT, resolve_registered_role
from ..ontology import get_ontology
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
CHAMPION_ROLES = ("champion_bodypart", "champion_hand", "champion_clothing")


class ServingProviderError(ValueError):
    """A production serving provider cannot satisfy its strict contract."""


class MMSegChampionSlot:
    """One verified MMSeg champion loaded for a single sequential serving slot."""

    def __init__(
        self,
        model: Any,
        class_names: tuple[str, ...],
        inference: Callable[[Any, np.ndarray], Any],
    ) -> None:
        if not class_names or len(class_names) != len(set(class_names)):
            raise ServingProviderError("champion class_names must be non-empty and unique")
        self.model = model
        self.class_names = class_names
        self.inference = inference

    def __call__(self, image: np.ndarray, labels: tuple[str, ...]) -> dict[str, np.ndarray]:
        source = np.asarray(image)
        if source.dtype != np.uint8 or source.ndim != 3 or source.shape[2] != 3:
            raise ServingProviderError("MMSeg champion input must be uint8 RGB")
        unknown = sorted(set(labels) - set(self.class_names))
        if unknown:
            raise ServingProviderError(f"champion does not declare requested classes: {unknown}")
        sample = self.inference(self.model, source)
        prediction = getattr(getattr(sample, "pred_sem_seg", None), "data", None)
        if prediction is None:
            raise ServingProviderError("MMSeg champion result lacks pred_sem_seg.data")
        detach = getattr(prediction, "detach", None)
        if callable(detach):
            prediction = detach()
        cpu = getattr(prediction, "cpu", None)
        if callable(cpu):
            prediction = cpu()
        prediction = np.asarray(prediction).squeeze()
        if prediction.shape != source.shape[:2] or not np.issubdtype(prediction.dtype, np.integer):
            raise ServingProviderError("MMSeg champion prediction has invalid geometry or dtype")
        if prediction.size and (
            int(prediction.min()) < 0 or int(prediction.max()) >= len(self.class_names)
        ):
            raise ServingProviderError("MMSeg champion prediction contains undeclared class IDs")
        by_name = {name: index for index, name in enumerate(self.class_names)}
        return {label: prediction == by_name[label] for label in labels}

    def close(self) -> None:
        model = self.model
        self.model = None
        to = getattr(model, "to", None)
        if callable(to):
            to("cpu")
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass


def load_production_mmseg_slot(
    role: str,
    checkpoint: Path,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
    initializer: Callable[..., Any] | None = None,
    inference: Callable[[Any, np.ndarray], Any] | None = None,
) -> MMSegChampionSlot:
    """Load one champion only after verifying its inference config and class contract."""
    if role not in CHAMPION_ROLES:
        raise ServingProviderError(f"unsupported MMSeg champion role: {role}")
    try:
        registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ServingProviderError(f"champion registry is unreadable: {exc}") from exc
    matches = [entry for entry in registry.get("models", []) if entry.get("role") == role]
    if len(matches) != 1:
        raise ServingProviderError(f"expected exactly one registry entry for {role}")
    entry = matches[0]
    resolved = resolve_registered_role(
        role, registry_path=Path(registry_path), models_root=Path(models_root)
    )
    if resolved != Path(checkpoint).resolve():
        raise ServingProviderError(f"resolved {role} checkpoint changed before load")
    config_value = entry.get("inference_config")
    config_digest = entry.get("inference_config_sha256")
    class_names = entry.get("class_names")
    if not isinstance(config_value, str) or not isinstance(config_digest, str):
        raise ServingProviderError(f"{role} lacks hashed inference_config metadata")
    if (
        not isinstance(class_names, list)
        or not all(isinstance(name, str) and name for name in class_names)
        or len(class_names) != len(set(class_names))
    ):
        raise ServingProviderError(f"{role} lacks a valid explicit class_names vocabulary")
    ontology = get_ontology()
    expected_map = "material" if role == "champion_clothing" else "part"
    for name in class_names:
        if name == "background":
            continue
        try:
            label = ontology.label(name)
        except Exception as exc:
            raise ServingProviderError(f"{role} declares unknown class name: {name}") from exc
        if label.map != expected_map:
            raise ServingProviderError(
                f"{role} class {name} belongs to {label.map}, expected {expected_map}"
            )
    normalized = Path(config_value.replace("\\", "/"))
    parts = normalized.parts
    if parts and parts[0].lower() == "models":
        normalized = Path(*parts[1:])
    config_path = (Path(models_root) / normalized).resolve()
    root = Path(models_root).resolve()
    if config_path == root or root not in config_path.parents or not config_path.is_file():
        raise ServingProviderError(f"{role} inference config is missing or escapes models root")
    actual_digest = hashlib.sha256(config_path.read_bytes()).hexdigest()
    if actual_digest != config_digest:
        raise ServingProviderError(f"{role} inference config hash mismatch")
    if initializer is None or inference is None:
        try:
            from mmseg.apis import inference_model, init_model
        except ImportError as exc:
            raise ServingProviderError("MMSeg serving runtime is not installed") from exc
        initializer = initializer or init_model
        inference = inference or inference_model
    model = initializer(str(config_path), str(resolved), device="cuda:0")
    return MMSegChampionSlot(model, tuple(class_names), inference)


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
