"""Host-side procedural primitive render/decode without DAZ assets (MF-P9-03.09).

STATIC_PASS only: synthesizes and golden-verifies analytic RGB/instance/PART plus
depth/normals primitives on the host. Never launches DAZ Studio, never loads DAZ
store assets, and never claims accepted/training/gold/live authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image

from ...validation import ArtifactValidationError, require_valid_document

# OpenCV reads OPENCV_IO_ENABLE_OPENEXR only at first imgcodecs init.
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"

PROOF_TIER = "STATIC_PASS"
AUTHORITY = "daz_procedural_primitive_host_static_only"
ARTIFACT_TYPE = "daz_procedural_primitive_bundle"
SCHEMA_VERSION = "1.0.0"
EXECUTOR = "host_procedural_primitive"
PRIMITIVE_KIND = "analytic_front_plane"
DEFAULT_MASTER_SEED = 20260719
DEFAULT_WIDTH = 64
DEFAULT_HEIGHT = 48
DEFAULT_DEPTH_M = 2.0
DEFAULT_PART_ID = 4  # chest_upper_torso
DEFAULT_INSTANCE_ID = 1
NORMALS_EXPECTED = (0.0, 0.0, -1.0)
VISIBLE_SLICE = (8, 40, 10, 54)  # y0,y1,x0,x1


class ProceduralPrimitiveError(ValueError):
    """Host procedural primitive contract failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _canonical_sha(document: Mapping[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthesize_primitive_arrays(
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    depth_m: float = DEFAULT_DEPTH_M,
    part_id: int = DEFAULT_PART_ID,
    instance_id: int = DEFAULT_INSTANCE_ID,
    master_seed: int = DEFAULT_MASTER_SEED,
) -> dict[str, np.ndarray]:
    """Synthesize deterministic analytic front-plane arrays (no DAZ)."""
    if width < 8 or height < 8 or width > 512 or height > 512:
        raise ProceduralPrimitiveError("resolution_out_of_range")
    if not (0.0 < depth_m <= 100.0):
        raise ProceduralPrimitiveError("depth_m_out_of_range")
    if part_id < 1 or part_id > 55:
        raise ProceduralPrimitiveError("part_id_out_of_range")
    if instance_id != DEFAULT_INSTANCE_ID:
        raise ProceduralPrimitiveError("instance_id_must_be_one")
    if master_seed < 0:
        raise ProceduralPrimitiveError("master_seed_invalid")

    y0, y1, x0, x1 = VISIBLE_SLICE
    if not (0 <= y0 < y1 <= height and 0 <= x0 < x1 <= width):
        raise ProceduralPrimitiveError("visible_slice_out_of_bounds")

    rng = np.random.default_rng(master_seed)
    # Background is deterministic dark noise; plane is flat analytic color.
    rgb = (rng.integers(8, 24, size=(height, width, 3), dtype=np.uint8)).astype(np.uint8)
    instance = np.zeros((height, width), dtype=np.uint16)
    part = np.zeros((height, width), dtype=np.uint16)
    depth = np.full((height, width), np.inf, dtype=np.float32)
    normals = np.zeros((height, width, 3), dtype=np.float32)

    rgb[y0:y1, x0:x1] = (48, 160, 220)
    instance[y0:y1, x0:x1] = np.uint16(instance_id)
    part[y0:y1, x0:x1] = np.uint16(part_id)
    depth[y0:y1, x0:x1] = np.float32(depth_m)
    normals[y0:y1, x0:x1] = np.asarray(NORMALS_EXPECTED, dtype=np.float32)

    return {
        "rgb": rgb,
        "instance": instance,
        "part": part,
        "depth": depth,
        "normals": normals,
    }


def _enable_openexr() -> None:
    os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"


def _write_arrays(root: Path, arrays: Mapping[str, np.ndarray]) -> dict[str, Path]:
    _enable_openexr()
    import cv2

    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "rgb": root / "rgb.png",
        "instance": root / "instance.png",
        "part": root / "part.png",
        "depth": root / "depth.exr",
        "normals": root / "normals.exr",
    }
    Image.fromarray(arrays["rgb"], mode="RGB").save(paths["rgb"], format="PNG")
    Image.fromarray(arrays["instance"]).save(paths["instance"], format="PNG")
    Image.fromarray(arrays["part"]).save(paths["part"], format="PNG")
    if not cv2.imwrite(str(paths["depth"]), arrays["depth"]):
        raise ProceduralPrimitiveError("depth_exr_write_failed")
    # OpenCV stores BGR channel order for 3-channel EXR; invert xyz -> zyx write.
    if not cv2.imwrite(str(paths["normals"]), arrays["normals"][..., ::-1]):
        raise ProceduralPrimitiveError("normals_exr_write_failed")
    return paths


def _artifact_record(path: Path, relative_path: str, encoding: str) -> dict[str, Any]:
    return {
        "relative_path": relative_path,
        "sha256": _file_sha(path),
        "bytes": path.stat().st_size,
        "encoding": encoding,
    }


def build_procedural_primitive_bundle(
    output_dir: Path,
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    depth_m: float = DEFAULT_DEPTH_M,
    part_id: int = DEFAULT_PART_ID,
    master_seed: int = DEFAULT_MASTER_SEED,
) -> dict[str, Any]:
    """Render host-side primitive artifacts and seal a schema-valid bundle."""
    arrays = synthesize_primitive_arrays(
        width=width,
        height=height,
        depth_m=depth_m,
        part_id=part_id,
        master_seed=master_seed,
    )
    paths = _write_arrays(Path(output_dir), arrays)
    y0, y1, x0, x1 = VISIBLE_SLICE
    visible = int((y1 - y0) * (x1 - x0))
    artifacts = {
        "rgb": _artifact_record(paths["rgb"], "rgb.png", "rgb_png"),
        "instance": _artifact_record(paths["instance"], "instance.png", "uint16_png"),
        "part": _artifact_record(paths["part"], "part.png", "uint16_png"),
        "depth": _artifact_record(paths["depth"], "depth.exr", "float32_exr"),
        "normals": _artifact_record(paths["normals"], "normals.exr", "float32_rgb_exr"),
    }
    draft: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "primitive_kind": PRIMITIVE_KIND,
        "master_seed": master_seed,
        "resolution": [width, height],
        "depth_m": float(depth_m),
        "part_id": part_id,
        "instance_id": DEFAULT_INSTANCE_ID,
        "executor": EXECUTOR,
        "live_daz_execution": False,
        "daz_assets_used": False,
        "training_eligible": False,
        "accepted": False,
        "gold_claimed": False,
        "artifacts": artifacts,
        "analytic_checks": {
            "depth_unit": "meter",
            "depth_quantity": "camera_view_axis_z",
            "depth_constant_on_visible": True,
            "normals_handedness": "right_handed",
            "normals_unit_length": True,
            "normals_expected_vector": list(NORMALS_EXPECTED),
            "visible_pixel_count": visible,
        },
        "golden_hashes": {
            "rgb": artifacts["rgb"]["sha256"],
            "instance": artifacts["instance"]["sha256"],
            "part": artifacts["part"]["sha256"],
            "depth": artifacts["depth"]["sha256"],
            "normals": artifacts["normals"]["sha256"],
            "bundle": "0" * 64,
        },
    }
    content = {key: value for key, value in draft.items() if key != "bundle_id"}
    content["golden_hashes"] = {
        **draft["golden_hashes"],
        "bundle": "0" * 64,
    }
    digest = _canonical_sha(content)
    draft["bundle_id"] = f"daz_proc_prim_{digest[:24]}"
    draft["canonical_sha256"] = digest
    draft["golden_hashes"]["bundle"] = digest
    return validate_procedural_primitive_bundle(draft, artifact_root=Path(output_dir))


def validate_procedural_primitive_bundle(
    document: Mapping[str, Any],
    *,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Schema + analytic decode verification; refuse authority escalation."""
    try:
        require_valid_document(document, ARTIFACT_TYPE)
    except ArtifactValidationError as exc:
        raise ProceduralPrimitiveError(f"primitive_bundle_schema_invalid:{exc}") from exc

    if document["live_daz_execution"] or document["daz_assets_used"]:
        raise ProceduralPrimitiveError("live_daz_or_assets_forbidden")
    if document["training_eligible"] or document["accepted"] or document["gold_claimed"]:
        raise ProceduralPrimitiveError("authority_escalation_forbidden")
    if document["executor"] != EXECUTOR:
        raise ProceduralPrimitiveError("executor_must_be_host_procedural_primitive")

    expected = synthesize_primitive_arrays(
        width=int(document["resolution"][0]),
        height=int(document["resolution"][1]),
        depth_m=float(document["depth_m"]),
        part_id=int(document["part_id"]),
        master_seed=int(document["master_seed"]),
    )
    y0, y1, x0, x1 = VISIBLE_SLICE
    visible_depth = expected["depth"][y0:y1, x0:x1]
    if not np.allclose(visible_depth, document["depth_m"], rtol=0, atol=0):
        raise ProceduralPrimitiveError("analytic_depth_mismatch")
    visible_normals = expected["normals"][y0:y1, x0:x1]
    lengths = np.linalg.norm(visible_normals, axis=-1)
    if not np.allclose(lengths, 1.0, rtol=0, atol=1e-6):
        raise ProceduralPrimitiveError("analytic_normals_nonunit")
    if not np.allclose(visible_normals, NORMALS_EXPECTED, rtol=0, atol=1e-6):
        raise ProceduralPrimitiveError("analytic_normals_vector_mismatch")

    content = {
        key: value
        for key, value in document.items()
        if key not in {"bundle_id", "canonical_sha256"}
    }
    content["golden_hashes"] = {**document["golden_hashes"], "bundle": "0" * 64}
    digest = _canonical_sha(content)
    if document["canonical_sha256"] != digest or document["golden_hashes"]["bundle"] != digest:
        raise ProceduralPrimitiveError("bundle_hash_mismatch")
    if document["bundle_id"] != f"daz_proc_prim_{digest[:24]}":
        raise ProceduralPrimitiveError("bundle_id_mismatch")

    if artifact_root is not None:
        root = Path(artifact_root)
        for role, meta in document["artifacts"].items():
            path = (root / meta["relative_path"]).resolve()
            if not str(path).startswith(str(root.resolve())):
                raise ProceduralPrimitiveError("artifact_path_escape")
            if not path.is_file():
                raise ProceduralPrimitiveError(f"artifact_missing:{role}")
            digest_file = _file_sha(path)
            if digest_file != meta["sha256"] or digest_file != document["golden_hashes"][role]:
                raise ProceduralPrimitiveError(f"artifact_hash_mismatch:{role}")
            if path.stat().st_size != meta["bytes"]:
                raise ProceduralPrimitiveError(f"artifact_bytes_mismatch:{role}")
            # Decode round-trip against expected arrays for PNG roles.
            if role in {"rgb", "instance", "part"}:
                arr = np.asarray(Image.open(path))
                if not np.array_equal(arr, expected[role]):
                    raise ProceduralPrimitiveError(f"artifact_decode_mismatch:{role}")
            elif role in {"depth", "normals"}:
                _enable_openexr()
                import cv2

                flags = cv2.IMREAD_ANYDEPTH | (
                    cv2.IMREAD_COLOR if role == "normals" else cv2.IMREAD_UNCHANGED
                )
                decoded = cv2.imread(str(path), flags)
                if decoded is None:
                    raise ProceduralPrimitiveError(f"artifact_exr_decode_failed:{role}")
                if role == "normals":
                    decoded = decoded[..., ::-1]
                if not np.allclose(decoded, expected[role], rtol=0, atol=1e-5, equal_nan=True):
                    # inf background: compare with equal_nan and allow inf equality
                    if role == "depth":
                        finite = np.isfinite(expected[role])
                        if not np.array_equal(np.isfinite(decoded), finite):
                            raise ProceduralPrimitiveError("depth_finite_mask_mismatch")
                        if not np.allclose(
                            decoded[finite], expected[role][finite], rtol=0, atol=1e-5
                        ):
                            raise ProceduralPrimitiveError("depth_decode_mismatch")
                    else:
                        raise ProceduralPrimitiveError("normals_decode_mismatch")

    return dict(document)


def republish_primitive_artifacts(document: Mapping[str, Any], output_dir: Path) -> dict[str, Any]:
    """Rebuild host-side artifacts from sealed seed params and verify golden hashes."""
    rebuilt = build_procedural_primitive_bundle(
        output_dir,
        width=int(document["resolution"][0]),
        height=int(document["resolution"][1]),
        depth_m=float(document["depth_m"]),
        part_id=int(document["part_id"]),
        master_seed=int(document["master_seed"]),
    )
    if rebuilt["canonical_sha256"] != document["canonical_sha256"]:
        raise ProceduralPrimitiveError("republish_canonical_mismatch")
    if rebuilt["golden_hashes"] != document["golden_hashes"]:
        raise ProceduralPrimitiveError("republish_golden_hash_mismatch")
    return rebuilt


def publish_procedural_primitive_bundle(
    document: Mapping[str, Any],
    artifact_root: Path,
    publish_root: Path,
    *,
    include_binary_artifacts: bool = False,
) -> tuple[Path, bool]:
    """Immutably publish bundle JSON under publish_root.

    Binary PNG/EXR artifacts stay local by default (Git prohibits EXR/bulk media).
    Golden verification regenerates from sealed seed parameters.
    """
    validated = validate_procedural_primitive_bundle(document, artifact_root=artifact_root)
    publish_root = Path(publish_root)
    target_dir = publish_root / validated["bundle_id"]
    manifest_path = target_dir / "bundle.json"
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing != validated:
            raise ProceduralPrimitiveError("published_bundle_immutable")
        return manifest_path, False

    target_dir.mkdir(parents=True, exist_ok=True)
    if include_binary_artifacts:
        for role, meta in validated["artifacts"].items():
            source = Path(artifact_root) / meta["relative_path"]
            destination = target_dir / meta["relative_path"]
            destination.write_bytes(source.read_bytes())
            if _file_sha(destination) != meta["sha256"]:
                raise ProceduralPrimitiveError(f"publish_hash_drift:{role}")

    payload = json.dumps(validated, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix="daz_proc_prim_", suffix=".json", dir=str(target_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
        os.replace(tmp_name, manifest_path)
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
    return manifest_path, True


__all__ = [
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "DEFAULT_DEPTH_M",
    "DEFAULT_HEIGHT",
    "DEFAULT_MASTER_SEED",
    "DEFAULT_PART_ID",
    "DEFAULT_WIDTH",
    "EXECUTOR",
    "NORMALS_EXPECTED",
    "PRIMITIVE_KIND",
    "PROOF_TIER",
    "SCHEMA_VERSION",
    "ProceduralPrimitiveError",
    "build_procedural_primitive_bundle",
    "publish_procedural_primitive_bundle",
    "republish_primitive_artifacts",
    "synthesize_primitive_arrays",
    "validate_procedural_primitive_bundle",
]
