"""Public bridge API currently available in the converged source tree.

The full product's historical initializer references bridge modules that are
not yet reconciled into this checkout.  Keep this facade deliberately narrow:
it exports only the independently restored external-adapter conformance
boundary and must expand with each verified bridge restoration rather than
silently importing unavailable modules.
"""

from .external_adapter_conformance import (
    ExternalAdapterConformanceError,
    build_external_adapter_conformance_evidence,
    validate_external_adapter_conformance_evidence,
)

__all__ = [
    "ExternalAdapterConformanceError",
    "build_external_adapter_conformance_evidence",
    "validate_external_adapter_conformance_evidence",
]
