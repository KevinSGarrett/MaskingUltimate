import base64
import hashlib
import io
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch
import yaml
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.models.ontology_contract import (
    V1_ONTOLOGY_VERSION,
    V1_PART_CLASS_NAMES,
    class_names_sha256,
)
from maskfactory.models.registry import CHAMPION_HAND_CLASS_NAMES
from maskfactory.providers.adapters import InteractiveSegmenterAdapter
from maskfactory.providers.contracts import MaskProposal, ProviderIdentity
from maskfactory.serve.api import (
    InferenceRuntime,
    OnDemandRefiner,
    ServingError,
    create_production_runtime,
    probe_vram,
)
from maskfactory.serve.comfy_export import ComfyPackageError, MFPredictMasks
from maskfactory.serve.providers import (
    ServingProviderError,
    load_active_interactive_refiner,
    load_production_mmseg_slot,
    load_production_sam2_refiner,
    production_sam2_runtime_options,
)
from maskfactory.stages.s07_sam2 import SamCandidate
from maskfactory.validation import validate_document
from registry_helpers import (
    governed_file_model,
    governed_ollama_model,
    governed_registry,
)


def _png(width: int = 24, height: int = 16) -> bytes:
    output = io.BytesIO()
    Image.fromarray(np.full((height, width, 3), 80, dtype=np.uint8)).save(output, format="PNG")
    return output.getvalue()


def _registry(path: Path) -> Path:
    path.write_text(
        json.dumps(
            governed_registry(
                [
                    governed_file_model(
                        key="champion",
                        role="champion_bodypart",
                        file="models/champion.pth",
                        sha256="a" * 64,
                    )
                ]
            )
        ),
        encoding="utf-8",
    )
    return path


def test_serve_cli_is_loopback_only_and_runtime_dependencies_are_locked(
    monkeypatch,
) -> None:
    lock = Path("env/requirements.lock.txt").read_text(encoding="utf-8").splitlines()
    assert "fastapi==0.139.0" in lock
    assert "uvicorn==0.51.0" in lock
    assert "python-multipart==0.0.32" in lock
    calls = []
    fake_uvicorn = SimpleNamespace(run=lambda app, **kwargs: calls.append((app, kwargs)))
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    sentinel = object()
    monkeypatch.setattr("maskfactory.serve.api.create_app", lambda: sentinel)
    result = CliRunner().invoke(main, ["serve", "--port", "9876"])
    assert result.exit_code == 0, result.output
    assert calls == [(sentinel, {"host": "127.0.0.1", "port": 9876, "log_level": "info"})]


def test_fastapi_multipart_endpoints_use_resolvable_in_memory_bytes_annotations() -> None:
    source = Path("src/maskfactory/serve/api.py").read_text(encoding="utf-8")
    assert source.count("image: bytes = File(...)") == 2
    assert "UploadFile" not in source
    assert "await image.read()" not in source


def test_serving_predictor_resolves_verified_champion_role_only(tmp_path: Path) -> None:
    models_root = tmp_path / "models"
    models_root.mkdir()
    checkpoint = models_root / "champion.bin"
    checkpoint.write_bytes(b"verified champion fixture")
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            governed_registry(
                [
                    governed_file_model(
                        key="body_v3",
                        file="models/champion.bin",
                        role="champion_bodypart",
                        version_tag="body-v3",
                        sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                    )
                ]
            )
        ),
        encoding="utf-8",
    )
    loaded = []

    def loader(checkpoints):
        loaded.append(dict(checkpoints))
        return lambda image, labels: {
            label: np.zeros(image.shape[:2], dtype=bool) for label in labels
        }

    runtime = InferenceRuntime(
        registry_path=registry, models_root=models_root, gpu_lock_path=tmp_path / "gpu.lock"
    )
    runtime.configure_champion_predictor(loader)
    assert loaded == [{"champion_bodypart": checkpoint}]
    assert runtime.loaded_models == ["champion_bodypart"]
    with pytest.raises(ServingError, match=r"champion_\* roles only"):
        runtime.configure_champion_predictor(loader, roles=("primary_human_parsing",))

    checkpoint.write_bytes(b"tampered")
    untrusted = InferenceRuntime(registry_path=registry, models_root=models_root)
    with pytest.raises(ServingError, match="hash mismatch"):
        untrusted.configure_champion_predictor(loader)


def test_models_endpoint_supports_governed_ollama_registry_entries(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            governed_registry(
                [
                    governed_ollama_model(
                        key="ollama_qwen",
                        role="local_vlm",
                        ollama_name="qwen2.5vl:7b",
                        digest="a" * 64,
                    )
                ]
            )
        ),
        encoding="utf-8",
    )
    runtime = InferenceRuntime(registry_path=registry)
    assert runtime.models()["models"] == [
        {
            "key": "ollama_qwen",
            "role": "local_vlm",
            "version_tag": "qwen2.5vl:7b",
            "sha256": "a" * 64,
            "ontology_version": None,
            "class_names_sha256": None,
        }
    ]


def test_sequential_champion_slots_and_sam2_on_demand_never_coreside(tmp_path: Path) -> None:
    models_root = tmp_path / "models"
    models_root.mkdir()
    entries = []
    for role in ("champion_bodypart", "champion_hand", "champion_clothing"):
        checkpoint = models_root / f"{role}.bin"
        checkpoint.write_bytes(role.encode())
        entries.append(
            governed_file_model(
                key=role,
                file=f"models/{checkpoint.name}",
                role=role,
                sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            )
        )
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(governed_registry(entries)), encoding="utf-8")
    events = []

    class Slot:
        def __init__(self, role):
            self.role = role
            events.append(("load", role))

        def __call__(self, image, labels):
            events.append(("call", self.role, labels))
            return {label: np.zeros(image.shape[:2], dtype=bool) for label in labels}

        def close(self):
            events.append(("close", self.role))

    sam_events = []

    class Sam:
        def __init__(self):
            sam_events.append("load")

        def __call__(self, image, _label, _clicks):
            sam_events.append("call")
            return np.zeros(image.shape[:2], dtype=bool)

        def close(self):
            sam_events.append("close")

    runtime = InferenceRuntime(
        registry_path=registry, models_root=models_root, gpu_lock_path=tmp_path / "gpu.lock"
    )
    runtime.configure_sequential_champions(lambda role, _path: Slot(role))
    runtime.configure_on_demand_refiner(Sam)
    assert events == [] and sam_events == []
    assert runtime.health()["loaded_models"] == []
    assert runtime.health()["configured_models"] == [
        "champion_bodypart",
        "champion_hand",
        "champion_clothing",
    ]
    runtime.start()
    response = runtime.predict(_png(), ("hair", "left_index_finger", "clothing_generic"))
    assert events == [
        ("load", "champion_bodypart"),
        ("call", "champion_bodypart", ("hair",)),
        ("close", "champion_bodypart"),
        ("load", "champion_hand"),
        ("call", "champion_hand", ("left_index_finger",)),
        ("close", "champion_hand"),
        ("load", "champion_clothing"),
        ("call", "champion_clothing", ("clothing_generic",)),
        ("close", "champion_clothing"),
    ]
    assert response["manifest"]["hair"]["provenance"]["models"] == ["champion_bodypart"]
    assert response["manifest"]["left_index_finger"]["provenance"]["models"] == ["champion_hand"]
    assert runtime.health()["loaded_models"] == []
    runtime.refine(_png(), "hair", ({"x": 1, "y": 1, "positive": True},))
    assert sam_events == ["load", "call"]
    assert runtime.refiner.provider is not None
    runtime.predict(_png(), ("hair",))
    assert sam_events == ["load", "call", "close"]
    assert runtime.refiner.provider is None
    runtime.stop()


def test_production_mmseg_slot_requires_hashed_config_and_maps_explicit_classes(
    tmp_path: Path,
) -> None:
    models_root = tmp_path / "models"
    models_root.mkdir()
    checkpoint = models_root / "body.pth"
    checkpoint.write_bytes(b"champion")
    config = models_root / "body.py"
    config.write_text("model = dict(type='fixture')\n", encoding="utf-8")
    registry = tmp_path / "registry.json"
    entry = governed_file_model(
        key="body",
        file="models/body.pth",
        role="champion_bodypart",
        sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        inference_config="models/body.py",
        inference_config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
        ontology_version=V1_ONTOLOGY_VERSION,
        class_names=list(V1_PART_CLASS_NAMES),
        class_names_sha256=class_names_sha256(list(V1_PART_CLASS_NAMES)),
        artifact_hashes={
            "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            "inference_config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        },
    )
    registry.write_text(json.dumps(governed_registry([entry])), encoding="utf-8")
    calls = []

    class Tensor:
        def detach(self):
            return self

        def cpu(self):
            return np.array([[[0, 1], [14, 1]]], dtype=np.int64)

    model = SimpleNamespace(to=lambda device: calls.append(("to", device)))
    slot = load_production_mmseg_slot(
        "champion_bodypart",
        checkpoint,
        registry_path=registry,
        models_root=models_root,
        initializer=lambda config_path, checkpoint_path, device: (
            calls.append((config_path, checkpoint_path, device)) or model
        ),
        inference=lambda _model, _image: SimpleNamespace(
            pred_sem_seg=SimpleNamespace(data=Tensor())
        ),
    )
    outputs = slot(np.zeros((2, 2, 3), dtype=np.uint8), ("hair", "left_upper_arm"))
    assert outputs["hair"].tolist() == [[False, True], [False, True]]
    assert outputs["left_upper_arm"].tolist() == [[False, False], [True, False]]
    assert calls[0] == (str(config), str(checkpoint), "cuda:0")
    slot.close()
    assert calls[-1] == ("to", "cpu")

    entry["inference_config_sha256"] = "0" * 64
    entry["artifact_hashes"]["inference_config_sha256"] = "0" * 64
    registry.write_text(json.dumps(governed_registry([entry])), encoding="utf-8")
    with pytest.raises(ServingProviderError, match="config hash mismatch"):
        load_production_mmseg_slot(
            "champion_bodypart",
            checkpoint,
            registry_path=registry,
            models_root=models_root,
            initializer=lambda *_args, **_kwargs: model,
            inference=lambda *_args: None,
        )


def test_production_mmseg_slot_accepts_exact_hand_crop_boundary_contract(tmp_path: Path) -> None:
    models_root = tmp_path / "models"
    models_root.mkdir()
    checkpoint = models_root / "hand.pth"
    checkpoint.write_bytes(b"hand")
    config = models_root / "hand.py"
    config.write_text("model = dict(type='fixture')\n", encoding="utf-8")
    entry = governed_file_model(
        key="hand",
        file="models/hand.pth",
        role="champion_hand",
        sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        inference_config="models/hand.py",
        inference_config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
        class_names=list(CHAMPION_HAND_CLASS_NAMES),
    )
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(governed_registry([entry])), encoding="utf-8")
    prediction = np.array([[[1, 3], [13, 0]]], dtype=np.int64)
    slot = load_production_mmseg_slot(
        "champion_hand",
        checkpoint,
        registry_path=registry,
        models_root=models_root,
        initializer=lambda *args, **kwargs: SimpleNamespace(to=lambda _device: None),
        inference=lambda *_args: SimpleNamespace(pred_sem_seg=SimpleNamespace(data=prediction)),
    )
    masks = slot(
        np.zeros((2, 2, 3), dtype=np.uint8),
        ("left_hand_base", "left_thumb", "finger_occlusion_boundary"),
    )
    assert masks["left_hand_base"].tolist() == [[True, False], [False, False]]
    assert masks["left_thumb"].tolist() == [[False, True], [False, False]]
    assert masks["finger_occlusion_boundary"].tolist() == [
        [False, False],
        [True, False],
    ]
    slot.close()

    entry["class_names"] = list(CHAMPION_HAND_CLASS_NAMES[:-1])
    registry.write_text(json.dumps(governed_registry([entry])), encoding="utf-8")
    with pytest.raises(ServingProviderError, match="14-class crop contract"):
        load_production_mmseg_slot(
            "champion_hand",
            checkpoint,
            registry_path=registry,
            models_root=models_root,
            initializer=lambda *args, **kwargs: object(),
            inference=lambda *_args: None,
        )


def test_production_runtime_auto_configures_only_a_complete_champion_set(tmp_path: Path) -> None:
    models_root = tmp_path / "models"
    models_root.mkdir()
    entries = []
    for role in ("champion_bodypart", "champion_hand", "champion_clothing"):
        checkpoint = models_root / f"{role}.pth"
        checkpoint.write_bytes(role.encode())
        entries.append(
            governed_file_model(
                key=role,
                file=f"models/{checkpoint.name}",
                role=role,
                sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            )
        )
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(governed_registry(entries)), encoding="utf-8")
    runtime = create_production_runtime(registry_path=registry, models_root=models_root)
    assert runtime.configured_models == [
        "champion_bodypart",
        "champion_hand",
        "champion_clothing",
    ]
    assert runtime.refiner is not None

    registry.write_text(json.dumps(governed_registry(entries[:1])), encoding="utf-8")
    with pytest.raises(ServingError, match="partial champion serving registry"):
        create_production_runtime(registry_path=registry, models_root=models_root)


def test_production_sam2_refiner_resolves_hashes_validates_clicks_and_releases_embedding(
    tmp_path: Path,
) -> None:
    models_root = tmp_path / "models"
    models_root.mkdir()
    entries = []
    roles = {
        "large": "primary_boundary_refiner",
        "base": "boundary_refiner_oom_fallback",
    }
    for key, role in roles.items():
        checkpoint = models_root / f"{key}.pt"
        checkpoint.write_bytes(key.encode())
        entries.append(
            governed_file_model(
                key=key,
                file=f"models/{checkpoint.name}",
                role=role,
                sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            )
        )
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(governed_registry(entries)), encoding="utf-8")
    events = []

    class Provider:
        def embed(self, image, *, model, precision):
            events.append(("embed", model, precision, image.shape))
            return "embedding"

        def predict(self, embedding, plan, *, multimask_output):
            events.append(
                (
                    "predict",
                    embedding,
                    plan.positive_points,
                    plan.negative_points,
                    multimask_output,
                )
            )
            weak = np.full((8, 10), -1, dtype=np.float32)
            strong = np.full((8, 10), -1, dtype=np.float32)
            strong[2:6, 3:7] = 1
            return [SamCandidate(weak, 0.4), SamCandidate(strong, 0.9)]

        def close(self, embedding):
            events.append(("close", embedding))

    def provider_factory(checkpoints, configs, work_dir):
        assert set(checkpoints) == {"sam2.1_hiera_large", "sam2.1_hiera_base_plus"}
        assert set(configs) == set(checkpoints) and work_dir == tmp_path / "work"
        return Provider()

    refiner = load_production_sam2_refiner(
        registry_path=registry,
        models_root=models_root,
        work_dir=tmp_path / "work",
        provider_factory=provider_factory,
    )
    image = np.zeros((8, 10, 3), dtype=np.uint8)
    mask = refiner(
        image,
        "hair",
        ({"x": 4, "y": 3, "positive": True}, {"x": 0, "y": 0, "positive": False}),
    )
    assert mask.sum() == 16
    second = refiner(image, "hair", ({"x": 5, "y": 4, "positive": True},))
    assert second.sum() == 16
    refiner.close()
    assert events == [
        ("embed", "sam2.1_hiera_large", "fp16", (8, 10, 3)),
        ("predict", "embedding", ((4, 3),), ((0, 0),), True),
        ("predict", "embedding", ((5, 4),), (), True),
        ("close", "embedding"),
    ]
    with pytest.raises(ValueError, match="positive click"):
        refiner(image, "hair", ({"x": 0, "y": 0, "positive": False},))
    with pytest.raises(ValueError, match="outside"):
        refiner(image, "hair", ({"x": 10, "y": 0, "positive": True},))


def test_active_interactive_serving_swaps_by_governed_role_and_accepts_legacy_alias(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root / "configs/pipeline.yaml").read_text(encoding="utf-8"))
    config["provider_roles"]["interactive_segmenter"]["active"] = "fixture_challenger"
    config["provider_catalog"]["fixture_challenger"] = {
        "registry": "model_registry",
        "key": "sam2_1_hiera_large",
        "execution": "local",
        "billing": "none",
    }
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    captured = {}
    mask = np.zeros((8, 10), dtype=bool)
    mask[2:6, 3:7] = True
    identity = ProviderIdentity(
        "fixture_challenger",
        "interactive_segmenter",
        "fixture_family",
        "fixture-commit",
        "fixture-runtime",
    )

    def refine(_embedding, *, prompt):
        captured.update(prompt)
        return (MaskProposal(mask, 0.9, identity, "fixture-prompt"),)

    provider = InteractiveSegmenterAdapter(identity, lambda image: image.shape, refine)
    refiner = load_active_interactive_refiner(
        config_path=config_path,
        external_registry_path=root / "configs/external_sources.yaml",
        model_registry_path=root / "models/model_registry.json",
        provider_loaders={"fixture_challenger": lambda: provider},
    )
    result = refiner(
        np.zeros((8, 10, 3), dtype=np.uint8),
        "hair",
        ({"x": 4, "y": 3, "positive": True},),
    )
    assert np.array_equal(result, mask)
    assert captured == {
        "label": "hair",
        "roi_xyxy": (0, 0, 10, 8),
        "positive_points": ((4, 3),),
        "negative_points": (),
        "multimask_output": True,
    }

    config["provider_roles"]["interactive_segmenter"]["active"] = "sam2.1_hiera_large"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    legacy_identity = ProviderIdentity(
        "sam2.1_hiera_large",
        "interactive_segmenter",
        "sam2",
        "fixture-commit",
        "fixture-runtime",
    )
    legacy = InteractiveSegmenterAdapter(
        legacy_identity,
        lambda image: image.shape,
        lambda _embedding, *, prompt: (MaskProposal(mask, 0.9, legacy_identity, "fixture-prompt"),),
    )
    aliased = load_active_interactive_refiner(
        config_path=config_path,
        external_registry_path=root / "configs/external_sources.yaml",
        model_registry_path=root / "models/model_registry.json",
        provider_loaders={"sam2_1_large": lambda: legacy},
    )
    assert np.array_equal(
        aliased(
            np.zeros((8, 10, 3), dtype=np.uint8),
            "hair",
            ({"x": 4, "y": 3, "positive": True},),
        ),
        mask,
    )


def test_production_sam2_runtime_uses_governed_local_cuda_settings_on_windows(
    tmp_path: Path,
) -> None:
    config = tmp_path / "pipeline.yaml"
    config.write_text(
        "stages:\n"
        "  S07:\n"
        "    enabled: true\n"
        "    local_cuda_python: C:/cuda/python.exe\n"
        "    source_path: models/runtime_cache/sam2/revision\n"
        "    dependency_site: models/runtime_cache/sam2_deps\n",
        encoding="utf-8",
    )
    assert production_sam2_runtime_options(config, windows_host=True) == {
        "local_cuda_python": Path("C:/cuda/python.exe"),
        "source_path": Path("models/runtime_cache/sam2/revision"),
        "dependency_site": Path("models/runtime_cache/sam2_deps"),
    }
    assert production_sam2_runtime_options(config, windows_host=False) == {}


def test_production_runtime_configures_sam2_without_loading_it(monkeypatch) -> None:
    loaded = []
    monkeypatch.setattr(
        "maskfactory.serve.providers.load_production_sam2_refiner",
        lambda: loaded.append("load") or (lambda image, label, clicks: np.zeros(image.shape[:2])),
    )
    runtime = create_production_runtime()
    assert loaded == [] and runtime.refiner is not None
    assert runtime.predictor is None


def test_on_demand_refiner_reuses_session_and_closes_explicitly() -> None:
    events = []

    class Session:
        def __call__(self, image, label, clicks):
            events.append((label, clicks))
            return np.zeros(image.shape[:2], dtype=bool)

        def close(self):
            events.append("close")

    refiner = OnDemandRefiner(lambda: events.append("load") or Session())
    image = np.zeros((8, 10, 3), dtype=np.uint8)
    click = ({"x": 1, "y": 1, "positive": True},)
    refiner(image, "hair", click)
    refiner(image, "hair", click)
    assert refiner.load_count == 1
    assert events.count("load") == 1
    refiner.close()
    assert events[-1] == "close" and refiner.provider is None


def test_runtime_serializes_concurrent_heavy_requests(tmp_path: Path) -> None:
    state = {"active": 0, "maximum": 0}
    state_lock = threading.Lock()

    def predict(image, labels):
        with state_lock:
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
        time.sleep(0.02)
        with state_lock:
            state["active"] -= 1
        return {label: np.zeros(image.shape[:2], dtype=bool) for label in labels}

    runtime = InferenceRuntime(predictor=predict, gpu_lock_path=tmp_path / "gpu.lock")
    runtime.start()
    threads = [threading.Thread(target=runtime.predict, args=(_png(), ("hair",))) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    runtime.stop()
    assert state["maximum"] == 1


def test_runtime_has_no_gpu_resource_governance_and_returns_read_only_draft_contract(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "gpu.lock"

    def predict(image: np.ndarray, labels: tuple[str, ...]):
        return {
            label: np.pad(
                np.ones((4, 5), dtype=bool),
                ((2, image.shape[0] - 6), (3, image.shape[1] - 8)),
            )
            for label in labels
        }

    runtime = InferenceRuntime(
        predictor=predict,
        refiner=lambda image, _label, _clicks: np.ones(image.shape[:2], dtype=bool),
        registry_path=_registry(tmp_path / "registry.json"),
        gpu_lock_path=lock,
        loaded_models=["champion"],
        vram_probe=lambda: {
            "available": True,
            "gpus": [{"index": 0, "total_mib": 8192, "used_mib": 1024, "free_mib": 7168}],
        },
    )
    with pytest.raises(ServingError, match="must be started"):
        runtime.predict(_png(), ("left_forearm",))
    runtime.start()
    health = runtime.health()
    assert health["status"] == "ok"
    assert health["versions"] == {"pipeline": "0.0.1", "mode_b_api": "1.0.0"}
    assert health["vram"]["gpus"][0]["free_mib"] == 7168
    assert not lock.exists()
    model_status = runtime.models()
    assert model_status["models"][0]["role"] == "champion_bodypart"
    assert model_status["champions"]["champion_bodypart"]["key"] == "champion"
    response = runtime.predict(_png(), ("left_forearm", "hair"))
    assert response["status"] == "draft_model_generated"
    assert response["manifest"]["hair"]["status"] == "draft_model_generated"
    provenance = response["manifest"]["hair"]["provenance"]
    assert validate_document(provenance, "serving_provenance") == ()
    assert provenance["provider"] == {
        "key": "champion",
        "role": "champion_bodypart",
        "lifecycle_state": "promoted",
        "license_eligibility": {"status": "verified", "eligible": True},
        "benchmark_certificate": {
            "status": "missing",
            "target_role": None,
            "issued_at": None,
            "sha256": None,
        },
        "rollback": {"status": "missing", "provider_key": None},
    }
    assert provenance["truth_tier"] == "machine_candidate"
    assert provenance["certification"] == {"status": "not_certified", "scope": None}
    assert provenance["routing"]["residual_reason"] == ("model_draft_has_no_autonomy_certificate")
    serialized_provenance = json.dumps(provenance)
    assert "models/champion.pth" not in serialized_provenance
    assert "example.invalid" not in serialized_provenance
    assert "source_url" not in serialized_provenance
    decoded = base64.b64decode(response["masks"]["left_forearm"])
    with Image.open(io.BytesIO(decoded)) as mask:
        assert mask.mode == "L" and mask.size == (24, 16)
    refined = runtime.refine(_png(), "left_forearm", ({"x": 3, "y": 4, "positive": True},))
    assert refined["status"] == "draft_model_generated" and refined["area_px"] == 24 * 16
    runtime.stop()
    assert not lock.exists()
    lock.write_text("legacy marker must be ignored\n", encoding="utf-8")
    runtime.start()
    runtime.stop()
    assert lock.read_text(encoding="utf-8") == "legacy marker must be ignored\n"


def test_vram_probe_parses_nvidia_smi_and_degrades_without_failing_health(monkeypatch) -> None:
    monkeypatch.setattr(
        "maskfactory.serve.api.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="0, NVIDIA RTX 5060 Laptop GPU, 8151, 1024, 7127\n",
            stderr="",
        ),
    )
    assert probe_vram() == {
        "available": True,
        "gpus": [
            {
                "index": 0,
                "name": "NVIDIA RTX 5060 Laptop GPU",
                "total_mib": 8151,
                "used_mib": 1024,
                "free_mib": 7127,
            }
        ],
    }
    monkeypatch.setattr(
        "maskfactory.serve.api.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="no driver"),
    )
    assert probe_vram() == {"available": False, "reason": "no driver", "gpus": []}


def test_comfy_predict_node_multipart_transport_batch_and_api_down_hint(tmp_path: Path) -> None:
    runtime = InferenceRuntime(
        predictor=lambda image, labels: {
            label: np.full(image.shape[:2], index % 2, dtype=bool)
            for index, label in enumerate(labels)
        },
        gpu_lock_path=tmp_path / "gpu.lock",
    )
    runtime.start()
    calls = []

    def transport(url, *, fields, files):
        calls.append((url, fields, files))
        return runtime.predict(files["image"][1], tuple(fields["labels"].split(",")))

    image = torch.full((1, 16, 24, 3), 0.5)
    masks, labels, manifest = MFPredictMasks(transport=transport).predict(
        image, "left_forearm,hair", 8, 4
    )
    assert masks.shape == (2, 16, 24)
    assert labels == "left_forearm,hair"
    comfy_manifest = json.loads(manifest)
    assert comfy_manifest["status"] == "draft_model_generated"
    comfy_provenance = comfy_manifest["manifest"]["hair"]["provenance"]
    assert comfy_provenance["provider"]["lifecycle_state"] == "unregistered"
    assert comfy_provenance["truth_tier"] == "machine_candidate"
    assert calls[0][1]["inpaint"] == '{"dilate": 8, "feather": 4}'
    assert calls[0][2]["image"][2] == "image/png"
    runtime.stop()

    def unavailable(*_args, **_kwargs):
        raise OSError("connection refused")

    with pytest.raises(ComfyPackageError, match="maskfactory serve --port 8765"):
        MFPredictMasks(transport=unavailable).predict(image, "hair")


def test_runtime_rejects_nonbinary_or_wrong_shape_provider_outputs(tmp_path: Path) -> None:
    runtime = InferenceRuntime(
        predictor=lambda _image, labels: {labels[0]: np.full((2, 2), 0.5)},
        gpu_lock_path=tmp_path / "gpu.lock",
    )
    runtime.start()
    with pytest.raises(ServingError, match="dimensions differ"):
        runtime.predict(_png(), ("hair",))
    runtime.stop()


def test_predict_honors_label_map_both_and_inpaint_contract(tmp_path: Path) -> None:
    def predict(image, labels):
        outputs = {}
        for index, label in enumerate(labels):
            mask = np.zeros(image.shape[:2], dtype=bool)
            mask[2:6, 2 + index * 6 : 6 + index * 6] = True
            outputs[label] = mask
        return outputs

    runtime = InferenceRuntime(predictor=predict, gpu_lock_path=tmp_path / "gpu.lock")
    runtime.start()
    response = runtime.predict(
        _png(),
        ("left_forearm", "right_forearm", "clothing_generic"),
        return_mode="both",
        inpaint={"dilate": 2, "feather": 3},
    )
    assert set(response["masks"]) == {"left_forearm", "right_forearm", "clothing_generic"}
    assert set(response["label_maps"]) == {"part", "material"}
    with Image.open(io.BytesIO(base64.b64decode(response["label_maps"]["part"]))) as part:
        assert part.size == (24, 16)
        values = np.asarray(part)
        assert {0, 18, 19}.issuperset(set(np.unique(values)))
    with Image.open(io.BytesIO(base64.b64decode(response["label_maps"]["material"]))) as material:
        assert material.mode == "L" and 3 in np.unique(np.asarray(material))
    ramp = np.asarray(
        Image.open(io.BytesIO(base64.b64decode(response["inpaint_masks"]["left_forearm"])))
    )
    assert set(np.unique(ramp)) - {0, 255}
    assert response["inpaint"] == {"dilate": 2, "feather": 3}
    with pytest.raises(ServingError, match="return_mode"):
        runtime.predict(_png(), ("hair",), return_mode="tensors")
    with pytest.raises(ServingError, match=r"\[0, 512\]"):
        runtime.predict(_png(), ("hair",), inpaint={"dilate": -1, "feather": 0})
    runtime.stop()


def test_all_three_reference_workflows_are_filed_and_use_registered_nodes() -> None:
    root = Path("src/maskfactory/serve/maskfactory_nodes/workflows")
    expected = {
        "wf_inpaint_gold_hand.json",
        "wf_bodypart_conditioned.json",
        "wf_live_predict_inpaint.json",
    }
    assert expected <= {path.name for path in root.glob("*.json")}
    registered = {
        "MFPackageBrowser",
        "MFLoadSource",
        "MFLoadInpaintMask",
        "MFLoadUnionMask",
        "MFMaskFromLabelMap",
        "MFCombineMasks",
        "MFPredictMasks",
        "LoadImage",
        "CheckpointLoaderSimple",
        "CLIPTextEncode",
        "VAEEncodeForInpaint",
        "KSampler",
        "VAEDecode",
        "ImageCompositeMasked",
        "SaveImage",
    }
    for name in expected:
        workflow = json.loads((root / name).read_text(encoding="utf-8"))
        assert workflow and all(node["class_type"] in registered for node in workflow.values())


def test_bodypart_conditioned_workflow_is_complete_skin_only_img2img_graph() -> None:
    path = Path("src/maskfactory/serve/maskfactory_nodes/workflows/wf_bodypart_conditioned.json")
    graph = json.loads(path.read_text(encoding="utf-8"))
    by_type = {}
    for node_id, node in graph.items():
        by_type.setdefault(node["class_type"], []).append((node_id, node))
        for value in node["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                assert value[0] in graph, f"dangling workflow link {node_id} -> {value[0]}"
    browser_id = by_type["MFPackageBrowser"][0][0]
    source = by_type["MFLoadSource"][0][1]
    union = by_type["MFLoadUnionMask"][0][1]
    material = by_type["MFMaskFromLabelMap"][0][1]
    combine_id, combine = by_type["MFCombineMasks"][0]
    assert source["inputs"] == {"image_id": [browser_id, 0], "person_index": [browser_id, 1]}
    assert union["inputs"]["label"] == "visible_body_skin"
    assert union["inputs"]["person_index"] == [browser_id, 1]
    assert material["inputs"]["map_name"] == "material"
    assert material["inputs"]["label_id"] == 3
    assert material["inputs"]["person_index"] == [browser_id, 1]
    assert combine["inputs"]["op"] == "subtract" and combine["inputs"]["binarize"] is True
    encode_id, encode = by_type["VAEEncodeForInpaint"][0]
    assert encode["inputs"]["mask"] == [combine_id, 0]
    assert encode["inputs"]["pixels"] == [by_type["MFLoadSource"][0][0], 0]
    sampler_id, sampler = by_type["KSampler"][0]
    assert sampler["inputs"]["latent_image"] == [encode_id, 0]
    decode_id, decode = by_type["VAEDecode"][0]
    assert decode["inputs"]["samples"] == [sampler_id, 0]
    composite_id, composite = by_type["ImageCompositeMasked"][0]
    assert composite["inputs"]["destination"] == [by_type["MFLoadSource"][0][0], 0]
    assert composite["inputs"]["source"] == [decode_id, 0]
    assert composite["inputs"]["mask"] == [combine_id, 0]
    # VAE decode crops to its latent grid. Resize only the generated candidate back
    # to source geometry before applying the original full-resolution binary mask.
    assert composite["inputs"]["resize_source"] is True
    assert by_type["SaveImage"][0][1]["inputs"]["images"] == [composite_id, 0]


def test_gold_hand_workflow_uses_gold_inpaint_mask_through_composite() -> None:
    path = Path("src/maskfactory/serve/maskfactory_nodes/workflows/wf_inpaint_gold_hand.json")
    graph = json.loads(path.read_text(encoding="utf-8"))
    by_type = {node["class_type"]: (node_id, node) for node_id, node in graph.items()}
    browser_id = by_type["MFPackageBrowser"][0]
    source_id, source = by_type["MFLoadSource"]
    mask_id, mask = by_type["MFLoadInpaintMask"]
    assert source["inputs"] == {"image_id": [browser_id, 0], "person_index": [browser_id, 1]}
    assert mask["inputs"] == {
        "image_id": [browser_id, 0],
        "person_index": [browser_id, 1],
        "label": "left_hand",
        "dilate_px": 8,
        "feather_px": 4,
        "mode": "existing",
    }
    encode_id, encode = by_type["VAEEncodeForInpaint"]
    assert encode["inputs"]["pixels"] == [source_id, 0]
    assert encode["inputs"]["mask"] == [mask_id, 0]
    sampler_id, sampler = by_type["KSampler"]
    assert sampler["inputs"]["latent_image"] == [encode_id, 0]
    decode_id, decode = by_type["VAEDecode"]
    assert decode["inputs"]["samples"] == [sampler_id, 0]
    composite_id, composite = by_type["ImageCompositeMasked"]
    assert composite["inputs"]["destination"] == [source_id, 0]
    assert composite["inputs"]["source"] == [decode_id, 0]
    assert composite["inputs"]["mask"] == [mask_id, 0]
    assert by_type["SaveImage"][1]["inputs"]["images"] == [composite_id, 0]


def test_live_predict_workflow_uses_predicted_mask_through_complete_inpaint_chain() -> None:
    path = Path("src/maskfactory/serve/maskfactory_nodes/workflows/wf_live_predict_inpaint.json")
    graph = json.loads(path.read_text(encoding="utf-8"))
    by_type = {node["class_type"]: (node_id, node) for node_id, node in graph.items()}
    image_id = by_type["LoadImage"][0]
    predict_id, predict = by_type["MFPredictMasks"]
    assert predict["inputs"] == {
        "image": [image_id, 0],
        "labels": "left_forearm",
        "dilate_px": 8,
        "feather_px": 4,
    }
    encode_id, encode = by_type["VAEEncodeForInpaint"]
    assert encode["inputs"]["pixels"] == [image_id, 0]
    assert encode["inputs"]["mask"] == [predict_id, 0]
    sampler_id, sampler = by_type["KSampler"]
    assert sampler["inputs"]["latent_image"] == [encode_id, 0]
    decode_id, decode = by_type["VAEDecode"]
    assert decode["inputs"]["samples"] == [sampler_id, 0]
    composite_id, composite = by_type["ImageCompositeMasked"]
    assert composite["inputs"]["destination"] == [image_id, 0]
    assert composite["inputs"]["source"] == [decode_id, 0]
    assert composite["inputs"]["mask"] == [predict_id, 0]
    assert by_type["SaveImage"][1]["inputs"]["images"] == [composite_id, 0]
