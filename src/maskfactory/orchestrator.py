"""Deterministic file-only stage orchestration for the MaskFactory pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from .gpu import GpuLock
from .state import transition_image_status, writer_connection

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORK_ROOT = ROOT / "work"
DEFAULT_PIPELINE_CONFIG = ROOT / "configs" / "pipeline.yaml"


@dataclass(frozen=True)
class StageSpec:
    name: str
    dependencies: tuple[str, ...]

    @property
    def slug(self) -> str:
        return self.name.lower().replace(".", "_")


STAGE_SPECS = (
    StageSpec("S00", ()),
    StageSpec("S01", ("S00",)),
    StageSpec("S02", ("S01",)),
    StageSpec("S03", ("S02",)),
    StageSpec("S04", ("S03",)),
    StageSpec("S05", ("S04",)),
    StageSpec("S06", ("S05",)),
    StageSpec("S07", ("S06",)),
    StageSpec("S08", ("S07",)),
    StageSpec("S08.5", ("S08",)),
    StageSpec("S09", ("S08.5",)),
    StageSpec("S09.5", ("S09",)),
    StageSpec("S10", ("S09.5",)),
    StageSpec("S11", ("S10",)),
    StageSpec("S12", ("S11",)),
    StageSpec("S13", ("S12",)),
    StageSpec("S14", ("S13",)),
    StageSpec("S15", ("S14",)),
)
STAGE_BY_NAME = MappingProxyType({stage.name: stage for stage in STAGE_SPECS})
STAGE_ORDER = tuple(stage.name for stage in STAGE_SPECS)


class StageConfigurationError(ValueError):
    """Raised for unknown, contradictory, or malformed stage configuration."""


class StageRunnerMissingError(RuntimeError):
    """Raised when execution reaches a stage whose implementation is not registered."""


class TransientStageError(RuntimeError):
    """Explicit retryable stage failure (OOM/IO/service interruption)."""


class SemanticStageError(RuntimeError):
    """A valid computation whose meaning requires human review."""


class FatalStageError(RuntimeError):
    """Non-retryable failure that quarantines this image."""


class StagePolicyError(RuntimeError):
    """Classified terminal stage outcome carrying retry evidence."""

    def __init__(self, *, stage: str, category: str, attempts: int, cause: BaseException) -> None:
        self.stage = stage
        self.category = category
        self.attempts = attempts
        self.cause = cause
        super().__init__(f"{stage} {category} after {attempts} attempt(s): {cause}")


@dataclass(frozen=True)
class StageContext:
    """Filesystem contract provided to exactly one stage invocation."""

    image_id: str
    stage: StageSpec
    output_dir: Path
    work_root: Path
    config: Mapping[str, Any]
    config_hash: str

    def prior_stage_dir(self, stage_name: str) -> Path:
        """Resolve a prior artifact directory without passing in-memory outputs."""
        spec = _stage(stage_name)
        return self.work_root / spec.slug / self.image_id


StageRunner = Callable[[StageContext], Mapping[str, Any]]
STAGE_RUNNERS: dict[str, StageRunner] = {}


@dataclass(frozen=True)
class StageExecution:
    stage: str
    status: str
    config_hash: str
    output_dir: str
    forced: bool
    model_keys: tuple[str, ...] = ()
    duration_sec: float = 0.0
    vram_peak_mb: float = 0.0


@dataclass(frozen=True)
class BatchOutcome:
    image_id: str
    status: str
    completed_stages: tuple[str, ...]
    failed_stage: str | None = None
    attempts: int = 0
    error: str | None = None


def _stage(name: str) -> StageSpec:
    normalized = name.upper()
    try:
        return STAGE_BY_NAME[normalized]
    except KeyError as exc:
        raise StageConfigurationError(
            f"unknown stage {name!r}; expected one of: {', '.join(STAGE_ORDER)}"
        ) from exc


def _normalize_stages(values: Sequence[str]) -> set[str]:
    return {_stage(value).name for value in values}


def load_pipeline_config(path: Path = DEFAULT_PIPELINE_CONFIG) -> dict[str, Any]:
    """Load the pipeline mapping; an absent pre-P1 config means empty defaults."""
    path = Path(path)
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise StageConfigurationError("pipeline config root must be a mapping")
    stages = loaded.get("stages", {})
    if not isinstance(stages, dict):
        raise StageConfigurationError("pipeline config stages must be a mapping")
    unknown = set(stages).difference(STAGE_ORDER)
    if unknown:
        raise StageConfigurationError("pipeline config has unknown stages: " + ", ".join(unknown))
    return loaded


def stage_config(config: Mapping[str, Any], stage_name: str) -> dict[str, Any]:
    """Return only global and per-stage configuration stamped for this stage."""
    stage = _stage(stage_name)
    global_config = config.get("global", {})
    stages = config.get("stages", {})
    if not isinstance(global_config, Mapping) or not isinstance(stages, Mapping):
        raise StageConfigurationError("global and stages config entries must be mappings")
    specific = stages.get(stage.name, {})
    if not isinstance(specific, Mapping):
        raise StageConfigurationError(f"config for {stage.name} must be a mapping")
    return {"global": dict(global_config), "stage": dict(specific)}


def config_digest(config: Mapping[str, Any], stage_name: str) -> str:
    """Hash canonical stage-relevant configuration for drift/caching evidence."""
    encoded = json.dumps(
        stage_config(config, stage_name), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def plan_stages(
    *,
    selected: Sequence[str] = (),
    force: Sequence[str] = (),
    skip: Sequence[str] = (),
    config: Mapping[str, Any] | None = None,
) -> tuple[StageSpec, ...]:
    """Resolve stage selection in canonical topological order."""
    config = config or {}
    selected_names = _normalize_stages(selected) if selected else set(STAGE_ORDER)
    force_names = _normalize_stages(force)
    skip_names = _normalize_stages(skip)
    conflict = force_names.intersection(skip_names)
    if conflict:
        raise StageConfigurationError(
            "stages cannot be both forced and skipped: " + ", ".join(conflict)
        )
    selected_names.update(force_names)
    stages_config = config.get("stages", {})
    if not isinstance(stages_config, Mapping):
        raise StageConfigurationError("pipeline config stages must be a mapping")
    planned: list[StageSpec] = []
    for stage in STAGE_SPECS:
        if stage.name not in selected_names or stage.name in skip_names:
            continue
        raw = stages_config.get(stage.name, {})
        if not isinstance(raw, Mapping):
            raise StageConfigurationError(f"config for {stage.name} must be a mapping")
        if raw.get("enabled", True) is False and stage.name not in force_names:
            continue
        planned.append(stage)
    return tuple(planned)


def register_stage_runner(stage_name: str, runner: StageRunner) -> None:
    """Register the concrete implementation for one canonical stage."""
    stage = _stage(stage_name)
    STAGE_RUNNERS[stage.name] = runner


def _read_stamp(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _replace_directory(staging: Path, destination: Path) -> None:
    """Promote a complete directory and remove every stale prior output."""
    backup = destination.with_name(destination.name + f".old-{uuid.uuid4().hex}")
    had_destination = destination.exists()
    if had_destination:
        os.replace(destination, backup)
    try:
        os.replace(staging, destination)
    except Exception:
        if had_destination and backup.exists():
            os.replace(backup, destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def _cleanup_abandoned_staging(destination: Path) -> None:
    """Remove only this image/stage's private directories left by a hard-killed owner."""
    for candidate in destination.parent.glob(destination.name + ".tmp-*"):
        if candidate.is_dir():
            shutil.rmtree(candidate)


def _execute_stage(
    *,
    image_id: str,
    stage: StageSpec,
    config: Mapping[str, Any],
    work_root: Path,
    runner: StageRunner,
    forced: bool,
) -> StageExecution:
    digest = config_digest(config, stage.name)
    destination = work_root / stage.slug / image_id
    stamp = _read_stamp(destination / "stage_run.json")
    if (
        not forced
        and stamp is not None
        and stamp.get("status") == "complete"
        and stamp.get("config_hash") == digest
        and (destination / "manifest_delta.json").is_file()
    ):
        return StageExecution(
            stage.name,
            "cached",
            digest,
            str(destination),
            False,
            tuple(stamp.get("model_keys", [])),
            0.0,
            float(stamp.get("vram_peak_mb", 0.0)),
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    _cleanup_abandoned_staging(destination)
    staging = destination.with_name(destination.name + f".tmp-{uuid.uuid4().hex}")
    staging.mkdir(parents=False, exist_ok=False)
    context = StageContext(
        image_id=image_id,
        stage=stage,
        output_dir=staging,
        work_root=work_root,
        config=MappingProxyType(stage_config(config, stage.name)),
        config_hash=digest,
    )
    try:
        started = time.perf_counter()
        delta = runner(context)
        if not isinstance(delta, Mapping):
            raise TypeError(f"{stage.name} runner must return a manifest-delta mapping")
        delta_document = dict(delta)
        telemetry = delta_document.pop("_telemetry", {})
        if not isinstance(telemetry, Mapping):
            raise TypeError(f"{stage.name} _telemetry must be a mapping")
        configured_models = context.config["stage"].get("model_keys", [])
        model_keys = tuple(sorted(set(telemetry.get("model_keys", configured_models))))
        vram_peak_mb = float(telemetry.get("vram_peak_mb", 0.0))
        if vram_peak_mb < 0:
            raise ValueError("vram_peak_mb cannot be negative")
        duration_sec = time.perf_counter() - started
        _write_json(staging / "manifest_delta.json", delta_document)
        files = sorted(
            path.relative_to(staging).as_posix() for path in staging.rglob("*") if path.is_file()
        )
        _write_json(
            staging / "stage_run.json",
            {
                "image_id": image_id,
                "stage": stage.name,
                "dependencies": list(stage.dependencies),
                "config_hash": digest,
                "forced": forced,
                "status": "complete",
                "model_keys": list(model_keys),
                "duration_sec": duration_sec,
                "vram_peak_mb": vram_peak_mb,
                "files": files,
            },
        )
        _replace_directory(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return StageExecution(
        stage.name,
        "complete",
        digest,
        str(destination),
        forced,
        model_keys,
        duration_sec,
        vram_peak_mb,
    )


def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, (TransientStageError, OSError, TimeoutError, MemoryError)) or (
        exc.__class__.__name__ == "OutOfMemoryError"
    )


def _execute_with_policy(
    *,
    image_id: str,
    stage: StageSpec,
    config: Mapping[str, Any],
    work_root: Path,
    runner: StageRunner,
    forced: bool,
    retry_delays: Sequence[float],
    sleeper: Callable[[float], None],
) -> StageExecution:
    attempts = 0
    while True:
        attempts += 1
        try:
            return _execute_stage(
                image_id=image_id,
                stage=stage,
                config=config,
                work_root=work_root,
                runner=runner,
                forced=forced,
            )
        except SemanticStageError as exc:
            raise StagePolicyError(
                stage=stage.name, category="semantic", attempts=attempts, cause=exc
            ) from exc
        except FatalStageError as exc:
            raise StagePolicyError(
                stage=stage.name, category="fatal", attempts=attempts, cause=exc
            ) from exc
        except Exception as exc:
            if _is_transient(exc) and attempts <= len(retry_delays):
                sleeper(retry_delays[attempts - 1])
                continue
            category = "transient_exhausted" if _is_transient(exc) else "fatal"
            raise StagePolicyError(
                stage=stage.name, category=category, attempts=attempts, cause=exc
            ) from exc


def run_pipeline(
    image_id: str,
    *,
    selected: Sequence[str] = (),
    force: Sequence[str] = (),
    skip: Sequence[str] = (),
    config: Mapping[str, Any] | None = None,
    work_root: Path = DEFAULT_WORK_ROOT,
    runners: Mapping[str, StageRunner] | None = None,
    retry_delays: Sequence[float] = (1.0, 2.0),
    sleeper: Callable[[float], None] = time.sleep,
    gpu_lock_path: Path | None = None,
    run_log: Any | None = None,
) -> tuple[StageExecution, ...]:
    """Run selected stages; downstream communication remains entirely on disk."""
    if not image_id.startswith("img_"):
        raise ValueError("image_id must start with img_")
    config = config or {}
    force_names = _normalize_stages(force)
    plan = plan_stages(selected=selected, force=force, skip=skip, config=config)
    available = runners if runners is not None else STAGE_RUNNERS
    lease = (
        GpuLock(Path(gpu_lock_path), purpose="pipeline", image_id=image_id)
        if gpu_lock_path is not None
        else nullcontext()
    )
    results: list[StageExecution] = []
    with lease:
        for stage in plan:
            runner = available.get(stage.name)
            if runner is None:
                raise StageRunnerMissingError(f"no runner registered for {stage.name}")
            try:
                execution = _execute_with_policy(
                    image_id=image_id,
                    stage=stage,
                    config=config,
                    work_root=Path(work_root),
                    runner=runner,
                    forced=stage.name in force_names,
                    retry_delays=retry_delays,
                    sleeper=sleeper,
                )
            except StagePolicyError as exc:
                if run_log is not None:
                    run_log.record_failure(
                        image_id=image_id,
                        stage=exc.stage,
                        category=exc.category,
                        attempts=exc.attempts,
                        error=str(exc.cause),
                    )
                raise
            results.append(execution)
            if run_log is not None:
                run_log.record_stage(
                    image_id=image_id,
                    stage=execution.stage,
                    status=execution.status,
                    config_hash=execution.config_hash,
                    model_keys=execution.model_keys,
                    duration_sec=execution.duration_sec,
                    vram_peak_mb=execution.vram_peak_mb,
                )
    return tuple(results)


def _append_queue(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(record), sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def run_batch(
    image_ids: Sequence[str],
    *,
    database: Path,
    selected: Sequence[str] = (),
    force: Sequence[str] = (),
    skip: Sequence[str] = (),
    config: Mapping[str, Any] | None = None,
    work_root: Path = DEFAULT_WORK_ROOT,
    runners: Mapping[str, StageRunner] | None = None,
    retry_delays: Sequence[float] = (1.0, 2.0),
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[BatchOutcome, ...]:
    """Run a batch, route semantic failures, quarantine fatal failures, and continue."""
    outcomes: list[BatchOutcome] = []
    queue_root = Path(work_root) / "queues"
    for image_id in image_ids:
        try:
            executions = run_pipeline(
                image_id,
                selected=selected,
                force=force,
                skip=skip,
                config=config,
                work_root=work_root,
                runners=runners,
                retry_delays=retry_delays,
                sleeper=sleeper,
            )
        except StagePolicyError as exc:
            record = {
                "ts": datetime_now(),
                "image_id": image_id,
                "stage": exc.stage,
                "category": exc.category,
                "attempts": exc.attempts,
                "error": str(exc.cause),
            }
            if exc.category == "semantic":
                record["route"] = "review"
                _append_queue(queue_root / "review_queue.jsonl", record)
                status = "needs_review"
            else:
                record["route"] = "quarantine"
                _append_queue(queue_root / "quarantine_queue.jsonl", record)
                with writer_connection(database) as connection:
                    transition_image_status(
                        connection,
                        image_id,
                        "quarantined",
                        updated_at=record["ts"],
                        current_stage=exc.stage,
                    )
                status = "quarantined"
            outcomes.append(
                BatchOutcome(
                    image_id=image_id,
                    status=status,
                    completed_stages=(),
                    failed_stage=exc.stage,
                    attempts=exc.attempts,
                    error=str(exc.cause),
                )
            )
            continue
        outcomes.append(
            BatchOutcome(
                image_id=image_id,
                status="complete",
                completed_stages=tuple(execution.stage for execution in executions),
            )
        )
    return tuple(outcomes)


def datetime_now() -> str:
    """UTC timestamp seam kept injectable/patchable for durable queue evidence."""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def execution_as_dict(result: StageExecution) -> dict[str, Any]:
    """Stable CLI/log representation."""
    return asdict(result)
