"""Fail-closed official SAM 3.1 shadow discovery and refinement adapters."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ..io.hashing import sha256_file
from .contracts import BoxProposal, MaskProposal, ProviderIdentity

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUNTIME_LOCK = ROOT / "env" / "sam31_runtime.lock.json"
OFFICIAL_PROVIDER_KEY = "sam3_1"
SHADOW_AUTHORITY = "shadow_candidate_only_no_active_map_serving_semantic_or_gold_authority"


class Sam31ShadowError(ValueError):
    """Official SAM 3.1 shadow evidence is malformed, stale, or over-authoritative."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_lock(path: Path) -> tuple[dict[str, Any], str]:
    path = Path(path)
    lock = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(lock, dict) or lock.get("provider") != OFFICIAL_PROVIDER_KEY:
        raise Sam31ShadowError("SAM 3.1 runtime lock identity is invalid")
    if set(lock) != {
        "schema_version",
        "provider",
        "status",
        "source",
        "checkpoint",
        "license_review",
        "runtime",
        "live_smoke",
    }:
        raise Sam31ShadowError("SAM 3.1 runtime lock structure is invalid")
    source = lock["source"]
    checkpoint = lock["checkpoint"]
    runtime = lock["runtime"]
    if (
        not isinstance(source.get("commit"), str)
        or len(source["commit"]) != 40
        or not isinstance(checkpoint.get("sha256"), str)
        or len(checkpoint["sha256"]) != 64
    ):
        raise Sam31ShadowError("SAM 3.1 immutable identity is incomplete")
    requirements = ROOT / runtime["requirements_lock"]
    if (
        not requirements.is_file()
        or sha256_file(requirements) != runtime["requirements_lock_sha256"]
    ):
        raise Sam31ShadowError("SAM 3.1 runtime requirements identity is stale")
    return lock, sha256_file(path)


def _identity(lock: Mapping[str, Any], lock_sha256: str, role: str) -> ProviderIdentity:
    runtime = lock["runtime"]
    fingerprint = _canonical_sha256(
        {
            "runtime_lock_sha256": lock_sha256,
            "checkpoint_sha256": lock["checkpoint"]["sha256"],
            "python": runtime["python"],
            "torch": runtime["torch"],
            "cuda": runtime["cuda"],
        }
    )
    return ProviderIdentity(
        OFFICIAL_PROVIDER_KEY,
        role,
        "sam3",
        lock["source"]["commit"],
        fingerprint,
    )


def sam31_provider_identity(
    role: str, *, lock_path: Path = DEFAULT_RUNTIME_LOCK
) -> ProviderIdentity:
    """Return the exact official identity for one supported SAM 3.1 contract role."""
    if role not in {"concept_detector", "interactive_segmenter"}:
        raise Sam31ShadowError("SAM 3.1 provider role is unsupported")
    lock, digest = _load_lock(lock_path)
    return _identity(lock, digest, role)


def _image(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        value = np.asarray(image.convert("RGB"))
    if value.ndim != 3 or value.shape[2] != 3:
        raise Sam31ShadowError("SAM 3.1 source image geometry is invalid")
    return value


def _mask(value: Any, shape: tuple[int, int], field: str) -> np.ndarray:
    result = np.asarray(value)
    if result.dtype != np.bool_ or result.ndim != 2 or result.shape != shape:
        raise Sam31ShadowError(f"{field} must be an exact-shape boolean mask")
    if not result.any():
        raise Sam31ShadowError(f"{field} must not be empty")
    return result


def _point(value: Any, shape: tuple[int, int], field: str) -> tuple[int, int]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        raise Sam31ShadowError(f"{field} is invalid")
    x, y = value
    if not 0 <= x < shape[1] or not 0 <= y < shape[0]:
        raise Sam31ShadowError(f"{field} is outside image geometry")
    return x, y


def _box(value: Any, shape: tuple[int, int]) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise Sam31ShadowError("box prompt is invalid")
    try:
        box = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise Sam31ShadowError("box prompt is invalid") from exc
    x1, y1, x2, y2 = box
    if (
        not all(np.isfinite(item) for item in box)
        or x1 < 0
        or y1 < 0
        or x2 > shape[1]
        or y2 > shape[0]
        or x2 <= x1
        or y2 <= y1
    ):
        raise Sam31ShadowError("box prompt is outside image geometry")
    return box


@dataclass(frozen=True)
class Sam31Embedding:
    payload: Any
    image_shape: tuple[int, int]
    image_sha256: str
    runtime_lock_sha256: str


class Sam31ConceptDetector:
    """Convert injected official-runtime discovery output into strict canonical proposals."""

    def __init__(
        self,
        executor: Callable[..., Sequence[Mapping[str, Any]]],
        *,
        lock_path: Path = DEFAULT_RUNTIME_LOCK,
    ) -> None:
        self._lock, self.runtime_lock_sha256 = _load_lock(lock_path)
        self.identity = _identity(self._lock, self.runtime_lock_sha256, "concept_detector")
        self._executor = executor
        self.authority = SHADOW_AUTHORITY

    def discover(
        self, image_path: Path, *, concepts: Sequence[str], exemplars: Sequence[Path] = ()
    ) -> Sequence[BoxProposal | MaskProposal]:
        path = Path(image_path)
        image = _image(path)
        normalized = tuple(str(value).strip() for value in concepts)
        if (
            not normalized
            or any(not value for value in normalized)
            or len(set(normalized)) != len(normalized)
        ):
            raise Sam31ShadowError("concept prompts must be unique nonempty strings")
        exemplar_paths = tuple(Path(value) for value in exemplars)
        if any(not value.is_file() for value in exemplar_paths):
            raise Sam31ShadowError("exemplar prompt artifact is missing")
        fingerprint = _canonical_sha256(
            {
                "image_sha256": sha256_file(path),
                "concepts": normalized,
                "exemplar_sha256": [sha256_file(value) for value in exemplar_paths],
                "runtime_lock_sha256": self.runtime_lock_sha256,
            }
        )
        raw = tuple(self._executor(path, concepts=normalized, exemplars=exemplar_paths))
        results: list[BoxProposal | MaskProposal] = []
        instance_keys: set[str] = set()
        for index, item in enumerate(raw):
            if not isinstance(item, Mapping) or set(item) != {
                "kind",
                "confidence",
                "label",
                "instance_key",
                "value",
            }:
                raise Sam31ShadowError("SAM 3.1 discovery result structure is invalid")
            instance = item["instance_key"]
            if not isinstance(instance, str) or not instance or instance in instance_keys:
                raise Sam31ShadowError("SAM 3.1 discovery instance identity is invalid")
            instance_keys.add(instance)
            confidence = float(item["confidence"])
            label = str(item["label"])
            if label not in normalized:
                raise Sam31ShadowError("SAM 3.1 discovery result label was not requested")
            if item["kind"] == "box":
                results.append(
                    BoxProposal(_box(item["value"], image.shape[:2]), confidence, label, instance)
                )
            elif item["kind"] == "mask":
                results.append(
                    MaskProposal(
                        _mask(item["value"], image.shape[:2], f"discovery[{index}].mask"),
                        confidence,
                        self.identity,
                        fingerprint,
                    )
                )
            else:
                raise Sam31ShadowError("SAM 3.1 discovery result kind is invalid")
        return tuple(results)


class Sam31InteractiveSegmenter:
    """Validate point/box/mask refinement and repair proposals from an injected runtime."""

    def __init__(
        self,
        embedder: Callable[[np.ndarray], Any],
        refiner: Callable[..., Sequence[tuple[Any, float]]],
        *,
        lock_path: Path = DEFAULT_RUNTIME_LOCK,
    ) -> None:
        self._lock, self.runtime_lock_sha256 = _load_lock(lock_path)
        self.identity = _identity(self._lock, self.runtime_lock_sha256, "interactive_segmenter")
        self._embedder = embedder
        self._refiner = refiner
        self.authority = SHADOW_AUTHORITY

    def embed(self, image: np.ndarray) -> Sam31Embedding:
        value = np.asarray(image)
        if value.dtype != np.uint8 or value.ndim != 3 or value.shape[2] != 3:
            raise Sam31ShadowError("SAM 3.1 embedding input must be uint8 RGB")
        return Sam31Embedding(
            self._embedder(value),
            value.shape[:2],
            hashlib.sha256(value.tobytes()).hexdigest(),
            self.runtime_lock_sha256,
        )

    def refine(self, embedding: Any, *, prompt: Mapping[str, Any]) -> Sequence[MaskProposal]:
        if (
            not isinstance(embedding, Sam31Embedding)
            or embedding.runtime_lock_sha256 != self.runtime_lock_sha256
        ):
            raise Sam31ShadowError("SAM 3.1 embedding provenance is stale or foreign")
        if set(prompt) != {"positive_points", "negative_points", "box_xyxy", "mask_prompt"}:
            raise Sam31ShadowError("SAM 3.1 refinement prompt structure is invalid")
        shape = embedding.image_shape
        positives = tuple(
            _point(value, shape, "positive point") for value in prompt["positive_points"]
        )
        negatives = tuple(
            _point(value, shape, "negative point") for value in prompt["negative_points"]
        )
        box = _box(prompt["box_xyxy"], shape) if prompt["box_xyxy"] is not None else None
        mask_prompt = (
            _mask(prompt["mask_prompt"], shape, "mask prompt")
            if prompt["mask_prompt"] is not None
            else None
        )
        if not positives and box is None and mask_prompt is None:
            raise Sam31ShadowError("SAM 3.1 refinement requires a positive prompt")
        normalized = {
            "positive_points": positives,
            "negative_points": negatives,
            "box_xyxy": box,
            "mask_prompt_sha256": (
                hashlib.sha256(mask_prompt.tobytes()).hexdigest()
                if mask_prompt is not None
                else None
            ),
        }
        fingerprint = _canonical_sha256(
            {
                "image_sha256": embedding.image_sha256,
                "runtime_lock_sha256": self.runtime_lock_sha256,
                "prompt": normalized,
            }
        )
        runtime_prompt = dict(normalized)
        if mask_prompt is not None:
            runtime_prompt["mask_prompt"] = mask_prompt
        raw = tuple(self._refiner(embedding.payload, prompt=runtime_prompt))
        if not raw:
            raise Sam31ShadowError("SAM 3.1 refinement returned no proposals")
        proposals = []
        for index, item in enumerate(raw):
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise Sam31ShadowError("SAM 3.1 refinement result structure is invalid")
            mask = _mask(item[0], shape, f"refinement[{index}].mask")
            if any(not mask[y, x] for x, y in positives) or any(mask[y, x] for x, y in negatives):
                raise Sam31ShadowError("SAM 3.1 refinement violates prompt polarity")
            if box is not None:
                x1, y1, x2, y2 = (
                    int(np.floor(box[0])),
                    int(np.floor(box[1])),
                    int(np.ceil(box[2])),
                    int(np.ceil(box[3])),
                )
                allowed = np.zeros(shape, dtype=bool)
                allowed[y1:y2, x1:x2] = True
                if np.any(mask & ~allowed):
                    raise Sam31ShadowError("SAM 3.1 refinement violates box containment")
            proposals.append(MaskProposal(mask, float(item[1]), self.identity, fingerprint))
        return tuple(proposals)


__all__ = [
    "DEFAULT_RUNTIME_LOCK",
    "OFFICIAL_PROVIDER_KEY",
    "SHADOW_AUTHORITY",
    "Sam31ConceptDetector",
    "Sam31Embedding",
    "Sam31InteractiveSegmenter",
    "Sam31ShadowError",
    "sam31_provider_identity",
]
