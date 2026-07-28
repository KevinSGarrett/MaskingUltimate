from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


class _Tensor:
    def __init__(self, value: np.ndarray) -> None:
        self.value = value

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self) -> np.ndarray:
        return self.value


def _load_runner(tmp_path: Path, monkeypatch):
    package = tmp_path / "groundingdino"
    (package / "config").mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "config/GroundingDINO_SwinT_OGC.py").write_text("", encoding="utf-8")
    groundingdino = types.ModuleType("groundingdino")
    groundingdino.__file__ = str(package / "__init__.py")
    util = types.ModuleType("groundingdino.util")
    inference = types.ModuleType("groundingdino.util.inference")
    calls = {"load_model": 0, "predict": 0, "load_devices": [], "predict_devices": []}

    def load_model(*args, **kwargs):
        calls["load_model"] += 1
        calls["load_devices"].append(kwargs.get("device"))
        print("model diagnostic")
        return object()

    def load_image(path: str):
        return None, np.zeros((3, 8, 8), dtype=np.float32)

    def predict(*args, **kwargs):
        calls["predict"] += 1
        calls["predict_devices"].append(kwargs.get("device"))
        return (
            _Tensor(np.asarray([[0.5, 0.5, 0.5, 0.5]], dtype=np.float32)),
            _Tensor(np.asarray([0.8], dtype=np.float32)),
            ["person"],
        )

    inference.load_model = load_model
    inference.load_image = load_image
    inference.predict = predict
    monkeypatch.setitem(sys.modules, "groundingdino", groundingdino)
    monkeypatch.setitem(sys.modules, "groundingdino.util", util)
    monkeypatch.setitem(sys.modules, "groundingdino.util.inference", inference)
    path = Path(__file__).resolve().parents[1] / "tools/run_groundingdino_wsl.py"
    spec = importlib.util.spec_from_file_location("test_groundingdino_batch_runner_module", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, calls


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_batch_uses_one_model_load_and_binds_every_source(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    runner, calls = _load_runner(tmp_path, monkeypatch)
    checkpoint = tmp_path / "model.pth"
    checkpoint.write_bytes(b"checkpoint")
    records = []
    for index in range(2):
        image = tmp_path / f"source-{index}.png"
        Image.new("RGB", (20 + index, 10 + index), "white").save(image)
        records.append(
            {
                "sample_id": f"sample-{index}",
                "source_sha256": _sha256(image),
                "image_path": str(image),
            }
        )

    result = runner.run_batch(
        checkpoint,
        records,
        ("person",),
        box_threshold=0.30,
        text_threshold=0.25,
    )

    assert result["schema_version"] == "maskfactory.groundingdino_batch.v1"
    assert result["record_count"] == 2
    assert result["model_load_count"] == 1
    assert result["authority"] == "proposal_boxes_only"
    assert result["may_write_final_masks"] is False
    assert calls == {
        "load_model": 1,
        "predict": 2,
        "load_devices": ["cpu"],
        "predict_devices": ["cpu", "cpu"],
    }
    assert [row["source_sha256"] for row in result["records"]] == [
        record["source_sha256"] for record in records
    ]
    assert len(result["output_sha256"]) == 64
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "model diagnostic" in captured.err


def test_batch_fails_closed_on_hash_drift_and_duplicate_sample(tmp_path: Path, monkeypatch) -> None:
    runner, _ = _load_runner(tmp_path, monkeypatch)
    checkpoint = tmp_path / "model.pth"
    checkpoint.write_bytes(b"checkpoint")
    image = tmp_path / "source.png"
    Image.new("RGB", (20, 10), "white").save(image)
    record = {"sample_id": "sample", "source_sha256": "0" * 64, "image_path": str(image)}
    with pytest.raises(ValueError, match="source hash mismatch"):
        runner.run_batch(
            checkpoint,
            [record],
            ("person",),
            box_threshold=0.30,
            text_threshold=0.25,
        )

    record["source_sha256"] = _sha256(image)
    with pytest.raises(ValueError, match="duplicated"):
        runner.run_batch(
            checkpoint,
            [record, dict(record)],
            ("person",),
            box_threshold=0.30,
            text_threshold=0.25,
        )


def test_batch_size_is_bounded_before_model_load(tmp_path: Path, monkeypatch) -> None:
    runner, calls = _load_runner(tmp_path, monkeypatch)
    checkpoint = tmp_path / "model.pth"
    checkpoint.write_bytes(b"checkpoint")
    with pytest.raises(ValueError, match="1..256"):
        runner.run_batch(
            checkpoint,
            [],
            ("person",),
            box_threshold=0.30,
            text_threshold=0.25,
        )
    assert calls["load_model"] == 0


def test_cuda_device_is_explicitly_forwarded(tmp_path: Path, monkeypatch) -> None:
    runner, calls = _load_runner(tmp_path, monkeypatch)
    checkpoint = tmp_path / "model.pth"
    checkpoint.write_bytes(b"checkpoint")
    image = tmp_path / "source.png"
    Image.new("RGB", (20, 10), "white").save(image)

    result = runner.run_batch(
        checkpoint,
        [{"sample_id": "sample", "source_sha256": _sha256(image), "image_path": str(image)}],
        ("person",),
        box_threshold=0.30,
        text_threshold=0.25,
        device="cuda",
    )

    assert result["device_type"] == "cuda"
    assert result["device"] == "cuda"
    assert calls["load_devices"] == ["cuda"]
    assert calls["predict_devices"] == ["cuda"]


def test_unknown_device_fails_before_model_load(tmp_path: Path, monkeypatch) -> None:
    runner, calls = _load_runner(tmp_path, monkeypatch)
    checkpoint = tmp_path / "model.pth"
    checkpoint.write_bytes(b"checkpoint")
    with pytest.raises(ValueError, match="exactly cpu or cuda"):
        runner.run_batch(
            checkpoint,
            [],
            ("person",),
            box_threshold=0.30,
            text_threshold=0.25,
            device="cuda:0",
        )
    assert calls["load_model"] == 0


def test_batch_checkpoint_resumes_contiguous_prefix_after_interruption(
    tmp_path: Path, monkeypatch
) -> None:
    runner, calls = _load_runner(tmp_path, monkeypatch)
    checkpoint = tmp_path / "model.pth"
    checkpoint.write_bytes(b"checkpoint")
    records = []
    for index in range(3):
        image = tmp_path / f"source-{index}.png"
        Image.new("RGB", (20 + index, 10 + index), "white").save(image)
        records.append(
            {
                "sample_id": f"sample-{index}",
                "source_sha256": _sha256(image),
                "image_path": str(image),
            }
        )
    original_predict = runner.predict
    attempt = {"count": 0}

    def interrupt_second(*args, **kwargs):
        attempt["count"] += 1
        if attempt["count"] == 2:
            raise RuntimeError("seeded interruption")
        return original_predict(*args, **kwargs)

    runner.predict = interrupt_second
    progress = tmp_path / "progress.json"
    with pytest.raises(RuntimeError, match="seeded interruption"):
        runner.run_batch(
            checkpoint,
            records,
            ("person",),
            box_threshold=0.30,
            text_threshold=0.25,
            checkpoint_path=progress,
        )
    partial = __import__("json").loads(progress.read_text(encoding="utf-8"))
    assert partial["completed_record_count"] == 1
    assert partial["complete"] is False

    runner.predict = original_predict
    resumed = runner.run_batch(
        checkpoint,
        records,
        ("person",),
        box_threshold=0.30,
        text_threshold=0.25,
        checkpoint_path=progress,
    )
    assert resumed["resumed_record_count"] == 1
    assert resumed["processed_record_count"] == 2
    assert resumed["record_count"] == 3
    assert calls["load_model"] == 2
    complete = __import__("json").loads(progress.read_text(encoding="utf-8"))
    assert complete["completed_record_count"] == 3
    assert complete["complete"] is True

    replay = runner.run_batch(
        checkpoint,
        records,
        ("person",),
        box_threshold=0.30,
        text_threshold=0.25,
        checkpoint_path=progress,
    )
    assert replay["model_load_count"] == 0
    assert replay["resumed_record_count"] == 3
    assert replay["processed_record_count"] == 0
    assert calls["load_model"] == 2


def test_batch_checkpoint_rejects_policy_drift(tmp_path: Path, monkeypatch) -> None:
    runner, _ = _load_runner(tmp_path, monkeypatch)
    checkpoint = tmp_path / "model.pth"
    checkpoint.write_bytes(b"checkpoint")
    image = tmp_path / "source.png"
    Image.new("RGB", (20, 10), "white").save(image)
    records = [{"sample_id": "sample", "source_sha256": _sha256(image), "image_path": str(image)}]
    progress = tmp_path / "progress.json"
    runner.run_batch(
        checkpoint,
        records,
        ("person",),
        box_threshold=0.30,
        text_threshold=0.25,
        checkpoint_path=progress,
    )
    with pytest.raises(ValueError, match="policy mismatch"):
        runner.run_batch(
            checkpoint,
            records,
            ("person",),
            box_threshold=0.31,
            text_threshold=0.25,
            checkpoint_path=progress,
        )


def test_nude_shard_loader_preserves_exact_shard_binding(tmp_path: Path, monkeypatch) -> None:
    runner, _ = _load_runner(tmp_path, monkeypatch)
    image = tmp_path / "source.png"
    Image.new("RGB", (20, 10), "white").save(image)
    body = {
        "schema_version": "maskfactory.nude_batch_shard.v1",
        "artifact_type": "tournament_sample_set",
        "batch_lane": "reference_and_tournament_input",
        "batch_number": 1,
        "platform": "runpod",
        "sample_count": 1,
        "ordered_sample_ids": ["sample"],
        "samples": [
            {
                "sample_id": "sample",
                "source_sha256": _sha256(image),
                "source_path_readonly": str(image),
            }
        ],
    }
    shard = {**body, "self_sha256": runner._canonical_sha256(body)}
    path = tmp_path / "shard.json"
    path.write_text(json.dumps(shard), encoding="utf-8")
    checkpoint = tmp_path / "model.pth"
    checkpoint.write_bytes(b"checkpoint")

    records, binding = runner._load_nude_shard(path)
    result = runner.run_batch(
        checkpoint,
        records,
        ("person",),
        box_threshold=0.30,
        text_threshold=0.25,
        input_binding=binding,
    )

    assert result["input_binding"] == {
        "schema_version": "maskfactory.nude_shard_binding.v1",
        "shard_self_sha256": shard["self_sha256"],
        "batch_lane": "reference_and_tournament_input",
        "batch_number": 1,
        "platform": "runpod",
        "sample_count": 1,
    }


def test_nude_shard_loader_rejects_resealed_order_drift(tmp_path: Path, monkeypatch) -> None:
    runner, _ = _load_runner(tmp_path, monkeypatch)
    body = {
        "schema_version": "maskfactory.nude_batch_shard.v1",
        "artifact_type": "tournament_sample_set",
        "batch_lane": "reference_and_tournament_input",
        "batch_number": 1,
        "platform": "runpod",
        "sample_count": 1,
        "ordered_sample_ids": ["wrong"],
        "samples": [
            {
                "sample_id": "sample",
                "source_sha256": "0" * 64,
                "source_path_readonly": "unused",
            }
        ],
    }
    path = tmp_path / "shard.json"
    path.write_text(
        json.dumps({**body, "self_sha256": runner._canonical_sha256(body)}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="contract is invalid"):
        runner._load_nude_shard(path)
