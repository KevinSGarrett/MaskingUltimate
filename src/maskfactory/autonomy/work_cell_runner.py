"""Continuous, milestone-batched execution for an autonomous work-cell mission."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .work_cell import STAGES, AutonomousWorkCell, WorkCellError


class StageHandler(Protocol):
    """One exact, hash-bound stage implementation."""

    implementation_sha256: str

    def __call__(self, work: Mapping[str, Any]) -> Mapping[str, Any]: ...


class WorkCellRunner:
    """Run a mission until terminal, idle, or its explicit operation bound."""

    def __init__(
        self,
        cell: AutonomousWorkCell,
        handlers: Mapping[str, StageHandler],
        *,
        owner: str,
        failure_root: Path | None = None,
        milestone_callback: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        missing = sorted(set(STAGES) - set(handlers))
        extra = sorted(set(handlers) - set(STAGES))
        if missing or extra:
            raise WorkCellError(f"stage handler coverage invalid: missing={missing} extra={extra}")
        if not owner.strip():
            raise ValueError("runner owner required")
        for stage, handler in handlers.items():
            digest = getattr(handler, "implementation_sha256", "")
            if not isinstance(digest, str) or len(digest) != 64:
                raise WorkCellError(f"stage handler hash invalid: {stage}")
        self.cell = cell
        self.handlers = dict(handlers)
        self.owner = owner
        self.failure_root = Path(failure_root or cell.root / "executor_failures")
        self.milestone_callback = milestone_callback

    def validate_bindings(self, mission_id: str) -> None:
        """Fail before work if the active handler bytes differ from the mission."""

        with self.cell._connect() as connection:
            manifest = self.cell._mission(connection, mission_id)
        expected = manifest["stage_versions"]
        drift = [
            stage
            for stage, handler in self.handlers.items()
            if handler.implementation_sha256 != expected[stage]
        ]
        if drift:
            raise WorkCellError(f"active stage implementation drift: {sorted(drift)}")

    def run(
        self,
        mission_id: str,
        *,
        max_stage_operations: int | None = None,
        idle_polls: int = 1,
        idle_seconds: float = 0.0,
    ) -> dict[str, Any]:
        """Execute without per-record reporting; return one sealed mission snapshot."""

        if max_stage_operations is not None and max_stage_operations < 1:
            raise ValueError("max_stage_operations must be positive")
        if idle_polls < 1 or idle_seconds < 0:
            raise ValueError("idle policy invalid")
        self.validate_bindings(mission_id)
        operations = 0
        consecutive_idle = 0
        prior_milestones = len(self.cell.report(mission_id)["milestones"])

        while max_stage_operations is None or operations < max_stage_operations:
            work = self.cell.claim(mission_id, owner=self.owner)
            if work is None:
                report = self.cell.report(mission_id)
                if report["mission_state"] == "complete":
                    break
                consecutive_idle += 1
                if consecutive_idle >= idle_polls:
                    break
                if idle_seconds:
                    time.sleep(idle_seconds)
                continue
            consecutive_idle = 0
            stage = str(work["stage"])
            try:
                result = self.handlers[stage](work)
                self.cell.apply_result(
                    mission_id,
                    str(work["record_id"]),
                    str(work["lease_token"]),
                    result,
                )
            except Exception as exc:  # stage isolation is a core mission guarantee
                evidence_sha = self._write_failure_evidence(mission_id, work, exc)
                self.cell.terminalize_system_failure(
                    mission_id,
                    str(work["record_id"]),
                    str(work["lease_token"]),
                    reason=f"stage_executor_failure:{stage}:{type(exc).__name__}",
                    evidence_sha256=evidence_sha,
                )
            operations += 1
            report = self.cell.report(mission_id)
            if len(report["milestones"]) > prior_milestones:
                prior_milestones = len(report["milestones"])
                if self.milestone_callback is not None:
                    self.milestone_callback(report)

        report = self.cell.report(mission_id)
        return {**report, "runner_stage_operations": operations}

    def _write_failure_evidence(
        self, mission_id: str, work: Mapping[str, Any], exc: Exception
    ) -> str:
        document = {
            "schema_version": "maskfactory.work_cell_executor_failure.v1",
            "mission_id": mission_id,
            "record_id": work["record_id"],
            "stage": work["stage"],
            "source_sha256": work["source_sha256"],
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
        }
        body = json.dumps(document, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        document["evidence_sha256"] = digest
        path = (
            self.failure_root
            / mission_id
            / f"{work['record_id']}_{work['stage']}_{digest[:12]}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != document:
                raise WorkCellError("executor failure evidence collision")
        else:
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            temporary.replace(path)
        return digest
