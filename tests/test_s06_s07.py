import json
import os
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

from maskfactory.providers.adapters import InteractiveSegmenterAdapter
from maskfactory.providers.contracts import MaskProposal, ProviderIdentity
from maskfactory.stages.s05_geometry import PromptPlan
from maskfactory.stages.s06_openvocab import (
    BoxProposal,
    OpenVocabError,
    infer_gdino_proposals,
    run_s06_production,
    write_gdino_proposals,
)
from maskfactory.stages.s07_sam2 import (
    MODEL_CONFIGS,
    ProviderNeutralInteractiveProvider,
    Sam2Error,
    SamCandidate,
    WslSam2Provider,
    build_embedding,
    cut_joint_ownership,
    postprocess_mask,
    refine_part,
    run_s07_production,
)


class FakeProvider:
    def __init__(self, predictions, *, oom=False):
        self.predictions = list(predictions)
        self.oom = oom
        self.embed_calls = []
        self.predict_calls = []

    def embed(self, image, *, model, precision):
        self.embed_calls.append((model, precision))
        if self.oom and "large" in model:
            raise RuntimeError("CUDA out of memory")
        return f"embedding:{model}"

    def predict(self, embedding, plan, *, multimask_output):
        self.predict_calls.append((embedding, plan, multimask_output))
        return self.predictions.pop(0)


def _plan() -> PromptPlan:
    return PromptPlan("left_forearm", (20, 20, 80, 80), ((50, 50),), ((5, 5),), "high")


def _logits(mask: np.ndarray) -> np.ndarray:
    return np.where(mask, 1.0, -1.0).astype(np.float32)


def test_provider_neutral_adapter_runs_canonical_interactive_segmenter() -> None:
    identity = ProviderIdentity(
        "sam3_1",
        "interactive_segmenter",
        "sam3",
        "source-fixture",
        "runtime-fixture",
    )
    captured: list[dict] = []
    mask = np.zeros((100, 100), dtype=bool)
    mask[30:70, 30:70] = True

    def refine(_embedding, *, prompt):
        captured.append(prompt)
        return (MaskProposal(mask, 0.92, identity, "prompt-fixture"),)

    primary = InteractiveSegmenterAdapter(identity, lambda image: image.shape, refine)
    fallback = FakeProvider([])
    provider = ProviderNeutralInteractiveProvider(
        primary,
        fallback,
        primary_model="sam3_1",
    )
    embedding, model = build_embedding(
        provider,
        np.zeros((100, 100, 3), dtype=np.uint8),
        primary_model="sam3_1",
        fallback_model="sam2.1_hiera_base_plus",
    )
    prior = mask.astype(np.uint8) * 255
    result = refine_part(provider, embedding, _plan(), prior, model=model)

    assert model == "sam3_1"
    assert result.model == "sam3_1"
    assert np.array_equal(result.mask, mask)
    assert captured == [
        {
            "positive_points": [(50, 50)],
            "negative_points": [(5, 5)],
            "box_xyxy": [20, 20, 80, 80],
            "mask_prompt": None,
        }
    ]
    assert fallback.embed_calls == []


def test_provider_neutral_adapter_uses_governed_sam2_fallback_only_on_oom() -> None:
    identity = ProviderIdentity(
        "sam3_1",
        "interactive_segmenter",
        "sam3",
        "source-fixture",
        "runtime-fixture",
    )

    def oom(_image):
        raise RuntimeError("CUDA out of memory")

    primary = InteractiveSegmenterAdapter(identity, oom, lambda *_args, **_kwargs: ())
    fallback = FakeProvider([])
    provider = ProviderNeutralInteractiveProvider(
        primary,
        fallback,
        primary_model="sam3_1",
    )
    embedding, model = build_embedding(
        provider,
        np.zeros((100, 100, 3), dtype=np.uint8),
        primary_model="sam3_1",
        fallback_model="sam2.1_hiera_base_plus",
    )

    assert model == "sam2.1_hiera_base_plus"
    assert embedding.route == "fallback"
    assert fallback.embed_calls == [("sam2.1_hiera_base_plus", "fp16")]


def test_s07_production_writes_strict_masks_metrics_and_one_embedding(tmp_path: Path) -> None:
    source = np.zeros((100, 100, 3), dtype=np.uint8)
    Image.fromarray(source, mode="RGB").save(tmp_path / "person.png")
    prior = np.zeros((100, 100), dtype=np.uint8)
    prior[30:70, 30:70] = 255
    Image.fromarray(prior, mode="L").save(tmp_path / "prior_left_forearm.png")
    plan = _plan()
    (tmp_path / "prompts.json").write_text(
        json.dumps(
            {
                "plans": [
                    {
                        "label": plan.label,
                        "box_xyxy": plan.box_xyxy,
                        "positive_points": plan.positive_points,
                        "negative_points": plan.negative_points,
                        "prior_quality": plan.prior_quality,
                        "multimask_output": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    provider = FakeProvider([[SamCandidate(_logits(prior > 0), 0.9)]])
    results, model = run_s07_production(
        tmp_path / "person.png",
        tmp_path / "prompts.json",
        tmp_path,
        tmp_path / "output",
        provider=provider,
    )
    assert model == "sam2.1_hiera_large"
    assert provider.embed_calls == [("sam2.1_hiera_large", "fp16")]
    assert set(results) == {"left_forearm"}
    mask = Image.open(tmp_path / "output/sam2_left_forearm.png")
    assert mask.mode == "L" and set(np.unique(np.asarray(mask)).tolist()) == {0, 255}
    metrics = json.loads((tmp_path / "output/sam2_metrics.json").read_text())
    assert metrics["embedding_count"] == 1
    assert metrics["prediction_count"] == 1
    assert metrics["parts"]["left_forearm"]["predicted_iou"] == 0.9


def test_s06_writes_only_configured_thresholded_proposal_boxes(tmp_path: Path) -> None:
    config = yaml.safe_load(Path("configs/prompting.yaml").read_text())["grounding_dino"]
    proposals = [
        BoxProposal("hair", (1, 2, 20, 30), 0.8, 0.7),
        BoxProposal("shoe", (5, 6, 10, 12), 0.29, 0.9),
    ]
    path = write_gdino_proposals(
        proposals,
        tmp_path,
        allowed_prompts=set(config["prompts"]),
        box_threshold=config["box_threshold"],
        text_threshold=config["text_threshold"],
    )
    document = json.loads(path.read_text())
    assert document["authority"] == "proposal_boxes_only"
    assert document["may_write_final_masks"] is False
    assert document["allowed_consumers"] == ["sam2_prompting", "fusion_evidence"]
    assert [proposal["prompt"] for proposal in document["proposals"]] == ["hair"]
    assert not list(tmp_path.glob("*.png"))
    with pytest.raises(OpenVocabError, match="unconfigured"):
        write_gdino_proposals(
            [BoxProposal("person", (0, 0, 2, 2), 1, 1)],
            tmp_path,
            allowed_prompts=set(config["prompts"]),
        )


@pytest.mark.skipif(os.name != "nt", reason="WSL bridge adapter requires a Windows host")
def test_s06_production_provider_preserves_proposal_only_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "image.png"
    Image.new("RGB", (40, 40), "white").save(image)
    checkpoint = tmp_path / "gdino.pth"
    checkpoint.write_bytes(b"fixture")

    def fake_run(command, **kwargs):
        assert "run_groundingdino_wsl.py" in " ".join(command)

        class Process:
            returncode = 0
            stderr = ""
            stdout = json.dumps(
                {
                    "protocol_version": 1,
                    "checkpoint_sha256": (
                        "3b3ca2563c77c69f651d7bd133e97139c186df06231157a64c507099c52bc799"
                    ),
                    "source_revision": "856dde20aee659246248e20734ef9ba5214f5e44",
                    "device_type": "cpu",
                    "device": "CPU fixture",
                    "model_load_count": 1,
                    "prompts": ["hair", "shoe"],
                    "box_threshold": 0.3,
                    "text_threshold": 0.25,
                    "image_size": [40, 40],
                    "authority": "proposal_boxes_only",
                    "may_write_final_masks": False,
                    "proposals": [
                        {
                            "prompt": "hair",
                            "bbox_xyxy": [1, 2, 20, 30],
                            "box_score": 0.8,
                            "text_score": 0.7,
                            "authority": "proposal_only",
                        }
                    ],
                }
            )

        return Process()

    monkeypatch.setattr("maskfactory.stages.s06_openvocab.subprocess.run", fake_run)
    proposals = infer_gdino_proposals(image, checkpoint=checkpoint, prompts=("hair", "shoe"))
    assert proposals == [BoxProposal("hair", (1.0, 2.0, 20.0, 30.0), 0.8, 0.7)]
    assert not hasattr(proposals[0], "mask")


def test_s06_production_refuses_prompt_vocabulary_drift(tmp_path: Path) -> None:
    with pytest.raises(OpenVocabError, match="vocabulary drifted"):
        run_s06_production(
            tmp_path / "missing.png",
            tmp_path / "output",
            checkpoint=tmp_path / "missing.pth",
            prompts=("hair",),
        )


def test_s06_provider_supports_pinned_local_cpu_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "image.png"
    Image.new("RGB", (40, 40), "white").save(image)
    checkpoint = tmp_path / "gdino.pth"
    checkpoint.write_bytes(b"fixture")
    python = tmp_path / "python.exe"
    python.write_bytes(b"fixture")
    source = tmp_path / "source"
    deps = tmp_path / "deps"
    (source / "groundingdino").mkdir(parents=True)
    (source / "groundingdino/__init__.py").write_text("", encoding="utf-8")
    (deps / "transformers").mkdir(parents=True)

    def fake_run(command, **kwargs):
        assert command[0] == str(python)
        assert kwargs["env"]["PYTHONPATH"].split(os.pathsep)[:2] == [
            str(source.resolve()),
            str(deps.resolve()),
        ]

        class Process:
            returncode = 0
            stderr = ""
            stdout = json.dumps(
                {
                    "protocol_version": 1,
                    "checkpoint_sha256": (
                        "3b3ca2563c77c69f651d7bd133e97139c186df06231157a64c507099c52bc799"
                    ),
                    "source_revision": "856dde20aee659246248e20734ef9ba5214f5e44",
                    "device_type": "cpu",
                    "device": "CPU fixture",
                    "model_load_count": 1,
                    "prompts": ["hair"],
                    "box_threshold": 0.3,
                    "text_threshold": 0.25,
                    "image_size": [40, 40],
                    "authority": "proposal_boxes_only",
                    "may_write_final_masks": False,
                    "proposals": [],
                }
            )

        return Process()

    monkeypatch.setattr("maskfactory.stages.s06_openvocab.subprocess.run", fake_run)
    runtime = tmp_path / "runtime.json"
    assert not infer_gdino_proposals(
        image,
        checkpoint=checkpoint,
        prompts=("hair",),
        local_python=python,
        source_path=source,
        dependency_site=deps,
        hf_home=tmp_path / "hf",
        runtime_path=runtime,
    )
    document = json.loads(runtime.read_text(encoding="utf-8"))
    assert document["launcher"] == "local_cpu"
    assert document["proposal_count"] == 0
    assert "proposals" not in document


def test_s07_embedding_uses_one_primary_or_one_oom_fallback() -> None:
    normal = FakeProvider([])
    embedding, model = build_embedding(normal, np.zeros((4, 4, 3)))
    assert model == "sam2.1_hiera_large"
    assert normal.embed_calls == [("sam2.1_hiera_large", "fp16")]
    fallback = FakeProvider([], oom=True)
    embedding, model = build_embedding(fallback, np.zeros((4, 4, 3)))
    assert model == "sam2.1_hiera_base_plus"
    assert fallback.embed_calls == [
        ("sam2.1_hiera_large", "fp16"),
        ("sam2.1_hiera_base_plus", "fp16"),
    ]


def test_s07_all_specialist_plans_still_record_one_embedding(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    Image.new("RGB", (100, 100), "white").save(image)
    prompts = tmp_path / "prompts.json"
    prompts.write_text(
        json.dumps(
            {
                "plans": [
                    {
                        "label": "hair",
                        "box_xyxy": [10, 10, 90, 90],
                        "positive_points": [[50, 50]],
                        "negative_points": [],
                        "prior_quality": "high",
                        "multimask_output": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    provider = FakeProvider([])
    results, model = run_s07_production(
        image,
        prompts,
        tmp_path,
        tmp_path / "output",
        provider=provider,
    )
    assert results == {}
    assert model == "sam2.1_hiera_large"
    assert provider.embed_calls == [("sam2.1_hiera_large", "fp16")]
    metrics = json.loads((tmp_path / "output/sam2_metrics.json").read_text(encoding="utf-8"))
    assert metrics["embedding_count"] == 1
    assert metrics["prediction_count"] == 0


@pytest.mark.skipif(os.name != "nt", reason="WSL bridge adapter requires a Windows host")
def test_s07_persistent_provider_embeds_once_and_serves_multimask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    large = tmp_path / "large.pt"
    base = tmp_path / "base.pt"
    large.write_bytes(b"large")
    base.write_bytes(b"base")

    def windows_path(value: str) -> Path:
        assert value.startswith("/mnt/c/")
        return Path("C:/" + value.removeprefix("/mnt/c/"))

    class Output:
        def __init__(self):
            self.lines = [
                json.dumps(
                    {
                        "protocol_version": 1,
                        "status": "ready",
                        "shape": [100, 100],
                        "model": "sam2.1_hiera_large",
                        "checkpoint_sha256": (
                            "2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318"
                        ),
                        "config": "configs/sam2.1/sam2.1_hiera_l.yaml",
                        "precision": "fp16",
                        "device_type": "cuda",
                        "device": "NVIDIA fixture",
                        "torch": "2.11.0+cu128",
                        "source_revision": "2b90b9f5ceec907a1c18123530e92e794ad901a4",
                        "embedding_count": 1,
                    }
                )
                + "\n"
            ]

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    class Error:
        def read(self):
            return ""

    class Process:
        def __init__(self, command, **kwargs):
            self.stdout = Output()
            self.stderr = Error()
            self.alive = True
            self.prediction_index = 0
            outer = self

            class Input:
                def write(self, value):
                    request = json.loads(value)
                    output = windows_path(request["output"])
                    logits = np.stack(
                        (
                            np.ones((100, 100), dtype=np.float32),
                            -np.ones((100, 100), dtype=np.float32),
                            np.ones((100, 100), dtype=np.float32),
                        )
                    )
                    np.savez_compressed(
                        output,
                        logits=logits,
                        scores=np.array([0.9, 0.5, 0.8], dtype=np.float32),
                    )
                    outer.prediction_index += 1
                    outer.stdout.lines.append(
                        json.dumps(
                            {
                                "protocol_version": 1,
                                "status": "ok",
                                "request_id": request["request_id"],
                                "count": 3,
                                "shape": [100, 100],
                                "embedding_count": 1,
                                "prediction_index": outer.prediction_index,
                                "multimask_output": True,
                            }
                        )
                        + "\n"
                    )

                def flush(self):
                    pass

            self.stdin = Input()

        def poll(self):
            return None if self.alive else 0

        def terminate(self):
            self.alive = False

        def wait(self, timeout):
            return 0

    monkeypatch.setattr("maskfactory.stages.s07_sam2.subprocess.Popen", Process)
    provider = WslSam2Provider(
        {
            "sam2.1_hiera_large": large,
            "sam2.1_hiera_base_plus": base,
        },
        {
            "sam2.1_hiera_large": "configs/sam2.1/sam2.1_hiera_l.yaml",
            "sam2.1_hiera_base_plus": "configs/sam2.1/sam2.1_hiera_b+.yaml",
        },
        tmp_path / "work",
    )
    embedding, model = build_embedding(provider, np.zeros((100, 100, 3), dtype=np.uint8))
    assert model == "sam2.1_hiera_large"
    candidates = provider.predict(embedding, _plan(), multimask_output=True)
    assert len(candidates) == 3
    assert [candidate.predicted_iou for candidate in candidates] == pytest.approx([0.9, 0.5, 0.8])
    assert all(candidate.logits.shape == (100, 100) for candidate in candidates)
    provider.close(embedding)
    runtime = json.loads((tmp_path / "work/runtime.json").read_text(encoding="utf-8"))
    assert runtime["launcher"] == "wsl_cuda"


@pytest.mark.skipif(os.name != "nt", reason="WSL bridge adapter requires a Windows host")
def test_s07_wsl_provider_translates_large_oom_and_builds_one_base_embedding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    large = tmp_path / "large.pt"
    base = tmp_path / "base.pt"
    large.write_bytes(b"large")
    base.write_bytes(b"base")
    calls = []

    class Input:
        def write(self, value):
            pass

        def flush(self):
            pass

    class Error:
        def __init__(self, text=""):
            self.text = text

        def read(self):
            return self.text

    class Output:
        def __init__(self, line):
            self.line = line

        def readline(self):
            line, self.line = self.line, ""
            return line

    class Process:
        def __init__(self, command, **kwargs):
            model = command[command.index("--model-key") + 1]
            calls.append(model)
            self.alive = model != "sam2.1_hiera_large"
            self.stdin = Input()
            if model == "sam2.1_hiera_large":
                self.stdout = Output("")
                self.stderr = Error("CUDA out of memory")
            else:
                self.stdout = Output(
                    json.dumps(
                        {
                            "protocol_version": 1,
                            "status": "ready",
                            "shape": [20, 20],
                            "model": model,
                            "checkpoint_sha256": (
                                "a2345aede8715ab1d5d31b4a509fb160c5a4af1970f199d9054ccfb746c004c5"
                            ),
                            "config": "configs/sam2.1/sam2.1_hiera_b+.yaml",
                            "precision": "fp16",
                            "device_type": "cuda",
                            "device": "NVIDIA fixture",
                            "torch": "2.11.0+cu128",
                            "source_revision": "2b90b9f5ceec907a1c18123530e92e794ad901a4",
                            "embedding_count": 1,
                        }
                    )
                    + "\n"
                )
                self.stderr = Error()

        def poll(self):
            return None if self.alive else 1

        def terminate(self):
            self.alive = False

        def wait(self, timeout):
            return 0

    monkeypatch.setattr("maskfactory.stages.s07_sam2.subprocess.Popen", Process)
    provider = WslSam2Provider(
        {
            "sam2.1_hiera_large": large,
            "sam2.1_hiera_base_plus": base,
        },
        {
            "sam2.1_hiera_large": "configs/sam2.1/sam2.1_hiera_l.yaml",
            "sam2.1_hiera_base_plus": "configs/sam2.1/sam2.1_hiera_b+.yaml",
        },
        tmp_path / "work",
    )

    embedding, model = build_embedding(provider, np.zeros((20, 20, 3), dtype=np.uint8))

    assert model == "sam2.1_hiera_base_plus"
    assert calls == ["sam2.1_hiera_large", "sam2.1_hiera_base_plus"]
    provider.close(embedding)
    runtime = json.loads((tmp_path / "work/runtime.json").read_text(encoding="utf-8"))
    assert runtime["model"] == "sam2.1_hiera_base_plus"


def test_s07_provider_supports_explicit_local_cuda_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    large = tmp_path / "large.pt"
    base = tmp_path / "base.pt"
    python = tmp_path / "python.exe"
    for path in (large, base, python):
        path.write_bytes(b"fixture")
    source = tmp_path / "source"
    deps = tmp_path / "deps"
    (source / "sam2").mkdir(parents=True)
    (source / "sam2/__init__.py").write_text("", encoding="utf-8")
    (deps / "hydra").mkdir(parents=True)

    class Output:
        def __init__(self):
            self.lines = [
                json.dumps(
                    {
                        "protocol_version": 1,
                        "status": "ready",
                        "shape": [100, 100],
                        "model": "sam2.1_hiera_large",
                        "checkpoint_sha256": (
                            "2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318"
                        ),
                        "config": "configs/sam2.1/sam2.1_hiera_l.yaml",
                        "precision": "fp16",
                        "device_type": "cuda",
                        "device": "NVIDIA fixture",
                        "torch": "2.11.0+cu128",
                        "source_revision": "2b90b9f5ceec907a1c18123530e92e794ad901a4",
                        "embedding_count": 1,
                    }
                )
                + "\n"
            ]

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    class Process:
        def __init__(self, command, **kwargs):
            assert command[0] == str(python)
            assert kwargs["env"]["PYTHONPATH"].split(os.pathsep)[:2] == [
                str(source.resolve()),
                str(deps.resolve()),
            ]
            self.stdout = Output()
            self.alive = True
            outer = self

            class Input:
                def write(self, value):
                    request = json.loads(value)
                    output = Path(request["output"])
                    np.savez_compressed(
                        output,
                        logits=np.zeros((3, 100, 100), dtype=np.float32),
                        scores=np.array([0.9, 0.8, 0.7], dtype=np.float32),
                    )
                    outer.stdout.lines.append(
                        json.dumps(
                            {
                                "protocol_version": 1,
                                "status": "ok",
                                "request_id": request["request_id"],
                                "embedding_count": 1,
                                "prediction_index": 1,
                                "multimask_output": True,
                            }
                        )
                        + "\n"
                    )

                def flush(self):
                    pass

            self.stdin = Input()
            self.stderr = None

        def poll(self):
            return None if self.alive else 0

        def terminate(self):
            self.alive = False

        def wait(self, timeout):
            return 0

    monkeypatch.setattr("maskfactory.stages.s07_sam2.subprocess.Popen", Process)
    provider = WslSam2Provider(
        {"sam2.1_hiera_large": large, "sam2.1_hiera_base_plus": base},
        MODEL_CONFIGS,
        tmp_path / "work",
        local_cuda_python=python,
        source_path=source,
        dependency_site=deps,
    )
    embedding = provider.embed(
        np.zeros((100, 100, 3), dtype=np.uint8),
        model="sam2.1_hiera_large",
        precision="fp16",
    )
    assert len(provider.predict(embedding, _plan(), multimask_output=True)) == 3
    provider.close(embedding)
    runtime = json.loads((tmp_path / "work/runtime.json").read_text(encoding="utf-8"))
    assert runtime["launcher"] == "local_cuda"


def test_s07_provider_refuses_config_mapping_drift(tmp_path: Path) -> None:
    with pytest.raises(Sam2Error, match="config mapping"):
        WslSam2Provider(
            {
                "sam2.1_hiera_large": tmp_path / "large.pt",
                "sam2.1_hiera_base_plus": tmp_path / "base.pt",
            },
            {
                "sam2.1_hiera_large": "wrong.yaml",
                "sam2.1_hiera_base_plus": "configs/sam2.1/sam2.1_hiera_b+.yaml",
            },
            tmp_path / "work",
        )


def test_s07_weighted_selection_and_single_corrective_iteration() -> None:
    prior = np.zeros((120, 120), dtype=bool)
    prior[30:90, 30:90] = True
    poor = np.zeros_like(prior)
    poor[0:70, 0:70] = True
    good = prior.copy()
    provider = FakeProvider(
        [
            [SamCandidate(_logits(poor), 0.95), SamCandidate(_logits(good), 0.70)],
        ]
    )
    result = refine_part(provider, "embedding", _plan(), prior, model="large")
    assert np.array_equal(result.mask, prior)
    assert result.predicted_iou == 0.70  # prior overlap dominates the weighted score
    assert not result.corrective_iteration
    assert provider.predict_calls[0][2] is True

    shifted = np.zeros_like(prior)
    shifted[30:90, 45:105] = True
    provider = FakeProvider(
        [
            [SamCandidate(_logits(shifted), 0.8)],
            [SamCandidate(_logits(good), 0.8)],
        ]
    )
    result = refine_part(
        provider,
        "embedding",
        _plan(),
        prior,
        model="large",
        skeleton_points_xy=((35, 50),),
    )
    assert result.corrective_iteration
    assert len(provider.predict_calls) == 2
    corrected_plan = provider.predict_calls[1][1]
    assert (35, 50) in corrected_plan.positive_points


def test_s07_low_confidence_keeps_prior_and_flags_review() -> None:
    prior = np.zeros((100, 100), dtype=bool)
    prior[20:80, 20:80] = True
    provider = FakeProvider([[SamCandidate(_logits(prior), 0.49)]])
    result = refine_part(provider, None, _plan(), prior, model="large")
    assert result.sam2_low_conf
    assert result.review_flags == ("sam2_low_conf", "careful_review")
    assert np.array_equal(result.mask, prior)


def test_s07_postprocess_exact_component_hole_and_joint_rules() -> None:
    mask = np.zeros((120, 120), dtype=bool)
    mask[20:100, 20:100] = True
    mask[40:42, 40:42] = False  # 4 px < 0.5%, fill
    mask[60:70, 60:70] = False  # 100 px > 0.5%, preserve
    mask[0:5, 0:5] = True  # 25 px < max(64, 2%), drop
    cleaned = postprocess_mask(mask)
    assert cleaned[40:42, 40:42].all()
    assert not cleaned[60:70, 60:70].any()
    assert not cleaned[0:5, 0:5].any()
    assert set(np.unique(cleaned)) <= {False, True}

    upper = np.zeros((20, 20), dtype=bool)
    forearm = np.zeros_like(upper)
    upper[5:15, 2:11] = True
    forearm[5:15, 9:18] = True
    band = np.zeros_like(upper)
    band[5:15, 9:11] = True
    owned = cut_joint_ownership(
        {"upper": upper, "forearm": forearm},
        {"elbow": band},
        {"elbow": ("upper", "forearm")},
    )
    assert np.array_equal(owned["elbow"], band)
    assert not (owned["upper"] & band).any() and not (owned["forearm"] & band).any()
    with pytest.raises(Sam2Error, match="adjacency"):
        cut_joint_ownership({"upper": upper}, {"elbow": band}, {})
