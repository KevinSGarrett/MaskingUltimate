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
    _normalize_refinement_box,
    _normalize_visual_exemplars,
)
from tools.run_sam31_runtime import (
    _payload_sha256 as runner_payload_sha256,
)

from maskfactory.providers.contracts import ConceptDetector, InteractiveSegmenter
from maskfactory.providers.sam31_exemplars import write_sam31_visual_exemplar
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


def _runtime(tmp_path: Path) -> OfficialSam31Runtime:
    """Create a dependency-injected runtime with portable governed path stubs."""
    runtime = OfficialSam31Runtime(path_mapper=lambda path: str(path))
    runtime.source_root = tmp_path / "sam31-source"
    runtime.source_root.mkdir()
    runtime.checkpoint = tmp_path / "sam31-checkpoint.pt"
    runtime.checkpoint.write_bytes(b"unit-test-checkpoint-stub")
    runtime.requirements_lock = tmp_path / "sam31-requirements.lock"
    runtime.requirements_lock.write_text("unit-test-runtime-stub\n", encoding="utf-8")
    return runtime


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


def _executor(runtime: OfficialSam31Runtime, *, mutate=None, returncode: int = 0, requests=None):
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
        if requests is not None:
            requests.append(request)
        arrays = _arrays(request)
        np.savez_compressed(output_path, **arrays)
        if request["operation"] == "discover" and request["visual_exemplars"]:
            prompt_translation = "text_plus_same_image_visual_box_exemplars_exact"
        elif request["operation"] == "discover":
            prompt_translation = "text_prompt_exact"
        elif request["prompt"]["box_xyxy"] is not None:
            prompt_translation = (
                "native_visual_box_prompt_exact_visual_text_center_point_postcondition_only"
            )
        else:
            prompt_translation = "mask_prior_to_native_visual_box_prompt_exact"
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
    runtime = _runtime(tmp_path)
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


def test_visual_exemplars_are_hash_bound_and_raw_external_images_fail_closed(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    requests = []
    runtime._executor = _executor(runtime, requests=requests)
    source = _image(tmp_path)
    raw_exemplar = tmp_path / "exemplar.png"
    raw_exemplar.write_bytes(source.read_bytes())
    with pytest.raises(Sam31RuntimeError, match="governed same-image"):
        runtime.discover(source, concepts=("hand",), exemplars=(raw_exemplar,))

    manifest = write_sam31_visual_exemplar(
        tmp_path / "positive-hand.json",
        source_image=source,
        bbox_xyxy=(3, 2, 11, 9),
    )
    discovered = runtime.discover(source, concepts=("hand",), exemplars=(manifest,))
    assert len(discovered) == 1
    assert requests[-1]["visual_exemplars"] == [
        {
            "bbox_xyxy": [3.0, 2.0, 11.0, 9.0],
            "polarity": "positive",
            "manifest_sha256": json.loads(manifest.read_text(encoding="utf-8"))["sha256"],
            "manifest_file_sha256": _sha256(manifest),
        }
    ]

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
    assert np.allclose(
        _normalize_refinement_box([4, 2, 10, 8], width=16, height=12),
        [4 / 16, 2 / 12, 6 / 16, 6 / 12],
    )

    normalized, labels = _normalize_visual_exemplars(
        [
            {
                "bbox_xyxy": [4, 2, 10, 8],
                "polarity": "positive",
                "manifest_sha256": "1" * 64,
                "manifest_file_sha256": "2" * 64,
            },
            {
                "bbox_xyxy": [1, 1, 3, 4],
                "polarity": "negative",
                "manifest_sha256": "3" * 64,
                "manifest_file_sha256": "4" * 64,
            },
        ],
        width=16,
        height=12,
    )
    assert np.allclose(normalized[0], [4 / 16, 2 / 12, 6 / 16, 6 / 12])
    assert labels == [1, 0]
    with pytest.raises(RuntimeError, match="duplicated"):
        _normalize_visual_exemplars(
            [
                {
                    "bbox_xyxy": [4, 2, 10, 8],
                    "polarity": "positive",
                    "manifest_sha256": "1" * 64,
                    "manifest_file_sha256": "2" * 64,
                },
                {
                    "bbox_xyxy": [1, 1, 3, 4],
                    "polarity": "negative",
                    "manifest_sha256": "1" * 64,
                    "manifest_file_sha256": "4" * 64,
                },
            ],
            width=16,
            height=12,
        )

    runner = (ROOT / "tools/run_sam31_runtime.py").read_text(encoding="utf-8")
    assert "build_sam3_predictor" in runner
    assert "build_sam3_image_model" not in runner
    assert 'version="sam3.1"' in runner
    assert '"text": concept' in runner
    assert 'payload["bounding_boxes"] = normalized_boxes' in runner
    assert 'payload["bounding_box_labels"] = box_labels' in runner
    assert '"text": "visual"' in runner
    assert '"bounding_boxes": [normalized_box]' in runner
    assert '"bounding_box_labels": [1]' in runner
    assert '"points": relative' not in runner


@pytest.mark.parametrize(
    "box",
    (None, [0, 0, 0, 1], [-1, 0, 1, 1], [0, 0, 17, 1], [0, 0, float("nan"), 1]),
)
def test_native_refinement_box_validation_fails_closed(box) -> None:
    with pytest.raises(RuntimeError, match="refinement box"):
        _normalize_refinement_box(box, width=16, height=12)


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
    runtime = _runtime(tmp_path)
    runtime._executor = _executor(runtime, mutate=mutate)
    with pytest.raises(Sam31RuntimeError, match=message):
        runtime.discover(_image(tmp_path), concepts=("person",))


def test_process_failure_preserves_cuda_oom_and_loaders_satisfy_contracts(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
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
