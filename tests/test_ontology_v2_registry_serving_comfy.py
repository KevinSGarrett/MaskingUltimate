import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.io.png_strict import write_binary_mask
from maskfactory.models.ontology_contract import (
    V2_ONTOLOGY_VERSION,
    V2_PART_CLASS_NAMES,
    class_names_sha256,
    validate_bodypart_model_contract,
)
from maskfactory.serve.api import InferenceRuntime, ServingError
from maskfactory.serve.comfy_export import (
    MFLoadGoldMask,
    MFLoadUnionMask,
    MFPackageBrowser,
    MFV2CanonicalSelector,
    list_package_pairs,
)
from registry_helpers import governed_file_model, governed_registry


def _png() -> bytes:
    output = io.BytesIO()
    Image.fromarray(np.full((8, 10, 3), 90, dtype=np.uint8)).save(output, format="PNG")
    return output.getvalue()


def _v2_registry(tmp_path: Path, class_names: list[str] | None = None) -> tuple[Path, Path]:
    models_root = tmp_path / "models"
    models_root.mkdir()
    checkpoint = models_root / "bodypart_v2.pth"
    checkpoint.write_bytes(b"bodypart-v2-fixture")
    config = models_root / "bodypart_v2.py"
    config.write_text("model = dict(type='fixture')\n", encoding="utf-8")
    checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
    names = class_names or list(V2_PART_CLASS_NAMES)
    entry = governed_file_model(
        key="bodypart_v2",
        file="models/bodypart_v2.pth",
        role="champion_bodypart",
        version_tag="fixture-v2",
        sha256=checkpoint_sha,
        inference_config="models/bodypart_v2.py",
        inference_config_sha256=config_sha,
        ontology_version=V2_ONTOLOGY_VERSION,
        class_names=names,
        class_names_sha256=class_names_sha256(names),
        artifact_hashes={
            "checkpoint_sha256": checkpoint_sha,
            "inference_config_sha256": config_sha,
        },
    )
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(governed_registry([entry])), encoding="utf-8")
    return registry, models_root


def test_exact_v2_registry_contract_and_serving_alias_provenance(tmp_path: Path) -> None:
    registry, models_root = _v2_registry(tmp_path)
    entry = json.loads(registry.read_text(encoding="utf-8"))["models"][0]
    contract = validate_bodypart_model_contract(entry, require_explicit=True)
    assert contract["ontology_version"] == V2_ONTOLOGY_VERSION
    assert contract["num_classes"] == 65

    calls: list[tuple[str, ...]] = []

    def loader(_checkpoints):
        def predictor(image, labels):
            calls.append(labels)
            return {label: np.ones(image.shape[:2], dtype=bool) for label in labels}

        return predictor

    runtime = InferenceRuntime(
        registry_path=registry,
        models_root=models_root,
        gpu_lock_path=tmp_path / "gpu.lock",
        vram_probe=lambda: {"source": "fixture"},
    )
    runtime.configure_champion_predictor(loader)
    runtime.start()
    try:
        response = runtime.predict(_png(), ("penis head",))
        assert calls == [("glans_penis",)]
        assert response["ontology_version"] == V2_ONTOLOGY_VERSION
        assert response["requested_labels"] == ["penis head"]
        assert response["labels"] == ["glans_penis"]
        assert response["selector_provenance"] == [
            {
                "requested": "penis head",
                "canonical": "glans_penis",
                "was_alias": True,
                "warning": None,
                "ontology_version": V2_ONTOLOGY_VERSION,
                "class_id": 62,
                "map": "part",
            }
        ]
        assert runtime.health()["ontology_version"] == V2_ONTOLOGY_VERSION
        models = runtime.models()
        assert models["ontology_version"] == V2_ONTOLOGY_VERSION
        assert (
            models["champions"]["champion_bodypart"]["class_names_sha256"]
            == entry["class_names_sha256"]
        )
        with pytest.raises(ServingError, match="derived union"):
            runtime.predict(_png(), ("penis",))
    finally:
        runtime.stop()


def test_v2_serving_rejects_non_exact_vocabulary(tmp_path: Path) -> None:
    names = list(V2_PART_CLASS_NAMES)
    names[-2:] = reversed(names[-2:])
    registry, models_root = _v2_registry(tmp_path, names)
    runtime = InferenceRuntime(registry_path=registry, models_root=models_root)
    with pytest.raises(ServingError, match="vocabulary must be exact 65 names in ID order"):
        runtime.configure_champion_predictor(lambda _checkpoints: object())


def test_v1_champion_rejects_v2_only_labels(tmp_path: Path) -> None:
    models_root = tmp_path / "models"
    models_root.mkdir()
    checkpoint = models_root / "bodypart_v1.pth"
    checkpoint.write_bytes(b"legacy-v1-fixture")
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            governed_registry(
                [
                    governed_file_model(
                        key="bodypart_v1",
                        file="models/bodypart_v1.pth",
                        role="champion_bodypart",
                        version_tag="fixture-v1",
                        sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                    )
                ]
            )
        ),
        encoding="utf-8",
    )
    runtime = InferenceRuntime(
        registry_path=registry,
        models_root=models_root,
        gpu_lock_path=tmp_path / "gpu.lock",
    )
    runtime.configure_champion_predictor(
        lambda _checkpoints: lambda image, labels: {
            label: np.zeros(image.shape[:2], dtype=bool) for label in labels
        }
    )
    runtime.start()
    try:
        with pytest.raises(ServingError, match="unknown ontology label"):
            runtime.predict(_png(), ("left_areola",))
    finally:
        runtime.stop()


def test_comfy_v2_package_aliases_manifest_paths_and_workflows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packages = tmp_path / "packages"
    image_id = "img_v2fixture"
    package = packages / image_id / "instances" / "p0"
    package.mkdir(parents=True)
    Image.fromarray(np.full((8, 10, 3), 80, dtype=np.uint8)).save(package / "source.png")
    mask = np.zeros((8, 10), dtype=np.uint8)
    mask[2:6, 3:7] = 255
    mask_path = package / "annotations" / "cvat_v2" / "glans_penis.png"
    write_binary_mask(mask_path, mask, source_size=(10, 8))
    write_binary_mask(package / "masks_derived" / "penis_visible.png", mask, source_size=(10, 8))
    manifest = {
        "schema_version": "2.0.0",
        "format_version": "2.0.0",
        "mask_ontology_version": V2_ONTOLOGY_VERSION,
        "image_id": image_id,
        "person_index": 0,
        "parts": {
            "glans_penis": {
                "status": "human_approved_gold",
                "mask_file": "annotations/cvat_v2/glans_penis.png",
            }
        },
    }
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("MASKFACTORY_PACKAGES_ROOT", str(packages))

    assert list_package_pairs(ontology_version=V2_ONTOLOGY_VERSION) == ((image_id, 0),)
    assert MFPackageBrowser().browse(
        "human_approved_gold", "v2fixture", 0, V2_ONTOLOGY_VERSION
    ) == (image_id, 0, 1)
    canonical, provenance_json = MFV2CanonicalSelector().select("penis head")
    assert canonical == "glans_penis"
    assert json.loads(provenance_json)["was_alias"] is True
    assert np.asarray(MFLoadGoldMask().load(image_id, 0, "penis head")[0]).sum() == 16
    assert np.asarray(MFLoadUnionMask().load_union(image_id, 0, "penis")[0]).sum() == 16

    workflows = Path("src/maskfactory/serve/maskfactory_nodes/workflows")
    anatomy = json.loads((workflows / "wf_v2_anatomy_selector.json").read_text())
    clothed = json.loads((workflows / "wf_v2_clothed_negative_guard.json").read_text())
    assert any(node["class_type"] == "MFV2CanonicalSelector" for node in anatomy.values())
    assert any(node["class_type"] == "MFCombineMasks" for node in clothed.values())
    assert clothed["1"]["inputs"]["ontology_version"] == V2_ONTOLOGY_VERSION
