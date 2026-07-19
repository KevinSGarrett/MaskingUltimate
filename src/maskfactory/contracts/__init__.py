"""External producer contracts consumed by Main-owned orchestration."""

from .maskfactory_adapter import (
    ADOPTED_CONTRACT_VERSIONS,
    ADOPTED_OPENAPI_PATHS,
    ADOPTED_WIRE_SCHEMA_VERSIONS,
    MaskFactoryAdapter,
    MaskFactoryAdapterError,
)

__all__ = [
    "ADOPTED_CONTRACT_VERSIONS",
    "ADOPTED_OPENAPI_PATHS",
    "ADOPTED_WIRE_SCHEMA_VERSIONS",
    "MaskFactoryAdapter",
    "MaskFactoryAdapterError",
]
