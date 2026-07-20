"""Expand the frozen tournament sample set with warehouse + ref + DAZ + other F: roots.

Preserves the existing image-disjoint feed (same source_sha256 / paths), then adds
new content-hash-disjoint samples from present gold-volume roots. Read-only:
no copy, no junction of data/ onto F:, no DAZ Studio / UI automation.

Target ≥100 when pools allow (MaskedWarehouse + Reference_Images + DAZ RO).

Usage:
  python runtime_artifacts/_expand_gold_volume_corpus_20260720.py --ts 20260720T1621
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LV = REPO_ROOT / "qa" / "live_verification"
RA = REPO_ROOT / "runtime_artifacts"

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

# Prefer latest gold-volume expansion; fall back to ultimate+MW base feed.
EXISTING_SAMPLE_SET = LV / "tournament_sample_set_gold_volume_20260720T1625.json"
FALLBACK_SAMPLE_SET = LV / "tournament_sample_set_ultimate_mw_20260720T1600.json"

ULTIMATE_ROOT = Path(
    r"F:\Reference_Images\Ultimate_Masking_Reference_Images\benchmark_reference"
)
REF_ROOT = Path(r"F:\Reference_Images")
MW_ROOT = Path(r"C:\Comfy_UI_Main\MaskedWarehouse")
DAZ_ROOT = Path(r"F:\DAZ")
CHAR_ROOT = Path(r"F:\Characters")
SHOOT_ROOT = Path(r"F:\Shoot")

TARGET_MIN = 100
MAX_TOTAL = 128

# Expansion quotas (beyond preserved base).
MW_LVMHP = 12
MW_SWIMSUIT = 8
MW_CELEBA = 16
MW_LAPA = 12
MW_BODY = 8
DAZ_MAX = 12
ULTIMATE_EXTRA_PER_CAT = 3
REF_COLLECTIONS = 8
REF_PER_COLLECTION = 4
CHAR_MAX = 10
SHOOT_MAX = 8


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


def _walk_images(
    root: Path,
    *,
    limit: int,
    max_dirs: int = 400,
    skip_parts: frozenset[str] = frozenset(),
    name_allow: frozenset[str] | None = None,
) -> list[Path]:
    found: list[Path] = []
    dirs = 0
    if not root.is_dir():
        return found
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirs += 1
            if dirs > max_dirs or len(found) >= limit:
                break
            parts = set(Path(dirpath).parts)
            if parts & skip_parts:
                dirnames.clear()
                continue
            dirnames.sort()
            for name in sorted(filenames):
                if Path(name).suffix.lower() not in IMG_EXT:
                    continue
                if name_allow is not None and name not in name_allow:
                    continue
                found.append(Path(dirpath) / name)
                if len(found) >= limit:
                    break
    except OSError:
        return found
    return found


def _add(
    records: list[dict[str, Any]],
    seen: set[str],
    *,
    path: Path,
    source_family: str,
    collection_id: str,
    source_drive: str,
    source_role: str = "gold_volume",
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
            "source_role": source_role,
            "role": "tournament_source_image",
            "mask_authored": False,
            "gold_authority": False,
        }
    )
    return True


def _preserve_existing(records: list[dict[str, Any]], seen: set[str]) -> dict[str, Any]:
    source = EXISTING_SAMPLE_SET if EXISTING_SAMPLE_SET.is_file() else FALLBACK_SAMPLE_SET
    if not source.is_file():
        return {"present": False, "preserved": 0, "path": str(EXISTING_SAMPLE_SET)}
    doc = json.loads(source.read_text(encoding="utf-8"))
    preserved = 0
    preserved_from = str(source.relative_to(REPO_ROOT)).replace("\\", "/")
    for sample in doc.get("samples") or []:
        sha = sample.get("source_sha256")
        path_s = sample.get("source_path_readonly")
        if not isinstance(sha, str) or not isinstance(path_s, str):
            continue
        path = Path(path_s)
        if not path.is_file():
            continue
        if sha in seen:
            continue
        # Re-verify hash for honesty (USB/path drift fail-closed by skip).
        try:
            live = _sha256_file(path)
        except OSError:
            continue
        if live != sha:
            continue
        seen.add(sha)
        records.append(
            {
                "sample_id": f"tsamp_{len(records):04d}",
                "source_family": sample.get("source_family") or "unknown",
                "collection_id": sample.get("collection_id") or "unknown",
                "source_path_readonly": str(path),
                "source_drive": sample.get("source_drive") or (path.drive + "\\"),
                "source_sha256": sha,
                "source_bytes": int(sample.get("source_bytes") or path.stat().st_size),
                "source_role": "preserved_base_feed",
                "role": "tournament_source_image",
                "mask_authored": False,
                "gold_authority": False,
                "preserved_from": preserved_from,
            }
        )
        preserved += 1
        if len(records) >= MAX_TOTAL:
            break
    return {
        "present": True,
        "preserved": preserved,
        "path": preserved_from,
        "prior_sample_count": doc.get("sample_count"),
        "prior_self_sha256": doc.get("self_sha256"),
    }


def _sample_daz(records: list[dict[str, Any]], seen: set[str]) -> dict[str, Any]:
    present = DAZ_ROOT.is_dir()
    if not present:
        return {"present": False, "added": 0, "note": "F:\\DAZ absent"}
    before = len(records)
    skip = frozenset(
        {
            "19_cache",
            "03_content",
            "02_installers",
            "textures",
            "compiled_shaders",
            "thumbnails",
            "rejected",
        }
    )
    pools: list[dict[str, Any]] = []
    # Prefer RGB validation / render / export trees; 12_renders is often empty.
    search_roots = [
        ("14_scene_packages", DAZ_ROOT / "14_scene_packages"),
        ("12_renders/pristine", DAZ_ROOT / "12_renders" / "pristine"),
        ("12_renders/derived", DAZ_ROOT / "12_renders" / "derived"),
        ("16_maskfactory_exports/intake_ready", DAZ_ROOT / "16_maskfactory_exports" / "intake_ready"),
        ("08_asset_tests/previews", DAZ_ROOT / "08_asset_tests" / "previews"),
        ("15_datasets/builds", DAZ_ROOT / "15_datasets" / "builds"),
    ]
    added_total = 0
    for label, root in search_roots:
        if added_total >= DAZ_MAX or len(records) >= MAX_TOTAL:
            break
        need = DAZ_MAX - added_total
        imgs = _walk_images(root, limit=need, max_dirs=250, skip_parts=skip)
        added = 0
        for img in imgs:
            if _add(
                records,
                seen,
                path=img,
                source_family="daz",
                collection_id=f"daz/{label}",
                source_drive="F:",
                source_role="daz_synthetic_geometry",
            ):
                added += 1
                added_total += 1
                if added_total >= DAZ_MAX:
                    break
        pools.append(
            {
                "pool": label,
                "path": str(root),
                "present": root.is_dir(),
                "added": added,
                "images_seen": len(imgs),
            }
        )
    return {
        "present": True,
        "root": str(DAZ_ROOT),
        "renders_populated": any(
            p.get("images_seen", 0) > 0 and "12_renders" in str(p.get("pool"))
            for p in pools
        ),
        "pools": pools,
        "added": len(records) - before,
        "honesty": "DAZ Studio never launched; read-only filesystem probe only",
    }


def _sample_mw_expand(records: list[dict[str, Any]], seen: set[str]) -> dict[str, Any]:
    present = MW_ROOT.is_dir()
    if not present:
        return {"present": False, "added": 0}
    before = len(records)
    pools: list[dict[str, Any]] = []

    celeba = MW_ROOT / "CelebAMask-HQ" / "CelebA-HQ-img"
    if celeba.is_dir() and len(records) < MAX_TOTAL:
        added = 0
        # Base feed already took early lex images; scan a larger prefix and
        # let content-hash disjointness skip duplicates.
        for img in _top_images(celeba, MW_CELEBA + 48):
            if added >= MW_CELEBA or len(records) >= MAX_TOTAL:
                break
            if _add(
                records,
                seen,
                path=img,
                source_family="maskedwarehouse",
                collection_id="CelebAMask-HQ/CelebA-HQ-img",
                source_drive="C:",
                source_role="mw_expand",
            ):
                added += 1
        pools.append({"pool": "celebamask_hq", "path": str(celeba), "added": added})

    lapa = MW_ROOT / "LaPa" / "val" / "images"
    if lapa.is_dir() and len(records) < MAX_TOTAL:
        added = 0
        for img in _top_images(lapa, MW_LAPA + 32):
            if added >= MW_LAPA or len(records) >= MAX_TOTAL:
                break
            if _add(
                records,
                seen,
                path=img,
                source_family="maskedwarehouse",
                collection_id="LaPa/val/images",
                source_drive="C:",
                source_role="mw_expand",
            ):
                added += 1
        pools.append({"pool": "lapa_val", "path": str(lapa), "added": added})

    lvm = MW_ROOT / "Body" / "LV-MHP-v1" / "LV-MHP-v1" / "images"
    if lvm.is_dir():
        added = 0
        for img in _top_images(lvm, MW_LVMHP + 24):
            if added >= MW_LVMHP or len(records) >= MAX_TOTAL:
                break
            if _add(
                records,
                seen,
                path=img,
                source_family="maskedwarehouse",
                collection_id="Body/LV-MHP-v1/images",
                source_drive="C:",
                source_role="mw_expand",
            ):
                added += 1
        pools.append({"pool": "lv_mhp_v1_images", "path": str(lvm), "added": added})

    swim = MW_ROOT / "Body" / "UniDataPro_swimsuit-human-segmentation-dataset"
    if swim.is_dir():
        added = 0
        # Prefer RGB image.jpg under numbered case dirs (skip mask.png).
        cases = sorted(
            (p for p in _list_dirs(swim) if p.name.isdigit()),
            key=lambda p: int(p.name),
        )
        for case in cases:
            if added >= MW_SWIMSUIT or len(records) >= MAX_TOTAL:
                break
            img = case / "image.jpg"
            if not img.is_file():
                continue
            if _add(
                records,
                seen,
                path=img,
                source_family="maskedwarehouse",
                collection_id="Body/UniDataPro_swimsuit/image.jpg",
                source_drive="C:",
                source_role="mw_expand",
            ):
                added += 1
        pools.append({"pool": "swimsuit_image_jpg", "path": str(swim), "added": added})

    body_roots = [
        MW_ROOT / "Body" / "archive" / "Men I" / "img",
        MW_ROOT / "Body" / "archive" / "Women I" / "img",
        MW_ROOT / "Body" / "archive" / "Men II" / "img",
        MW_ROOT / "Body" / "archive" / "Women II" / "img",
    ]
    body_added = 0
    for broot in body_roots:
        if body_added >= MW_BODY or len(records) >= MAX_TOTAL:
            break
        if not broot.is_dir():
            continue
        for img in _top_images(broot, MW_BODY):
            if body_added >= MW_BODY or len(records) >= MAX_TOTAL:
                break
            if _add(
                records,
                seen,
                path=img,
                source_family="maskedwarehouse",
                collection_id=str(broot.relative_to(MW_ROOT)).replace("\\", "/"),
                source_drive="C:",
                source_role="mw_expand",
            ):
                body_added += 1
    if body_added:
        pools.append({"pool": "body_archive", "added": body_added})

    return {
        "present": True,
        "root": str(MW_ROOT),
        "pools": pools,
        "added": len(records) - before,
    }


def _sample_ultimate_extra(records: list[dict[str, Any]], seen: set[str]) -> dict[str, Any]:
    present = ULTIMATE_ROOT.is_dir()
    if not present:
        return {"present": False, "added": 0}
    before = len(records)
    cats_used: list[str] = []
    for cat in _list_dirs(ULTIMATE_ROOT):
        if len(records) >= MAX_TOTAL:
            break
        # Skip first 3 (already in base feed); take next ULTIMATE_EXTRA_PER_CAT.
        imgs = _top_images(cat, 3 + ULTIMATE_EXTRA_PER_CAT)
        added_here = 0
        for img in imgs[3:]:
            if _add(
                records,
                seen,
                path=img,
                source_family="ultimate_masking_reference_images",
                collection_id=f"benchmark_reference/{cat.name}",
                source_drive="F:",
                source_role="ref_expand",
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


def _sample_reference_collections(
    records: list[dict[str, Any]], seen: set[str]
) -> dict[str, Any]:
    present = REF_ROOT.is_dir()
    if not present:
        return {"present": False, "added": 0}
    before = len(records)
    used: list[str] = []
    skip_names = {
        "Ultimate_Masking_Reference_Images",  # handled via ultimate pools
        "manifests",
    }
    for coll in _list_dirs(REF_ROOT):
        if len(used) >= REF_COLLECTIONS or len(records) >= MAX_TOTAL:
            break
        if coll.name in skip_names:
            continue
        imgs = _top_images(coll, REF_PER_COLLECTION)
        if not imgs:
            # one level deeper
            for sub in _list_dirs(coll):
                imgs = _top_images(sub, REF_PER_COLLECTION)
                if imgs:
                    break
        added_here = 0
        for img in imgs:
            if _add(
                records,
                seen,
                path=img,
                source_family="reference_library",
                collection_id=f"reference_images/{coll.name}",
                source_drive="F:",
                source_role="ref_expand",
            ):
                added_here += 1
        if added_here:
            used.append(coll.name)
    return {
        "present": True,
        "root": str(REF_ROOT),
        "collections_used": used,
        "added": len(records) - before,
    }


def _sample_characters(records: list[dict[str, Any]], seen: set[str]) -> dict[str, Any]:
    present = CHAR_ROOT.is_dir()
    if not present:
        return {"present": False, "added": 0}
    before = len(records)
    imgs = _walk_images(
        CHAR_ROOT,
        limit=CHAR_MAX * 2,
        max_dirs=200,
        skip_parts=frozenset({"raw", "tmp", "cache"}),
    )
    added = 0
    for img in imgs:
        if added >= CHAR_MAX or len(records) >= MAX_TOTAL:
            break
        # Prefer reference composites / stills; skip tiny icons if any.
        try:
            if img.stat().st_size < 20_000:
                continue
        except OSError:
            continue
        rel = str(img.relative_to(CHAR_ROOT)).replace("\\", "/")
        if _add(
            records,
            seen,
            path=img,
            source_family="characters",
            collection_id=f"characters/{rel.split('/')[0]}",
            source_drive="F:",
            source_role="f_gold_root",
        ):
            added += 1
    return {
        "present": True,
        "root": str(CHAR_ROOT),
        "added": len(records) - before,
    }


def _sample_shoot(records: list[dict[str, Any]], seen: set[str]) -> dict[str, Any]:
    present = SHOOT_ROOT.is_dir()
    if not present:
        return {"present": False, "added": 0}
    before = len(records)
    imgs = _walk_images(
        SHOOT_ROOT,
        limit=SHOOT_MAX * 3,
        max_dirs=250,
        skip_parts=frozenset({"raw", "CR3", "ARW", "NEF", "cache"}),
    )
    added = 0
    for img in imgs:
        if added >= SHOOT_MAX or len(records) >= MAX_TOTAL:
            break
        try:
            if img.stat().st_size < 50_000:
                continue
        except OSError:
            continue
        if _add(
            records,
            seen,
            path=img,
            source_family="shoot",
            collection_id="shoot/jpg",
            source_drive="F:",
            source_role="f_gold_root",
        ):
            added += 1
    return {
        "present": True,
        "root": str(SHOOT_ROOT),
        "added": len(records) - before,
    }


def _counts_by_source(records: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(r["source_family"] for r in records))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ts", required=True)
    args = parser.parse_args()

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Order: preserve base, then underrepresented roots (DAZ/MW/ref/chars/shoot),
    # then Ultimate extras as fill — so USB F: diversity is not starved by Ultimate.
    preserved = _preserve_existing(records, seen)
    daz = _sample_daz(records, seen)
    mw = _sample_mw_expand(records, seen)
    ref = _sample_reference_collections(records, seen)
    chars = _sample_characters(records, seen)
    shoot = _sample_shoot(records, seen)
    ultimate = _sample_ultimate_extra(records, seen)

    # Top-up from Ultimate large pools if still under TARGET_MIN or MAX_TOTAL has room.
    if len(records) < MAX_TOTAL and ULTIMATE_ROOT.is_dir():
        for cat_name in (
            "clothed__one",
            "mixed__two",
            "nude__one",
            "mixed__one",
            "clothed__two",
            "nude__two",
        ):
            if len(records) >= MAX_TOTAL:
                break
            cat = ULTIMATE_ROOT / cat_name
            if not cat.is_dir():
                continue
            for img in _top_images(cat, 48):
                if len(records) >= MAX_TOTAL:
                    break
                _add(
                    records,
                    seen,
                    path=img,
                    source_family="ultimate_masking_reference_images",
                    collection_id=f"benchmark_reference/{cat_name}",
                    source_drive="F:",
                    source_role="ref_topup",
                )

    image_disjoint = len({r["source_sha256"] for r in records}) == len(records)
    feasible_ge_64 = len(records) >= 64
    feasible_ge_100 = len(records) >= TARGET_MIN
    by_source = _counts_by_source(records)

    roots_present = {
        "maskedwarehouse": MW_ROOT.is_dir(),
        "reference_library_ultimate": ULTIMATE_ROOT.is_dir(),
        "reference_images": REF_ROOT.is_dir(),
        "daz": DAZ_ROOT.is_dir(),
        "characters": CHAR_ROOT.is_dir(),
        "shoot": SHOOT_ROOT.is_dir(),
        "f_maskedwarehouse": Path(r"F:\MaskedWarehouse").is_dir(),
    }

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
        "daz_not_human_anchor_gold": True,
        "recorded_at": now,
        "expanded_from": preserved.get("path")
        or "tournament_sample_set_gold_volume_20260720T1625.json",
        "target_min": TARGET_MIN,
        "max_total": MAX_TOTAL,
        "sample_count": len(records),
        "feasible_ge_50": len(records) >= 50,
        "feasible_ge_64": feasible_ge_64,
        "feasible_ge_100": feasible_ge_100,
        "unique_sha256_count": len(seen),
        "counts_by_source": by_source,
        "roots_present": roots_present,
        "ordered_sample_ids": [r["sample_id"] for r in records],
        "source_summary": {
            "preserved_base_feed": preserved,
            "daz": daz,
            "maskedwarehouse_expand": mw,
            "ultimate_masking_reference_images_extra": ultimate,
            "reference_library_collections": ref,
            "characters": chars,
            "shoot": shoot,
        },
        "bounds": {
            "mw_celeba": MW_CELEBA,
            "mw_lapa": MW_LAPA,
            "mw_lvmhp": MW_LVMHP,
            "mw_swimsuit": MW_SWIMSUIT,
            "mw_body": MW_BODY,
            "daz_max": DAZ_MAX,
            "ultimate_extra_per_cat": ULTIMATE_EXTRA_PER_CAT,
            "ref_collections": REF_COLLECTIONS,
            "ref_per_collection": REF_PER_COLLECTION,
            "char_max": CHAR_MAX,
            "shoot_max": SHOOT_MAX,
        },
        "samples": records,
        "honesty_boundary": {
            "not_maskfactory_gold": True,
            "not_human_anchor": True,
            "no_fabricated_candidates": True,
            "no_force_registered_champions": True,
            "sibling_tournament_input_only": True,
            "never_junction_data_to_usb_f": True,
            "never_interactive_daz_studio": True,
        },
    }
    _seal(manifest)

    manifest_rel = f"qa/live_verification/tournament_sample_set_gold_volume_{args.ts}.json"
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
            "frozen image-disjoint gold-volume sample set (identical ordered_sample_ids) "
            "as the shared evaluation corpus. Sources: MaskedWarehouse + Ultimate/ref + "
            "DAZ (read-only) + other present F: gold roots. Do not treat as MaskFactory "
            "gold; emit genuine machine_verified_candidate sidecars under runs/ only when "
            "≥3 independent mask families are live."
        ),
        "sample_set": {
            "path": manifest_rel,
            "self_sha256": manifest["self_sha256"],
            "sample_count": manifest["sample_count"],
            "feasible_ge_50": manifest["feasible_ge_50"],
            "feasible_ge_64": feasible_ge_64,
            "feasible_ge_100": feasible_ge_100,
            "image_disjoint": image_disjoint,
            "counts_by_source": by_source,
            "ordered_sample_ids": manifest["ordered_sample_ids"],
        },
        "consumer_contract": {
            "identical_ordered_sample_ids": True,
            "content_hash_key": "source_sha256",
            "outputs_under": ["runs/", "runtime_artifacts/", "qa/live_verification/"],
            "forbidden_writes": [
                "F:\\Reference_Images",
                "F:\\Reference_Images\\Ultimate_Masking_Reference_Images",
                "F:\\DAZ",
                "F:\\Characters",
                "F:\\Shoot",
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

    latest = {
        "schema_version": "1.0.0",
        "artifact_type": "tournament_sample_set_sibling_feed_latest",
        "feed_path": f"qa/live_verification/tournament_sample_set_sibling_feed_{args.ts}.json",
        "sample_set_path": manifest_rel,
        "sample_count": manifest["sample_count"],
        "counts_by_source": by_source,
        "sample_set_self_sha256": manifest["self_sha256"],
        "feed_self_sha256": feed["self_sha256"],
        "recorded_at": now,
    }
    _seal(latest)
    latest_path = LV / "tournament_sample_set_sibling_feed_latest.json"
    latest_path.write_text(
        json.dumps(latest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (RA / "tournament_sample_set_sibling_feed_latest.json").write_text(
        json.dumps(latest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    corpus: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "gold_volume_source_corpus",
        "authority": "gold_volume_tournament_input_path_map",
        "evidence_tier": "RUNTIME_PROBE_BOUNDED",
        "frozen": True,
        "image_disjoint": image_disjoint,
        "read_only_source": True,
        "no_f_junction_created": True,
        "no_bytes_copied_into_repo": True,
        "never_junction_data_to_usb_f": True,
        "docker_vhdx_stays_on_c": True,
        "recorded_at": now,
        "expanded_from": manifest["expanded_from"],
        "sample_set_path": manifest_rel,
        "sibling_feed_path": str(feed_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "sample_count": len(records),
        "feasible_ge_100": feasible_ge_100,
        "counts_by_source": by_source,
        "roots_present": roots_present,
        "source_summary": manifest["source_summary"],
        "governing_configs": [
            "configs/gold_volume_sources.yaml",
            "configs/gold_volume_tournament_inputs.yaml",
        ],
        "honesty_boundary": manifest["honesty_boundary"],
        "ordered_sample_ids": manifest["ordered_sample_ids"],
        "sample_set_self_sha256": manifest["self_sha256"],
    }
    _seal(corpus)
    corpus_rel = f"qa/live_verification/gold_volume_source_corpus_{args.ts}.json"
    corpus_path = REPO_ROOT / corpus_rel
    corpus_path.write_text(
        json.dumps(corpus, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "sample_count": len(records),
                "feasible_ge_64": feasible_ge_64,
                "feasible_ge_100": feasible_ge_100,
                "image_disjoint": image_disjoint,
                "counts_by_source": by_source,
                "manifest": manifest_rel,
                "manifest_self_sha256": manifest["self_sha256"],
                "feed": str(feed_path.relative_to(REPO_ROOT)).replace("\\", "/"),
                "corpus": corpus_rel,
                "corpus_self_sha256": corpus["self_sha256"],
                "preserved": preserved.get("preserved"),
                "daz_added": daz.get("added"),
                "mw_expand_added": mw.get("added"),
            },
            sort_keys=True,
        )
    )
    return 0 if feasible_ge_100 and image_disjoint else 2


if __name__ == "__main__":
    raise SystemExit(main())
