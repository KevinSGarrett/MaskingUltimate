"""Isolated Comfy_UI_Main-side ``MaskFactoryAdapter`` boundary.

This module is the durable orchestration boundary. It imports ONLY the adopted
producer contract surface (``maskfactory.contracts``) -- never ``maskfactory.bridge``
or any other producer internal, never a ComfyUI node id, never a MaskFactory
internal filesystem path. The producer-side external-adapter conformance verifier
observes exactly these imports and must accept them.

Authority ceiling: this adapter is an *isolated* Main-side consumer. It is NOT
the real Comfy_UI_Main runtime and never mints production authority.
"""

from __future__ import annotations

from typing import Any, Mapping

from maskfactory.contracts import (
    ADOPTED_CONTRACT_VERSIONS,
    ADOPTED_OPENAPI_PATHS,
    ADOPTED_WIRE_SCHEMA_VERSIONS,
    MaskFactoryAdapter,
    MaskFactoryAdapterError,
)

DOCUMENTED_DEPENDENCIES: tuple[str, ...] = (
    "maskfactory.contracts",
)


class IsolatedMainMaskFactoryAdapter(MaskFactoryAdapter):
    """Contracts-only adapter over the producer's published OpenAPI surface.

    ``predict``/``refine`` fail closed with a typed error unless a live Mode B
    endpoint is explicitly wired, which honors draft-only default authority and
    the no-silent-fallback rule (an unavailable service never yields a mask).
    """

    def __init__(self, *, live_endpoint: str | None = None) -> None:
        self._live_endpoint = live_endpoint

    def health(self) -> Mapping[str, Any]:
        return {
            "status": "adapter_ready" if self._live_endpoint else "service_unconfigured",
            "adopted_contract_versions": dict(ADOPTED_CONTRACT_VERSIONS),
            "openapi_paths": sorted(ADOPTED_OPENAPI_PATHS),
        }

    def models(self) -> Mapping[str, Any]:
        return {
            "wire_schema_versions": dict(ADOPTED_WIRE_SCHEMA_VERSIONS),
            "bridge_contract": ADOPTED_CONTRACT_VERSIONS["bridge_contract"],
        }

    def predict(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._live_endpoint is None:
            raise MaskFactoryAdapterError(
                "mode_b_service_unavailable: no live /predict endpoint configured; "
                "draft-only default authority, no silent fallback"
            )
        raise MaskFactoryAdapterError("live_predict_not_enabled_in_isolated_consumer")

    def refine(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._live_endpoint is None:
            raise MaskFactoryAdapterError(
                "mode_b_service_unavailable: no live /refine endpoint configured; "
                "draft-only default authority, no silent fallback"
            )
        raise MaskFactoryAdapterError("live_refine_not_enabled_in_isolated_consumer")
