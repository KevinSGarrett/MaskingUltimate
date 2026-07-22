from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
from PIL import Image


class _Values:
    def __init__(self, values):
        self.values = values

    def tolist(self):
        return self.values


def _load_runner(tmp_path: Path, monkeypatch):
    calls = {"loads": 0, "batches": []}

    class FakeYolo:
        def __init__(self, checkpoint: str, task: str):
            calls["loads"] += 1
            assert task == "detect"

        def predict(self, *, source, **kwargs):
            calls["batches"].append(list(source))
            return [
                types.SimpleNamespace(
                    names={0: "person"},
                    boxes=types.SimpleNamespace(
                        cls=_Values([0.0]),
                        conf=_Values([0.8]),
                        xyxy=_Values([[1.0, 2.0, 8.0, 9.0]]),
                    ),
                )
                for _ in source
            ]

    ultralytics = types.ModuleType("ultralytics")
    ultralytics.YOLO = FakeYolo
    monkeypatch.setitem(sys.modules, "ultralytics", ultralytics)
    path = Path(__file__).resolve().parents[1] / "tools/run_yolo11_batch.py"
    spec = importlib.util.spec_from_file_location("test_yolo11_batch_runner_module", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, calls, FakeYolo


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reseal(document, runner) -> None:
    body = dict(document)
    body.pop("self_sha256", None)
    document["self_sha256"] = runner._canonical_sha256(body)


def _shard(tmp_path: Path, runner, count: int = 3) -> Path:
    samples = []
    for index in range(count):
        image = tmp_path / f"{index}.png"
        Image.new("RGB", (16, 12), "white").save(image)
        samples.append(
            {
                "sample_id": f"sample-{index}",
                "source_sha256": _sha(image),
                "source_path_readonly": str(image),
                "source_role": "reference_and_tournament_input",
                "source_split": "unsplit_reference",
                "source_labels": [],
                "annotation_ref": None,
            }
        )
    body = {
        "schema_version": "maskfactory.nude_batch_shard.v1",
        "artifact_type": "tournament_sample_set",
        "batch_lane": "reference_and_tournament_input",
        "batch_number": 1,
        "platform": "runpod",
        "sample_count": count,
        "ordered_sample_ids": [sample["sample_id"] for sample in samples],
        "samples": samples,
    }
    path = tmp_path / "shard.json"
    path.write_text(
        json.dumps({**body, "self_sha256": runner._canonical_sha256(body)}), encoding="utf-8"
    )
    return path


def test_yolo_batch_uses_one_load_and_bounded_microbatches(tmp_path: Path, monkeypatch) -> None:
    runner, calls, _ = _load_runner(tmp_path, monkeypatch)
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"model")
    result = runner.run_batch(
        checkpoint=checkpoint,
        shard_path=_shard(tmp_path, runner),
        microbatch_size=2,
        progress_path=tmp_path / "progress.json",
    )
    assert result["record_count"] == 3
    assert result["model_load_count"] == 1
    assert result["authority"] == "proposal_boxes_only"
    assert result["may_write_final_masks"] is False
    assert calls["loads"] == 1
    assert [len(batch) for batch in calls["batches"]] == [2, 1]


def test_yolo_batch_resumes_contiguous_prefix_after_failure(tmp_path: Path, monkeypatch) -> None:
    runner, calls, fake_yolo = _load_runner(tmp_path, monkeypatch)
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"model")
    shard = _shard(tmp_path, runner)
    progress = tmp_path / "progress.json"
    original = fake_yolo.predict
    attempts = {"count": 0}

    def fail_second(self, *, source, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 2:
            raise RuntimeError("seeded failure")
        return original(self, source=source, **kwargs)

    fake_yolo.predict = fail_second
    with pytest.raises(RuntimeError, match="seeded failure"):
        runner.run_batch(
            checkpoint=checkpoint,
            shard_path=shard,
            microbatch_size=1,
            progress_path=progress,
        )
    assert json.loads(progress.read_text())["completed_record_count"] == 1

    fake_yolo.predict = original
    result = runner.run_batch(
        checkpoint=checkpoint,
        shard_path=shard,
        microbatch_size=1,
        progress_path=progress,
    )
    assert result["resumed_record_count"] == 1
    assert result["processed_record_count"] == 2
    assert json.loads(progress.read_text())["complete"] is True
    assert calls["loads"] == 2


def test_reference_shard_cannot_inherit_labels_or_annotations(tmp_path: Path, monkeypatch) -> None:
    runner, _, _ = _load_runner(tmp_path, monkeypatch)
    shard_path = _shard(tmp_path, runner, count=1)
    document = json.loads(shard_path.read_text())
    document["samples"][0]["source_labels"] = ["nipple"]
    _reseal(document, runner)
    shard_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="inherited source truth"):
        runner._load_shard(shard_path)


def test_source_hash_drift_fails_before_model_load(tmp_path: Path, monkeypatch) -> None:
    runner, calls, _ = _load_runner(tmp_path, monkeypatch)
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"model")
    shard_path = _shard(tmp_path, runner, count=1)
    document = json.loads(shard_path.read_text())
    document["samples"][0]["source_sha256"] = "0" * 64
    _reseal(document, runner)
    shard_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="source hash mismatch"):
        runner.run_batch(checkpoint=checkpoint, shard_path=shard_path)
    assert calls["loads"] == 0
