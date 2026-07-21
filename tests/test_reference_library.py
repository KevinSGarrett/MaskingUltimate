import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from maskfactory.reference_library import (
    ReferenceLibraryError,
    evaluate_benchmark_training_isolation,
    evaluate_reference_benchmark_drift,
    freeze_reference_benchmark_version,
    inspect_reference_database,
    inspect_reference_selection,
    load_reference_library_policy,
    materialize_reference_tier,
    publish_reference_database_snapshot,
    retrieve_reference_candidates,
    validate_benchmark_training_isolation,
    validate_reference_library_policy,
    validate_reference_materialized_tier,
    validate_reference_selection,
    write_reference_acquisition_context,
    write_reference_benchmark_drift_report,
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
          size_bytes INTEGER DEFAULT 0, quality_score REAL DEFAULT 0
        );
        CREATE TABLE exact_members (
          relative_path TEXT, is_representative INTEGER
        );
        CREATE TABLE visual_index (
          relative_path TEXT, status TEXT, tags_json TEXT DEFAULT '[]',
          content_state TEXT DEFAULT 'clothed', person_count TEXT DEFAULT 'one',
          framing TEXT DEFAULT 'full_body', view TEXT DEFAULT 'front',
          pose TEXT DEFAULT 'standing', presentation TEXT DEFAULT 'unclear',
          body_type TEXT DEFAULT 'unclear', background TEXT DEFAULT 'plain_studio',
          lighting TEXT DEFAULT 'even', difficulty_score REAL DEFAULT 0
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
    policy["output_database"] = str(
        (output_root / "manifests" / "reference_library.sqlite").resolve()
    )
    policy["versioning"]["active_benchmark_manifest"] = None
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


def test_reference_policy_rejects_unsafe_database_and_versioning_paths(tmp_path: Path):
    policy = _small_policy_at(tmp_path / "output")
    policy["output_database"] = str((tmp_path / "outside.sqlite").resolve())
    with pytest.raises(ReferenceLibraryError, match="output_database escapes"):
        validate_reference_library_policy(policy)
    policy = _small_policy_at(tmp_path / "output")
    policy["versioning"]["immutable_versions_directory"] = "../outside"
    with pytest.raises(ReferenceLibraryError, match="versioning path is unsafe"):
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
        database,
        [
            {
                "relative_path": "training/a.jpg",
                "source_sha256": sha_b,
                "dhash64": "f" * 16,
                "partition": "train",
            }
        ],
    ) == (f"exact_overlap:0:{sha_b}",)
    near = evaluate_benchmark_training_isolation(
        database,
        [
            {
                "relative_path": "training/near.jpg",
                "source_sha256": "f" * 64,
                "dhash64": "0000000000000000",
                "partition": "holdout",
            }
        ],
        expected_benchmark_count=1,
    )
    assert near["passed"] is False
    assert near["issues"] == ["perceptual_overlap:0:0000000000000000"]
    incomplete = evaluate_benchmark_training_isolation(database, [{}], expected_benchmark_count=2)
    assert {
        "benchmark_count:1!=2",
        "invalid_partition:0:None",
        "missing_dhash64:0",
        "missing_relative_path:0",
        "missing_source_sha256:0",
    } <= set(incomplete["issues"])
    path_overlap = evaluate_benchmark_training_isolation(
        database,
        [
            {
                "relative_path": "A.JPG",
                "source_sha256": "f" * 64,
                "dhash64": "f" * 16,
                "partition": "val",
            }
        ],
    )
    assert path_overlap["issues"] == ["path_overlap:0:A.JPG"]


def test_reference_database_snapshot_is_atomic_consistent_and_replaceable(tmp_path: Path):
    database = _database(tmp_path)
    output = tmp_path / "published.sqlite"
    first = publish_reference_database_snapshot(database, output)
    assert first["quick_check"] == "ok"
    assert len(first["sha256"]) == 64
    published = sqlite3.connect(output)
    assert published.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 0
    published.close()

    source = sqlite3.connect(database)
    source.execute(
        "INSERT INTO images(relative_path,sha256,dhash64) VALUES (?,?,?)",
        ("new.jpg", "a" * 64, "1"),
    )
    source.commit()
    source.close()
    second = publish_reference_database_snapshot(database, output)
    assert second["sha256"] != first["sha256"]
    published = sqlite3.connect(output)
    assert published.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 1
    published.close()


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
    audit = validate_reference_materialized_tier(database, policy, "benchmark_reference")
    assert audit["passed"] is True
    assert audit["verified_count"] == 1
    assert len(audit["materialized_fingerprint"]) == 64

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


def test_benchmark_freeze_is_content_addressed_immutable_and_drift_checked(tmp_path: Path):
    source_root = tmp_path / "source"
    output_root = tmp_path / "output"
    source_root.mkdir()
    output_root.mkdir()
    benchmark = source_root / "benchmark.jpg"
    retrieval = source_root / "retrieval.jpg"
    benchmark.write_bytes(b"benchmark")
    retrieval.write_bytes(b"retrieval")
    benchmark_sha = hashlib.sha256(benchmark.read_bytes()).hexdigest()
    retrieval_sha = hashlib.sha256(retrieval.read_bytes()).hexdigest()
    database = _database(tmp_path)
    connection = sqlite3.connect(database)
    connection.executemany(
        "INSERT INTO images(relative_path,sha256,dhash64,size_bytes) VALUES (?,?,?,?)",
        [
            ("benchmark.jpg", benchmark_sha, "0000000000000001", benchmark.stat().st_size),
            ("retrieval.jpg", retrieval_sha, "0000000000000002", retrieval.stat().st_size),
        ],
    )
    connection.executemany(
        "INSERT INTO exact_members(relative_path,is_representative) VALUES (?,1)",
        [("benchmark.jpg",), ("retrieval.jpg",)],
    )
    connection.executemany(
        "INSERT INTO visual_index(relative_path,status,tags_json) VALUES (?,'valid',?)",
        [("benchmark.jpg", '["part_hand_fingers"]'), ("retrieval.jpg", "[]")],
    )
    connection.executemany(
        "INSERT INTO near_duplicate_members(relative_path,cluster_id,representative_path,"
        "group_size,similarity) VALUES (?,?,?,1,1.0)",
        [
            ("benchmark.jpg", "cluster-a", "benchmark.jpg"),
            ("retrieval.jpg", "cluster-b", "retrieval.jpg"),
        ],
    )
    connection.executemany(
        "INSERT INTO selections(relative_path,tier,rank) VALUES (?,?,1)",
        [
            ("benchmark.jpg", "benchmark_reference"),
            ("retrieval.jpg", "retrieval_reference"),
        ],
    )
    connection.executemany(
        "INSERT INTO pipeline_meta(key,value_json) VALUES (?,?)",
        [
            ("near_dedup", '{"near_unique":2}'),
            ("library_purpose", '{"body_part_focus_tags":["part_hand_fingers"]}'),
        ],
    )
    connection.commit()
    connection.close()
    policy = _small_policy_at(output_root)
    policy["source_root"] = str(source_root.resolve())
    copied = materialize_reference_tier(
        database,
        policy,
        "benchmark_reference",
        max_items=1,
        free_bytes_provider=lambda _root: 200 * 1024**3,
    )
    assert copied["complete"] is True

    first = freeze_reference_benchmark_version(database, policy)
    second = freeze_reference_benchmark_version(database, policy)
    assert first["created"] is True
    assert second["created"] is False
    assert first["version_id"] == second["version_id"]
    manifest = Path(first["manifest_path"])
    original_manifest = manifest.read_bytes()
    health = evaluate_reference_benchmark_drift(database, policy, manifest)
    assert health["passed"] is True
    report_path = output_root / "reports" / "health.json"
    write_reference_benchmark_drift_report(health, report_path)
    write_reference_benchmark_drift_report(health, report_path)

    tampered = json.loads(manifest.read_text(encoding="utf-8"))
    tampered["content"]["benchmark_count"] = 0
    manifest.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ReferenceLibraryError, match="content digest mismatch"):
        freeze_reference_benchmark_version(database, policy)
    manifest.write_bytes(original_manifest)

    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE images SET sha256=? WHERE relative_path='benchmark.jpg'", ("f" * 64,)
    )
    connection.commit()
    connection.close()
    drift = evaluate_reference_benchmark_drift(database, policy, manifest)
    assert drift["drift_detected"] is True
    assert "benchmark_content_drift" in drift["issues"]
    assert manifest.read_bytes() == original_manifest


def test_retrieval_context_ranks_deficits_without_granting_truth(tmp_path: Path):
    database = _database(tmp_path)
    connection = sqlite3.connect(database)
    connection.executemany(
        "INSERT INTO images(relative_path,sha256,dhash64,quality_score) VALUES (?,?,?,?)",
        [
            ("matching.jpg", "a" * 64, "1", 0.9),
            ("other.jpg", "b" * 64, "2", 0.8),
        ],
    )
    connection.executemany(
        "INSERT INTO visual_index(relative_path,status,tags_json,person_count,view,pose,"
        "difficulty_score) VALUES (?,?,?,?,?,?,?)",
        [
            (
                "matching.jpg",
                "valid",
                '["part_hand_fingers"]',
                "two",
                "profile",
                "sitting",
                0.9,
            ),
            ("other.jpg", "valid", "[]", "one", "front", "standing", 0.1),
        ],
    )
    connection.executemany(
        "INSERT INTO selections(relative_path,tier,rank,selection_score) VALUES (?,?,?,?)",
        [
            ("matching.jpg", "retrieval_reference", 1, 0.8),
            ("other.jpg", "retrieval_reference", 2, 0.7),
        ],
    )
    connection.commit()
    connection.close()
    query = {
        "view": "left_profile",
        "pose": "seated_or_crouched",
        "instance_context": "duo",
        "failed_body_part": "left_hand",
    }
    report = retrieve_reference_candidates(database, query, limit=2)
    assert report["candidates"][0]["relative_path"] == "matching.jpg"
    assert report["candidates"][0]["matched_attributes"] == [
        "view",
        "pose",
        "instance_context",
    ]
    assert report["candidates"][0]["truth_authority"] == "none"
    assert report["candidates"][0]["training_eligible"] is False
    output = tmp_path / "reference_context.json"
    first = write_reference_acquisition_context(
        database,
        coverage_deficits=(query,),
        failures=(
            {
                "failed_body_part": "left_hand",
                "failure_reason": "finger_merge",
                "pose_angle": "seated_or_crouched",
            },
        ),
        output_path=output,
        limit_per_target=1,
    ).read_bytes()
    second = write_reference_acquisition_context(
        database,
        coverage_deficits=(query,),
        failures=(),
        output_path=tmp_path / "second.json",
        limit_per_target=1,
    )
    assert json.loads(first)["authority"]["truth_authority"] == "none"
    assert (
        json.loads(second.read_text(encoding="utf-8"))["targets"][0]["retrieval"]["candidates"][0][
            "relative_path"
        ]
        == "matching.jpg"
    )
