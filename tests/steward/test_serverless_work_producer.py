from __future__ import annotations

import json
from pathlib import Path

import pytest

from maskfactory.steward.fallback_dispatcher import (
    WORK_ITEM_NAME,
)
from maskfactory.steward.serverless_work_producer import (
    PAYLOAD_NAME,
    WORKLOAD_NAME,
    WORKLOAD_SCHEMA,
    ServerlessWorkProducer,
    ServerlessWorkProducerError,
    canonical_sha256,
    file_sha256,
    seal_serverless_workload,
)


SESSION_ID = "019f91d1-ea20-7d81-83ff-03d393eaa1f5"


def write_prepared(root: Path, *, payload: dict | None = None) -> dict:
    root.mkdir(parents=True)
    payload = payload or {"input": {"command": ["python", "preflight.py"]}}
    payload_path = root / PAYLOAD_NAME
    payload_path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    identity = {
        "schema_version": WORKLOAD_SCHEMA,
        "session_id": SESSION_ID,
        "profile": "maskfactory",
        "payload_sha256": canonical_sha256(payload),
        "requested_seconds": 180,
    }
    manifest = seal_serverless_workload(
        {
            **identity,
            "mission_id": canonical_sha256(identity),
            "payload_file": PAYLOAD_NAME,
            "payload_raw_sha256": file_sha256(payload_path),
        }
    )
    (root / WORKLOAD_NAME).write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def test_prepared_workload_materializes_once_and_dispatcher_accepts_it(
    tmp_path: Path,
) -> None:
    ready = tmp_path / "ready"
    inbox = tmp_path / "inbox"
    manifest = write_prepared(ready / "sam-v10")
    producer = ServerlessWorkProducer(ready_root=ready, inbox_root=inbox)

    first = producer.produce()
    second = producer.produce()

    assert first == [
        {
            "mission_id": manifest["mission_id"],
            "created": True,
            "payload_sha256": manifest["payload_sha256"],
            "work_item_sha256": file_sha256(
                inbox / manifest["mission_id"] / WORK_ITEM_NAME
            ),
        }
    ]
    assert second == [
        {
            "mission_id": manifest["mission_id"],
            "created": False,
            "terminal_reused": False,
        }
    ]
    item = json.loads(
        (inbox / manifest["mission_id"] / WORK_ITEM_NAME).read_text(encoding="utf-8")
    )
    assert item["route"] == "serverless_overflow"
    assert item["payload_sha256"] == manifest["payload_sha256"]
    assert item["requested_seconds"] == 180


def test_payload_drift_fails_closed_before_inbox_creation(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    inbox = tmp_path / "inbox"
    root = ready / "sam-v10"
    manifest = write_prepared(root)
    (root / PAYLOAD_NAME).write_text('{"changed":true}\n', encoding="utf-8")
    producer = ServerlessWorkProducer(ready_root=ready, inbox_root=inbox)

    with pytest.raises(ServerlessWorkProducerError, match="raw hash mismatch"):
        producer.produce()

    assert not (inbox / manifest["mission_id"]).exists()


def test_manifest_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    root = ready / "sam-v10"
    write_prepared(root)
    path = root / WORKLOAD_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["mission_id"] = "a" * 64
    path.write_text(
        json.dumps(seal_serverless_workload(manifest), sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ServerlessWorkProducerError, match="mission mismatch"):
        ServerlessWorkProducer(
            ready_root=ready,
            inbox_root=tmp_path / "inbox",
        ).produce()
