"""Production-aware weekly audit queue builder for runs/**/autonomy/*.json."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ..io.hashing import sha256_file
from ..validation import validate_document
from .audit import select_mixed_human_audits
from .lifecycle import verified_lifecycle_winner_mask


def iter_lifecycle_sidecars(lifecycle_root: Path) -> list[Path]:
    """Discover autonomy lifecycle sidecars under a root.

    Production writes live at ``runs/**/autonomy/<label>.json``. Demo/test roots
    may be a flat lifecycle directory. Prefer ``**/autonomy/*.json`` when present
    so scanning ``runs/`` does not choke on unrelated JSON.
    """
    root = Path(lifecycle_root)
    autonomy_hits = sorted(
        path
        for path in root.rglob("*.json")
        if "autonomy" in path.parts and not path.name.endswith(".corpus_record.json")
    )
    if autonomy_hits:
        return autonomy_hits
    return sorted(
        path for path in root.rglob("*.json") if not path.name.endswith(".corpus_record.json")
    )


def build_production_weekly_audit_queue(
    lifecycle_root: Path,
    output_path: Path,
    *,
    period_id: str,
    operations_policy: dict[str, Any],
) -> dict[str, Any]:
    """Build the weekly audit queue from production or flat lifecycle roots."""
    lifecycle_root = Path(lifecycle_root)
    records = []
    for path in iter_lifecycle_sidecars(lifecycle_root):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if validate_document(document, "autonomy_lifecycle"):
            continue
        if document.get("status") != operations_policy["calibrated_status"]:
            continue
        # Mask paths are relative to the stage root (parent of the autonomy/ dir).
        winner_mask = verified_lifecycle_winner_mask(document, path.parent)
        identity = (
            f"{document['image_id']}:{document['instance_id']}:{document['label']}:"
            f"{document['winner_mask_sha256']}:{document['pipeline_fingerprint']}"
        )
        records.append(
            {
                "record_id": hashlib.sha256(identity.encode()).hexdigest(),
                "image_id": document["image_id"],
                "instance_id": document["instance_id"],
                "label": document["label"],
                "context": document["context"],
                "risk_bucket": document.get("risk_bucket", document["context"]),
                "risk_priority": float(document.get("risk_priority", 0.0)),
                "pipeline_fingerprint": document["pipeline_fingerprint"],
                "winner_mask_path": document["winner_mask_path"],
                "winner_mask_sha256": document["winner_mask_sha256"],
                "lifecycle_path": str(path),
                "lifecycle_sha256": sha256_file(path),
                "verified_winner_mask_path": str(winner_mask),
            }
        )
    selection = select_mixed_human_audits(
        tuple(records),
        random_fraction=float(operations_policy["random_human_audit_fraction"]),
        minimum_random=int(operations_policy["minimum_random_audits_per_week"]),
        risk_oversample_fraction=float(operations_policy["risk_oversample_fraction"]),
        minimum_per_high_risk_bucket=int(operations_policy["minimum_audits_per_high_risk_bucket"]),
        period_id=period_id,
    )
    selected = set(selection.selected_record_ids)
    document = {
        "schema_version": "1.0.0",
        "period_id": period_id,
        "population_count": selection.population_count,
        "selected_count": len(selection.selected_record_ids),
        "random_selected_count": len(selection.random_record_ids),
        "risk_selected_count": len(selection.risk_record_ids),
        "selection_fraction": (
            len(selection.selected_record_ids) / selection.population_count
            if selection.population_count
            else 0.0
        ),
        "selection_method": "preoutcome_random_plus_risk_bucket_oversample",
        "records": [record for record in records if record["record_id"] in selected],
        "outcomes_status": "pending" if selected else "empty",
    }
    _atomic_json(Path(output_path), document)
    return document


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


__all__ = [
    "build_production_weekly_audit_queue",
    "iter_lifecycle_sidecars",
]
