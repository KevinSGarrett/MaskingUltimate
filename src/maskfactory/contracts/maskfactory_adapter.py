"""External adapter boundary for Main-owned orchestration.

This package intentionally exposes only the additive producer contract surface.
Main can depend on this module without importing MaskFactory internals.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

ADOPTED_CONTRACT_VERSIONS = {
    "bridge_contract": "maskfactory-comfyui-bridge/1.0",
    "api_contract": "maskfactory-api/1.0",
    "package_format": "maskfactory-package/1.0",
    "ontology_version": "body_parts_v1",
    "node_pack_version": "1.0.0",
}

ADOPTED_WIRE_SCHEMA_VERSIONS = {
    "maskfactory_release_snapshot": "1.0.0",
    "maskfactory_capability_snapshot": "1.0.0",
    "maskfactory_consumer_requirements": "1.0.0",
    "mask_acquisition_request": "1.0.0",
    "mask_acquisition_receipt": "1.0.0",
    "mask_bridge_error": "1.0.0",
    "maskfactory_adoption_receipt": "1.0.0",
    "mask_authority_invalidation_event": "1.0.0",
    "mask_repair_feedback": "1.0.0",
    "mask_bridge_event": "1.0.0",
    "operational_autonomy_certificate": "1.0.0",
    "mask_bridge_semantic_invariant_profile": "1.0.0",
}

ADOPTED_OPENAPI_PATHS = frozenset({"/health", "/models", "/predict", "/refine"})


class MaskFactoryAdapterError(RuntimeError):
    """Typed error boundary for adapter-visible MaskFactory failures."""


class MaskFactoryAdapter(Protocol):
    """Main-owned interface for calling producer-published capabilities only."""

    def health(self) -> Mapping[str, Any]:
        """Return health contract from the producer OpenAPI surface."""

    def models(self) -> Mapping[str, Any]:
        """Return currently published model/capability summary."""

    def predict(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Submit one frozen `mask_acquisition_request` exchange."""

    def refine(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Submit one frozen `mask_repair_feedback`-driven refinement exchange."""
