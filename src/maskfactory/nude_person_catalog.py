"""Fail-closed comparison of independent person-proposal catalogs."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

SHA256 = re.compile(r"^[a-f0-9]{64}$")
MAX_EXACT_MATCH_PEOPLE = 8


class NudePersonCatalogError(ValueError):
    """Person proposal evidence violated its governed contract."""


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise NudePersonCatalogError(f"{field}_invalid")
    return value


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NudePersonCatalogError(f"{field}_invalid")
    return value.strip()


def _box(value: Any, *, width: int, height: int) -> tuple[float, float, float, float]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 4
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)
    ):
        raise NudePersonCatalogError("person_bbox_invalid")
    box = tuple(float(item) for item in value)
    left, top, right, bottom = box
    if (
        not all(math.isfinite(item) for item in box)
        or left < 0
        or top < 0
        or right <= left
        or bottom <= top
        or right > width
        or bottom > height
    ):
        raise NudePersonCatalogError("person_bbox_out_of_bounds")
    return box


def _iou(left: Sequence[float], right: Sequence[float]) -> float:
    x1, y1 = max(left[0], right[0]), max(left[1], right[1])
    x2, y2 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


def _unique_matching(
    anchor: Sequence[Mapping[str, Any]],
    candidate: Sequence[Mapping[str, Any]],
    *,
    iou_min: float,
) -> tuple[int, ...] | None:
    matches: list[tuple[int, ...]] = []
    for permutation in itertools.permutations(range(len(candidate))):
        if all(
            _iou(anchor[index]["bbox_xyxy"], candidate[other]["bbox_xyxy"]) >= iou_min
            for index, other in enumerate(permutation)
        ):
            matches.append(permutation)
            if len(matches) > 1:
                return None
    return matches[0] if len(matches) == 1 else None


def compare_person_proposal_catalogs(
    *,
    sample_id: str,
    source_sha256: str,
    image_size: Sequence[int],
    provider_records: Sequence[Mapping[str, Any]],
    iou_min: float = 0.50,
) -> dict[str, Any]:
    """Compare proposal-only person catalogs without promoting mask authority."""

    sample_id = _nonempty(sample_id, "sample_id")
    source_sha256 = _sha(source_sha256, "source_sha256")
    if (
        not isinstance(image_size, Sequence)
        or isinstance(image_size, (str, bytes))
        or len(image_size) != 2
        or any(
            isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in image_size
        )
    ):
        raise NudePersonCatalogError("image_size_invalid")
    width, height = image_size
    if not 0 < iou_min <= 1:
        raise NudePersonCatalogError("iou_policy_invalid")
    if len(provider_records) < 2:
        raise NudePersonCatalogError("two_provider_families_required")

    normalized = []
    identities: set[str] = set()
    families: set[str] = set()
    for record in provider_records:
        if not isinstance(record, Mapping):
            raise NudePersonCatalogError("provider_record_invalid")
        provider_id = _nonempty(record.get("provider_id"), "provider_id")
        family_id = _nonempty(record.get("family_id"), "family_id")
        revision = _nonempty(record.get("revision"), "provider_revision")
        identity = f"{provider_id}@{revision}"
        if identity in identities or family_id in families:
            raise NudePersonCatalogError("provider_families_not_independent")
        if record.get("source_sha256") != source_sha256:
            raise NudePersonCatalogError("provider_source_mismatch")
        artifact_sha256 = _sha(record.get("artifact_sha256"), "provider_artifact_sha256")
        raw_proposals = record.get("proposals")
        if not isinstance(raw_proposals, Sequence) or isinstance(raw_proposals, (str, bytes)):
            raise NudePersonCatalogError("provider_proposals_invalid")
        proposals = []
        for proposal in raw_proposals:
            if not isinstance(proposal, Mapping):
                raise NudePersonCatalogError("person_proposal_invalid")
            if proposal.get("label") != "person" or proposal.get("authority") != "proposal_only":
                raise NudePersonCatalogError("person_proposal_authority_invalid")
            confidence = proposal.get("confidence", proposal.get("box_score"))
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not math.isfinite(float(confidence))
                or not 0 <= float(confidence) <= 1
            ):
                raise NudePersonCatalogError("person_confidence_invalid")
            proposals.append(
                {
                    "bbox_xyxy": list(_box(proposal.get("bbox_xyxy"), width=width, height=height)),
                    "confidence": float(confidence),
                }
            )
        identities.add(identity)
        families.add(family_id)
        normalized.append(
            {
                "provider_id": provider_id,
                "family_id": family_id,
                "revision": revision,
                "artifact_sha256": artifact_sha256,
                "proposals": proposals,
            }
        )
    normalized.sort(key=lambda row: (row["family_id"], row["provider_id"], row["revision"]))

    counts = [len(row["proposals"]) for row in normalized]
    reasons: list[str] = []
    catalog: list[dict[str, Any]] = []
    if not all(counts):
        reasons.append("no_person_consensus")
    elif len(set(counts)) != 1:
        reasons.append("person_count_disagreement")
    elif counts[0] > MAX_EXACT_MATCH_PEOPLE:
        reasons.append("person_count_exceeds_exact_match_limit")
    else:
        anchor = normalized[0]["proposals"]
        anchor_order = sorted(
            range(len(anchor)),
            key=lambda index: (
                (anchor[index]["bbox_xyxy"][0] + anchor[index]["bbox_xyxy"][2]) / 2,
                (anchor[index]["bbox_xyxy"][1] + anchor[index]["bbox_xyxy"][3]) / 2,
                index,
            ),
        )
        aligned = [[anchor[index] for index in anchor_order]]
        for provider in normalized[1:]:
            match = _unique_matching(aligned[0], provider["proposals"], iou_min=iou_min)
            if match is None:
                reasons.append("person_spatial_matching_ambiguous")
                break
            aligned.append([provider["proposals"][index] for index in match])
        if not reasons:
            for person_index in range(counts[0]):
                members = []
                pairwise_ious = []
                for provider_index, provider in enumerate(normalized):
                    proposal = aligned[provider_index][person_index]
                    members.append(
                        {
                            "provider_id": provider["provider_id"],
                            "family_id": provider["family_id"],
                            **proposal,
                        }
                    )
                for left in range(len(members)):
                    for right in range(left + 1, len(members)):
                        pairwise_ious.append(
                            _iou(members[left]["bbox_xyxy"], members[right]["bbox_xyxy"])
                        )
                catalog.append(
                    {
                        "person_index": person_index,
                        "minimum_pairwise_iou": min(pairwise_ious),
                        "members": members,
                    }
                )

    status = "pass" if not reasons else "abstain"
    body: dict[str, Any] = {
        "schema_version": "maskfactory.nude_person_catalog_comparison.v1",
        "status": status,
        "sample_id": sample_id,
        "source_sha256": source_sha256,
        "image_size": [width, height],
        "provider_family_count": len(families),
        "provider_person_counts": counts,
        "person_count": len(catalog) if status == "pass" else None,
        "catalog": catalog,
        "reasons": reasons,
        "policy": {"iou_min": iou_min, "max_exact_match_people": MAX_EXACT_MATCH_PEOPLE},
        "provider_records": normalized,
        "authority": "person_catalog_comparison_only",
        "production_mask_authority": False,
        "operational_certificate_eligible": False,
    }
    return {**body, "report_sha256": _canonical_sha256(body)}


__all__ = ["NudePersonCatalogError", "compare_person_proposal_catalogs"]
