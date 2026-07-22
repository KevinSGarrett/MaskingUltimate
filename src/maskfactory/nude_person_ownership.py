"""Conservative multi-provider person ownership for adult anatomy candidates."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from .providers.disagreement import binary_mask_sha256

SHA256 = re.compile(r"^[a-f0-9]{64}$")


class NudePersonOwnershipError(ValueError):
    """Person detections or anatomy ownership evidence failed closed."""


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise NudePersonOwnershipError(f"{field}_invalid")
    return value


def _box(value: Any, *, width: int, height: int) -> tuple[int, int, int, int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 4:
        raise NudePersonOwnershipError("person_bbox_invalid")
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
        raise NudePersonOwnershipError("person_bbox_invalid")
    left, top, right, bottom = (int(round(float(item))) for item in value)
    if left < 0 or top < 0 or right <= left or bottom <= top or right > width or bottom > height:
        raise NudePersonOwnershipError("person_bbox_out_of_bounds")
    return left, top, right, bottom


def _iou(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
    x1, y1 = max(left[0], right[0]), max(left[1], right[1])
    x2, y2 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


def resolve_person_instance_ownership(
    anatomy_mask: np.ndarray,
    *,
    source_sha256: str,
    mask_sha256: str,
    candidate_label: str,
    detector_reports: Sequence[Mapping[str, Any]],
    containment_min: float = 0.95,
    runner_up_max: float = 0.20,
    provider_box_iou_min: float = 0.50,
) -> dict[str, Any]:
    """Assign one anatomy mask only when two detector families agree on its owner.

    Detector-local person indexes are accepted only when the corresponding boxes
    overlap across every family.  Ambiguity produces a no-owner receipt rather
    than guessing or stopping unrelated batch records.
    """

    mask = np.asarray(anatomy_mask)
    if mask.ndim != 2 or mask.dtype != np.bool_ or not mask.any():
        raise NudePersonOwnershipError("anatomy_mask_invalid")
    source_sha256 = _sha(source_sha256, "source_sha256")
    if _sha(mask_sha256, "mask_sha256") != binary_mask_sha256(mask):
        raise NudePersonOwnershipError("mask_sha256_mismatch")
    if not isinstance(candidate_label, str) or not candidate_label.strip():
        raise NudePersonOwnershipError("candidate_label_invalid")
    if not 0 < containment_min <= 1 or not 0 <= runner_up_max < containment_min:
        raise NudePersonOwnershipError("containment_policy_invalid")
    if not 0 < provider_box_iou_min <= 1:
        raise NudePersonOwnershipError("provider_box_iou_policy_invalid")
    if len(detector_reports) < 2:
        raise NudePersonOwnershipError("two_detector_families_required")

    height, width = mask.shape
    families: set[str] = set()
    providers: set[str] = set()
    normalized_reports: list[dict[str, Any]] = []
    indexes: set[int] | None = None
    for report in detector_reports:
        if not isinstance(report, Mapping):
            raise NudePersonOwnershipError("detector_report_invalid")
        provider_id = str(report.get("provider_id") or "").strip()
        family_id = str(report.get("family_id") or "").strip()
        if not provider_id or not family_id or provider_id in providers:
            raise NudePersonOwnershipError("detector_identity_invalid")
        if family_id in families:
            raise NudePersonOwnershipError("detector_families_not_independent")
        if report.get("source_sha256") != source_sha256:
            raise NudePersonOwnershipError("detector_source_mismatch")
        report_sha256 = _sha(report.get("report_sha256"), "detector_report_sha256")
        raw_people = report.get("persons")
        if not isinstance(raw_people, Sequence) or isinstance(raw_people, (str, bytes)):
            raise NudePersonOwnershipError("detector_persons_invalid")
        people: list[dict[str, Any]] = []
        seen: set[int] = set()
        for person in raw_people:
            if not isinstance(person, Mapping):
                raise NudePersonOwnershipError("detector_person_invalid")
            person_index = person.get("person_index")
            if (
                not isinstance(person_index, int)
                or isinstance(person_index, bool)
                or person_index < 0
                or person_index in seen
            ):
                raise NudePersonOwnershipError("detector_person_index_invalid")
            seen.add(person_index)
            bbox = _box(person.get("bbox_xyxy"), width=width, height=height)
            confidence = person.get("confidence")
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not 0 <= float(confidence) <= 1
            ):
                raise NudePersonOwnershipError("detector_confidence_invalid")
            inside = int(mask[bbox[1] : bbox[3], bbox[0] : bbox[2]].sum())
            people.append(
                {
                    "person_index": person_index,
                    "bbox_xyxy": list(bbox),
                    "confidence": float(confidence),
                    "anatomy_containment": inside / int(mask.sum()),
                }
            )
        families.add(family_id)
        providers.add(provider_id)
        indexes = seen if indexes is None else indexes & seen
        normalized_reports.append(
            {
                "provider_id": provider_id,
                "family_id": family_id,
                "source_sha256": source_sha256,
                "report_sha256": report_sha256,
                "persons": sorted(people, key=lambda row: row["person_index"]),
            }
        )
    if len(families) < 2:
        raise NudePersonOwnershipError("two_detector_families_required")

    by_report = [
        {int(person["person_index"]): person for person in report["persons"]}
        for report in normalized_reports
    ]
    candidates = []
    for person_index in sorted(indexes or set()):
        rows = [report[person_index] for report in by_report]
        pair_ious = [_iou(tuple(rows[0]["bbox_xyxy"]), tuple(row["bbox_xyxy"])) for row in rows[1:]]
        candidates.append(
            {
                "person_index": person_index,
                "minimum_anatomy_containment": min(row["anatomy_containment"] for row in rows),
                "minimum_provider_box_iou": min(pair_ious, default=1.0),
            }
        )
    ordered = sorted(
        candidates,
        key=lambda row: (-row["minimum_anatomy_containment"], row["person_index"]),
    )
    winner = ordered[0] if ordered else None
    runner_up = ordered[1]["minimum_anatomy_containment"] if len(ordered) > 1 else 0.0
    verified = bool(
        winner
        and winner["minimum_anatomy_containment"] >= containment_min
        and winner["minimum_provider_box_iou"] >= provider_box_iou_min
        and runner_up <= runner_up_max
    )
    person_index = int(winner["person_index"]) if verified and winner else None
    report: dict[str, Any] = {
        "schema_version": "maskfactory.nude_person_instance_ownership.v1",
        "status": "verified" if verified else "ambiguous",
        "source_sha256": source_sha256,
        "mask_sha256": mask_sha256,
        "candidate_label": candidate_label,
        "person_index": person_index,
        "owner_id": f"person-{person_index}" if person_index is not None else None,
        "scene_instance_id": (
            f"nude-{source_sha256[:16]}-p{person_index}" if person_index is not None else None
        ),
        "detector_family_count": len(families),
        "detector_reports": normalized_reports,
        "candidates": ordered,
        "policy": {
            "containment_min": containment_min,
            "runner_up_max": runner_up_max,
            "provider_box_iou_min": provider_box_iou_min,
        },
        "reasons": [] if verified else ["person_instance_ownership_ambiguous"],
        "production_mask_authority": False,
        "operational_certificate_eligible": False,
    }
    report["report_sha256"] = _canonical_sha256(report)
    return report


def validate_person_instance_ownership_report(
    report: Mapping[str, Any],
    anatomy_mask: np.ndarray,
    *,
    source_sha256: str,
    mask_sha256: str,
    candidate_label: str,
) -> dict[str, Any]:
    """Recompute a complete ownership receipt from its bound pixels and detections."""

    if not isinstance(report, Mapping):
        raise NudePersonOwnershipError("ownership_report_invalid")
    policy = report.get("policy")
    detector_reports = report.get("detector_reports")
    if not isinstance(policy, Mapping) or not isinstance(detector_reports, Sequence):
        raise NudePersonOwnershipError("ownership_report_evidence_invalid")
    try:
        rebuilt = resolve_person_instance_ownership(
            anatomy_mask,
            source_sha256=source_sha256,
            mask_sha256=mask_sha256,
            candidate_label=candidate_label,
            detector_reports=detector_reports,
            containment_min=float(policy["containment_min"]),
            runner_up_max=float(policy["runner_up_max"]),
            provider_box_iou_min=float(policy["provider_box_iou_min"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, NudePersonOwnershipError):
            raise
        raise NudePersonOwnershipError("ownership_policy_invalid") from exc
    if dict(report) != rebuilt:
        raise NudePersonOwnershipError("ownership_report_drift")
    return rebuilt


__all__ = [
    "NudePersonOwnershipError",
    "resolve_person_instance_ownership",
    "validate_person_instance_ownership_report",
]
