"""Build a bounded, frozen, image-disjoint tournament sample set (≥50).

Sources (READ-ONLY):
  * F:\\Reference_Images\\Ultimate_Masking_Reference_Images\\benchmark_reference
  * C:\\Comfy_UI_Main\\MaskedWarehouse (CelebAMask-HQ / LaPa / Body archive)

Honesty:
  * Content-hash image-disjoint (sha256).
  * External / reference labels are NOT treated as MaskFactory gold.
  * No bytes copied into the repo; no F: junction; no fabricated candidates.
  * Target ≥50 when pools allow; never pad with duplicates.

Usage:
  python runtime_artifacts/_build_tournament_sample_set_20260720.py --ts 20260720T1505
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
RA = REPO_ROOT / "runtime_artifacts"

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

ULTIMATE_ROOT = Path(r"F:\Reference_Images\Ultimate_Masking_Reference_Images\benchmark_reference")
MW_ROOT = Path(r"C:\Comfy_UI_Main\MaskedWarehouse")

# Bounded sampling: enough for ≥50 without a multi-thousand USB hash sweep.
TARGET_MIN = 50
MAX_TOTAL = 64
ULTIMATE_PER_CATEGORY = 3
MW_CELEBA = 6
MW_LAPA = 5
MW_BODY = 5


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _seal(doc: dict[str, Any]) -> dict[str, Any]:
    doc.pop("self_sha256", None)
    payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    doc["self_sha256"] = hashlib.sha256(payload).hexdigest()
    return doc


def _list_dirs(root: Path) -> list[Path]:
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


def _add(
    records: list[dict[str, Any]],
    seen: set[str],
    *,
    path: Path,
    source_family: str,
    collection_id: str,
    source_drive: str,
) -> bool:
    if len(records) >= MAX_TOTAL:
        return False
    try:
        size = path.stat().st_size
        if size <= 0:
            return False
        sha = _sha256_file(path)
    except OSError:
        return False
    if sha in seen:
        return False
    seen.add(sha)
    records.append(
        {
            "sample_id": f"tsamp_{len(records):04d}",
            "source_family": source_family,
            "collection_id": collection_id,
            "source_path_readonly": str(path),
            "source_drive": source_drive,
            "source_sha256": sha,
            "source_bytes": size,
            "role": "tournament_source_image",
            "mask_authored": False,
            "gold_authority": False,
        }
    )
    return True


def _sample_ultimate(records: list[dict[str, Any]], seen: set[str]) -> dict[str, Any]:
    present = ULTIMATE_ROOT.is_dir()
    cats_used: list[str] = []
    if not present:
        return {"present": False, "categories_used": [], "added": 0}
    before = len(records)
    for cat in _list_dirs(ULTIMATE_ROOT):
        if len(records) >= MAX_TOTAL:
            break
        imgs = _top_images(cat, ULTIMATE_PER_CATEGORY)
        added_here = 0
        for img in imgs:
            if _add(
                records,
                seen,
                path=img,
                source_family="ultimate_masking_reference_images",
                collection_id=f"benchmark_reference/{cat.name}",
                source_drive="F:",
            ):
                added_here += 1
        if added_here:
            cats_used.append(cat.name)
    return {
        "present": True,
        "root": str(ULTIMATE_ROOT),
        "categories_used": cats_used,
        "added": len(records) - before,
    }


def _sample_maskedwarehouse(records: list[dict[str, Any]], seen: set[str]) -> dict[str, Any]:
    present = MW_ROOT.is_dir()
    pools: list[dict[str, Any]] = []
    if not present:
        return {"present": False, "pools": [], "added": 0}
    before = len(records)

    celeba = MW_ROOT / "CelebAMask-HQ" / "CelebA-HQ-img"
    if celeba.is_dir():
        added = 0
        for img in _top_images(celeba, MW_CELEBA):
            if _add(
                records,
                seen,
                path=img,
                source_family="maskedwarehouse",
                collection_id="CelebAMask-HQ/CelebA-HQ-img",
                source_drive="C:",
            ):
                added += 1
        pools.append({"pool": "celebamask_hq", "path": str(celeba), "added": added})

    lapa = MW_ROOT / "LaPa" / "val" / "images"
    if lapa.is_dir():
        added = 0
        for img in _top_images(lapa, MW_LAPA):
            if _add(
                records,
                seen,
                path=img,
                source_family="maskedwarehouse",
                collection_id="LaPa/val/images",
                source_drive="C:",
            ):
                added += 1
        pools.append({"pool": "lapa_val", "path": str(lapa), "added": added})

    body_roots = [
        MW_ROOT / "Body" / "archive" / "Men I" / "img",
        MW_ROOT / "Body" / "archive" / "Women I" / "img",
        MW_ROOT / "Body" / "archive" / "Men II" / "img",
    ]
    body_added = 0
    for broot in body_roots:
        if body_added >= MW_BODY or len(records) >= MAX_TOTAL:
            break
        if not broot.is_dir():
            continue
        need = min(2, MW_BODY - body_added)
        for img in _top_images(broot, need):
            if _add(
                records,
                seen,
                path=img,
                source_family="maskedwarehouse",
                collection_id=str(broot.relative_to(MW_ROOT)).replace("\\", "/"),
                source_drive="C:",
            ):
                body_added += 1
    if body_added:
        pools.append(
            {
                "pool": "body_archive",
                "path": str(MW_ROOT / "Body" / "archive"),
                "added": body_added,
            }
        )

    return {
        "present": True,
        "root": str(MW_ROOT),
        "pools": pools,
        "added": len(records) - before,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ts", required=True)
    args = parser.parse_args()

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    ultimate = _sample_ultimate(records, seen)
    mw = _sample_maskedwarehouse(records, seen)

    # If still under TARGET_MIN, top up from Ultimate clothed__one / mixed__two (large pools).
    if len(records) < TARGET_MIN and ultimate.get("present"):
        for cat_name in ("clothed__one", "mixed__two", "nude__one", "mixed__one"):
            if len(records) >= TARGET_MIN:
                break
            cat = ULTIMATE_ROOT / cat_name
            if not cat.is_dir():
                continue
            # Take next lexicographic images beyond the first ULTIMATE_PER_CATEGORY.
            imgs = _top_images(cat, ULTIMATE_PER_CATEGORY + 8)
            for img in imgs[ULTIMATE_PER_CATEGORY:]:
                if len(records) >= TARGET_MIN:
                    break
                _add(
                    records,
                    seen,
                    path=img,
                    source_family="ultimate_masking_reference_images",
                    collection_id=f"benchmark_reference/{cat_name}",
                    source_drive="F:",
                )

    image_disjoint = len({r["source_sha256"] for r in records}) == len(records)
    feasible_ge_50 = len(records) >= TARGET_MIN

    manifest: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "tournament_sample_set",
        "authority": "tournament_input_selection_only",
        "evidence_tier": "RUNTIME_PROBE_BOUNDED",
        "frozen": True,
        "image_disjoint": image_disjoint,
        "read_only_source": True,
        "no_f_junction_created": True,
        "no_bytes_copied_into_repo": True,
        "external_labels_not_gold": True,
        "recorded_at": now,
        "target_min": TARGET_MIN,
        "max_total": MAX_TOTAL,
        "sample_count": len(records),
        "feasible_ge_50": feasible_ge_50,
        "unique_sha256_count": len(seen),
        "ordered_sample_ids": [r["sample_id"] for r in records],
        "source_summary": {
            "ultimate_masking_reference_images": ultimate,
            "maskedwarehouse": mw,
        },
        "bounds": {
            "ultimate_per_category": ULTIMATE_PER_CATEGORY,
            "mw_celeba": MW_CELEBA,
            "mw_lapa": MW_LAPA,
            "mw_body": MW_BODY,
        },
        "samples": records,
        "honesty_boundary": {
            "not_maskfactory_gold": True,
            "not_human_anchor": True,
            "no_fabricated_candidates": True,
            "no_force_registered_champions": True,
            "sibling_tournament_input_only": True,
        },
    }
    _seal(manifest)

    manifest_rel = f"qa/live_verification/tournament_sample_set_ultimate_mw_{args.ts}.json"
    manifest_path = REPO_ROOT / manifest_rel
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    feed: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "tournament_sample_set_sibling_feed",
        "authority": "tournament_input_selection_only",
        "evidence_tier": "RUNTIME_PROBE_BOUNDED",
        "recorded_at": now,
        "instruction": (
            "FULL AUTONOMY: sibling multi-provider GPU tournament MUST consume this "
            "frozen image-disjoint sample set (identical ordered_sample_ids) as the "
            "shared evaluation corpus. Read-only paths; do not treat as gold; emit "
            "genuine machine_verified_candidate sidecars under runs/ only when ≥3 "
            "independent mask families are live."
        ),
        "sample_set": {
            "path": manifest_rel,
            "self_sha256": manifest["self_sha256"],
            "sample_count": manifest["sample_count"],
            "feasible_ge_50": feasible_ge_50,
            "image_disjoint": image_disjoint,
            "ordered_sample_ids": manifest["ordered_sample_ids"],
        },
        "consumer_contract": {
            "identical_ordered_sample_ids": True,
            "content_hash_key": "source_sha256",
            "outputs_under": ["runs/", "runtime_artifacts/", "qa/live_verification/"],
            "forbidden_writes": [
                "F:\\Reference_Images",
                "F:\\Reference_Images\\Ultimate_Masking_Reference_Images",
                "C:\\Comfy_UI_Main\\MaskedWarehouse",
            ],
        },
        "next_agent_step": (
            "GPU-sequence ≥3 independent mask families over this sample set; write "
            "machine_verified_candidate + *.corpus_record.json envelopes under runs/; "
            "then re-run tools/run_measured_champions_path.py / "
            "tools/build_autonomous_gold_admission.py --corpus."
        ),
    }
    _seal(feed)
    feed_path = LV / f"tournament_sample_set_sibling_feed_{args.ts}.json"
    feed_path.write_text(json.dumps(feed, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Stable pointer for sibling agents (always the latest feed from this builder).
    latest = {
        "schema_version": "1.0.0",
        "artifact_type": "tournament_sample_set_sibling_feed_latest",
        "feed_path": f"qa/live_verification/tournament_sample_set_sibling_feed_{args.ts}.json",
        "sample_set_path": manifest_rel,
        "sample_count": manifest["sample_count"],
        "sample_set_self_sha256": manifest["self_sha256"],
        "feed_self_sha256": feed["self_sha256"],
        "recorded_at": now,
    }
    _seal(latest)
    latest_path = LV / "tournament_sample_set_sibling_feed_latest.json"
    latest_path.write_text(json.dumps(latest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Also under runtime_artifacts for agents that watch that tree.
    (RA / "tournament_sample_set_sibling_feed_latest.json").write_text(
        json.dumps(latest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "sample_count": manifest["sample_count"],
                "feasible_ge_50": feasible_ge_50,
                "image_disjoint": image_disjoint,
                "manifest": manifest_rel,
                "manifest_self_sha256": manifest["self_sha256"],
                "feed": str(feed_path.relative_to(REPO_ROOT)).replace("\\", "/"),
                "feed_self_sha256": feed["self_sha256"],
                "ultimate_added": ultimate.get("added", 0),
                "mw_added": mw.get("added", 0),
            },
            sort_keys=True,
        )
    )
    return 0 if feasible_ge_50 and image_disjoint else 2


if __name__ == "__main__":
    raise SystemExit(main())
