from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from maskfactory.nude_batch_queue import NudeBatchQueue
from maskfactory.nude_corpus_intake import canonical_sha256
from maskfactory.nude_person_catalog import compare_person_proposal_catalogs
from maskfactory.nude_person_catalog_queue_bridge import (
    NudePersonCatalogQueueBridgeError,
    bridge_person_catalog_batch_to_queue,
)


def _fixture(tmp_path: Path):
    lane, source_sha = "bbox_prompt_and_action_tag_supervision", "a" * 64
    sample = {
        "sample_id": "sample-1",
        "source_sha256": source_sha,
        "source_path_readonly": "/readonly/source.png",
        "source_role": lane,
        "source_split": "unsplit_reference",
        "source_labels": [],
        "annotation_ref": None,
    }
    shard_body = {
        "schema_version": "maskfactory.nude_batch_shard.v1",
        "artifact_type": "tournament_sample_set",
        "batch_lane": lane,
        "batch_number": 1,
        "platform": "runpod",
        "sample_count": 1,
        "ordered_sample_ids": ["sample-1"],
        "samples": [sample],
    }
    shard = tmp_path / "shard.json"
    shard.write_text(json.dumps({**shard_body, "self_sha256": canonical_sha256(shard_body)}))
    report = compare_person_proposal_catalogs(
        sample_id="sample-1",
        source_sha256=source_sha,
        image_size=[100, 80],
        provider_records=[
            {
                "provider_id": "gdino",
                "family_id": "groundingdino",
                "revision": "r1",
                "artifact_sha256": "b" * 64,
                "source_sha256": source_sha,
                "proposals": [
                    {
                        "bbox_xyxy": [5, 5, 95, 78],
                        "confidence": 0.9,
                        "label": "person",
                        "authority": "proposal_only",
                    }
                ],
            },
            {
                "provider_id": "yolo",
                "family_id": "yolo",
                "revision": "r1",
                "artifact_sha256": "c" * 64,
                "source_sha256": source_sha,
                "proposals": [
                    {
                        "bbox_xyxy": [5, 5, 95, 78],
                        "confidence": 0.9,
                        "label": "person",
                        "authority": "proposal_only",
                    }
                ],
            },
        ],
    )
    body = {
        "schema_version": "maskfactory.nude_person_catalog_batch.v1",
        "shard_self_sha256": json.loads(shard.read_text())["self_sha256"],
        "batch_lane": lane,
        "platform": "runpod",
        "record_count": 1,
        "provider_artifacts": [],
        "comparison_policy": {"iou_min": 0.5},
        "status_counts": {"pass": 1},
        "reason_counts": {},
        "records": [report],
        "authority": "person_catalog_comparison_only",
        "production_mask_authority": False,
        "operational_certificate_issued": False,
    }
    batch = tmp_path / "catalog.json"
    batch.write_text(json.dumps({**body, "self_sha256": canonical_sha256(body)}))
    return shard, batch, lane


def _queue(tmp_path: Path, shard: Path, lane: str):
    queue = NudeBatchQueue(tmp_path / "queue.sqlite")
    path = f"runpod/{lane}.0001.json"
    queue.seed(
        [
            {
                "platform": "runpod",
                "path": path,
                "lane": lane,
                "self_sha256": json.loads(shard.read_text())["self_sha256"],
                "sample_count": 1,
            }
        ],
        platform="runpod",
    )
    lease = queue.claim(platform="runpod", owner="test")
    assert lease
    return queue, path, lease["lease_token"]


def test_bridge_is_nonterminal_and_idempotent(tmp_path: Path) -> None:
    shard, batch, lane = _fixture(tmp_path)
    queue, path, token = _queue(tmp_path, shard, lane)
    kwargs = {
        "catalog_batch_path": batch,
        "nude_shard_path": shard,
        "output_path": tmp_path / "bridge.json",
        "queue": queue,
        "platform": "runpod",
        "shard_path": path,
        "lease_token": token,
    }
    first = bridge_person_catalog_batch_to_queue(**kwargs)
    assert first["checkpoint"] == {
        "inserted": 1,
        "retained": 0,
        "terminal_progress_advanced": False,
    }
    assert first["production_mask_authority"] is False
    replay = bridge_person_catalog_batch_to_queue(**kwargs)
    assert replay == first
    assert queue.summary(platform="runpod")["checkpointed_records"] == 0


def test_bridge_rejects_seal_drift_before_queue_mutation(tmp_path: Path) -> None:
    shard, batch, lane = _fixture(tmp_path)
    queue, path, token = _queue(tmp_path, shard, lane)
    drift = json.loads(batch.read_text())
    drift["records"][0]["source_sha256"] = "0" * 64
    batch.write_text(json.dumps(drift))
    try:
        bridge_person_catalog_batch_to_queue(
            catalog_batch_path=batch,
            nude_shard_path=shard,
            output_path=tmp_path / "bridge.json",
            queue=queue,
            platform="runpod",
            shard_path=path,
            lease_token=token,
        )
    except NudePersonCatalogQueueBridgeError as exc:
        assert "catalog_batch_self_hash_invalid" in str(exc)
    else:
        raise AssertionError("sealed batch drift must fail")
    assert queue.summary(platform="runpod")["stage_evidence"] == {}


def test_bridge_accepts_the_actual_comparator_batch_report(tmp_path: Path) -> None:
    comparator_path = (
        Path(__file__).resolve().parents[1] / "tools/compare_person_proposal_batches.py"
    )
    spec = importlib.util.spec_from_file_location(
        "compare_person_proposal_batches_bridge", comparator_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lane = "bbox_prompt_and_action_tag_supervision"
    fixture_spec = importlib.util.spec_from_file_location(
        "compare_person_proposal_batches_fixture",
        Path(__file__).resolve().with_name("test_compare_person_proposal_batches.py"),
    )
    assert fixture_spec and fixture_spec.loader
    fixture_module = importlib.util.module_from_spec(fixture_spec)
    fixture_spec.loader.exec_module(fixture_module)
    shard, (gdino, yolo) = fixture_module._fixture(tmp_path, lane=lane)
    batch = tmp_path / "actual-comparator.json"
    batch.write_text(
        json.dumps(
            module.compare_batches(
                shard_path=shard,
                groundingdino_path=gdino,
                yolo_path=yolo,
                platform="runpod",
                expected_lane=lane,
            )
        )
    )
    queue, path, token = _queue(tmp_path, shard, lane)
    result = bridge_person_catalog_batch_to_queue(
        catalog_batch_path=batch,
        nude_shard_path=shard,
        output_path=tmp_path / "actual-bridge.json",
        queue=queue,
        platform="runpod",
        shard_path=path,
        lease_token=token,
    )
    assert result["record_count"] == 1
    assert result["checkpoint"]["inserted"] == 1
