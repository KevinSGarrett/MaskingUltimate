"""Production-safe orchestration for official SAM 3.1 shadow candidates."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from PIL import Image

from ..io.hashing import sha256_file
from ..validation import ArtifactValidationError, require_valid_document
from .benchmark_policy import (
    DEFAULT_SPECIALIST_MARGIN_MANIFEST,
    load_specialist_margin_manifest,
)
from .contracts import (
    BoxProposal,
    ConceptDetector,
    InteractiveSegmenter,
    MaskProposal,
    ProviderIdentity,
)
from .sam31_candidates import (
    Sam31LaneCandidate,
    governed_lane_labels,
    verify_sam31_candidate_package,
    write_sam31_candidate_package,
)
from .sam31_shadow import (
    DEFAULT_RUNTIME_LOCK,
    OFFICIAL_PROVIDER_KEY,
    SHADOW_AUTHORITY,
    sam31_provider_identity,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PIPELINE = ROOT / "configs" / "pipeline.yaml"
ORCHESTRATION_AUTHORITY = (
    "production_orchestration_shadow_evidence_only_"
    "no_active_map_serving_semantic_mask_or_gold_authority"
)
RUNNABLE_LIFECYCLES = frozenset({"installed", "benchmarked", "promoted"})
NONCOMPLETION_STATUSES = frozenset({"skipped_unavailable", "complete_no_candidates", "failed"})


class Sam31OrchestrationError(ValueError):
    """Official SAM 3.1 shadow orchestration is stale, unsafe, or malformed."""


@dataclass(frozen=True, order=True)
class Sam31ConceptRoute:
    lane: str
    semantic_label: str
    concept: str


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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


def canonical_sam31_concept_routes() -> tuple[Sam31ConceptRoute, ...]:
    """Derive unique, visible-surface concepts from the frozen specialist label policy."""
    prefixes = {
        "accessory": "visible separate accessory instance",
        "chest_pelvic": "visible target-person anatomy surface",
        "clothing": "visible target-person garment or material region",
        "foot_toe": "visible target-person foot region",
        "hair": "visible target-person hair or head boundary",
        "hand_finger": "visible target-person hand region",
        "repeated_instance": "separate repeated instance near the target person",
    }
    routes = tuple(
        Sam31ConceptRoute(
            lane,
            label,
            f"{prefixes[lane]}: {label.replace('_', ' ')}",
        )
        for lane, labels in sorted(governed_lane_labels().items())
        for label in sorted(labels)
    )
    concepts = [route.concept for route in routes]
    if not routes or len(concepts) != len(set(concepts)):
        raise Sam31OrchestrationError("SAM 3.1 canonical concept routes are empty or ambiguous")
    return routes


def _route_policy_sha256(path: Path = DEFAULT_SPECIALIST_MARGIN_MANIFEST) -> str:
    manifest, _ = load_specialist_margin_manifest(path)
    return str(manifest["sha256"])


def _base_document(
    *,
    source_image_path: Path,
    parent_instance_key: str,
    lifecycle_state: str,
    exemplar_paths: Sequence[Path],
    pipeline_path: Path,
    runtime_lock_path: Path,
) -> dict[str, Any]:
    source_image_path = Path(source_image_path)
    if not source_image_path.is_file() or not parent_instance_key:
        raise Sam31OrchestrationError("SAM 3.1 source image and parent instance are required")
    with Image.open(source_image_path) as image:
        width, height = image.size
    exemplars = tuple(Path(path) for path in exemplar_paths)
    if any(not path.is_file() for path in exemplars):
        raise Sam31OrchestrationError("SAM 3.1 exemplar artifact is missing")
    routes = canonical_sam31_concept_routes()
    pipeline_sha256 = sha256_file(Path(pipeline_path))
    return {
        "schema_version": "1.0.0",
        "provider_key": OFFICIAL_PROVIDER_KEY,
        "lifecycle_state": lifecycle_state,
        "source_image_sha256": sha256_file(source_image_path),
        "source_width": width,
        "source_height": height,
        "parent_instance_key": parent_instance_key,
        "route_policy_sha256": _route_policy_sha256(),
        "requested_route_count": len(routes),
        "requested_lanes": sorted({route.lane for route in routes}),
        "exemplar_sha256": [sha256_file(path) for path in exemplars],
        "expected_provider_identities": {
            "concept_detector": _identity_document(
                sam31_provider_identity("concept_detector", lock_path=runtime_lock_path)
            ),
            "interactive_segmenter": _identity_document(
                sam31_provider_identity("interactive_segmenter", lock_path=runtime_lock_path)
            ),
        },
        "pipeline_sha256_before": pipeline_sha256,
        "pipeline_sha256_after": pipeline_sha256,
        "authority": ORCHESTRATION_AUTHORITY,
    }


def _write_document(output_dir: Path, document: dict[str, Any]) -> Path:
    document["sha256"] = _canonical_sha256(document)
    try:
        require_valid_document(document, "sam31_shadow_orchestration")
    except ArtifactValidationError as exc:
        raise Sam31OrchestrationError(str(exc)) from exc
    path = Path(output_dir) / "orchestration.json"
    _atomic_json(path, document)
    return path


def write_sam31_shadow_noncompletion(
    *,
    source_image_path: Path,
    parent_instance_key: str,
    lifecycle_state: str,
    output_dir: Path,
    status: Literal["skipped_unavailable", "complete_no_candidates", "failed"],
    reason: str,
    discovery_request_count: int = 0,
    discovery_result_count: int = 0,
    exemplar_paths: Sequence[Path] = (),
    pipeline_path: Path = DEFAULT_PIPELINE,
    runtime_lock_path: Path = DEFAULT_RUNTIME_LOCK,
) -> Path:
    """Persist an explicit zero-authority skip/failure instead of hiding it."""
    if status not in NONCOMPLETION_STATUSES or not reason.strip():
        raise Sam31OrchestrationError("SAM 3.1 noncompletion status and reason are invalid")
    output_dir = Path(output_dir)
    shutil.rmtree(output_dir / "candidates", ignore_errors=True)
    document = _base_document(
        source_image_path=source_image_path,
        parent_instance_key=parent_instance_key,
        lifecycle_state=lifecycle_state,
        exemplar_paths=exemplar_paths,
        pipeline_path=pipeline_path,
        runtime_lock_path=runtime_lock_path,
    )
    document.update(
        {
            "status": status,
            "reason": reason.strip(),
            "discovery_request_count": int(discovery_request_count),
            "discovery_result_count": int(discovery_result_count),
            "candidate_count": 0,
            "candidate_package_path": None,
            "candidate_package_file_sha256": None,
            "candidate_package_document_sha256": None,
        }
    )
    return _write_document(output_dir, document)


def run_sam31_shadow_orchestration(
    *,
    source_image_path: Path,
    parent_instance_key: str,
    lifecycle_state: str,
    concept_detector: ConceptDetector,
    interactive_segmenter: InteractiveSegmenter | None,
    output_dir: Path,
    exemplar_paths: Sequence[Path] = (),
    pipeline_path: Path = DEFAULT_PIPELINE,
    runtime_lock_path: Path = DEFAULT_RUNTIME_LOCK,
) -> Path:
    """Run every governed lane and persist only isolated official-SAM3.1 candidates."""
    if lifecycle_state not in RUNNABLE_LIFECYCLES:
        raise Sam31OrchestrationError("SAM 3.1 lifecycle is not runnable")
    expected_concept = sam31_provider_identity("concept_detector", lock_path=runtime_lock_path)
    expected_interactive = sam31_provider_identity(
        "interactive_segmenter", lock_path=runtime_lock_path
    )
    if (
        concept_detector.identity != expected_concept
        or getattr(concept_detector, "authority", None) != SHADOW_AUTHORITY
        or (
            interactive_segmenter is not None
            and (
                interactive_segmenter.identity != expected_interactive
                or getattr(interactive_segmenter, "authority", None) != SHADOW_AUTHORITY
            )
        )
    ):
        raise Sam31OrchestrationError("SAM 3.1 loader identity or authority is not official shadow")

    source_image_path = Path(source_image_path)
    exemplars = tuple(Path(path) for path in exemplar_paths)
    embedding: Any | None = None
    routes = canonical_sam31_concept_routes()
    candidates: list[Sam31LaneCandidate] = []
    discovery_results = 0
    for request_index, route in enumerate(routes):
        proposals = tuple(
            concept_detector.discover(
                source_image_path,
                concepts=(route.concept,),
                exemplars=exemplars,
            )
        )
        discovery_results += len(proposals)
        for proposal_index, proposal in enumerate(proposals):
            if isinstance(proposal, BoxProposal):
                if proposal.label != route.concept:
                    raise Sam31OrchestrationError(
                        "SAM 3.1 discovery box label does not match its requested route"
                    )
                if interactive_segmenter is None:
                    raise Sam31OrchestrationError(
                        "SAM 3.1 box discovery requires the official shadow interactive segmenter"
                    )
                if embedding is None:
                    with Image.open(source_image_path) as source:
                        image = np.asarray(source.convert("RGB"))
                    embedding = interactive_segmenter.embed(image)
                prompt = {
                    "positive_points": (),
                    "negative_points": (),
                    "box_xyxy": proposal.bbox_xyxy,
                    "mask_prompt": None,
                }
                discovery_instance = proposal.instance_key or f"box-{proposal_index}"
                refined = tuple(interactive_segmenter.refine(embedding, prompt=prompt))
            elif isinstance(proposal, MaskProposal):
                if proposal.provider != expected_concept:
                    raise Sam31OrchestrationError(
                        "SAM 3.1 discovery mask has stale concept-provider identity"
                    )
                discovery_instance = f"mask-{proposal_index}"
                refined = (proposal,)
            else:
                raise Sam31OrchestrationError("SAM 3.1 discovery returned a foreign proposal")
            for refinement_index, mask in enumerate(refined):
                expected_provider = (
                    expected_interactive if isinstance(proposal, BoxProposal) else expected_concept
                )
                if mask.provider != expected_provider:
                    raise Sam31OrchestrationError(
                        "SAM 3.1 candidate has stale provider identity for its discovery route"
                    )
                candidates.append(
                    Sam31LaneCandidate(
                        candidate_id=(
                            f"sam31-{route.lane}-{request_index:03d}-"
                            f"{proposal_index:02d}-{refinement_index:02d}"
                        ),
                        lane=route.lane,
                        semantic_label=route.semantic_label,
                        instance_key=(
                            f"{parent_instance_key}.{request_index:03d}."
                            f"{discovery_instance}.{refinement_index:02d}"
                        ),
                        proposal=mask,
                    )
                )

    if not candidates:
        return write_sam31_shadow_noncompletion(
            source_image_path=source_image_path,
            parent_instance_key=parent_instance_key,
            lifecycle_state=lifecycle_state,
            output_dir=output_dir,
            status="complete_no_candidates",
            reason="official SAM 3.1 completed all governed concept requests with no candidates",
            discovery_request_count=len(routes),
            discovery_result_count=discovery_results,
            exemplar_paths=exemplars,
            pipeline_path=pipeline_path,
            runtime_lock_path=runtime_lock_path,
        )

    candidate_root = Path(output_dir) / "candidates"
    package_path = write_sam31_candidate_package(
        source_image_path=source_image_path,
        candidates=candidates,
        output_dir=candidate_root,
        pipeline_path=pipeline_path,
        runtime_lock_path=runtime_lock_path,
    )
    package = json.loads(package_path.read_text(encoding="utf-8"))
    document = _base_document(
        source_image_path=source_image_path,
        parent_instance_key=parent_instance_key,
        lifecycle_state=lifecycle_state,
        exemplar_paths=exemplars,
        pipeline_path=pipeline_path,
        runtime_lock_path=runtime_lock_path,
    )
    document.update(
        {
            "status": "complete",
            "reason": None,
            "discovery_request_count": len(routes),
            "discovery_result_count": discovery_results,
            "candidate_count": len(candidates),
            "candidate_package_path": "candidates/sam31_shadow_candidates.json",
            "candidate_package_file_sha256": sha256_file(package_path),
            "candidate_package_document_sha256": package["sha256"],
        }
    )
    if sha256_file(Path(pipeline_path)) != document["pipeline_sha256_before"]:
        raise Sam31OrchestrationError("active provider map changed during SAM 3.1 orchestration")
    path = _write_document(output_dir, document)
    verify_sam31_shadow_orchestration(
        path,
        artifact_root=output_dir,
        source_image_path=source_image_path,
        pipeline_path=pipeline_path,
        runtime_lock_path=runtime_lock_path,
    )
    return path


def verify_sam31_shadow_orchestration(
    manifest_path: Path,
    *,
    artifact_root: Path,
    source_image_path: Path,
    pipeline_path: Path = DEFAULT_PIPELINE,
    runtime_lock_path: Path = DEFAULT_RUNTIME_LOCK,
) -> dict[str, Any]:
    """Recompute the route policy, identities, active map, and candidate package."""
    document = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    try:
        require_valid_document(document, "sam31_shadow_orchestration")
    except ArtifactValidationError as exc:
        raise Sam31OrchestrationError(str(exc)) from exc
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if document["sha256"] != _canonical_sha256(payload):
        raise Sam31OrchestrationError("SAM 3.1 orchestration hash mismatch")
    source_image_path = Path(source_image_path)
    if document["source_image_sha256"] != sha256_file(source_image_path):
        raise Sam31OrchestrationError("SAM 3.1 orchestration source identity is stale")
    pipeline_sha256 = sha256_file(Path(pipeline_path))
    if (
        document["pipeline_sha256_before"] != pipeline_sha256
        or document["pipeline_sha256_after"] != pipeline_sha256
    ):
        raise Sam31OrchestrationError("SAM 3.1 orchestration active-map identity is stale")
    routes = canonical_sam31_concept_routes()
    if (
        document["route_policy_sha256"] != _route_policy_sha256()
        or document["requested_route_count"] != len(routes)
        or document["requested_lanes"] != sorted({route.lane for route in routes})
    ):
        raise Sam31OrchestrationError("SAM 3.1 orchestration route policy is stale")
    expected = {
        "concept_detector": _identity_document(
            sam31_provider_identity("concept_detector", lock_path=runtime_lock_path)
        ),
        "interactive_segmenter": _identity_document(
            sam31_provider_identity("interactive_segmenter", lock_path=runtime_lock_path)
        ),
    }
    if document["expected_provider_identities"] != expected:
        raise Sam31OrchestrationError("SAM 3.1 orchestration provider identity is stale")
    if document["status"] == "complete":
        root = Path(artifact_root).resolve()
        package_path = (root / document["candidate_package_path"]).resolve()
        try:
            package_path.relative_to(root)
        except ValueError as exc:
            raise Sam31OrchestrationError("SAM 3.1 candidate package path escapes root") from exc
        if (
            not package_path.is_file()
            or sha256_file(package_path) != document["candidate_package_file_sha256"]
        ):
            raise Sam31OrchestrationError("SAM 3.1 candidate package file identity is stale")
        summary = verify_sam31_candidate_package(
            package_path,
            artifact_root=package_path.parent,
            pipeline_path=pipeline_path,
            runtime_lock_path=runtime_lock_path,
        )
        if (
            summary["candidate_count"] != document["candidate_count"]
            or summary["sha256"] != document["candidate_package_document_sha256"]
        ):
            raise Sam31OrchestrationError("SAM 3.1 candidate package summary is stale")
    elif (Path(artifact_root) / "candidates").exists():
        raise Sam31OrchestrationError("noncomplete SAM 3.1 orchestration retained candidates")
    return {
        "status": document["status"],
        "candidate_count": document["candidate_count"],
        "requested_lanes": document["requested_lanes"],
        "sha256": document["sha256"],
        "authority": ORCHESTRATION_AUTHORITY,
    }


__all__ = [
    "NONCOMPLETION_STATUSES",
    "ORCHESTRATION_AUTHORITY",
    "RUNNABLE_LIFECYCLES",
    "Sam31ConceptRoute",
    "Sam31OrchestrationError",
    "canonical_sam31_concept_routes",
    "run_sam31_shadow_orchestration",
    "verify_sam31_shadow_orchestration",
    "write_sam31_shadow_noncompletion",
]
