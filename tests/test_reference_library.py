import hashlib
import sqlite3
from pathlib import Path

import pytest

from maskfactory.reference_library import (
    ReferenceLibraryError,
    inspect_reference_database,
    load_reference_library_policy,
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
          relative_path TEXT PRIMARY KEY, sha256 TEXT, dhash64 TEXT
        );
        CREATE TABLE exact_members (
          relative_path TEXT, is_representative INTEGER
        );
        CREATE TABLE visual_index (
          relative_path TEXT, status TEXT
        );
        CREATE TABLE selections (
          relative_path TEXT, tier TEXT, materialized_path TEXT,
          materialized_sha256 TEXT
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
        "INSERT INTO images VALUES (?,?,?)",
        [("a.jpg", sha_b, "0000000000000001"), ("b.jpg", sha_r, "0000000000000002")],
    )
    connection.executemany("INSERT INTO exact_members VALUES (?,1)", [("a.jpg",), ("b.jpg",)])
    connection.executemany("INSERT INTO visual_index VALUES (?, 'valid')", [("a.jpg",), ("b.jpg",)])
    connection.executemany(
        "INSERT INTO selections VALUES (?,?,?,?)",
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
    report = validate_reference_selection(database, _small_policy())
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
        "INSERT INTO images VALUES (?,?,?)",
        [("a.jpg", sha, "1"), ("b.jpg", sha, "1")],
    )
    connection.executemany(
        "INSERT INTO selections VALUES (?,?,?,?)",
        [
            ("a.jpg", "benchmark_reference", str(materialized), sha),
            ("b.jpg", "retrieval_reference", str(materialized), sha),
        ],
    )
    connection.commit()
    connection.close()
    report = validate_reference_selection(database, _small_policy())
    assert report["passed"] is False
    assert "exact_sha256_overlap_between_tiers" in report["issues"]
