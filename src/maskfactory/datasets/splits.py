"""Hash-stable image-level dataset splits with duplicate and holdout protection."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class SplitRecord:
    image_id: str
    phash64: str
    source_origin: str


def assign_splits(
    records: tuple[SplitRecord, ...], *, hard_case_ids: frozenset[str] = frozenset()
) -> dict[str, str]:
    """Assign one split per image; pHash-connected groups can never cross partitions."""
    if len({record.image_id for record in records}) != len(records):
        raise ValueError("split records require unique image IDs")
    ordered = tuple(sorted(records, key=lambda item: item.image_id))
    parent = list(range(len(ordered)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    hashes = [_phash(record.phash64) for record in ordered]
    for left in range(len(ordered)):
        for right in range(left + 1, len(ordered)):
            if (hashes[left] ^ hashes[right]).bit_count() <= 6:
                union(left, right)
    groups: dict[int, list[SplitRecord]] = {}
    for index, record in enumerate(ordered):
        groups.setdefault(find(index), []).append(record)
    result = {}
    for group in groups.values():
        if any(record.image_id in hard_case_ids for record in group):
            split = "hard_case_holdout"
        elif any(record.source_origin in {"synthetic", "generated"} for record in group):
            split = "train"
        else:
            split = hash_split(group[0].image_id)
        for record in group:
            result[record.image_id] = split
    return result


def hash_split(image_id: str) -> str:
    bucket = int(hashlib.sha256(image_id.encode("utf-8")).hexdigest()[:8], 16) % 100
    return "train" if bucket <= 69 else "val" if bucket <= 84 else "test_holdout"


def validate_instance_split_integrity(instance_splits: dict[str, str]) -> None:
    """Reject any image whose pN instances were assigned to different partitions."""
    by_image: dict[str, set[str]] = {}
    for instance_id, split in instance_splits.items():
        try:
            image_id, suffix = instance_id.rsplit("_p", 1)
            int(suffix)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid per-instance split key: {instance_id}") from exc
        by_image.setdefault(image_id, set()).add(split)
    leaked = {image_id: sorted(values) for image_id, values in by_image.items() if len(values) > 1}
    if leaked:
        raise ValueError(f"multi-instance split leakage: {leaked}")


def _phash(value: str) -> int:
    try:
        parsed = int(value, 16)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid 64-bit pHash: {value!r}") from exc
    if not 0 <= parsed < 2**64:
        raise ValueError(f"invalid 64-bit pHash: {value!r}")
    return parsed
