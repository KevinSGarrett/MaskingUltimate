"""Persist and verify isolated official SAM 3.1 specialist-lane shadow candidates."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ..io.hashing import sha256_file
from ..io.png_strict import write_binary_mask
from ..validation import ArtifactValidationError, require_valid_document
from .benchmark_policy import load_specialist_margin_manifest
from .contracts import MaskProposal
from .sam31_shadow import DEFAULT_RUNTIME_LOCK, OFFICIAL_PROVIDER_KEY, sam31_provider_identity

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PIPELINE = ROOT / "configs" / "pipeline.yaml"
PACKAGE_AUTHORITY = (
    "isolated_sam31_specialist_candidates_only_"
    "no_active_map_serving_semantic_mask_or_gold_authority"
)
LANE_TO_ROLE = {
    "accessory": "clothing_accessory_segmentation",
    "chest_pelvic": "chest_pelvic_segmentation",
    "clothing": "clothing_accessory_segmentation",
    "foot_toe": "foot_toe_segmentation",
    "hair": "hair_matting",
    "hand_finger": "hand_finger_segmentation",
    "repeated_instance": "repeated_instance_segmentation",
}
_SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")


class Sam31CandidatePackageError(ValueError):
    """A persisted SAM 3.1 candidate package is incomplete, stale, or unsafe."""


@dataclass(frozen=True)
class Sam31LaneCandidate:
    candidate_id: str
    lane: str
    semantic_label: str
    instance_key: str
    proposal: MaskProposal


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _runtime_identity(path: Path) -> dict[str, str]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("provider") != OFFICIAL_PROVIDER_KEY:
        raise Sam31CandidatePackageError("candidate runtime lock is not official SAM 3.1")
    return {
        "runtime_lock_sha256": sha256_file(Path(path)),
        "source_commit": document["source"]["commit"],
        "checkpoint_sha256": document["checkpoint"]["sha256"],
    }


def governed_lane_labels() -> dict[str, frozenset[str]]:
    """Return the frozen semantic-label vocabulary for each SAM 3.1 lane."""
    manifest, _ = load_specialist_margin_manifest()
    roles = manifest["roles"]
    mapping = {lane: frozenset(roles[role]["hard_labels"]) for lane, role in LANE_TO_ROLE.items()}
    mapping["accessory"] = frozenset({"accessory"})
    mapping["clothing"] = mapping["clothing"] - {"accessory"}
    return mapping


def _strict_mask(path: Path, shape: tuple[int, int]) -> np.ndarray:
    with Image.open(path) as image:
        value = np.asarray(image)
        mode = image.mode
        image_format = image.format
    if (
        image_format != "PNG"
        or mode != "L"
        or value.shape != shape
        or set(np.unique(value).tolist()) - {0, 255}
    ):
        raise Sam31CandidatePackageError(f"candidate mask is not strict PNG: {path}")
    mask = value == 255
    if not mask.any():
        raise Sam31CandidatePackageError(f"candidate mask is empty: {path}")
    return mask


def _bbox(mask: np.ndarray) -> list[int]:
    ys, xs = np.nonzero(mask)
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def _safe_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise Sam31CandidatePackageError("candidate artifact path is invalid")
    root = Path(root).resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise Sam31CandidatePackageError("candidate artifact path escapes package") from exc
    if not path.is_file():
        raise Sam31CandidatePackageError("candidate artifact is missing")
    return path


def _atomic_json(path: Path, document: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_sam31_candidate_package(
    *,
    source_image_path: Path,
    candidates: Sequence[Sam31LaneCandidate],
    output_dir: Path,
    pipeline_path: Path = DEFAULT_PIPELINE,
    runtime_lock_path: Path = DEFAULT_RUNTIME_LOCK,
) -> Path:
    """Write strict candidates and a sealed manifest without changing provider selection."""
    source_image_path = Path(source_image_path)
    pipeline_path = Path(pipeline_path)
    output_dir = Path(output_dir)
    if not candidates:
        raise Sam31CandidatePackageError("candidate package requires candidates")
    with Image.open(source_image_path) as image:
        width, height = image.size
    shape = (height, width)
    pipeline_before = sha256_file(pipeline_path)
    runtime = _runtime_identity(runtime_lock_path)
    allowed = governed_lane_labels()
    seen_ids: set[str] = set()
    seen_routes: set[tuple[str, str, str]] = set()
    rows = []
    for candidate in sorted(candidates, key=lambda value: (value.lane, value.candidate_id)):
        proposal = candidate.proposal
        route = (candidate.lane, candidate.semantic_label, candidate.instance_key)
        if _SAFE_ID.fullmatch(candidate.candidate_id) is None or candidate.candidate_id in seen_ids:
            raise Sam31CandidatePackageError("candidate IDs must be safe and unique")
        if route in seen_routes or not candidate.instance_key:
            raise Sam31CandidatePackageError("candidate lane/label/instance route is duplicated")
        if (
            candidate.lane not in LANE_TO_ROLE
            or candidate.semantic_label not in allowed[candidate.lane]
        ):
            raise Sam31CandidatePackageError("candidate lane or semantic label is not governed")
        if (
            proposal.provider
            != sam31_provider_identity(proposal.provider.role, lock_path=runtime_lock_path)
            or proposal.mask.shape != shape
            or not proposal.mask.any()
        ):
            raise Sam31CandidatePackageError("candidate provider or image identity is stale")
        seen_ids.add(candidate.candidate_id)
        seen_routes.add(route)
        relative = Path("masks") / candidate.lane / f"{candidate.candidate_id}.png"
        mask_path = output_dir / relative
        write_binary_mask(mask_path, proposal.mask, source_size=(width, height))
        strict = _strict_mask(mask_path, shape)
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "lane": candidate.lane,
                "benchmark_role": LANE_TO_ROLE[candidate.lane],
                "semantic_label": candidate.semantic_label,
                "instance_key": candidate.instance_key,
                "mask_path": relative.as_posix(),
                "mask_sha256": sha256_file(mask_path),
                "foreground_pixels": int(strict.sum()),
                "bbox_xyxy": _bbox(strict),
                "confidence": proposal.confidence,
                "prompt_fingerprint": proposal.prompt_fingerprint,
                "provider_role": proposal.provider.role,
                "provider_runtime_fingerprint": proposal.provider.runtime_fingerprint,
            }
        )
    if sha256_file(pipeline_path) != pipeline_before:
        raise Sam31CandidatePackageError("active provider map changed during candidate packaging")
    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "provider_key": OFFICIAL_PROVIDER_KEY,
        "model_family": "sam3",
        "source_image_sha256": sha256_file(source_image_path),
        "source_width": width,
        "source_height": height,
        "pipeline_sha256_before": pipeline_before,
        "pipeline_sha256_after": pipeline_before,
        **runtime,
        "enabled_lanes": sorted({row["lane"] for row in rows}),
        "candidate_count": len(rows),
        "candidates": rows,
        "authority": PACKAGE_AUTHORITY,
    }
    document["sha256"] = _canonical_sha256(document)
    try:
        require_valid_document(document, "sam31_shadow_candidate_package")
    except ArtifactValidationError as exc:
        raise Sam31CandidatePackageError(str(exc)) from exc
    path = output_dir / "sam31_shadow_candidates.json"
    _atomic_json(path, document)
    verify_sam31_candidate_package(
        path,
        artifact_root=output_dir,
        pipeline_path=pipeline_path,
        runtime_lock_path=runtime_lock_path,
    )
    return path


def verify_sam31_candidate_package(
    manifest_path: Path,
    *,
    artifact_root: Path,
    pipeline_path: Path = DEFAULT_PIPELINE,
    runtime_lock_path: Path = DEFAULT_RUNTIME_LOCK,
) -> dict[str, Any]:
    """Verify schema, seals, current identities, strict PNGs, and exact lane routing."""
    document = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    try:
        require_valid_document(document, "sam31_shadow_candidate_package")
    except ArtifactValidationError as exc:
        raise Sam31CandidatePackageError(str(exc)) from exc
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if document["sha256"] != _canonical_sha256(payload):
        raise Sam31CandidatePackageError("candidate package hash mismatch")
    runtime = _runtime_identity(runtime_lock_path)
    if any(document[key] != value for key, value in runtime.items()):
        raise Sam31CandidatePackageError("candidate package runtime identity is stale")
    pipeline = sha256_file(Path(pipeline_path))
    if (
        document["pipeline_sha256_before"] != pipeline
        or document["pipeline_sha256_after"] != pipeline
    ):
        raise Sam31CandidatePackageError("candidate package active-map identity is stale")
    allowed = governed_lane_labels()
    seen_paths: set[str] = set()
    seen_ids: set[str] = set()
    seen_routes: set[tuple[str, str, str]] = set()
    for row in document["candidates"]:
        route = (row["lane"], row["semantic_label"], row["instance_key"])
        expected_identity = sam31_provider_identity(
            row["provider_role"], lock_path=runtime_lock_path
        )
        if (
            row["candidate_id"] in seen_ids
            or row["mask_path"] in seen_paths
            or route in seen_routes
            or row["benchmark_role"] != LANE_TO_ROLE.get(row["lane"])
            or row["semantic_label"] not in allowed.get(row["lane"], ())
            or row["provider_runtime_fingerprint"] != expected_identity.runtime_fingerprint
        ):
            raise Sam31CandidatePackageError("candidate routing is duplicated or invalid")
        path = _safe_path(artifact_root, row["mask_path"])
        mask = _strict_mask(path, (document["source_height"], document["source_width"]))
        if (
            sha256_file(path) != row["mask_sha256"]
            or int(mask.sum()) != row["foreground_pixels"]
            or _bbox(mask) != row["bbox_xyxy"]
        ):
            raise Sam31CandidatePackageError("candidate artifact evidence is stale")
        seen_ids.add(row["candidate_id"])
        seen_paths.add(row["mask_path"])
        seen_routes.add(route)
    if document["candidate_count"] != len(document["candidates"]):
        raise Sam31CandidatePackageError("candidate count is inconsistent")
    if document["enabled_lanes"] != sorted({row["lane"] for row in document["candidates"]}):
        raise Sam31CandidatePackageError("candidate enabled-lane set is inconsistent")
    return {
        "candidate_count": document["candidate_count"],
        "enabled_lanes": document["enabled_lanes"],
        "sha256": document["sha256"],
        "authority": PACKAGE_AUTHORITY,
    }


__all__ = [
    "LANE_TO_ROLE",
    "PACKAGE_AUTHORITY",
    "Sam31CandidatePackageError",
    "Sam31LaneCandidate",
    "governed_lane_labels",
    "verify_sam31_candidate_package",
    "write_sam31_candidate_package",
]
