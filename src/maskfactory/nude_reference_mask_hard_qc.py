"""Deterministic hard-QA vetoes for generated reference-corpus person masks."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError
from scipy import ndimage

from .nude_box_mask_generation import validate_box_prompt_provider_batch_structure
from .providers.disagreement import binary_mask_sha256

SHA256 = re.compile(r"^[a-f0-9]{64}$")
DEFAULT_POLICY = {
    "minimum_mask_to_prompt_box_ratio": 0.05,
    "maximum_component_count": 16,
    "minimum_largest_component_fraction": 0.50,
    "maximum_cross_person_overlap_pixels": 0,
}


class NudeReferenceMaskHardQcError(ValueError):
    """Hard-QA input identity or policy failed closed."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _policy(value: Mapping[str, Any] | None) -> dict[str, Any]:
    policy = dict(DEFAULT_POLICY if value is None else value)
    if set(policy) != set(DEFAULT_POLICY):
        raise NudeReferenceMaskHardQcError("reference_mask_hard_qc_policy_fields_invalid")
    minimum_ratio = policy["minimum_mask_to_prompt_box_ratio"]
    maximum_components = policy["maximum_component_count"]
    largest_fraction = policy["minimum_largest_component_fraction"]
    maximum_overlap = policy["maximum_cross_person_overlap_pixels"]
    if (
        isinstance(minimum_ratio, bool)
        or not isinstance(minimum_ratio, (int, float))
        or not 0 < float(minimum_ratio) < 1
        or isinstance(maximum_components, bool)
        or not isinstance(maximum_components, int)
        or maximum_components < 1
        or isinstance(largest_fraction, bool)
        or not isinstance(largest_fraction, (int, float))
        or not 0 < float(largest_fraction) <= 1
        or isinstance(maximum_overlap, bool)
        or not isinstance(maximum_overlap, int)
        or maximum_overlap < 0
    ):
        raise NudeReferenceMaskHardQcError("reference_mask_hard_qc_policy_invalid")
    if (
        float(minimum_ratio) < DEFAULT_POLICY["minimum_mask_to_prompt_box_ratio"]
        or maximum_components > DEFAULT_POLICY["maximum_component_count"]
        or float(largest_fraction) < DEFAULT_POLICY["minimum_largest_component_fraction"]
        or maximum_overlap > DEFAULT_POLICY["maximum_cross_person_overlap_pixels"]
    ):
        raise NudeReferenceMaskHardQcError("reference_mask_hard_qc_policy_weakened")
    return policy


def _check(check_id: str, passed: bool, detail: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "severity": "BLOCK",
        "passed": bool(passed),
        "detail": dict(detail),
    }


def _candidate_base_checks(
    candidate: Mapping[str, Any],
    *,
    output_root: Path,
    source_shape: tuple[int, int],
    policy: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], np.ndarray | None]:
    checks = []
    root = Path(output_root).resolve()
    relative = Path(str(candidate.get("artifact_relative_path") or ""))
    path = (root / relative).resolve()
    contained_path = path != root and root in path.parents
    artifact_exists = contained_path and path.is_file()
    artifact_hash_matches = bool(
        artifact_exists and _file_sha256(path) == candidate.get("artifact_sha256")
    )
    checks.append(
        _check(
            "NREF-QC-001",
            contained_path and artifact_exists and artifact_hash_matches,
            {
                "path_contained": contained_path,
                "artifact_exists": artifact_exists,
                "artifact_hash_matches": artifact_hash_matches,
            },
        )
    )
    if not artifact_exists:
        return checks, None
    try:
        with Image.open(path) as image:
            mode = image.mode
            size = image.size
            pixels = np.asarray(image)
    except (OSError, UnidentifiedImageError):
        checks.append(
            _check(
                "NREF-QC-002",
                False,
                {"mode": None, "size": None, "strict_binary": False},
            )
        )
        return checks, None
    height, width = source_shape
    values = set(np.unique(pixels).tolist()) if pixels.ndim == 2 else set()
    strict_binary = mode == "L" and size == (width, height) and values <= {0, 255}
    checks.append(
        _check(
            "NREF-QC-002",
            strict_binary,
            {
                "mode": mode,
                "size": list(size),
                "source_size": [width, height],
                "strict_binary": strict_binary,
            },
        )
    )
    if not strict_binary:
        return checks, None
    mask = pixels == 255
    mask_sha256 = binary_mask_sha256(mask)
    pixel_count = int(mask.sum())
    identity_matches = mask_sha256 == candidate.get("mask_sha256") and pixel_count == candidate.get(
        "pixel_count"
    )
    checks.append(
        _check(
            "NREF-QC-003",
            identity_matches,
            {
                "mask_sha256": mask_sha256,
                "declared_mask_sha256": candidate.get("mask_sha256"),
                "pixel_count": pixel_count,
                "declared_pixel_count": candidate.get("pixel_count"),
            },
        )
    )
    prompt = candidate.get("prompt")
    try:
        left, top, right, bottom = (int(value) for value in prompt["box_xyxy"])
        point_x, point_y = (int(value) for value in prompt["positive_points"][0])
        prompt_sha_matches = prompt.get("prompt_sha256") == _canonical_sha256(
            {
                key: prompt[key]
                for key in ("positive_points", "negative_points", "box_xyxy", "mask_prompt")
            }
        )
        prompt_geometry_valid = (
            0 <= left < right <= width
            and 0 <= top < bottom <= height
            and left <= point_x < right
            and top <= point_y < bottom
        )
    except (KeyError, TypeError, ValueError, IndexError):
        left = top = right = bottom = point_x = point_y = 0
        prompt_sha_matches = False
        prompt_geometry_valid = False
    outside_pixels = None
    positive_hit = False
    prompt_box_area = 0
    ratio = 0.0
    if prompt_geometry_valid:
        allowed = np.zeros(mask.shape, dtype=bool)
        allowed[top:bottom, left:right] = True
        outside_pixels = int(np.count_nonzero(mask & ~allowed))
        positive_hit = bool(mask[point_y, point_x])
        prompt_box_area = (right - left) * (bottom - top)
        ratio = pixel_count / prompt_box_area
    prompt_pass = bool(
        prompt_sha_matches and prompt_geometry_valid and outside_pixels == 0 and positive_hit
    )
    checks.append(
        _check(
            "NREF-QC-004",
            prompt_pass,
            {
                "prompt_sha_matches": prompt_sha_matches,
                "prompt_geometry_valid": prompt_geometry_valid,
                "outside_prompt_box_pixels": outside_pixels,
                "positive_point_hit": positive_hit,
            },
        )
    )
    noncollapsed = bool(
        pixel_count > 0 and ratio >= float(policy["minimum_mask_to_prompt_box_ratio"])
    )
    checks.append(
        _check(
            "NREF-QC-005",
            noncollapsed,
            {
                "mask_pixels": pixel_count,
                "prompt_box_pixels": prompt_box_area,
                "mask_to_prompt_box_ratio": ratio,
                "minimum_ratio": policy["minimum_mask_to_prompt_box_ratio"],
            },
        )
    )
    components, component_count = ndimage.label(mask)
    component_sizes = np.bincount(components.ravel())[1:]
    largest_fraction = float(component_sizes.max() / pixel_count) if pixel_count else 0.0
    topology_pass = bool(
        component_count <= int(policy["maximum_component_count"])
        and largest_fraction >= float(policy["minimum_largest_component_fraction"])
    )
    checks.append(
        _check(
            "NREF-QC-006",
            topology_pass,
            {
                "component_count": int(component_count),
                "maximum_component_count": policy["maximum_component_count"],
                "largest_component_fraction": largest_fraction,
                "minimum_largest_component_fraction": policy["minimum_largest_component_fraction"],
            },
        )
    )
    return checks, mask


def run_reference_person_mask_hard_qc(
    provider_batch: Mapping[str, Any],
    *,
    output_root: Path,
    source_paths: Mapping[str, Path],
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply non-overridable per-candidate and multi-person hard-QA checks."""

    policy = _policy(policy)
    # Structural tamper stops the batch. Source/artifact defects become a hard
    # per-record outcome so unrelated records continue.
    validated = validate_box_prompt_provider_batch_structure(provider_batch)
    paths = {str(key): Path(value) for key, value in source_paths.items()}
    output_records = []
    for record in validated["records"]:
        sample_id = record["sample_id"]
        if record["status"] != "generated":
            output_records.append(
                {
                    "sample_id": sample_id,
                    "source_sha256": record["source_sha256"],
                    "status": "upstream_abstain",
                    "blockers": ["NREF-UPSTREAM-INCOMPLETE"],
                    "source_check": None,
                    "candidate_reports": [],
                }
            )
            continue
        source_path = paths.get(sample_id)
        source_exists = bool(source_path is not None and source_path.is_file())
        source_hash_matches = bool(
            source_exists and _file_sha256(source_path) == record["source_sha256"]
        )
        source_decodes = False
        width = height = 0
        if source_hash_matches:
            try:
                with Image.open(source_path) as source_image:
                    width, height = source_image.size
                source_decodes = width > 0 and height > 0
            except (OSError, UnidentifiedImageError):
                source_decodes = False
        source_check = _check(
            "NREF-QC-000",
            source_exists and source_hash_matches and source_decodes,
            {
                "source_exists": source_exists,
                "source_hash_matches": source_hash_matches,
                "source_decodes": source_decodes,
                "source_size": [width, height] if source_decodes else None,
            },
        )
        if not source_check["passed"]:
            output_records.append(
                {
                    "sample_id": sample_id,
                    "source_sha256": record["source_sha256"],
                    "status": "fail",
                    "blockers": ["NREF-QC-000"],
                    "source_check": source_check,
                    "candidate_reports": [],
                }
            )
            continue
        candidate_reports = []
        masks: dict[int, np.ndarray] = {}
        for candidate in record["candidates"]:
            checks, mask = _candidate_base_checks(
                candidate,
                output_root=output_root,
                source_shape=(height, width),
                policy=policy,
            )
            person_index = int(candidate["person_index"])
            if mask is not None:
                masks[person_index] = mask
            candidate_reports.append(
                {
                    "person_index": person_index,
                    "mask_sha256": candidate["mask_sha256"],
                    "checks": checks,
                }
            )
        by_person = {report["person_index"]: report for report in candidate_reports}
        hash_groups: dict[str, list[int]] = {}
        for report in candidate_reports:
            hash_groups.setdefault(report["mask_sha256"], []).append(report["person_index"])
        duplicated_people = {
            person_index
            for people in hash_groups.values()
            if len(people) > 1
            for person_index in people
        }
        for person_index, report in by_person.items():
            report["checks"].append(
                _check(
                    "NREF-QC-007",
                    person_index not in duplicated_people,
                    {"duplicate_person_indexes": sorted(duplicated_people)},
                )
            )
        overlap_by_person = {person_index: 0 for person_index in by_person}
        people = sorted(masks)
        for left_index, left in enumerate(people):
            for right in people[left_index + 1 :]:
                overlap = int(np.count_nonzero(masks[left] & masks[right]))
                overlap_by_person[left] += overlap
                overlap_by_person[right] += overlap
        for person_index, report in by_person.items():
            overlap = overlap_by_person[person_index]
            report["checks"].append(
                _check(
                    "NREF-QC-008",
                    overlap <= int(policy["maximum_cross_person_overlap_pixels"]),
                    {
                        "cross_person_overlap_pixels": overlap,
                        "maximum_cross_person_overlap_pixels": policy[
                            "maximum_cross_person_overlap_pixels"
                        ],
                    },
                )
            )
            report["status"] = (
                "pass" if all(check["passed"] for check in report["checks"]) else "fail"
            )
            report["blockers"] = [
                check["check_id"] for check in report["checks"] if not check["passed"]
            ]
            report_body = dict(report)
            report["report_sha256"] = _canonical_sha256(report_body)
        blockers = sorted(
            {blocker for report in candidate_reports for blocker in report["blockers"]}
        )
        output_records.append(
            {
                "sample_id": sample_id,
                "source_sha256": record["source_sha256"],
                "status": "pass" if not blockers else "fail",
                "blockers": blockers,
                "source_check": source_check,
                "candidate_reports": candidate_reports,
            }
        )
    counts = Counter(record["status"] for record in output_records)
    policy_sha256 = _canonical_sha256(policy)
    body = {
        "schema_version": "maskfactory.nude_reference_person_mask_hard_qc.v1",
        "provider_batch_sha256": validated["self_sha256"],
        "provider": validated["provider"],
        "policy": policy,
        "policy_sha256": policy_sha256,
        "record_count": len(output_records),
        "status_counts": dict(sorted(counts.items())),
        "records": output_records,
        "hard_qc_complete_for_retained_candidates": True,
        "hard_qc_may_be_overridden": False,
        "strict_visual_review_complete": False,
        "production_mask_authority": False,
        "operational_certificates_issued": False,
    }
    return {**body, "self_sha256": _canonical_sha256(body)}


def validate_reference_person_mask_hard_qc(
    document: Mapping[str, Any],
    *,
    provider_batch: Mapping[str, Any],
    output_root: Path,
    source_paths: Mapping[str, Path],
) -> dict[str, Any]:
    if document.get("schema_version") != "maskfactory.nude_reference_person_mask_hard_qc.v1":
        raise NudeReferenceMaskHardQcError("reference_mask_hard_qc_schema_invalid")
    rebuilt = run_reference_person_mask_hard_qc(
        provider_batch,
        output_root=output_root,
        source_paths=source_paths,
        policy=document.get("policy"),
    )
    if dict(document) != rebuilt:
        raise NudeReferenceMaskHardQcError("reference_mask_hard_qc_evidence_drift")
    return rebuilt


def build_reference_mask_hard_qc_stage_receipt(
    *,
    provider: Mapping[str, Any],
    provider_batch_sha256: str,
    policy_sha256: str,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Seal one nonterminal hard-QA decision for resumable queue replay."""

    provider_key = provider.get("provider_key") if isinstance(provider, Mapping) else None
    if not isinstance(provider_key, str) or not provider_key:
        raise NudeReferenceMaskHardQcError("hard_qc_stage_provider_invalid")
    for value, field in (
        (provider_batch_sha256, "provider_batch_sha256"),
        (policy_sha256, "policy_sha256"),
        (record.get("source_sha256"), "source_sha256"),
    ):
        if not isinstance(value, str) or SHA256.fullmatch(value) is None:
            raise NudeReferenceMaskHardQcError(f"hard_qc_stage_{field}_invalid")
    sample_id = record.get("sample_id")
    status = record.get("status")
    blockers = record.get("blockers")
    candidate_reports = record.get("candidate_reports")
    if not isinstance(sample_id, str) or not sample_id:
        raise NudeReferenceMaskHardQcError("hard_qc_stage_sample_id_invalid")
    if status not in {"pass", "fail", "upstream_abstain"}:
        raise NudeReferenceMaskHardQcError("hard_qc_stage_status_invalid")
    if not isinstance(blockers, list) or not all(isinstance(value, str) for value in blockers):
        raise NudeReferenceMaskHardQcError("hard_qc_stage_blockers_invalid")
    if (status == "pass") == bool(blockers):
        raise NudeReferenceMaskHardQcError("hard_qc_stage_status_blocker_mismatch")
    if not isinstance(candidate_reports, list):
        raise NudeReferenceMaskHardQcError("hard_qc_stage_candidate_reports_invalid")
    body = {
        "schema_version": "maskfactory.nude_reference_mask_hard_qc_stage.v1",
        "stage": f"reference_person_mask_hard_qc:{provider_key}",
        "sample_id": sample_id,
        "source_sha256": record["source_sha256"],
        "provider": dict(provider),
        "provider_batch_sha256": provider_batch_sha256,
        "policy_sha256": policy_sha256,
        "status": status,
        "blockers": list(blockers),
        "source_check": record.get("source_check"),
        "candidate_reports": [dict(report) for report in candidate_reports],
        "authority": "intermediate_hard_qc_evidence",
        "hard_qc_may_be_overridden": False,
        "production_mask_authority": False,
        "operational_certificate_issued": False,
    }
    return {**body, "evidence_sha256": _canonical_sha256(body)}


def validate_reference_mask_hard_qc_stage_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise NudeReferenceMaskHardQcError("hard_qc_stage_payload_invalid")
    if payload.get("schema_version") != "maskfactory.nude_reference_mask_hard_qc_stage.v1":
        raise NudeReferenceMaskHardQcError("hard_qc_stage_schema_invalid")
    rebuilt = build_reference_mask_hard_qc_stage_receipt(
        provider=payload.get("provider", {}),
        provider_batch_sha256=str(payload.get("provider_batch_sha256") or ""),
        policy_sha256=str(payload.get("policy_sha256") or ""),
        record={
            "sample_id": payload.get("sample_id"),
            "source_sha256": payload.get("source_sha256"),
            "status": payload.get("status"),
            "blockers": payload.get("blockers"),
            "source_check": payload.get("source_check"),
            "candidate_reports": payload.get("candidate_reports"),
        },
    )
    if dict(payload) != rebuilt:
        raise NudeReferenceMaskHardQcError("hard_qc_stage_evidence_drift")
    return rebuilt


__all__ = [
    "DEFAULT_POLICY",
    "NudeReferenceMaskHardQcError",
    "build_reference_mask_hard_qc_stage_receipt",
    "run_reference_person_mask_hard_qc",
    "validate_reference_person_mask_hard_qc",
    "validate_reference_mask_hard_qc_stage_receipt",
]
