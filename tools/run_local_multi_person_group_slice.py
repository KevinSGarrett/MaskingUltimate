"""Bounded runtime: real LV-MHP-v1 multi-body group slice through live gates.

This harness expands multi-person contact/exclusivity QC coverage *beyond* the
12-duo slice (`tools/run_local_multi_person_source_slice.py`) by decoding **real
local** LV-MHP-v1 groups of 2, 3, and 4 people (external-supervision assets
under MaskedWarehouse) and executing the *actual* non-overridable multi-person
image gate (`evaluate_multi_person_candidate_gate`,
QC-035/QC-036/AUT-MP-001/002/003) on those real pixels. Groups of three or more
exercise the ``small_group`` context (N>2 promoted instances with the full
pairwise contact/exclusivity/reciprocity matrix), which the duo slice never
touches.

Honest boundary (RUNTIME_PASS_BOUNDED, never inflated):
  * Uses external-supervision LV-MHP-v1 masks, NOT Kevin-governed demo sources.
  * Does NOT satisfy MF-P8-11.07 (real 10-20 image governed demo), gold,
    doctor-green, champions, or PRODUCTION_EVIDENCE_PASS.
  * No fabricated masks: silhouettes/atomic-unions are decoded straight from the
    real per-person annotation PNGs; contact bands are derived from real
    dilation geometry; seeded faults are explicit corruptions used only to prove
    the hard blockers fire on real multi-body data.

The evidence is self-sealed (sha256) and lists the sha256 of every real source
file consumed so the run is independently reproducible/auditable.
"""

from __future__ import annotations

import argparse
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
from maskfactory.qa.multi_instance import MultiInstanceQcInputs

ANNOTATION_PATTERN = re.compile(r"^(?P<image>\d+)_(?P<count>\d+)_(?P<instance>\d+)\.png$")
PROOF_TIER = "RUNTIME_PASS_BOUNDED"
ARTIFACT_TYPE = "local_multi_person_group_runtime_report"
AUTHORITY = (
    "local_external_supervision_lv_mhp_multi_body_group_gate_runtime_only_"
    "no_kevin_governed_demo_gold_champions_or_production_authority"
)
SCHEMA_VERSION = "1.0.0"
CONTACT_DILATION_ITERATIONS = 5
DEFAULT_SIZES = (2, 3, 4)
DEFAULT_LIMIT_PER_SIZE = 16


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_doc(document: dict[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


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


def _name(index: int) -> str:
    return f"p{index}"


def _select_groups(
    annotations_root: Path, sizes: tuple[int, ...], limit_per_size: int
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

    selected: list[dict[str, Any]] = []
    for size in sizes:
        taken = 0
        for image_id in sorted(grouped, key=lambda value: value.encode("ascii")):
            counts = declared_counts[image_id]
            instances = grouped[image_id]
            if counts != {size} or set(instances) != set(range(1, size + 1)):
                continue
            selected.append(
                {
                    "image_id": image_id,
                    "size": size,
                    "paths": [instances[rank] for rank in range(1, size + 1)],
                }
            )
            taken += 1
            if taken >= limit_per_size:
                break
    return selected


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


def _process_group(group: dict[str, Any]) -> dict[str, Any]:
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

    silhouettes = {_name(index): mask for index, mask in enumerate(masks)}
    atomics = {_name(index): mask.copy() for index, mask in enumerate(masks)}
    contact_bands, recorded, relationships, pair_metrics = _clean_relationship_geometry(masks)
    contact_pairs = [metric["pair"] for metric in pair_metrics if metric["contact"]]

    clean = _gate(silhouettes, atomics, contact_bands, recorded, relationships, size=size)

    seeded: dict[str, dict[str, Any]] = {}

    # Exclusivity (QC-035): force p1 to duplicate p0; drop all relationships.
    overlap_sil = dict(silhouettes)
    overlap_sil[_name(1)] = masks[0].copy()
    overlap_atomic = {name: value.copy() for name, value in overlap_sil.items()}
    empty_recorded = {_name(index): frozenset() for index in range(size)}
    overlap = _gate(overlap_sil, overlap_atomic, {}, empty_recorded, {}, size=size)
    seeded["exclusivity_overlap"] = {
        "injected": True,
        "blocked": "QC-035" in overlap.blockers,
        "blockers": list(overlap.blockers),
    }

    # Cross-instance bleed (QC-036) + containment (AUT-MP-001): bleed p0's atomic into p1.
    bleed_atomics = {name: value.copy() for name, value in atomics.items()}
    bleed_atomics[_name(0)] = masks[0] | masks[1]
    bleed = _gate(silhouettes, bleed_atomics, contact_bands, recorded, relationships, size=size)
    seeded["cross_instance_bleed"] = {
        "injected": True,
        "blocked": "QC-036" in bleed.blockers,
        "containment_also_blocked": "AUT-MP-001" in bleed.blockers,
        "blockers": list(bleed.blockers),
    }

    # Contact non-reciprocity (AUT-MP-002/003): drop one direction of a real contact pair.
    if contact_pairs:
        first = next(pair for pair in relationships if relationships[pair] == "contact")
        broken = {
            pair: kind for pair, kind in relationships.items() if pair != (first[1], first[0])
        }
        one_way = _gate(silhouettes, atomics, contact_bands, recorded, broken, size=size)
        seeded["contact_nonreciprocity"] = {
            "injected": True,
            "blocked": "AUT-MP-002" in one_way.blockers,
            "blockers": list(one_way.blockers),
        }

    return {
        "image_id": group["image_id"],
        "size": size,
        "status": "processed",
        "annotations": [path.name for path in paths],
        "annotation_sha256": [_sha_file(path) for path in paths],
        "shape": list(shape),
        "person_pixels": [int(np.count_nonzero(mask)) for mask in masks],
        "pair_metrics": pair_metrics,
        "contact_pair_count": len(contact_pairs),
        "contact_detected": bool(contact_pairs),
        "clean_gate_passed": clean.passed,
        "clean_gate_blockers": list(clean.blockers),
        "seeded_faults": seeded,
    }


def run_local_multi_person_group_slice(
    source_root: Path, sizes: tuple[int, ...], limit_per_size: int
) -> dict[str, Any]:
    content = _resolve_content_root(source_root)
    annotations_root = content / "annotations"
    images_root = content / "images"
    if not annotations_root.is_dir() or not images_root.is_dir():
        raise FileNotFoundError(f"LV-MHP images/annotations directories missing under {content}")

    groups = _select_groups(annotations_root, sizes, limit_per_size)
    if not groups:
        raise RuntimeError(f"no LV-MHP groups found for sizes={sizes}")

    records = [_process_group(group) for group in groups]
    processed = [record for record in records if record["status"] == "processed"]
    clean_pass = [record for record in processed if record["clean_gate_passed"]]
    contact_pass = [record for record in clean_pass if record["contact_detected"]]

    def _all_seeded(name: str, key: str) -> bool:
        present = [
            record["seeded_faults"][name] for record in processed if name in record["seeded_faults"]
        ]
        return bool(present) and all(item[key] for item in present)

    seeded_exclusivity_ok = _all_seeded("exclusivity_overlap", "blocked")
    seeded_bleed_ok = _all_seeded("cross_instance_bleed", "blocked")
    seeded_containment_ok = _all_seeded("cross_instance_bleed", "containment_also_blocked")
    seeded_nonreciprocity_ok = _all_seeded("contact_nonreciprocity", "blocked")

    per_size: dict[str, dict[str, int]] = {}
    for size in sizes:
        size_processed = [record for record in processed if record["size"] == size]
        size_clean = [record for record in size_processed if record["clean_gate_passed"]]
        size_contact = [record for record in size_clean if record["contact_detected"]]
        per_size[str(size)] = {
            "processed": len(size_processed),
            "clean_gate_pass": len(size_clean),
            "contact_clean_pass": len(size_contact),
        }

    all_clean = bool(processed) and len(clean_pass) == len(processed)
    seeded_all = seeded_exclusivity_ok and seeded_bleed_ok and seeded_containment_ok
    runtime_pass = all_clean and seeded_all

    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER if runtime_pass else "RUNTIME_PARTIAL",
        "authority": AUTHORITY,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": "lv_mhp_v1",
        "source_role": "multi_person_full_body_parsing",
        "source_content_root": str(content),
        "gate_families_exercised": [
            "QC-035",
            "QC-036",
            "AUT-MP-001",
            "AUT-MP-002",
            "AUT-MP-003",
        ],
        "small_group_context_exercised": any(size >= 3 for size in sizes),
        "contact_dilation_iterations": CONTACT_DILATION_ITERATIONS,
        "group_sizes_requested": list(sizes),
        "limit_per_size": limit_per_size,
        "group_count_selected": len(groups),
        "group_count_processed": len(processed),
        "clean_gate_pass_count": len(clean_pass),
        "contact_clean_pass_count": len(contact_pass),
        "noncontact_clean_pass_count": len(clean_pass) - len(contact_pass),
        "per_size_breakdown": per_size,
        "seeded_faults_all_blocked": {
            "exclusivity_overlap_qc035": seeded_exclusivity_ok,
            "cross_instance_bleed_qc036": seeded_bleed_ok,
            "bleed_containment_aut_mp_001": seeded_containment_ok,
            "contact_nonreciprocity_aut_mp_002": seeded_nonreciprocity_ok,
        },
        "records": records,
        "mf_p8_11_07_demo_complete": False,
        "kevin_governed_multi_person_sources_used": False,
        "gold_claimed": False,
        "champions_claimed": False,
        "doctor_green_claimed": False,
        "visual_qa_pass_claimed": False,
        "production_evidence_pass_claimed": False,
        "honest_non_claims": [
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
    document["report_id"] = f"lmpg_{digest[:24]}"
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
        document = run_local_multi_person_group_slice(
            source_root, tuple(args.sizes), args.limit_per_size
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
                "clean_gate_pass_count": document["clean_gate_pass_count"],
                "contact_clean_pass_count": document["contact_clean_pass_count"],
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
