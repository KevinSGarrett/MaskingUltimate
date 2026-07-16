"""Optional, default-disabled DAZ exact-synthetic supervision lane."""

from .control import (
    DazControlError,
    DazErrorCode,
    RegisteredRootResolver,
    append_event,
    build_event,
    initialize_daz_root,
    initialize_state_database,
    inspect_state_database,
    load_control_configuration,
    read_control_state,
    result_envelope,
    set_control_state,
)
from .policy import (
    DazConfiguration,
    DazPolicyError,
    daz_foundation_doctor,
    inspect_acquisition_queue,
    load_typed_daz_configuration,
    validate_daz_configuration,
    validate_synthetic_authority,
    validate_synthetic_share,
)
from .source_guard import PROHIBITED_EXTENSIONS, find_prohibited_source_assets

__all__ = [
    "DazConfiguration",
    "DazControlError",
    "DazErrorCode",
    "DazPolicyError",
    "RegisteredRootResolver",
    "PROHIBITED_EXTENSIONS",
    "append_event",
    "build_event",
    "daz_foundation_doctor",
    "find_prohibited_source_assets",
    "inspect_acquisition_queue",
    "initialize_daz_root",
    "initialize_state_database",
    "inspect_state_database",
    "load_control_configuration",
    "load_typed_daz_configuration",
    "read_control_state",
    "result_envelope",
    "set_control_state",
    "validate_daz_configuration",
    "validate_synthetic_authority",
    "validate_synthetic_share",
]
