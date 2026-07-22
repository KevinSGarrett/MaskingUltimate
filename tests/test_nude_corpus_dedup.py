from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from maskfactory.nude_corpus_dedup import (
    NudeCorpusDedupError,
    anchored_dual_hash_pairs,
    anchored_hamming_pairs,
    assert_partition_isolation,
    group_records,
    load_group_evidence,
    normalized_source_family_key,
    write_group_evidence,
)


def _record(
    sample: str,
    *,
    dataset: str,
    lineage: str,
    path: str,
    sha: str,
    split: str,
    role: str = "polygon_external_supervision",
) -> dict[str, object]:
    return {
        "sample_id": sample,
        "dataset_id": dataset,
        "lineage_group": lineage,
        "source_family": dataset,
        "source_relative_path": path,
        "source_sha256": sha,
        "source_role": role,
        "source_split": split,
    }


def test_correlated_versions_exact_and_near_duplicates_share_strictest_partition() -> None:
    records = [
        _record(
            "main-v3",
            dataset="main.v3",
            lineage="main",
            path="main.v3/train/photo_jpg.rf.aaaaaaaa.jpg",
            sha="a" * 64,
            split="train",
        ),
        _record(
            "main-v4",
            dataset="main.v4",
            lineage="main",
            path="main.v4/valid/photo_jpg.rf.bbbbbbbb.jpg",
            sha="b" * 64,
            split="valid",
        ),
        _record(
            "mange-v2",
            dataset="mange.v2",
            lineage="mange",
            path="mange.v2/train/frame-a.jpg",
            sha="c" * 64,
            split="train",
        ),
        _record(
            "mange-v3",
            dataset="mange.v3",
            lineage="mange",
            path="mange.v3/test/frame-b.jpg",
            sha="d" * 64,
            split="test",
        ),
        _record(
            "holdout",
            dataset="benchmark",
            lineage="benchmark",
            path="benchmark/test/holdout.jpg",
            sha="e" * 64,
            split="test",
            role="bbox_evaluation_only",
        ),
        _record(
            "holdout-copy",
            dataset="other",
            lineage="other",
            path="other/train/copy.jpg",
            sha="e" * 64,
            split="train",
        ),
    ]
    grouped, summary = group_records(
        records,
        dhashes=(
            0x10,
            0x11,
            0xFFFF000000000000,
            0xFFFF000000000001,
            0xFFFFFFFFFFFFFFFF,
            0xFFFFFFFFFFFFFFFF,
        ),
        phashes=(
            0x10,
            0x11,
            0xFFFF000000000000,
            0xFFFF000000000001,
            0xFFFFFFFFFFFFFFFF,
            0xFFFFFFFFFFFFFFFF,
        ),
    )
    by_id = {row["sample_id"]: row for row in grouped}
    assert by_id["main-v3"]["split_group_id"] == by_id["main-v4"]["split_group_id"]
    assert by_id["main-v3"]["assigned_partition"] == "validation"
    assert by_id["mange-v2"]["split_group_id"] == by_id["mange-v3"]["split_group_id"]
    assert by_id["mange-v2"]["assigned_partition"] == "test"
    assert by_id["holdout-copy"]["assigned_partition"] == "holdout"
    assert summary["record_count"] == 6
    assert_partition_isolation(grouped)


def test_roboflow_suffix_is_removed_only_inside_lineage() -> None:
    first = _record(
        "a",
        dataset="main.v3",
        lineage="main",
        path="train/example_jpg.rf.0123456789abcdef.jpg",
        sha="a" * 64,
        split="train",
    )
    second = deepcopy(first)
    second.update(sample_id="b", dataset_id="main.v4")
    assert normalized_source_family_key(first) == "main:example"
    assert normalized_source_family_key(first) == normalized_source_family_key(second)


def test_partition_preflight_rejects_one_group_in_multiple_partitions() -> None:
    records = [
        {"sample_id": "a", "split_group_id": "group", "assigned_partition": "train"},
        {"sample_id": "b", "split_group_id": "group", "assigned_partition": "test"},
    ]
    with pytest.raises(NudeCorpusDedupError, match="split group leakage"):
        assert_partition_isolation(records)


def test_invalid_or_duplicate_identity_fails_closed() -> None:
    record = _record(
        "duplicate",
        dataset="one",
        lineage="one",
        path="one/a.jpg",
        sha="a" * 64,
        split="train",
    )
    with pytest.raises(NudeCorpusDedupError, match="not unique"):
        group_records([record, deepcopy(record)], dhashes=(0, 1), phashes=(0, 1))


def test_anchored_hamming_groups_do_not_transitively_chain() -> None:
    assert anchored_hamming_pairs((0, 1, 3, 7), threshold=1) == ((0, 1), (2, 3))


def test_dual_hash_requires_secondary_visual_agreement() -> None:
    assert anchored_dual_hash_pairs(
        (0, 1, 3),
        (0, 0xFFFF, 1),
        dhash_threshold=2,
        phash_threshold=1,
    ) == ((0, 2),)


def test_downstream_loader_rejects_mapping_or_summary_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    records = [
        {
            "sample_id": "sample",
            "split_group_id": "group",
            "assigned_partition": "train",
        }
    ]
    summary = {
        "record_count": 1,
        "split_group_count": 1,
        "partition_counts": {"train": 1},
    }
    write_group_evidence(records, summary, tmp_path)
    monkeypatch.setattr("maskfactory.nude_corpus_dedup.ADOPTED_RECORD_COUNT", 1)
    loaded = load_group_evidence(tmp_path / "summary.json", tmp_path / "split_groups.jsonl")
    assert set(loaded) == {"sample"}

    mapping = tmp_path / "split_groups.jsonl"
    mapping.write_text(mapping.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
    with pytest.raises(NudeCorpusDedupError, match="mapping hash mismatch"):
        load_group_evidence(tmp_path / "summary.json", mapping)

    mapping.write_text(
        json.dumps(records[0], sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    summary_path = tmp_path / "summary.json"
    document = json.loads(summary_path.read_text(encoding="utf-8"))
    document["status"] = "DRIFT"
    summary_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(NudeCorpusDedupError, match="summary self hash mismatch"):
        load_group_evidence(summary_path, mapping)
