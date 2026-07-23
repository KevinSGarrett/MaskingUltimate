from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image
from tools import run_sam31_runtime as runner

from maskfactory.providers import sam31_runtime
from maskfactory.providers.sam31_runtime import ResidentSam31CommandExecutor


def _runtime_argv(tmp_path: Path, request_id: str) -> tuple[str, ...]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name in ("source", "checkpoint", "runtime-lock", "requirements-lock"):
        path = tmp_path / name
        path.mkdir(exist_ok=True) if name == "source" else path.write_text(name, encoding="utf-8")
        paths[name] = path
    request_root = tmp_path / request_id
    request_root.mkdir()
    for name in ("request.json", "prompt.npz"):
        (request_root / name).write_text(name, encoding="utf-8")
    (request_root / "frames").mkdir()
    return (
        "wsl.exe",
        "-d",
        "Ubuntu-22.04",
        "--",
        sys.executable,
        str(tmp_path / "run_sam31_runtime.py"),
        "--source-root",
        str(paths["source"]),
        "--checkpoint",
        str(paths["checkpoint"]),
        "--runtime-lock",
        str(paths["runtime-lock"]),
        "--requirements-lock",
        str(paths["requirements-lock"]),
        "--frame-dir",
        str(request_root / "frames"),
        "--request",
        str(request_root / "request.json"),
        "--prompt-npz",
        str(request_root / "prompt.npz"),
        "--output",
        str(request_root / "output.npz"),
        "--expected-source-commit",
        "a" * 40,
    )


def test_resident_executor_reuses_one_process_and_seals_shutdown(
    tmp_path: Path, monkeypatch
) -> None:
    fake_server = tmp_path / "fake_server.py"
    fake_server.write_text(
        """
import hashlib, json, os, sys
schema = "maskfactory.sam31_resident_protocol.v1"
print(json.dumps({"schema_version": schema, "status": "ready", "process_id": os.getpid(), "common_identity_sha256": "a" * 64}), flush=True)
count = 0
for line in sys.stdin:
    command = json.loads(line)
    if command["operation"] == "shutdown":
        body = {"schema_version": schema, "status": "stopped", "request_id": command["request_id"], "process_id": os.getpid(), "common_identity_sha256": "a" * 64, "request_count": count, "successful_request_count": count, "failed_request_count": 0, "model_load_count": 1, "resident_model_count": 1}
        body["self_sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        print(json.dumps(body), flush=True)
        raise SystemExit(0)
    count += 1
    print(json.dumps({"schema_version": schema, "status": "complete", "request_id": command["request_id"], "process_id": os.getpid(), "request_sequence": count, "model_load_count": 1, "report": {"request_path": command["request"]}}), flush=True)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    real_popen = subprocess.Popen
    launches: list[tuple[str, ...]] = []

    def fake_popen(command, **kwargs):
        launches.append(tuple(command))
        return real_popen((sys.executable, str(fake_server)), **kwargs)

    monkeypatch.setattr(sam31_runtime.subprocess, "Popen", fake_popen)
    executor = ResidentSam31CommandExecutor()
    first_argv = _runtime_argv(tmp_path / "first-root", "one")
    first = executor(first_argv, 10)
    second_argv = list(_runtime_argv(tmp_path / "second-root", "two"))
    for flag in (
        "--source-root",
        "--checkpoint",
        "--runtime-lock",
        "--requirements-lock",
        "--expected-source-commit",
    ):
        second_argv[second_argv.index(flag) + 1] = first_argv[first_argv.index(flag) + 1]
    second = executor(tuple(second_argv), 10)
    evidence = executor.close(timeout_seconds=10)

    assert first.returncode == second.returncode == 0
    assert len(launches) == 1
    assert evidence["summary"]["request_count"] == 2
    assert evidence["summary"]["model_load_count"] == 1
    assert evidence["response_sequences"] == [1, 2]
    body = {key: value for key, value in evidence.items() if key != "self_sha256"}
    assert (
        evidence["self_sha256"]
        == hashlib.sha256(
            json.dumps(
                body,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
    )


def test_runner_process_cache_loads_predictor_once_for_two_requests(
    tmp_path: Path, monkeypatch
) -> None:
    runner._PREDICTOR_CACHE.clear()
    runner._MODEL_LOAD_COUNT = 0
    source_root = tmp_path / "source"
    source_root.mkdir()
    checkpoint = tmp_path / "checkpoint.pt"
    runtime_lock = tmp_path / "runtime.json"
    requirements_lock = tmp_path / "requirements.lock"
    checkpoint.write_bytes(b"checkpoint")
    runtime_lock.write_text("{}\n", encoding="utf-8")
    requirements_lock.write_text("requirements\n", encoding="utf-8")
    commit = "c" * 40

    def fake_check_output(argv, **_kwargs):
        return commit + "\n" if "rev-parse" in argv else ""

    monkeypatch.setattr(runner.subprocess, "check_output", fake_check_output)

    class FakeCuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def manual_seed_all(_seed):
            return None

        @staticmethod
        def synchronize():
            return None

        @staticmethod
        def memory_allocated():
            return 123

        @staticmethod
        def reset_peak_memory_stats():
            return None

        @staticmethod
        def max_memory_allocated():
            return 456

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = FakeCuda()
    fake_torch.manual_seed = lambda _seed: None
    fake_torch.backends = types.SimpleNamespace(
        cudnn=types.SimpleNamespace(benchmark=True, deterministic=False)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    builds = []

    class FakePredictor:
        def handle_request(self, payload):
            if payload["type"] == "add_prompt":
                mask = np.zeros((1, 12, 16), dtype=bool)
                mask[0, 2:9, 3:11] = True
                return {
                    "outputs": {
                        "out_binary_masks": mask,
                        "out_obj_ids": np.asarray([1], dtype=np.int64),
                        "out_probs": np.asarray([0.9], dtype=np.float32),
                        "out_boxes_xywh": np.asarray(
                            [[3 / 16, 2 / 12, 8 / 16, 7 / 12]], dtype=np.float32
                        ),
                    }
                }
            return {}

    def build_sam3_predictor(**kwargs):
        builds.append(kwargs)
        return FakePredictor()

    sam3_module = types.ModuleType("sam3")
    builder_module = types.ModuleType("sam3.model_builder")
    builder_module.build_sam3_predictor = build_sam3_predictor
    monkeypatch.setitem(sys.modules, "sam3", sam3_module)
    monkeypatch.setitem(sys.modules, "sam3.model_builder", builder_module)
    monkeypatch.setattr(runner, "start_sam31_session", lambda *_args, **_kwargs: "session")

    def request_args(name: str) -> argparse.Namespace:
        root = tmp_path / name
        frames = root / "frames"
        frames.mkdir(parents=True)
        Image.fromarray(np.zeros((12, 16, 3), dtype=np.uint8), "RGB").save(frames / "00000.jpg")
        request = {
            "schema_version": "1.0.0",
            "operation": "refine",
            "concepts": [],
            "prompt": {
                "positive_points": [[5, 5]],
                "negative_points": [],
                "box_xyxy": [2, 1, 13, 11],
                "mask_prompt_sha256": None,
            },
            "visual_exemplars": [],
            "image_rgb_sha256": hashlib.sha256(name.encode()).hexdigest(),
            "authority": runner.AUTHORITY,
            "may_author_gold": False,
        }
        request_path = root / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        prompt_path = root / "prompt.npz"
        np.savez_compressed(prompt_path, mask_prompt=np.zeros((0, 0), dtype=bool))
        return argparse.Namespace(
            source_root=source_root,
            checkpoint=checkpoint,
            runtime_lock=runtime_lock,
            requirements_lock=requirements_lock,
            frame_dir=frames,
            request=request_path,
            prompt_npz=prompt_path,
            output=root / "output.npz",
            expected_source_commit=commit,
        )

    first = runner.execute(request_args("one"))
    second = runner.execute(request_args("two"))

    assert first["result_count"] == second["result_count"] == 1
    assert len(builds) == 1
    assert runner.resident_cache_stats() == {
        "resident_model_count": 1,
        "model_load_count": 1,
    }
