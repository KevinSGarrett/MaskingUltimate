"""Durable daily text logs and per-run JSON telemetry ledgers."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from loguru import logger

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOGS_ROOT = ROOT / "logs"
DEFAULT_RUNS_ROOT = ROOT / "runs"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _config_hash(config: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(config), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class PipelineRunLog:
    """Incrementally persisted run ledger; survives normal stage/process failures."""

    def __init__(
        self,
        *,
        image_ids: Sequence[str],
        config: Mapping[str, Any],
        logs_root: Path = DEFAULT_LOGS_ROOT,
        runs_root: Path = DEFAULT_RUNS_ROOT,
        run_id: str | None = None,
    ) -> None:
        now = _utc_now()
        self.run_id = run_id or f"run_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self.logs_root = Path(logs_root)
        self.runs_root = Path(runs_root)
        self.run_dir = self.runs_root / self.run_id
        self.run_path = self.run_dir / "run.json"
        self.logs_root.mkdir(parents=True, exist_ok=True)
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self._sink_id = logger.add(
            self.logs_root / f"maskfactory_{now.date().isoformat()}.log",
            format="{time:YYYY-MM-DDTHH:mm:ss.SSSZ} | {level} | {extra[run_id]} | {message}",
            filter=lambda record: record["extra"].get("run_id") == self.run_id,
            enqueue=False,
        )
        self._bound = logger.bind(run_id=self.run_id)
        self.document: dict[str, Any] = {
            "schema_version": "1.0.0",
            "run_id": self.run_id,
            "status": "running",
            "image_ids": list(image_ids),
            "started_at": now.isoformat(),
            "ended_at": None,
            "config_hash": _config_hash(config),
            "model_keys": [],
            "duration_sec": 0.0,
            "vram_peak_mb": 0.0,
            "stages": [],
            "error": None,
        }
        self._write()
        self._bound.info("run started images={}", ",".join(image_ids))

    def _write(self) -> None:
        temporary = self.run_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, self.run_path)

    def record_stage(
        self,
        *,
        image_id: str,
        stage: str,
        status: str,
        config_hash: str,
        model_keys: Sequence[str],
        duration_sec: float,
        vram_peak_mb: float,
    ) -> None:
        entry = {
            "image_id": image_id,
            "stage": stage,
            "status": status,
            "config_hash": config_hash,
            "model_keys": sorted(set(model_keys)),
            "duration_sec": round(float(duration_sec), 6),
            "vram_peak_mb": round(float(vram_peak_mb), 3),
        }
        self.document["stages"].append(entry)
        self.document["model_keys"] = sorted(
            set(self.document["model_keys"]).union(entry["model_keys"])
        )
        self.document["duration_sec"] = round(
            float(self.document["duration_sec"]) + entry["duration_sec"], 6
        )
        self.document["vram_peak_mb"] = max(
            float(self.document["vram_peak_mb"]), entry["vram_peak_mb"]
        )
        self._write()
        self._bound.info(
            "stage={} image={} status={} config={} models={} duration_sec={:.6f} vram_peak_mb={:.3f}",
            stage,
            image_id,
            status,
            config_hash,
            ",".join(entry["model_keys"]),
            entry["duration_sec"],
            entry["vram_peak_mb"],
        )

    def record_failure(
        self, *, image_id: str, stage: str, category: str, attempts: int, error: str
    ) -> None:
        entry = {
            "image_id": image_id,
            "stage": stage,
            "status": "failed",
            "category": category,
            "attempts": attempts,
            "error": error,
        }
        self.document["stages"].append(entry)
        self._write()
        self._bound.error(
            "stage={} image={} category={} attempts={} error={}",
            stage,
            image_id,
            category,
            attempts,
            error,
        )

    def finish(self, *, status: str, error: str | None = None) -> None:
        if self.document["status"] != "running":
            return
        self.document["status"] = status
        self.document["ended_at"] = _utc_now().isoformat()
        self.document["error"] = error
        self._write()
        self._bound.info("run finished status={}", status)
        logger.remove(self._sink_id)

    def __enter__(self) -> PipelineRunLog:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.finish(
            status="failed" if exc is not None else "complete", error=str(exc) if exc else None
        )
