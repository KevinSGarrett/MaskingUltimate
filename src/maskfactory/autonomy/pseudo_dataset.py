"""Backward-compatible training manifest from certified autonomy lifecycle artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from ..io.hashing import sha256_file
from .calibration import verify_autonomy_certificate
from .lifecycle import (
    certificate_is_revoked,
    certificate_stratum_is_revoked,
    load_scoped_certificate,
    verified_lifecycle_winner_mask,
)


def build_weighted_pseudo_manifest(
    lifecycle_root: Path,
    output_path: Path,
    *,
    certificate_root: Path,
    revocations_root: Path,
    protected_anchor_ids_path: Path,
    operations_policy: dict[str, Any],
) -> dict[str, Any]:
    lifecycle_root = Path(lifecycle_root)
    protected_anchor_ids = {
        line.strip()
        for line in Path(protected_anchor_ids_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    records = []
    for path in sorted(lifecycle_root.rglob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if (
            document.get("status") != operations_policy["calibrated_status"]
            or document.get("truth_tier") != "autonomous_certified_gold"
        ):
            continue
        mask_path = verified_lifecycle_winner_mask(document, lifecycle_root)
        if document["image_id"] in protected_anchor_ids:
            raise ValueError(
                "autonomous training truth overlaps a protected calibration/holdout anchor: "
                f"{document['image_id']}"
            )
        if certificate_is_revoked(
            revocations_root,
            label=document["label"],
            context=document["context"],
            pipeline_fingerprint=document["pipeline_fingerprint"],
        ):
            continue
        certificate = load_scoped_certificate(
            certificate_root, label=document["label"], context=document["context"]
        )
        if not isinstance(certificate, dict):
            continue
        instance_context = str(certificate.get("instance_context", document["context"]))
        risk_bucket = str(certificate.get("risk_bucket", document["context"]))
        if instance_context in {"duo", "small_group"} and certificate_stratum_is_revoked(
            revocations_root,
            risk_bucket=risk_bucket,
            instance_context=instance_context,
            pipeline_fingerprint=document["pipeline_fingerprint"],
        ):
            continue
        valid, reason = verify_autonomy_certificate(
            certificate,
            label=document["label"],
            context=document["context"],
            instance_context=instance_context,
            risk_bucket=risk_bucket,
            pipeline_fingerprint=document["pipeline_fingerprint"],
        )
        if not valid:
            continue
        records.append(
            {
                "image_id": document["image_id"],
                "instance_id": document["instance_id"],
                "label": document["label"],
                "context": document["context"],
                "instance_context": instance_context,
                "mask_path": str(mask_path),
                "mask_sha256": document["winner_mask_sha256"],
                "pipeline_fingerprint": document["pipeline_fingerprint"],
                "certificate_sha256": certificate["sha256"],
                "split": "train_only",
                "truth_tier": "autonomous_certified_gold",
                "loss_weight": float(operations_policy["autonomous_certified_loss_weight"]),
                "authority": "certificate_bound_autonomous_training_truth",
            }
        )
    manifest = {
        "schema_version": "2.0.0",
        "authority": "autonomous_certified_gold_train_only",
        "truth_tier": "autonomous_certified_gold",
        "record_count": len(records),
        "protected_anchor_ids_sha256": sha256_file(protected_anchor_ids_path),
        "protected_anchor_overlap_count": 0,
        "loss_weight": float(operations_policy["autonomous_certified_loss_weight"]),
        "human_gold_loss_weight": float(operations_policy["human_gold_loss_weight"]),
        "records": records,
    }
    manifest["sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    _atomic_json(Path(output_path), manifest)
    return manifest


def _atomic_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = ["build_weighted_pseudo_manifest"]
