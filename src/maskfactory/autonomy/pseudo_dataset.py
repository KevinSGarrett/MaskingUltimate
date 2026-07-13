"""Train-only weighted pseudo-label manifest from calibrated autonomy lifecycle artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from ..io.hashing import sha256_file
from .calibration import verify_autonomy_certificate
from .lifecycle import certificate_is_revoked, load_scoped_certificate


def build_weighted_pseudo_manifest(
    lifecycle_root: Path,
    output_path: Path,
    *,
    certificate_root: Path,
    revocations_root: Path,
    human_holdout_ids_path: Path,
    operations_policy: dict[str, Any],
) -> dict[str, Any]:
    lifecycle_root = Path(lifecycle_root)
    holdout_ids = {
        line.strip()
        for line in Path(human_holdout_ids_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    records = []
    for path in sorted(lifecycle_root.rglob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("status") != operations_policy["calibrated_status"]:
            continue
        if document["image_id"] in holdout_ids:
            raise ValueError(
                f"calibrated pseudo-label overlaps a human holdout: {document['image_id']}"
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
        valid, reason = verify_autonomy_certificate(
            certificate,
            label=document["label"],
            context=document["context"],
            pipeline_fingerprint=document["pipeline_fingerprint"],
        )
        if not valid:
            continue
        recorded_mask_path = Path(document["winner_mask_path"])
        mask_path = (
            recorded_mask_path
            if recorded_mask_path.is_absolute()
            else lifecycle_root.parent / recorded_mask_path
        )
        if not mask_path.is_file() or sha256_file(mask_path) != document["winner_mask_sha256"]:
            raise ValueError(f"calibrated pseudo-label mask hash failed: {mask_path}")
        records.append(
            {
                "image_id": document["image_id"],
                "instance_id": document["instance_id"],
                "label": document["label"],
                "context": document["context"],
                "mask_path": str(mask_path),
                "mask_sha256": document["winner_mask_sha256"],
                "pipeline_fingerprint": document["pipeline_fingerprint"],
                "certificate_sha256": certificate["sha256"],
                "split": "train_only",
                "loss_weight": float(operations_policy["pseudo_label_loss_weight"]),
                "authority": "calibrated_auto_accepted_non_gold",
            }
        )
    manifest = {
        "schema_version": "1.0.0",
        "authority": "weighted_pseudo_labels_train_only",
        "record_count": len(records),
        "human_holdout_ids_sha256": sha256_file(human_holdout_ids_path),
        "human_holdout_overlap_count": 0,
        "loss_weight": float(operations_policy["pseudo_label_loss_weight"]),
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
