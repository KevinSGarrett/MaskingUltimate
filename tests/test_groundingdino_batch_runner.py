from __future__ import annotations

import hashlib
import importlib.util
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
    calls = {"load_model": 0, "predict": 0}

    def load_model(*args, **kwargs):
        calls["load_model"] += 1
        return object()

    def load_image(path: str):
        return None, np.zeros((3, 8, 8), dtype=np.float32)

    def predict(*args, **kwargs):
        calls["predict"] += 1
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


def test_batch_uses_one_model_load_and_binds_every_source(tmp_path: Path, monkeypatch) -> None:
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
    assert calls == {"load_model": 1, "predict": 2}
    assert [row["source_sha256"] for row in result["records"]] == [
        record["source_sha256"] for record in records
    ]
    assert len(result["output_sha256"]) == 64


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
