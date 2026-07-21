"""Append-only import boundary for newly discovered provider challengers."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from ..governance import validate_external_source_registry, validate_model_registry

DISCOVERY_MARKER = "  # ---- AUTO-DISCOVERED PLANNED CHALLENGERS (append-only import boundary) ----"
DISCOVERY_FIELDS = {
    "provider_key",
    "discovered_at",
    "source_url",
    "component",
    "target_role",
    "output_type",
    "evidence_sha256",
}


class ProviderDiscoveryError(ValueError):
    """A discovery cannot enter the planned-challenger catalog safely."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _validate_discovery(discovery: Mapping[str, Any]) -> None:
    if set(discovery) != DISCOVERY_FIELDS:
        raise ProviderDiscoveryError(
            f"discovery must contain exact fields: {sorted(DISCOVERY_FIELDS)}"
        )
    payload = {key: discovery[key] for key in sorted(discovery) if key != "evidence_sha256"}
    if discovery["evidence_sha256"] != _canonical_sha256(payload):
        raise ProviderDiscoveryError("discovery evidence hash mismatch")
    key = discovery["provider_key"]
    if not isinstance(key, str) or re.fullmatch(r"[a-z][a-z0-9_]{2,63}", key) is None:
        raise ProviderDiscoveryError("discovery provider_key is invalid")
    for field in ("component", "target_role", "output_type"):
        if not isinstance(discovery[field], str) or not discovery[field].strip():
            raise ProviderDiscoveryError(f"discovery {field} is empty")
    if not isinstance(discovery["source_url"], str) or not discovery["source_url"].startswith(
        "https://"
    ):
        raise ProviderDiscoveryError("discovery source_url must use HTTPS")
    try:
        timestamp = datetime.fromisoformat(str(discovery["discovered_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderDiscoveryError("discovery discovered_at is invalid") from exc
    if timestamp.tzinfo is None:
        raise ProviderDiscoveryError("discovery discovered_at must include a timezone")


def _load_history(path: Path) -> tuple[list[str], str | None]:
    if not path.is_file():
        return [], None
    lines = path.read_text(encoding="utf-8").splitlines()
    previous = None
    for number, line in enumerate(lines, 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProviderDiscoveryError(f"invalid discovery history row {number}") from exc
        claimed = record.get("record_sha256")
        payload = {key: value for key, value in record.items() if key != "record_sha256"}
        if (
            claimed != _canonical_sha256(payload)
            or payload.get("previous_record_sha256") != previous
        ):
            raise ProviderDiscoveryError(f"discovery history chain is invalid at row {number}")
        previous = str(claimed)
    return lines, previous


def import_planned_challenger(
    discovery: Mapping[str, Any],
    *,
    external_registry_path: Path,
    pipeline_path: Path,
    model_registry_path: Path,
    history_path: Path,
) -> dict[str, Any]:
    """Import one write-once discovery without touching active roles/certificates."""
    _validate_discovery(discovery)
    external_registry_path = Path(external_registry_path)
    pipeline_path = Path(pipeline_path)
    model_registry_path = Path(model_registry_path)
    history_path = Path(history_path)
    original_registry = external_registry_path.read_bytes()
    original_history = history_path.read_bytes() if history_path.is_file() else None
    pipeline_bytes = pipeline_path.read_bytes()
    model_bytes = model_registry_path.read_bytes()
    registry = yaml.safe_load(original_registry)
    pipeline = yaml.safe_load(pipeline_bytes)
    models = json.loads(model_bytes)
    validate_external_source_registry(registry)
    validate_model_registry(models)
    if discovery["provider_key"] in registry["providers"]:
        raise ProviderDiscoveryError(
            f"provider discovery already exists: {discovery['provider_key']}"
        )
    active_roles = {
        role: config.get("active")
        for role, config in pipeline.get("provider_roles", {}).items()
        if isinstance(config, Mapping)
    }
    certificates = {
        str(model.get("key")): model.get("benchmark_certificate")
        for model in models["models"]
        if isinstance(model, Mapping) and "benchmark_certificate" in model
    }
    history_lines, previous_record_sha256 = _load_history(history_path)

    entry = {
        "component": discovery["component"],
        "lifecycle_state": "planned",
        "source_url": discovery["source_url"],
        "license": "unreviewed discovery; exact code and checkpoint terms must be frozen",
        "verify_license": True,
        "version": f"unfrozen discovery {discovery['discovered_at']}",
        "local_path": "(not installed; planned discovery challenger)",
        "output_type": discovery["output_type"],
        "role": f"planned challenger for {discovery['target_role']}; never active on import",
        "authority_level": "evaluation-only candidate after governed installation",
        "discovery_evidence_sha256": discovery["evidence_sha256"],
    }
    dumped = yaml.safe_dump(
        {str(discovery["provider_key"]): entry},
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    indented = "\n".join(f"  {line}" if line else line for line in dumped.splitlines())
    text = original_registry.decode("utf-8")
    if text.count(DISCOVERY_MARKER) != 1:
        raise ProviderDiscoveryError("external registry discovery marker is missing or duplicated")
    updated_text = text.replace(DISCOVERY_MARKER, f"{DISCOVERY_MARKER}\n{indented}\n", 1)
    candidate = yaml.safe_load(updated_text)
    validate_external_source_registry(candidate)
    if candidate["providers"][discovery["provider_key"]]["lifecycle_state"] != "planned":
        raise ProviderDiscoveryError("discovery import did not remain planned")

    prior_registry_sha256 = hashlib.sha256(original_registry).hexdigest()
    updated_registry_bytes = updated_text.encode("utf-8")
    record: dict[str, Any] = {
        "schema_version": "1.0.0",
        "provider_key": discovery["provider_key"],
        "discovered_at": discovery["discovered_at"],
        "discovery_evidence_sha256": discovery["evidence_sha256"],
        "prior_registry_sha256": prior_registry_sha256,
        "updated_registry_sha256": hashlib.sha256(updated_registry_bytes).hexdigest(),
        "active_roles_sha256": _canonical_sha256(active_roles),
        "benchmark_certificates_sha256": _canonical_sha256(certificates),
        "pipeline_file_sha256": hashlib.sha256(pipeline_bytes).hexdigest(),
        "model_registry_file_sha256": hashlib.sha256(model_bytes).hexdigest(),
        "previous_record_sha256": previous_record_sha256,
    }
    record["record_sha256"] = _canonical_sha256(record)

    registry_temp = external_registry_path.with_suffix(
        external_registry_path.suffix + ".discovery.tmp"
    )
    history_temp = history_path.with_suffix(history_path.suffix + ".tmp")
    registry_temp.write_bytes(updated_registry_bytes)
    history_temp.parent.mkdir(parents=True, exist_ok=True)
    history_text = "\n".join((*history_lines, json.dumps(record, sort_keys=True))) + "\n"
    history_temp.write_text(history_text, encoding="utf-8", newline="\n")
    try:
        os.replace(registry_temp, external_registry_path)
        os.replace(history_temp, history_path)
    except Exception:
        external_registry_path.write_bytes(original_registry)
        registry_temp.unlink(missing_ok=True)
        history_temp.unlink(missing_ok=True)
        raise

    if (
        pipeline_path.read_bytes() != pipeline_bytes
        or model_registry_path.read_bytes() != model_bytes
    ):
        external_registry_path.write_bytes(original_registry)
        if original_history is None:
            history_path.unlink(missing_ok=True)
        else:
            history_path.write_bytes(original_history)
        raise ProviderDiscoveryError(
            "discovery import changed active-role or certificate authority"
        )
    return record


__all__ = [
    "DISCOVERY_FIELDS",
    "DISCOVERY_MARKER",
    "ProviderDiscoveryError",
    "import_planned_challenger",
]
