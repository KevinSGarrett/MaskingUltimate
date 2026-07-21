"""Validation for bounded single-GPU visual-critic runtime evidence."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .critic_catalog import validate_catalog

SHA256 = re.compile(r"^[a-f0-9]{64}$")
QUALIFIED_MODEL_IDS = frozenset({"qwen3_6_27b_fp8", "internvl3_5_8b_bf16"})


class RuntimeQualificationError(ValueError):
    """Runtime evidence does not satisfy the bounded single-GPU contract."""


def _positive_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeQualificationError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise RuntimeQualificationError(f"{field} must be finite and positive")
    return result


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise RuntimeQualificationError(f"{field} must be a SHA-256")
    return value


def _models_by_id(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result = {str(row.get("model_id")): row for row in rows}
    if len(result) != len(rows):
        raise RuntimeQualificationError("runtime evidence model IDs must be unique")
    return result


def validate_single_gpu_runtime_evidence(
    evidence: Mapping[str, Any], catalog: Mapping[str, Any]
) -> None:
    """Require exact, reproducible two-process smokes for both feasible families."""

    validate_catalog(catalog)
    if evidence.get("schema_version") != "1.0.0":
        raise RuntimeQualificationError("runtime evidence schema version is unsupported")
    if evidence.get("status") != "RUNTIME_PASS_BOUNDED":
        raise RuntimeQualificationError("runtime evidence does not claim RUNTIME_PASS_BOUNDED")
    hardware = evidence.get("hardware")
    if not isinstance(hardware, Mapping):
        raise RuntimeQualificationError("runtime evidence hardware is missing")
    expected_hardware = catalog["current_hardware"]
    if (
        hardware.get("tier_id") != expected_hardware["tier_id"]
        or hardware.get("gpu_name") != expected_hardware["gpu_name"]
        or hardware.get("gpu_count") != 1
        or int(hardware.get("vram_bytes", 0)) != int(expected_hardware["vram_bytes_per_gpu"])
    ):
        raise RuntimeQualificationError("runtime evidence hardware differs from the catalog")

    evidence_models = _models_by_id(evidence.get("models") or [])
    if set(evidence_models) != QUALIFIED_MODEL_IDS:
        raise RuntimeQualificationError(
            "runtime evidence must contain exactly both feasible models"
        )
    catalog_models = {model["model_id"]: model for model in catalog["models"]}
    family_ids = set()
    for model_id, observation in evidence_models.items():
        registered = catalog_models[model_id]
        if not registered["hardware"]["single_gpu_48gb_feasible"]:
            raise RuntimeQualificationError(f"{model_id} is not a single-GPU candidate")
        for field in ("repository", "revision", "quantization", "family_id"):
            if observation.get(field) != registered[field]:
                raise RuntimeQualificationError(f"{model_id} {field} differs from the catalog")
        family_ids.add(observation["family_id"])
        _sha256(observation.get("artifact_tree_sha256"), f"{model_id}.artifact_tree_sha256")
        _sha256(observation.get("prompt_sha256"), f"{model_id}.prompt_sha256")
        if int(observation.get("downloaded_bytes", 0)) < int(registered["weight_bytes"]):
            raise RuntimeQualificationError(f"{model_id} downloaded bytes are incomplete")
        if int(observation.get("image_budget", 0)) < 3:
            raise RuntimeQualificationError(f"{model_id} image budget is below the panel contract")
        if int(observation.get("context_token_budget", 0)) < 4096:
            raise RuntimeQualificationError(f"{model_id} context budget is too small")
        endpoint = str(observation.get("endpoint") or "")
        if not (endpoint.startswith("http://127.0.0.1:") or endpoint == "local-process://isolated"):
            raise RuntimeQualificationError(f"{model_id} execution boundary is not private")
        runs = observation.get("process_runs")
        if not isinstance(runs, Sequence) or isinstance(runs, (str, bytes)) or len(runs) != 2:
            raise RuntimeQualificationError(f"{model_id} requires exactly two process runs")
        pids = set()
        response_hashes = set()
        for index, run in enumerate(runs):
            if not isinstance(run, Mapping) or run.get("status") != "pass":
                raise RuntimeQualificationError(f"{model_id} process run {index} did not pass")
            pids.add(int(run.get("pid", 0)))
            response_hashes.add(_sha256(run.get("response_sha256"), "response_sha256"))
            _positive_number(run.get("cold_latency_ms"), "cold_latency_ms")
            _positive_number(run.get("warm_latency_ms"), "warm_latency_ms")
            peak_vram = _positive_number(run.get("peak_vram_bytes"), "peak_vram_bytes")
            if peak_vram > int(expected_hardware["vram_bytes_per_gpu"]):
                raise RuntimeQualificationError(f"{model_id} exceeded available VRAM")
        if len(pids) != 2 or 0 in pids:
            raise RuntimeQualificationError(f"{model_id} restart evidence lacks distinct live PIDs")
        if len(response_hashes) != 1:
            raise RuntimeQualificationError(f"{model_id} response changed across process restart")
    if family_ids != {"qwen", "internvl"}:
        raise RuntimeQualificationError("runtime evidence lacks independent model families")
    if evidence.get("authority_claimed") is not False:
        raise RuntimeQualificationError("runtime smoke cannot claim visual authority")
