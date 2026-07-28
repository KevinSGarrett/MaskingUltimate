"""Local-only Mode-B inference service contract and lazy FastAPI application."""

from __future__ import annotations

import base64
import io
import json
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
from PIL import Image

from .. import __version__
from ..gpu import DEFAULT_GPU_LOCK_PATH
from ..inpaint import feathered_dilation
from ..models.ontology_contract import (
    V1_ONTOLOGY_VERSION,
    ModelOntologyContractError,
    canonicalize_served_selector,
    ontology_for_version,
)
from ..models.registry import (
    DEFAULT_MODELS_ROOT,
    ModelRegistryError,
    resolve_registered_role_contract,
)
from .static_contracts import ServingStaticContractError, enforce_serving_provenance

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = ROOT / "models/model_registry.json"


class ServingError(RuntimeError):
    """The serving contract cannot safely fulfill a request."""


Predictor = Callable[[np.ndarray, tuple[str, ...]], dict[str, np.ndarray]]
Refiner = Callable[[np.ndarray, str, tuple[dict[str, Any], ...]], np.ndarray]
ChampionPredictorLoader = Callable[[Mapping[str, Path]], Predictor]
SlotPredictorLoader = Callable[[str, Path], Predictor]
RefinerLoader = Callable[[], Refiner]


def probe_vram() -> dict[str, Any]:
    """Return stable NVIDIA memory telemetry without making service health fatal."""
    command = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.total,memory.used,memory.free",
        "--format=csv,noheader,nounits",
    ]
    try:
        process = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "reason": str(exc), "gpus": []}
    if process.returncode:
        return {
            "available": False,
            "reason": (process.stderr.strip() or process.stdout.strip())[-500:],
            "gpus": [],
        }
    gpus = []
    try:
        for line in process.stdout.splitlines():
            index, name, total, used, free = (value.strip() for value in line.split(",", 4))
            gpus.append(
                {
                    "index": int(index),
                    "name": name,
                    "total_mib": int(total),
                    "used_mib": int(used),
                    "free_mib": int(free),
                }
            )
    except (TypeError, ValueError):
        return {"available": False, "reason": "unparseable nvidia-smi output", "gpus": []}
    return {"available": bool(gpus), "gpus": gpus}


class SequentialChampionPredictor:
    """Load, use, and unload one champion role at a time for an inference request."""

    ROLE_ORDER = ("champion_bodypart", "champion_hand", "champion_clothing")

    def __init__(
        self,
        checkpoints: Mapping[str, Path],
        loader: SlotPredictorLoader,
        *,
        ontology_version: str = V1_ONTOLOGY_VERSION,
    ) -> None:
        if set(checkpoints) != set(self.ROLE_ORDER):
            raise ServingError(f"sequential serving requires exactly {list(self.ROLE_ORDER)}")
        self.checkpoints = {role: Path(path) for role, path in checkpoints.items()}
        self.loader = loader
        self.ontology_version = ontology_version
        self.load_history: list[str] = []

    def __call__(self, image: np.ndarray, labels: tuple[str, ...]) -> dict[str, np.ndarray]:
        grouped = {role: [] for role in self.ROLE_ORDER}
        for label in labels:
            grouped[_champion_role_for_label(label, ontology_version=self.ontology_version)].append(
                label
            )
        outputs: dict[str, np.ndarray] = {}
        for role in self.ROLE_ORDER:
            requested = tuple(grouped[role])
            if not requested:
                continue
            provider = self.loader(role, self.checkpoints[role])
            self.load_history.append(role)
            try:
                result = provider(image, requested)
                if set(result) != set(requested):
                    raise ServingError(f"{role} output labels differ from its slot request")
                outputs.update(result)
            finally:
                close = getattr(provider, "close", None)
                if callable(close):
                    close()
                del provider
        return outputs


class OnDemandRefiner:
    """Load SAM2 lazily and retain one interactive session until explicitly released."""

    def __init__(self, loader: RefinerLoader) -> None:
        self.loader = loader
        self.load_count = 0
        self.provider: Refiner | None = None

    def __call__(
        self, image: np.ndarray, label: str, clicks: tuple[dict[str, Any], ...]
    ) -> np.ndarray:
        if self.provider is None:
            self.provider = self.loader()
            self.load_count += 1
        return self.provider(image, label, clicks)

    def close(self) -> None:
        if self.provider is None:
            return
        close = getattr(self.provider, "close", None)
        if callable(close):
            close()
        self.provider = None


@dataclass
class InferenceRuntime:
    predictor: Predictor | None = None
    refiner: Refiner | None = None
    registry_path: Path = DEFAULT_REGISTRY
    models_root: Path = DEFAULT_MODELS_ROOT
    gpu_lock_path: Path = DEFAULT_GPU_LOCK_PATH
    loaded_models: list[str] = field(default_factory=list)
    configured_models: list[str] = field(default_factory=list)
    model_contracts: dict[str, dict[str, Any]] = field(default_factory=dict)
    vram_probe: Callable[[], dict[str, Any]] = probe_vram
    _started: bool = False
    _request_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def configure_champion_predictor(
        self,
        loader: ChampionPredictorLoader,
        *,
        roles: tuple[str, ...] = ("champion_bodypart",),
    ) -> None:
        """Resolve verified champion roles and build the only production predictor path."""
        if self._started:
            raise ServingError("cannot reconfigure champion models while serving")
        if not roles or len(set(roles)) != len(roles):
            raise ServingError("champion role list must be non-empty and unique")
        if any(not role.startswith("champion_") for role in roles):
            raise ServingError("serving predictor may load champion_* roles only")
        try:
            resolved = {
                role: resolve_registered_role_contract(
                    role,
                    registry_path=self.registry_path,
                    models_root=self.models_root,
                )
                for role in roles
            }
        except ModelRegistryError as exc:
            raise ServingError(f"champion model resolution failed: {exc}") from exc
        checkpoints = {role: value[0] for role, value in resolved.items()}
        contracts = {role: value[1] for role, value in resolved.items()}
        self.predictor = loader(checkpoints)
        if self.predictor is None:
            raise ServingError("champion predictor loader returned no predictor")
        self.loaded_models = list(roles)
        self.configured_models = list(roles)
        self.model_contracts = contracts

    def configure_sequential_champions(self, loader: SlotPredictorLoader) -> None:
        """Resolve the required serving champions without co-residency."""
        if self._started:
            raise ServingError("cannot reconfigure champion models while serving")
        roles = SequentialChampionPredictor.ROLE_ORDER
        try:
            resolved = {
                role: resolve_registered_role_contract(
                    role, registry_path=self.registry_path, models_root=self.models_root
                )
                for role in roles
            }
        except ModelRegistryError as exc:
            raise ServingError(f"champion model resolution failed: {exc}") from exc
        checkpoints = {role: value[0] for role, value in resolved.items()}
        contracts = {role: value[1] for role, value in resolved.items()}
        ontology_version = str(
            contracts.get("champion_bodypart", {}).get("ontology_version") or V1_ONTOLOGY_VERSION
        )
        self.predictor = SequentialChampionPredictor(
            checkpoints, loader, ontology_version=ontology_version
        )
        self.loaded_models = []
        self.configured_models = list(roles)
        self.model_contracts = contracts

    def configure_on_demand_refiner(self, loader: RefinerLoader) -> None:
        if self._started:
            raise ServingError("cannot reconfigure SAM2 while serving")
        self.refiner = OnDemandRefiner(loader)

    def start(self) -> None:
        if self._started:
            raise ServingError("MaskFactory serving runtime is already started")
        self._started = True

    def stop(self) -> None:
        if self._started:
            close = getattr(self.refiner, "close", None)
            if callable(close):
                close()
            self._started = False

    def ontology_version(self) -> str:
        return str(
            self.model_contracts.get("champion_bodypart", {}).get("ontology_version")
            or V1_ONTOLOGY_VERSION
        )

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok" if self._started else "not_started",
            "pipeline_version": __version__,
            "versions": {"pipeline": __version__, "mode_b_api": "1.0.0"},
            "ontology_version": self.ontology_version(),
            "loaded_models": list(self.loaded_models),
            "configured_models": list(self.configured_models),
            "vram": self.vram_probe(),
        }

    def models(self) -> dict[str, Any]:
        document = json.loads(Path(self.registry_path).read_text(encoding="utf-8"))

        def version_tag(item: Mapping[str, Any]) -> str:
            # File-backed checkpoints use version_tag; governed Ollama entries use
            # their immutable model name/digest contract instead.
            return str(
                item.get("version_tag")
                or item.get("ollama_name")
                or item.get("digest")
                or item["key"]
            )

        models = [
            {
                "key": item["key"],
                "role": item["role"],
                "version_tag": version_tag(item),
                "sha256": item.get("sha256"),
                "ontology_version": (
                    item.get("ontology_version")
                    or (V1_ONTOLOGY_VERSION if item.get("role") == "champion_bodypart" else None)
                ),
                "class_names_sha256": item.get("class_names_sha256"),
            }
            for item in document.get("models", [])
            if item.get("verified")
        ]
        champions = {
            item["role"]: {
                "key": item["key"],
                "version_tag": version_tag(item),
                "sha256": item.get("sha256"),
                "ontology_version": (
                    item.get("ontology_version")
                    or (V1_ONTOLOGY_VERSION if item.get("role") == "champion_bodypart" else None)
                ),
                "class_names_sha256": item.get("class_names_sha256"),
            }
            for item in document.get("models", [])
            if item.get("verified") and str(item.get("role", "")).startswith("champion_")
        }
        return {
            "models": models,
            "champions": champions,
            "loaded_models": list(self.loaded_models),
            "configured_models": list(self.configured_models),
            "ontology_version": self.ontology_version(),
            "model_contracts": self.model_contracts,
        }

    def predict(
        self,
        image_bytes: bytes,
        labels: tuple[str, ...],
        *,
        return_mode: str = "binaries",
        inpaint: Mapping[str, int] | None = None,
    ) -> dict[str, Any]:
        if not self._started:
            raise ServingError("serving runtime must be started before inference")
        if self.predictor is None:
            raise ServingError("champion prediction provider is not configured")
        if return_mode not in {"binaries", "label_maps", "both"}:
            raise ServingError("return_mode must be binaries, label_maps, or both")
        ontology_version = self.ontology_version()
        try:
            selector_provenance = tuple(
                canonicalize_served_selector(label, ontology_version=ontology_version)
                for label in labels
            )
        except ModelOntologyContractError as exc:
            raise ServingError(str(exc)) from exc
        canonical_labels = tuple(item["canonical"] for item in selector_provenance)
        if len(set(canonical_labels)) != len(canonical_labels):
            raise ServingError("requested selectors collapse to duplicate canonical labels")
        dilation, feather = _validate_inpaint_request(inpaint)
        image = _decode_rgb(image_bytes)
        with self._request_lock:
            close = getattr(self.refiner, "close", None)
            if callable(close):
                close()
            outputs = self.predictor(image, canonical_labels)
        if set(outputs) != set(canonical_labels):
            raise ServingError("predictor output labels differ from the request")
        masks = {}
        mask_arrays = {}
        metadata = {}
        provenance_by_canonical = {item["canonical"]: item for item in selector_provenance}
        for label in canonical_labels:
            mask = _validated_mask(outputs[label], image.shape[:2], label)
            mask_arrays[label] = mask
            if return_mode in {"binaries", "both"}:
                masks[label] = _png_base64(mask)
            source_models = (
                [_champion_role_for_label(label, ontology_version=ontology_version)]
                if isinstance(self.predictor, SequentialChampionPredictor)
                else list(self.loaded_models)
            )
            if not source_models and not self.model_contracts:
                source_models = ["unconfigured_predictor"]
            if len(source_models) != 1:
                raise ServingError(
                    f"serving provenance requires exactly one champion role for {label}"
                )
            source_role = source_models[0]
            contract = self.model_contracts.get(source_role)
            if not isinstance(contract, Mapping):
                contract = (
                    _unconfigured_serving_contract()
                    if source_role == "unconfigured_predictor"
                    else _registered_serving_contract(self.registry_path, source_role)
                )
            provenance = _serving_provenance(source_role, contract)
            metadata[label] = {
                "visibility": "visible" if mask.any() else "not_visible",
                "area_px": int(mask.sum()),
                "status": "draft_model_generated",
                "ontology_version": ontology_version,
                "selector_provenance": provenance_by_canonical[label],
                "provenance": provenance,
            }
        response = {
            "status": "draft_model_generated",
            "ontology_version": ontology_version,
            "requested_labels": list(labels),
            "labels": list(canonical_labels),
            "selector_provenance": list(selector_provenance),
            "width": image.shape[1],
            "height": image.shape[0],
            "masks": masks,
            "manifest": metadata,
        }
        if return_mode in {"label_maps", "both"}:
            response["label_maps"] = _encoded_label_maps(
                mask_arrays, image.shape[:2], ontology_version=ontology_version
            )
        if inpaint is not None:
            response["inpaint_masks"] = {
                label: _grayscale_png_base64(
                    feathered_dilation(mask, dilate_px=dilation, feather_px=feather)
                )
                for label, mask in mask_arrays.items()
            }
            response["inpaint"] = {"dilate": dilation, "feather": feather}
        return response

    def refine(
        self, image_bytes: bytes, label: str, clicks: tuple[dict[str, Any], ...]
    ) -> dict[str, Any]:
        if not self._started:
            raise ServingError("serving runtime must be started before refinement")
        if self.refiner is None:
            raise ServingError("interactive refinement provider is not configured")
        image = _decode_rgb(image_bytes)
        with self._request_lock:
            mask = _validated_mask(self.refiner(image, label, clicks), image.shape[:2], label)
        return {
            "status": "draft_model_generated",
            "label": label,
            "mask": _png_base64(mask),
            "area_px": int(mask.sum()),
            "provenance": {"source": "interactive_segmenter_refine"},
        }


def create_production_runtime(
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
    config_path: Path = ROOT / "configs/pipeline.yaml",
    external_registry_path: Path = ROOT / "configs/external_sources.yaml",
) -> InferenceRuntime:
    """Build the production runtime with every currently available verified provider."""
    from functools import partial

    from ..models.registry import champion_status
    from .providers import (
        CHAMPION_ROLES,
        load_active_interactive_refiner,
        load_production_mmseg_slot,
    )

    runtime = InferenceRuntime(registry_path=Path(registry_path), models_root=Path(models_root))
    runtime.configure_on_demand_refiner(
        partial(
            load_active_interactive_refiner,
            config_path=Path(config_path),
            external_registry_path=Path(external_registry_path),
            model_registry_path=runtime.registry_path,
            models_root=runtime.models_root,
        )
    )
    present = set(champion_status(registry_path=runtime.registry_path)["champions"])
    required = set(CHAMPION_ROLES)
    if present & required and present & required != required:
        missing = sorted(required - present)
        raise ServingError(f"partial champion serving registry; missing roles: {missing}")
    if required <= present:
        runtime.configure_sequential_champions(
            partial(
                load_production_mmseg_slot,
                registry_path=runtime.registry_path,
                models_root=runtime.models_root,
            )
        )
    return runtime


def create_app(runtime: InferenceRuntime | None = None):
    """Create the FastAPI app lazily so non-serving environments need no web stack."""
    try:
        from fastapi import FastAPI, File, Form, HTTPException
    except ImportError as exc:
        raise ServingError(
            "FastAPI serving dependencies are missing; install the pinned MaskFactory environment"
        ) from exc

    service = runtime or create_production_runtime()
    app = FastAPI(title="MaskFactory", version=__version__)

    @app.on_event("startup")
    def startup() -> None:
        service.start()

    @app.on_event("shutdown")
    def shutdown() -> None:
        service.stop()

    @app.get("/health")
    def health():
        return service.health()

    @app.get("/models")
    def models():
        return service.models()

    @app.post("/predict")
    async def predict(
        image: bytes = File(...),
        labels: str = Form(...),
        return_mode: str = Form("binaries"),
        inpaint: str = Form("null"),
    ):
        try:
            requested = tuple(value.strip() for value in labels.split(",") if value.strip())
            if not requested:
                raise ServingError("at least one label is required")
            parsed_inpaint = json.loads(inpaint)
            return service.predict(
                image,
                requested,
                return_mode=return_mode,
                inpaint=parsed_inpaint,
            )
        except (ServingError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/refine")
    async def refine(image: bytes = File(...), label: str = Form(...), clicks: str = Form("[]")):
        try:
            parsed = tuple(json.loads(clicks))
            return service.refine(image, label, parsed)
        except (ServingError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return app


def _decode_rgb(value: bytes) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(value)) as opened:
            return np.asarray(opened.convert("RGB"))
    except (OSError, ValueError) as exc:
        raise ServingError("request image is not a readable raster") from exc


def _champion_role_for_label(name: str, *, ontology_version: str = V1_ONTOLOGY_VERSION) -> str:
    try:
        label = ontology_for_version(ontology_version).label(name)
    except Exception as exc:
        raise ServingError(f"unknown ontology label requested: {name}") from exc
    if label.map == "material":
        return "champion_clothing"
    if label.map != "part":
        raise ServingError(f"label is not served by a champion segmentation slot: {name}")
    if label.id is not None and 20 <= int(label.id) <= 33:
        return "champion_hand"
    return "champion_bodypart"


def _serving_provenance(role: str, contract: Mapping[str, Any]) -> dict[str, Any]:
    """Expose governed decisions without raw paths, credentials, or license text."""
    provenance = {
        "source": "champion_models",
        "models": [role],
        "provider": {
            "key": contract.get("model_key"),
            "role": contract.get("role"),
            "lifecycle_state": contract.get("lifecycle_state"),
            "license_eligibility": dict(contract.get("license_eligibility", {})),
            "benchmark_certificate": dict(contract.get("benchmark_certificate", {})),
            "rollback": dict(contract.get("rollback", {})),
        },
        "truth_tier": "machine_candidate",
        "certification": {"status": "not_certified", "scope": None},
        "routing": {
            "destination": "review_draft",
            "residual_reason": "model_draft_has_no_autonomy_certificate",
            "audit_reason": None,
        },
    }
    try:
        return enforce_serving_provenance(provenance)
    except ServingStaticContractError as exc:
        raise ServingError(f"serving provenance contract is invalid: {exc}") from exc


def _registered_serving_contract(registry_path: Path, source: str) -> dict[str, Any]:
    """Build the redacted contract for an already-loaded legacy predictor."""
    try:
        document = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ServingError(f"serving registry is unreadable: {exc}") from exc
    matches = [
        entry
        for entry in document.get("models", ())
        if entry.get("key") == source or entry.get("role") == source
    ]
    if len(matches) != 1:
        raise ServingError(f"serving contract is missing or ambiguous for {source}")
    entry = matches[0]
    if entry.get("verified") is not True or entry.get("lifecycle_state") != "promoted":
        raise ServingError(f"serving provider is not verified/promoted: {source}")
    license_review = entry.get("license_review")
    certificate = entry.get("benchmark_certificate")
    return {
        "model_key": entry.get("key"),
        "role": entry.get("role"),
        "lifecycle_state": entry.get("lifecycle_state"),
        "license_eligibility": {
            "status": (
                license_review.get("status") if isinstance(license_review, Mapping) else "missing"
            ),
            "eligible": isinstance(license_review, Mapping)
            and license_review.get("status") in {"verified", "not_required"},
        },
        "benchmark_certificate": (
            {
                "status": "current",
                "target_role": certificate.get("target_role"),
                "issued_at": certificate.get("issued_at"),
                "sha256": certificate.get("sha256"),
            }
            if isinstance(certificate, Mapping)
            else {
                "status": "missing",
                "target_role": None,
                "issued_at": None,
                "sha256": None,
            }
        ),
        "rollback": {
            "status": (
                "declared" if isinstance(entry.get("rollback_provider"), str) else "missing"
            ),
            "provider_key": entry.get("rollback_provider"),
        },
    }


def _unconfigured_serving_contract() -> dict[str, Any]:
    """Describe direct injected predictors honestly; production never selects this state."""
    return {
        "model_key": "unconfigured_predictor",
        "role": "unconfigured_predictor",
        "lifecycle_state": "unregistered",
        "license_eligibility": {"status": "missing", "eligible": False},
        "benchmark_certificate": {
            "status": "missing",
            "target_role": None,
            "issued_at": None,
            "sha256": None,
        },
        "rollback": {"status": "missing", "provider_key": None},
    }


def _validated_mask(mask: np.ndarray, shape: tuple[int, int], label: str) -> np.ndarray:
    array = np.asarray(mask)
    if array.shape != shape:
        raise ServingError(f"{label} mask dimensions differ from request image")
    if array.dtype == bool:
        return array
    if not set(np.unique(array)).issubset({0, 1, 255}):
        raise ServingError(f"{label} mask is not binary")
    return array > 0


def _png_base64(mask: np.ndarray) -> str:
    output = io.BytesIO()
    Image.fromarray(mask.astype(np.uint8) * 255, mode="L").save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def _grayscale_png_base64(values: np.ndarray) -> str:
    output = io.BytesIO()
    Image.fromarray(np.asarray(values, dtype=np.uint8), mode="L").save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def _validate_inpaint_request(value: Mapping[str, int] | None) -> tuple[int, int]:
    if value is None:
        return 0, 0
    if not isinstance(value, Mapping) or set(value) != {"dilate", "feather"}:
        raise ServingError("inpaint must be null or exactly {dilate, feather}")
    if any(isinstance(value[key], bool) or not isinstance(value[key], int) for key in value):
        raise ServingError("inpaint dilation and feather must be integers")
    dilation, feather = int(value["dilate"]), int(value["feather"])
    if not 0 <= dilation <= 512 or not 0 <= feather <= 512:
        raise ServingError("inpaint dilation and feather must be in [0, 512]")
    return dilation, feather


def _encoded_label_maps(
    masks: Mapping[str, np.ndarray],
    shape: tuple[int, int],
    *,
    ontology_version: str = V1_ONTOLOGY_VERSION,
) -> dict[str, str]:
    maps: dict[str, np.ndarray] = {}
    ontology = ontology_for_version(ontology_version)
    for name, mask in masks.items():
        label = ontology.label(name)
        if label.map not in {"part", "material"} or label.id is None:
            raise ServingError(f"label-map return requires indexed atomic label: {name}")
        target = maps.setdefault(label.map, np.zeros(shape, dtype=np.uint16))
        conflict = mask & (target != 0) & (target != int(label.id))
        if conflict.any():
            raise ServingError(f"predicted {label.map} masks overlap; label map would be ambiguous")
        target[mask] = int(label.id)
    encoded = {}
    for map_name, values in maps.items():
        output = io.BytesIO()
        if map_name == "part":
            Image.fromarray(values).save(output, format="PNG")
        else:
            Image.fromarray(values.astype(np.uint8), mode="L").save(output, format="PNG")
        encoded[map_name] = base64.b64encode(output.getvalue()).decode("ascii")
    return encoded
