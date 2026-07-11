"""Dependency-light, read-only ComfyUI package-reader nodes."""

from __future__ import annotations

import base64
import io
import json
import os
import urllib.error
import urllib.request
import uuid
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PACKAGES_ROOT = ROOT / "data/packages"
FORMAT_MAJOR = 1


class ComfyPackageError(ValueError):
    """A package cannot be safely exposed to ComfyUI."""


def packages_root() -> Path:
    configured = Path(__file__).with_name("config.json")
    if configured.is_file():
        try:
            config_root = json.loads(configured.read_text(encoding="utf-8"))["packages_root"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ComfyPackageError(f"invalid MaskFactory node config: {configured}") from exc
    else:
        config_root = DEFAULT_PACKAGES_ROOT
    return Path(os.environ.get("MASKFACTORY_PACKAGES_ROOT", config_root))


def list_package_pairs(
    root: Path | None = None,
    *,
    status: str = "human_approved_gold",
    search: str = "",
) -> tuple[tuple[str, int], ...]:
    """List approved (image_id, person_index) pairs, including legacy p0 packages."""
    root = Path(root or packages_root())
    pairs = []
    for image_root in sorted(path for path in root.glob("img_*") if path.is_dir()):
        nested = sorted(path for path in (image_root / "instances").glob("p*") if path.is_dir())
        candidates = nested or [image_root]
        for fallback, package in enumerate(candidates):
            try:
                person_index = int(package.name[1:]) if package != image_root else fallback
            except ValueError:
                continue
            manifest_path = package / "manifest.json"
            if not manifest_path.is_file():
                continue
            manifest = _manifest(package)
            statuses = {
                str(entry.get("status"))
                for entry in manifest.get("parts", {}).values()
                if isinstance(entry, dict)
            }
            if status and status not in statuses:
                continue
            if search and search.lower() not in image_root.name.lower():
                continue
            pairs.append((image_root.name, person_index))
    return tuple(pairs)


def resolve_package(image_id: str, person_index: int = 0, root: Path | None = None) -> Path:
    if not image_id.startswith("img_") or person_index < 0:
        raise ComfyPackageError("image_id/person_index is invalid")
    root = Path(root or packages_root())
    nested = root / image_id / "instances" / f"p{person_index}"
    legacy = root / image_id
    package = nested if nested.is_dir() else legacy if person_index == 0 else nested
    if not (package / "manifest.json").is_file():
        available = list_package_pairs(root, status="")
        nearest = ", ".join(f"{name}/p{index}" for name, index in available[:8])
        raise ComfyPackageError(
            f"package {image_id}/p{person_index} not found; available: {nearest or 'none'}"
        )
    _manifest(package)
    return package


def assert_workflow_output_target(target: Path, root: Path | None = None) -> Path:
    """Reject any attempted ComfyUI output inside the immutable package truth tree."""
    truth_root = Path(root or packages_root()).resolve()
    resolved = Path(target).resolve()
    try:
        resolved.relative_to(truth_root)
    except ValueError:
        return resolved
    raise ComfyPackageError(
        f"ComfyUI node output may not mutate MaskFactory package truth: {resolved}"
    )


class MFPackageBrowser:
    CATEGORY = "MaskFactory/Package"
    RETURN_TYPES = ("STRING", "INT", "INT")
    RETURN_NAMES = ("image_id", "person_index", "count")
    FUNCTION = "browse"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "status": ("STRING", {"default": "human_approved_gold"}),
                "search": ("STRING", {"default": ""}),
                "index": ("INT", {"default": 0, "min": 0}),
            }
        }

    def browse(self, status: str, search: str, index: int):
        pairs = list_package_pairs(status=status, search=search)
        if not pairs:
            raise ComfyPackageError("no packages match the requested status/search")
        image_id, person_index = pairs[index % len(pairs)]
        return image_id, person_index, len(pairs)


class _ImagePackageNode:
    @classmethod
    def _package_inputs(cls, extra: dict[str, Any] | None = None):
        required: dict[str, Any] = {
            "image_id": ("STRING", {"default": ""}),
            "person_index": ("INT", {"default": 0, "min": 0}),
        }
        required.update(extra or {})
        return {"required": required}


class MFLoadSource(_ImagePackageNode):
    CATEGORY = "MaskFactory/Load"
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "load"
    INPUT_TYPES = classmethod(lambda cls: cls._package_inputs())

    def load(self, image_id: str, person_index: int = 0):
        package = resolve_package(image_id, person_index)
        source = _source(package)
        with Image.open(source) as opened:
            rgb = np.asarray(opened.convert("RGB"), dtype=np.float32) / 255.0
        return (torch.from_numpy(rgb).unsqueeze(0),)


class MFLoadGoldMask(_ImagePackageNode):
    CATEGORY = "MaskFactory/Load"
    RETURN_TYPES = ("MASK",)
    FUNCTION = "load"

    @classmethod
    def INPUT_TYPES(cls):
        return cls._package_inputs(
            {
                "label": ("STRING", {"default": "left_forearm"}),
                "on_missing": (["error", "empty"], {"default": "error"}),
            }
        )

    def load(
        self,
        image_id: str,
        person_index: int = 0,
        label: str = "left_forearm",
        on_missing: str = "error",
    ):
        return (
            _load_mask(
                resolve_package(image_id, person_index), Path("masks") / f"{label}.png", on_missing
            ),
        )


class MFLoadUnionMask(MFLoadGoldMask):
    FUNCTION = "load_union"

    def load_union(
        self,
        image_id: str,
        person_index: int = 0,
        label: str = "both_hands",
        on_missing: str = "error",
    ):
        package = resolve_package(image_id, person_index)
        for directory in ("masks_derived", "masks_regions"):
            candidate = package / directory / f"{label}.png"
            if candidate.is_file():
                return (_mask_tensor(candidate, package),)
        return (_missing_mask(package, label, on_missing),)


class MFLoadProjectedRegion(MFLoadGoldMask):
    CATEGORY = "MaskFactory/Load (NON-TRUTH Projected)"
    FUNCTION = "load_projected"

    def load_projected(
        self,
        image_id: str,
        person_index: int = 0,
        label: str = "left_breast_projected_region",
        on_missing: str = "error",
    ):
        return (
            _load_mask(
                resolve_package(image_id, person_index),
                Path("projected") / f"{label}.png",
                on_missing,
            ),
        )


class MFLoadInpaintMask(_ImagePackageNode):
    CATEGORY = "MaskFactory/Load"
    RETURN_TYPES = ("MASK",)
    FUNCTION = "load"

    @classmethod
    def INPUT_TYPES(cls):
        return cls._package_inputs(
            {
                "label": ("STRING", {"default": "left_hand"}),
                "dilate_px": ("INT", {"default": 8, "min": 0}),
                "feather_px": ("INT", {"default": 4, "min": 0}),
                "mode": (["existing", "derive"], {"default": "existing"}),
            }
        )

    def load(
        self,
        image_id: str,
        person_index: int = 0,
        label: str = "left_hand",
        dilate_px: int = 8,
        feather_px: int = 4,
        mode: str = "existing",
    ):
        package = resolve_package(image_id, person_index)
        if mode == "existing":
            path = package / "inpaint" / f"inpaint_{label}_d{dilate_px}f{feather_px}.png"
            if not path.is_file():
                raise ComfyPackageError(f"existing inpaint mask missing: {path.name}")
            return (_mask_tensor(path, package, binary=False),)
        source = _find_label_binary(package, label)
        mask = np.asarray(Image.open(source).convert("L")) > 0
        scale = max(mask.shape) / 1024
        ramp = _feathered_dilation(mask, round(dilate_px * scale), round(feather_px * scale))
        return (torch.from_numpy(ramp.astype(np.float32) / 255.0),)


class MFMaskFromLabelMap(_ImagePackageNode):
    CATEGORY = "MaskFactory/Load"
    RETURN_TYPES = ("MASK",)
    FUNCTION = "load"

    @classmethod
    def INPUT_TYPES(cls):
        return cls._package_inputs(
            {
                "map_name": (["part", "material"], {"default": "part"}),
                "label_id": ("INT", {"default": 1, "min": 0}),
            }
        )

    def load(
        self,
        image_id: str,
        person_index: int = 0,
        map_name: str = "part",
        label_id: int = 1,
    ):
        package = resolve_package(image_id, person_index)
        path = package / f"label_map_{map_name}.png"
        labels = np.asarray(Image.open(path))
        _check_shape(labels.shape, package)
        return (torch.from_numpy((labels == label_id).astype(np.float32)),)


class MFCombineMasks:
    CATEGORY = "MaskFactory/Mask"
    RETURN_TYPES = ("MASK",)
    FUNCTION = "combine"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mask_a": ("MASK",),
                "mask_b": ("MASK",),
                "op": (["union", "intersect", "subtract", "xor"],),
                "binarize": ("BOOLEAN", {"default": True}),
            }
        }

    def combine(self, mask_a, mask_b, op: str, binarize: bool = True):
        a, b = torch.as_tensor(mask_a), torch.as_tensor(mask_b)
        if a.shape != b.shape:
            raise ComfyPackageError("mask shape mismatch; resizing is forbidden")
        if binarize:
            aa, bb = a > 0.5, b > 0.5
            operations = {
                "union": aa | bb,
                "intersect": aa & bb,
                "subtract": aa & ~bb,
                "xor": aa ^ bb,
            }
            return (operations[op].float(),)
        operations = {
            "union": torch.maximum(a, b),
            "intersect": torch.minimum(a, b),
            "subtract": torch.clamp(a - b, 0, 1),
            "xor": torch.abs(a - b),
        }
        return (operations[op],)


class MFMaskStats:
    CATEGORY = "MaskFactory/QA"
    RETURN_TYPES = ("STRING",)
    FUNCTION = "stats"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"mask": ("MASK",)}}

    def stats(self, mask):
        array = np.asarray(torch.as_tensor(mask).detach().cpu()) > 0.5
        if array.ndim == 3 and array.shape[0] == 1:
            array = array[0]
        if array.ndim != 2:
            raise ComfyPackageError("Mask Stats requires one HxW mask")
        ys, xs = np.nonzero(array)
        document = {
            "area_px": int(array.sum()),
            "area_pct": float(100 * array.mean()),
            "bbox_xyxy": None
            if not len(xs)
            else [
                int(xs.min()),
                int(ys.min()),
                int(xs.max()) + 1,
                int(ys.max()) + 1,
            ],
            "components": _component_count(array),
        }
        return (json.dumps(document, sort_keys=True),)


class MFPredictMasks:
    CATEGORY = "MaskFactory/Predict"
    RETURN_TYPES = ("MASK", "STRING", "STRING")
    RETURN_NAMES = ("masks", "labels", "manifest_json")
    FUNCTION = "predict"

    def __init__(self, transport=None):
        self.transport = transport or _multipart_predict

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "labels": ("STRING", {"default": "left_forearm"}),
                "dilate_px": ("INT", {"default": 0, "min": 0}),
                "feather_px": ("INT", {"default": 0, "min": 0}),
            }
        }

    def predict(self, image, labels: str, dilate_px: int = 0, feather_px: int = 0):
        tensor = torch.as_tensor(image).detach().cpu()
        if tensor.ndim != 4 or tensor.shape[0] != 1 or tensor.shape[-1] != 3:
            raise ComfyPackageError("MF Predict Masks requires one IMAGE tensor [1,H,W,3]")
        array = np.asarray(torch.clamp(tensor[0], 0, 1) * 255, dtype=np.uint8)
        output = io.BytesIO()
        Image.fromarray(array, mode="RGB").save(output, format="PNG")
        requested = tuple(value.strip() for value in labels.split(",") if value.strip())
        if not requested:
            raise ComfyPackageError("MF Predict Masks requires at least one label")
        try:
            response = self.transport(
                _api_url() + "/predict",
                fields={
                    "labels": ",".join(requested),
                    "return_mode": "binaries",
                    "inpaint": json.dumps({"dilate": dilate_px, "feather": feather_px}),
                },
                files={"image": ("image.png", output.getvalue(), "image/png")},
            )
        except (OSError, ValueError, urllib.error.URLError) as exc:
            raise ComfyPackageError(
                "MaskFactory API unavailable; run `maskfactory serve --port 8765`: " + str(exc)
            ) from exc
        if response.get("status") != "draft_model_generated" or response.get("labels") != list(
            requested
        ):
            raise ComfyPackageError("MaskFactory API response metadata does not match the request")
        masks = []
        for label in requested:
            try:
                decoded = base64.b64decode(response["masks"][label], validate=True)
                mask = np.asarray(Image.open(io.BytesIO(decoded)).convert("L"))
            except (KeyError, ValueError, OSError) as exc:
                raise ComfyPackageError(f"API mask payload invalid for {label}") from exc
            if mask.shape != array.shape[:2]:
                raise ComfyPackageError(f"API mask dimensions differ for {label}")
            masks.append(torch.from_numpy(mask.astype(np.float32) / 255.0))
        return torch.stack(masks), ",".join(requested), json.dumps(response, sort_keys=True)


def _manifest(package: Path) -> dict[str, Any]:
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    version = str(manifest.get("format_version", manifest.get("schema_version", "1.0.0")))
    try:
        major = int(version.split(".", 1)[0])
    except ValueError as exc:
        raise ComfyPackageError(f"invalid package format version: {version}") from exc
    if major > FORMAT_MAJOR:
        raise ComfyPackageError(
            f"package format {version} is newer than node-pack major {FORMAT_MAJOR}"
        )
    return manifest


def _source(package: Path) -> Path:
    path = next(
        (package / name for name in ("source.png", "source.jpg") if (package / name).is_file()),
        None,
    )
    if path is None:
        raise ComfyPackageError("package source image is missing")
    return path


def _check_shape(shape: tuple[int, ...], package: Path) -> None:
    with Image.open(_source(package)) as source:
        expected = (source.height, source.width)
    if tuple(shape) != expected:
        raise ComfyPackageError(
            f"mask dimensions {tuple(shape)} != source {expected}; resizing is forbidden"
        )


def _mask_tensor(path: Path, package: Path, *, binary: bool = True) -> torch.Tensor:
    array = np.asarray(Image.open(path).convert("L"))
    _check_shape(array.shape, package)
    if binary and not set(np.unique(array)).issubset({0, 255}):
        raise ComfyPackageError(f"gold mask is not strict binary: {path}")
    return torch.from_numpy(array.astype(np.float32) / 255.0)


def _load_mask(package: Path, relative: Path, on_missing: str) -> torch.Tensor:
    path = package / relative
    return (
        _mask_tensor(path, package)
        if path.is_file()
        else _missing_mask(package, relative.stem, on_missing)
    )


def _missing_mask(package: Path, label: str, on_missing: str) -> torch.Tensor:
    if on_missing != "empty":
        raise ComfyPackageError(f"mask {label!r} is missing")
    warnings.warn(f"MaskFactory mask {label!r} missing; returning empty mask", stacklevel=2)
    with Image.open(_source(package)) as source:
        return torch.zeros((source.height, source.width), dtype=torch.float32)


def _find_label_binary(package: Path, label: str) -> Path:
    for directory in ("masks", "masks_derived", "masks_regions", "protected"):
        path = package / directory / f"{label}.png"
        if path.is_file():
            return path
    raise ComfyPackageError(f"no binary source for inpaint label {label!r}")


def _dilate(mask: np.ndarray, count: int) -> np.ndarray:
    result = mask.astype(bool)
    for _ in range(count):
        padded = np.pad(result, 1)
        result = (
            padded[1:-1, 1:-1]
            | padded[:-2, 1:-1]
            | padded[2:, 1:-1]
            | padded[1:-1, :-2]
            | padded[1:-1, 2:]
        )
    return result


def _feathered_dilation(mask: np.ndarray, dilate_px: int, feather_px: int) -> np.ndarray:
    core = _dilate(mask, dilate_px)
    result = core.astype(np.uint8) * 255
    previous = core
    for distance in range(1, feather_px + 1):
        expanded = _dilate(previous, 1)
        result[expanded & ~previous] = round(255 * (feather_px - distance + 1) / (feather_px + 1))
        previous = expanded
    return result


def _component_count(mask: np.ndarray) -> int:
    pending = set(map(tuple, np.argwhere(mask)))
    count = 0
    while pending:
        count += 1
        stack = [pending.pop()]
        while stack:
            y, x = stack.pop()
            for neighbor in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if neighbor in pending:
                    pending.remove(neighbor)
                    stack.append(neighbor)
    return count


def _api_url() -> str:
    configured = Path(__file__).with_name("config.json")
    if not configured.is_file():
        return "http://127.0.0.1:8765"
    return str(json.loads(configured.read_text(encoding="utf-8"))["api_url"]).rstrip("/")


def _multipart_predict(
    url: str, *, fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]
):
    boundary = "maskfactory-" + uuid.uuid4().hex
    body = bytearray()
    for name, value in fields.items():
        body.extend(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    for name, (filename, content, content_type) in files.items():
        body.extend(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
            f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode()
        )
        body.extend(content)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


NODE_CLASS_MAPPINGS = {
    "MFPackageBrowser": MFPackageBrowser,
    "MFLoadSource": MFLoadSource,
    "MFLoadGoldMask": MFLoadGoldMask,
    "MFLoadUnionMask": MFLoadUnionMask,
    "MFLoadProjectedRegion": MFLoadProjectedRegion,
    "MFLoadInpaintMask": MFLoadInpaintMask,
    "MFMaskFromLabelMap": MFMaskFromLabelMap,
    "MFCombineMasks": MFCombineMasks,
    "MFMaskStats": MFMaskStats,
    "MFPredictMasks": MFPredictMasks,
}

NODE_DISPLAY_NAME_MAPPINGS = {name: "MF " + name.removeprefix("MF") for name in NODE_CLASS_MAPPINGS}
