import ast
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
import torch
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.io.png_strict import write_binary_mask, write_label_map
from maskfactory.serve.comfy_export import (
    NODE_CLASS_MAPPINGS,
    ComfyPackageError,
    MFLoadGoldMask,
    MFLoadInpaintMask,
    MFLoadProjectedRegion,
    MFLoadSource,
    MFLoadUnionMask,
    MFMaskFromLabelMap,
    MFPackageBrowser,
    assert_workflow_output_target,
    list_package_pairs,
)
from maskfactory.serve.comfy_install import install_node_pack


def _packages(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "packages"
    image_id = "img_a3f9c2e17b04"
    for index in range(2):
        package = root / image_id / "instances" / f"p{index}"
        package.mkdir(parents=True)
        Image.fromarray(np.full((20, 30, 3), 40 + index * 100, dtype=np.uint8)).save(
            package / "source.png"
        )
        mask = np.zeros((20, 30), dtype=np.uint8)
        mask[2 + index * 8 : 8 + index * 8, 3:12] = 255
        write_binary_mask(package / "masks/left_forearm.png", mask, source_size=(30, 20))
        write_binary_mask(package / "masks_derived/both_hands.png", mask, source_size=(30, 20))
        write_binary_mask(
            package / "projected/left_breast_projected_region.png",
            mask,
            source_size=(30, 20),
        )
        write_binary_mask(
            package / "inpaint/inpaint_left_forearm_d8f4.png",
            mask,
            source_size=(30, 20),
        )
        labels = np.zeros((20, 30), dtype=np.uint16)
        labels[mask > 0] = 18
        write_label_map(package / "label_map_part.png", labels, bits=16)
        manifest = {
            "schema_version": "1.0.0",
            "image_id": image_id,
            "parts": {
                "left_forearm": {
                    "status": "human_approved_gold",
                    "visibility": "visible",
                }
            },
        }
        (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root, image_id


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_every_image_backed_node_defaults_person_index_to_zero() -> None:
    for node in (
        MFLoadSource,
        MFLoadGoldMask,
        MFLoadUnionMask,
        MFLoadProjectedRegion,
        MFLoadInpaintMask,
        MFMaskFromLabelMap,
    ):
        person = node.INPUT_TYPES()["required"]["person_index"]
        assert person[0] == "INT" and person[1]["default"] == 0
    assert set(NODE_CLASS_MAPPINGS) >= {
        "MFPackageBrowser",
        "MFLoadSource",
        "MFLoadGoldMask",
        "MFLoadUnionMask",
        "MFLoadProjectedRegion",
        "MFLoadInpaintMask",
        "MFMaskFromLabelMap",
    }


def test_browser_lists_pairs_default_p0_is_identical_and_p1_loads_independently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, image_id = _packages(tmp_path)
    monkeypatch.setenv("MASKFACTORY_PACKAGES_ROOT", str(root))
    before = _tree_hash(root)
    assert list_package_pairs() == ((image_id, 0), (image_id, 1))
    assert MFPackageBrowser().browse("human_approved_gold", "", 1) == (image_id, 1, 2)

    loader = MFLoadGoldMask()
    implicit = loader.load(image_id, label="left_forearm")[0]
    explicit = loader.load(image_id, person_index=0, label="left_forearm")[0]
    second = loader.load(image_id, person_index=1, label="left_forearm")[0]
    assert torch.equal(implicit, explicit)
    assert not torch.equal(explicit, second)
    assert torch.equal(MFMaskFromLabelMap().load(image_id, 1, "part", 18)[0], second)
    assert MFLoadSource().load(image_id)[0].shape == (1, 20, 30, 3)
    assert _tree_hash(root) == before


def test_serialized_legacy_p0_and_multi_instance_p1_workflows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, image_id = _packages(tmp_path)
    monkeypatch.setenv("MASKFACTORY_PACKAGES_ROOT", str(root))
    workflows = Path("src/maskfactory/serve/maskfactory_nodes/workflows")
    legacy = json.loads((workflows / "wf_person_index_default_p0.json").read_text())
    multi = json.loads((workflows / "wf_multi_instance_p1.json").read_text())
    old_inputs = {**legacy["1"]["inputs"], "image_id": image_id}
    p1_inputs = {**multi["1"]["inputs"], "image_id": image_id}
    old_output = NODE_CLASS_MAPPINGS[legacy["1"]["class_type"]]().load(**old_inputs)[0]
    explicit_p0 = MFLoadGoldMask().load(
        image_id, person_index=0, label="left_forearm", on_missing="error"
    )[0]
    p1_output = NODE_CLASS_MAPPINGS[multi["1"]["class_type"]]().load(**p1_inputs)[0]
    assert torch.equal(old_output, explicit_p0)
    assert not torch.equal(old_output, p1_output)


def test_nodes_refuse_dimension_mismatch_and_newer_package_format(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, image_id = _packages(tmp_path)
    monkeypatch.setenv("MASKFACTORY_PACKAGES_ROOT", str(root))
    package = root / image_id / "instances/p0"
    write_binary_mask(
        package / "masks/left_forearm.png",
        np.zeros((10, 10), dtype=np.uint8),
        source_size=(10, 10),
    )
    with pytest.raises(ComfyPackageError, match="resizing is forbidden"):
        MFLoadGoldMask().load(image_id, 0, "left_forearm")
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["format_version"] = "3.0.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ComfyPackageError, match="newer than node-pack"):
        MFLoadSource().load(image_id, 0)


def test_missing_status_projected_and_derived_inpaint_semantics_are_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, image_id = _packages(tmp_path)
    monkeypatch.setenv("MASKFACTORY_PACKAGES_ROOT", str(root))
    before = _tree_hash(root)
    with pytest.raises(ComfyPackageError, match="missing"):
        MFLoadGoldMask().load(image_id, 0, "right_forearm", "error")
    with pytest.warns(UserWarning, match="returning empty"):
        empty = MFLoadGoldMask().load(image_id, 0, "right_forearm", "empty")[0]
    assert empty.shape == (20, 30) and not torch.any(empty)
    assert "NON-TRUTH" in MFLoadProjectedRegion.CATEGORY
    projected = MFLoadProjectedRegion().load_projected(
        image_id, 0, "left_breast_projected_region", "error"
    )[0]
    assert set(torch.unique(projected).tolist()) == {0.0, 1.0}
    ramp = MFLoadInpaintMask().load(
        image_id, 0, "left_forearm", dilate_px=0, feather_px=40, mode="derive"
    )[0]
    assert 0.0 < float(ramp.max()) <= 1.0 and len(torch.unique(ramp)) > 2
    p1_manifest = root / image_id / "instances/p1/manifest.json"
    rejected = json.loads(p1_manifest.read_text())
    rejected["parts"]["left_forearm"]["status"] = "rejected_needs_fix"
    p1_manifest.write_text(json.dumps(rejected), encoding="utf-8")
    assert list_package_pairs() == ((image_id, 0),)
    # The deliberate manifest edit above is the only mutation; node calls do not write package data.
    rejected["parts"]["left_forearm"]["status"] = "human_approved_gold"
    p1_manifest.write_text(json.dumps(rejected), encoding="utf-8")
    assert _tree_hash(root) == before


def test_installer_copies_standalone_pack_workflows_and_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_root, _image_id = _packages(tmp_path)
    comfy_root = tmp_path / "ComfyUI"
    comfy_root.mkdir()
    target = install_node_pack(comfy_root, packages_root=package_root)
    assert target == comfy_root / "custom_nodes/maskfactory_nodes"
    config = json.loads((target / "config.json").read_text())
    assert config == {
        "api_url": "http://127.0.0.1:8765",
        "format_version": "1.x-2.x",
        "packages_root": str(package_root.resolve()),
        "supported_ontology_versions": ["body_parts_v1", "body_parts_v2"],
    }
    assert (target / "__init__.py").is_file()
    assert {path.name for path in (target / "workflows").glob("*.json")} >= {
        "wf_person_index_default_p0.json",
        "wf_multi_instance_p1.json",
        "wf_v2_anatomy_selector.json",
        "wf_v2_clothed_negative_guard.json",
    }
    monkeypatch.delenv("MASKFACTORY_PACKAGES_ROOT", raising=False)
    spec = importlib.util.spec_from_file_location(
        "installed_maskfactory_nodes", target / "__init__.py"
    )
    assert spec is not None and spec.loader is not None
    installed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installed)
    assert installed.packages_root() == package_root.resolve()

    cli_root = tmp_path / "ComfyUI_cli"
    cli_root.mkdir()
    result = CliRunner().invoke(
        main,
        ["comfy", "install", "--comfy-root", str(cli_root), "--packages-root", str(package_root)],
    )
    assert result.exit_code == 0, result.output
    assert (cli_root / "custom_nodes/maskfactory_nodes/config.json").is_file()


def test_node_runtime_has_no_package_write_or_heavy_dependency_path() -> None:
    source_path = Path("src/maskfactory/serve/comfy_export.py")
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    assert not imports & {"cv2", "mmseg", "scipy", "transformers"}
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not calls & {
        "write_text",
        "write_bytes",
        "unlink",
        "replace",
        "rename",
        "mkdir",
        "touch",
        "rmdir",
    }


def test_deliberate_package_mutation_target_is_rejected(tmp_path: Path) -> None:
    root, image_id = _packages(tmp_path)
    with pytest.raises(ComfyPackageError, match="may not mutate"):
        assert_workflow_output_target(root / image_id / "instances/p0/masks/left_forearm.png", root)
    ordinary_output = tmp_path / "ComfyUI/output/result.png"
    assert assert_workflow_output_target(ordinary_output, root) == ordinary_output.resolve()
