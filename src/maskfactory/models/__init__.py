"""Model checkpoint acquisition and verified-registry access."""

from . import smoke as _smoke  # noqa: F401 - registers built-in smoke runners
from .registry import (
    DEFAULT_CATALOG,
    DEFAULT_REGISTRY,
    ModelFetchError,
    ModelRegistryError,
    catalog_model_keys,
    fetch_models,
    load_registered_model,
    register_smoke_runner,
    resolve_registered_model,
)

__all__ = [
    "DEFAULT_CATALOG",
    "DEFAULT_REGISTRY",
    "ModelFetchError",
    "ModelRegistryError",
    "catalog_model_keys",
    "fetch_models",
    "load_registered_model",
    "register_smoke_runner",
    "resolve_registered_model",
]
