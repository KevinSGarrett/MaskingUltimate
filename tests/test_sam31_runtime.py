from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from tools.run_sam31_runtime import (
    _box_from_masks,
    _derived_positive,
)
from tools.run_sam31_runtime import (
    _payload_sha256 as runner_payload_sha256,
)

from maskfactory.providers.contracts import ConceptDetector, InteractiveSegmenter
from maskfactory.providers.sam31_runtime import (
    AUTHORITY,
    OfficialSam31Runtime,
    Sam31RuntimeError,
    load_official_sam31_concept_detector,
    load_official_sam31_interactive_segmenter,
    sam31_runtime_payload_sha256,
)

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _image(tmp_path: Path) -> Path:
    path = tmp_path / "image.png"
    pixels = np.zeros((12, 16, 3), dtype=np.uint8)
    pixels[2:9, 3:11] = (120, 80, 40)
    Image.fromarray(pixels, "RGB").save(path)
    return path


def _arrays(request: dict) -> dict[str, np.ndarray]:
    mask = np.zeros((1, 12, 16), dtype=bool)
    mask[0, 3:6, 3:6] = True
    return {
        "masks": mask,
        "object_ids": np.asarray([1], dtype=np.int64),
        "probabilities": np.asarray([0.95], dtype=np.float32),
        "boxes_xywh": np.asarray([[3 / 16, 3 / 12, 3 / 16, 3 / 12]], dtype=np.float32),
        "concept_indices": np.asarray(
            [0 if request["operation"] == "discover" else -1], dtype=np.int64
        ),
    }


def _executor(runtime: OfficialSam31Runtime, *, mutate=None, returncode: int = 0):
    def execute(argv, timeout):
        assert argv[:5] == (
            "wsl.exe",
            "-d",
            "Ubuntu-22.04",
            "--",
            runtime.runtime_python,
        )
        assert timeout == 1200
        if returncode:
            return subprocess.CompletedProcess(argv, returncode, "", "CUDA out of memory")
        request_path = Path(argv[argv.index("--request") + 1])
        prompt_path = Path(argv[argv.index("--prompt-npz") + 1])
        frame_path = Path(argv[argv.index("--frame-dir") + 1]) / "00000.jpg"
        output_path = Path(argv[argv.index("--output") + 1])
        request = json.loads(request_path.read_text(encoding="utf-8"))
        arrays = _arrays(request)
        np.savez_compressed(output_path, **arrays)
        if request["operation"] == "discover":
            prompt_translation = "text_prompt_exact"
        elif request["prompt"]["positive_points"]:
            prompt_translation = "point_prompt_exact_with_optional_roi_clip"
        else:
            prompt_translation = (
                "box_or_mask_prior_to_deterministic_positive_point_with_optional_roi_clip"
            )
        report = {
            "schema_version": "1.0.0",
            "provider": "sam3_1",
            "operation": request["operation"],
            "source_commit": runtime.lock["source"]["commit"],
            "source_tree_clean": True,
            "runtime_lock_sha256": _sha256(runtime.lock_path),
            "requirements_lock_sha256": runtime.lock["runtime"]["requirements_lock_sha256"],
            "checkpoint_sha256": runtime.lock["checkpoint"]["sha256"],
            "request_sha256": _sha256(request_path),
            "image_rgb_sha256": request["image_rgb_sha256"],
            "encoded_frame_sha256": _sha256(frame_path),
            "prompt_npz_sha256": _sha256(prompt_path),
            "builder": "build_sam3_predictor",
            "version": "sam3.1",
            "result_count": 1,
            "artifact_shapes": {name: list(value.shape) for name, value in arrays.items()},
            "payload_sha256": sam31_runtime_payload_sha256(arrays),
            "output_npz_sha256": _sha256(output_path),
            "model_load_latency_ms": 10_000.0,
            "inference_latency_ms": 1_500.0,
            "model_vram_bytes": 7_000_000_000,
            "peak_inference_vram_bytes": 7_500_000_000,
            "prompt_translation": prompt_translation,
            "authority": AUTHORITY,
            "may_author_gold": False,
        }
        if mutate is not None:
            mutate(report)
        return subprocess.CompletedProcess(argv, 0, json.dumps(report), "")

    return execute


def test_official_runtime_emits_text_discovery_and_point_refinement(tmp_path: Path) -> None:
    runtime = OfficialSam31Runtime(path_mapper=lambda path: str(path))
    runtime._executor = _executor(runtime)
    source = _image(tmp_path)
    discovered = runtime.discover(source, concepts=("visible left hand",))
    assert len(discovered) == 1
    assert discovered[0]["kind"] == "mask"
    assert discovered[0]["label"] == "visible left hand"
    assert discovered[0]["value"].dtype == np.bool_
    assert len(discovered[0]["instance_key"]) == 24

    image = np.asarray(Image.open(source).convert("RGB"))
    embedding = runtime.embed(image)
    assert embedding.rgb.flags.writeable is False
    refined = runtime.refine(
        embedding,
        prompt={
            "positive_points": ((4, 4),),
            "negative_points": ((7, 7),),
            "box_xyxy": (2.0, 2.0, 8.0, 8.0),
            "mask_prompt_sha256": None,
        },
    )
    assert len(refined) == 1
    assert refined[0][0][4, 4]
    assert not refined[0][0][7, 7]
    assert refined[0][1] == pytest.approx(0.95)


def test_mask_prior_is_hash_bound_and_external_exemplars_fail_closed(tmp_path: Path) -> None:
    runtime = OfficialSam31Runtime(path_mapper=lambda path: str(path))
    runtime._executor = _executor(runtime)
    source = _image(tmp_path)
    exemplar = tmp_path / "exemplar.png"
    exemplar.write_bytes(source.read_bytes())
    with pytest.raises(Sam31RuntimeError, match="cannot be silently ignored"):
        runtime.discover(source, concepts=("hand",), exemplars=(exemplar,))

    embedding = runtime.embed(np.asarray(Image.open(source).convert("RGB")))
    mask = np.zeros((12, 16), dtype=bool)
    mask[3:6, 3:6] = True
    valid = runtime.refine(
        embedding,
        prompt={
            "positive_points": (),
            "negative_points": (),
            "box_xyxy": None,
            "mask_prompt_sha256": hashlib.sha256(mask.tobytes()).hexdigest(),
            "mask_prompt": mask,
        },
    )
    assert valid[0][0][4, 4]
    with pytest.raises(Sam31RuntimeError, match="hash is stale"):
        runtime.refine(
            embedding,
            prompt={
                "positive_points": (),
                "negative_points": (),
                "box_xyxy": None,
                "mask_prompt_sha256": "0" * 64,
                "mask_prompt": mask,
            },
        )


def test_host_and_runner_share_payload_hash_and_deterministic_prompt_geometry() -> None:
    request = {"operation": "refine"}
    arrays = _arrays(request)
    assert sam31_runtime_payload_sha256(arrays) == runner_payload_sha256(arrays)

    mask = np.zeros((12, 16), dtype=bool)
    mask[2:8, 4:10] = True
    point = _derived_positive(mask)
    assert mask[point[1], point[0]]
    assert point == _derived_positive(mask.copy())
    boxes = _box_from_masks(mask[None, :, :], height=12, width=16)
    assert boxes.shape == (1, 4)
    assert np.allclose(boxes[0], [4 / 16, 2 / 12, 6 / 16, 6 / 12])

    runner = (ROOT / "tools/run_sam31_runtime.py").read_text(encoding="utf-8")
    assert "build_sam3_predictor" in runner
    assert "build_sam3_image_model" not in runner
    assert 'version="sam3.1"' in runner
    assert '"text": concept' in runner
    assert '"point_labels": labels' in runner


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda report: report.update(extra="field"), "fields are not closed"),
        (lambda report: report.update(builder="build_sam3_image_model"), "identity or authority"),
        (lambda report: report.update(may_author_gold=True), "identity or authority"),
        (lambda report: report.update(output_npz_sha256="0" * 64), "artifact SHA-256"),
        (lambda report: report.update(payload_sha256="0" * 64), "payload SHA-256"),
        (lambda report: report.update(result_count=2), "result count"),
    ],
)
def test_official_runtime_rejects_report_and_artifact_drift(
    tmp_path: Path, mutate, message: str
) -> None:
    runtime = OfficialSam31Runtime(path_mapper=lambda path: str(path))
    runtime._executor = _executor(runtime, mutate=mutate)
    with pytest.raises(Sam31RuntimeError, match=message):
        runtime.discover(_image(tmp_path), concepts=("person",))


def test_process_failure_preserves_cuda_oom_and_loaders_satisfy_contracts(tmp_path: Path) -> None:
    runtime = OfficialSam31Runtime(path_mapper=lambda path: str(path))
    runtime._executor = _executor(runtime, returncode=1)
    with pytest.raises(Sam31RuntimeError, match="CUDA out of memory"):
        runtime.discover(_image(tmp_path), concepts=("person",))

    concept = load_official_sam31_concept_detector()
    interactive = load_official_sam31_interactive_segmenter()
    assert isinstance(concept, ConceptDetector)
    assert isinstance(interactive, InteractiveSegmenter)
    assert concept.identity.provider_key == interactive.identity.provider_key == "sam3_1"
    assert concept.identity.role == "concept_detector"
    assert interactive.identity.role == "interactive_segmenter"
