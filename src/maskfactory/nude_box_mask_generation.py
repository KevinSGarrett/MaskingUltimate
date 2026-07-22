"""Deterministic box-prompted person-mask generation for reference corpora.

This stage consumes a previously sealed, multi-detector person catalog.  It
creates provider-specific *draft* masks and comparison evidence; it never turns
the source image, detector box, or generated candidate into pixel truth.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .io.png_strict import read_mask, write_binary_mask
from .nude_person_catalog import validate_person_proposal_catalog_report
from .providers.contracts import (
    InteractiveSegmenter,
    MaskProposal,
    ProviderIdentity,
    require_independent_model_families,
)
from .providers.disagreement import binary_mask_sha256
from .stages.s05_geometry import PromptPlan
from .stages.s07_sam2 import Sam2Provider, build_embedding

SHA256 = re.compile(r"^[a-f0-9]{64}$")


class NudeBoxMaskGenerationError(ValueError):
    """Box-prompt generation or comparison evidence failed closed."""


class Sam2BoxPromptInteractiveSegmenter:
    """Expose the governed SAM2.1 primary/OOM pair through the role contract."""

    def __init__(self, provider: Sam2Provider, identity: ProviderIdentity) -> None:
        if identity.role != "interactive_segmenter" or identity.model_family != "sam2":
            raise NudeBoxMaskGenerationError("sam2_bridge_identity_invalid")
        self.provider = provider
        self.identity = identity

    def embed(self, image: np.ndarray) -> tuple[Any, str]:
        source = np.asarray(image)
        if source.dtype != np.uint8 or source.ndim != 3 or source.shape[2] != 3:
            raise NudeBoxMaskGenerationError("sam2_bridge_source_invalid")
        return build_embedding(self.provider, source)

    def refine(self, embedding: Any, *, prompt: Mapping[str, Any]) -> Sequence[MaskProposal]:
        if (
            not isinstance(embedding, tuple)
            or len(embedding) != 2
            or not isinstance(embedding[1], str)
        ):
            raise NudeBoxMaskGenerationError("sam2_bridge_embedding_invalid")
        if set(prompt) != {"positive_points", "negative_points", "box_xyxy", "mask_prompt"}:
            raise NudeBoxMaskGenerationError("sam2_bridge_prompt_fields_invalid")
        if prompt["mask_prompt"] is not None:
            raise NudeBoxMaskGenerationError("sam2_bridge_mask_prior_unsupported")
        try:
            box = tuple(int(value) for value in prompt["box_xyxy"])
            positives = tuple(
                tuple(int(value) for value in point) for point in prompt["positive_points"]
            )
            negatives = tuple(
                tuple(int(value) for value in point) for point in prompt["negative_points"]
            )
        except (TypeError, ValueError) as exc:
            raise NudeBoxMaskGenerationError("sam2_bridge_prompt_invalid") from exc
        if len(box) != 4 or any(len(point) != 2 for point in (*positives, *negatives)):
            raise NudeBoxMaskGenerationError("sam2_bridge_prompt_invalid")
        plan = PromptPlan(
            label="person",
            box_xyxy=box,
            positive_points=positives,
            negative_points=negatives,
            prior_quality="multi_detector_person_catalog",
            multimask_output=True,
        )
        raw = self.provider.predict(embedding[0], plan, multimask_output=True)
        prompt_fingerprint = _canonical_sha256(
            {
                "provider": _identity(self.identity),
                "selected_model": embedding[1],
                "prompt": {
                    "positive_points": [list(point) for point in positives],
                    "negative_points": [list(point) for point in negatives],
                    "box_xyxy": list(box),
                    "mask_prompt": None,
                },
                "postprocess": "strict_box_clip_v1",
            }
        )
        left, top, right, bottom = box
        proposals = []
        for candidate in raw:
            logits = np.asarray(candidate.logits)
            if logits.ndim != 2 or not np.isfinite(logits).all():
                raise NudeBoxMaskGenerationError("sam2_bridge_logits_invalid")
            allowed = np.zeros(logits.shape, dtype=bool)
            if not (0 <= left < right <= logits.shape[1] and 0 <= top < bottom <= logits.shape[0]):
                raise NudeBoxMaskGenerationError("sam2_bridge_box_out_of_bounds")
            allowed[top:bottom, left:right] = True
            proposals.append(
                MaskProposal(
                    (logits >= 0) & allowed,
                    float(candidate.predicted_iou),
                    self.identity,
                    prompt_fingerprint,
                )
            )
        return tuple(proposals)

    def close(self, embedding: Any) -> None:
        if not isinstance(embedding, tuple) or len(embedding) != 2:
            return
        close = getattr(self.provider, "close", None)
        if callable(close):
            close(embedding[0])


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(identity: ProviderIdentity) -> dict[str, Any]:
    return {
        "provider_key": identity.provider_key,
        "role": identity.role,
        "model_family": identity.model_family,
        "source_commit": identity.source_commit,
        "runtime_fingerprint": identity.runtime_fingerprint,
        "contract_version": identity.contract_version,
    }


def _validate_catalog_batch(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(document, Mapping):
        raise NudeBoxMaskGenerationError("catalog_batch_invalid")
    if document.get("schema_version") != "maskfactory.nude_person_catalog_batch.v1":
        raise NudeBoxMaskGenerationError("catalog_batch_schema_invalid")
    body = {key: value for key, value in document.items() if key != "self_sha256"}
    if document.get("self_sha256") != _canonical_sha256(body):
        raise NudeBoxMaskGenerationError("catalog_batch_hash_mismatch")
    records = document.get("records")
    if not isinstance(records, list) or len(records) != document.get("record_count"):
        raise NudeBoxMaskGenerationError("catalog_batch_records_invalid")
    validated = [validate_person_proposal_catalog_report(record) for record in records]
    sample_ids = [record["sample_id"] for record in validated]
    if len(sample_ids) != len(set(sample_ids)):
        raise NudeBoxMaskGenerationError("catalog_batch_sample_duplicated")
    return validated


def _source_paths(
    records: Sequence[Mapping[str, Any]], source_paths: Mapping[str, Path]
) -> dict[str, Path]:
    expected = {str(record["sample_id"]) for record in records if record["status"] == "pass"}
    normalized = {str(key): Path(value) for key, value in source_paths.items()}
    missing = sorted(expected - set(normalized))
    if missing:
        raise NudeBoxMaskGenerationError(f"source_paths_missing:{','.join(missing[:8])}")
    return normalized


def _prompt_for_person(person: Mapping[str, Any], *, width: int, height: int) -> dict[str, Any]:
    members = person.get("members")
    if not isinstance(members, list) or len(members) < 2:
        raise NudeBoxMaskGenerationError("person_catalog_members_invalid")
    boxes = []
    for member in members:
        box = member.get("bbox_xyxy") if isinstance(member, Mapping) else None
        if (
            not isinstance(box, list)
            or len(box) != 4
            or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in box)
        ):
            raise NudeBoxMaskGenerationError("person_catalog_box_invalid")
        values = tuple(float(value) for value in box)
        if (
            not all(math.isfinite(value) for value in values)
            or values[0] < 0
            or values[1] < 0
            or values[2] <= values[0]
            or values[3] <= values[1]
            or values[2] > width
            or values[3] > height
        ):
            raise NudeBoxMaskGenerationError("person_catalog_box_out_of_bounds")
        boxes.append(values)
    left = max(0, int(math.floor(min(box[0] for box in boxes))))
    top = max(0, int(math.floor(min(box[1] for box in boxes))))
    right = min(width, int(math.ceil(max(box[2] for box in boxes))))
    bottom = min(height, int(math.ceil(max(box[3] for box in boxes))))
    intersection = (
        max(box[0] for box in boxes),
        max(box[1] for box in boxes),
        min(box[2] for box in boxes),
        min(box[3] for box in boxes),
    )
    if intersection[2] <= intersection[0] or intersection[3] <= intersection[1]:
        raise NudeBoxMaskGenerationError("person_catalog_boxes_have_no_shared_interior")
    point_x = min(width - 1, max(0, int((intersection[0] + intersection[2]) / 2)))
    point_y = min(height - 1, max(0, int((intersection[1] + intersection[3]) / 2)))
    prompt_body = {
        "positive_points": [[point_x, point_y]],
        "negative_points": [],
        "box_xyxy": [left, top, right, bottom],
        "mask_prompt": None,
    }
    return {**prompt_body, "prompt_sha256": _canonical_sha256(prompt_body)}


def _select_proposal(
    proposals: Sequence[MaskProposal],
    *,
    identity: ProviderIdentity,
    prompt: Mapping[str, Any],
    shape: tuple[int, int],
) -> tuple[MaskProposal, str]:
    if not proposals:
        raise NudeBoxMaskGenerationError("provider_returned_no_masks")
    height, width = shape
    left, top, right, bottom = prompt["box_xyxy"]
    point_x, point_y = prompt["positive_points"][0]
    allowed = np.zeros(shape, dtype=bool)
    allowed[top:bottom, left:right] = True
    ranked = []
    for index, proposal in enumerate(proposals):
        if not isinstance(proposal, MaskProposal) or proposal.provider != identity:
            raise NudeBoxMaskGenerationError("provider_mask_identity_mismatch")
        mask = np.asarray(proposal.mask)
        if mask.dtype != np.bool_ or mask.shape != (height, width):
            raise NudeBoxMaskGenerationError("provider_mask_geometry_invalid")
        if not mask.any():
            continue
        if not mask[point_y, point_x] or np.any(mask & ~allowed):
            continue
        mask_sha256 = binary_mask_sha256(mask)
        ranked.append((proposal.confidence, mask_sha256, -index, proposal, mask_sha256))
    if not ranked:
        raise NudeBoxMaskGenerationError("provider_returned_no_prompt_compliant_mask")
    selected = max(ranked, key=lambda row: row[:3])
    return selected[3], selected[4]


def _write_candidate(path: Path, mask: np.ndarray, *, width: int, height: int) -> str:
    if path.exists():
        existing = read_mask(path)
        expected = np.asarray(mask, dtype=np.uint8) * 255
        if not np.array_equal(existing, expected):
            raise NudeBoxMaskGenerationError("candidate_output_idempotency_conflict")
    else:
        write_binary_mask(path, np.asarray(mask), source_size=(width, height))
    return _file_sha256(path)


def generate_box_prompt_provider_batch(
    *,
    catalog_batch: Mapping[str, Any],
    source_paths: Mapping[str, Path],
    provider: InteractiveSegmenter,
    output_root: Path,
    sample_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Run one provider across a sealed catalog and continue after record failures."""

    records = _validate_catalog_batch(catalog_batch)
    if sample_ids is not None:
        requested = tuple(str(sample_id) for sample_id in sample_ids)
        if not requested or len(requested) != len(set(requested)):
            raise NudeBoxMaskGenerationError("requested_sample_ids_invalid")
        requested_set = set(requested)
        available = {record["sample_id"] for record in records}
        missing = sorted(requested_set - available)
        if missing:
            raise NudeBoxMaskGenerationError(f"requested_sample_ids_missing:{','.join(missing)}")
        records = [record for record in records if record["sample_id"] in requested_set]
    paths = _source_paths(records, source_paths)
    if not isinstance(provider, InteractiveSegmenter):
        raise NudeBoxMaskGenerationError("interactive_provider_contract_invalid")
    identity = provider.identity
    if identity.role != "interactive_segmenter":
        raise NudeBoxMaskGenerationError("interactive_provider_role_invalid")
    output_root = Path(output_root)
    output_records: list[dict[str, Any]] = []
    for record in records:
        sample_id = record["sample_id"]
        if record["status"] != "pass":
            output_records.append(
                {
                    "sample_id": sample_id,
                    "source_sha256": record["source_sha256"],
                    "status": "catalog_abstain",
                    "reason": list(record["reasons"]),
                    "candidates": [],
                }
            )
            continue
        embedding: Any | None = None
        try:
            source_path = paths[sample_id]
            if not source_path.is_file() or _file_sha256(source_path) != record["source_sha256"]:
                raise NudeBoxMaskGenerationError("source_file_hash_mismatch")
            with Image.open(source_path) as image:
                source = np.asarray(image.convert("RGB"))
            width, height = record["image_size"]
            if source.dtype != np.uint8 or source.shape != (height, width, 3):
                raise NudeBoxMaskGenerationError("source_decoded_geometry_mismatch")
            embedding = provider.embed(source)
            candidates = []
            for person in record["catalog"]:
                person_index = person.get("person_index")
                if not isinstance(person_index, int) or isinstance(person_index, bool):
                    raise NudeBoxMaskGenerationError("person_index_invalid")
                prompt = _prompt_for_person(person, width=width, height=height)
                raw = provider.refine(
                    embedding,
                    prompt={
                        key: prompt[key]
                        for key in (
                            "positive_points",
                            "negative_points",
                            "box_xyxy",
                            "mask_prompt",
                        )
                    },
                )
                proposal, mask_sha256 = _select_proposal(
                    raw,
                    identity=identity,
                    prompt=prompt,
                    shape=(height, width),
                )
                relative_path = (
                    Path(sample_id)
                    / f"person_{person_index:03d}"
                    / (f"{identity.provider_key}.png")
                )
                output_path = output_root / relative_path
                artifact_sha256 = _write_candidate(
                    output_path, proposal.mask, width=width, height=height
                )
                candidates.append(
                    {
                        "person_index": person_index,
                        "candidate_label": "person",
                        "prompt": prompt,
                        "prompt_fingerprint": proposal.prompt_fingerprint,
                        "confidence": proposal.confidence,
                        "mask_sha256": mask_sha256,
                        "artifact_relative_path": relative_path.as_posix(),
                        "artifact_sha256": artifact_sha256,
                        "pixel_count": int(np.count_nonzero(proposal.mask)),
                        "authority": "draft_machine_candidate_only",
                        "production_mask_authority": False,
                        "operational_certificate_eligible": False,
                    }
                )
            output_records.append(
                {
                    "sample_id": sample_id,
                    "source_sha256": record["source_sha256"],
                    "status": "generated",
                    "reason": [],
                    "candidates": candidates,
                }
            )
        except Exception as exc:  # one malformed/runtime record cannot stop the shard
            output_records.append(
                {
                    "sample_id": sample_id,
                    "source_sha256": record["source_sha256"],
                    "status": "provider_abstain",
                    "reason": [f"{type(exc).__name__}:{exc}"],
                    "candidates": [],
                }
            )
        finally:
            if embedding is not None:
                close = getattr(provider, "close", None)
                if callable(close):
                    close(embedding)
    counts = Counter(row["status"] for row in output_records)
    body: dict[str, Any] = {
        "schema_version": "maskfactory.nude_box_prompt_provider_batch.v1",
        "catalog_batch_sha256": catalog_batch["self_sha256"],
        "provider": _identity(identity),
        "record_count": len(output_records),
        "candidate_count": sum(len(row["candidates"]) for row in output_records),
        "status_counts": dict(sorted(counts.items())),
        "records": output_records,
        "authority": "draft_provider_masks_only",
        "source_images_are_pixel_truth": False,
        "boxes_are_pixel_truth": False,
        "production_mask_authority": False,
        "operational_certificates_issued": False,
    }
    return {**body, "self_sha256": _canonical_sha256(body)}


def validate_box_prompt_provider_batch(
    document: Mapping[str, Any], *, output_root: Path
) -> dict[str, Any]:
    """Revalidate a provider batch, including every retained mask byte."""

    validated = validate_box_prompt_provider_batch_structure(document)
    records = validated["records"]
    candidates = 0
    root = Path(output_root).resolve()
    for record in records:
        for candidate in record.get("candidates", ()):
            relative = Path(str(candidate.get("artifact_relative_path") or ""))
            path = (root / relative).resolve()
            if path == root or root not in path.parents or not path.is_file():
                raise NudeBoxMaskGenerationError("provider_mask_path_invalid")
            if _file_sha256(path) != candidate.get("artifact_sha256"):
                raise NudeBoxMaskGenerationError("provider_mask_artifact_hash_mismatch")
            mask = read_mask(path)
            if mask.ndim != 2 or set(np.unique(mask).tolist()) - {0, 255}:
                raise NudeBoxMaskGenerationError("provider_mask_png_invalid")
            binary = mask == 255
            if binary_mask_sha256(binary) != candidate.get("mask_sha256"):
                raise NudeBoxMaskGenerationError("provider_mask_pixel_hash_mismatch")
            if int(binary.sum()) != candidate.get("pixel_count"):
                raise NudeBoxMaskGenerationError("provider_mask_pixel_count_mismatch")
            candidates += 1
    if candidates != validated.get("candidate_count"):
        raise NudeBoxMaskGenerationError("provider_batch_candidate_count_mismatch")
    return validated


def validate_box_prompt_provider_batch_structure(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate sealed metadata without reading candidate artifacts."""

    if not isinstance(document, Mapping):
        raise NudeBoxMaskGenerationError("provider_batch_invalid")
    if document.get("schema_version") != "maskfactory.nude_box_prompt_provider_batch.v1":
        raise NudeBoxMaskGenerationError("provider_batch_schema_invalid")
    body = {key: value for key, value in document.items() if key != "self_sha256"}
    if document.get("self_sha256") != _canonical_sha256(body):
        raise NudeBoxMaskGenerationError("provider_batch_hash_mismatch")
    records = document.get("records")
    if not isinstance(records, list) or len(records) != document.get("record_count"):
        raise NudeBoxMaskGenerationError("provider_batch_records_invalid")
    provider = document.get("provider")
    expected_provider_fields = {
        "provider_key",
        "role",
        "model_family",
        "source_commit",
        "runtime_fingerprint",
        "contract_version",
    }
    if not isinstance(provider, Mapping) or set(provider) != expected_provider_fields:
        raise NudeBoxMaskGenerationError("provider_batch_identity_invalid")
    try:
        identity = ProviderIdentity(**provider)
    except (TypeError, ValueError) as exc:
        raise NudeBoxMaskGenerationError("provider_batch_identity_invalid") from exc
    if identity.role != "interactive_segmenter":
        raise NudeBoxMaskGenerationError("provider_batch_role_invalid")
    if (
        document.get("authority") != "draft_provider_masks_only"
        or document.get("source_images_are_pixel_truth") is not False
        or document.get("boxes_are_pixel_truth") is not False
        or document.get("production_mask_authority") is not False
        or document.get("operational_certificates_issued") is not False
    ):
        raise NudeBoxMaskGenerationError("provider_batch_authority_invalid")
    if (
        not isinstance(document.get("catalog_batch_sha256"), str)
        or SHA256.fullmatch(document["catalog_batch_sha256"]) is None
    ):
        raise NudeBoxMaskGenerationError("provider_batch_catalog_hash_invalid")
    candidate_count = 0
    statuses = Counter()
    sample_ids = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise NudeBoxMaskGenerationError("provider_batch_record_invalid")
        sample_id = record.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id or sample_id in sample_ids:
            raise NudeBoxMaskGenerationError("provider_batch_sample_id_invalid")
        sample_ids.add(sample_id)
        status = record.get("status")
        if status not in {"generated", "catalog_abstain", "provider_abstain"}:
            raise NudeBoxMaskGenerationError("provider_batch_status_invalid")
        candidates = record.get("candidates")
        if not isinstance(candidates, list) or (status == "generated") != bool(candidates):
            raise NudeBoxMaskGenerationError("provider_batch_candidate_state_invalid")
        if (
            not isinstance(record.get("source_sha256"), str)
            or SHA256.fullmatch(record["source_sha256"]) is None
        ):
            raise NudeBoxMaskGenerationError("provider_batch_source_hash_invalid")
        if not isinstance(record.get("reason"), list) or not all(
            isinstance(reason, str) for reason in record["reason"]
        ):
            raise NudeBoxMaskGenerationError("provider_batch_reasons_invalid")
        statuses[status] += 1
        person_indexes = set()
        for candidate in record.get("candidates", ()):
            if not isinstance(candidate, Mapping):
                raise NudeBoxMaskGenerationError("provider_batch_candidate_invalid")
            person_index = candidate.get("person_index")
            if (
                not isinstance(person_index, int)
                or isinstance(person_index, bool)
                or person_index < 0
                or person_index in person_indexes
            ):
                raise NudeBoxMaskGenerationError("provider_batch_person_index_invalid")
            person_indexes.add(person_index)
            if (
                candidate.get("candidate_label") != "person"
                or candidate.get("authority") != "draft_machine_candidate_only"
                or candidate.get("production_mask_authority") is not False
                or candidate.get("operational_certificate_eligible") is not False
            ):
                raise NudeBoxMaskGenerationError("provider_batch_candidate_authority_invalid")
            for field in ("mask_sha256", "artifact_sha256"):
                if (
                    not isinstance(candidate.get(field), str)
                    or SHA256.fullmatch(candidate[field]) is None
                ):
                    raise NudeBoxMaskGenerationError(f"provider_batch_{field}_invalid")
            relative = Path(str(candidate.get("artifact_relative_path") or ""))
            if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                raise NudeBoxMaskGenerationError("provider_batch_candidate_path_invalid")
            confidence = candidate.get("confidence")
            pixel_count = candidate.get("pixel_count")
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not math.isfinite(float(confidence))
                or not 0 <= float(confidence) <= 1
                or isinstance(pixel_count, bool)
                or not isinstance(pixel_count, int)
                or pixel_count < 1
                or not isinstance(candidate.get("prompt_fingerprint"), str)
                or not candidate["prompt_fingerprint"]
            ):
                raise NudeBoxMaskGenerationError("provider_batch_candidate_metadata_invalid")
            candidate_count += 1
    if candidate_count != document.get("candidate_count"):
        raise NudeBoxMaskGenerationError("provider_batch_candidate_count_mismatch")
    if dict(sorted(statuses.items())) != document.get("status_counts"):
        raise NudeBoxMaskGenerationError("provider_batch_status_counts_mismatch")
    return dict(document)


def build_box_prompt_mask_stage_receipt(
    *,
    provider: Mapping[str, Any],
    catalog_batch_sha256: str,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Seal one provider/record result for nonterminal queue checkpointing."""

    required_identity = {
        "provider_key",
        "role",
        "model_family",
        "source_commit",
        "runtime_fingerprint",
        "contract_version",
    }
    if not isinstance(provider, Mapping) or set(provider) != required_identity:
        raise NudeBoxMaskGenerationError("mask_stage_provider_identity_invalid")
    identity = ProviderIdentity(**provider)
    if identity.role != "interactive_segmenter":
        raise NudeBoxMaskGenerationError("mask_stage_provider_role_invalid")
    if not isinstance(catalog_batch_sha256, str) or SHA256.fullmatch(catalog_batch_sha256) is None:
        raise NudeBoxMaskGenerationError("mask_stage_catalog_hash_invalid")
    if not isinstance(record, Mapping):
        raise NudeBoxMaskGenerationError("mask_stage_record_invalid")
    sample_id = record.get("sample_id")
    source_sha256 = record.get("source_sha256")
    status = record.get("status")
    reasons = record.get("reason")
    candidates = record.get("candidates")
    if not isinstance(sample_id, str) or not sample_id:
        raise NudeBoxMaskGenerationError("mask_stage_sample_id_invalid")
    if not isinstance(source_sha256, str) or SHA256.fullmatch(source_sha256) is None:
        raise NudeBoxMaskGenerationError("mask_stage_source_hash_invalid")
    if status not in {"generated", "catalog_abstain", "provider_abstain"}:
        raise NudeBoxMaskGenerationError("mask_stage_status_invalid")
    if not isinstance(reasons, list) or not all(isinstance(reason, str) for reason in reasons):
        raise NudeBoxMaskGenerationError("mask_stage_reasons_invalid")
    if not isinstance(candidates, list):
        raise NudeBoxMaskGenerationError("mask_stage_candidates_invalid")
    if status == "generated" and not candidates:
        raise NudeBoxMaskGenerationError("mask_stage_generated_candidates_required")
    if status != "generated" and candidates:
        raise NudeBoxMaskGenerationError("mask_stage_abstain_candidates_forbidden")
    seen_people = set()
    normalized_candidates = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise NudeBoxMaskGenerationError("mask_stage_candidate_invalid")
        person_index = candidate.get("person_index")
        if (
            not isinstance(person_index, int)
            or isinstance(person_index, bool)
            or person_index < 0
            or person_index in seen_people
        ):
            raise NudeBoxMaskGenerationError("mask_stage_person_index_invalid")
        seen_people.add(person_index)
        if (
            candidate.get("authority") != "draft_machine_candidate_only"
            or candidate.get("production_mask_authority") is not False
            or candidate.get("operational_certificate_eligible") is not False
        ):
            raise NudeBoxMaskGenerationError("mask_stage_candidate_authority_invalid")
        for field in ("mask_sha256", "artifact_sha256"):
            if (
                not isinstance(candidate.get(field), str)
                or SHA256.fullmatch(candidate[field]) is None
            ):
                raise NudeBoxMaskGenerationError(f"mask_stage_{field}_invalid")
        normalized_candidates.append(dict(candidate))
    normalized_candidates.sort(key=lambda candidate: candidate["person_index"])
    body: dict[str, Any] = {
        "schema_version": "maskfactory.nude_box_prompt_mask_stage.v1",
        "stage": f"box_prompt_mask_generation:{identity.provider_key}",
        "sample_id": sample_id,
        "source_sha256": source_sha256,
        "catalog_batch_sha256": catalog_batch_sha256,
        "provider": dict(provider),
        "status": status,
        "reasons": reasons,
        "candidate_count": len(normalized_candidates),
        "candidates": normalized_candidates,
        "authority": "intermediate_non_authoritative_evidence",
        "production_mask_authority": False,
        "operational_certificate_issued": False,
    }
    return {**body, "evidence_sha256": _canonical_sha256(body)}


def validate_box_prompt_mask_stage_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise NudeBoxMaskGenerationError("mask_stage_payload_invalid")
    if payload.get("schema_version") != "maskfactory.nude_box_prompt_mask_stage.v1":
        raise NudeBoxMaskGenerationError("mask_stage_schema_invalid")
    rebuilt = build_box_prompt_mask_stage_receipt(
        provider=payload.get("provider", {}),
        catalog_batch_sha256=str(payload.get("catalog_batch_sha256") or ""),
        record={
            "sample_id": payload.get("sample_id"),
            "source_sha256": payload.get("source_sha256"),
            "status": payload.get("status"),
            "reason": payload.get("reasons"),
            "candidates": payload.get("candidates"),
        },
    )
    if dict(payload) != rebuilt:
        raise NudeBoxMaskGenerationError("mask_stage_evidence_drift")
    return rebuilt


def compare_box_prompt_provider_batches(
    batches: Sequence[Mapping[str, Any]],
    *,
    output_roots: Sequence[Path],
    iou_min: float = 0.80,
) -> dict[str, Any]:
    """Compare independent provider masks; agreement remains non-authoritative."""

    if len(batches) < 2 or len(output_roots) != len(batches):
        raise NudeBoxMaskGenerationError("two_provider_batches_required")
    if not 0 < iou_min <= 1:
        raise NudeBoxMaskGenerationError("mask_iou_policy_invalid")
    validated = [
        validate_box_prompt_provider_batch(batch, output_root=root)
        for batch, root in zip(batches, output_roots, strict=True)
    ]
    identities = [ProviderIdentity(**batch["provider"]) for batch in validated]
    try:
        require_independent_model_families(identities, minimum=2)
    except ValueError as exc:
        raise NudeBoxMaskGenerationError("provider_mask_families_not_independent") from exc
    if len({batch["catalog_batch_sha256"] for batch in validated}) != 1:
        raise NudeBoxMaskGenerationError("provider_catalog_batch_mismatch")
    indexes = [{row["sample_id"]: row for row in batch["records"]} for batch in validated]
    if any(set(index) != set(indexes[0]) for index in indexes[1:]):
        raise NudeBoxMaskGenerationError("provider_sample_set_mismatch")
    output = []
    roots = [Path(root).resolve() for root in output_roots]
    for sample_id in sorted(indexes[0]):
        rows = [index[sample_id] for index in indexes]
        source_sha256 = rows[0]["source_sha256"]
        reasons = []
        comparisons = []
        if any(row["source_sha256"] != source_sha256 for row in rows):
            raise NudeBoxMaskGenerationError("provider_source_hash_mismatch")
        if any(row["status"] != "generated" for row in rows):
            reasons.append("provider_generation_incomplete")
        else:
            candidate_maps = [
                {candidate["person_index"]: candidate for candidate in row["candidates"]}
                for row in rows
            ]
            if any(set(mapping) != set(candidate_maps[0]) for mapping in candidate_maps[1:]):
                reasons.append("provider_person_set_mismatch")
            else:
                for person_index in sorted(candidate_maps[0]):
                    masks = []
                    for provider_index, mapping in enumerate(candidate_maps):
                        candidate = mapping[person_index]
                        path = roots[provider_index] / candidate["artifact_relative_path"]
                        masks.append(read_mask(path) == 255)
                    pairwise = []
                    for left in range(len(masks)):
                        for right in range(left + 1, len(masks)):
                            intersection = int(np.count_nonzero(masks[left] & masks[right]))
                            union = int(np.count_nonzero(masks[left] | masks[right]))
                            pairwise.append(intersection / union if union else 0.0)
                    minimum = min(pairwise)
                    comparisons.append(
                        {"person_index": person_index, "minimum_pairwise_iou": minimum}
                    )
                    if minimum < iou_min:
                        reasons.append("provider_mask_spatial_disagreement")
        output.append(
            {
                "sample_id": sample_id,
                "source_sha256": source_sha256,
                "status": "pass" if not reasons else "abstain",
                "reasons": sorted(set(reasons)),
                "comparisons": comparisons,
            }
        )
    counts = Counter(row["status"] for row in output)
    body = {
        "schema_version": "maskfactory.nude_box_prompt_mask_comparison.v1",
        "catalog_batch_sha256": validated[0]["catalog_batch_sha256"],
        "provider_batch_sha256": [batch["self_sha256"] for batch in validated],
        "provider_families": sorted(identity.model_family for identity in identities),
        "policy": {"minimum_pairwise_iou": iou_min},
        "record_count": len(output),
        "status_counts": dict(sorted(counts.items())),
        "records": output,
        "authority": "draft_mask_comparison_only",
        "hard_qc_complete": False,
        "strict_visual_review_complete": False,
        "production_mask_authority": False,
        "operational_certificates_issued": False,
    }
    return {**body, "self_sha256": _canonical_sha256(body)}


__all__ = [
    "NudeBoxMaskGenerationError",
    "Sam2BoxPromptInteractiveSegmenter",
    "build_box_prompt_mask_stage_receipt",
    "compare_box_prompt_provider_batches",
    "generate_box_prompt_provider_batch",
    "validate_box_prompt_mask_stage_receipt",
    "validate_box_prompt_provider_batch",
    "validate_box_prompt_provider_batch_structure",
]
