"""Callable adapters that put incumbents and challengers behind one contract surface."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from .contracts import BoxProposal, MaskProposal, ProviderIdentity

LEGACY_PROVIDER_ALIASES = {
    "sam2": "sam2_1_large",
    "sam2.1_hiera_large": "sam2_1_large",
    "sam2_hiera_large": "sam2_1_large",
    "sam2_1_hiera_large": "sam2_1_large",
    "sam2.1_hiera_base_plus": "sam2_1_base_plus",
    "sam2_hiera_base_plus": "sam2_1_base_plus",
}


def provider_contract_metadata(
    identity: ProviderIdentity,
    *,
    historical_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Emit canonical metadata while hash-preserving any historical evidence document."""
    metadata: dict[str, Any] = {
        "contract_version": identity.contract_version,
        "provider_key": identity.provider_key,
        "role": identity.role,
        "model_family": identity.model_family,
        "source_commit": identity.source_commit,
        "runtime_fingerprint": identity.runtime_fingerprint,
        "provenance_aliases": list(identity.provenance_aliases),
    }
    if historical_manifest is not None:
        canonical = json.dumps(historical_manifest, sort_keys=True, separators=(",", ":")).encode()
        metadata["historical_provenance_sha256"] = hashlib.sha256(canonical).hexdigest()
    return metadata


def provider_identity_from_manifest(
    manifest: Mapping[str, Any],
    *,
    role: str,
    source_commit: str = "legacy-unrecorded",
    runtime_fingerprint: str = "legacy-unrecorded",
) -> ProviderIdentity:
    """Read canonical or legacy SAM2 provenance without rewriting historical fields."""
    contract = manifest.get("provider_contract")
    if isinstance(contract, Mapping):
        aliases = contract.get("provenance_aliases", ())
        if not isinstance(aliases, (list, tuple)):
            raise ValueError("provider provenance aliases must be an array")
        return ProviderIdentity(
            str(contract["provider_key"]),
            str(contract["role"]),
            str(contract["model_family"]),
            str(contract["source_commit"]),
            str(contract["runtime_fingerprint"]),
            contract_version=str(contract["contract_version"]),
            provenance_aliases=tuple(str(value) for value in aliases),
        )
    identifier = next(
        (
            str(manifest[key])
            for key in ("sam2_model", "provider", "model")
            if isinstance(manifest.get(key), str) and manifest[key]
        ),
        None,
    )
    if identifier is None:
        raise ValueError("historical provider manifest has no provider identifier")
    normalized = identifier.lower().replace("-", "_")
    canonical = LEGACY_PROVIDER_ALIASES.get(normalized, normalized)
    family = "sam2" if canonical.startswith("sam2") else canonical.split("_", 1)[0]
    return ProviderIdentity(
        canonical,
        role,
        family,
        source_commit,
        runtime_fingerprint,
        provenance_aliases=(identifier,),
    )


class PersonDetectorAdapter:
    def __init__(
        self,
        identity: ProviderIdentity,
        detector: Callable[[Path], Sequence[BoxProposal]],
    ) -> None:
        self.identity = identity
        self._detector = detector

    def detect_people(self, image_path: Path) -> Sequence[BoxProposal]:
        results = tuple(self._detector(Path(image_path)))
        if not all(isinstance(result, BoxProposal) for result in results):
            raise TypeError("person detector returned a non-BoxProposal result")
        return results


class ConceptDetectorAdapter:
    def __init__(self, identity: ProviderIdentity, detector: Callable[..., Sequence[Any]]) -> None:
        self.identity = identity
        self._detector = detector

    def discover(
        self, image_path: Path, *, concepts: Sequence[str], exemplars: Sequence[Path] = ()
    ) -> Sequence[BoxProposal | MaskProposal]:
        results = tuple(
            self._detector(Path(image_path), concepts=tuple(concepts), exemplars=tuple(exemplars))
        )
        if not all(isinstance(result, (BoxProposal, MaskProposal)) for result in results):
            raise TypeError("concept detector returned non-canonical proposal evidence")
        return results


class InteractiveSegmenterAdapter:
    def __init__(
        self,
        identity: ProviderIdentity,
        embedder: Callable[[np.ndarray], Any],
        refiner: Callable[..., Sequence[MaskProposal]],
    ) -> None:
        self.identity = identity
        self._embedder = embedder
        self._refiner = refiner

    def embed(self, image: np.ndarray) -> Any:
        return self._embedder(np.asarray(image))

    def refine(self, embedding: Any, *, prompt: Mapping[str, Any]) -> Sequence[MaskProposal]:
        results = tuple(self._refiner(embedding, prompt=dict(prompt)))
        if not results or not all(isinstance(result, MaskProposal) for result in results):
            raise TypeError("interactive segmenter returned invalid mask proposals")
        return results


class GeometryProviderAdapter:
    def __init__(self, identity: ProviderIdentity, infer: Callable[..., Mapping[str, Any]]) -> None:
        self.identity = identity
        self._infer = infer

    def infer_geometry(self, image_path: Path, *, person_box: BoxProposal) -> Mapping[str, Any]:
        return dict(self._infer(Path(image_path), person_box=person_box))


class PoseProviderAdapter:
    def __init__(self, identity: ProviderIdentity, infer: Callable[..., Mapping[str, Any]]) -> None:
        self.identity = identity
        self._infer = infer

    def infer_pose(self, image_path: Path, *, person_box: BoxProposal) -> Mapping[str, Any]:
        return dict(self._infer(Path(image_path), person_box=person_box))


class SilhouetteProviderAdapter:
    def __init__(self, identity: ProviderIdentity, infer: Callable[..., MaskProposal]) -> None:
        self.identity = identity
        self._infer = infer

    def infer_silhouette(self, image_path: Path, *, person_box: BoxProposal) -> MaskProposal:
        result = self._infer(Path(image_path), person_box=person_box)
        if not isinstance(result, MaskProposal):
            raise TypeError("silhouette provider returned a non-MaskProposal result")
        return result


class VlmReviewerAdapter:
    def __init__(
        self, identity: ProviderIdentity, reviewer: Callable[..., Mapping[str, Any]]
    ) -> None:
        self.identity = identity
        self._reviewer = reviewer

    def review(
        self, image_path: Path, *, masks: Mapping[str, Path], evidence: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        return dict(
            self._reviewer(
                Path(image_path),
                masks=dict(masks),
                evidence=dict(evidence),
            )
        )


__all__ = [
    "ConceptDetectorAdapter",
    "GeometryProviderAdapter",
    "InteractiveSegmenterAdapter",
    "LEGACY_PROVIDER_ALIASES",
    "PersonDetectorAdapter",
    "PoseProviderAdapter",
    "SilhouetteProviderAdapter",
    "VlmReviewerAdapter",
    "provider_contract_metadata",
    "provider_identity_from_manifest",
]
