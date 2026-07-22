"""Full-corpus exact, perceptual, and correlated-family leakage grouping."""

from __future__ import annotations

import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .nude_corpus_intake import ADOPTED_RECORD_COUNT, load_adopted_intake, load_records

PARTITION_PRECEDENCE = {"train": 0, "validation": 1, "test": 2, "holdout": 3}
ROBOFLOW_SUFFIX = re.compile(r"\.rf\.[0-9a-f]{8,}$", re.IGNORECASE)
ENCODING_SUFFIX = re.compile(r"_(?:jpg|jpeg|png)$", re.IGNORECASE)


class NudeCorpusDedupError(RuntimeError):
    """A source identity, decode, group, or leakage invariant failed closed."""


class _UnionFind:
    def __init__(self, count: int) -> None:
        self.parent = list(range(count))

    def find(self, index: int) -> int:
        while self.parent[index] != index:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def anchored_hamming_pairs(values: Sequence[int], *, threshold: int) -> tuple[tuple[int, int], ...]:
    """Cluster around fixed representatives so Hamming-neighbor chains cannot collapse a corpus."""

    if not 0 <= threshold <= 7:
        raise NudeCorpusDedupError("hamming threshold must be between 0 and 7")
    block_count = threshold + 1
    base_width, remainder = divmod(64, block_count)
    blocks: list[tuple[int, int]] = []
    shift = 0
    for index in range(block_count):
        width = base_width + int(index < remainder)
        blocks.append((shift, (1 << width) - 1))
        shift += width
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    anchors: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for index, value in enumerate(values):
        if not 0 <= value < 2**64:
            raise NudeCorpusDedupError("perceptual hashes must be unsigned 64-bit integers")
        candidates: set[int] = set()
        for block_index, (block_shift, mask) in enumerate(blocks):
            candidates.update(buckets.get((block_index, (value >> block_shift) & mask), ()))
        eligible = [
            candidate
            for candidate in candidates
            if candidate in anchors and (values[candidate] ^ value).bit_count() <= threshold
        ]
        if eligible:
            anchor = min(
                eligible, key=lambda candidate: ((values[candidate] ^ value).bit_count(), candidate)
            )
            pairs.append((anchor, index))
            continue
        anchors.add(index)
        for block_index, (block_shift, mask) in enumerate(blocks):
            buckets[(block_index, (value >> block_shift) & mask)].append(index)
    return tuple(pairs)


def anchored_dual_hash_pairs(
    dhashes: Sequence[int],
    phashes: Sequence[int],
    *,
    dhash_threshold: int,
    phash_threshold: int,
) -> tuple[tuple[int, int], ...]:
    """Require both edge-gradient and DCT similarity against a fixed anchor."""

    if len(dhashes) != len(phashes):
        raise NudeCorpusDedupError("dual perceptual hash coverage mismatch")
    candidates = anchored_hamming_pairs(dhashes, threshold=dhash_threshold)
    return tuple(
        (anchor, member)
        for anchor, member in candidates
        if (phashes[anchor] ^ phashes[member]).bit_count() <= phash_threshold
    )


def normalized_source_family_key(record: Mapping[str, Any]) -> str:
    """Recover the pre-augmentation filename identity inside one lineage group."""

    lineage = str(record.get("lineage_group") or "").casefold().strip()
    relative = str(record.get("source_relative_path") or "").replace("\\", "/")
    stem = Path(relative).stem.casefold()
    stem = ENCODING_SUFFIX.sub("", ROBOFLOW_SUFFIX.sub("", stem))
    if not lineage or not stem:
        raise NudeCorpusDedupError("source family identity missing")
    return f"{lineage}:{stem}"


def requested_partition(record: Mapping[str, Any]) -> str:
    if record.get("source_role") == "bbox_evaluation_only":
        return "holdout"
    split = str(record.get("source_split") or "").casefold()
    if split in {"valid", "val", "validation"}:
        return "validation"
    if split in {"test", "evaluation", "eval"}:
        return "test"
    return "train"


def group_records(
    records: Sequence[Mapping[str, Any]],
    *,
    dhashes: Sequence[int],
    phashes: Sequence[int],
    hamming_threshold: int = 3,
    phash_threshold: int = 6,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Assign every record to one unioned group and one leakage-safe partition."""

    if len(records) != len(dhashes) or len(records) != len(phashes) or not records:
        raise NudeCorpusDedupError("record/hash coverage mismatch")
    if len({str(record.get("sample_id")) for record in records}) != len(records):
        raise NudeCorpusDedupError("sample identities are not unique")
    union = _UnionFind(len(records))
    exact_first: dict[str, int] = {}
    family_first: dict[str, int] = {}
    for index, (record, dhash) in enumerate(zip(records, dhashes, strict=True)):
        source_sha = str(record.get("source_sha256") or "")
        if len(source_sha) != 64 or not 0 <= dhash < 2**64:
            raise NudeCorpusDedupError("source or perceptual hash invalid")
        union.union(exact_first.setdefault(source_sha, index), index)
        family = normalized_source_family_key(record)
        union.union(family_first.setdefault(family, index), index)
    base_components: dict[int, list[int]] = defaultdict(list)
    for index in range(len(records)):
        base_components[union.find(index)].append(index)
    ordered_components = sorted(
        base_components.values(),
        key=lambda members: min(str(records[index]["sample_id"]) for index in members),
    )
    representative_indices = [
        min(
            members,
            key=lambda index: (dhashes[index], phashes[index], str(records[index]["sample_id"])),
        )
        for members in ordered_components
    ]
    representative_dhashes = [dhashes[index] for index in representative_indices]
    representative_phashes = [phashes[index] for index in representative_indices]
    for anchor, member in anchored_dual_hash_pairs(
        representative_dhashes,
        representative_phashes,
        dhash_threshold=hamming_threshold,
        phash_threshold=phash_threshold,
    ):
        union.union(ordered_components[anchor][0], ordered_components[member][0])

    grouped: dict[int, list[int]] = defaultdict(list)
    for index in range(len(records)):
        grouped[union.find(index)].append(index)
    output: list[dict[str, Any]] = [{} for _ in records]
    cross_partition_groups = 0
    cross_dataset_groups = 0
    exact_duplicate_groups = 0
    perceptual_or_family_groups = 0
    partition_counts: Counter[str] = Counter()
    group_size_counts: Counter[int] = Counter()
    for members in grouped.values():
        ordered = sorted(members, key=lambda index: str(records[index]["sample_id"]))
        member_ids = [str(records[index]["sample_id"]) for index in ordered]
        group_id = "nude_group_" + hashlib.sha256("\n".join(member_ids).encode()).hexdigest()[:24]
        requested = {requested_partition(records[index]) for index in ordered}
        assigned = max(requested, key=lambda partition: PARTITION_PRECEDENCE[partition])
        datasets = {str(records[index]["dataset_id"]) for index in ordered}
        exact_shas = {str(records[index]["source_sha256"]) for index in ordered}
        families = {normalized_source_family_key(records[index]) for index in ordered}
        if len(requested) > 1:
            cross_partition_groups += 1
        if len(datasets) > 1:
            cross_dataset_groups += 1
        if len(ordered) > 1 and len(exact_shas) == 1:
            exact_duplicate_groups += 1
        if len(ordered) > 1 and (len(exact_shas) > 1 or len(families) == 1):
            perceptual_or_family_groups += 1
        group_size_counts[len(ordered)] += 1
        for index in ordered:
            record = records[index]
            partition_counts[assigned] += 1
            output[index] = {
                "sample_id": record["sample_id"],
                "dataset_id": record["dataset_id"],
                "lineage_group": record["lineage_group"],
                "source_family": record["source_family"],
                "source_relative_path": record["source_relative_path"],
                "source_sha256": record["source_sha256"],
                "dhash64": f"{dhashes[index]:016x}",
                "phash64": f"{phashes[index]:016x}",
                "normalized_source_family_key": normalized_source_family_key(record),
                "source_role": record["source_role"],
                "source_split": record["source_split"],
                "requested_partition": requested_partition(record),
                "assigned_partition": assigned,
                "split_group_id": group_id,
                "split_group_size": len(ordered),
            }
    if any(not row for row in output):
        raise NudeCorpusDedupError("not every record received a group")
    summary = {
        "record_count": len(output),
        "split_group_count": len(grouped),
        "duplicate_record_count": len(output) - len(grouped),
        "cross_partition_group_count": cross_partition_groups,
        "cross_dataset_group_count": cross_dataset_groups,
        "exact_duplicate_group_count": exact_duplicate_groups,
        "perceptual_or_family_group_count": perceptual_or_family_groups,
        "partition_counts": dict(sorted(partition_counts.items())),
        "group_size_histogram": {
            str(key): value for key, value in sorted(group_size_counts.items())
        },
        "hamming_threshold": hamming_threshold,
        "phash_threshold": phash_threshold,
        "near_duplicate_rule": "anchored_dhash_lte_3_and_phash_lte_6",
        "partition_precedence": ["train", "validation", "test", "holdout"],
    }
    return output, summary


def _decode_and_hash(record: Mapping[str, Any]) -> tuple[int, int]:
    path = Path(str(record["source_path_readonly"]))
    try:
        before = path.stat()
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != record["source_sha256"]:
            raise NudeCorpusDedupError(f"source hash drift:{record['sample_id']}")
        with Image.open(io.BytesIO(raw)) as opened:
            image = ImageOps.exif_transpose(opened.convert("RGB"))
            grayscale = image.convert("L")
            gradient = grayscale.resize((9, 8), Image.Resampling.BILINEAR)
            dct_input = np.asarray(
                grayscale.resize((32, 32), Image.Resampling.BILINEAR), dtype=np.float64
            )
        after = path.stat()
    except (OSError, UnidentifiedImageError) as exc:
        raise NudeCorpusDedupError(f"source decode failed:{record['sample_id']}") from exc
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise NudeCorpusDedupError(f"source changed during grouping:{record['sample_id']}")
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


def build_full_corpus_groups(
    intake_root: Path,
    *,
    workers: int = 8,
    hamming_threshold: int = 3,
    phash_threshold: int = 6,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    intake = load_adopted_intake(intake_root, platform="local")
    records_by_id = load_records(intake)
    records = [records_by_id[key] for key in sorted(records_by_id)]
    if len(records) != ADOPTED_RECORD_COUNT:
        raise NudeCorpusDedupError("adopted record count drift")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        hash_pairs = list(executor.map(_decode_and_hash, records, chunksize=32))
    dhashes = [pair[0] for pair in hash_pairs]
    phashes = [pair[1] for pair in hash_pairs]
    grouped, summary = group_records(
        records,
        dhashes=dhashes,
        phashes=phashes,
        hamming_threshold=hamming_threshold,
        phash_threshold=phash_threshold,
    )
    summary.update(
        {
            "schema_version": "maskfactory.nude_corpus_split_groups.v1",
            "artifact_type": "nude_corpus_split_group_summary",
            "registry_sha256": intake["registry"]["self_sha256"],
            "shard_index_sha256": intake["index"]["self_sha256"],
            "source_hashes_verified": True,
            "perceptual_hash": "dhash64_9x8_bilinear",
            "secondary_perceptual_hash": "phash64_dct_32x32_top8",
        }
    )
    return grouped, summary


def write_group_evidence(
    records: Sequence[Mapping[str, Any]], summary: Mapping[str, Any], output_dir: Path
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping_path = output_dir / "split_groups.jsonl"
    stream_hash = hashlib.sha256()
    with mapping_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            line = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            handle.write(line + "\n")
            stream_hash.update((line + "\n").encode("utf-8"))
    result = dict(summary)
    result["mapping_path"] = str(mapping_path.resolve())
    result["mapping_file_sha256"] = hashlib.sha256(mapping_path.read_bytes()).hexdigest()
    result["mapping_stream_sha256"] = stream_hash.hexdigest()
    result["status"] = "PASS"
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    result["self_sha256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    (output_dir / "summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def load_group_evidence(summary_path: Path, mapping_path: Path) -> dict[str, dict[str, Any]]:
    """Fail closed before downstream qualification or partition selection uses the mapping."""

    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    claimed_self = summary.pop("self_sha256", None)
    encoded = json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if claimed_self != hashlib.sha256(encoded.encode("utf-8")).hexdigest():
        raise NudeCorpusDedupError("split-group summary self hash mismatch")
    mapping = Path(mapping_path)
    if hashlib.sha256(mapping.read_bytes()).hexdigest() != summary.get("mapping_file_sha256"):
        raise NudeCorpusDedupError("split-group mapping hash mismatch")
    records: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    with mapping.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise NudeCorpusDedupError(f"split-group JSONL invalid:{line_number}") from exc
            sample_id = str(record.get("sample_id") or "")
            if not sample_id or sample_id in by_id:
                raise NudeCorpusDedupError("split-group sample identity invalid")
            by_id[sample_id] = record
            records.append(record)
    assert_partition_isolation(records)
    if len(records) != summary.get("record_count") or len(records) != ADOPTED_RECORD_COUNT:
        raise NudeCorpusDedupError("split-group mapping coverage mismatch")
    if len({record["split_group_id"] for record in records}) != summary.get("split_group_count"):
        raise NudeCorpusDedupError("split-group count mismatch")
    observed_partitions = dict(
        sorted(Counter(record["assigned_partition"] for record in records).items())
    )
    if observed_partitions != summary.get("partition_counts"):
        raise NudeCorpusDedupError("split-group partition totals mismatch")
    return by_id


def assert_partition_isolation(records: Sequence[Mapping[str, Any]]) -> None:
    observed: dict[str, str] = {}
    for record in records:
        group = str(record.get("split_group_id") or "")
        partition = str(record.get("assigned_partition") or "")
        if not group or partition not in PARTITION_PRECEDENCE:
            raise NudeCorpusDedupError("partition record invalid")
        previous = observed.setdefault(group, partition)
        if previous != partition:
            raise NudeCorpusDedupError(f"split group leakage:{group}:{previous}:{partition}")


__all__ = [
    "NudeCorpusDedupError",
    "anchored_hamming_pairs",
    "anchored_dual_hash_pairs",
    "assert_partition_isolation",
    "build_full_corpus_groups",
    "group_records",
    "load_group_evidence",
    "normalized_source_family_key",
    "requested_partition",
    "write_group_evidence",
]
