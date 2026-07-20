"""Seal multi-person tournament candidates without losing identity or family provenance."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ..io.hashing import sha256_file
from ..providers.contracts import ProviderIdentity
from ..validation import ArtifactValidationError, require_valid_document
from .calibration import load_autonomy_config
from .multi_person_availability import (
    DEFAULT_MODEL_REGISTRY,
    DEFAULT_POLICY,
    DEFAULT_RUNTIME_MATRIX,
    build_multi_person_availability_snapshot,
)
from .tournament import CandidateEvidence

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AUTONOMY_CONFIG = ROOT / "configs" / "autonomous_masks.yaml"
MULTI_PERSON_FUNCTIONAL_FAMILIES = (
    "deterministic_repair",
    "fusion",
    "geometry",
    "pose",
    "rf_detr_detection",
    "sam21_refinement",
    "sam31_exhaustive_discovery",
    "sam31_refinement",
    "silhouette",
    "specialist",
)
EVIDENCE_AUTHORITY = (
    "multi_person_tournament_evidence_only_"
    "no_selection_serving_training_semantic_mask_or_gold_authority"
)


class MultiPersonEvidenceError(ValueError):
    """Multi-person tournament evidence is incomplete, rebound, or identity-ambiguous."""


@dataclass(frozen=True)
class ProviderContribution:
    functional_family: str
    provider: ProviderIdentity


@dataclass(frozen=True)
class MultiPersonCandidateRecord:
    generator_family: str
    round_number: int
    parent_candidate_id: str | None
    contributions: tuple[ProviderContribution, ...]
    evidence: CandidateEvidence


@dataclass(frozen=True)
class MultiPersonTournamentTarget:
    person_id: str
    instance_id: str
    label: str
    candidates: tuple[MultiPersonCandidateRecord, ...]


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _atomic_json(path: Path, document: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _relative_artifact(path: Path, root: Path) -> str:
    root = Path(root).resolve()
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise MultiPersonEvidenceError("candidate artifact escapes the evidence root") from exc
    if not resolved.is_file():
        raise MultiPersonEvidenceError("candidate artifact is missing")
    return relative.as_posix()


def _artifact(path: str, root: Path) -> Path:
    if not isinstance(path, str) or Path(path).is_absolute():
        raise MultiPersonEvidenceError("candidate artifact path is invalid")
    root = Path(root).resolve()
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise MultiPersonEvidenceError("candidate artifact escapes the evidence root") from exc
    if not resolved.is_file():
        raise MultiPersonEvidenceError("candidate artifact is missing")
    return resolved


def _strict_mask(path: Path, shape: tuple[int, int]) -> None:
    with Image.open(path) as image:
        array = np.asarray(image)
        mode = image.mode
        image_format = image.format
    if (
        image_format != "PNG"
        or mode != "L"
        or array.shape != shape
        or set(np.unique(array).tolist()) - {0, 255}
        or not np.any(array == 255)
    ):
        raise MultiPersonEvidenceError("candidate artifact is not a nonempty strict PNG mask")


def _provider_document(identity: ProviderIdentity) -> dict[str, Any]:
    return {
        "provider_key": identity.provider_key,
        "role": identity.role,
        "model_family": identity.model_family,
        "source_commit": identity.source_commit,
        "runtime_fingerprint": identity.runtime_fingerprint,
        "contract_version": identity.contract_version,
        "provenance_aliases": list(identity.provenance_aliases),
    }


def _evidence_document(evidence: CandidateEvidence, mask_path: str) -> dict[str, Any]:
    document = asdict(evidence)
    document["mask_path"] = mask_path
    document["block_qc_ids"] = list(evidence.block_qc_ids)
    document["source_provider_keys"] = list(evidence.source_provider_keys)
    document["source_model_families"] = list(evidence.source_model_families)
    return document


def _bounds(config_path: Path) -> tuple[int, int, str]:
    config = load_autonomy_config(Path(config_path))
    tournament = config["tournament"]
    return (
        int(tournament["maximum_rounds"]),
        int(tournament["maximum_candidates_per_label"]),
        sha256_file(Path(config_path)),
    )


def write_multi_person_tournament_evidence(
    *,
    image_id: str,
    source_image_path: Path,
    instance_context: str,
    pipeline_fingerprint: str,
    targets: Sequence[MultiPersonTournamentTarget],
    artifact_root: Path,
    output_path: Path,
    config_path: Path = DEFAULT_AUTONOMY_CONFIG,
    availability_policy_path: Path = DEFAULT_POLICY,
    model_registry_path: Path = DEFAULT_MODEL_REGISTRY,
    runtime_matrix_path: Path = DEFAULT_RUNTIME_MATRIX,
) -> Path:
    """Write a sealed per-target evidence manifest around existing tournament candidates."""
    if instance_context not in {"duo", "small_group"}:
        raise MultiPersonEvidenceError("multi-person evidence context must be duo or small_group")
    if not image_id or not pipeline_fingerprint or not targets:
        raise MultiPersonEvidenceError("image, pipeline, and target identities are required")
    with Image.open(source_image_path) as image:
        width, height = image.size
    maximum_rounds, maximum_candidates, config_sha256 = _bounds(config_path)
    availability_snapshot = build_multi_person_availability_snapshot(
        policy_path=availability_policy_path,
        model_registry_path=model_registry_path,
        runtime_matrix_path=runtime_matrix_path,
    )
    rows = []
    for target in sorted(
        targets, key=lambda value: (value.person_id, value.instance_id, value.label)
    ):
        candidates = []
        for candidate in sorted(
            target.candidates, key=lambda value: (value.round_number, value.evidence.candidate_id)
        ):
            relative = _relative_artifact(Path(candidate.evidence.mask_path), artifact_root)
            candidates.append(
                {
                    "generator_family": candidate.generator_family,
                    "round_number": candidate.round_number,
                    "parent_candidate_id": candidate.parent_candidate_id,
                    "contributions": [
                        {
                            "functional_family": contribution.functional_family,
                            "provider": _provider_document(contribution.provider),
                        }
                        for contribution in candidate.contributions
                    ],
                    "evidence": _evidence_document(candidate.evidence, relative),
                }
            )
        rows.append(
            {
                "person_id": target.person_id,
                "instance_id": target.instance_id,
                "label": target.label,
                "candidates": candidates,
            }
        )
    document: dict[str, Any] = {
        "schema_version": "1.1.0",
        "image_id": image_id,
        "source_image_sha256": sha256_file(Path(source_image_path)),
        "source_width": width,
        "source_height": height,
        "instance_context": instance_context,
        "pipeline_fingerprint": pipeline_fingerprint,
        "autonomy_config_sha256": config_sha256,
        "maximum_rounds": maximum_rounds,
        "maximum_candidates_per_target": maximum_candidates,
        "availability_snapshot": availability_snapshot,
        "target_count": len(rows),
        "candidate_count": sum(len(row["candidates"]) for row in rows),
        "targets": rows,
        "authority": EVIDENCE_AUTHORITY,
    }
    document["sha256"] = _canonical_sha256(document)
    try:
        require_valid_document(document, "multi_person_tournament_evidence")
    except ArtifactValidationError as exc:
        raise MultiPersonEvidenceError(str(exc)) from exc
    _atomic_json(Path(output_path), document)
    verify_multi_person_tournament_evidence(
        Path(output_path),
        artifact_root=artifact_root,
        expected_pipeline_fingerprint=pipeline_fingerprint,
        source_image_path=source_image_path,
        config_path=config_path,
        availability_policy_path=availability_policy_path,
        model_registry_path=model_registry_path,
        runtime_matrix_path=runtime_matrix_path,
    )
    return Path(output_path)


def verify_multi_person_tournament_evidence(
    manifest_path: Path,
    *,
    artifact_root: Path,
    expected_pipeline_fingerprint: str,
    source_image_path: Path | None = None,
    config_path: Path = DEFAULT_AUTONOMY_CONFIG,
    availability_policy_path: Path = DEFAULT_POLICY,
    model_registry_path: Path = DEFAULT_MODEL_REGISTRY,
    runtime_matrix_path: Path = DEFAULT_RUNTIME_MATRIX,
) -> dict[str, Any]:
    """Verify seals, current config, strict artifacts, identities, bounds, and family coverage."""
    document = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    try:
        require_valid_document(document, "multi_person_tournament_evidence")
    except ArtifactValidationError as exc:
        raise MultiPersonEvidenceError(str(exc)) from exc
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if document["sha256"] != _canonical_sha256(payload):
        raise MultiPersonEvidenceError("multi-person evidence hash mismatch")
    maximum_rounds, maximum_candidates, config_sha256 = _bounds(config_path)
    if (
        document["pipeline_fingerprint"] != expected_pipeline_fingerprint
        or document["autonomy_config_sha256"] != config_sha256
        or document["maximum_rounds"] != maximum_rounds
        or document["maximum_candidates_per_target"] != maximum_candidates
    ):
        raise MultiPersonEvidenceError("multi-person evidence policy identity is stale")
    current_availability = build_multi_person_availability_snapshot(
        policy_path=availability_policy_path,
        model_registry_path=model_registry_path,
        runtime_matrix_path=runtime_matrix_path,
    )
    if document["availability_snapshot"] != current_availability:
        raise MultiPersonEvidenceError("multi-person provider availability identity is stale")
    if source_image_path is not None:
        with Image.open(source_image_path) as image:
            source_size = image.size
        if sha256_file(Path(source_image_path)) != document[
            "source_image_sha256"
        ] or source_size != (document["source_width"], document["source_height"]):
            raise MultiPersonEvidenceError("multi-person source image identity is stale")
    targets = document["targets"]
    target_keys = [(row["person_id"], row["instance_id"], row["label"]) for row in targets]
    if len(target_keys) != len(set(target_keys)):
        raise MultiPersonEvidenceError("multi-person target identity is duplicated")
    people = {row["person_id"] for row in targets}
    expected_people = 2 if document["instance_context"] == "duo" else 3
    if len(people) < expected_people or (
        document["instance_context"] == "duo" and len(people) != 2
    ):
        raise MultiPersonEvidenceError("target people do not match the multi-person context")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    total = 0
    availability = document["availability_snapshot"]["families"]
    available = {family for family, state in availability.items() if state["available"]}
    unavailable = set(MULTI_PERSON_FUNCTIONAL_FAMILIES) - available
    for target in targets:
        candidates = target["candidates"]
        if not candidates or len(candidates) > maximum_candidates:
            raise MultiPersonEvidenceError("target candidate count violates tournament bounds")
        contributed: set[str] = set()
        local_rows = {row["evidence"]["candidate_id"]: row for row in candidates}
        if len(local_rows) != len(candidates):
            raise MultiPersonEvidenceError("candidate identity is duplicated within a target")
        for row in candidates:
            evidence = row["evidence"]
            candidate_id = evidence["candidate_id"]
            if candidate_id in seen_ids or evidence["mask_path"] in seen_paths:
                raise MultiPersonEvidenceError(
                    "candidate identity or artifact is reused across targets"
                )
            if not 0 <= row["round_number"] <= maximum_rounds:
                raise MultiPersonEvidenceError("candidate correction round exceeds policy")
            parent = row["parent_candidate_id"]
            if row["round_number"] == 0 and parent is not None:
                raise MultiPersonEvidenceError("initial candidate cannot name a parent")
            if row["round_number"] > 0:
                if parent not in local_rows:
                    raise MultiPersonEvidenceError("repair candidate parent is missing from target")
                if local_rows[parent]["round_number"] >= row["round_number"]:
                    raise MultiPersonEvidenceError("repair candidate parent round is not earlier")
            contributions = row["contributions"]
            contribution_keys = [
                (
                    item["functional_family"],
                    item["provider"]["provider_key"],
                    item["provider"]["role"],
                )
                for item in contributions
            ]
            if not contributions or len(contribution_keys) != len(set(contribution_keys)):
                raise MultiPersonEvidenceError(
                    "candidate provider contribution is missing or duplicated"
                )
            functional = {item["functional_family"] for item in contributions}
            if row["generator_family"] not in functional or functional & unavailable:
                raise MultiPersonEvidenceError("candidate uses an unavailable or unbound family")
            if row["generator_family"] == "deterministic_repair" and row["round_number"] == 0:
                raise MultiPersonEvidenceError(
                    "deterministic repair must descend from an earlier round"
                )
            provider_keys = {item["provider"]["provider_key"] for item in contributions}
            model_families = {item["provider"]["model_family"] for item in contributions}
            if (
                set(evidence["source_provider_keys"]) != provider_keys
                or set(evidence["source_model_families"]) != model_families
                or evidence["independent_sources"] != len(model_families)
            ):
                raise MultiPersonEvidenceError(
                    "independent-family provenance differs from contributions"
                )
            path = _artifact(evidence["mask_path"], artifact_root)
            _strict_mask(path, (document["source_height"], document["source_width"]))
            if sha256_file(path) != evidence["mask_sha256"]:
                raise MultiPersonEvidenceError("candidate artifact hash is stale")
            contributed.update(functional)
            seen_ids.add(candidate_id)
            seen_paths.add(evidence["mask_path"])
            total += 1
        if contributed != available:
            raise MultiPersonEvidenceError("available tournament family coverage is incomplete")
    if document["target_count"] != len(targets) or document["candidate_count"] != total:
        raise MultiPersonEvidenceError("multi-person evidence counts are inconsistent")
    return {
        "image_id": document["image_id"],
        "instance_context": document["instance_context"],
        "target_count": document["target_count"],
        "candidate_count": document["candidate_count"],
        "sha256": document["sha256"],
        "authority": EVIDENCE_AUTHORITY,
    }


def load_multi_person_tournament_candidates(
    manifest_path: Path,
    *,
    artifact_root: Path,
    expected_pipeline_fingerprint: str,
    source_image_path: Path | None = None,
    config_path: Path = DEFAULT_AUTONOMY_CONFIG,
    availability_policy_path: Path = DEFAULT_POLICY,
    model_registry_path: Path = DEFAULT_MODEL_REGISTRY,
    runtime_matrix_path: Path = DEFAULT_RUNTIME_MATRIX,
) -> dict[tuple[str, str, str], tuple[CandidateEvidence, ...]]:
    """Return existing tournament evidence only after the complete envelope verifies."""
    verify_multi_person_tournament_evidence(
        manifest_path,
        artifact_root=artifact_root,
        expected_pipeline_fingerprint=expected_pipeline_fingerprint,
        source_image_path=source_image_path,
        config_path=config_path,
        availability_policy_path=availability_policy_path,
        model_registry_path=model_registry_path,
        runtime_matrix_path=runtime_matrix_path,
    )
    document = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return {
        (target["person_id"], target["instance_id"], target["label"]): tuple(
            CandidateEvidence(
                **{
                    **row["evidence"],
                    "mask_path": str(Path(artifact_root) / row["evidence"]["mask_path"]),
                    "block_qc_ids": tuple(row["evidence"]["block_qc_ids"]),
                    "source_provider_keys": tuple(row["evidence"]["source_provider_keys"]),
                    "source_model_families": tuple(row["evidence"]["source_model_families"]),
                }
            )
            for row in target["candidates"]
        )
        for target in document["targets"]
    }


__all__ = [
    "EVIDENCE_AUTHORITY",
    "MULTI_PERSON_FUNCTIONAL_FAMILIES",
    "MultiPersonCandidateRecord",
    "MultiPersonEvidenceError",
    "MultiPersonTournamentTarget",
    "ProviderContribution",
    "load_multi_person_tournament_candidates",
    "verify_multi_person_tournament_evidence",
    "write_multi_person_tournament_evidence",
]
