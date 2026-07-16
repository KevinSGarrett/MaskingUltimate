"""Lifecycle-aware official SAM 3.1 repair proposals with zero map authority."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from PIL import Image

from ..autonomy.repair import evaluate_repair_candidate
from ..io.hashing import sha256_file
from ..io.png_strict import write_binary_mask
from ..ontology import get_ontology
from ..validation import ArtifactValidationError, require_valid_document
from .contracts import InteractiveSegmenter, ProviderIdentity
from .sam31_orchestration import RUNNABLE_LIFECYCLES
from .sam31_shadow import (
    DEFAULT_RUNTIME_LOCK,
    OFFICIAL_PROVIDER_KEY,
    SHADOW_AUTHORITY,
    sam31_provider_identity,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PIPELINE = ROOT / "configs" / "pipeline.yaml"
REPAIR_AUTHORITY = (
    "official_sam31_repair_proposals_only_" "no_active_map_semantic_mask_serving_or_gold_authority"
)
NONCOMPLETION_STATUSES = frozenset({"skipped_unavailable", "complete_no_candidates", "failed"})


class Sam31RepairError(ValueError):
    """Official SAM 3.1 repair evidence is malformed, stale, or over-authoritative."""


@dataclass(frozen=True)
class Sam31RepairRequest:
    """One bounded semantic-label repair request in full crop coordinates."""

    label: str
    roi_xyxy: tuple[int, int, int, int]
    positive_points: tuple[tuple[int, int], ...]
    negative_points: tuple[tuple[int, int], ...]
    current_mask: np.ndarray
    protected_mask: np.ndarray
    person_bbox_xyxy: tuple[int, int, int, int] | None = None


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _array_sha256(value: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()


def _identity_document(identity: ProviderIdentity) -> dict[str, Any]:
    return {
        "provider_key": identity.provider_key,
        "role": identity.role,
        "model_family": identity.model_family,
        "source_commit": identity.source_commit,
        "runtime_fingerprint": identity.runtime_fingerprint,
        "contract_version": identity.contract_version,
        "provenance_aliases": list(identity.provenance_aliases),
    }


def _atomic_json(path: Path, document: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _base_document(
    *,
    source_image_path: Path,
    parent_instance_key: str,
    lifecycle_state: str,
    pipeline_path: Path,
    runtime_lock_path: Path,
) -> dict[str, Any]:
    source_image_path = Path(source_image_path)
    if not source_image_path.is_file() or not parent_instance_key:
        raise Sam31RepairError("SAM 3.1 repair source image and parent instance are required")
    with Image.open(source_image_path) as image:
        width, height = image.size
    pipeline_sha256 = sha256_file(Path(pipeline_path))
    return {
        "schema_version": "1.0.0",
        "provider_key": OFFICIAL_PROVIDER_KEY,
        "lifecycle_state": lifecycle_state,
        "source_image_sha256": sha256_file(source_image_path),
        "source_width": width,
        "source_height": height,
        "parent_instance_key": parent_instance_key,
        "expected_provider_identity": _identity_document(
            sam31_provider_identity("interactive_segmenter", lock_path=runtime_lock_path)
        ),
        "pipeline_sha256_before": pipeline_sha256,
        "pipeline_sha256_after": pipeline_sha256,
        "authority": REPAIR_AUTHORITY,
    }


def _write_document(output_dir: Path, document: dict[str, Any]) -> Path:
    document["sha256"] = _canonical_sha256(document)
    try:
        require_valid_document(document, "sam31_repair_orchestration")
    except ArtifactValidationError as exc:
        raise Sam31RepairError(str(exc)) from exc
    path = Path(output_dir) / "orchestration.json"
    _atomic_json(path, document)
    return path


def write_sam31_repair_noncompletion(
    *,
    source_image_path: Path,
    parent_instance_key: str,
    lifecycle_state: str,
    output_dir: Path,
    status: Literal["skipped_unavailable", "complete_no_candidates", "failed"],
    reason: str,
    pipeline_path: Path = DEFAULT_PIPELINE,
    runtime_lock_path: Path = DEFAULT_RUNTIME_LOCK,
) -> Path:
    """Persist an explicit zero-authority repair skip/failure."""
    if status not in NONCOMPLETION_STATUSES or not reason.strip():
        raise Sam31RepairError("SAM 3.1 repair noncompletion status or reason is invalid")
    output_dir = Path(output_dir)
    shutil.rmtree(output_dir / "candidates", ignore_errors=True)
    document = _base_document(
        source_image_path=source_image_path,
        parent_instance_key=parent_instance_key,
        lifecycle_state=lifecycle_state,
        pipeline_path=pipeline_path,
        runtime_lock_path=runtime_lock_path,
    )
    document.update(
        {
            "status": status,
            "reason": reason.strip(),
            "request_count": 0,
            "proposal_count": 0,
            "accepted_candidate_count": 0,
            "requests": [],
        }
    )
    return _write_document(output_dir, document)


def _validate_request(request: Sam31RepairRequest, image_shape: tuple[int, int]) -> None:
    get_ontology().label(request.label, require_enabled=True)
    current = np.asarray(request.current_mask)
    protected = np.asarray(request.protected_mask)
    if (
        current.dtype != np.bool_
        or protected.dtype != np.bool_
        or current.shape != image_shape
        or protected.shape != image_shape
        or not current.any()
    ):
        raise Sam31RepairError("SAM 3.1 repair request masks are invalid")
    left, top, right, bottom = request.roi_xyxy
    height, width = image_shape
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise Sam31RepairError("SAM 3.1 repair ROI is outside image geometry")
    if not request.positive_points:
        raise Sam31RepairError("SAM 3.1 repair requires a positive point")
    for point in (*request.positive_points, *request.negative_points):
        if (
            len(point) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in point)
            or not (0 <= point[0] < width and 0 <= point[1] < height)
        ):
            raise Sam31RepairError("SAM 3.1 repair point is outside image geometry")
    if len(set(request.positive_points) & set(request.negative_points)):
        raise Sam31RepairError("SAM 3.1 repair point polarity conflicts")


def run_sam31_repair_orchestration(
    *,
    source_image_path: Path,
    parent_instance_key: str,
    lifecycle_state: str,
    interactive_segmenter: InteractiveSegmenter,
    requests: Sequence[Sam31RepairRequest],
    output_dir: Path,
    repair_policy: Mapping[str, Any],
    pipeline_path: Path = DEFAULT_PIPELINE,
    runtime_lock_path: Path = DEFAULT_RUNTIME_LOCK,
) -> Path:
    """Materialize only guard-passing SAM 3.1 repair masks in an isolated sidecar."""
    if lifecycle_state not in RUNNABLE_LIFECYCLES:
        raise Sam31RepairError("SAM 3.1 repair lifecycle is not runnable")
    expected = sam31_provider_identity("interactive_segmenter", lock_path=runtime_lock_path)
    if (
        not isinstance(interactive_segmenter, InteractiveSegmenter)
        or interactive_segmenter.identity != expected
        or getattr(interactive_segmenter, "authority", None) != SHADOW_AUTHORITY
    ):
        raise Sam31RepairError("SAM 3.1 repair loader identity or authority is not official shadow")
    maximum = int(repair_policy["maximum_total_candidates_per_label"])
    if maximum < 1 or maximum > 12:
        raise Sam31RepairError("SAM 3.1 repair candidate limit must be within 1..12")
    source_image_path = Path(source_image_path)
    pipeline_sha256_before = sha256_file(Path(pipeline_path))
    with Image.open(source_image_path) as source:
        image = np.asarray(source.convert("RGB"))
    normalized_requests = tuple(requests)
    if not normalized_requests:
        return write_sam31_repair_noncompletion(
            source_image_path=source_image_path,
            parent_instance_key=parent_instance_key,
            lifecycle_state=lifecycle_state,
            output_dir=output_dir,
            status="complete_no_candidates",
            reason="no bounded workhorse repair plan requested official SAM 3.1",
            pipeline_path=pipeline_path,
            runtime_lock_path=runtime_lock_path,
        )
    keys = [(request.label, request.roi_xyxy) for request in normalized_requests]
    if len(keys) != len(set(keys)):
        raise Sam31RepairError("SAM 3.1 repair requests must have unique label/ROI keys")
    for request in normalized_requests:
        _validate_request(request, image.shape[:2])
    embedding = interactive_segmenter.embed(image)
    output_dir = Path(output_dir)
    candidate_root = output_dir / "candidates"
    shutil.rmtree(candidate_root, ignore_errors=True)
    request_documents = []
    proposal_count = 0
    accepted_count = 0
    for request_index, request in enumerate(normalized_requests):
        current = np.asarray(request.current_mask)
        protected = np.asarray(request.protected_mask)
        roi_mask = np.zeros(current.shape, dtype=bool)
        left, top, right, bottom = request.roi_xyxy
        roi_mask[top:bottom, left:right] = True
        mask_prompt = current & roi_mask
        prompt = {
            "positive_points": request.positive_points,
            "negative_points": request.negative_points,
            "box_xyxy": request.roi_xyxy,
            "mask_prompt": mask_prompt if mask_prompt.any() else None,
        }
        proposals = tuple(interactive_segmenter.refine(embedding, prompt=prompt))
        if len(proposals) > maximum:
            raise Sam31RepairError("SAM 3.1 repair exceeded the bounded candidate limit")
        proposal_documents = []
        for proposal_index, proposal in enumerate(proposals):
            proposal_count += 1
            if proposal.provider != expected:
                raise Sam31RepairError("SAM 3.1 repair proposal has stale provider identity")
            candidate = np.asarray(proposal.mask)
            guard = evaluate_repair_candidate(
                candidate,
                current_mask=current,
                protected_mask=protected,
                label=request.label,
                roi_xyxy=request.roi_xyxy,
                person_bbox_xyxy=request.person_bbox_xyxy,
                ordinary_max_changed_fraction=float(repair_policy["ordinary_max_changed_fraction"]),
                reconstruction_max_changed_fraction=float(
                    repair_policy["reconstruction_max_changed_fraction"]
                ),
                maximum_protected_overlap_fraction=float(
                    repair_policy["maximum_protected_overlap_fraction"]
                ),
                maximum_outside_roi_fraction=float(repair_policy["maximum_outside_roi_fraction"]),
                expected_area_slack=float(repair_policy["expected_area_slack"]),
            )
            candidate_id = f"sam31-repair-{request_index:03d}-{proposal_index:02d}"
            relative_path = None
            file_sha256 = None
            if guard.eligible:
                path = candidate_root / f"{candidate_id}.png"
                write_binary_mask(path, candidate.astype(np.uint8) * 255)
                relative_path = path.relative_to(output_dir).as_posix()
                file_sha256 = sha256_file(path)
                accepted_count += 1
            proposal_documents.append(
                {
                    "candidate_id": candidate_id,
                    "confidence": proposal.confidence,
                    "prompt_fingerprint": proposal.prompt_fingerprint,
                    "eligible": guard.eligible,
                    "guard": asdict(guard) | {"vetoes": list(guard.vetoes)},
                    "mask_sha256": _array_sha256(candidate),
                    "candidate_path": relative_path,
                    "candidate_file_sha256": file_sha256,
                }
            )
        request_documents.append(
            {
                "label": request.label,
                "roi_xyxy": list(request.roi_xyxy),
                "positive_points": [list(point) for point in request.positive_points],
                "negative_points": [list(point) for point in request.negative_points],
                "current_mask_sha256": _array_sha256(current),
                "protected_mask_sha256": _array_sha256(protected),
                "person_bbox_xyxy": (
                    list(request.person_bbox_xyxy) if request.person_bbox_xyxy is not None else None
                ),
                "proposals": proposal_documents,
            }
        )
    if sha256_file(Path(pipeline_path)) != pipeline_sha256_before:
        raise Sam31RepairError("active provider map changed during SAM 3.1 repair")
    document = _base_document(
        source_image_path=source_image_path,
        parent_instance_key=parent_instance_key,
        lifecycle_state=lifecycle_state,
        pipeline_path=pipeline_path,
        runtime_lock_path=runtime_lock_path,
    )
    document.update(
        {
            "status": "complete",
            "reason": None,
            "request_count": len(request_documents),
            "proposal_count": proposal_count,
            "accepted_candidate_count": accepted_count,
            "requests": request_documents,
        }
    )
    if document["pipeline_sha256_before"] != pipeline_sha256_before:
        raise Sam31RepairError("active provider map changed during SAM 3.1 repair")
    path = _write_document(output_dir, document)
    verify_sam31_repair_orchestration(
        path,
        artifact_root=output_dir,
        source_image_path=source_image_path,
        pipeline_path=pipeline_path,
        runtime_lock_path=runtime_lock_path,
    )
    return path


def verify_sam31_repair_orchestration(
    manifest_path: Path,
    *,
    artifact_root: Path,
    source_image_path: Path,
    pipeline_path: Path = DEFAULT_PIPELINE,
    runtime_lock_path: Path = DEFAULT_RUNTIME_LOCK,
) -> dict[str, Any]:
    """Recompute manifest, source, provider, active-map, and candidate file identities."""
    document = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    try:
        require_valid_document(document, "sam31_repair_orchestration")
    except ArtifactValidationError as exc:
        raise Sam31RepairError(str(exc)) from exc
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if document["sha256"] != _canonical_sha256(payload):
        raise Sam31RepairError("SAM 3.1 repair orchestration hash mismatch")
    if document["source_image_sha256"] != sha256_file(Path(source_image_path)):
        raise Sam31RepairError("SAM 3.1 repair source identity is stale")
    pipeline_sha256 = sha256_file(Path(pipeline_path))
    if (
        document["pipeline_sha256_before"] != pipeline_sha256
        or document["pipeline_sha256_after"] != pipeline_sha256
    ):
        raise Sam31RepairError("SAM 3.1 repair active-map identity is stale")
    expected = _identity_document(
        sam31_provider_identity("interactive_segmenter", lock_path=runtime_lock_path)
    )
    if document["expected_provider_identity"] != expected:
        raise Sam31RepairError("SAM 3.1 repair provider identity is stale")
    root = Path(artifact_root).resolve()
    seen: set[str] = set()
    accepted = 0
    proposal_count = 0
    for request in document["requests"]:
        for proposal in request["proposals"]:
            proposal_count += 1
            candidate_id = proposal["candidate_id"]
            if candidate_id in seen:
                raise Sam31RepairError("SAM 3.1 repair candidate identity is duplicated")
            seen.add(candidate_id)
            if proposal["eligible"]:
                accepted += 1
                path = (root / proposal["candidate_path"]).resolve()
                try:
                    path.relative_to(root)
                except ValueError as exc:
                    raise Sam31RepairError("SAM 3.1 repair candidate path escapes root") from exc
                if not path.is_file() or sha256_file(path) != proposal["candidate_file_sha256"]:
                    raise Sam31RepairError("SAM 3.1 repair candidate file identity is stale")
                with Image.open(path) as image:
                    array = np.asarray(image)
                    if image.mode != "L" or set(np.unique(array).tolist()) > {0, 255}:
                        raise Sam31RepairError("SAM 3.1 repair candidate format is invalid")
                if _array_sha256(array.astype(bool)) != proposal["mask_sha256"]:
                    raise Sam31RepairError("SAM 3.1 repair candidate mask identity is stale")
            elif proposal["candidate_path"] is not None:
                raise Sam31RepairError("rejected SAM 3.1 repair proposal retained a mask artifact")
    if accepted != document["accepted_candidate_count"]:
        raise Sam31RepairError("SAM 3.1 repair accepted-candidate count is stale")
    if (
        len(document["requests"]) != document["request_count"]
        or proposal_count != document["proposal_count"]
    ):
        raise Sam31RepairError("SAM 3.1 repair request/proposal count is stale")
    if document["status"] != "complete" and (root / "candidates").exists():
        raise Sam31RepairError("noncomplete SAM 3.1 repair retained candidates")
    return {
        "status": document["status"],
        "request_count": document["request_count"],
        "proposal_count": document["proposal_count"],
        "accepted_candidate_count": accepted,
        "sha256": document["sha256"],
        "authority": REPAIR_AUTHORITY,
    }


__all__ = [
    "NONCOMPLETION_STATUSES",
    "REPAIR_AUTHORITY",
    "Sam31RepairError",
    "Sam31RepairRequest",
    "run_sam31_repair_orchestration",
    "verify_sam31_repair_orchestration",
    "write_sam31_repair_noncompletion",
]
