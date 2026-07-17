"""Provider-neutral SAM 3D Body geometry adapter with fail-closed fallback."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .adapters import provider_contract_metadata
from .contracts import BoxProposal, GeometryProvider, ProviderIdentity

ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = ROOT / "env/sam3d_body_runtime.lock.json"
REQUIRED_ARRAYS = {
    "pred_vertices": 3,
    "pred_keypoints_3d": 3,
    "pred_keypoints_2d": 2,
    "pred_cam_t": 1,
}


class Sam3dBodyGeometryError(ValueError):
    """SAM 3D Body output cannot be tied to the requested person and frame."""


Backend = Callable[..., Sequence[Mapping[str, Any]]]


def sam3d_body_identity(lock_path: Path = LOCK_PATH) -> ProviderIdentity:
    """Build exact provider identity from the governed runtime lock."""
    path = Path(lock_path)
    lock = json.loads(path.read_text(encoding="utf-8"))
    if (
        lock.get("provider") != "sam3d_body"
        or lock.get("checkpoint", {}).get("downloaded") is not True
        or lock.get("authority", {}).get("may_author_gold") is not False
    ):
        raise Sam3dBodyGeometryError("SAM 3D Body runtime lock is not install-ready")
    return ProviderIdentity(
        "sam3d_body",
        "geometry_provider",
        "sam3d_body",
        str(lock["source"]["commit"]),
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )


class Sam3dBodyGeometryProvider:
    """Adapt exact single-box upstream output into the GeometryProvider contract."""

    def __init__(self, backend: Backend, *, identity: ProviderIdentity | None = None) -> None:
        self.identity = identity or sam3d_body_identity()
        if self.identity.provider_key != "sam3d_body" or self.identity.role != "geometry_provider":
            raise Sam3dBodyGeometryError("SAM 3D Body provider identity is invalid")
        self._backend = backend

    def infer_geometry(self, image_path: Path, *, person_box: BoxProposal) -> Mapping[str, Any]:
        path = Path(image_path)
        if not path.is_file():
            raise Sam3dBodyGeometryError("SAM 3D Body input image is missing")
        if not person_box.instance_key:
            raise Sam3dBodyGeometryError("requested person requires an immutable instance key")
        requested = np.asarray(person_box.bbox_xyxy, dtype=np.float32)
        outputs = tuple(self._backend(path, bboxes=requested.reshape(1, 4)))
        if len(outputs) != 1 or not isinstance(outputs[0], Mapping):
            raise Sam3dBodyGeometryError(
                "explicit single-person SAM 3D Body request must return exactly one result"
            )
        raw = outputs[0]
        observed_box = _finite_array(raw.get("bbox"), "bbox", columns=4).reshape(-1)
        if observed_box.shape != (4,) or float(np.max(np.abs(observed_box - requested))) > 1.0:
            raise Sam3dBodyGeometryError("SAM 3D Body result does not own the requested person box")
        focal = np.asarray(raw.get("focal_length"), dtype=np.float64).reshape(-1)
        if focal.size not in {1, 2} or not np.all(np.isfinite(focal)) or np.any(focal <= 0):
            raise Sam3dBodyGeometryError("SAM 3D Body focal length is invalid")
        arrays: dict[str, np.ndarray] = {}
        for name, columns in REQUIRED_ARRAYS.items():
            value = _finite_array(raw.get(name), name, columns=columns)
            if name == "pred_cam_t" and value.reshape(-1).shape != (3,):
                raise Sam3dBodyGeometryError("SAM 3D Body camera translation must have 3 values")
            arrays[name] = value.copy()
        image_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        output_sha256 = _geometry_sha256(observed_box, focal, arrays)
        return {
            "provider": self.identity.provider_key,
            "person_instance_key": person_box.instance_key,
            "requested_bbox_xyxy": tuple(float(value) for value in requested),
            "observed_bbox_xyxy": tuple(float(value) for value in observed_box),
            "focal_length": tuple(float(value) for value in focal),
            **arrays,
            "coordinate_frames": {
                "input_box": "full_image_pixels_xyxy",
                "keypoints_2d": "full_image_pixels_xy_upstream_sam3d_body",
                "vertices_3d": "upstream_sam3d_body_native_camera_frame_unconverted",
                "keypoints_3d": "upstream_sam3d_body_native_camera_frame_unconverted",
                "camera_translation": "upstream_sam3d_body_native_camera_frame_unconverted",
                "implicit_axis_conversion": False,
            },
            "provenance": {
                **provider_contract_metadata(self.identity),
                "image_sha256": image_sha256,
                "selection": "explicit_single_requested_bbox",
                "person_instance_key": person_box.instance_key,
                "output_sha256": output_sha256,
                "may_author_gold": False,
            },
        }


class GeometryProviderWithOomFallback:
    """Use the challenger only when it succeeds; fallback solely on a real OOM."""

    def __init__(self, challenger: GeometryProvider, fallback: GeometryProvider) -> None:
        self.identity = challenger.identity
        self._challenger = challenger
        self._fallback = fallback

    def infer_geometry(self, image_path: Path, *, person_box: BoxProposal) -> Mapping[str, Any]:
        try:
            result = dict(self._challenger.infer_geometry(Path(image_path), person_box=person_box))
        except Exception as exc:
            if not _is_oom(exc):
                raise
            result = dict(self._fallback.infer_geometry(Path(image_path), person_box=person_box))
            result["routing"] = {
                "attempted_provider": self._challenger.identity.provider_key,
                "used_provider": self._fallback.identity.provider_key,
                "fallback_reason": "out_of_memory",
                "fallback_exception_type": type(exc).__name__,
                "production_route_changed": False,
            }
            return result
        result["routing"] = {
            "attempted_provider": self._challenger.identity.provider_key,
            "used_provider": self._challenger.identity.provider_key,
            "fallback_reason": None,
            "production_route_changed": False,
        }
        return result


def _finite_array(value: Any, name: str, *, columns: int) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise Sam3dBodyGeometryError(f"SAM 3D Body {name} is not numeric") from exc
    if array.size == 0 or not np.all(np.isfinite(array)):
        raise Sam3dBodyGeometryError(f"SAM 3D Body {name} is empty or non-finite")
    if columns == 1:
        return array
    if array.ndim == 1:
        if array.shape != (columns,):
            raise Sam3dBodyGeometryError(f"SAM 3D Body {name} has invalid dimensions")
    elif array.ndim != 2 or array.shape[1] < columns:
        raise Sam3dBodyGeometryError(f"SAM 3D Body {name} has invalid dimensions")
    return array


def _geometry_sha256(bbox: np.ndarray, focal: np.ndarray, arrays: Mapping[str, np.ndarray]) -> str:
    digest = hashlib.sha256()
    for name, value in (("bbox", bbox), ("focal_length", focal), *sorted(arrays.items())):
        array = np.ascontiguousarray(value, dtype=np.float64)
        digest.update(name.encode("utf-8"))
        digest.update(json.dumps(list(array.shape), separators=(",", ":")).encode("utf-8"))
        digest.update(array.tobytes())
    return digest.hexdigest()


def _is_oom(exc: Exception) -> bool:
    if isinstance(exc, MemoryError) or type(exc).__name__ == "OutOfMemoryError":
        return True
    if isinstance(exc, RuntimeError):
        message = str(exc).lower()
        return "out of memory" in message and ("cuda" in message or "gpu" in message)
    return False


__all__ = [
    "GeometryProviderWithOomFallback",
    "Sam3dBodyGeometryError",
    "Sam3dBodyGeometryProvider",
    "sam3d_body_identity",
]
