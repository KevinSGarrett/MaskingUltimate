from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from tools.smoke_sam31_multiplex_wsl import _payload_sha256 as runner_payload_sha256

from maskfactory.providers.sam31_multiplex import (
    Sam31MultiplexError,
    Sam31MultiplexSmokeRunner,
    multiplex_payload_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "qa/fixtures/smoke/ultralytics_bus_adults.jpg"


def _arrays() -> dict[str, np.ndarray]:
    masks = np.zeros((2, 8, 12), dtype=bool)
    masks[0, 2:7, 3:10] = True
    masks[1, 0:3, 0:3] = True
    return {
        "masks": masks,
        "object_ids": np.asarray([1, 2], dtype=np.int64),
        "probabilities": np.asarray([0.95, 0.90], dtype=np.float32),
        "boxes_xywh": np.asarray([[3.0, 2.0, 7.0, 5.0], [0.0, 0.0, 3.0, 3.0]], dtype=np.float32),
    }


def _executor(runner, *, mutate=None, returncode=0):
    def execute(argv, timeout):
        assert argv[:5] == (
            "wsl.exe",
            "-d",
            "Ubuntu-22.04",
            "--",
            runner.runtime_python,
        )
        assert argv[argv.index("--repeats") + 1] == "2"
        assert timeout == 900
        if returncode:
            return subprocess.CompletedProcess(argv, returncode, "", "CUDA out of memory")
        output_path = Path(argv[argv.index("--output") + 1])
        arrays = _arrays()
        np.savez_compressed(output_path, **arrays)
        report = {
            "schema_version": "1.0.0",
            "provider": "sam3_1",
            "source_commit": runner.lock["source"]["commit"],
            "source_tree_clean": True,
            "runtime_lock_sha256": hashlib.sha256(runner.lock_path.read_bytes()).hexdigest(),
            "requirements_lock_sha256": runner.lock["runtime"]["requirements_lock_sha256"],
            "checkpoint_sha256": runner.lock["checkpoint"]["sha256"],
            "image_sha256": hashlib.sha256(IMAGE.read_bytes()).hexdigest(),
            "builder": "build_sam3_predictor",
            "version": "sam3.1",
            "adaptation": "single_frame_directory_via_object_multiplex",
            "prompt": {"type": "text", "concept": "person"},
            "repeats": 2,
            "deterministic": True,
            "mask_payload_sha256": multiplex_payload_sha256(arrays),
            "output_npz_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
            "artifact_shapes": {name: list(value.shape) for name, value in arrays.items()},
            "model_load_latency_ms": 12_000.0,
            "cold_latency_ms": 1_500.0,
            "warm_latency_ms": 1_000.0,
            "model_vram_bytes": 7_000_000_000,
            "peak_inference_vram_bytes": 7_500_000_000,
            "authority": "runtime_smoke_only_no_candidate_serving_or_gold_authority",
            "may_author_gold": False,
        }
        if mutate is not None:
            mutate(report)
        return subprocess.CompletedProcess(argv, 0, json.dumps(report), "")

    return execute


def test_official_source_routes_sam31_checkpoint_through_multiplex_predictor() -> None:
    builder = (ROOT / "models/runtime_cache/sam3_source_5dd401d1/sam3/model_builder.py").read_text(
        encoding="utf-8"
    )
    runner = (ROOT / "tools/smoke_sam31_multiplex_wsl.py").read_text(encoding="utf-8")
    assert 'if version == "sam3.1":' in builder
    assert "return build_sam3_multiplex_video_predictor(" in builder
    assert 'checkpoint_path = download_ckpt_from_hf(version="sam3")' in builder
    assert "build_sam3_predictor" in runner
    assert "build_sam3_image_model" not in runner
    assert 'version="sam3.1"' in runner
    assert "single_frame_directory_via_object_multiplex" in runner


def test_host_and_isolated_runner_share_exact_payload_hash() -> None:
    arrays = _arrays()
    assert multiplex_payload_sha256(arrays) == runner_payload_sha256(arrays)


def test_multiplex_smoke_contract_accepts_exact_artifact_and_report() -> None:
    runner = Sam31MultiplexSmokeRunner(path_mapper=lambda path: str(path))
    runner._executor = _executor(runner)
    report = runner.run(IMAGE)
    assert report["builder"] == "build_sam3_predictor"
    assert report["version"] == "sam3.1"
    assert report["object_count"] == 2
    assert report["mask_pixel_count"] == 44
    assert report["may_author_gold"] is False


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda report: report.update(extra="field"), "fields are not closed"),
        (lambda report: report.update(builder="build_sam3_image_model"), "identity or authority"),
        (lambda report: report.update(version="sam3"), "identity or authority"),
        (lambda report: report.update(deterministic=False), "identity or authority"),
        (lambda report: report.update(output_npz_sha256="0" * 64), "artifact SHA-256"),
        (lambda report: report.update(mask_payload_sha256="0" * 64), "payload SHA-256"),
        (lambda report: report.update(artifact_shapes={}), "shape evidence"),
    ],
)
def test_multiplex_smoke_rejects_report_and_artifact_drift(mutate, message: str) -> None:
    runner = Sam31MultiplexSmokeRunner(path_mapper=lambda path: str(path))
    runner._executor = _executor(runner, mutate=mutate)
    with pytest.raises(Sam31MultiplexError, match=message):
        runner.run(IMAGE)


def test_multiplex_process_failure_preserves_cuda_oom_text() -> None:
    runner = Sam31MultiplexSmokeRunner(path_mapper=lambda path: str(path))
    runner._executor = _executor(runner, returncode=1)
    with pytest.raises(Sam31MultiplexError, match="CUDA out of memory"):
        runner.run(IMAGE)
