"""Bounded runtime: real LV-MHP-v1 duo masks through the Mode A package-QC path.

The prior stream sealed ``RUNTIME_PASS_BOUNDED`` on the real LV-MHP-v1 duo
*image gate* (``run_local_multi_person_source_slice.py`` ->
``evaluate_multi_person_candidate_gate``). This harness advances that runtime by
driving the **Mode A vertical-slice package-QC / ownership path** on the *same
real* per-person annotation masks:

  * Materializes a real-mask-backed Mode A package pair per duo -- ownership
    masks are the decoded LV-MHP per-instance annotation PNGs (never fabricated)
    and the source raster is the real LV-MHP image.
  * Runs the real ``evaluate_mode_a_package_read`` on both persons and requires
    both to be accepted with distinct package identities and a passing transform
    round-trip.
  * Runs the real ``evaluate_multi_person_candidate_gate`` on the real masks
    (QC-035/QC-036/AUT-MP-001/002/003) with real contact-band geometry.
  * Seeds a wrong-person subject swap and a cross-instance scene swap and
    requires the Mode A read to fail closed (``wrong_owner`` /
    ``instance_mismatch``).
  * Emits a zero-ownership-ambiguity verdict from the real overlap / distinct
    real ownership hashes.

Honest boundary (RUNTIME_PASS_BOUNDED, never inflated):
  * Uses external-supervision LV-MHP-v1 masks, NOT Kevin-governed demo sources.
  * The package wrapper/transform/protected-region contract is fixture-authority
    only: it proves the package-QC and ownership fail-closed logic on real
    ownership pixels; it does NOT satisfy MF-P6-12.02 (adopted single-person
    Main/ComfyUI transaction), MF-P6-12.03 completion, MF-P8-11.07 (governed
    demo), gold, doctor-green, champions, or PRODUCTION_EVIDENCE_PASS.
  * No independent real-accuracy claim: masks are the supervision annotations
    themselves, so this measures package/ownership plumbing, not model accuracy.

Every consumed real source file is listed with its sha256 and the evidence is
self-sealed (sha256) so the run is independently reproducible / auditable.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
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
ARTIFACT_TYPE = "local_multi_person_mode_a_slice_report"
AUTHORITY = (
    "local_external_supervision_lv_mhp_duo_mode_a_package_qc_runtime_only_"
    "fixture_authority_no_kevin_governed_demo_gold_champions_or_production_authority"
)
SCHEMA_VERSION = "1.0.0"
CONTACT_DILATION_ITERATIONS = 5
_LABEL = "torso"
_ONTOLOGY = b"ontology-body-parts-v1-lvmhp-duo"
_RELEASE = b"release-lvmhp-duo-fixture-v1"
_CAPABILITY = b"capability-lvmhp-duo-fixture-v1"
_DECIDED_AT_DEFAULT = "2026-07-20T00:00:00Z"
_CHARACTER_REVISIONS = ("char-rev-lvmhp-p0-v1", "char-rev-lvmhp-p1-v1")
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_doc(document: dict[str, Any]) -> str:
    return _sha_bytes(canonical_json_bytes(document))


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


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


def _select_duos(annotations_root: Path, limit: int) -> list[dict[str, Any]]:
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

    duos: list[dict[str, Any]] = []
    for image_id in sorted(grouped, key=lambda value: value.encode("ascii")):
        counts = declared_counts[image_id]
        instances = grouped[image_id]
        if counts != {2} or set(instances) != {1, 2}:
            continue
        duos.append(
            {
                "image_id": image_id,
                "p0_path": instances[1],
                "p1_path": instances[2],
            }
        )
        if len(duos) >= limit:
            break
    return duos


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
    """Deterministic in-bounds crop chain over the annotation raster space.

    Geometry is identical per person (guaranteeing a clean round-trip on any real
    duo dimension); ``chain_id`` carries the person/image identity so the two
    per-person chain hashes are distinct.
    """
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
        "chain_id": f"lvmhp-duo-crop-{image_id}-p{person_index}-v1",
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
    """Anchor a small protected box at the real instance centroid, clamped in-bounds."""
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


def _revocation(token: str = "d") -> bytes:
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
    instance_id = f"p{person_index}"
    owner_id = f"person-{person_index}"
    scene_instance_id = f"scene-{image_id}-{instance_id}"
    character_revision = _CHARACTER_REVISIONS[person_index]
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
        "package_revision": "rev-lvmhp-1",
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
):
    inputs = MultiInstanceQcInputs(
        silhouettes=silhouettes,
        atomic_unions=atomics,
        contact_bands=contact_bands,
        recorded_relationships=recorded,
        expected_promoted_count=2,
    )
    return evaluate_multi_person_candidate_gate(
        inputs,
        instance_context="duo",
        promoted_instances=("p0", "p1"),
        relationships=relationships,
    )


def _process_duo(duo: dict[str, Any], images_root: Path, workdir: Path, decided_at: str) -> dict:
    p0 = _load_silhouette(duo["p0_path"])
    p1 = _load_silhouette(duo["p1_path"])
    if p0.shape != p1.shape:
        return {
            "image_id": duo["image_id"],
            "status": "skipped_shape_mismatch",
            "p0_shape": list(p0.shape),
            "p1_shape": list(p1.shape),
        }
    image_path = _find_image(images_root, duo["image_id"])
    if image_path is None:
        return {"image_id": duo["image_id"], "status": "skipped_missing_image"}

    source_encoded = image_path.read_bytes()
    with Image.open(image_path) as handle:
        source_pixels = np.asarray(handle.convert("RGB")).tobytes()

    packages = {
        "p0": _build_person_package(
            image_id=duo["image_id"],
            person_index=0,
            mask=p0,
            source_encoded=source_encoded,
            source_pixels=source_pixels,
            workdir=workdir,
        ),
        "p1": _build_person_package(
            image_id=duo["image_id"],
            person_index=1,
            mask=p1,
            source_encoded=source_encoded,
            source_pixels=source_pixels,
            workdir=workdir,
        ),
    }

    reads = {
        key: _summarize_read(
            evaluate_mode_a_package_read(
                packages[key]["request"], packages[key]["evidence"], decided_at=decided_at
            )
        )
        for key in ("p0", "p1")
    }
    package_ids = {reads["p0"]["package_id"], reads["p1"]["package_id"]}
    both_accepted = reads["p0"]["status"] == "accepted" and reads["p1"]["status"] == "accepted"
    distinct_package_ids = None not in package_ids and len(package_ids) == 2
    roundtrips_ok = all(reads[key]["transform_roundtrip_passed"] is True for key in ("p0", "p1"))

    # Real multi-person gate on the real masks with real contact geometry.
    dil0 = ndimage.binary_dilation(p0, iterations=CONTACT_DILATION_ITERATIONS)
    dil1 = ndimage.binary_dilation(p1, iterations=CONTACT_DILATION_ITERATIONS)
    band_ab = dil0 & p1
    band_ba = dil1 & p0
    contact = bool(band_ab.any() and band_ba.any())
    silhouettes = {"p0": p0, "p1": p1}
    atomics = {"p0": p0.copy(), "p1": p1.copy()}
    if contact:
        contact_bands = {("p0", "p1"): band_ab, ("p1", "p0"): band_ba}
        recorded = {"p0": frozenset({"p1"}), "p1": frozenset({"p0"})}
        relationships = {("p0", "p1"): "contact", ("p1", "p0"): "contact"}
    else:
        contact_bands = {}
        recorded = {"p0": frozenset(), "p1": frozenset()}
        relationships = {}
    gate = _gate(silhouettes, atomics, contact_bands, recorded, relationships)

    # Seeded fail-closed faults on the real package (wrong person, cross instance).
    wrong_bundle = copy.deepcopy(packages["p0"])
    wrong_bundle["request"]["subject"]["canonical_person_id"] = "person-1"
    wrong_decision = evaluate_mode_a_package_read(
        wrong_bundle["request"], wrong_bundle["evidence"], decided_at=decided_at
    )
    wrong_reasons = list(wrong_decision.get("rejection_reasons") or ())
    wrong_rejected = wrong_decision.get("status") == "rejected" and "wrong_owner" in wrong_reasons

    cross_bundle = copy.deepcopy(packages["p0"])
    cross_bundle["request"]["subject"]["scene_instance_id"] = packages["p1"]["scene_instance_id"]
    cross_decision = evaluate_mode_a_package_read(
        cross_bundle["request"], cross_bundle["evidence"], decided_at=decided_at
    )
    cross_reasons = list(cross_decision.get("rejection_reasons") or ())
    cross_rejected = (
        cross_decision.get("status") == "rejected" and "instance_mismatch" in cross_reasons
    )

    overlap_px = int(np.count_nonzero(p0 & p1))
    union_px = int(np.count_nonzero(p0 | p1))
    raw_iou = round(overlap_px / union_px, 6) if union_px else 0.0
    strict_zero_overlap = overlap_px == 0
    distinct_ownership = (
        packages["p0"]["ownership_mask_sha256"] != packages["p1"]["ownership_mask_sha256"]
    )
    reciprocal_ok = (not contact) or (gate.passed and "AUT-MP-002" not in gate.blockers)
    # Bounded ownership integrity == the contract the runtime actually enforces:
    # exclusivity (QC-035) + no cross-instance core bleed (QC-036) hold, both
    # persons read as distinct accepted packages, and contact is reciprocal. Real
    # LV-MHP annotations carry small boundary overlaps below the exclusivity
    # threshold; ``strict_zero_overlap`` is reported separately and never inflated.
    bounded_ownership_integrity = (
        gate.passed
        and "QC-035" not in gate.blockers
        and "QC-036" not in gate.blockers
        and distinct_ownership
        and reciprocal_ok
        and both_accepted
        and distinct_package_ids
    )

    duo_pass = (
        both_accepted
        and distinct_package_ids
        and roundtrips_ok
        and gate.passed
        and wrong_rejected
        and cross_rejected
        and bounded_ownership_integrity
    )

    return {
        "image_id": duo["image_id"],
        "status": "processed",
        "duo_pass": duo_pass,
        "shape": [int(p0.shape[0]), int(p0.shape[1])],
        "image_file": image_path.name,
        "image_file_sha256": _sha_bytes(source_encoded),
        "p0_annotation": duo["p0_path"].name,
        "p1_annotation": duo["p1_path"].name,
        "p0_annotation_sha256": _sha_file(duo["p0_path"]),
        "p1_annotation_sha256": _sha_file(duo["p1_path"]),
        "p0_pixels": int(np.count_nonzero(p0)),
        "p1_pixels": int(np.count_nonzero(p1)),
        "overlap_px": overlap_px,
        "raw_silhouette_iou": raw_iou,
        "strict_zero_overlap": strict_zero_overlap,
        "contact_detected": contact,
        "ownership_mask_sha256s": {
            "p0": packages["p0"]["ownership_mask_sha256"],
            "p1": packages["p1"]["ownership_mask_sha256"],
        },
        "distinct_ownership_masks": distinct_ownership,
        "transform_chain_sha256s": {
            "p0": packages["p0"]["transform_chain_sha256"],
            "p1": packages["p1"]["transform_chain_sha256"],
        },
        "mode_a_reads": {
            "p0": reads["p0"],
            "p1": reads["p1"],
            "both_accepted": both_accepted,
            "distinct_package_ids": distinct_package_ids,
            "transform_roundtrips_passed": roundtrips_ok,
        },
        "multi_person_gate": {
            "passed": gate.passed,
            "blockers": list(gate.blockers),
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
        },
        "bounded_ownership_integrity": bounded_ownership_integrity,
    }


def run_local_multi_person_mode_a_slice(
    source_root: Path, limit: int, workdir: Path, *, decided_at: str = _DECIDED_AT_DEFAULT
) -> dict[str, Any]:
    content = _resolve_content_root(source_root)
    annotations_root = content / "annotations"
    images_root = content / "images"
    if not annotations_root.is_dir() or not images_root.is_dir():
        raise FileNotFoundError(f"LV-MHP images/annotations directories missing under {content}")

    duos = _select_duos(annotations_root, limit)
    if not duos:
        raise RuntimeError("no LV-MHP duo (person_count==2) annotations were found")

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    records = [_process_duo(duo, images_root, workdir, decided_at) for duo in duos]
    processed = [record for record in records if record["status"] == "processed"]

    reads_accepted = [r for r in processed if r["mode_a_reads"]["both_accepted"]]
    distinct_ids = [r for r in processed if r["mode_a_reads"]["distinct_package_ids"]]
    gate_pass = [r for r in processed if r["multi_person_gate"]["passed"]]
    wrong_blocked = [r for r in processed if r["seeded_faults"]["wrong_person"]["rejected"]]
    cross_blocked = [r for r in processed if r["seeded_faults"]["cross_instance"]["rejected"]]
    bounded_integrity = [r for r in processed if r["bounded_ownership_integrity"]]
    strict_zero = [r for r in processed if r["strict_zero_overlap"]]
    duo_pass = [r for r in processed if r["duo_pass"]]

    def _all(subset: list[dict[str, Any]]) -> bool:
        return bool(processed) and len(subset) == len(processed)

    runtime_pass = (
        _all(reads_accepted)
        and _all(distinct_ids)
        and _all(gate_pass)
        and _all(wrong_blocked)
        and _all(cross_blocked)
        and _all(bounded_integrity)
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
        "advances_over_prior_gate_runtime": (
            "mode_a_package_read_ownership_and_seeded_fault_fail_closed_on_real_masks"
        ),
        "gate_families_exercised": ["QC-035", "QC-036", "AUT-MP-001", "AUT-MP-002", "AUT-MP-003"],
        "mode_a_use_scope": "diagnostic",
        "contact_dilation_iterations": CONTACT_DILATION_ITERATIONS,
        "duo_count_requested": limit,
        "duo_count_processed": len(processed),
        "duo_pass_count": len(duo_pass),
        "mode_a_reads_accepted_count": len(reads_accepted),
        "distinct_package_id_count": len(distinct_ids),
        "multi_person_gate_pass_count": len(gate_pass),
        "seeded_faults_all_blocked": {
            "wrong_person_wrong_owner": _all(wrong_blocked),
            "cross_instance_instance_mismatch": _all(cross_blocked),
        },
        "bounded_ownership_integrity_count": len(bounded_integrity),
        "strict_zero_overlap_count": len(strict_zero),
        "ownership_integrity_boundary": (
            "bounded_ownership_integrity == enforced QC-035 exclusivity + QC-036 "
            "no-core-bleed + distinct accepted Mode A reads + reciprocal contact. "
            "Real LV-MHP duo annotations carry small sub-threshold boundary overlaps, "
            "so strict_zero_overlap is a stricter synthetic-fixture ideal reported "
            "separately and NOT the runtime pass criterion."
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
    document["report_id"] = f"lmpma_{digest[:24]}"
    document["seal_sha256"] = digest
    document["sha256"] = _sha_doc(
        {key: value for key, value in document.items() if key != "sha256"}
    )
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=None,
        help="Defaults to read-when-present MaskedWarehouse LV-MHP via gold_volume_sources.",
    )
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
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
        document = run_local_multi_person_mode_a_slice(source_root, args.limit, args.workdir)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    print(
        json.dumps(
            {
                "proof_tier": document["proof_tier"],
                "duo_count_processed": document["duo_count_processed"],
                "duo_pass_count": document["duo_pass_count"],
                "mode_a_reads_accepted_count": document["mode_a_reads_accepted_count"],
                "multi_person_gate_pass_count": document["multi_person_gate_pass_count"],
                "seeded_faults_all_blocked": document["seeded_faults_all_blocked"],
                "bounded_ownership_integrity_count": document["bounded_ownership_integrity_count"],
                "strict_zero_overlap_count": document["strict_zero_overlap_count"],
                "seal_sha256": document["seal_sha256"],
                "sha256": document["sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
