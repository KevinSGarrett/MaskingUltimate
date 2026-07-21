"""Governed same-image visual-box exemplars for official SAM 3.1 discovery."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from maskfactory.validation import require_valid_document

AUTHORITY = "same_image_visual_prompt_only_no_mask_or_gold_authority"


class Sam31VisualExemplarError(ValueError):
    """A visual-exemplar manifest is invalid, stale, or bound to another image."""


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _array_sha256(value: np.ndarray) -> str:
    array = np.ascontiguousarray(value)
    digest = hashlib.sha256()
    digest.update(array.dtype.str.encode("ascii"))
    digest.update(json.dumps(list(array.shape), separators=(",", ":")).encode("utf-8"))
    digest.update(array.tobytes())
    return digest.hexdigest()


def _source_identity(source_image: Path) -> tuple[str, str, int, int]:
    path = Path(source_image)
    if not path.is_file():
        raise Sam31VisualExemplarError("SAM 3.1 visual-exemplar source image is missing")
    try:
        with Image.open(path) as image:
            rgb = np.asarray(image.convert("RGB"))
    except (OSError, ValueError) as exc:
        raise Sam31VisualExemplarError(
            "SAM 3.1 visual-exemplar source image is unreadable"
        ) from exc
    height, width = rgb.shape[:2]
    return _file_sha256(path), _array_sha256(rgb), width, height


def _normalize_bbox(
    bbox_xyxy: Sequence[float], *, width: int, height: int
) -> tuple[float, float, float, float]:
    if isinstance(bbox_xyxy, (str, bytes)) or len(bbox_xyxy) != 4:
        raise Sam31VisualExemplarError("SAM 3.1 visual-exemplar bbox must contain four values")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in bbox_xyxy):
        raise Sam31VisualExemplarError("SAM 3.1 visual-exemplar bbox values must be numeric")
    x1, y1, x2, y2 = (float(value) for value in bbox_xyxy)
    if not all(math.isfinite(value) for value in (x1, y1, x2, y2)):
        raise Sam31VisualExemplarError("SAM 3.1 visual-exemplar bbox values must be finite")
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise Sam31VisualExemplarError("SAM 3.1 visual-exemplar bbox is outside its source image")
    return x1, y1, x2, y2


def write_sam31_visual_exemplar(
    output_path: Path,
    *,
    source_image: Path,
    bbox_xyxy: Sequence[float],
    polarity: str = "positive",
) -> Path:
    """Write one closed, self-hashed visual-box prompt bound to an exact source image."""
    if polarity not in {"positive", "negative"}:
        raise Sam31VisualExemplarError(
            "SAM 3.1 visual-exemplar polarity must be positive or negative"
        )
    file_sha256, rgb_sha256, width, height = _source_identity(source_image)
    bbox = _normalize_bbox(bbox_xyxy, width=width, height=height)
    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "kind": "same_image_visual_box",
        "source_image_file_sha256": file_sha256,
        "source_image_rgb_sha256": rgb_sha256,
        "source_width": width,
        "source_height": height,
        "bbox_xyxy": list(bbox),
        "polarity": polarity,
        "authority": AUTHORITY,
    }
    document["sha256"] = _canonical_sha256(document)
    require_valid_document(document, "sam31_visual_exemplar")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, destination)
    finally:
        temporary = Path(temporary_name)
        if temporary.exists():
            temporary.unlink()
    return destination


def load_sam31_visual_exemplar(manifest_path: Path, *, source_image: Path) -> dict[str, Any]:
    """Validate one manifest and require an exact match to the target source image."""
    path = Path(manifest_path)
    if not path.is_file() or path.suffix.lower() != ".json":
        raise Sam31VisualExemplarError(
            "SAM 3.1 exemplars must be governed same-image visual-exemplar JSON manifests"
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Sam31VisualExemplarError("SAM 3.1 visual-exemplar manifest is unreadable") from exc
    if not isinstance(document, Mapping):
        raise Sam31VisualExemplarError("SAM 3.1 visual-exemplar manifest must be an object")
    try:
        require_valid_document(document, "sam31_visual_exemplar")
    except ValueError as exc:
        raise Sam31VisualExemplarError(
            f"SAM 3.1 visual-exemplar manifest failed schema validation: {exc}"
        ) from exc
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if document["sha256"] != _canonical_sha256(payload):
        raise Sam31VisualExemplarError("SAM 3.1 visual-exemplar document hash is stale")
    file_sha256, rgb_sha256, width, height = _source_identity(source_image)
    expected_identity = {
        "source_image_file_sha256": file_sha256,
        "source_image_rgb_sha256": rgb_sha256,
        "source_width": width,
        "source_height": height,
    }
    if any(document.get(key) != value for key, value in expected_identity.items()):
        raise Sam31VisualExemplarError(
            "SAM 3.1 visual exemplar is bound to a different source image"
        )
    bbox = _normalize_bbox(document["bbox_xyxy"], width=width, height=height)
    return {
        "bbox_xyxy": list(bbox),
        "polarity": document["polarity"],
        "manifest_sha256": document["sha256"],
        "manifest_file_sha256": _file_sha256(path),
    }


__all__ = [
    "AUTHORITY",
    "Sam31VisualExemplarError",
    "load_sam31_visual_exemplar",
    "write_sam31_visual_exemplar",
]
