"""Central reader-capability policy for disjoint truth partitions."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

P5_CERTIFIED_ENTRY_COUNT = 200
D5_CERTIFIED_PACKAGE_COUNT = 300
D5_TARGET_PER_CELL = 8
D5_MINIMUM_COVERED_CELL_FRACTION = 0.80
D5_MINIMUM_ATTRIBUTE_COUNT = 40

READER_CAPABILITIES = MappingProxyType(
    {
        "trainer": ("train", "val"),
        "model_selector": ("val",),
        "pseudo_label_generator": ("train",),
        "threshold_tuner": ("calibration",),
        "certificate_fitter": ("calibration",),
        "final_evaluator": ("test_holdout", "hard_case_holdout"),
    }
)

PARTITION_CAPABILITIES = MappingProxyType(
    {
        "train": frozenset({"trainer", "model_selector", "pseudo_label_generator"}),
        "calibration": frozenset({"threshold_tuner", "certificate_fitter"}),
        "holdout": frozenset({"final_evaluator"}),
    }
)


def require_partition_capability(partition: str, capability: str) -> None:
    """Reject every reader that is not explicitly authorized for a truth partition."""
    allowed = PARTITION_CAPABILITIES.get(partition)
    if allowed is None:
        raise ValueError(f"unknown truth partition: {partition}")
    if capability not in allowed:
        raise ValueError(
            f"reader capability {capability!r} cannot access truth partition {partition!r}"
        )


def serialized_reader_capabilities() -> dict[str, list[str]]:
    return {name: list(splits) for name, splits in READER_CAPABILITIES.items()}


def evaluate_certified_volume_gates(
    certified_training_package_count: int, coverage: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate P5/D5 from certified volume; pseudo-label weight is never an input."""
    if (
        not isinstance(certified_training_package_count, int)
        or certified_training_package_count < 0
    ):
        raise ValueError("certified training package count must be a nonnegative integer")
    cells = coverage.get("cells")
    attributes = coverage.get("attribute_totals")
    if not isinstance(cells, list) or not cells or not isinstance(attributes, Mapping):
        raise ValueError("certified coverage matrix is incomplete")
    covered_cells = sum(
        isinstance(cell, Mapping) and int(cell.get("approved_gold_count", -1)) >= D5_TARGET_PER_CELL
        for cell in cells
    )
    covered_fraction = covered_cells / len(cells)
    attributes_pass = bool(attributes) and all(
        isinstance(value, int) and value >= D5_MINIMUM_ATTRIBUTE_COUNT
        for value in attributes.values()
    )
    p5_passed = certified_training_package_count >= P5_CERTIFIED_ENTRY_COUNT
    coverage_passed = covered_fraction >= D5_MINIMUM_COVERED_CELL_FRACTION and attributes_pass
    return {
        "certified_training_package_count": certified_training_package_count,
        "p5_entry_target": P5_CERTIFIED_ENTRY_COUNT,
        "p5_entry_passed": p5_passed,
        "d5_certified_target": D5_CERTIFIED_PACKAGE_COUNT,
        "d5_covered_cell_fraction": covered_fraction,
        "d5_minimum_covered_cell_fraction": D5_MINIMUM_COVERED_CELL_FRACTION,
        "d5_attributes_passed": attributes_pass,
        "d5_coverage_passed": coverage_passed,
        "d5_passed": certified_training_package_count >= D5_CERTIFIED_PACKAGE_COUNT
        and coverage_passed,
    }


__all__ = [
    "PARTITION_CAPABILITIES",
    "P5_CERTIFIED_ENTRY_COUNT",
    "D5_CERTIFIED_PACKAGE_COUNT",
    "READER_CAPABILITIES",
    "evaluate_certified_volume_gates",
    "require_partition_capability",
    "serialized_reader_capabilities",
]
