"""Deterministic hard-QA and bounded repair for autonomous mask candidates."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import ndimage

SCHEMA_VERSION = "maskfactory_mask_hard_qa_campaign.v1"
ZERO_SHA256 = "0" * 64
CHECK_NAMES = (
    "format",
    "ontology",
    "ownership",
    "laterality",
    "topology",
    "protected_region",
    "complete_map",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


class MaskHardQAError(RuntimeError):
    """A mask record or candidate cannot be evaluated safely."""


@dataclass(frozen=True)
class MaskHardQALimits:
    max_components: int = 1
    max_repair_attempts: int = 2
    disagreement_iou_floor: float = 0.75

    def validate(self) -> None:
        if (
            not isinstance(self.max_components, int)
            or isinstance(self.max_components, bool)
            or self.max_components <= 0
        ):
            raise MaskHardQAError("max_components must be positive")
        if (
            not isinstance(self.max_repair_attempts, int)
            or isinstance(self.max_repair_attempts, bool)
            or self.max_repair_attempts < 0
        ):
            raise MaskHardQAError("max_repair_attempts must be non-negative")
        if (
            not isinstance(self.disagreement_iou_floor, (int, float))
            or isinstance(self.disagreement_iou_floor, bool)
            or not 0 <= self.disagreement_iou_floor <= 1
        ):
            raise MaskHardQAError("disagreement_iou_floor must be in [0, 1]")


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MaskHardQAError("hard-QA evidence is not canonical JSON") from exc


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _seal(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    sealed = deepcopy(dict(value))
    sealed[field] = ZERO_SHA256
    sealed[field] = _canonical_sha256(sealed)
    return sealed


def _verify_self_hash(value: Mapping[str, Any], field: str) -> None:
    declared = value.get(field)
    if not isinstance(declared, str) or not _SHA256_RE.fullmatch(declared):
        raise MaskHardQAError(f"{field} is invalid")
    zeroed = deepcopy(dict(value))
    zeroed[field] = ZERO_SHA256
    if _canonical_sha256(zeroed) != declared:
        raise MaskHardQAError(f"{field} canonical self-hash mismatch")


def _identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise MaskHardQAError(f"{field} is invalid")
    return value


def _array_sha256(array: np.ndarray) -> str:
    value = np.asarray(array)
    digest = hashlib.sha256()
    digest.update(str(value.dtype).encode("ascii"))
    digest.update(b"\0")
    digest.update(json.dumps(list(value.shape), separators=(",", ":")).encode("ascii"))
    digest.update(b"\0")
    digest.update(np.ascontiguousarray(value).tobytes())
    return digest.hexdigest()


def _resource_bool(value: object, *, name: str, shape: tuple[int, int]) -> np.ndarray:
    array = np.asarray(value)
    if array.shape != shape or array.ndim != 2:
        raise MaskHardQAError(f"{name} geometry differs from source")
    if array.dtype == np.bool_:
        return array.copy()
    if not np.issubdtype(array.dtype, np.integer):
        raise MaskHardQAError(f"{name} must be boolean/integer")
    unique = set(int(item) for item in np.unique(array))
    if not unique.issubset({0, 1, 255}):
        raise MaskHardQAError(f"{name} must be binary")
    return (array != 0).copy()


def _candidate_bool(value: object, *, shape: tuple[int, int]) -> tuple[np.ndarray | None, str]:
    array = np.asarray(value)
    if array.ndim != 2 or array.shape != shape:
        return None, "candidate geometry mismatch"
    if array.dtype != np.bool_ and not np.issubdtype(array.dtype, np.integer):
        return None, "candidate dtype is not boolean/integer"
    unique = set(int(item) for item in np.unique(array))
    if not unique.issubset({0, 1, 255}):
        return None, "candidate is not binary"
    normalized = (array != 0).copy()
    if not normalized.any():
        return None, "candidate is empty"
    return normalized, "candidate format is valid"


def _check(
    *,
    name: str,
    passed: bool,
    detail: str,
) -> dict[str, str]:
    return {
        "name": name,
        "status": "PASS" if passed else "BLOCK",
        "detail": detail,
    }


def _hard_qa(
    *,
    mask: np.ndarray,
    candidate_label_id: int,
    target_label_id: int,
    owner: np.ndarray,
    side: np.ndarray,
    protected: np.ndarray,
    complete_map: np.ndarray,
    ontology_label_ids: frozenset[int],
    limits: MaskHardQALimits,
) -> tuple[list[dict[str, str]], str | None]:
    labels, components = ndimage.label(mask)
    del labels
    has_holes = bool(np.any(ndimage.binary_fill_holes(mask) & ~mask))
    occupied_other = mask & ~np.isin(complete_map, (0, target_label_id))
    checks = [
        _check(name="format", passed=True, detail="binary geometry and nonempty area pass"),
        _check(
            name="ontology",
            passed=(
                candidate_label_id == target_label_id and candidate_label_id in ontology_label_ids
            ),
            detail=(
                f"candidate_label_id={candidate_label_id} " f"target_label_id={target_label_id}"
            ),
        ),
        _check(
            name="ownership",
            passed=not bool(np.any(mask & ~owner)),
            detail=f"outside_owner_px={int(np.count_nonzero(mask & ~owner))}",
        ),
        _check(
            name="laterality",
            passed=not bool(np.any(mask & ~side)),
            detail=f"outside_side_px={int(np.count_nonzero(mask & ~side))}",
        ),
        _check(
            name="topology",
            passed=components <= limits.max_components and not has_holes,
            detail=f"components={components};holes={int(has_holes)}",
        ),
        _check(
            name="protected_region",
            passed=not bool(np.any(mask & protected)),
            detail=f"protected_overlap_px={int(np.count_nonzero(mask & protected))}",
        ),
        _check(
            name="complete_map",
            passed=(
                not bool(np.any(occupied_other))
                and set(int(item) for item in np.unique(complete_map)).issubset(
                    ontology_label_ids | {0}
                )
            ),
            detail=(
                f"overwrite_other_px={int(np.count_nonzero(occupied_other))};"
                f"map_labels={sorted(int(item) for item in np.unique(complete_map))}"
            ),
        ),
    ]
    first_failure = next(
        (row["name"] for row in checks if row["status"] == "BLOCK"),
        None,
    )
    return checks, first_failure


def _default_repair(
    hypothesis: str,
    mask: np.ndarray,
    resources: Mapping[str, np.ndarray],
    target_label_id: int,
) -> np.ndarray:
    if hypothesis == "intersect_owner":
        return mask & resources["owner"]
    if hypothesis == "intersect_side":
        return mask & resources["side"]
    if hypothesis == "remove_protected":
        return mask & ~resources["protected"]
    if hypothesis == "preserve_complete_map":
        return mask & np.isin(resources["complete_map"], (0, target_label_id))
    if hypothesis == "largest_component":
        labels, count = ndimage.label(mask)
        if count <= 1:
            return mask.copy()
        areas = [int(np.count_nonzero(labels == index)) for index in range(1, count + 1)]
        return labels == (int(np.argmax(areas)) + 1)
    if hypothesis == "fill_holes":
        return ndimage.binary_fill_holes(mask)
    return mask.copy()


def _hypothesis_for(checks: Sequence[Mapping[str, str]], failure: str) -> str | None:
    if failure == "ownership":
        return "intersect_owner"
    if failure == "laterality":
        return "intersect_side"
    if failure == "protected_region":
        return "remove_protected"
    if failure == "complete_map":
        return "preserve_complete_map"
    if failure == "topology":
        detail = next(row["detail"] for row in checks if row["name"] == "topology")
        return (
            "fill_holes"
            if "holes=1" in detail and "components=1;" in detail
            else "largest_component"
        )
    return None


def evaluate_mask_candidate(
    *,
    record_id: str,
    provider_id: str,
    candidate_mask: object,
    candidate_label_id: int,
    resources: Mapping[str, object],
    target_label_id: int,
    ontology_label_ids: Sequence[int],
    limits: MaskHardQALimits,
    repairer: Callable[
        [str, np.ndarray, Mapping[str, np.ndarray], int],
        np.ndarray,
    ] = _default_repair,
) -> tuple[dict[str, Any], np.ndarray | None]:
    """Evaluate one immutable parent candidate and bounded repairs."""

    limits.validate()
    record = _identifier(record_id, field="record_id")
    provider = _identifier(provider_id, field="provider_id")
    if (
        not isinstance(target_label_id, int)
        or isinstance(target_label_id, bool)
        or target_label_id <= 0
    ):
        raise MaskHardQAError("target_label_id must be positive")
    if not isinstance(resources, Mapping) or set(resources) != {
        "owner",
        "side",
        "protected",
        "complete_map",
    }:
        raise MaskHardQAError("mask hard-QA resource field set mismatch")
    complete_map = np.asarray(resources["complete_map"])
    if complete_map.ndim != 2 or not np.issubdtype(complete_map.dtype, np.integer):
        raise MaskHardQAError("complete_map must be a two-dimensional integer array")
    shape = complete_map.shape
    normalized_resources = {
        "owner": _resource_bool(resources["owner"], name="owner", shape=shape),
        "side": _resource_bool(resources["side"], name="side", shape=shape),
        "protected": _resource_bool(
            resources["protected"],
            name="protected",
            shape=shape,
        ),
        "complete_map": complete_map.copy(),
    }
    if (
        not isinstance(candidate_label_id, int)
        or isinstance(candidate_label_id, bool)
        or candidate_label_id <= 0
    ):
        raise MaskHardQAError("candidate_label_id must be positive")
    if (
        not isinstance(ontology_label_ids, Sequence)
        or isinstance(ontology_label_ids, (str, bytes))
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in ontology_label_ids
        )
    ):
        raise MaskHardQAError("ontology_label_ids must be positive integers")
    ontology = frozenset(ontology_label_ids)
    if (
        not ontology
        or any(value <= 0 for value in ontology)
        or len(ontology) != len(tuple(ontology_label_ids))
    ):
        raise MaskHardQAError("ontology_label_ids must be positive and unique")
    try:
        parent_array = np.asarray(candidate_mask)
    except (TypeError, ValueError) as exc:
        raise MaskHardQAError("candidate mask cannot be represented as an array") from exc
    parent_sha256 = _array_sha256(parent_array)
    parent_snapshot = parent_array.copy()
    normalized, format_detail = _candidate_bool(candidate_mask, shape=shape)
    if normalized is None:
        checks = [
            _check(
                name=name,
                passed=False,
                detail=(
                    format_detail if name == "format" else "blocked by candidate format failure"
                ),
            )
            for name in CHECK_NAMES
        ]
        result = _seal(
            {
                "schema_version": SCHEMA_VERSION,
                "record_id": record,
                "provider_id": provider,
                "parent_sha256": parent_sha256,
                "final_mask_sha256": None,
                "outcome": "VETO",
                "initial_checks": checks,
                "final_checks": checks,
                "repairs": [],
                "parent_preserved": np.array_equal(parent_array, parent_snapshot),
                "result_sha256": ZERO_SHA256,
            },
            "result_sha256",
        )
        return result, None

    current = normalized
    initial_checks, failure = _hard_qa(
        mask=current,
        candidate_label_id=candidate_label_id,
        target_label_id=target_label_id,
        owner=normalized_resources["owner"],
        side=normalized_resources["side"],
        protected=normalized_resources["protected"],
        complete_map=normalized_resources["complete_map"],
        ontology_label_ids=ontology,
        limits=limits,
    )
    final_checks = initial_checks
    repairs: list[dict[str, Any]] = []
    seen_masks = {_array_sha256(current)}
    used_hypotheses: set[str] = set()
    outcome = "PASS" if failure is None else "VETO"
    for attempt in range(1, limits.max_repair_attempts + 1):
        if failure is None:
            break
        hypothesis = _hypothesis_for(final_checks, failure)
        if hypothesis is None:
            outcome = "VETO"
            break
        if hypothesis in used_hypotheses:
            outcome = "NO_PROGRESS"
            break
        used_hypotheses.add(hypothesis)
        before_sha256 = _array_sha256(current)
        try:
            repaired = np.asarray(
                repairer(
                    hypothesis,
                    current.copy(),
                    {key: value.copy() for key, value in normalized_resources.items()},
                    target_label_id,
                )
            )
        except Exception as exc:
            raise MaskHardQAError("repair callback failed closed") from exc
        repaired_normalized, repair_format = _candidate_bool(repaired, shape=shape)
        if repaired_normalized is None:
            repairs.append(
                {
                    "attempt": attempt,
                    "hypothesis": hypothesis,
                    "before_sha256": before_sha256,
                    "after_sha256": _array_sha256(repaired),
                    "status": "VETO",
                    "detail": repair_format,
                }
            )
            outcome = "VETO"
            break
        after_sha256 = _array_sha256(repaired_normalized)
        repairs.append(
            {
                "attempt": attempt,
                "hypothesis": hypothesis,
                "before_sha256": before_sha256,
                "after_sha256": after_sha256,
                "status": "APPLIED",
                "detail": "bounded deterministic repair applied",
            }
        )
        if after_sha256 in seen_masks:
            outcome = "NO_PROGRESS"
            break
        seen_masks.add(after_sha256)
        current = repaired_normalized
        final_checks, failure = _hard_qa(
            mask=current,
            candidate_label_id=candidate_label_id,
            target_label_id=target_label_id,
            owner=normalized_resources["owner"],
            side=normalized_resources["side"],
            protected=normalized_resources["protected"],
            complete_map=normalized_resources["complete_map"],
            ontology_label_ids=ontology,
            limits=limits,
        )
        outcome = "PASS_AFTER_REPAIR" if failure is None else "REPAIR_EXHAUSTED"
    parent_preserved = np.array_equal(parent_array, parent_snapshot)
    if not parent_preserved:
        outcome = "VETO"
    result = _seal(
        {
            "schema_version": SCHEMA_VERSION,
            "record_id": record,
            "provider_id": provider,
            "parent_sha256": parent_sha256,
            "final_mask_sha256": _array_sha256(current),
            "outcome": outcome,
            "initial_checks": initial_checks,
            "final_checks": final_checks,
            "repairs": repairs,
            "parent_preserved": parent_preserved,
            "result_sha256": ZERO_SHA256,
        },
        "result_sha256",
    )
    return result, current.copy() if outcome in {"PASS", "PASS_AFTER_REPAIR"} else None


def evaluate_mask_record(
    *,
    record_id: str,
    candidates: Sequence[Mapping[str, Any]],
    resources: Mapping[str, object],
    target_label_id: int,
    ontology_label_ids: Sequence[int],
    limits: MaskHardQALimits,
) -> dict[str, Any]:
    """Evaluate independent provider candidates and their final disagreement."""

    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise MaskHardQAError("candidates must be a sequence")
    provider_ids: set[str] = set()
    results: list[dict[str, Any]] = []
    passed_masks: list[tuple[str, np.ndarray]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping) or set(candidate) != {
            "provider_id",
            "label_id",
            "mask",
        }:
            raise MaskHardQAError("candidate field set mismatch")
        provider_id = _identifier(candidate["provider_id"], field="provider_id")
        if provider_id in provider_ids:
            raise MaskHardQAError("candidate provider IDs must be unique")
        provider_ids.add(provider_id)
        result, final_mask = evaluate_mask_candidate(
            record_id=record_id,
            provider_id=provider_id,
            candidate_mask=candidate["mask"],
            candidate_label_id=candidate["label_id"],
            resources=resources,
            target_label_id=target_label_id,
            ontology_label_ids=ontology_label_ids,
            limits=limits,
        )
        results.append(result)
        if final_mask is not None:
            passed_masks.append((provider_id, final_mask))
    disagreements: list[dict[str, Any]] = []
    for left_index, (left_id, left_mask) in enumerate(passed_masks):
        for right_id, right_mask in passed_masks[left_index + 1 :]:
            union = int(np.count_nonzero(left_mask | right_mask))
            iou = float(np.count_nonzero(left_mask & right_mask) / max(1, union))
            disagreements.append(
                {
                    "left_provider_id": left_id,
                    "right_provider_id": right_id,
                    "iou": iou,
                    "status": ("PASS" if iou >= limits.disagreement_iou_floor else "DISAGREE"),
                }
            )
    has_disagreement = any(row["status"] == "DISAGREE" for row in disagreements)
    record_outcome = "ABSTAIN" if has_disagreement else "PASS" if passed_masks else "VETO"
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "record_id": _identifier(record_id, field="record_id"),
        "candidate_results": results,
        "disagreement": disagreements,
        "passed_candidate_count": len(passed_masks),
        "record_outcome": record_outcome,
        "record_sha256": ZERO_SHA256,
    }
    if has_disagreement:
        # Independent masks below the IoU floor are neither a provider pass nor
        # a repairable winner.  Preserve both candidate evidence and abstain so
        # a later promotion path cannot reinterpret this record as hard-QA PASS.
        record["reason"] = "provider_disagreement"
    return _seal(
        record,
        "record_sha256",
    )


def evaluate_mask_campaign(
    records: Sequence[Mapping[str, Any]],
    *,
    limits: MaskHardQALimits,
) -> dict[str, Any]:
    """Continue unrelated records after one typed per-record failure."""

    limits.validate()
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise MaskHardQAError("records must be a sequence")
    outputs: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        try:
            if not isinstance(record, Mapping) or set(record) != {
                "record_id",
                "candidates",
                "resources",
                "target_label_id",
                "ontology_label_ids",
            }:
                raise MaskHardQAError("record field set mismatch")
            output = evaluate_mask_record(
                record_id=record["record_id"],
                candidates=record["candidates"],
                resources=record["resources"],
                target_label_id=record["target_label_id"],
                ontology_label_ids=record["ontology_label_ids"],
                limits=limits,
            )
        except MaskHardQAError as exc:
            record_id = (
                record.get("record_id") if isinstance(record, Mapping) else f"record-index-{index}"
            )
            try:
                safe_record_id = _identifier(record_id, field="record_id")
            except MaskHardQAError:
                safe_record_id = f"record-index-{index}"
            output = _seal(
                {
                    "schema_version": SCHEMA_VERSION,
                    "record_id": safe_record_id,
                    "candidate_results": [],
                    "disagreement": [],
                    "passed_candidate_count": 0,
                    "record_outcome": "ABSTAIN",
                    "reason": f"{type(exc).__name__}: record failed closed",
                    "record_sha256": ZERO_SHA256,
                },
                "record_sha256",
            )
        outputs.append(output)
    return _seal(
        {
            "schema_version": SCHEMA_VERSION,
            "records": outputs,
            "record_count": len(outputs),
            "passed_record_count": sum(row["record_outcome"] == "PASS" for row in outputs),
            "campaign_sha256": ZERO_SHA256,
        },
        "campaign_sha256",
    )


def validate_mask_campaign(
    campaign: Mapping[str, Any],
    *,
    records: Sequence[Mapping[str, Any]],
    limits: MaskHardQALimits,
) -> dict[str, Any]:
    """Recompute the whole campaign and reject rehashed outcome drift."""

    if not isinstance(campaign, Mapping):
        raise MaskHardQAError("campaign evidence must be an object")
    _verify_self_hash(campaign, "campaign_sha256")
    campaign_records = campaign.get("records")
    if not isinstance(campaign_records, list):
        raise MaskHardQAError("campaign records must be a list")
    for record in campaign_records:
        if not isinstance(record, Mapping):
            raise MaskHardQAError("campaign record evidence must be an object")
        _verify_self_hash(record, "record_sha256")
        candidate_results = record.get("candidate_results")
        if not isinstance(candidate_results, list):
            raise MaskHardQAError("candidate results must be a list")
        for result in candidate_results:
            if not isinstance(result, Mapping):
                raise MaskHardQAError("candidate result evidence must be an object")
            _verify_self_hash(result, "result_sha256")
    expected = evaluate_mask_campaign(records, limits=limits)
    if dict(campaign) != expected:
        raise MaskHardQAError("campaign evidence differs from deterministic hard-QA replay")
    return expected


__all__ = [
    "CHECK_NAMES",
    "MaskHardQAError",
    "MaskHardQALimits",
    "SCHEMA_VERSION",
    "evaluate_mask_campaign",
    "evaluate_mask_candidate",
    "evaluate_mask_record",
    "validate_mask_campaign",
]
