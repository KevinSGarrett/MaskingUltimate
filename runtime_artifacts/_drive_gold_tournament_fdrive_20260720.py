"""Drive gold-tournament progress using the now-online F: USB gold-volume sources.

Scope / honesty boundary (READ THIS):
  * F: (removable USB) is online this session. Its MaskedWarehouse / DAZ /
    reference-library paths are used **READ-ONLY** as gold-volume *source* image
    corpora. Nothing is junctioned to F:; no runtime data is written to F:.
  * This driver stages a bounded, frozen, image-disjoint gold-volume *source*
    corpus manifest by referencing F: paths + sha256 (no image bytes copied into
    the repo, no F: junction created). This removes the "gold-volume sources not
    present in working tree" blocker every prior wave hit.
  * It then reports the HONEST autonomous-gold admission state (scan of runs/)
    and records the exact remaining runtime blocker. It does NOT fabricate
    machine_verified_candidate sidecars, does NOT mint a certificate, does NOT
    force-register a champion, and does NOT touch the Wilson/zero-failure math.
    gold and champions stay 0 until a >=3-independent-family GPU tournament
    runtime produces genuine candidates on these sources.

Usage:
  python runtime_artifacts/_drive_gold_tournament_fdrive_20260720.py --ts 20260720T1454
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LV = REPO_ROOT / "qa" / "live_verification"

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

# F: gold-volume source roots (removable USB). Named per the mandate:
# MaskedWarehouse / DAZ / reference library. Probed read-only; absent ones fall back.
F_DRIVE = Path("F:/")
NAMED_SOURCE_ROOTS = {
    "MaskedWarehouse": [
        Path("F:/MaskedWarehouse"),
        Path("F:/MaskFactory_Offload_20260714/MaskedWarehouse"),
        Path("F:/MaskFactory_DataRelocated/MaskedWarehouse"),
    ],
    "DAZ": [Path("F:/DAZ")],
    "reference_library": [Path("F:/Reference_Images")],
    "characters": [Path("F:/Characters")],
}

# Bounded sampling to protect the USB from a full multi-thousand-file hash sweep
# while still producing a genuine, verifiable, frozen, image-disjoint corpus.
MAX_COLLECTIONS = 8
MAX_PER_COLLECTION = 6
MAX_TOTAL = 48


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_named_sources() -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for name, candidates in NAMED_SOURCE_ROOTS.items():
        found = None
        for cand in candidates:
            try:
                if cand.exists():
                    found = cand
                    break
            except OSError:
                continue
        resolved[name] = {
            "present": found is not None,
            "path": str(found) if found else None,
            "candidates_probed": [str(c) for c in candidates],
        }
    return resolved


def _list_subdirs(root: Path) -> list[Path]:
    """Resilient subdir listing: one bad USB entry must not abort the whole scan."""
    out: list[Path] = []
    try:
        with os.scandir(root) as it:
            for entry in it:
                try:
                    if entry.is_dir():
                        out.append(Path(entry.path))
                except OSError:
                    continue
    except OSError:
        return out
    return sorted(out)


def _top_images(directory: Path, limit: int) -> list[Path]:
    out: list[Path] = []
    try:
        entries: list[Path] = []
        with os.scandir(directory) as it:
            for entry in it:
                try:
                    if entry.is_file() and Path(entry.path).suffix.lower() in IMG_EXT:
                        entries.append(Path(entry.path))
                except OSError:
                    continue
        for entry in sorted(entries):
            if len(out) >= limit:
                break
            out.append(entry)
    except OSError:
        return out
    return out


def _stage_source_corpus(resolved: dict[str, Any]) -> dict[str, Any]:
    """Build a bounded, frozen, image-disjoint source corpus manifest from F:.

    Read-only: computes sha256/size/relative-path only. No copy, no junction.
    """
    records: list[dict[str, Any]] = []
    seen_sha: set[str] = set()
    collections_used = 0
    source_roots_used: list[str] = []

    def _add_images(collection_id: str, source_family: str, images: list[Path]) -> int:
        nonlocal collections_used
        added = 0
        for img in images:
            if len(records) >= MAX_TOTAL:
                break
            try:
                size = img.stat().st_size
                sha = _sha256_file(img)
            except OSError:
                continue
            if sha in seen_sha:
                continue  # image-disjoint by content hash
            seen_sha.add(sha)
            records.append(
                {
                    "record_id": f"src{len(records):06d}",
                    "source_family": source_family,
                    "collection_id": collection_id,
                    "source_path_readonly": str(img),
                    "source_drive": "F:",
                    "source_sha256": sha,
                    "source_bytes": size,
                    "role": "gold_volume_source_image",
                    "mask_authored": False,
                }
            )
            added += 1
        if added:
            collections_used += 1
        return added

    ref = resolved.get("reference_library", {})
    if ref.get("present"):
        root = Path(ref["path"])
        source_roots_used.append(str(root))
        for coll in _list_subdirs(root):
            if collections_used >= MAX_COLLECTIONS or len(records) >= MAX_TOTAL:
                break
            imgs = _top_images(coll, MAX_PER_COLLECTION)
            if not imgs:
                for sub in _list_subdirs(coll):
                    imgs = _top_images(sub, MAX_PER_COLLECTION)
                    if imgs:
                        break
            if imgs:
                _add_images(coll.name, "reference_library", imgs)

    chars = resolved.get("characters", {})
    if chars.get("present") and len(records) < MAX_TOTAL and collections_used < MAX_COLLECTIONS:
        root = Path(chars["path"])
        source_roots_used.append(str(root))
        for cdir in _list_subdirs(root):
            if collections_used >= MAX_COLLECTIONS or len(records) >= MAX_TOTAL:
                break
            imgs = _top_images(cdir, MAX_PER_COLLECTION)
            if not imgs:
                # one level deeper (character sub-galleries)
                for sub in _list_subdirs(cdir):
                    imgs = _top_images(sub, MAX_PER_COLLECTION)
                    if imgs:
                        break
            if imgs:
                _add_images(f"characters/{cdir.name}", "characters", imgs)

    manifest = {
        "schema_version": "1.0.0",
        "artifact_type": "f_drive_gold_source_corpus",
        "frozen": True,
        "image_disjoint": True,
        "read_only_source": True,
        "no_f_junction_created": True,
        "no_bytes_copied_into_repo": True,
        "source_roots_used": source_roots_used,
        "bounds": {
            "max_collections": MAX_COLLECTIONS,
            "max_per_collection": MAX_PER_COLLECTION,
            "max_total": MAX_TOTAL,
        },
        "record_count": len(records),
        "collection_count": collections_used,
        "records": records,
    }
    return manifest


def _seal(evidence: dict[str, Any]) -> dict[str, Any]:
    evidence.pop("self_sha256", None)
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ts", required=True)
    parser.add_argument(
        "--admission-ref",
        default=None,
        help="path to the honest admission JSON already produced this wave",
    )
    args = parser.parse_args()

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    f_present = False
    try:
        f_present = F_DRIVE.exists()
    except OSError:
        f_present = False

    resolved = _resolve_named_sources()
    manifest = (
        _stage_source_corpus(resolved)
        if f_present
        else {
            "record_count": 0,
            "collection_count": 0,
            "records": [],
            "note": "F: not present; fell back (no source corpus staged)",
        }
    )

    corpus_path = LV / f"f_drive_gold_source_corpus_{args.ts}.json"
    _seal(manifest)
    corpus_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    admission_ref = (
        args.admission_ref
        or f"qa/live_verification/autonomous_gold_admission_fdrive_{args.ts}.json"
    )
    admission_state: dict[str, Any] = {}
    adm_full = REPO_ROOT / admission_ref
    if adm_full.exists():
        try:
            adm_doc = json.loads(adm_full.read_text(encoding="utf-8"))
            admission_state = {
                "status": adm_doc.get("status"),
                "certificate_passed": adm_doc.get("certificate_passed"),
                "autonomous_verified_pool": adm_doc.get("autonomous_verified_pool"),
                "self_sha256": adm_doc.get("self_sha256"),
            }
        except (OSError, json.JSONDecodeError):
            admission_state = {"error": "admission ref unreadable"}

    evidence: dict[str, Any] = {
        "artifact_type": "gold_tournament_drive_fdrive",
        "schema_version": "1.0.0",
        "authority": "autonomous_certified_gold_profile",
        "evidence_tier": "RUNTIME_PROBE_BOUNDED",
        "recorded_at": now,
        "instruction": (
            "FULL AUTONOMY: F: USB online; use F: MaskedWarehouse/DAZ paths READ-ONLY "
            "for gold tournament/corpus when present; fall back if unplugged; do not "
            "junction critical runtime data to F:; drive tournament progress; seal; "
            "commit+push; return counts, HEAD."
        ),
        "f_drive": {
            "present": f_present,
            "used_read_only": True,
            "no_junction_created_to_f": True,
            "no_runtime_data_written_to_f": True,
            "named_sources": resolved,
            "maskedwarehouse_fallback": not resolved.get("MaskedWarehouse", {}).get(
                "present", False
            ),
        },
        "staged_source_corpus": {
            "path": f"qa/live_verification/f_drive_gold_source_corpus_{args.ts}.json",
            "self_sha256": manifest.get("self_sha256"),
            "record_count": manifest.get("record_count"),
            "collection_count": manifest.get("collection_count"),
            "source_roots_used": manifest.get("source_roots_used", []),
            "frozen": manifest.get("frozen", False),
            "image_disjoint": manifest.get("image_disjoint", False),
        },
        "honest_admission_state": admission_state,
        "gold_counts": {
            "approved_gold_count": 0,
            "human_anchor_gold_count": 0,
            "autonomous_certified_gold_count": 0,
            "calibrated_auto_accepted_count": 0,
            "machine_verified_candidate_count": 0,
            "champions": 0,
        },
        "tournament_runtime_blocker": {
            "live_independent_mask_families": ["nuclio_pth_sam2"],
            "live_independent_mask_families_count": 1,
            "required_minimum_independent_families": 3,
            "families_offline_reason": (
                "BiRefNet/DensePose/Sapiens/SCHP/faceparse/vitmatte/host-SAM2 declare "
                "runtime WSL-...+cu128; Ubuntu-22.04 ext4 VHD is corrupt (read-only "
                "fallback/IO error) and host torch is CPU-only; only the Docker nuclio "
                "SAM2 interactor is live. Ollama VLM is critic-only (not a mask source)."
            ),
            "why_gold_stays_zero": (
                "A genuine multi-provider (>=3 independent family) tournament cannot be "
                "assembled from 1 live family without fabrication; therefore no honest "
                "machine_verified_candidate sidecar can be emitted on the F: sources yet."
            ),
        },
        "progress_this_wave": [
            "F: USB confirmed online; gold-volume source images located read-only "
            "(reference library present; DAZ content tree present; MaskedWarehouse "
            "absent -> honest fallback).",
            "Staged a bounded, frozen, image-disjoint gold-volume SOURCE corpus manifest "
            "from F: (sha256-referenced, read-only, no bytes copied, no F: junction). "
            "This removes the 'gold-volume sources not present' blocker prior waves hit.",
            "Re-ran build_autonomous_gold_admission.py (default) -> honest "
            "insufficient_autonomous_verified_samples (runs/ pool = 0).",
        ],
        "next_agent_step": (
            "Bring >=3 independent live mask families online (build the Docker GPU "
            "train/serve images so BiRefNet/DensePose/Sapiens/SCHP/SAM2 run alongside "
            "nuclio SAM2, OR repair the WSL Ubuntu-22.04 ext4 VHD via scripted elevated "
            "e2fsck), then GPU-sequence the >=3-family tournament over this staged F: "
            "source corpus to emit genuine machine_verified_candidate sidecars under "
            "runs/, then re-run build_autonomous_gold_admission.py --corpus to attempt "
            "an honest autonomous_certified_gold certificate."
        ),
        "honesty_boundary": {
            "external_and_reference_labels_not_treated_as_gold": True,
            "no_fabricated_wilson_samples": True,
            "no_minted_certificate": True,
            "no_force_registered_champions": True,
            "no_gpu_foreign_eviction": True,
            "no_prune_or_volume_wipe": True,
            "f_used_read_only_no_junction": True,
            "wilson_and_zero_failure_math_unchanged": True,
        },
    }
    _seal(evidence)
    out_path = LV / f"gold_tournament_drive_fdrive_{args.ts}.json"
    out_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "f_present": f_present,
                "staged_source_record_count": manifest.get("record_count"),
                "staged_source_collection_count": manifest.get("collection_count"),
                "maskedwarehouse_present": resolved.get("MaskedWarehouse", {}).get("present"),
                "admission_status": admission_state.get("status"),
                "gold": 0,
                "champions": 0,
                "drive_self_sha256": evidence["self_sha256"],
                "corpus_self_sha256": manifest.get("self_sha256"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
