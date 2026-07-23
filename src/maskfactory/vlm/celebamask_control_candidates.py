"""Select exact direct-label CelebAMask-HQ critic-control candidates."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image

from .canonical_polygon_source_candidates import sha256_file
from .critic_catalog import canonical_sha256

SCHEMA_VERSION = "maskfactory.celebamask_control_candidates.v1"
LABELS = {"hair": "hair", "neck": "neck"}
PARTITIONS = ("qualification_train", "qualification_test")


class CelebAMaskControlCandidateError(ValueError):
    """CelebAMask candidate inputs or authority bindings are invalid."""


def _partition(sample_id: str) -> str:
    value = int(hashlib.sha256(sample_id.encode("utf-8")).hexdigest()[:8], 16)
    return PARTITIONS[value % len(PARTITIONS)]


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CelebAMaskControlCandidateError(f"invalid yaml:{path}")
    return value


def _verify_policy(provenance: Mapping[str, Any], remap: Mapping[str, Any]) -> dict[str, Any]:
    source = provenance.get("sources", {}).get("celebamask_hq", {})
    admission = source.get("training_admission", {})
    allowed_uses = source.get("allowed_uses", [])
    if (
        source.get("license_status") != "recorded_restricted_non_commercial"
        or "private_noncommercial_semantic_critic_calibration_after_qualification"
        not in allowed_uses
        or admission.get("status") != "permitted_after_qualification"
    ):
        raise CelebAMaskControlCandidateError("critic calibration use is not permitted")
    mappings = remap.get("mappings", {})
    for raw_label, canonical_label in LABELS.items():
        mapping = mappings.get(raw_label, {})
        if mapping.get("action") != "direct" or mapping.get("part") != [canonical_label]:
            raise CelebAMaskControlCandidateError(
                f"label is not an exact direct mapping:{raw_label}"
            )
        if canonical_label not in admission.get("allowed_label_scope", []):
            raise CelebAMaskControlCandidateError(
                f"label is outside admitted scope:{canonical_label}"
            )
    return {
        "source_url": source.get("official_source_url"),
        "license_status": source["license_status"],
        "use_profile_id": admission.get("use_profile_id"),
        "external_masks_are_gold": provenance.get("policy", {}).get("source_masks_are_gold"),
    }


def _candidate(
    *,
    root: Path,
    mask_path: Path,
    raw_label: str,
    canonical_label: str,
) -> dict[str, Any] | None:
    stem = mask_path.name.removesuffix(f"_{raw_label}.png")
    source_path = root / "CelebA-HQ-img" / f"{int(stem)}.jpg"
    if not source_path.is_file():
        return None
    with Image.open(mask_path) as opened:
        mask = np.asarray(opened.convert("L"))
    values = set(np.unique(mask).tolist())
    if not values.issubset({0, 255}) or not np.any(mask == 255):
        return None
    with Image.open(source_path) as opened:
        source_size = list(opened.size)
    sample_id = f"celebamask_{int(stem):05d}_{canonical_label}"
    return {
        "sample_id": sample_id,
        "source_image_id": f"celebamask_{int(stem):05d}",
        "canonical_label": canonical_label,
        "raw_label": raw_label,
        "assigned_partition": _partition(f"celebamask_{int(stem):05d}"),
        "source_relative_path": source_path.relative_to(root).as_posix(),
        "source_dimensions": source_size,
        "mask_relative_path": mask_path.relative_to(root).as_posix(),
        "mask_dimensions": [int(mask.shape[1]), int(mask.shape[0])],
        "mask_pixel_count": int(np.count_nonzero(mask == 255)),
        "mask_values": sorted(values),
        "alignment_policy": "resize_source_to_mask_bilinear",
        "external_reference_qualification_complete": False,
        "visual_alignment_reviewed": False,
        "critic_control_eligible": False,
        "gold_or_production_authority": False,
    }


def build_celebamask_control_candidates(
    *,
    root: Path,
    provenance_path: Path,
    remap_path: Path,
    per_label_partition: int = 8,
) -> dict[str, Any]:
    """Select deterministic, partition-bound direct-label candidates."""

    if per_label_partition < 1:
        raise CelebAMaskControlCandidateError("per-label partition count is invalid")
    provenance = _load_yaml(provenance_path)
    remap = _load_yaml(remap_path)
    policy = _verify_policy(provenance, remap)
    if policy["external_masks_are_gold"] is not False:
        raise CelebAMaskControlCandidateError("external masks gold policy drifted")
    annotation_root = root / "CelebAMask-HQ-mask-anno"
    selected: list[dict[str, Any]] = []
    for raw_label, canonical_label in LABELS.items():
        pool: dict[str, list[Path]] = {name: [] for name in PARTITIONS}
        paths = sorted(annotation_root.rglob(f"*_{raw_label}.png"))
        for mask_path in paths:
            stem = mask_path.name.removesuffix(f"_{raw_label}.png")
            source_image_id = f"celebamask_{int(stem):05d}"
            pool[_partition(source_image_id)].append(mask_path)
        for partition in PARTITIONS:
            ranked = sorted(
                pool[partition],
                key=lambda path: canonical_sha256(
                    {
                        "source_image_id": (
                            f"celebamask_{int(path.name.removesuffix(f'_{raw_label}.png')):05d}"
                        ),
                        "mask_relative_path": path.relative_to(root).as_posix(),
                    }
                ),
            )
            if len(ranked) < per_label_partition:
                raise CelebAMaskControlCandidateError(
                    f"insufficient candidates:{canonical_label}:{partition}"
                )
            accepted = 0
            for mask_path in ranked:
                record = _candidate(
                    root=root,
                    mask_path=mask_path,
                    raw_label=raw_label,
                    canonical_label=canonical_label,
                )
                if record is None:
                    continue
                record["source_sha256"] = sha256_file(root / record["source_relative_path"])
                record["mask_sha256"] = sha256_file(root / record["mask_relative_path"])
                selected.append(record)
                accepted += 1
                if accepted == per_label_partition:
                    break
            if accepted != per_label_partition:
                raise CelebAMaskControlCandidateError(
                    f"insufficient valid candidates:{canonical_label}:{partition}"
                )
    selected.sort(
        key=lambda item: (
            item["assigned_partition"],
            item["canonical_label"],
            item["sample_id"],
        )
    )
    by_label = Counter(item["canonical_label"] for item in selected)
    by_partition = Counter(item["assigned_partition"] for item in selected)
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "celebamask_exact_direct_label_control_candidates",
        "input_bindings": {
            "provenance_sha256": sha256_file(provenance_path),
            "remap_sha256": sha256_file(remap_path),
            "source_url": policy["source_url"],
            "license_status": policy["license_status"],
            "use_profile_id": policy["use_profile_id"],
        },
        "selection_policy": {
            "labels": LABELS,
            "partitions": list(PARTITIONS),
            "per_label_partition": per_label_partition,
            "same_source_partition_function": "sha256(source_image_id)_u32_mod_2",
            "source_image_disjoint_across_partitions": True,
            "identity_disjointness_proven": False,
        },
        "selected_count": len(selected),
        "selected_by_label": dict(sorted(by_label.items())),
        "selected_by_partition": dict(sorted(by_partition.items())),
        "selected": selected,
        "authority_claimed": False,
        "critic_control_authority_granted": False,
        "gold_or_production_authority_granted": False,
        "claim_limits": [
            "candidate selection only",
            "individual exact-record visual alignment remains required",
            "identity-disjointness is not established",
            "external labels remain non-gold weighted supervision",
            "no certificate or production authority",
        ],
        "next_required_stage": (
            "materialize complete per-record panels and perform exact-record "
            "semantic/alignment qualification"
        ),
    }
    document["self_sha256"] = canonical_sha256(document)
    return document


def verify_celebamask_control_candidates(document: Mapping[str, Any]) -> None:
    """Verify self binding, partition integrity, and authority limits."""

    payload = {key: value for key, value in document.items() if key != "self_sha256"}
    if document.get("self_sha256") != canonical_sha256(payload):
        raise CelebAMaskControlCandidateError("candidate self hash mismatch")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise CelebAMaskControlCandidateError("candidate schema mismatch")
    if (
        document.get("authority_claimed") is not False
        or document.get("critic_control_authority_granted") is not False
        or document.get("gold_or_production_authority_granted") is not False
    ):
        raise CelebAMaskControlCandidateError("candidate authority was upgraded")
    records = document.get("selected")
    if not isinstance(records, list) or document.get("selected_count") != len(records):
        raise CelebAMaskControlCandidateError("candidate count mismatch")
    source_partitions: dict[str, str] = {}
    for record in records:
        source_id = record.get("source_image_id")
        partition = record.get("assigned_partition")
        prior = source_partitions.setdefault(source_id, partition)
        if prior != partition:
            raise CelebAMaskControlCandidateError("source crossed partitions")
        if (
            record.get("critic_control_eligible") is not False
            or record.get("gold_or_production_authority") is not False
        ):
            raise CelebAMaskControlCandidateError("record authority was upgraded")
