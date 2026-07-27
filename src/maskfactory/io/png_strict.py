"""png_strict: the ONE and ONLY mask writer for MaskFactory (doc 03 §1, MF-P0-08.03).

Every mask PNG in the project is written through this module. Direct
``cv2.imwrite`` / ``PIL.Image.save`` on mask paths anywhere else is banned by CI
(MF-P0-08.04 / pitfall 5 / QC-030 parity) precisely so the gold format invariants
below can never be violated by an accidental alternate write path.

Gold binary invariants (doc 03 §1):
  * PNG only (never JPG/WebP).
  * 1-channel grayscale, mode ``L``, 8-bit. No alpha, no palette.
  * Values are hard binary: exactly {0, 255}. Anything else -> reject (QC-002).
  * Dimensions equal the source W x H exactly (QC-001).
  * No anti-aliasing anywhere (callers use nearest-neighbour only).
  * Lossless PNG, zlib compress level 6, ``optimize=False``.

Label maps (doc 03 §1 / doc 02): ``label_map_part.png`` is 16-bit indexed,
``label_map_material.png`` is 8-bit indexed. Inpaint/matting ramps are a separate
*derived* grayscale artifact (0-255 allowed, doc 03 §6/§7) and are never gold.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from PIL import Image

# PNG compression: doc 03 §1 requires zlib level 6, never lossy, never optimized.
_COMPRESS_LEVEL = 6
_PNG = ".png"


class PngStrictError(ValueError):
    """Raised when an array or path violates the gold mask format contract."""


def _require_png(path: Path) -> Path:
    path = Path(path)
    if path.suffix.lower() != _PNG:
        raise PngStrictError(f"mask files must be .png (never JPG/WebP): {path.name}")
    return path


def _check_2d(arr: np.ndarray) -> None:
    if arr.ndim != 2:
        raise PngStrictError(f"mask array must be 2-D (H, W); got shape {arr.shape}")


def _check_dims(arr: np.ndarray, source_size: Optional[Tuple[int, int]]) -> None:
    if source_size is None:
        return
    w, h = source_size  # source_size is (width, height) per PIL convention
    if arr.shape != (h, w):
        raise PngStrictError(f"mask dims {arr.shape[1]}x{arr.shape[0]} != source {w}x{h} (QC-001)")


def _binary_uint8(arr: np.ndarray) -> np.ndarray:
    """Coerce to a strict {0,255} uint8 array or raise (QC-002)."""
    if arr.dtype == np.bool_:
        return arr.astype(np.uint8) * 255
    if arr.dtype != np.uint8:
        raise PngStrictError(
            f"binary mask must be bool or uint8, got dtype {arr.dtype} "
            "(no silent casting -- caller must produce exact {0,255})"
        )
    extra = set(np.unique(arr).tolist()) - {0, 255}
    if extra:
        raise PngStrictError(
            f"binary mask has non-{{0,255}} values {sorted(extra)[:8]} (QC-002 reject)"
        )
    return arr


def write_binary_mask(
    path, arr: np.ndarray, *, source_size: Optional[Tuple[int, int]] = None
) -> Path:
    """Write a gold binary mask. Enforces mode L / 8-bit / {0,255} / exact dims."""
    path = _require_png(path)
    arr = np.asarray(arr)
    _check_2d(arr)
    arr = _binary_uint8(arr)
    _check_dims(arr, source_size)
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.fromarray(arr, mode="L")
    img.save(path, format="PNG", optimize=False, compress_level=_COMPRESS_LEVEL)
    return path


def write_label_map(path, arr: np.ndarray, *, bits: int) -> Path:
    """Write an indexed label map: bits=16 (label_map_part) or bits=8 (material)."""
    path = _require_png(path)
    arr = np.asarray(arr)
    _check_2d(arr)
    if bits == 16:
        if arr.min() < 0 or arr.max() > 0xFFFF:
            raise PngStrictError("16-bit label map values must fit in 0..65535")
        img = Image.fromarray(arr.astype(np.uint16))  # mode I;16
    elif bits == 8:
        if arr.min() < 0 or arr.max() > 0xFF:
            raise PngStrictError("8-bit label map values must fit in 0..255")
        img = Image.fromarray(arr.astype(np.uint8), mode="L")
    else:
        raise PngStrictError(f"label map bits must be 8 or 16, got {bits}")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG", optimize=False, compress_level=_COMPRESS_LEVEL)
    return path


def write_grayscale(
    path, arr: np.ndarray, *, source_size: Optional[Tuple[int, int]] = None
) -> Path:
    """Write a DERIVED 0-255 grayscale ramp (inpaint feather / matte, doc 03 §6/§7).

    Not gold: the {0,255} binary assertion deliberately does not apply here.
    """
    path = _require_png(path)
    arr = np.asarray(arr)
    _check_2d(arr)
    if arr.dtype != np.uint8:
        raise PngStrictError(f"grayscale ramp must be uint8 (0-255), got {arr.dtype}")
    _check_dims(arr, source_size)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr, mode="L").save(
        path, format="PNG", optimize=False, compress_level=_COMPRESS_LEVEL
    )
    return path


def read_mask(path) -> np.ndarray:
    """Read a PNG mask back as a numpy array (mode preserved). Used by QA + self-test."""
    with Image.open(path) as im:
        return np.array(im)


def self_test() -> bool:
    """Built-in self-test (MF-P0-08.03). Returns True iff every invariant holds."""
    import tempfile

    ok = True
    tmp = Path(tempfile.mkdtemp(prefix="png_strict_"))

    def check(cond: bool, msg: str) -> None:
        nonlocal ok
        status = "PASS" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"  [{status}] {msg}")

    # 1) binary round-trip preserves mode/values/shape
    a = np.zeros((40, 30), dtype=np.uint8)
    a[10:20, 5:15] = 255
    p = write_binary_mask(tmp / "bin.png", a, source_size=(30, 40))
    with Image.open(p) as im:
        check(im.mode == "L", f"binary saved as mode L (got {im.mode})")
        back = np.array(im)
    check(back.shape == (40, 30), f"dims preserved (got {back.shape})")
    check(set(np.unique(back).tolist()) <= {0, 255}, "values stay in {0,255}")
    check(np.array_equal(back, a), "round-trip is bit-exact")

    # 2) bool input scales to 255
    b = np.zeros((8, 8), dtype=bool)
    b[0, 0] = True
    pb = write_binary_mask(tmp / "boolean.png", b)
    check(int(read_mask(pb).max()) == 255, "bool True -> 255")

    # 3) non-binary uint8 rejected
    try:
        write_binary_mask(tmp / "bad.png", np.full((4, 4), 128, np.uint8))
        check(False, "non-binary {128} should raise")
    except PngStrictError:
        check(True, "non-binary value rejected (QC-002)")

    # 4) wrong dims vs source rejected
    try:
        write_binary_mask(tmp / "dim.png", a, source_size=(99, 99))
        check(False, "wrong dims should raise")
    except PngStrictError:
        check(True, "dim mismatch rejected (QC-001)")

    # 5) non-png path rejected
    try:
        write_binary_mask(tmp / "nope.jpg", a)
        check(False, ".jpg should raise")
    except PngStrictError:
        check(True, "non-PNG extension rejected")

    # 6) 16-bit label map round-trip preserves large indices
    lm = np.array([[0, 1, 55], [256, 4096, 60000]], dtype=np.uint16)
    plm = write_label_map(tmp / "label_map_part.png", lm, bits=16)
    back16 = read_mask(plm).astype(np.uint16)
    check(np.array_equal(back16, lm), "16-bit label map round-trips exactly")

    # 7) grayscale ramp allows 0-255 (not asserted binary)
    ramp = np.tile(np.arange(256, dtype=np.uint8), (4, 1))
    pr = write_grayscale(tmp / "inpaint_ramp.png", ramp)
    check(
        int(read_mask(pr).max()) == 255 and int(read_mask(pr).min()) == 0,
        "grayscale ramp 0..255 written",
    )

    print(f"png_strict self-test: {'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return ok


if __name__ == "__main__":
    sys.exit(0 if self_test() else 1)
