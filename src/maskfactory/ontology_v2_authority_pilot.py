"""Build and verify the governed real-image ontology-v2 authority pilot.

Selection is useful evidence, but it is not semantic or mask authority.  The
manifest therefore keeps requested coverage separate from states that current
source evidence can actually resolve.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .authority.operational_certificate import canonical_decoded_raster_sha256
from .nude_corpus_intake import (
    ADOPTED_RECORD_COUNT,
    ADOPTED_REGISTRY_SHA256,
    ADOPTED_SHARD_INDEX_SHA256,
    load_adopted_intake,
    load_records,
    sha256_file,
)
from .ontology_v2_inactive_gates import (
    PILOT_IMAGE_MAX,
    PILOT_IMAGE_MIN,
    REQUIRED_PILOT_STATES,
    appended_v2_part_names,
)

SCHEMA_VERSION = "maskfactory.ontology_v2_authority_pilot.v2"
AUTHORITY = "real_image_pilot_selection_no_mask_truth_or_gold_authority"
WAREHOUSE_SOURCE_KIND = "maskedwarehouse_external_candidate"
REFERENCE_SOURCE_KIND = "reference_library_coverage"
REFERENCE_BUCKETS = (
    "clothed__one",
    "nude__one",
    "mixed__two",
    "underwear_swimwear__one",
)
CURRENT_STATES = frozenset(REQUIRED_PILOT_STATES)


class OntologyV2AuthorityPilotError(ValueError):
    """The real-image pilot selection or evidence failed closed."""


def canonical_sha256(document: Mapping[str, Any]) -> str:
    payload = dict(document)
    payload.pop("self_sha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _decoded_source(path: Path) -> tuple[str, int, int]:
    try:
        with Image.open(path) as image:
            rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    except (OSError, ValueError) as exc:
        raise OntologyV2AuthorityPilotError(f"source_decode_failed:{path}") from exc
    return (
        canonical_decoded_raster_sha256(rgb, channel_layout="RGB"),
        int(rgb.shape[1]),
        int(rgb.shape[0]),
    )


def _observations(row: Mapping[str, Any]) -> dict[str, tuple[str, str]]:
    """Return only states justified by raw external annotation semantics."""

    observed: dict[str, tuple[str, str]] = {}
    for mask in row.get("masks", ()):
        label = mask.get("candidate_label")
        kind = mask.get("candidate_kind")
        raw = str(mask.get("raw_label", "")).casefold()
        if label == "anus" and kind == "anatomy":
            observed["anus"] = ("visible", "exact_external_polygon_label")
        elif label == "vulva_external_region" and (
            kind == "source_alias_for_visible_external_anatomy" or raw in {"vagina", "vulva"}
        ):
            observed["vulva"] = ("visible", "visible_external_anatomy_alias_polygon")
        elif label == "nipple":
            for target in ("left_nipple", "right_nipple"):
                observed[target] = (
                    "ambiguous_do_not_use",
                    "unsided_external_nipple_polygon_cannot_invent_laterality",
                )
        elif label in {"penis", "male_genital_region"}:
            for target in ("penis_shaft", "glans_penis"):
                observed[target] = (
                    "ambiguous_do_not_use",
                    "coarse_external_penis_polygon_cannot_invent_subpart",
                )
        if label in {"scrotum_or_testicular_region", "male_genital_region"}:
            for target in ("left_scrotal_region", "right_scrotal_region"):
                observed[target] = (
                    "ambiguous_do_not_use",
                    "coarse_external_scrotal_region_cannot_invent_laterality",
                )
        if label == "breast_region":
            for target in ("left_areola", "right_areola"):
                observed[target] = (
                    "ambiguous_do_not_use",
                    "coarse_external_breast_polygon_cannot_invent_areola_or_laterality",
                )
    return observed


def _select_warehouse_rows(
    records: Mapping[str, Mapping[str, Any]],
    hard_qc_rows: Iterable[Mapping[str, Any]],
    *,
    count: int,
) -> list[tuple[Mapping[str, Any], Mapping[str, Any], dict[str, tuple[str, str]]]]:
    candidates = []
    for hard_qc in hard_qc_rows:
        if hard_qc.get("outcome") != "hard_qc_pass_candidate":
            continue
        source = records.get(str(hard_qc.get("sample_id")))
        if (
            source is None
            or source.get("source_role") != "polygon_external_supervision"
            or source.get("media_domain") == "synthetic_or_generated"
        ):
            continue
        observed = _observations(hard_qc)
        if observed:
            candidates.append((source, hard_qc, observed))
    candidates.sort(
        key=lambda item: (
            -len(item[2]),
            str(item[0].get("dataset_id")),
            str(item[0].get("source_sha256")),
        )
    )
    selected = []
    groups: set[str] = set()
    datasets: Counter[str] = Counter()
    while len(selected) < count:
        remaining = [
            item
            for item in candidates
            if str(item[0].get("split_group_id") or item[1].get("split_group_id")) not in groups
            and datasets[str(item[0].get("dataset_id"))] < 8
        ]
        if not remaining:
            break
        covered = {name for _, _, observations in selected for name in observations}
        remaining.sort(
            key=lambda item: (
                -len(set(item[2]) - covered),
                datasets[str(item[0].get("dataset_id"))],
                -len(item[2]),
                str(item[0].get("source_sha256")),
            )
        )
        chosen = remaining[0]
        selected.append(chosen)
        source, hard_qc, _ = chosen
        groups.add(str(source.get("split_group_id") or hard_qc.get("split_group_id")))
        datasets[str(source.get("dataset_id"))] += 1
    if len(selected) != count:
        raise OntologyV2AuthorityPilotError(
            f"insufficient_distinct_maskedwarehouse_candidates:{len(selected)}/{count}"
        )
    return selected


def _reference_files(root: Path) -> list[tuple[str, Path]]:
    selected = []
    for bucket in REFERENCE_BUCKETS:
        files = sorted(
            path for path in (root / "benchmark_reference" / bucket).rglob("*") if path.is_file()
        )
        if not files:
            raise OntologyV2AuthorityPilotError(f"reference_bucket_empty:{bucket}")
        selected.append((bucket, files[0]))
    return selected


def _target_matrix(rows: list[dict[str, Any]]) -> None:
    classes = appended_v2_part_names()
    combinations = [(label, state) for state in REQUIRED_PILOT_STATES for label in classes]
    supports: dict[tuple[str, str], list[int]] = {}
    for index, row in enumerate(rows):
        for label, observation in row.pop("_observations", {}).items():
            supports.setdefault((label, observation[0]), []).append(index)
    assigned = [0] * len(rows)
    for ordinal, (label, requested_state) in enumerate(combinations):
        candidates = supports.get((label, requested_state), [])
        if candidates:
            index = min(candidates, key=lambda candidate: (assigned[candidate], candidate))
        else:
            index = min(
                range(len(rows)),
                key=lambda candidate: (
                    assigned[candidate],
                    (candidate - ordinal) % len(rows),
                ),
            )
        assigned[index] += 1
        observations = rows[index].get("observed_semantics", {})
        observed = observations.get(label)
        current_state = "unreviewed_for_v2"
        evidence_basis = "qualified_autonomous_visual_resolution_pending"
        if observed and observed["state"] == requested_state:
            current_state = requested_state
            evidence_basis = observed["evidence_basis"]
        rows[index]["coverage_targets"].append(
            {
                "canonical_label": label,
                "requested_state": requested_state,
                "current_state": current_state,
                "state_evidence_basis": evidence_basis,
                "semantic_positive_authority": False,
                "qualified_visual_resolution_required": current_state == "unreviewed_for_v2",
            }
        )


def build_authority_pilot(
    *,
    intake_root: Path,
    hard_qc_records_path: Path,
    reference_root: Path,
    ontology_path: Path,
    warehouse_count: int = 20,
) -> dict[str, Any]:
    if warehouse_count + len(REFERENCE_BUCKETS) not in range(PILOT_IMAGE_MIN, PILOT_IMAGE_MAX + 1):
        raise OntologyV2AuthorityPilotError("pilot_image_count_out_of_range")
    intake = load_adopted_intake(intake_root)
    records = load_records(intake)
    with Path(hard_qc_records_path).open("r", encoding="utf-8") as handle:
        hard_qc_rows = [json.loads(line) for line in handle if line.strip()]
    selected = _select_warehouse_rows(records, hard_qc_rows, count=warehouse_count)
    rows: list[dict[str, Any]] = []
    for source, hard_qc, observations in selected:
        path = Path(str(source["source_path_readonly"]))
        encoded = sha256_file(path)
        if encoded != source["source_sha256"]:
            raise OntologyV2AuthorityPilotError(f"source_hash_drift:{source['sample_id']}")
        decoded, width, height = _decoded_source(path)
        if [width, height] != [source["width"], source["height"]]:
            raise OntologyV2AuthorityPilotError(f"source_geometry_drift:{source['sample_id']}")
        observed = {
            label: {"state": state, "evidence_basis": basis}
            for label, (state, basis) in sorted(observations.items())
        }
        rows.append(
            {
                "image_id": f"pilot_{encoded[:24]}",
                "source_kind": WAREHOUSE_SOURCE_KIND,
                "source_path": path.as_posix(),
                "runpod_path": str(source["source_path_runpod"]),
                "source_encoded_sha256": encoded,
                "source_decoded_pixel_sha256": decoded,
                "width": width,
                "height": height,
                "dataset_id": source["dataset_id"],
                "sample_id": source["sample_id"],
                "split_group_id": hard_qc["split_group_id"],
                "source_role": source["source_role"],
                "source_authority": source["authority"],
                "annotation_evidence_authority": hard_qc["external_mask_authority"],
                "mask_truth_authority": False,
                "observed_semantics": observed,
                "coverage_targets": [],
                "_observations": observations,
            }
        )
    reference_root = Path(reference_root).resolve(strict=True)
    for bucket, path in _reference_files(reference_root):
        encoded = sha256_file(path)
        decoded, width, height = _decoded_source(path)
        relative = path.relative_to(reference_root).as_posix()
        rows.append(
            {
                "image_id": f"pilot_{encoded[:24]}",
                "source_kind": REFERENCE_SOURCE_KIND,
                "source_path": path.as_posix(),
                "runpod_path": (
                    "/workspace/assets/Reference_Images/Ultimate_Masking_Reference_Images/"
                    + relative
                ),
                "source_encoded_sha256": encoded,
                "source_decoded_pixel_sha256": decoded,
                "width": width,
                "height": height,
                "dataset_id": "ultimate_masking_reference_images",
                "sample_id": None,
                "split_group_id": f"reference_{encoded}",
                "source_role": "retrieval_and_coverage_reference",
                "source_authority": "reference_only_no_mask_truth",
                "annotation_evidence_authority": "none",
                "mask_truth_authority": False,
                "retrieval_bucket_hint": bucket,
                "retrieval_hint_is_semantic_truth": False,
                "observed_semantics": {},
                "coverage_targets": [],
                "_observations": {},
            }
        )
    _target_matrix(rows)
    requested_states = sorted(
        {target["requested_state"] for row in rows for target in row["coverage_targets"]}
    )
    requested_classes = sorted(
        {target["canonical_label"] for row in rows for target in row["coverage_targets"]}
    )
    resolved_states = sorted(
        {
            target["current_state"]
            for row in rows
            for target in row["coverage_targets"]
            if target["current_state"] != "unreviewed_for_v2"
        }
    )
    core: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "ontology_v2_real_image_authority_pilot",
        "authority": AUTHORITY,
        "ontology_version": "body_parts_v2",
        "ontology_sha256": sha256_file(ontology_path),
        "active_runtime_ontology": "body_parts_v1",
        "production_activation_performed": False,
        "mandatory_human_anchor": False,
        "pilot_complete": False,
        "selection_status": "real_source_selection_complete_authority_resolution_open",
        "source_lineage": {
            "nude_registry_sha256": ADOPTED_REGISTRY_SHA256,
            "nude_shard_index_sha256": ADOPTED_SHARD_INDEX_SHA256,
            "nude_record_count": ADOPTED_RECORD_COUNT,
            "hard_qc_records_path": Path(hard_qc_records_path).as_posix(),
            "hard_qc_records_sha256": sha256_file(hard_qc_records_path),
            "reference_inventory_summary_path": (
                reference_root / "manifests" / "inventory_summary.json"
            ).as_posix(),
            "reference_inventory_summary_sha256": sha256_file(
                reference_root / "manifests" / "inventory_summary.json"
            ),
        },
        "image_count": len(rows),
        "maskedwarehouse_image_count": warehouse_count,
        "reference_image_count": len(REFERENCE_BUCKETS),
        "coverage_target_count": sum(len(row["coverage_targets"]) for row in rows),
        "requested_states": requested_states,
        "requested_appended_classes": requested_classes,
        "resolved_states": resolved_states,
        "missing_resolved_states": sorted(set(REQUIRED_PILOT_STATES) - set(resolved_states)),
        "semantic_positive_count": 0,
        "images": rows,
        "claim_limits": [
            "external polygon evidence remains machine hard-QC candidate evidence, not gold",
            "coarse or unsided source labels never create fine anatomy or laterality",
            "reference-library bucket names are retrieval hints only and grant no semantic or pixel truth",
            "coverage targets are not canonical v2 target contracts or resolved authority",
            "the pilot remains incomplete until qualified autonomous evidence resolves every required state and applicable class",
        ],
    }
    core["self_sha256"] = canonical_sha256(core)
    verify_authority_pilot(core, rehash_sources=True)
    return core


def verify_authority_pilot(
    document: Mapping[str, Any], *, rehash_sources: bool = False
) -> dict[str, Any]:
    required = {
        "schema_version",
        "artifact_type",
        "authority",
        "ontology_version",
        "ontology_sha256",
        "active_runtime_ontology",
        "production_activation_performed",
        "mandatory_human_anchor",
        "pilot_complete",
        "selection_status",
        "source_lineage",
        "image_count",
        "maskedwarehouse_image_count",
        "reference_image_count",
        "coverage_target_count",
        "requested_states",
        "requested_appended_classes",
        "resolved_states",
        "missing_resolved_states",
        "semantic_positive_count",
        "images",
        "claim_limits",
        "self_sha256",
    }
    if set(document) != required:
        raise OntologyV2AuthorityPilotError("pilot_top_level_fields_not_closed")
    if (
        document["schema_version"] != SCHEMA_VERSION
        or document["authority"] != AUTHORITY
        or document["pilot_complete"] is not False
        or document["production_activation_performed"] is not False
        or document["mandatory_human_anchor"] is not False
        or document["semantic_positive_count"] != 0
    ):
        raise OntologyV2AuthorityPilotError("pilot_authority_boundary_invalid")
    if canonical_sha256(document) != document["self_sha256"]:
        raise OntologyV2AuthorityPilotError("pilot_self_hash_mismatch")
    images = document["images"]
    if not isinstance(images, list) or not PILOT_IMAGE_MIN <= len(images) <= PILOT_IMAGE_MAX:
        raise OntologyV2AuthorityPilotError("pilot_image_count_invalid")
    ids = [row.get("image_id") for row in images]
    hashes = [row.get("source_encoded_sha256") for row in images]
    groups = [row.get("split_group_id") for row in images]
    if (
        len(ids) != len(set(ids))
        or len(hashes) != len(set(hashes))
        or len(groups) != len(set(groups))
    ):
        raise OntologyV2AuthorityPilotError("pilot_images_or_groups_not_distinct")
    requested_states: set[str] = set()
    requested_classes: set[str] = set()
    resolved_states: set[str] = set()
    for row in images:
        if row.get("source_kind") not in {WAREHOUSE_SOURCE_KIND, REFERENCE_SOURCE_KIND}:
            raise OntologyV2AuthorityPilotError("pilot_source_kind_invalid")
        if row.get("mask_truth_authority") is not False:
            raise OntologyV2AuthorityPilotError("pilot_source_promoted_to_mask_truth")
        path = Path(str(row.get("source_path")))
        if rehash_sources and (
            not path.is_file() or sha256_file(path) != row["source_encoded_sha256"]
        ):
            raise OntologyV2AuthorityPilotError(f"pilot_source_hash_mismatch:{row.get('image_id')}")
        targets = row.get("coverage_targets")
        if not isinstance(targets, list) or not targets:
            raise OntologyV2AuthorityPilotError("pilot_coverage_targets_missing")
        for target in targets:
            if set(target) != {
                "canonical_label",
                "requested_state",
                "current_state",
                "state_evidence_basis",
                "semantic_positive_authority",
                "qualified_visual_resolution_required",
            }:
                raise OntologyV2AuthorityPilotError("pilot_coverage_target_fields_not_closed")
            requested_states.add(str(target["requested_state"]))
            requested_classes.add(str(target["canonical_label"]))
            if target["current_state"] not in CURRENT_STATES:
                raise OntologyV2AuthorityPilotError("pilot_current_state_invalid")
            if target["semantic_positive_authority"] is not False:
                raise OntologyV2AuthorityPilotError("pilot_target_promoted_without_authority")
            if target["current_state"] != "unreviewed_for_v2":
                resolved_states.add(str(target["current_state"]))
                if (
                    target["state_evidence_basis"]
                    == "qualified_autonomous_visual_resolution_pending"
                ):
                    raise OntologyV2AuthorityPilotError("pilot_resolved_state_lacks_evidence")
    if requested_states != set(REQUIRED_PILOT_STATES):
        raise OntologyV2AuthorityPilotError("pilot_requested_state_coverage_incomplete")
    if requested_classes != set(appended_v2_part_names()):
        raise OntologyV2AuthorityPilotError("pilot_requested_class_coverage_incomplete")
    if sorted(resolved_states) != document["resolved_states"]:
        raise OntologyV2AuthorityPilotError("pilot_resolved_state_summary_drift")
    return {
        "status": "PASS_SELECTION_AUTHORITY_RESOLUTION_OPEN",
        "image_count": len(images),
        "coverage_target_count": sum(len(row["coverage_targets"]) for row in images),
        "requested_state_count": len(requested_states),
        "requested_class_count": len(requested_classes),
        "resolved_state_count": len(resolved_states),
        "pilot_complete": False,
    }


__all__ = [
    "AUTHORITY",
    "OntologyV2AuthorityPilotError",
    "SCHEMA_VERSION",
    "build_authority_pilot",
    "canonical_sha256",
    "verify_authority_pilot",
]
