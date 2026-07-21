"""Fail-closed storage capacity policy for the DAZ acquisition worker."""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

GIB = 1024**3
CAPACITY_REFUSED_EXIT = 76


class CapacityPolicyError(ValueError):
    """The storage thresholds or observed capacity are invalid."""


class CapacityHold(RuntimeError):
    """New or active acquisition work is prohibited by the storage floor."""

    def __init__(self, report: "CapacityReport", operation: str) -> None:
        self.report = report
        self.operation = operation
        super().__init__(
            f"storage_capacity_{report.state}: {operation} refused with "
            f"{report.free_gib:.3f} GiB free"
        )


@dataclass(frozen=True)
class CapacityReport:
    state: str
    free_bytes: int
    free_gib: float
    soft_floor_gib: float
    hard_floor_gib: float
    emergency_floor_gib: float
    new_work_allowed: bool
    active_job_allowed: bool


def evaluate_capacity(
    free_bytes: int,
    *,
    soft_floor_gib: float = 150.0,
    hard_floor_gib: float = 100.0,
    emergency_floor_gib: float = 60.0,
) -> CapacityReport:
    if (
        isinstance(free_bytes, bool)
        or not isinstance(free_bytes, int)
        or free_bytes < 0
        or not 0 < emergency_floor_gib < hard_floor_gib < soft_floor_gib
    ):
        raise CapacityPolicyError("capacity thresholds or observed bytes are invalid")
    free_gib = free_bytes / GIB
    if free_gib < emergency_floor_gib:
        state = "emergency"
    elif free_gib < hard_floor_gib:
        state = "hard"
    elif free_gib < soft_floor_gib:
        state = "soft"
    else:
        state = "healthy"
    return CapacityReport(
        state=state,
        free_bytes=free_bytes,
        free_gib=free_gib,
        soft_floor_gib=soft_floor_gib,
        hard_floor_gib=hard_floor_gib,
        emergency_floor_gib=emergency_floor_gib,
        new_work_allowed=state == "healthy",
        active_job_allowed=state in {"healthy", "soft"},
    )


def inspect_capacity(
    root: Path,
    *,
    soft_floor_gib: float = 150.0,
    hard_floor_gib: float = 100.0,
    emergency_floor_gib: float = 60.0,
    free_bytes_override: int | None = None,
) -> CapacityReport:
    root = Path(root)
    if not root.is_dir():
        raise CapacityPolicyError("capacity root must be an existing directory")
    free_bytes = (
        free_bytes_override
        if free_bytes_override is not None
        else int(shutil.disk_usage(root).free)
    )
    return evaluate_capacity(
        free_bytes,
        soft_floor_gib=soft_floor_gib,
        hard_floor_gib=hard_floor_gib,
        emergency_floor_gib=emergency_floor_gib,
    )


def ensure_new_work_allowed(root: Path, **kwargs: float) -> CapacityReport:
    report = inspect_capacity(root, **kwargs)
    if not report.new_work_allowed:
        raise CapacityHold(report, "new_work")
    return report


def ensure_active_job_allowed(root: Path, **kwargs: float) -> CapacityReport:
    report = inspect_capacity(root, **kwargs)
    if not report.active_job_allowed:
        raise CapacityHold(report, "active_job")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--operation", choices=("new-work", "active-job"), default="new-work")
    parser.add_argument("--soft-floor-gib", type=float, default=150.0)
    parser.add_argument("--hard-floor-gib", type=float, default=100.0)
    parser.add_argument("--emergency-floor-gib", type=float, default=60.0)
    parser.add_argument("--free-bytes", type=int, help="Deterministic diagnostic/test override.")
    args = parser.parse_args()
    try:
        report = inspect_capacity(
            args.root,
            soft_floor_gib=args.soft_floor_gib,
            hard_floor_gib=args.hard_floor_gib,
            emergency_floor_gib=args.emergency_floor_gib,
            free_bytes_override=args.free_bytes,
        )
        allowed = (
            report.new_work_allowed if args.operation == "new-work" else report.active_job_allowed
        )
        payload = {"schema_version": "1.0.0", **asdict(report), "operation": args.operation}
        print(json.dumps(payload, sort_keys=True))
        return 0 if allowed else CAPACITY_REFUSED_EXIT
    except (CapacityPolicyError, OSError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "state": "invalid",
                    "operation": args.operation,
                    "reason": f"{type(exc).__name__}: {exc}",
                },
                sort_keys=True,
            )
        )
        return CAPACITY_REFUSED_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
