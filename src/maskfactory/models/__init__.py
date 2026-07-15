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
    register_ollama_models,
    register_smoke_runner,
    register_training_candidate,
    resolve_registered_managed_model,
    resolve_registered_model,
    verify_registered_model_smokes,
)

__all__ = [
    "DEFAULT_CATALOG",
    "DEFAULT_REGISTRY",
    "ModelFetchError",
    "ModelRegistryError",
    "catalog_model_keys",
    "fetch_models",
    "load_registered_model",
    "register_ollama_models",
    "register_smoke_runner",
    "register_training_candidate",
    "resolve_registered_managed_model",
    "resolve_registered_model",
    "verify_registered_model_smokes",
]
