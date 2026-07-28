"""Deterministic stratified, pairwise, low-discrepancy DAZ candidate generation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping

import yaml

from ...validation import require_valid_document
from .deficits import validate_real_deficit_signal_report
from .vocabulary import validate_coverage_vocabulary_report

SHA256 = re.compile(r"^[0-9a-f]{64}$")
TOKEN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
EXPECTED_POLICY_SHA256 = "8cef5db1e8f43d8ba1ceea47b0898c80494c030e8409d703a3dcaea7c42f308d"


class CandidateGenerationError(ValueError):
    """Candidate policy, inputs, generated batch, or publication is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_candidate_generation_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_candidate_generation_policy(document)
    return document


def validate_candidate_generation_policy(policy: Mapping[str, Any]) -> None:
    if not isinstance(policy, Mapping) or set(policy) != {
        "schema_version",
        "generator_version",
        "candidate_count",
        "discrete_sampling",
        "continuous_sampling",
        "registry_sampling",
        "rejections",
        "authority",
        "publication",
    }:
        raise CandidateGenerationError("candidate_policy_fields_invalid", str(policy))
    if policy["schema_version"] != "1.0.0" or policy["generator_version"] != "1.0.0":
        raise CandidateGenerationError("candidate_policy_identity_invalid", str(policy))
    if policy["candidate_count"] != {"minimum": 10, "default": 32, "maximum": 100}:
        raise CandidateGenerationError("candidate_policy_count_invalid", str(policy))
    if policy["discrete_sampling"] != {
        "method": "deterministic_greedy_stratified_pairwise",
        "pairwise_scope": "declared_high_risk_intersections",
        "balance_max_count_spread": 1,
        "locked_demand_axes_preserved": True,
    }:
        raise CandidateGenerationError("candidate_policy_discrete_invalid", str(policy))
    if policy["continuous_sampling"] != {
        "method": "seeded_halton",
        "bases": [2, 3, 5, 7, 11, 13],
        "bounds_from_vocabulary": True,
        "finite_required": True,
    }:
        raise CandidateGenerationError("candidate_policy_continuous_invalid", str(policy))
    if policy["registry_sampling"] != {
        "method": "deterministic_weighted_reservoir_without_replacement_under_caps",
        "versioned_snapshot_required": True,
        "positive_finite_weight_required": True,
        "positive_integer_cap_required": True,
        "unresolved_pool_rejects_candidate": True,
    }:
        raise CandidateGenerationError("candidate_policy_registry_invalid", str(policy))
    if policy["rejections"] != {
        "recorded_per_candidate": True,
        "allowed_reasons": [
            "registry_pool_missing",
            "registry_pool_exhausted",
            "locked_axis_invalid",
        ],
    }:
        raise CandidateGenerationError("candidate_policy_rejections_invalid", str(policy))
    if policy["authority"] != {
        "stage": "unscored_unselected_candidate",
        "candidates_are_recipes": False,
        "candidates_are_feasible_scenes": False,
        "candidates_create_gold": False,
        "synthetic_counts_close_real_deficits": False,
    } or policy["publication"] != {"immutable": True, "atomic": True}:
        raise CandidateGenerationError("candidate_policy_authority_invalid", str(policy))


def build_candidate_batch(
    *,
    vocabulary_report: Mapping[str, Any],
    demand_report: Mapping[str, Any],
    demand_id: str,
    policy: Mapping[str, Any],
    master_seed: int,
    candidate_count: int | None = None,
    registry_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    validate_candidate_generation_policy(policy)
    validate_coverage_vocabulary_report(vocabulary_report)
    validate_real_deficit_signal_report(demand_report)
    count = candidate_count or policy["candidate_count"]["default"]
    if (
        not 10 <= count <= 100
        or not isinstance(master_seed, int)
        or not 0 <= master_seed <= 2**31 - 1
    ):
        raise CandidateGenerationError("candidate_request_invalid", f"{count}:{master_seed}")
    demand = next((row for row in demand_report["demands"] if row["demand_id"] == demand_id), None)
    if demand is None or demand["actionability"] != "eligible":
        raise CandidateGenerationError("candidate_demand_ineligible", demand_id)
    axes = {row["axis_id"]: row["values"] for row in vocabulary_report["axes"]}
    axis_order = list(axes)
    locked = {row["axis_id"]: row["value"] for row in demand["closed_axis_projection"]}
    if any(axis not in axes or value not in axes[axis] for axis, value in locked.items()):
        raise CandidateGenerationError("candidate_locked_axis_invalid", str(locked))
    pair_axes = _pair_axes(vocabulary_report["high_risk_intersections"])
    usage: dict[str, Counter[Any]] = {axis: Counter() for axis in axis_order}
    seen_pairs: set[tuple[str, Any, str, Any]] = set()
    registry, registry_meta = _validate_registry(registry_snapshot, vocabulary_report)
    registry_usage: dict[str, Counter[str]] = defaultdict(Counter)
    candidates = []
    for index in range(count):
        chosen: dict[str, Any] = {}
        for axis in axis_order:
            if axis in locked:
                value = locked[axis]
            else:
                values = axes[axis]
                value = min(
                    values,
                    key=lambda item: (
                        usage[axis][item],
                        -_pair_gain(axis, item, chosen, pair_axes, seen_pairs),
                        _tie(master_seed, index, axis, item),
                    ),
                )
            chosen[axis] = value
            usage[axis][value] += 1
        for left, right in pair_axes:
            seen_pairs.add((left, chosen[left], right, chosen[right]))
        continuous = _continuous(index, master_seed, vocabulary_report, policy)
        registry_values, rejections = _registry_values(
            index, master_seed, registry, registry_usage, vocabulary_report
        )
        content = {
            "candidate_index": index,
            "discrete": [{"axis_id": axis, "value": chosen[axis]} for axis in axis_order],
            "continuous": continuous,
            "registry": registry_values,
            "rejections": rejections,
            "registry_complete": not rejections,
            "scored": False,
            "selected": False,
        }
        candidates.append({"candidate_id": f"dc_{_sha(content)[:24]}", **content})
    possible_pairs = sum(len(axes[left]) * len(axes[right]) for left, right in pair_axes)
    unlocked_spreads = [
        max(usage[axis][value] for value in axes[axis])
        - min(usage[axis][value] for value in axes[axis])
        for axis in axis_order
        if axis not in locked
    ]
    distribution = {
        "discrete_method": policy["discrete_sampling"]["method"],
        "continuous_method": policy["continuous_sampling"]["method"],
        "registry_method": policy["registry_sampling"]["method"],
        "maximum_unlocked_axis_count_spread": max(unlocked_spreads, default=0),
        "selected_pair_count": possible_pairs,
        "covered_selected_pair_count": len(seen_pairs),
        "selected_pair_coverage_ratio": len(seen_pairs) / possible_pairs if possible_pairs else 0.0,
        "continuous_axis_count": len(vocabulary_report["continuous_axes"]),
        "continuous_points_in_bounds": True,
    }
    reasons = Counter(row["reason"] for item in candidates for row in item["rejections"])
    summary = {
        "candidate_count": count,
        "registry_complete_candidate_count": sum(item["registry_complete"] for item in candidates),
        "rejected_candidate_count": sum(not item["registry_complete"] for item in candidates),
        "rejection_reason_counts": dict(sorted(reasons.items())),
        "scored_candidate_count": 0,
        "selected_candidate_count": 0,
    }
    content = {
        "generator_version": policy["generator_version"],
        "policy_sha256": _sha(policy),
        "vocabulary": {
            key: vocabulary_report[key]
            for key in ("report_id", "report_sha256", "vocabulary_version")
        },
        "demand": {
            "demand_id": demand_id,
            "demand_report_id": demand_report["report_id"],
            "demand_report_sha256": demand_report["report_sha256"],
            "actionability": "eligible",
            "locked_axes": [
                {"axis_id": axis, "value": locked[axis]} for axis in axis_order if axis in locked
            ],
        },
        "registry_snapshot": registry_meta,
        "master_seed": master_seed,
        "requested_candidate_count": count,
        "candidates": candidates,
        "distribution": distribution,
        "summary": summary,
        "authority": dict(policy["authority"]),
        "publication": dict(policy["publication"]),
    }
    digest = _sha(content)
    report = {
        "schema_version": "1.0.0",
        "batch_id": f"dcb_{digest[:24]}",
        "batch_sha256": digest,
        **content,
    }
    validate_candidate_batch(report, vocabulary_report=vocabulary_report)
    return report


def validate_candidate_batch(
    report: Mapping[str, Any], *, vocabulary_report: Mapping[str, Any]
) -> None:
    require_valid_document(report, "daz_candidate_batch_report")
    validate_coverage_vocabulary_report(vocabulary_report)
    _verify(report)
    if report["policy_sha256"] != EXPECTED_POLICY_SHA256:
        raise CandidateGenerationError("candidate_policy_hash_invalid", report["batch_id"])
    if report["vocabulary"] != {
        key: vocabulary_report[key] for key in ("report_id", "report_sha256", "vocabulary_version")
    }:
        raise CandidateGenerationError("candidate_vocabulary_binding_invalid", report["batch_id"])
    axis_order = [row["axis_id"] for row in vocabulary_report["axes"]]
    axis_values = {row["axis_id"]: row["values"] for row in vocabulary_report["axes"]}
    registry_patterns = {
        row["axis_id"]: re.compile(row["value_pattern"])
        for row in vocabulary_report["registry_axes"]
    }
    registry_order = list(registry_patterns)
    bounds = {
        row["axis_id"]: (row["minimum"], row["maximum"])
        for row in vocabulary_report["continuous_axes"]
    }
    locked = {row["axis_id"]: row["value"] for row in report["demand"]["locked_axes"]}
    registry_meta = report["registry_snapshot"]
    if (
        (registry_meta["snapshot_id"] is None) != (registry_meta["snapshot_sha256"] is None)
        or (registry_meta["snapshot_id"] is None) != (registry_meta["provided_axis_count"] == 0)
        or registry_meta["required_axis_count"] != len(registry_order)
        or registry_meta["complete"]
        != (registry_meta["provided_axis_count"] == len(registry_order))
    ):
        raise CandidateGenerationError("candidate_registry_metadata_invalid", report["batch_id"])
    usage: dict[str, Counter[Any]] = {axis: Counter() for axis in axis_order}
    seen_pairs: set[tuple[str, Any, str, Any]] = set()
    pair_axes = _pair_axes(vocabulary_report["high_risk_intersections"])
    for index, candidate in enumerate(report["candidates"]):
        content = {key: value for key, value in candidate.items() if key != "candidate_id"}
        if (
            candidate["candidate_id"] != f"dc_{_sha(content)[:24]}"
            or candidate["candidate_index"] != index
        ):
            raise CandidateGenerationError(
                "candidate_hash_or_index_invalid", candidate["candidate_id"]
            )
        discrete = {row["axis_id"]: row["value"] for row in candidate["discrete"]}
        continuous = {row["axis_id"]: row["value"] for row in candidate["continuous"]}
        if (
            list(discrete) != axis_order
            or any(discrete.get(axis) != value for axis, value in locked.items())
            or any(value not in axis_values[axis] for axis, value in discrete.items())
        ):
            raise CandidateGenerationError(
                "candidate_discrete_semantics_invalid", candidate["candidate_id"]
            )
        for axis, value in discrete.items():
            usage[axis][value] += 1
        for left, right in pair_axes:
            seen_pairs.add((left, discrete[left], right, discrete[right]))
        if list(continuous) != list(bounds) or any(
            not math.isfinite(value) or not bounds[axis][0] <= value <= bounds[axis][1]
            for axis, value in continuous.items()
        ):
            raise CandidateGenerationError(
                "candidate_continuous_semantics_invalid", candidate["candidate_id"]
            )
        if candidate["registry_complete"] != (not candidate["rejections"]):
            raise CandidateGenerationError(
                "candidate_registry_semantics_invalid", candidate["candidate_id"]
            )
        registry = {row["axis_id"]: row["value"] for row in candidate["registry"]}
        rejected = {row["axis_id"]: row["reason"] for row in candidate["rejections"]}
        if (
            len(registry) != len(candidate["registry"])
            or len(rejected) != len(candidate["rejections"])
            or not set(registry).isdisjoint(rejected)
            or set(registry) | set(rejected) != set(registry_order)
            or [axis for axis in registry_order if axis in registry] != list(registry)
            or [axis for axis in registry_order if axis in rejected] != list(rejected)
            or any(
                not registry_patterns[axis].fullmatch(str(value))
                for axis, value in registry.items()
            )
        ):
            raise CandidateGenerationError(
                "candidate_registry_partition_invalid", candidate["candidate_id"]
            )
    reasons = Counter(row["reason"] for item in report["candidates"] for row in item["rejections"])
    possible_pairs = sum(
        len(axis_values[left]) * len(axis_values[right]) for left, right in pair_axes
    )
    spreads = [
        max(usage[axis][value] for value in axis_values[axis])
        - min(usage[axis][value] for value in axis_values[axis])
        for axis in axis_order
        if axis not in locked
    ]
    expected_distribution = {
        "discrete_method": "deterministic_greedy_stratified_pairwise",
        "continuous_method": "seeded_halton",
        "registry_method": "deterministic_weighted_reservoir_without_replacement_under_caps",
        "maximum_unlocked_axis_count_spread": max(spreads, default=0),
        "selected_pair_count": possible_pairs,
        "covered_selected_pair_count": len(seen_pairs),
        "selected_pair_coverage_ratio": len(seen_pairs) / possible_pairs if possible_pairs else 0.0,
        "continuous_axis_count": len(bounds),
        "continuous_points_in_bounds": True,
    }
    expected_summary = {
        "candidate_count": len(report["candidates"]),
        "registry_complete_candidate_count": sum(
            item["registry_complete"] for item in report["candidates"]
        ),
        "rejected_candidate_count": sum(
            not item["registry_complete"] for item in report["candidates"]
        ),
        "rejection_reason_counts": dict(sorted(reasons.items())),
        "scored_candidate_count": 0,
        "selected_candidate_count": 0,
    }
    if report["distribution"] != expected_distribution or report["summary"] != expected_summary:
        raise CandidateGenerationError("candidate_summary_invalid", report["batch_id"])


def publish_candidate_batch(
    report: Mapping[str, Any], output_root: Path, *, vocabulary_report: Mapping[str, Any]
) -> tuple[Path, bool]:
    validate_candidate_batch(report, vocabulary_report=vocabulary_report)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{report['batch_id']}.json"
    payload = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise CandidateGenerationError("candidate_publication_conflict", str(target))
        return target, False
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=root
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target, True


def _pair_axes(intersections: list[Mapping[str, Any]]) -> list[tuple[str, str]]:
    pairs = {tuple(sorted(pair)) for row in intersections for pair in combinations(row["axes"], 2)}
    return sorted(pairs)


def _pair_gain(
    axis: str,
    value: Any,
    chosen: Mapping[str, Any],
    pairs: list[tuple[str, str]],
    seen: set[tuple[str, Any, str, Any]],
) -> int:
    gain = 0
    for left, right in pairs:
        if axis == right and left in chosen:
            gain += (left, chosen[left], right, value) not in seen
        elif axis == left and right in chosen:
            gain += (left, value, right, chosen[right]) not in seen
    return gain


def _continuous(
    index: int, seed: int, vocabulary: Mapping[str, Any], policy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    start = 1 + seed % 104729
    rows = []
    for axis, base in zip(
        vocabulary["continuous_axes"], policy["continuous_sampling"]["bases"], strict=True
    ):
        unit = _radical_inverse(start + index, base)
        value = axis["minimum"] + unit * (axis["maximum"] - axis["minimum"])
        rows.append({"axis_id": axis["axis_id"], "value": value})
    return rows


def _radical_inverse(number: int, base: int) -> float:
    value = 0.0
    factor = 1.0 / base
    while number:
        number, digit = divmod(number, base)
        value += digit * factor
        factor /= base
    return value


def _validate_registry(
    snapshot: Mapping[str, Any] | None, vocabulary: Mapping[str, Any]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    required = vocabulary["registry_axes"]
    if snapshot is None:
        return {}, {
            "snapshot_id": None,
            "snapshot_sha256": None,
            "provided_axis_count": 0,
            "required_axis_count": len(required),
            "complete": False,
        }
    if (
        set(snapshot) != {"snapshot_id", "snapshot_sha256", "pools"}
        or not TOKEN.fullmatch(str(snapshot["snapshot_id"]))
        or not SHA256.fullmatch(str(snapshot["snapshot_sha256"]))
        or snapshot["snapshot_sha256"]
        != _sha({"snapshot_id": snapshot["snapshot_id"], "pools": snapshot["pools"]})
    ):
        raise CandidateGenerationError("candidate_registry_snapshot_invalid", str(snapshot))
    pools = snapshot["pools"]
    if not isinstance(pools, Mapping) or not set(pools) <= {row["axis_id"] for row in required}:
        raise CandidateGenerationError("candidate_registry_pools_invalid", str(pools))
    patterns = {row["axis_id"]: re.compile(row["value_pattern"]) for row in required}
    normalized = {}
    for axis, entries in pools.items():
        if not isinstance(entries, list) or not entries:
            raise CandidateGenerationError("candidate_registry_pool_invalid", axis)
        values = set()
        normalized[axis] = []
        for entry in entries:
            if (
                set(entry) != {"value", "weight", "cap"}
                or entry["value"] in values
                or not patterns[axis].fullmatch(str(entry["value"]))
                or not isinstance(entry["weight"], (int, float))
                or isinstance(entry["weight"], bool)
                or not math.isfinite(entry["weight"])
                or entry["weight"] <= 0
                or not isinstance(entry["cap"], int)
                or isinstance(entry["cap"], bool)
                or entry["cap"] <= 0
            ):
                raise CandidateGenerationError(
                    "candidate_registry_entry_invalid", f"{axis}:{entry}"
                )
            values.add(entry["value"])
            normalized[axis].append(dict(entry))
        normalized[axis].sort(key=lambda row: row["value"])
    return normalized, {
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "provided_axis_count": len(pools),
        "required_axis_count": len(required),
        "complete": len(pools) == len(required),
    }


def _registry_values(
    index: int,
    seed: int,
    pools: Mapping[str, list[dict[str, Any]]],
    usage: Mapping[str, Counter[str]],
    vocabulary: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chosen = []
    rejected = []
    for axis in vocabulary["registry_axes"]:
        axis_id = axis["axis_id"]
        pool = pools.get(axis_id)
        if pool is None:
            rejected.append({"reason": "registry_pool_missing", "axis_id": axis_id})
            continue
        available = [entry for entry in pool if usage[axis_id][entry["value"]] < entry["cap"]]
        if not available:
            rejected.append({"reason": "registry_pool_exhausted", "axis_id": axis_id})
            continue
        selected = min(
            available,
            key=lambda entry: _reservoir_key(seed, index, axis_id, entry["value"], entry["weight"]),
        )
        usage[axis_id][selected["value"]] += 1
        chosen.append({"axis_id": axis_id, "value": selected["value"]})
    return chosen, rejected


def _reservoir_key(seed: int, index: int, axis: str, value: str, weight: float) -> float:
    integer = int(hashlib.sha256(f"{seed}:{index}:{axis}:{value}".encode()).hexdigest(), 16)
    unit = (integer + 1) / (2**256 + 1)
    return -math.log(unit) / weight


def _tie(seed: int, index: int, axis: str, value: Any) -> str:
    return hashlib.sha256(f"{seed}:{index}:{axis}:{value}".encode()).hexdigest()


def _sha(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def _verify(report: Mapping[str, Any]) -> None:
    content = {
        key: value
        for key, value in report.items()
        if key not in {"schema_version", "batch_id", "batch_sha256"}
    }
    digest = _sha(content)
    if report["batch_sha256"] != digest or report["batch_id"] != f"dcb_{digest[:24]}":
        raise CandidateGenerationError("candidate_batch_hash_invalid", str(report.get("batch_id")))
