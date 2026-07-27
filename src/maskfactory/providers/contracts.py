"""Provider-neutral role contracts and independence accounting."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

import numpy as np

PROVIDER_CONTRACT_VERSION = "1.0.0"


@dataclass(frozen=True)
class ProviderIdentity:
    provider_key: str
    role: str
    model_family: str
    source_commit: str
    runtime_fingerprint: str
    contract_version: str = PROVIDER_CONTRACT_VERSION
    provenance_aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        values = (
            self.provider_key,
            self.role,
            self.model_family,
            self.source_commit,
            self.runtime_fingerprint,
        )
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("provider identity fields must be non-empty strings")
        if self.contract_version != PROVIDER_CONTRACT_VERSION:
            raise ValueError(f"provider contract version must be {PROVIDER_CONTRACT_VERSION}")
        if len(self.provenance_aliases) != len(set(self.provenance_aliases)):
            raise ValueError("provider provenance aliases must be unique")


@dataclass(frozen=True)
class BoxProposal:
    bbox_xyxy: tuple[float, float, float, float]
    confidence: float
    label: str
    instance_key: str | None = None

    def __post_init__(self) -> None:
        x1, y1, x2, y2 = self.bbox_xyxy
        if not all(np.isfinite(value) for value in self.bbox_xyxy) or x2 <= x1 or y2 <= y1:
            raise ValueError("provider box must have finite positive area")
        if not np.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("provider box confidence must be in 0..1")
        if not self.label:
            raise ValueError("provider box label is required")


@dataclass(frozen=True)
class MaskProposal:
    mask: np.ndarray
    confidence: float
    provider: ProviderIdentity
    prompt_fingerprint: str

    def __post_init__(self) -> None:
        mask = np.asarray(self.mask)
        if mask.ndim != 2 or mask.dtype != np.bool_:
            raise ValueError("provider mask proposal must be a 2-D boolean array")
        if not np.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("provider mask confidence must be in 0..1")
        if not self.prompt_fingerprint:
            raise ValueError("provider mask prompt fingerprint is required")


@dataclass(frozen=True)
class AlphaMatteProposal:
    """Provider-neutral soft matte with exact proposal provenance."""

    alpha: np.ndarray
    provider: ProviderIdentity
    prompt_fingerprint: str

    def __post_init__(self) -> None:
        alpha = np.asarray(self.alpha)
        if alpha.ndim != 2 or alpha.dtype != np.float32:
            raise ValueError("alpha matte must be a 2-D float32 array")
        if not np.isfinite(alpha).all() or alpha.min() < 0 or alpha.max() > 1:
            raise ValueError("alpha matte must contain finite values in 0..1")
        if not self.prompt_fingerprint:
            raise ValueError("alpha matte prompt fingerprint is required")


@dataclass(frozen=True)
class AlphaMatteSequenceProposal:
    """Provider-neutral ordered alpha sequence with exact route provenance."""

    alphas: np.ndarray
    provider: ProviderIdentity
    prompt_fingerprint: str
    route: str

    def __post_init__(self) -> None:
        alphas = np.asarray(self.alphas)
        if alphas.ndim != 3 or alphas.dtype != np.float32 or alphas.shape[0] < 1:
            raise ValueError("alpha sequence must be a non-empty 3-D float32 array")
        if not np.isfinite(alphas).all() or alphas.min() < 0 or alphas.max() > 1:
            raise ValueError("alpha sequence must contain finite values in 0..1")
        if not self.prompt_fingerprint:
            raise ValueError("alpha sequence prompt fingerprint is required")
        if not self.route:
            raise ValueError("alpha sequence route is required")


@runtime_checkable
class PersonDetector(Protocol):
    identity: ProviderIdentity

    def detect_people(self, image_path: Path) -> Sequence[BoxProposal]: ...


@runtime_checkable
class ConceptDetector(Protocol):
    identity: ProviderIdentity

    def discover(
        self, image_path: Path, *, concepts: Sequence[str], exemplars: Sequence[Path] = ()
    ) -> Sequence[BoxProposal | MaskProposal]: ...


@runtime_checkable
class InteractiveSegmenter(Protocol):
    identity: ProviderIdentity

    def embed(self, image: np.ndarray) -> Any: ...

    def refine(self, embedding: Any, *, prompt: Mapping[str, Any]) -> Sequence[MaskProposal]: ...


@runtime_checkable
class GeometryProvider(Protocol):
    identity: ProviderIdentity

    def infer_geometry(self, image_path: Path, *, person_box: BoxProposal) -> Mapping[str, Any]: ...


@runtime_checkable
class PoseProvider(Protocol):
    identity: ProviderIdentity

    def infer_pose(self, image_path: Path, *, person_box: BoxProposal) -> Mapping[str, Any]: ...


@runtime_checkable
class SilhouetteProvider(Protocol):
    identity: ProviderIdentity

    def infer_silhouette(self, image_path: Path, *, person_box: BoxProposal) -> MaskProposal: ...


@runtime_checkable
class MattingRefiner(Protocol):
    identity: ProviderIdentity

    def refine_matte(self, image_path: Path, *, prior_mask: np.ndarray) -> AlphaMatteProposal: ...


@runtime_checkable
class TemporalMattingRefiner(Protocol):
    identity: ProviderIdentity

    def refine_sequence(
        self, frame_paths: Sequence[Path], *, initial_mask: np.ndarray
    ) -> AlphaMatteSequenceProposal: ...


@runtime_checkable
class VlmReviewer(Protocol):
    identity: ProviderIdentity

    def review(
        self, image_path: Path, *, masks: Mapping[str, Path], evidence: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...


def independent_model_families(identities: Sequence[ProviderIdentity]) -> frozenset[str]:
    """Count model families, not correlated checkpoints or prompt variants."""
    return frozenset(identity.model_family for identity in identities)


def require_independent_model_families(
    identities: Sequence[ProviderIdentity], *, minimum: int
) -> None:
    families = independent_model_families(identities)
    if len(families) < minimum:
        raise ValueError(
            f"candidate evidence has {len(families)} independent model families; "
            f"requires {minimum}: {sorted(families)}"
        )


__all__ = [
    "AlphaMatteProposal",
    "AlphaMatteSequenceProposal",
    "BoxProposal",
    "ConceptDetector",
    "GeometryProvider",
    "InteractiveSegmenter",
    "MaskProposal",
    "MattingRefiner",
    "PersonDetector",
    "PoseProvider",
    "PROVIDER_CONTRACT_VERSION",
    "ProviderIdentity",
    "SilhouetteProvider",
    "TemporalMattingRefiner",
    "VlmReviewer",
    "independent_model_families",
    "require_independent_model_families",
]
