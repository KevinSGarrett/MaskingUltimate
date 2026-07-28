"""Inactive body-parts-v2 dataset, holdout, metric, and promotion contracts."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from ...ontology import load_ontology
from ...ontology_v2 import DEFAULT_ONTOLOGY_V2
from ...ontology_v2_manifest import require_v2_supervision_eligible
from ...qa.metrics import boundary_f
from ..augmentations import IGNORE_INDEX, burn_ambiguous_to_ignore, validate_augmentation_config

V2_ONTOLOGY_VERSION = "body_parts_v2"
V1_ONTOLOGY_VERSION = "body_parts_v1"
V2_CLASS_NAMES = tuple(
    label.name
    for label in sorted(
        load_ontology(DEFAULT_ONTOLOGY_V2).labels_for_map("part"),
        key=lambda item: int(item.id),
    )
)
V2_NEW_CLASS_NAMES = V2_CLASS_NAMES[56:]
V2_NEW_CLASS_IDS = tuple(range(56, 65))
V2_NAME_TO_ID = {name: class_id for class_id, name in enumerate(V2_CLASS_NAMES)}
V2_SIDE_PARTNERS = {
    "left_areola": "right_areola",
    "right_areola": "left_areola",
    "left_nipple": "right_nipple",
    "right_nipple": "left_nipple",
    "left_scrotal_region": "right_scrotal_region",
    "right_scrotal_region": "left_scrotal_region",
}
HOLDOUT_COHORTS = frozenset({"train", "val", "positive_holdout", "clothed_negative_holdout"})


class V2TrainingContractError(ValueError):
    """Inactive v2 training evidence is incomplete or semantically unsafe."""


@dataclass(frozen=True)
class V2HoldoutRecord:
    sample_id: str
    identity_key: str
    phash64: str
    cohort: str
    positive_labels: tuple[str, ...] = ()
    clothed_negative: bool = False
    fully_reviewed_v2: bool = True


@dataclass(frozen=True)
class V2EvaluationSample:
    sample_id: str
    identity_key: str
    cohort: str
    prediction: np.ndarray
    target: np.ndarray


def supervision_contract(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Separate v1 pretraining from fully reviewed v2 fine-tune authority."""
    version = manifest.get("mask_ontology_version")
    if version == V1_ONTOLOGY_VERSION:
        return {
            "ontology_version": V1_ONTOLOGY_VERSION,
            "mode": "v1_pretraining_only",
            "head_num_classes": 56,
            "supervised_ids": list(range(56)),
            "v2_finetune_eligible": False,
            "new_label_negative_ids": [],
            "reason": "v1 absence provides no negative evidence for IDs 56-64",
        }
    if version != V2_ONTOLOGY_VERSION:
        raise V2TrainingContractError(f"unsupported supervision ontology: {version!r}")
    require_v2_supervision_eligible(manifest)
    return {
        "ontology_version": V2_ONTOLOGY_VERSION,
        "mode": "v2_finetune",
        "head_num_classes": 65,
        "supervised_ids": list(range(65)),
        "v2_finetune_eligible": True,
        "new_label_negative_ids": list(V2_NEW_CLASS_IDS),
        "reason": "all 65 labels carry body_parts_v2 human review authority",
    }


def prepare_v2_training_map(
    label_map: np.ndarray, ambiguity_mask: np.ndarray | None = None
) -> np.ndarray:
    """Preserve exact IDs 0..64 and burn only explicit ambiguity to ignore 255."""
    labels = np.asarray(label_map)
    if labels.ndim != 2 or not np.issubdtype(labels.dtype, np.integer):
        raise V2TrainingContractError("v2 training map must be an indexed 2-D integer array")
    valid = labels != IGNORE_INDEX
    invalid = np.unique(labels[valid][(labels[valid] < 0) | (labels[valid] >= 65)])
    if invalid.size:
        raise V2TrainingContractError(f"v2 training map has out-of-range IDs: {invalid.tolist()}")
    if ambiguity_mask is None:
        result = labels.astype(np.uint8, copy=True)
    else:
        result = burn_ambiguous_to_ignore(labels, ambiguity_mask)
    remaining = result != IGNORE_INDEX
    if not np.array_equal(result[remaining], labels[remaining].astype(np.uint8)):
        raise V2TrainingContractError("v2 export remapped a canonical class ID")
    return result


def validate_v2_training_config(config: Mapping[str, Any]) -> None:
    """Validate a separate inactive 65-class training config without touching v1."""
    if config.get("activation_status") != "approved_design_not_active":
        raise V2TrainingContractError("v2 training config must remain inactive before activation")
    if config.get("ontology_version") != V2_ONTOLOGY_VERSION:
        raise V2TrainingContractError("v2 training config ontology_version is not body_parts_v2")
    model = _mapping(config.get("model"), "model")
    if model.get("num_classes") != 65:
        raise V2TrainingContractError("v2 training config requires exactly 65 classes, never 57")
    if tuple(model.get("classes", ())) != V2_CLASS_NAMES:
        raise V2TrainingContractError("v2 training config class vocabulary is not exact IDs 0..64")
    data = _mapping(config.get("data"), "data")
    if data.get("ignore_index") != IGNORE_INDEX:
        raise V2TrainingContractError("v2 training config requires ignore_index 255")
    sampler = _mapping(data.get("sampler"), "data.sampler")
    if tuple(sampler.get("anatomy_ids", ())) != V2_NEW_CLASS_IDS:
        raise V2TrainingContractError("v2 sampler must target exact anatomy IDs 56..64")
    if float(sampler.get("anatomy_crop_min_fraction", -1)) < 0.5:
        raise V2TrainingContractError("v2 sampler requires at least 50% anatomy-positive crops")
    whole_fraction = float(sampler.get("whole_body_min_fraction", -1))
    if not 0 < whole_fraction <= 0.5:
        raise V2TrainingContractError("v2 sampler must retain a bounded whole-body fraction")
    if sampler.get("fabricate_hidden_positive") is not False:
        raise V2TrainingContractError("v2 sampler must forbid fabricated hidden positives")
    training = _mapping(config.get("training"), "training")
    weights = _mapping(training.get("class_weights"), "training.class_weights")
    if weights != {"formula": "inverse_sqrt_pixel_frequency", "cap_multiplier": 8.0}:
        raise V2TrainingContractError("v2 class weights must be inverse-sqrt and capped at x8")
    required_metrics = {
        "per_class_iou",
        "boundary_f_2px",
        "positive_recall",
        "clothed_false_positive_rate",
        "left_right_swap_rate",
    }
    evaluation = _mapping(config.get("evaluation"), "evaluation")
    if set(evaluation.get("metrics", ())) != required_metrics:
        raise V2TrainingContractError("v2 evaluation metrics are incomplete")
    validate_augmentation_config(config.get("augmentations", ()))


def plan_v2_finetune_batches(
    samples: Sequence[Mapping[str, Any]],
    *,
    draws: int,
    seed: int = 1337,
    anatomy_fraction: float = 0.5,
    whole_body_fraction: float = 0.25,
) -> dict[str, Any]:
    """Plan deterministic anatomy-focused and anti-forgetting draws from reviewed v2 only."""
    if draws < 1 or not 0.5 <= anatomy_fraction <= 1:
        raise V2TrainingContractError("v2 batch plan requires draws>0 and anatomy_fraction>=0.5")
    if not 0 < whole_body_fraction <= 1 - anatomy_fraction:
        raise V2TrainingContractError("whole-body fraction must fit beside anatomy-focused draws")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sample in samples:
        sample_id = sample.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id or sample_id in seen:
            raise V2TrainingContractError("v2 sampler requires unique nonempty sample IDs")
        if sample.get("fully_reviewed_v2") is not True:
            raise V2TrainingContractError(f"v2 sampler refused unreviewed sample: {sample_id}")
        present = tuple(sorted({int(value) for value in sample.get("present_new_ids", ())}))
        if any(value not in V2_NEW_CLASS_IDS for value in present):
            raise V2TrainingContractError(f"v2 sampler received non-anatomy rare ID: {sample_id}")
        normalized.append({"sample_id": sample_id, "present_new_ids": present})
        seen.add(sample_id)
    if not normalized:
        raise V2TrainingContractError("v2 sampler requires at least one fully reviewed sample")
    anatomy_pool = [sample for sample in normalized if sample["present_new_ids"]]
    rng = np.random.default_rng(seed)

    def ordered(pool: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        indexes = rng.permutation(len(pool)).tolist()
        return [pool[index] for index in indexes]

    all_ordered = ordered(normalized)
    selections: list[dict[str, Any]] = []
    if anatomy_pool:
        anatomy_count = math.ceil(draws * anatomy_fraction)
        whole_count = math.ceil(draws * whole_body_fraction)
        whole_count = min(whole_count, draws - anatomy_count)
        anatomy_ordered = ordered(anatomy_pool)
        for index in range(anatomy_count):
            sample = anatomy_ordered[index % len(anatomy_ordered)]
            selections.append({**sample, "mode": "anatomy_focused_crop"})
        for index in range(whole_count):
            sample = all_ordered[index % len(all_ordered)]
            selections.append({**sample, "mode": "whole_body_anti_forgetting"})
        for index in range(draws - len(selections)):
            sample = all_ordered[(whole_count + index) % len(all_ordered)]
            selections.append({**sample, "mode": "standard_crop"})
    else:
        for index in range(draws):
            sample = all_ordered[index % len(all_ordered)]
            selections.append({**sample, "mode": "whole_body_anti_forgetting"})
    anatomy_count = sum(item["mode"] == "anatomy_focused_crop" for item in selections)
    whole_count = sum(item["mode"] == "whole_body_anti_forgetting" for item in selections)
    return {
        "schema_version": "1.0.0",
        "ontology_version": V2_ONTOLOGY_VERSION,
        "draws": draws,
        "inventory_supports_anatomy_focus": bool(anatomy_pool),
        "anatomy_focused_fraction": anatomy_count / draws,
        "whole_body_fraction": whole_count / draws,
        "fabricated_positive_count": 0,
        "selections": selections,
    }


def build_v2_holdout_manifest(records: Sequence[V2HoldoutRecord]) -> dict[str, Any]:
    """Prove identity and near-duplicate separation for positive/clothed-negative holdouts."""
    if not records or len({record.sample_id for record in records}) != len(records):
        raise V2TrainingContractError("v2 holdout records require unique samples")
    for record in records:
        if not record.identity_key or record.cohort not in HOLDOUT_COHORTS:
            raise V2TrainingContractError(f"invalid v2 holdout record: {record.sample_id}")
        if record.fully_reviewed_v2 is not True:
            raise V2TrainingContractError(
                f"holdout sample is not fully reviewed v2: {record.sample_id}"
            )
        labels = set(record.positive_labels)
        if not labels <= set(V2_NEW_CLASS_NAMES):
            raise V2TrainingContractError(f"holdout has unknown anatomy label: {record.sample_id}")
        if record.cohort == "positive_holdout" and not labels:
            raise V2TrainingContractError(f"positive holdout lacks a positive: {record.sample_id}")
        if record.cohort == "clothed_negative_holdout" and (labels or not record.clothed_negative):
            raise V2TrainingContractError(
                f"clothed-negative holdout is not an explicit reviewed negative: {record.sample_id}"
            )
    phashes = [_parse_phash(record.phash64) for record in records]
    parent = list(range(len(records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for left, first in enumerate(records):
        for right in range(left + 1, len(records)):
            second = records[right]
            if (
                first.identity_key == second.identity_key
                or (phashes[left] ^ phashes[right]).bit_count() <= 6
            ):
                union(left, right)
    groups: dict[int, list[V2HoldoutRecord]] = {}
    for index, record in enumerate(records):
        groups.setdefault(find(index), []).append(record)
    leaked = {
        tuple(sorted(record.sample_id for record in group)): sorted(
            {record.cohort for record in group}
        )
        for group in groups.values()
        if len({record.cohort for record in group}) > 1
    }
    if leaked:
        raise V2TrainingContractError(f"identity/pHash group crosses v2 cohorts: {leaked}")
    cohorts = {
        cohort: sorted(record.sample_id for record in records if record.cohort == cohort)
        for cohort in sorted(HOLDOUT_COHORTS)
    }
    if not cohorts["positive_holdout"] or not cohorts["clothed_negative_holdout"]:
        raise V2TrainingContractError(
            "v2 evaluation requires positive and clothed-negative holdouts"
        )
    canonical = [
        {
            "sample_id": record.sample_id,
            "identity_key": record.identity_key,
            "phash64": record.phash64.lower(),
            "cohort": record.cohort,
            "positive_labels": sorted(record.positive_labels),
            "clothed_negative": record.clothed_negative,
        }
        for record in sorted(records, key=lambda item: item.sample_id)
    ]
    return {
        "schema_version": "1.0.0",
        "ontology_version": V2_ONTOLOGY_VERSION,
        "identity_phash_separation_passed": True,
        "records_sha256": hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "cohorts": cohorts,
        "records": canonical,
    }


def evaluate_v2_holdouts(
    samples: Sequence[V2EvaluationSample],
    *,
    positive_inventory: Mapping[str, int],
    holdout_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Emit every doc-18 per-class metric; aggregate mIoU alone is never authority."""
    if holdout_manifest.get("identity_phash_separation_passed") is not True:
        raise V2TrainingContractError("metric evaluation requires separated holdout authority")
    positive = [sample for sample in samples if sample.cohort == "positive_holdout"]
    negatives = [sample for sample in samples if sample.cohort == "clothed_negative_holdout"]
    if not positive or not negatives:
        raise V2TrainingContractError("metric evaluation requires both holdout cohorts")
    prepared = []
    for sample in samples:
        if sample.cohort not in {"positive_holdout", "clothed_negative_holdout"}:
            raise V2TrainingContractError(f"metric sample has invalid cohort: {sample.sample_id}")
        prediction = prepare_v2_training_map(sample.prediction)
        target = prepare_v2_training_map(sample.target)
        if prediction.shape != target.shape:
            raise V2TrainingContractError(f"metric map dimensions differ: {sample.sample_id}")
        prepared.append((sample, prediction, target))
    rows = []
    for name in V2_NEW_CLASS_NAMES:
        class_id = V2_NAME_TO_ID[name]
        intersections = unions = true_positives = false_negatives = 0
        positive_instances = 0
        boundary_values: list[float] = []
        swap_errors = swap_denominator = 0
        partner = V2_SIDE_PARTNERS.get(name)
        partner_id = V2_NAME_TO_ID[partner] if partner else None
        for sample, prediction, target in prepared:
            if sample.cohort != "positive_holdout":
                continue
            valid = target != IGNORE_INDEX
            expected = (target == class_id) & valid
            predicted = (prediction == class_id) & valid
            positive_instances += int(np.any(expected))
            intersections += int(np.count_nonzero(expected & predicted))
            unions += int(np.count_nonzero(expected | predicted))
            true_positives += int(np.count_nonzero(expected & predicted))
            false_negatives += int(np.count_nonzero(expected & ~predicted))
            if np.any(expected | predicted):
                boundary_values.append(boundary_f(predicted, expected, tolerance_px=2))
            if partner_id is not None:
                swap_errors += int(np.count_nonzero(expected & (prediction == partner_id)))
                swap_denominator += int(np.count_nonzero(expected))
        negative_images = negative_fp_images = negative_pixels = negative_fp_pixels = 0
        for sample, prediction, target in prepared:
            if sample.cohort != "clothed_negative_holdout":
                continue
            valid = target != IGNORE_INDEX
            predicted = (prediction == class_id) & valid
            negative_images += 1
            negative_fp_images += int(np.any(predicted))
            negative_pixels += int(np.count_nonzero(valid))
            negative_fp_pixels += int(np.count_nonzero(predicted))
        denominator = true_positives + false_negatives
        rows.append(
            {
                "class_id": class_id,
                "class_name": name,
                "clear_positive_inventory": int(positive_inventory.get(name, 0)),
                "positive_holdout_instances": positive_instances,
                "iou": intersections / unions if unions else None,
                "boundary_f_2px": float(np.mean(boundary_values)) if boundary_values else None,
                "positive_recall": true_positives / denominator if denominator else None,
                "clothed_negative_images": negative_images,
                "clothed_false_positive_images": negative_fp_images,
                "clothed_false_positive_image_rate": negative_fp_images / negative_images,
                "clothed_false_positive_pixel_rate": (
                    negative_fp_pixels / negative_pixels if negative_pixels else None
                ),
                "left_right_swap_rate": (
                    swap_errors / swap_denominator
                    if partner_id is not None and swap_denominator
                    else None
                ),
                "systematic_clothed_false_positive": negative_fp_images > 0,
            }
        )
    return {
        "schema_version": "1.0.0",
        "ontology_version": V2_ONTOLOGY_VERSION,
        "metric_authority": "identity_separated_positive_and_clothed_negative_holdouts",
        "holdout_records_sha256": holdout_manifest.get("records_sha256"),
        "aggregate_only_is_sufficient": False,
        "zero_tolerance_clothing_gate_until_calibrated": True,
        "classes": rows,
    }


def evaluate_v2_promotion_gate(report: Mapping[str, Any]) -> dict[str, Any]:
    """Refuse v2 promotion on missing per-class evidence, low inventory, or clothing fire."""
    if report.get("ontology_version") != V2_ONTOLOGY_VERSION:
        raise V2TrainingContractError("promotion report is not body_parts_v2")
    if report.get("metric_authority") != (
        "identity_separated_positive_and_clothed_negative_holdouts"
    ):
        raise V2TrainingContractError("promotion report lacks holdout metric authority")
    rows = report.get("classes")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise V2TrainingContractError("promotion report classes are missing")
    by_name = {row.get("class_name"): row for row in rows if isinstance(row, Mapping)}
    if set(by_name) != set(V2_NEW_CLASS_NAMES) or len(rows) != len(V2_NEW_CLASS_NAMES):
        raise V2TrainingContractError("promotion report must contain each new class exactly once")
    checks: dict[str, dict[str, Any]] = {}
    for name in V2_NEW_CLASS_NAMES:
        row = by_name[name]
        measured = all(
            _unit_or_none(row.get(metric)) is not None
            for metric in (
                "iou",
                "boundary_f_2px",
                "positive_recall",
                "clothed_false_positive_image_rate",
                "clothed_false_positive_pixel_rate",
            )
        )
        if name in V2_SIDE_PARTNERS:
            measured = measured and _unit_or_none(row.get("left_right_swap_rate")) is not None
        inventory = _nonnegative_int(row.get("clear_positive_inventory"), f"{name} inventory")
        positive_holdout = _nonnegative_int(
            row.get("positive_holdout_instances"), f"{name} positive holdout"
        )
        clothed_holdout = _nonnegative_int(
            row.get("clothed_negative_images"), f"{name} clothed holdout"
        )
        clothing_clear = (
            row.get("systematic_clothed_false_positive") is False
            and _nonnegative_int(
                row.get("clothed_false_positive_images"), f"{name} clothing false positives"
            )
            == 0
        )
        checks[name] = {
            "clear_positive_inventory_at_least_50": inventory >= 50,
            "measured_positive_holdout": positive_holdout > 0 and measured,
            "measured_clothed_negative_holdout": clothed_holdout > 0,
            "no_systematic_clothed_false_positive": clothing_clear,
            "passed": inventory >= 50
            and positive_holdout > 0
            and clothed_holdout > 0
            and measured
            and clothing_clear,
        }
    return {
        "schema_version": "1.0.0",
        "ontology_version": V2_ONTOLOGY_VERSION,
        "checks": checks,
        "passed": all(check["passed"] for check in checks.values()),
    }


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise V2TrainingContractError(f"v2 training config lacks {name}")
    return value


def _parse_phash(value: str) -> int:
    try:
        parsed = int(value, 16)
    except (TypeError, ValueError) as exc:
        raise V2TrainingContractError(f"invalid 64-bit pHash: {value!r}") from exc
    if not 0 <= parsed < 2**64:
        raise V2TrainingContractError(f"invalid 64-bit pHash: {value!r}")
    return parsed


def _unit_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) and 0 <= numeric <= 1 else None


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise V2TrainingContractError(f"{name} must be a nonnegative integer")
    return value
