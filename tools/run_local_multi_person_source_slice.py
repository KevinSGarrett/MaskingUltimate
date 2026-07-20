"""Bounded runtime: real LV-MHP-v1 multi-person source slice through live gates.

This harness advances the multi-person demo/source path *beyond* the synthetic
STATIC_PASS contract suite by decoding **real local** LV-MHP-v1 duo annotations
(external-supervision assets under MaskedWarehouse) and executing the *actual*
non-overridable multi-person image gate (`evaluate_multi_person_candidate_gate`,
QC-035/QC-036/AUT-MP-001/002/003) on those real pixels.

Honest boundary (RUNTIME_PASS_BOUNDED, never inflated):
  * Uses external-supervision LV-MHP-v1 masks, NOT Kevin-governed demo sources.
  * Does NOT satisfy MF-P8-11.07 (real 10-20 image governed demo), gold,
    doctor-green, champions, or PRODUCTION_EVIDENCE_PASS.
  * No fabricated masks: silhouettes/atomic-unions are decoded straight from the
    real per-person annotation PNGs; contact bands are derived from real
    dilation geometry; seeded faults are explicit corruptions used only to prove
    the hard blockers fire on real data.

The evidence is self-sealed (sha256) and lists the sha256 of every real source
file consumed so the run is independently reproducible/auditable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage

from maskfactory.autonomy.multi_person_gate import evaluate_multi_person_candidate_gate
from maskfactory.qa.multi_instance import MultiInstanceQcInputs

ANNOTATION_PATTERN = re.compile(r"^(?P<image>\d+)_(?P<count>\d+)_(?P<instance>\d+)\.png$")
PROOF_TIER = "RUNTIME_PASS_BOUNDED"
ARTIFACT_TYPE = "local_multi_person_source_runtime_report"
AUTHORITY = (
    "local_external_supervision_lv_mhp_duo_gate_runtime_only_"
    "no_kevin_governed_demo_gold_champions_or_production_authority"
)
SCHEMA_VERSION = "1.0.0"
CONTACT_DILATION_ITERATIONS = 5


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


def _process_duo(duo: dict[str, Any]) -> dict[str, Any]:
    p0 = _load_silhouette(duo["p0_path"])
    p1 = _load_silhouette(duo["p1_path"])
    if p0.shape != p1.shape:
        return {
            "image_id": duo["image_id"],
            "status": "skipped_shape_mismatch",
            "p0_shape": list(p0.shape),
            "p1_shape": list(p1.shape),
        }

    raw_intersection = int(np.count_nonzero(p0 & p1))
    raw_union = int(np.count_nonzero(p0 | p1))
    raw_iou = round(raw_intersection / raw_union, 6) if raw_union else 0.0

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

    clean = _gate(silhouettes, atomics, contact_bands, recorded, relationships)

    seeded: dict[str, dict[str, Any]] = {}

    overlap = _gate(
        {"p0": p0, "p1": p0.copy()},
        {"p0": p0.copy(), "p1": p0.copy()},
        {},
        {"p0": frozenset(), "p1": frozenset()},
        {},
    )
    seeded["exclusivity_overlap"] = {
        "injected": True,
        "blocked": "QC-035" in overlap.blockers,
        "blockers": list(overlap.blockers),
    }

    bleed_atomic0 = p0 | p1
    bleed = _gate(
        {"p0": p0, "p1": p1},
        {"p0": bleed_atomic0, "p1": p1.copy()},
        contact_bands,
        recorded,
        relationships,
    )
    seeded["cross_instance_bleed"] = {
        "injected": True,
        "blocked": "QC-036" in bleed.blockers,
        "containment_also_blocked": "AUT-MP-001" in bleed.blockers,
        "blockers": list(bleed.blockers),
    }

    if contact:
        one_way = _gate(
            silhouettes,
            atomics,
            contact_bands,
            recorded,
            {("p0", "p1"): "contact"},
        )
        seeded["contact_nonreciprocity"] = {
            "injected": True,
            "blocked": "AUT-MP-002" in one_way.blockers,
            "blockers": list(one_way.blockers),
        }

    return {
        "image_id": duo["image_id"],
        "status": "processed",
        "p0_annotation": duo["p0_path"].name,
        "p1_annotation": duo["p1_path"].name,
        "p0_annotation_sha256": _sha_file(duo["p0_path"]),
        "p1_annotation_sha256": _sha_file(duo["p1_path"]),
        "shape": list(p0.shape),
        "p0_pixels": int(np.count_nonzero(p0)),
        "p1_pixels": int(np.count_nonzero(p1)),
        "raw_silhouette_intersection_px": raw_intersection,
        "raw_silhouette_iou": raw_iou,
        "contact_detected": contact,
        "contact_band_px": {
            "p0->p1": int(band_ab.sum()),
            "p1->p0": int(band_ba.sum()),
        },
        "clean_gate_passed": clean.passed,
        "clean_gate_blockers": list(clean.blockers),
        "seeded_faults": seeded,
    }


def run_local_multi_person_source_slice(source_root: Path, limit: int) -> dict[str, Any]:
    content = _resolve_content_root(source_root)
    annotations_root = content / "annotations"
    images_root = content / "images"
    if not annotations_root.is_dir() or not images_root.is_dir():
        raise FileNotFoundError(f"LV-MHP images/annotations directories missing under {content}")

    duos = _select_duos(annotations_root, limit)
    if not duos:
        raise RuntimeError("no LV-MHP duo (person_count==2) annotations were found")

    records = [_process_duo(duo) for duo in duos]
    processed = [record for record in records if record["status"] == "processed"]

    clean_pass = [record for record in processed if record["clean_gate_passed"]]
    contact_pass = [record for record in clean_pass if record["contact_detected"]]

    def _all_seeded(name: str, key: str) -> bool:
        results = [record["seeded_faults"].get(name) for record in processed]
        present = [item for item in results if item is not None]
        return bool(present) and all(item[key] for item in present)

    seeded_exclusivity_ok = _all_seeded("exclusivity_overlap", "blocked")
    seeded_bleed_ok = _all_seeded("cross_instance_bleed", "blocked")
    seeded_containment_ok = _all_seeded("cross_instance_bleed", "containment_also_blocked")
    seeded_nonreciprocity_ok = _all_seeded("contact_nonreciprocity", "blocked")

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
        "contact_dilation_iterations": CONTACT_DILATION_ITERATIONS,
        "duo_count_requested": limit,
        "duo_count_processed": len(processed),
        "clean_gate_pass_count": len(clean_pass),
        "contact_clean_pass_count": len(contact_pass),
        "noncontact_clean_pass_count": len(clean_pass) - len(contact_pass),
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
    document["report_id"] = f"lmps_{digest[:24]}"
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
        default=Path(r"C:\Comfy_UI_Main\MaskedWarehouse\Body\LV-MHP-v1"),
    )
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        document = json.loads(args.output.read_text(encoding="utf-8"))
        recomputed = _sha_doc({key: value for key, value in document.items() if key != "sha256"})
        if recomputed != document.get("sha256"):
            raise SystemExit(
                f"seal mismatch: recomputed={recomputed} stored={document.get('sha256')}"
            )
    else:
        document = run_local_multi_person_source_slice(args.source_root, args.limit)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    print(
        json.dumps(
            {
                "proof_tier": document["proof_tier"],
                "duo_count_processed": document["duo_count_processed"],
                "clean_gate_pass_count": document["clean_gate_pass_count"],
                "contact_clean_pass_count": document["contact_clean_pass_count"],
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
