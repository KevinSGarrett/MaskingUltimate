"""Bounded runtime: Mode A package-QC + contact gates on real LV-MHP groups.

Advances the duo Mode A package-QC climb
(``tools/run_local_multi_person_mode_a_slice.py``) by driving the same real
``evaluate_mode_a_package_read`` ownership path across **multi-body groups** of
2, 3, and 4 people from MaskedWarehouse LV-MHP-v1, while also exercising the
full pairwise contact/exclusivity matrix via
``evaluate_multi_person_candidate_gate`` (QC-035/036, AUT-MP-001/002/003) under
``duo`` and ``small_group`` contexts.

Per selected group:
  * Materializes one Mode A package per promoted instance from the real
    per-person annotation PNG + real source raster (never fabricated masks).
  * Requires every instance Mode A read to accept with distinct package ids and
    a passing transform round-trip.
  * Runs the live multi-person gate on real contact-band geometry.
  * Seeds wrong-person and cross-instance Mode A faults and requires fail-closed
    ``wrong_owner`` / ``instance_mismatch`` refusals.
  * Seeds exclusivity / bleed / contact-nonreciprocity gate faults on real
    multi-body pixels and requires the hard blockers to fire.

Honest boundary (RUNTIME_PASS_BOUNDED, never inflated):
  * External-supervision LV-MHP-v1 only — not Kevin-governed demo sources.
  * Fixture-authority package wrapper/transform contract only; does NOT satisfy
    MF-P6-12.02/12.03, MF-P8-11.07, gold, doctor-green, champions, or
    PRODUCTION_EVIDENCE_PASS.
  * No independent real-accuracy claim (masks are the supervision annotations).
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage

from maskfactory.autonomy.gold_volume_sources import default_maskedwarehouse_lv_mhp_root
from maskfactory.autonomy.multi_person_gate import evaluate_multi_person_candidate_gate
from maskfactory.bridge.mode_a_package_read import evaluate_mode_a_package_read
from maskfactory.bridge.transforms import execute_box
from maskfactory.io.png_strict import write_binary_mask
from maskfactory.qa.multi_instance import MultiInstanceQcInputs
from maskfactory.validation import canonical_document_sha256, canonical_json_bytes

ANNOTATION_PATTERN = re.compile(r"^(?P<image>\d+)_(?P<count>\d+)_(?P<instance>\d+)\.png$")
PROOF_TIER = "RUNTIME_PASS_BOUNDED"
ARTIFACT_TYPE = "local_multi_person_mode_a_group_slice_report"
AUTHORITY = (
    "local_external_supervision_lv_mhp_multi_body_mode_a_package_qc_contact_"
    "runtime_only_fixture_authority_no_kevin_governed_demo_gold_champions_or_"
    "production_authority"
)
SCHEMA_VERSION = "1.0.0"
CONTACT_DILATION_ITERATIONS = 5
DEFAULT_SIZES = (2, 3, 4)
DEFAULT_LIMIT_PER_SIZE = 8
_LABEL = "torso"
_ONTOLOGY = b"ontology-body-parts-v1-lvmhp-group"
_RELEASE = b"release-lvmhp-group-fixture-v1"
_CAPABILITY = b"capability-lvmhp-group-fixture-v1"
_DECIDED_AT_DEFAULT = "2026-07-20T00:00:00Z"
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_doc(document: dict[str, Any]) -> str:
    return _sha_bytes(canonical_json_bytes(document))


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _name(index: int) -> str:
    return f"p{index}"


def _char_revision(index: int) -> str:
    return f"char-rev-lvmhp-p{index}-v1"


def _load_silhouette(path: Path) -> np.ndarray:
    with Image.open(path) as handle:
        array = np.array(handle)
    if array.ndim == 3:
        array = array[..., :3].any(axis=2).astype(np.uint8)
    return array > 0


def _resolve_content_root(source_root: Path) -> Path:
    root = Path(source_root).resolve(strict=True)
    nested = root / "LV-MHP-v1"
    return nested if nested.is_dir() else root


def _has_any_contact(paths: list[Path]) -> bool:
    masks = [_load_silhouette(path) for path in paths]
    dilated = [
        ndimage.binary_dilation(mask, iterations=CONTACT_DILATION_ITERATIONS) for mask in masks
    ]
    for i, j in itertools.combinations(range(len(masks)), 2):
        if (dilated[i] & masks[j]).any() and (dilated[j] & masks[i]).any():
            return True
    return False


def _select_groups(
    annotations_root: Path,
    sizes: tuple[int, ...],
    limit_per_size: int,
    *,
    prefer_contact: bool = True,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[int, Path]] = {}
    declared_counts: dict[str, set[int]] = {}
    for path in sorted(annotations_root.iterdir(), key=lambda item: item.name):
        if not path.is_file():
            continue
        match = ANNOTATION_PATTERN.fullmatch(path.name)
        if match is None:
            continue
        image_id = match.group("image")
        declared_counts.setdefault(image_id, set()).add(int(match.group("count")))
        grouped.setdefault(image_id, {})[int(match.group("instance"))] = path

    # Bound contact probes so warehouse-scale annotation trees stay practical.
    contact_probe_budget = max(limit_per_size * 12, limit_per_size)

    selected: list[dict[str, Any]] = []
    for size in sizes:
        contact_taken: list[dict[str, Any]] = []
        noncontact_taken: list[dict[str, Any]] = []
        probed = 0
        for image_id in sorted(grouped, key=lambda value: value.encode("ascii")):
            counts = declared_counts[image_id]
            instances = grouped[image_id]
            if counts != {size} or set(instances) != set(range(1, size + 1)):
                continue
            candidate = {
                "image_id": image_id,
                "size": size,
                "paths": [instances[rank] for rank in range(1, size + 1)],
            }
            if not prefer_contact:
                contact_taken.append(candidate)
                if len(contact_taken) >= limit_per_size:
                    break
                continue

            if len(contact_taken) >= limit_per_size:
                break
            if probed < contact_probe_budget:
                probed += 1
                if _has_any_contact(candidate["paths"]):
                    contact_taken.append(candidate)
                elif len(noncontact_taken) < limit_per_size:
                    noncontact_taken.append(candidate)
            elif len(noncontact_taken) < limit_per_size:
                noncontact_taken.append(candidate)

        taken = contact_taken[:limit_per_size]
        if len(taken) < limit_per_size:
            needed = limit_per_size - len(taken)
            taken.extend(noncontact_taken[:needed])
        selected.extend(taken)
    return selected


def _find_image(images_root: Path, image_id: str) -> Path | None:
    for extension in _IMAGE_EXTENSIONS:
        candidate = images_root / f"{image_id}{extension}"
        if candidate.is_file():
            return candidate
    return None


def _step(
    sequence: int,
    operation: str,
    source: dict[str, Any],
    output: dict[str, Any],
    parameters: dict[str, Any],
) -> dict[str, Any]:
    step = {
        "sequence": sequence,
        "operation": operation,
        "input": source,
        "output": output,
        "parameters": parameters,
        "inverse_strategy": "exact_inverse",
        "step_sha256": "",
    }
    step["step_sha256"] = canonical_document_sha256(
        step, excluded_top_level_fields=("step_sha256",)
    )
    return step


def _transform_chain(image_id: str, person_index: int, width: int, height: int) -> dict[str, Any]:
    source = {"coordinate_space": "source_pixel", "width": width, "height": height}
    crop_width, crop_height = width - 2, height - 2
    crop = {"coordinate_space": "crop_pixel", "width": crop_width, "height": crop_height}
    steps = [
        _step(
            0,
            "crop",
            source,
            crop,
            {
                "parameter_type": "crop",
                "x": 0,
                "y": 0,
                "width": crop_width,
                "height": crop_height,
            },
        )
    ]
    chain = {
        "chain_id": f"lvmhp-group-crop-{image_id}-p{person_index}-v1",
        "chain_sha256": "",
        "source": source,
        "output": crop,
        "steps": steps,
        "roundtrip_policy": {
            "required": True,
            "maximum_error_px": 0.0,
            "reject_noninvertible": True,
        },
    }
    chain["chain_sha256"] = canonical_document_sha256(
        chain, excluded_top_level_fields=("chain_sha256",)
    )
    return chain


def _instance_anchor(mask: np.ndarray) -> tuple[int, int]:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return 0, 0
    return int(round(float(xs.mean()))), int(round(float(ys.mean())))


def _protected_region(
    *,
    person_index: int,
    owner_id: str,
    scene_instance_id: str,
    character_revision: str,
    chain: dict[str, Any],
    mask: np.ndarray,
    width: int,
    height: int,
) -> dict[str, Any]:
    box_size = 12
    max_x = max(0, (width - 3) - box_size)
    max_y = max(0, (height - 3) - box_size)
    anchor_x, anchor_y = _instance_anchor(mask)
    x0 = float(min(max(anchor_x - box_size // 2, 0), max_x))
    y0 = float(min(max(anchor_y - box_size // 2, 0), max_y))
    box = {
        "x0": x0,
        "y0": y0,
        "x1": x0 + box_size,
        "y1": y0 + box_size,
        "coordinate_space": "source_pixel",
    }
    expected_box = execute_box(chain, box)
    owner = {
        "canonical_person_id": owner_id,
        "scene_instance_id": scene_instance_id,
        "character_revision": character_revision,
        "person_index": person_index,
    }
    return {
        "region_id": f"prot-{scene_instance_id}-face",
        "owner": owner,
        "box": box,
        "expected_box": expected_box,
        "probe": {
            "x": min(max(float(anchor_x), 0.0), float(width - 3)),
            "y": min(max(float(anchor_y), 0.0), float(height - 3)),
            "coordinate_space": "source_pixel",
        },
    }


def _revocation(token: str = "g") -> bytes:
    record = {
        "event_payload_sha256": token * 64,
        "trust_binding": {"key_role": "producer_journal"},
        "signature": {"signed_payload_sha256": token * 64},
    }
    return json.dumps(record, separators=(",", ":")).encode("utf-8")


def _build_person_package(
    *,
    image_id: str,
    person_index: int,
    mask: np.ndarray,
    source_encoded: bytes,
    source_pixels: bytes,
    workdir: Path,
) -> dict[str, Any]:
    height, width = int(mask.shape[0]), int(mask.shape[1])
    instance_id = _name(person_index)
    owner_id = f"person-{person_index}"
    scene_instance_id = f"scene-{image_id}-{instance_id}"
    character_revision = _char_revision(person_index)
    character_instance_id = f"char-inst-{character_revision}"
    package_id = f"pkg-lvmhp-{image_id}-{instance_id}"

    mask_path = write_binary_mask(workdir / f"ownership_{image_id}_{instance_id}.png", mask)
    mask_encoded = mask_path.read_bytes()
    mask_pixels = (mask.astype(np.uint8) * 255).tobytes()

    chain = _transform_chain(image_id, person_index, width, height)
    protected = _protected_region(
        person_index=person_index,
        owner_id=owner_id,
        scene_instance_id=scene_instance_id,
        character_revision=character_revision,
        chain=chain,
        mask=mask,
        width=width,
        height=height,
    )

    manifest = json.dumps(
        {
            "image_id": image_id,
            "person_index": person_index,
            "parts": {_LABEL: {"status": "human_approved_gold"}},
            "ownership_mask_sha256": _sha_bytes(mask_encoded),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    package_material = {
        "source_encoded_sha256": _sha_bytes(source_encoded),
        "source_decoded_pixel_sha256": _sha_bytes(source_pixels),
        "mask_encoded_sha256": _sha_bytes(mask_encoded),
        "mask_decoded_sha256": _sha_bytes(mask_pixels),
        "manifest_sha256": _sha_bytes(manifest),
        "ontology_sha256": _sha_bytes(_ONTOLOGY),
        "image_id": image_id,
        "person_index": person_index,
        "label": _LABEL,
    }
    package_sha256 = canonical_document_sha256(package_material)

    entry = {
        "image_id": image_id,
        "person_index": person_index,
        "label": _LABEL,
        "package_id": package_id,
        "package_revision": "rev-lvmhp-group-1",
        "artifact_id": f"artifact-{image_id}-{instance_id}-{_LABEL}",
        "owner_id": owner_id,
        "scene_instance_id": scene_instance_id,
        "character_revision": character_revision,
        "character_instance_id": character_instance_id,
        "raw_part_status": "human_approved_gold",
        "ontology_version": "body_parts_v1",
        "ontology_sha256": _sha_bytes(_ONTOLOGY),
        "source_encoded_sha256": package_material["source_encoded_sha256"],
        "source_decoded_pixel_sha256": package_material["source_decoded_pixel_sha256"],
        "mask_encoded_sha256": package_material["mask_encoded_sha256"],
        "mask_decoded_sha256": package_material["mask_decoded_sha256"],
        "manifest_sha256": package_material["manifest_sha256"],
        "package_sha256": package_sha256,
        "transform_chain_sha256": chain["chain_sha256"],
        "ownership_mask_sha256": package_material["mask_encoded_sha256"],
        "protected_region_id": protected["region_id"],
    }

    request = {
        "image_id": image_id,
        "person_index": person_index,
        "label": _LABEL,
        "exact_use_scope": "diagnostic",
        "artifact_kind": "atomic",
        "ontology_version": "body_parts_v1",
        "raw_part_status": "human_approved_gold",
        "subject": {
            "canonical_person_id": owner_id,
            "scene_instance_id": scene_instance_id,
            "character_revision": character_revision,
        },
        "transform_chain": chain,
        "transform_probes": [protected["probe"]],
        "protected_regions": [
            {
                "region_id": protected["region_id"],
                "owner": protected["owner"],
                "box": protected["box"],
            }
        ],
        "expected_protected_regions": [
            {
                "region_id": protected["region_id"],
                "owner": protected["owner"],
                "box": protected["expected_box"],
            }
        ],
    }
    evidence = {
        "catalog": {
            "adoption_decision": "adopted",
            "release_status": "adopted",
            "release_payload_sha256": _sha_bytes(_RELEASE),
            "capability_snapshot_sha256": _sha_bytes(_CAPABILITY),
            "packages": [entry],
        },
        "package_root": str(workdir.resolve()),
        "relative_paths": {
            "source": f"source_{image_id}.bin",
            "mask": f"ownership_{image_id}_{instance_id}.png",
            "manifest": f"manifest_{image_id}_{instance_id}.json",
        },
        "bytes": {
            "source_encoded": source_encoded,
            "source_decoded_pixels": source_pixels,
            "mask_encoded": mask_encoded,
            "mask_decoded_pixels": mask_pixels,
            "manifest": manifest,
            "ontology": _ONTOLOGY,
            "release": _RELEASE,
            "capability": _CAPABILITY,
            "revocation_identity": _revocation(),
        },
        "wrapper": None,
    }
    (workdir / f"manifest_{image_id}_{instance_id}.json").write_bytes(manifest)
    (workdir / f"source_{image_id}.bin").write_bytes(source_encoded)
    return {
        "instance_id": instance_id,
        "owner_id": owner_id,
        "scene_instance_id": scene_instance_id,
        "character_revision": character_revision,
        "character_instance_id": character_instance_id,
        "package_id": package_id,
        "ownership_mask_sha256": package_material["mask_encoded_sha256"],
        "transform_chain_sha256": chain["chain_sha256"],
        "request": request,
        "evidence": evidence,
    }


def _summarize_read(decision: dict[str, Any]) -> dict[str, Any]:
    observed = decision.get("observed") if isinstance(decision.get("observed"), dict) else {}
    handles = (
        decision.get("immutable_handles")
        if isinstance(decision.get("immutable_handles"), dict)
        else {}
    )
    return {
        "status": decision["status"],
        "owner_id": observed.get("owner_id"),
        "scene_instance_id": observed.get("scene_instance_id"),
        "package_id": handles.get("package_id"),
        "transform_roundtrip_passed": observed.get("transform_roundtrip_passed"),
        "decision_sha256": decision["decision_sha256"],
        "rejection_reasons": list(decision.get("rejection_reasons") or ()),
    }


def _gate(
    silhouettes: dict[str, np.ndarray],
    atomics: dict[str, np.ndarray],
    contact_bands: dict[tuple[str, str], np.ndarray],
    recorded: dict[str, frozenset[str]],
    relationships: dict[tuple[str, str], str],
    *,
    size: int,
):
    inputs = MultiInstanceQcInputs(
        silhouettes=silhouettes,
        atomic_unions=atomics,
        contact_bands=contact_bands,
        recorded_relationships=recorded,
        expected_promoted_count=size,
    )
    return evaluate_multi_person_candidate_gate(
        inputs,
        instance_context="duo" if size == 2 else "small_group",
        promoted_instances=tuple(_name(index) for index in range(size)),
        relationships=relationships,
    )


def _clean_relationship_geometry(
    masks: list[np.ndarray],
) -> tuple[
    dict[tuple[str, str], np.ndarray],
    dict[str, frozenset[str]],
    dict[tuple[str, str], str],
    list[dict[str, Any]],
]:
    size = len(masks)
    dilated = [
        ndimage.binary_dilation(mask, iterations=CONTACT_DILATION_ITERATIONS) for mask in masks
    ]
    contact_bands: dict[tuple[str, str], np.ndarray] = {}
    neighbors: dict[str, set[str]] = {_name(index): set() for index in range(size)}
    relationships: dict[tuple[str, str], str] = {}
    pair_metrics: list[dict[str, Any]] = []
    for i, j in itertools.combinations(range(size), 2):
        band_ij = dilated[i] & masks[j]
        band_ji = dilated[j] & masks[i]
        contact = bool(band_ij.any() and band_ji.any())
        intersection = int(np.count_nonzero(masks[i] & masks[j]))
        union = int(np.count_nonzero(masks[i] | masks[j]))
        pair_metrics.append(
            {
                "pair": f"{_name(i)}:{_name(j)}",
                "raw_intersection_px": intersection,
                "raw_iou": round(intersection / union, 6) if union else 0.0,
                "contact": contact,
                "band_px": {
                    f"{_name(i)}->{_name(j)}": int(band_ij.sum()),
                    f"{_name(j)}->{_name(i)}": int(band_ji.sum()),
                },
            }
        )
        if contact:
            contact_bands[(_name(i), _name(j))] = band_ij
            contact_bands[(_name(j), _name(i))] = band_ji
            neighbors[_name(i)].add(_name(j))
            neighbors[_name(j)].add(_name(i))
            relationships[(_name(i), _name(j))] = "contact"
            relationships[(_name(j), _name(i))] = "contact"
    recorded = {name: frozenset(values) for name, values in neighbors.items()}
    return contact_bands, recorded, relationships, pair_metrics


def _process_group(
    group: dict[str, Any], images_root: Path, workdir: Path, decided_at: str
) -> dict[str, Any]:
    size = group["size"]
    paths: list[Path] = group["paths"]
    masks = [_load_silhouette(path) for path in paths]
    shape = masks[0].shape
    if any(mask.shape != shape for mask in masks):
        return {
            "image_id": group["image_id"],
            "size": size,
            "status": "skipped_shape_mismatch",
            "shapes": [list(mask.shape) for mask in masks],
        }

    image_path = _find_image(images_root, group["image_id"])
    if image_path is None:
        return {
            "image_id": group["image_id"],
            "size": size,
            "status": "skipped_missing_image",
        }

    source_encoded = image_path.read_bytes()
    with Image.open(image_path) as handle:
        source_pixels = np.asarray(handle.convert("RGB")).tobytes()

    packages = {
        _name(index): _build_person_package(
            image_id=group["image_id"],
            person_index=index,
            mask=masks[index],
            source_encoded=source_encoded,
            source_pixels=source_pixels,
            workdir=workdir,
        )
        for index in range(size)
    }

    reads = {
        key: _summarize_read(
            evaluate_mode_a_package_read(
                packages[key]["request"], packages[key]["evidence"], decided_at=decided_at
            )
        )
        for key in packages
    }
    package_ids = {reads[key]["package_id"] for key in packages}
    all_accepted = all(reads[key]["status"] == "accepted" for key in packages)
    distinct_package_ids = None not in package_ids and len(package_ids) == size
    roundtrips_ok = all(reads[key]["transform_roundtrip_passed"] is True for key in packages)

    silhouettes = {_name(index): masks[index] for index in range(size)}
    atomics = {_name(index): masks[index].copy() for index in range(size)}
    contact_bands, recorded, relationships, pair_metrics = _clean_relationship_geometry(masks)
    contact_pairs = [metric["pair"] for metric in pair_metrics if metric["contact"]]
    gate = _gate(silhouettes, atomics, contact_bands, recorded, relationships, size=size)

    # Mode A seeded fail-closed faults (wrong person + cross instance).
    wrong_bundle = copy.deepcopy(packages[_name(0)])
    wrong_bundle["request"]["subject"]["canonical_person_id"] = "person-1"
    wrong_decision = evaluate_mode_a_package_read(
        wrong_bundle["request"], wrong_bundle["evidence"], decided_at=decided_at
    )
    wrong_reasons = list(wrong_decision.get("rejection_reasons") or ())
    wrong_rejected = wrong_decision.get("status") == "rejected" and "wrong_owner" in wrong_reasons

    cross_bundle = copy.deepcopy(packages[_name(0)])
    cross_bundle["request"]["subject"]["scene_instance_id"] = packages[_name(1)]["scene_instance_id"]
    cross_decision = evaluate_mode_a_package_read(
        cross_bundle["request"], cross_bundle["evidence"], decided_at=decided_at
    )
    cross_reasons = list(cross_decision.get("rejection_reasons") or ())
    cross_rejected = (
        cross_decision.get("status") == "rejected" and "instance_mismatch" in cross_reasons
    )

    # Gate seeded faults on real multi-body pixels.
    gate_seeded: dict[str, dict[str, Any]] = {}
    overlap_sil = dict(silhouettes)
    overlap_sil[_name(1)] = masks[0].copy()
    overlap_atomic = {name: value.copy() for name, value in overlap_sil.items()}
    empty_recorded = {_name(index): frozenset() for index in range(size)}
    overlap = _gate(overlap_sil, overlap_atomic, {}, empty_recorded, {}, size=size)
    gate_seeded["exclusivity_overlap"] = {
        "injected": True,
        "blocked": "QC-035" in overlap.blockers,
        "blockers": list(overlap.blockers),
    }

    bleed_atomics = {name: value.copy() for name, value in atomics.items()}
    bleed_atomics[_name(0)] = masks[0] | masks[1]
    bleed = _gate(silhouettes, bleed_atomics, contact_bands, recorded, relationships, size=size)
    gate_seeded["cross_instance_bleed"] = {
        "injected": True,
        "blocked": "QC-036" in bleed.blockers,
        "containment_also_blocked": "AUT-MP-001" in bleed.blockers,
        "blockers": list(bleed.blockers),
    }

    if contact_pairs:
        first = next(pair for pair in relationships if relationships[pair] == "contact")
        broken = {
            pair: kind for pair, kind in relationships.items() if pair != (first[1], first[0])
        }
        one_way = _gate(silhouettes, atomics, contact_bands, recorded, broken, size=size)
        gate_seeded["contact_nonreciprocity"] = {
            "injected": True,
            "blocked": "AUT-MP-002" in one_way.blockers,
            "blockers": list(one_way.blockers),
        }

    ownership_hashes = {
        _name(index): packages[_name(index)]["ownership_mask_sha256"] for index in range(size)
    }
    distinct_ownership = len(set(ownership_hashes.values())) == size
    reciprocal_ok = (not contact_pairs) or (gate.passed and "AUT-MP-002" not in gate.blockers)
    bounded_ownership_integrity = (
        gate.passed
        and "QC-035" not in gate.blockers
        and "QC-036" not in gate.blockers
        and distinct_ownership
        and reciprocal_ok
        and all_accepted
        and distinct_package_ids
    )
    gate_faults_ok = (
        gate_seeded["exclusivity_overlap"]["blocked"]
        and gate_seeded["cross_instance_bleed"]["blocked"]
        and gate_seeded["cross_instance_bleed"]["containment_also_blocked"]
        and (
            "contact_nonreciprocity" not in gate_seeded
            or gate_seeded["contact_nonreciprocity"]["blocked"]
        )
    )
    group_pass = (
        all_accepted
        and distinct_package_ids
        and roundtrips_ok
        and gate.passed
        and wrong_rejected
        and cross_rejected
        and bounded_ownership_integrity
        and gate_faults_ok
    )

    return {
        "image_id": group["image_id"],
        "size": size,
        "status": "processed",
        "group_pass": group_pass,
        "shape": [int(shape[0]), int(shape[1])],
        "image_file": image_path.name,
        "image_file_sha256": _sha_bytes(source_encoded),
        "annotations": [path.name for path in paths],
        "annotation_sha256": [_sha_file(path) for path in paths],
        "person_pixels": [int(np.count_nonzero(mask)) for mask in masks],
        "pair_metrics": pair_metrics,
        "contact_pair_count": len(contact_pairs),
        "contact_detected": bool(contact_pairs),
        "ownership_mask_sha256s": ownership_hashes,
        "distinct_ownership_masks": distinct_ownership,
        "transform_chain_sha256s": {
            _name(index): packages[_name(index)]["transform_chain_sha256"] for index in range(size)
        },
        "mode_a_reads": {
            **{key: reads[key] for key in reads},
            "all_accepted": all_accepted,
            "accepted_count": sum(1 for key in reads if reads[key]["status"] == "accepted"),
            "distinct_package_ids": distinct_package_ids,
            "transform_roundtrips_passed": roundtrips_ok,
        },
        "multi_person_gate": {
            "passed": gate.passed,
            "blockers": list(gate.blockers),
            "instance_context": "duo" if size == 2 else "small_group",
        },
        "seeded_faults": {
            "wrong_person": {
                "injected": True,
                "rejected": wrong_rejected,
                "blocking_reason_codes": wrong_reasons,
                "decision_sha256": wrong_decision["decision_sha256"],
            },
            "cross_instance": {
                "injected": True,
                "rejected": cross_rejected,
                "blocking_reason_codes": cross_reasons,
                "decision_sha256": cross_decision["decision_sha256"],
            },
            **gate_seeded,
        },
        "bounded_ownership_integrity": bounded_ownership_integrity,
    }


def run_local_multi_person_mode_a_group_slice(
    source_root: Path,
    sizes: tuple[int, ...],
    limit_per_size: int,
    workdir: Path,
    *,
    decided_at: str = _DECIDED_AT_DEFAULT,
    prefer_contact: bool = True,
) -> dict[str, Any]:
    content = _resolve_content_root(source_root)
    annotations_root = content / "annotations"
    images_root = content / "images"
    if not annotations_root.is_dir() or not images_root.is_dir():
        raise FileNotFoundError(f"LV-MHP images/annotations directories missing under {content}")

    groups = _select_groups(
        annotations_root, sizes, limit_per_size, prefer_contact=prefer_contact
    )
    if not groups:
        raise RuntimeError(f"no LV-MHP groups found for sizes={sizes}")

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    records = [
        _process_group(group, images_root, workdir, decided_at) for group in groups
    ]
    processed = [record for record in records if record["status"] == "processed"]
    group_pass = [record for record in processed if record["group_pass"]]
    reads_accepted = [r for r in processed if r["mode_a_reads"]["all_accepted"]]
    distinct_ids = [r for r in processed if r["mode_a_reads"]["distinct_package_ids"]]
    gate_pass = [r for r in processed if r["multi_person_gate"]["passed"]]
    contact_pass = [r for r in group_pass if r["contact_detected"]]
    wrong_blocked = [r for r in processed if r["seeded_faults"]["wrong_person"]["rejected"]]
    cross_blocked = [r for r in processed if r["seeded_faults"]["cross_instance"]["rejected"]]
    bounded_integrity = [r for r in processed if r["bounded_ownership_integrity"]]

    def _all(subset: list[dict[str, Any]]) -> bool:
        return bool(processed) and len(subset) == len(processed)

    def _all_seeded(name: str, key: str) -> bool:
        present = [
            record["seeded_faults"][name]
            for record in processed
            if name in record["seeded_faults"]
        ]
        return bool(present) and all(item[key] for item in present)

    seeded_exclusivity_ok = _all_seeded("exclusivity_overlap", "blocked")
    seeded_bleed_ok = _all_seeded("cross_instance_bleed", "blocked")
    seeded_containment_ok = _all_seeded("cross_instance_bleed", "containment_also_blocked")
    seeded_nonreciprocity_ok = _all_seeded("contact_nonreciprocity", "blocked")

    per_size: dict[str, dict[str, int]] = {}
    for size in sizes:
        size_processed = [record for record in processed if record["size"] == size]
        size_pass = [record for record in size_processed if record["group_pass"]]
        size_contact = [record for record in size_pass if record["contact_detected"]]
        per_size[str(size)] = {
            "processed": len(size_processed),
            "group_pass": len(size_pass),
            "contact_group_pass": len(size_contact),
            "mode_a_all_accepted": sum(
                1 for record in size_processed if record["mode_a_reads"]["all_accepted"]
            ),
            "gate_pass": sum(
                1 for record in size_processed if record["multi_person_gate"]["passed"]
            ),
        }

    runtime_pass = (
        _all(reads_accepted)
        and _all(distinct_ids)
        and _all(gate_pass)
        and _all(wrong_blocked)
        and _all(cross_blocked)
        and _all(bounded_integrity)
        and _all(group_pass)
        and seeded_exclusivity_ok
        and seeded_bleed_ok
        and seeded_containment_ok
    )

    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER if runtime_pass else "RUNTIME_PARTIAL",
        "authority": AUTHORITY,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "decided_at": decided_at,
        "source": "lv_mhp_v1",
        "source_role": "multi_person_full_body_parsing",
        "source_content_root": str(content),
        "advances_over_prior_mode_a_duo_runtime": (
            "mode_a_package_read_plus_contact_qc_on_real_multi_body_groups_2_3_4"
        ),
        "gate_families_exercised": ["QC-035", "QC-036", "AUT-MP-001", "AUT-MP-002", "AUT-MP-003"],
        "mode_a_use_scope": "diagnostic",
        "small_group_context_exercised": any(size >= 3 for size in sizes),
        "contact_dilation_iterations": CONTACT_DILATION_ITERATIONS,
        "prefer_contact": prefer_contact,
        "group_sizes_requested": list(sizes),
        "limit_per_size": limit_per_size,
        "group_count_selected": len(groups),
        "group_count_processed": len(processed),
        "group_pass_count": len(group_pass),
        "contact_group_pass_count": len(contact_pass),
        "noncontact_group_pass_count": len(group_pass) - len(contact_pass),
        "mode_a_reads_all_accepted_count": len(reads_accepted),
        "distinct_package_id_group_count": len(distinct_ids),
        "multi_person_gate_pass_count": len(gate_pass),
        "bounded_ownership_integrity_count": len(bounded_integrity),
        "per_size_breakdown": per_size,
        "seeded_faults_all_blocked": {
            "wrong_person_wrong_owner": _all(wrong_blocked),
            "cross_instance_instance_mismatch": _all(cross_blocked),
            "exclusivity_overlap_qc035": seeded_exclusivity_ok,
            "cross_instance_bleed_qc036": seeded_bleed_ok,
            "bleed_containment_aut_mp_001": seeded_containment_ok,
            "contact_nonreciprocity_aut_mp_002": seeded_nonreciprocity_ok,
        },
        "ownership_integrity_boundary": (
            "bounded_ownership_integrity == enforced QC-035 exclusivity + QC-036 "
            "no-core-bleed + distinct accepted Mode A reads for every promoted "
            "instance + reciprocal contact under duo/small_group. Real LV-MHP "
            "annotations may carry small sub-threshold boundary overlaps."
        ),
        "records": records,
        "package_authority_tier": "fixture_authority",
        "mf_p6_12_02_prerequisite_complete": False,
        "mf_p6_12_03_complete": False,
        "main_adapter_execution_complete": False,
        "mf_p8_11_07_demo_complete": False,
        "kevin_governed_multi_person_sources_used": False,
        "gold_claimed": False,
        "champions_claimed": False,
        "doctor_green_claimed": False,
        "visual_qa_pass_claimed": False,
        "production_evidence_pass_claimed": False,
        "independent_real_accuracy_claim": False,
        "honest_non_claims": [
            "mf_p6_12_02_adopted_main_comfyui_transaction",
            "mf_p6_12_03_complete",
            "main_adapter_execution",
            "mf_p8_11_07_real_governed_demo",
            "kevin_governed_multi_person_sources",
            "autonomous_certified_gold",
            "champions",
            "doctor_green",
            "production_evidence_pass",
            "independent_real_accuracy",
        ],
    }
    digest = _sha_doc(document)
    document["report_id"] = f"lmpmag_{digest[:24]}"
    document["seal_sha256"] = digest
    document["sha256"] = _sha_doc(
        {key: value for key, value in document.items() if key != "sha256"}
    )
    return document


def _parse_sizes(raw: str) -> tuple[int, ...]:
    sizes = tuple(int(token) for token in raw.split(",") if token.strip())
    if not sizes or any(size < 2 for size in sizes):
        raise argparse.ArgumentTypeError("--sizes must be a comma-separated list of integers >= 2")
    return sizes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=None,
        help="Defaults to read-when-present MaskedWarehouse LV-MHP via gold_volume_sources.",
    )
    parser.add_argument("--sizes", type=_parse_sizes, default=DEFAULT_SIZES)
    parser.add_argument("--limit-per-size", type=int, default=DEFAULT_LIMIT_PER_SIZE)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-prefer-contact", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    source_root = args.source_root or default_maskedwarehouse_lv_mhp_root()

    if args.verify:
        document = json.loads(args.output.read_text(encoding="utf-8"))
        recomputed = _sha_doc({key: value for key, value in document.items() if key != "sha256"})
        if recomputed != document.get("sha256"):
            raise SystemExit(
                f"seal mismatch: recomputed={recomputed} stored={document.get('sha256')}"
            )
    else:
        document = run_local_multi_person_mode_a_group_slice(
            source_root,
            tuple(args.sizes),
            args.limit_per_size,
            args.workdir,
            prefer_contact=not args.no_prefer_contact,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    print(
        json.dumps(
            {
                "proof_tier": document["proof_tier"],
                "group_count_processed": document["group_count_processed"],
                "group_pass_count": document["group_pass_count"],
                "contact_group_pass_count": document["contact_group_pass_count"],
                "mode_a_reads_all_accepted_count": document["mode_a_reads_all_accepted_count"],
                "multi_person_gate_pass_count": document["multi_person_gate_pass_count"],
                "per_size_breakdown": document["per_size_breakdown"],
                "seeded_faults_all_blocked": document["seeded_faults_all_blocked"],
                "seal_sha256": document["seal_sha256"],
                "sha256": document["sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
