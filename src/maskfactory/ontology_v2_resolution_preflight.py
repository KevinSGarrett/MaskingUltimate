"""Fail-closed real-source preflight for the immutable ontology-v2 workload.

This module proves only the first two workload stages: source identity and
coverage-target binding.  It deliberately cannot resolve semantics, issue a
mask, review pixels visually, or advance any authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .authority.operational_certificate import canonical_decoded_raster_sha256
from .nude_corpus_intake import sha256_file
from .ontology_v2_authority_pilot import canonical_sha256, verify_authority_pilot
from .ontology_v2_resolution_workload import verify_resolution_workload

SCHEMA_VERSION = "maskfactory.ontology_v2_resolution_preflight.v1"
AUTHORITY = "source_identity_and_coverage_target_validation_only"
STATUS = "HARD_QA_PASS_BOUNDED_PREPROPOSAL"


class OntologyV2ResolutionPreflightError(ValueError):
    """The immutable pilot or its Pod-local source binding drifted."""


def _decoded_source(path: Path) -> tuple[str, int, int]:
    try:
        with Image.open(path) as image:
            rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    except (OSError, ValueError) as exc:
        raise OntologyV2ResolutionPreflightError(f"source_decode_failed:{path}") from exc
    return (
        canonical_decoded_raster_sha256(rgb, channel_layout="RGB"),
        int(rgb.shape[1]),
        int(rgb.shape[0]),
    )


def _target_sha256(target: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(target, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _file_hash_is_valid(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def build_resolution_preflight(
    pilot: Mapping[str, Any],
    workload: Mapping[str, Any],
    *,
    pilot_file_sha256: str,
    workload_file_sha256: str,
) -> dict[str, Any]:
    """Verify Pod-local source bytes and the immutable 90-unit target binding."""

    if not _file_hash_is_valid(pilot_file_sha256):
        raise OntologyV2ResolutionPreflightError("pilot_file_sha256_invalid")
    if not _file_hash_is_valid(workload_file_sha256):
        raise OntologyV2ResolutionPreflightError("workload_file_sha256_invalid")
    verify_authority_pilot(pilot)
    verify_resolution_workload(workload, pilot=pilot)

    image_by_id = {str(image["image_id"]): image for image in pilot["images"]}
    source_rows: list[dict[str, Any]] = []
    for image_id, image in sorted(image_by_id.items()):
        runtime_path = Path(str(image.get("runpod_path") or ""))
        if not runtime_path.is_file():
            raise OntologyV2ResolutionPreflightError(f"runtime_source_missing:{image_id}")
        encoded = sha256_file(runtime_path)
        if encoded != image["source_encoded_sha256"]:
            raise OntologyV2ResolutionPreflightError(
                f"source_encoded_sha_mismatch:{image_id}"
            )
        decoded, width, height = _decoded_source(runtime_path)
        if decoded != image.get("source_decoded_pixel_sha256"):
            raise OntologyV2ResolutionPreflightError(
                f"source_decoded_sha_mismatch:{image_id}"
            )
        if [width, height] != [image.get("width"), image.get("height")]:
            raise OntologyV2ResolutionPreflightError(f"source_geometry_mismatch:{image_id}")
        source_rows.append(
            {
                "image_id": image_id,
                "runtime_path": runtime_path.as_posix(),
                "source_encoded_sha256": encoded,
                "source_decoded_pixel_sha256": decoded,
                "width": width,
                "height": height,
            }
        )

    target_rows: list[dict[str, Any]] = []
    for entry in sorted(workload["entries"], key=lambda row: int(row["ordinal"])):
        image_id = str(entry["image_id"])
        image = image_by_id.get(image_id)
        if image is None:
            raise OntologyV2ResolutionPreflightError(f"work_unit_unknown_image:{entry['work_unit_id']}")
        if entry["runpod_path"] != image.get("runpod_path"):
            raise OntologyV2ResolutionPreflightError(
                f"work_unit_runtime_path_mismatch:{entry['work_unit_id']}"
            )
        if entry["source_encoded_sha256"] != image["source_encoded_sha256"]:
            raise OntologyV2ResolutionPreflightError(
                f"work_unit_source_hash_mismatch:{entry['work_unit_id']}"
            )
        ordinal = int(entry["coverage_target_ordinal"])
        targets = image["coverage_targets"]
        if ordinal < 0 or ordinal >= len(targets):
            raise OntologyV2ResolutionPreflightError(
                f"work_unit_target_ordinal_invalid:{entry['work_unit_id']}"
            )
        expected_target = targets[ordinal]
        if entry["coverage_target"] != expected_target:
            raise OntologyV2ResolutionPreflightError(
                f"work_unit_target_content_mismatch:{entry['work_unit_id']}"
            )
        target_hash = _target_sha256(expected_target)
        if entry["coverage_target_sha256"] != target_hash:
            raise OntologyV2ResolutionPreflightError(
                f"work_unit_target_hash_mismatch:{entry['work_unit_id']}"
            )
        target_rows.append(
            {
                "work_unit_id": entry["work_unit_id"],
                "workload_ordinal": int(entry["ordinal"]),
                "coverage_target_ordinal": ordinal,
                "image_id": image_id,
                "coverage_target_sha256": target_hash,
            }
        )

    core: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "ontology_v2_resolution_preflight",
        "authority": AUTHORITY,
        "status": STATUS,
        "pilot_manifest_file_sha256": pilot_file_sha256,
        "pilot_manifest_self_sha256": pilot["self_sha256"],
        "workload_file_sha256": workload_file_sha256,
        "workload_self_sha256": workload["self_sha256"],
        "image_count": len(source_rows),
        "work_unit_count": len(target_rows),
        "source_identity_rows": source_rows,
        "coverage_target_rows": target_rows,
        "semantic_resolution_performed": False,
        "visual_review_performed": False,
        "mask_or_gold_authority": False,
        "claim_limits": [
            "Only source_identity and coverage_target_validation are evidenced.",
            "Provider proposals, owner binding, canonical targets, hard QA, visual review, repair, semantic alignment, and immutable outcomes remain pending.",
            "No semantic state, mask truth, certificate, gold, training, promotion, or production authority is granted.",
        ],
    }
    core["self_sha256"] = canonical_sha256(core)
    verify_resolution_preflight(core, pilot=pilot, workload=workload)
    return core


def verify_resolution_preflight(
    document: Mapping[str, Any],
    *,
    pilot: Mapping[str, Any],
    workload: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify a completed preproposal receipt without re-reading image bytes."""

    required = {
        "schema_version",
        "artifact_type",
        "authority",
        "status",
        "pilot_manifest_file_sha256",
        "pilot_manifest_self_sha256",
        "workload_file_sha256",
        "workload_self_sha256",
        "image_count",
        "work_unit_count",
        "source_identity_rows",
        "coverage_target_rows",
        "semantic_resolution_performed",
        "visual_review_performed",
        "mask_or_gold_authority",
        "claim_limits",
        "self_sha256",
    }
    if set(document) != required:
        raise OntologyV2ResolutionPreflightError("preflight_fields_not_closed")
    if (
        document["schema_version"] != SCHEMA_VERSION
        or document["artifact_type"] != "ontology_v2_resolution_preflight"
        or document["authority"] != AUTHORITY
        or document["status"] != STATUS
        or document["semantic_resolution_performed"] is not False
        or document["visual_review_performed"] is not False
        or document["mask_or_gold_authority"] is not False
        or canonical_sha256(document) != document["self_sha256"]
    ):
        raise OntologyV2ResolutionPreflightError("preflight_authority_or_hash_invalid")
    verify_authority_pilot(pilot)
    verify_resolution_workload(workload, pilot=pilot)
    if (
        document["pilot_manifest_self_sha256"] != pilot["self_sha256"]
        or document["workload_self_sha256"] != workload["self_sha256"]
        or document["image_count"] != pilot["image_count"]
        or document["work_unit_count"] != workload["work_unit_count"]
    ):
        raise OntologyV2ResolutionPreflightError("preflight_input_binding_mismatch")
    if len(document["source_identity_rows"]) != pilot["image_count"]:
        raise OntologyV2ResolutionPreflightError("preflight_source_count_invalid")
    if len(document["coverage_target_rows"]) != workload["work_unit_count"]:
        raise OntologyV2ResolutionPreflightError("preflight_target_count_invalid")
    expected_source_rows = [
        {
            "image_id": image_id,
            "runtime_path": Path(str(image["runpod_path"])).as_posix(),
            "source_encoded_sha256": image["source_encoded_sha256"],
            "source_decoded_pixel_sha256": image["source_decoded_pixel_sha256"],
            "width": image["width"],
            "height": image["height"],
        }
        for image_id, image in sorted(
            ((str(image["image_id"]), image) for image in pilot["images"]),
            key=lambda item: item[0],
        )
    ]
    if document["source_identity_rows"] != expected_source_rows:
        raise OntologyV2ResolutionPreflightError("preflight_source_rows_mismatch")
    expected_target_rows = [
        {
            "work_unit_id": entry["work_unit_id"],
            "workload_ordinal": int(entry["ordinal"]),
            "coverage_target_ordinal": int(entry["coverage_target_ordinal"]),
            "image_id": str(entry["image_id"]),
            "coverage_target_sha256": entry["coverage_target_sha256"],
        }
        for entry in sorted(workload["entries"], key=lambda row: int(row["ordinal"]))
    ]
    if document["coverage_target_rows"] != expected_target_rows:
        raise OntologyV2ResolutionPreflightError("preflight_target_rows_mismatch")
    return {
        "status": STATUS,
        "image_count": document["image_count"],
        "work_unit_count": document["work_unit_count"],
        "semantic_resolution_performed": False,
        "visual_review_performed": False,
    }


__all__ = [
    "AUTHORITY",
    "OntologyV2ResolutionPreflightError",
    "SCHEMA_VERSION",
    "STATUS",
    "build_resolution_preflight",
    "verify_resolution_preflight",
]
