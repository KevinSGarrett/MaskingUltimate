"""Fail-closed proof that eligible MaskedWarehouse sources reach real consumers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import yaml


class MaskedWarehouseConsumerError(ValueError):
    """Consumer binding evidence is incomplete or inconsistent."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def verify_maskedwarehouse_consumers(
    *, project_root: Path, provenance_path: Path, binding_path: Path
) -> dict[str, Any]:
    provenance = yaml.safe_load(provenance_path.read_text(encoding="utf-8"))
    bindings = json.loads(binding_path.read_text(encoding="utf-8"))
    sources = provenance.get("sources")
    rows = bindings.get("sources")
    if not isinstance(sources, Mapping) or not isinstance(rows, list):
        raise MaskedWarehouseConsumerError("source registries are malformed")
    by_name = {row.get("source"): row for row in rows if isinstance(row, Mapping)}
    if set(by_name) != set(sources):
        raise MaskedWarehouseConsumerError("consumer binding source set drift")

    verified: list[dict[str, Any]] = []
    for source, policy in sources.items():
        row = by_name[source]
        admission = policy.get("training_admission", {})
        eligible = admission.get("status") == "permitted_after_qualification"
        if row.get("eligible") is not eligible:
            raise MaskedWarehouseConsumerError(f"{source}: eligibility drift")
        consumers = row.get("consumers")
        if not eligible:
            if consumers != [] or not row.get("blocked_reason"):
                raise MaskedWarehouseConsumerError(f"{source}: blocked source has consumer")
            verified.append({"source": source, "eligible": False, "status": "policy_blocked"})
            continue
        if not isinstance(consumers, list) or not consumers:
            raise MaskedWarehouseConsumerError(f"{source}: inventory-only source")
        verified_consumers = []
        for consumer in consumers:
            artifact = project_root / consumer["artifact_path"]
            if not artifact.is_file() or _sha256(artifact) != consumer["artifact_sha256"]:
                raise MaskedWarehouseConsumerError(f"{source}: downstream artifact drift")
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            packages = payload.get("packages", [])
            match = next((item for item in packages if item.get("source") == source), None)
            if not isinstance(match, Mapping):
                raise MaskedWarehouseConsumerError(f"{source}: consumer record missing")
            for field in ("source_sha256", "annotation_sha256", "manifest_sha256"):
                if match.get(field) != consumer.get(field):
                    raise MaskedWarehouseConsumerError(f"{source}: {field} drift")
            verified_consumers.append(dict(consumer))
        verified.append(
            {
                "source": source,
                "eligible": True,
                "status": "consumed",
                "consumers": verified_consumers,
            }
        )

    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "maskedwarehouse_consumer_binding_report",
        "status": "PASS",
        "provenance_sha256": _sha256(provenance_path),
        "binding_sha256": _sha256(binding_path),
        "eligible_source_count": sum(bool(row["eligible"]) for row in verified),
        "consumed_eligible_source_count": sum(row["status"] == "consumed" for row in verified),
        "policy_blocked_source_count": sum(row["status"] == "policy_blocked" for row in verified),
        "sources": verified,
        "authority_limits": {
            "source_masks_are_gold": False,
            "consumer_binding_grants_gold": False,
            "consumer_binding_grants_production_authority": False,
        },
    }
    report["seal_sha256"] = _canonical_sha256(report)
    return report


__all__ = ["MaskedWarehouseConsumerError", "verify_maskedwarehouse_consumers"]
