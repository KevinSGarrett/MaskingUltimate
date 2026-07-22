"""Exact and perceptual split-group evidence for external-supervision images."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .external_supervision_evidence import publish_immutable_evidence, seal_payload
from .nude_corpus_dedup import anchored_dual_hash_pairs

SOURCE_KEYS = ("celebamask_hq", "lapa", "lv_mhp_v1")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


class ExternalDedupError(ValueError):
    """External-source dedup inputs or image bindings are invalid."""


class ExternalImageDecodeError(ExternalDedupError):
    """A hash-bound source image cannot be decoded and must be quarantined."""


def build_external_split_dedup_evidence(
    *,
    manifest_paths: Mapping[str, Path],
    source_roots: Mapping[str, Path],
    hamming_threshold: int = 3,
    phash_threshold: int = 6,
) -> dict[str, Any]:
    """Bind every eligible source image to one exact/perceptual split group."""

    if set(manifest_paths) != set(SOURCE_KEYS) or set(source_roots) != set(SOURCE_KEYS):
        raise ExternalDedupError("dedup requires all three canonical eligible sources")
    if not 0 <= hamming_threshold <= 7:
        raise ExternalDedupError("hamming threshold must be between 0 and 7")
    if not 0 <= phash_threshold <= 16:
        raise ExternalDedupError("pHash threshold must be between 0 and 16")

    records: list[dict[str, Any]] = []
    quarantined_records: list[dict[str, Any]] = []
    manifest_bindings: dict[str, dict[str, Any]] = {}
    for source in SOURCE_KEYS:
        manifest_path = Path(manifest_paths[source]).resolve(strict=True)
        manifest_bytes = manifest_path.read_bytes()
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExternalDedupError(f"invalid source manifest JSON: {source}") from exc
        _validate_manifest(manifest, source)
        root = Path(source_roots[source]).resolve(strict=True)
        split_map = _lv_mhp_split_map(root) if source == "lv_mhp_v1" else {}
        image_records = [item for item in manifest["files"] if _is_source_image(source, item)]
        if not image_records:
            raise ExternalDedupError(f"source manifest has no images: {source}")
        for item in image_records:
            relative = str(item["path"])
            try:
                image_path = (root / Path(relative)).resolve(strict=True)
                image_path.relative_to(root)
            except (FileNotFoundError, OSError, ValueError) as exc:
                raise ExternalDedupError(
                    f"image path escaped or is missing: {source}:{relative}"
                ) from exc
            if image_path.is_symlink() or not image_path.is_file():
                raise ExternalDedupError(f"image is not a regular file: {source}:{relative}")
            before = image_path.stat()
            raw_bytes = image_path.read_bytes()
            actual_sha = hashlib.sha256(raw_bytes).hexdigest()
            if actual_sha != item.get("sha256"):
                raise ExternalDedupError(f"source image hash drift: {source}:{relative}")
            upstream_split = _upstream_split(source, relative, split_map)
            try:
                dhash, phash = _perceptual_hashes(raw_bytes, identity=f"{source}:{relative}")
            except ExternalImageDecodeError:
                quarantined_records.append(
                    {
                        "record_id": f"{source}:{relative}",
                        "source": source,
                        "relative_path": relative,
                        "source_sha256": actual_sha,
                        "upstream_split": upstream_split,
                        "reason": "source_image_decode_failed",
                        "disposition": "excluded_from_qualification_and_training",
                    }
                )
                continue
            after = image_path.stat()
            if _stat_identity(before) != _stat_identity(after):
                raise ExternalDedupError(f"source image changed during dedup: {source}:{relative}")
            records.append(
                {
                    "record_id": f"{source}:{relative}",
                    "source": source,
                    "relative_path": relative,
                    "source_sha256": actual_sha,
                    "dhash64": f"{dhash:016x}",
                    "phash64": f"{phash:016x}",
                    "upstream_split": upstream_split,
                }
            )
        manifest_bindings[source] = {
            "path": str(manifest_path),
            "file_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "seal_sha256": manifest["seal_sha256"],
            "image_count": len(image_records),
        }

    records.sort(key=lambda item: item["record_id"].encode("utf-8"))
    quarantined_records.sort(key=lambda item: item["record_id"].encode("utf-8"))
    if len({record["record_id"] for record in records}) != len(records):
        raise ExternalDedupError("dedup record identities are not unique")
    parent = list(range(len(records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    exact_first: dict[str, int] = {}
    for index, record in enumerate(records):
        previous = exact_first.setdefault(record["source_sha256"], index)
        union(previous, index)
    exact_components: dict[int, list[int]] = {}
    for index in range(len(records)):
        exact_components.setdefault(find(index), []).append(index)
    ordered_components = sorted(
        exact_components.values(), key=lambda members: records[members[0]]["record_id"]
    )
    representatives = [
        min(
            members,
            key=lambda index: (
                records[index]["dhash64"],
                records[index]["phash64"],
                records[index]["record_id"],
            ),
        )
        for members in ordered_components
    ]
    for anchor, member in anchored_dual_hash_pairs(
        tuple(int(records[index]["dhash64"], 16) for index in representatives),
        tuple(int(records[index]["phash64"], 16) for index in representatives),
        dhash_threshold=hamming_threshold,
        phash_threshold=phash_threshold,
    ):
        union(ordered_components[anchor][0], ordered_components[member][0])

    groups: dict[int, list[int]] = {}
    for index in range(len(records)):
        groups.setdefault(find(index), []).append(index)
    group_summaries: list[dict[str, Any]] = []
    cross_source_exact = 0
    perceptual_only = 0
    upstream_conflicts = 0
    for members in sorted(groups.values(), key=lambda values: records[values[0]]["record_id"]):
        member_ids = [records[index]["record_id"] for index in members]
        group_id = (
            "external_group_"
            + hashlib.sha256("\n".join(member_ids).encode("utf-8")).hexdigest()[:24]
        )
        for index in members:
            records[index]["split_group_id"] = group_id
        sources = {records[index]["source"] for index in members}
        shas = {records[index]["source_sha256"] for index in members}
        splits = {
            records[index]["upstream_split"]
            for index in members
            if records[index]["upstream_split"] != "unspecified"
        }
        if len(members) > 1 and len(sources) > 1 and len(shas) == 1:
            cross_source_exact += 1
        if len(members) > 1 and len(shas) > 1:
            perceptual_only += 1
        if len(splits) > 1:
            upstream_conflicts += 1
        group_summaries.append(
            {
                "split_group_id": group_id,
                "member_count": len(members),
                "sources": sorted(sources),
                "upstream_splits": sorted(splits),
                "exact_sha_count": len(shas),
            }
        )

    evidence: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "external_supervision_split_dedup_evidence",
        "source": "all_eligible_external_sources",
        "gate": "split_dedup_passed",
        "status": "PASS",
        "hash_algorithm": "sha256",
        "perceptual_hash": "dhash64_9x8_bilinear",
        "secondary_perceptual_hash": "phash64_dct_32x32_top8",
        "hamming_threshold": hamming_threshold,
        "phash_threshold": phash_threshold,
        "near_duplicate_rule": (
            f"anchored_dhash_lte_{hamming_threshold}_and_phash_lte_{phash_threshold}"
        ),
        "partition_rule": "all records sharing split_group_id must remain in one downstream partition",
        "manifest_bindings": manifest_bindings,
        "source_image_count": len(records) + len(quarantined_records),
        "record_count": len(records),
        "quarantined_record_count": len(quarantined_records),
        "split_group_count": len(groups),
        "duplicate_record_count": len(records) - len(groups),
        "cross_source_exact_group_count": cross_source_exact,
        "perceptual_only_group_count": perceptual_only,
        "upstream_split_conflict_group_count": upstream_conflicts,
        "groups": group_summaries,
        "records": records,
        "quarantined_records": quarantined_records,
    }
    evidence["seal_sha256"] = seal_payload(evidence)
    return evidence


def find_hamming_pairs(values: Sequence[int], *, threshold: int) -> tuple[tuple[int, int], ...]:
    """Find all 64-bit pairs within a small Hamming radius using disjoint blocks."""

    if not 0 <= threshold <= 7:
        raise ExternalDedupError("hamming threshold must be between 0 and 7")
    block_count = threshold + 1
    base_width, remainder = divmod(64, block_count)
    blocks: list[tuple[int, int]] = []
    shift = 0
    for index in range(block_count):
        width = base_width + int(index < remainder)
        blocks.append((shift, (1 << width) - 1))
        shift += width
    buckets: dict[tuple[int, int], list[int]] = {}
    pairs: list[tuple[int, int]] = []
    for index, value in enumerate(values):
        if not 0 <= value < 2**64:
            raise ExternalDedupError("perceptual hashes must be unsigned 64-bit integers")
        candidates: set[int] = set()
        for block_index, (block_shift, mask) in enumerate(blocks):
            candidates.update(buckets.get((block_index, (value >> block_shift) & mask), ()))
        for candidate in sorted(candidates):
            if (values[candidate] ^ value).bit_count() <= threshold:
                pairs.append((candidate, index))
        for block_index, (block_shift, mask) in enumerate(blocks):
            buckets.setdefault((block_index, (value >> block_shift) & mask), []).append(index)
    return tuple(sorted(pairs))


def _validate_manifest(manifest: Mapping[str, Any], source: str) -> None:
    if (
        manifest.get("artifact_type") != "external_supervision_source_hash_manifest"
        or manifest.get("source") != source
        or manifest.get("status") != "PASS"
        or manifest.get("seal_sha256") != seal_payload(manifest)
        or not isinstance(manifest.get("files"), list)
    ):
        raise ExternalDedupError(f"source manifest contract or seal is invalid: {source}")


def _is_source_image(source: str, item: Mapping[str, Any]) -> bool:
    path = item.get("path")
    if not isinstance(path, str) or Path(path).suffix.casefold() not in IMAGE_SUFFIXES:
        return False
    normalized = path.replace("\\", "/")
    if source == "celebamask_hq":
        return normalized.startswith("CelebA-HQ-img/")
    if source == "lapa":
        return any(normalized.startswith(f"{split}/images/") for split in ("train", "val", "test"))
    return normalized.startswith("LV-MHP-v1/images/")


def _upstream_split(source: str, relative: str, split_map: Mapping[str, str]) -> str:
    if source == "lapa":
        return relative.split("/", 1)[0]
    if source == "lv_mhp_v1":
        stem = Path(relative).stem
        if stem not in split_map:
            raise ExternalDedupError(f"LV-MHP image is absent from upstream split lists: {stem}")
        return split_map[stem]
    return "unspecified"


def _lv_mhp_split_map(root: Path) -> dict[str, str]:
    content = root / "LV-MHP-v1" if (root / "LV-MHP-v1").is_dir() else root
    result: dict[str, str] = {}
    for filename, split in (("train_list.txt", "train"), ("test_list.txt", "test")):
        path = content / filename
        if not path.is_file():
            raise ExternalDedupError(f"LV-MHP split list is missing: {filename}")
        for raw in path.read_text(encoding="utf-8").splitlines():
            stem = Path(raw.strip()).stem
            if not stem:
                continue
            if stem in result:
                raise ExternalDedupError(f"LV-MHP image crosses upstream split lists: {stem}")
            result[stem] = split
    return result


def _perceptual_hashes(raw_bytes: bytes, *, identity: str) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(raw_bytes)) as opened:
            image = ImageOps.exif_transpose(opened.convert("RGB"))
            grayscale = image.convert("L")
            gradient = grayscale.resize((9, 8), Image.Resampling.BILINEAR)
            dct_input = np.asarray(
                grayscale.resize((32, 32), Image.Resampling.BILINEAR), dtype=np.float64
            )
    except (OSError, UnidentifiedImageError) as exc:
        raise ExternalImageDecodeError(f"cannot decode source image: {identity}") from exc
    pixels = gradient.tobytes()
    dhash = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            dhash = (dhash << 1) | int(pixels[offset + column + 1] > pixels[offset + column])
    coordinates = np.arange(32, dtype=np.float64)
    frequencies = np.arange(8, dtype=np.float64)[:, None]
    dct_matrix = np.cos(np.pi * (2 * coordinates + 1) * frequencies / 64.0)
    dct_matrix[0] *= 1.0 / np.sqrt(2.0)
    dct_matrix *= np.sqrt(2.0 / 32.0)
    coefficients = dct_matrix @ dct_input @ dct_matrix.T
    median = float(np.median(coefficients.flatten()[1:]))
    phash = 0
    for value in coefficients.flatten():
        phash = (phash << 1) | int(float(value) > median)
    return dhash, phash


def _stat_identity(value: Any) -> tuple[int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for source in SOURCE_KEYS:
        parser.add_argument(f"--{source}-manifest", type=Path, required=True)
        parser.add_argument(f"--{source}-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hamming-threshold", type=int, default=3)
    parser.add_argument("--phash-threshold", type=int, default=6)
    args = parser.parse_args(argv)
    manifests = {source: getattr(args, f"{source}_manifest") for source in SOURCE_KEYS}
    roots = {source: getattr(args, f"{source}_root") for source in SOURCE_KEYS}
    evidence = build_external_split_dedup_evidence(
        manifest_paths=manifests,
        source_roots=roots,
        hamming_threshold=args.hamming_threshold,
        phash_threshold=args.phash_threshold,
    )
    file_sha256 = publish_immutable_evidence(evidence, args.output)
    print(
        json.dumps(
            {
                "status": "PASS",
                "record_count": evidence["record_count"],
                "split_group_count": evidence["split_group_count"],
                "duplicate_record_count": evidence["duplicate_record_count"],
                "upstream_split_conflict_group_count": evidence[
                    "upstream_split_conflict_group_count"
                ],
                "evidence_path": str(args.output.resolve()),
                "evidence_file_sha256": file_sha256,
                "evidence_seal_sha256": evidence["seal_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ExternalDedupError",
    "build_external_split_dedup_evidence",
    "find_hamming_pairs",
]
