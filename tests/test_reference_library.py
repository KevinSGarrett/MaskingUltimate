import hashlib
import sqlite3
from pathlib import Path

import pytest

from maskfactory.reference_library import (
    ReferenceLibraryError,
    inspect_reference_database,
    inspect_reference_selection,
    load_reference_library_policy,
    materialize_reference_tier,
    validate_benchmark_training_isolation,
    validate_reference_library_policy,
    validate_reference_selection,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs" / "reference_library.yaml"


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "reference.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE images (
          relative_path TEXT PRIMARY KEY, sha256 TEXT, dhash64 TEXT,
          size_bytes INTEGER DEFAULT 0
        );
        CREATE TABLE exact_members (
          relative_path TEXT, is_representative INTEGER
        );
        CREATE TABLE visual_index (
          relative_path TEXT, status TEXT, tags_json TEXT DEFAULT '[]',
          content_state TEXT DEFAULT 'clothed', person_count TEXT DEFAULT 'one'
        );
        CREATE TABLE selections (
          relative_path TEXT, tier TEXT, materialized_path TEXT,
          materialized_sha256 TEXT, rank INTEGER DEFAULT 0,
          selection_score REAL DEFAULT 0, selection_reasons_json TEXT DEFAULT '{}',
          materialized_at TEXT
        );
        CREATE TABLE near_duplicate_members (
          relative_path TEXT, cluster_id TEXT, representative_path TEXT,
          group_size INTEGER, similarity REAL
        );
        CREATE TABLE pipeline_meta (
          key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT
        );
        CREATE TABLE pipeline_runs (
          id INTEGER, stage TEXT, started_at TEXT, completed_at TEXT,
          processed INTEGER, failed INTEGER
        );
        """
    )
    connection.commit()
    connection.close()
    return path


def _small_policy() -> dict:
    policy = load_reference_library_policy(POLICY)
    policy["tiers"]["benchmark_reference"]["target_count"] = 1
    policy["tiers"]["retrieval_reference"]["target_count"] = 1
    return policy


def _small_policy_at(output_root: Path) -> dict:
    policy = _small_policy()
    policy["source_root"] = str(output_root.resolve())
    policy["output_root"] = str(output_root.resolve())
    return policy


def test_reference_policy_has_no_truth_and_explicitly_keeps_governed_adult_material():
    policy = load_reference_library_policy(POLICY)
    assert policy["truth_authority"] == "none"
    assert policy["content_policy"]["adult_content_is_eligible"] is True
    assert policy["content_policy"]["nsfw_tag_is_organizational_not_an_exclusion"] is True
    assert policy["content_policy"]["known_or_suspected_minor_is_prohibited"] is True


def test_reference_policy_rejects_any_training_authority():
    policy = load_reference_library_policy(POLICY)
    policy["tiers"]["retrieval_reference"]["training_eligible"] = True
    with pytest.raises(ReferenceLibraryError, match="training/truth authority"):
        validate_reference_library_policy(policy)


def test_status_and_selection_validation_are_read_only_and_hash_checked(tmp_path: Path):
    database = _database(tmp_path)
    benchmark = tmp_path / "benchmark.jpg"
    retrieval = tmp_path / "retrieval.jpg"
    benchmark.write_bytes(b"benchmark")
    retrieval.write_bytes(b"retrieval")
    sha_b = hashlib.sha256(benchmark.read_bytes()).hexdigest()
    sha_r = hashlib.sha256(retrieval.read_bytes()).hexdigest()
    connection = sqlite3.connect(database)
    connection.executemany(
        "INSERT INTO images(relative_path,sha256,dhash64) VALUES (?,?,?)",
        [("a.jpg", sha_b, "0000000000000001"), ("b.jpg", sha_r, "0000000000000002")],
    )
    connection.executemany("INSERT INTO exact_members VALUES (?,1)", [("a.jpg",), ("b.jpg",)])
    connection.executemany(
        "INSERT INTO visual_index(relative_path,status) VALUES (?, 'valid')",
        [("a.jpg",), ("b.jpg",)],
    )
    connection.executemany(
        "INSERT INTO selections(relative_path,tier,materialized_path,materialized_sha256) "
        "VALUES (?,?,?,?)",
        [
            ("a.jpg", "benchmark_reference", str(benchmark), sha_b),
            ("b.jpg", "retrieval_reference", str(retrieval), sha_r),
        ],
    )
    connection.execute("INSERT INTO pipeline_runs VALUES (1,'index','t0','t1',2,0)")
    connection.commit()
    connection.close()

    status = inspect_reference_database(database)
    assert status["index_progress"] == {
        "classified": 2,
        "remaining": 0,
        "percent": 100.0,
        "complete": True,
    }
    report = validate_reference_selection(database, _small_policy_at(tmp_path))
    assert report["passed"] is True
    assert report["selection_counts"] == {
        "benchmark_reference": 1,
        "retrieval_reference": 1,
    }
    assert validate_benchmark_training_isolation(database, []) == ()
    assert validate_benchmark_training_isolation(
        database, [{"source_sha256": sha_b, "dhash64": "f" * 16}]
    ) == (f"exact_overlap:0:{sha_b}",)


def test_selection_validator_detects_tier_sha_overlap(tmp_path: Path):
    database = _database(tmp_path)
    materialized = tmp_path / "same.jpg"
    materialized.write_bytes(b"same")
    sha = hashlib.sha256(materialized.read_bytes()).hexdigest()
    connection = sqlite3.connect(database)
    connection.executemany(
        "INSERT INTO images(relative_path,sha256,dhash64) VALUES (?,?,?)",
        [("a.jpg", sha, "1"), ("b.jpg", sha, "1")],
    )
    connection.executemany(
        "INSERT INTO selections(relative_path,tier,materialized_path,materialized_sha256) "
        "VALUES (?,?,?,?)",
        [
            ("a.jpg", "benchmark_reference", str(materialized), sha),
            ("b.jpg", "retrieval_reference", str(materialized), sha),
        ],
    )
    connection.commit()
    connection.close()
    report = validate_reference_selection(database, _small_policy_at(tmp_path))
    assert report["passed"] is False
    assert "exact_sha256_overlap_between_tiers" in report["issues"]


def test_selection_validator_resolves_relative_output_and_rejects_escape(tmp_path: Path):
    database = _database(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    benchmark = output / "benchmark.jpg"
    retrieval = output / "retrieval.jpg"
    benchmark.write_bytes(b"benchmark")
    retrieval.write_bytes(b"retrieval")
    sha_b = hashlib.sha256(benchmark.read_bytes()).hexdigest()
    sha_r = hashlib.sha256(retrieval.read_bytes()).hexdigest()
    connection = sqlite3.connect(database)
    connection.executemany(
        "INSERT INTO images(relative_path,sha256,dhash64) VALUES (?,?,?)",
        [("a.jpg", sha_b, "1"), ("b.jpg", sha_r, "2")],
    )
    connection.executemany(
        "INSERT INTO selections(relative_path,tier,materialized_path,materialized_sha256) "
        "VALUES (?,?,?,?)",
        [
            ("a.jpg", "benchmark_reference", "benchmark.jpg", sha_b),
            ("b.jpg", "retrieval_reference", "retrieval.jpg", sha_r),
        ],
    )
    connection.commit()
    connection.close()
    policy = _small_policy_at(output)
    assert validate_reference_selection(database, policy)["passed"] is True

    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE selections SET materialized_path=? WHERE relative_path='a.jpg'",
        (str(tmp_path / "outside.jpg"),),
    )
    connection.commit()
    connection.close()
    report = validate_reference_selection(database, policy)
    assert report["passed"] is False
    assert any(issue.startswith("materialized_outside_output_root") for issue in report["issues"])


def test_selection_status_proves_near_dedup_counts_coverage_and_fingerprint(tmp_path: Path):
    database = _database(tmp_path)
    connection = sqlite3.connect(database)
    connection.executemany(
        "INSERT INTO images(relative_path,sha256,dhash64) VALUES (?,?,?)",
        [("a.jpg", "a" * 64, "1"), ("b.jpg", "b" * 64, "2")],
    )
    connection.executemany("INSERT INTO exact_members VALUES (?,1)", [("a.jpg",), ("b.jpg",)])
    connection.executemany(
        "INSERT INTO visual_index(relative_path,status,tags_json) VALUES (?,?,?)",
        [
            ("a.jpg", "valid", '["part_hand_fingers"]'),
            ("b.jpg", "valid", "[]"),
        ],
    )
    connection.executemany(
        "INSERT INTO near_duplicate_members VALUES (?,?,?,?,?)",
        [
            ("a.jpg", "c1", "a.jpg", 1, 1.0),
            ("b.jpg", "c2", "b.jpg", 1, 1.0),
        ],
    )
    connection.executemany(
        "INSERT INTO selections(relative_path,tier,materialized_path,materialized_sha256,"
        "rank,selection_score,selection_reasons_json) VALUES (?,?,?,?,?,?,?)",
        [
            ("a.jpg", "benchmark_reference", None, None, 1, 0.9, '{"reason":"a"}'),
            ("b.jpg", "retrieval_reference", None, None, 1, 0.8, '{"reason":"b"}'),
        ],
    )
    connection.executemany(
        "INSERT INTO pipeline_meta VALUES (?,?,?)",
        [
            ("near_dedup", '{"near_unique":2}', "now"),
            (
                "library_purpose",
                '{"body_part_focus_tags":["part_hand_fingers"]}',
                "now",
            ),
        ],
    )
    connection.commit()
    connection.close()
    report = inspect_reference_selection(database, _small_policy_at(tmp_path))
    assert report["passed"] is True
    assert report["selection_counts"] == {
        "benchmark_reference": 1,
        "retrieval_reference": 1,
    }
    assert report["cross_tier_near_cluster_overlap"] == 0
    assert len(report["near_group_fingerprint"]) == 64
    assert len(report["selection_fingerprint"]) == 64


def test_tier_materialization_is_bounded_hashed_resumable_and_capacity_safe(tmp_path: Path):
    source_root = tmp_path / "source"
    output_root = tmp_path / "output"
    source_root.mkdir()
    output_root.mkdir()
    benchmark_source = source_root / "benchmark.jpg"
    retrieval_source = source_root / "retrieval.jpg"
    benchmark_source.write_bytes(b"benchmark")
    retrieval_source.write_bytes(b"retrieval")
    benchmark_sha = hashlib.sha256(benchmark_source.read_bytes()).hexdigest()
    retrieval_sha = hashlib.sha256(retrieval_source.read_bytes()).hexdigest()
    database = _database(tmp_path)
    connection = sqlite3.connect(database)
    connection.executemany(
        "INSERT INTO images(relative_path,sha256,dhash64,size_bytes) VALUES (?,?,?,?)",
        [
            ("benchmark.jpg", benchmark_sha, "1", benchmark_source.stat().st_size),
            ("retrieval.jpg", retrieval_sha, "2", retrieval_source.stat().st_size),
        ],
    )
    connection.executemany(
        "INSERT INTO visual_index(relative_path,status) VALUES (?,'valid')",
        [("benchmark.jpg",), ("retrieval.jpg",)],
    )
    connection.executemany(
        "INSERT INTO selections(relative_path,tier,rank) VALUES (?,?,1)",
        [
            ("benchmark.jpg", "benchmark_reference"),
            ("retrieval.jpg", "retrieval_reference"),
        ],
    )
    connection.commit()
    connection.close()
    policy = _small_policy_at(output_root)
    policy["source_root"] = str(source_root.resolve())
    benchmark_mtime = benchmark_source.stat().st_mtime_ns
    report = materialize_reference_tier(
        database,
        policy,
        "benchmark_reference",
        max_items=1,
        free_bytes_provider=lambda _root: 200 * 1024**3,
    )
    assert report["complete"] is True
    assert report["processed_this_chunk"] == 1
    assert benchmark_source.stat().st_mtime_ns == benchmark_mtime
    connection = sqlite3.connect(database)
    materialized_path, claimed_sha = connection.execute(
        "SELECT materialized_path,materialized_sha256 FROM selections "
        "WHERE tier='benchmark_reference'"
    ).fetchone()
    connection.close()
    assert (output_root / materialized_path).read_bytes() == b"benchmark"
    assert claimed_sha == benchmark_sha

    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE selections SET materialized_path=NULL,materialized_sha256=NULL "
        "WHERE tier='benchmark_reference'"
    )
    connection.commit()
    connection.close()
    replay = materialize_reference_tier(
        database,
        policy,
        "benchmark_reference",
        max_items=1,
        free_bytes_provider=lambda _root: 200 * 1024**3,
    )
    assert replay["processed_this_chunk"] == 0
    assert replay["reused_this_chunk"] == 1
    assert replay["complete"] is True

    hold = materialize_reference_tier(
        database,
        policy,
        "retrieval_reference",
        max_items=1,
        free_bytes_provider=lambda _root: 149 * 1024**3,
    )
    assert hold["complete"] is False
    assert hold["processed_this_chunk"] == 0
    assert hold["capacity_hold"]["reason"] == "storage_below_soft_floor"
    assert not list((output_root / "retrieval_reference").rglob("*"))
