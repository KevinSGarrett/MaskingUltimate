import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.models.ontology_contract import (
    V1_ONTOLOGY_VERSION,
    V1_PART_CLASS_NAMES,
    class_names_sha256,
)
from maskfactory.models.registry import (
    CHAMPION_HAND_CLASS_NAMES,
    ModelFetchError,
    ModelRegistryError,
    champion_status,
    fetch_models,
    load_registered_model,
    promote_model_role,
    register_ollama_models,
    register_smoke_runner,
    resolve_registered_managed_model,
    resolve_registered_model,
    resolve_registered_role,
    rollback_model_role,
    verify_registered_model_smokes,
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fixture(tmp_path: Path, *, expected_hash: str | None = None) -> tuple[Path, Path, Path]:
    source = tmp_path / "source" / "fixture.ckpt"
    source.parent.mkdir()
    source.write_bytes(b"fixture-checkpoint-v1")
    image = tmp_path / "smoke.png"
    Image.new("RGB", (3, 2), (17, 31, 47)).save(image)
    entry = {
        "url": source.as_uri(),
        "family": "fixture_family",
        "filename": "fixture.ckpt",
        "version_tag": "fixture-v1",
        "license": "test-only",
        "role": "test_fixture",
        "runtime": "pytest",
        "vram_note": "none",
        "smoke_test": "fixture_image_inference",
        "smoke_image": image.name,
    }
    if expected_hash is not None:
        entry["sha256"] = expected_hash
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(
        yaml.safe_dump({"schema_version": "1.0.0", "models": {"fixture": entry}}),
        encoding="utf-8",
    )
    return source, image, catalog


def _smoke(checkpoint: Path, image: Path) -> dict[str, object]:
    with Image.open(image) as sample:
        sample.load()
        inference_bytes = checkpoint.read_bytes() + bytes(sample.size) + sample.tobytes()
    return {"passed": True, "output_sha256": _digest(inference_bytes)}


def test_fetch_downloads_hashes_smokes_registers_and_is_idempotent(tmp_path: Path):
    source, image, catalog = _fixture(tmp_path)
    models_root = tmp_path / "models"
    registry = models_root / "model_registry.json"
    fixed_time = datetime(2026, 7, 10, 23, 45, tzinfo=UTC)

    first = fetch_models(
        ["fixture"],
        catalog_path=catalog,
        registry_path=registry,
        models_root=models_root,
        smoke_runners={"fixture_image_inference": _smoke},
        now=lambda: fixed_time,
    )[0]

    target = models_root / "fixture_family" / "fixture.ckpt"
    document = json.loads(registry.read_text(encoding="utf-8"))
    recorded = document["models"][0]
    assert target.read_bytes() == source.read_bytes()
    assert first["fetch_status"] == "downloaded"
    assert recorded["sha256"] == _digest(source.read_bytes())
    assert recorded["source_url"] == source.as_uri()
    assert recorded["version_tag"] == "fixture-v1"
    assert recorded["license"] == "test-only"
    assert recorded["downloaded_at"] == "2026-07-10T23:45:00Z"
    assert recorded["smoke_test"]["image"] == image.name
    assert recorded["smoke_test"]["output_sha256"]
    assert recorded["verified"] is True

    second = fetch_models(
        ["fixture"],
        catalog_path=catalog,
        registry_path=registry,
        models_root=models_root,
    )[0]
    assert second["fetch_status"] == "cached"
    assert json.loads(registry.read_text(encoding="utf-8")) == document

    verified = verify_registered_model_smokes(
        catalog_path=catalog,
        registry_path=registry,
        models_root=models_root,
        smoke_runners={"fixture_image_inference": _smoke},
    )
    assert verified == [
        {
            "key": "fixture",
            "sha256": _digest(source.read_bytes()),
            "output_sha256": recorded["smoke_test"]["output_sha256"],
        }
    ]


def test_failed_smoke_never_publishes_checkpoint_or_verified_entry(tmp_path: Path):
    _, _, catalog = _fixture(tmp_path)
    models_root = tmp_path / "models"
    registry = models_root / "model_registry.json"

    def failed_smoke(checkpoint: Path, image: Path) -> dict[str, object]:
        return {"passed": False, "output_sha256": ""}

    try:
        fetch_models(
            ["fixture"],
            catalog_path=catalog,
            registry_path=registry,
            models_root=models_root,
            smoke_runners={"fixture_image_inference": failed_smoke},
        )
    except ModelFetchError as exc:
        assert "smoke test failed" in str(exc)
    else:
        raise AssertionError("failed smoke test was accepted")

    assert not (models_root / "fixture_family" / "fixture.ckpt").exists()
    assert not registry.exists()


def test_hash_mismatch_never_publishes_checkpoint(tmp_path: Path):
    _, _, catalog = _fixture(tmp_path, expected_hash="0" * 64)
    models_root = tmp_path / "models"

    try:
        fetch_models(
            ["fixture"],
            catalog_path=catalog,
            registry_path=models_root / "model_registry.json",
            models_root=models_root,
            smoke_runners={"fixture_image_inference": _smoke},
        )
    except ModelFetchError as exc:
        assert "SHA-256 mismatch" in str(exc)
    else:
        raise AssertionError("bad checkpoint hash was accepted")

    assert not (models_root / "fixture_family" / "fixture.ckpt").exists()


def test_loader_refuses_unregistered_unverified_missing_and_tampered_paths(
    tmp_path: Path,
):
    source, _, catalog = _fixture(tmp_path)
    models_root = tmp_path / "models"
    registry = models_root / "model_registry.json"

    for candidate in ("unknown", source):
        try:
            resolve_registered_model(candidate, registry_path=registry, models_root=models_root)
        except ModelRegistryError as exc:
            assert "not registered" in str(exc)
        else:
            raise AssertionError("unregistered checkpoint was accepted")

    fetch_models(
        ["fixture"],
        catalog_path=catalog,
        registry_path=registry,
        models_root=models_root,
        smoke_runners={"fixture_image_inference": _smoke},
    )
    target = models_root / "fixture_family" / "fixture.ckpt"
    assert (
        resolve_registered_model("fixture", registry_path=registry, models_root=models_root)
        == target
    )
    assert (
        resolve_registered_model(str(target), registry_path=registry, models_root=models_root)
        == target
    )
    assert (
        load_registered_model(
            target,
            lambda path: path.read_bytes(),
            registry_path=registry,
            models_root=models_root,
        )
        == source.read_bytes()
    )

    target.write_bytes(b"tampered")
    try:
        resolve_registered_model("fixture", registry_path=registry, models_root=models_root)
    except ModelRegistryError as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("tampered checkpoint was accepted")

    document = json.loads(registry.read_text(encoding="utf-8"))
    document["models"][0]["verified"] = False
    target.write_bytes(source.read_bytes())
    registry.write_text(json.dumps(document), encoding="utf-8")
    try:
        resolve_registered_model("fixture", registry_path=registry, models_root=models_root)
    except ModelRegistryError as exc:
        assert "not verified" in str(exc)
    else:
        raise AssertionError("unverified checkpoint was accepted")


def test_models_fetch_cli_downloads_and_reports_verified(tmp_path: Path):
    _, _, catalog = _fixture(tmp_path)
    models_root = tmp_path / "models"
    registry = models_root / "registry.json"
    register_smoke_runner("fixture_image_inference", _smoke)

    result = CliRunner().invoke(
        main,
        [
            "models",
            "fetch",
            "fixture",
            "--catalog",
            str(catalog),
            "--registry",
            str(registry),
            "--models-root",
            str(models_root),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "fixture: downloaded" in result.output
    assert "verified=true" in result.output

    all_models_root = tmp_path / "all-models"
    all_result = CliRunner().invoke(
        main,
        [
            "models",
            "fetch",
            "--all",
            "--catalog",
            str(catalog),
            "--registry",
            str(all_models_root / "registry.json"),
            "--models-root",
            str(all_models_root),
        ],
    )
    assert all_result.exit_code == 0, all_result.output
    assert "fixture: downloaded" in all_result.output


def test_models_fetch_cli_requires_exactly_key_or_all(tmp_path: Path):
    _, _, catalog = _fixture(tmp_path)
    runner = CliRunner()

    neither = runner.invoke(main, ["models", "fetch", "--catalog", str(catalog)])
    both = runner.invoke(main, ["models", "fetch", "fixture", "--all"])

    assert neither.exit_code == 2
    assert both.exit_code == 2
    assert "provide exactly one model KEY or --all" in neither.output
    assert "provide exactly one model KEY or --all" in both.output


def test_champion_role_promotion_and_single_edit_rollback(tmp_path: Path) -> None:
    _, _, catalog = _fixture(tmp_path)
    models_root = tmp_path / "models"
    registry = models_root / "registry.json"
    register_smoke_runner("fixture_image_inference", _smoke)
    fetch_models(
        ["fixture"],
        catalog_path=catalog,
        registry_path=registry,
        models_root=models_root,
    )
    document = json.loads(registry.read_text())
    incumbent = document["models"][0]
    incumbent["role"] = "champion_bodypart"
    challenger = {**incumbent, "key": "challenger", "role": "challenger_bodypart"}
    config = models_root / "challenger_inference.py"
    config.write_text("model = dict(type='fixture')\n", encoding="utf-8")
    challenger.update(
        {
            "inference_config": "models/challenger_inference.py",
            "inference_config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
            "ontology_version": V1_ONTOLOGY_VERSION,
            "class_names": list(V1_PART_CLASS_NAMES),
            "class_names_sha256": class_names_sha256(list(V1_PART_CLASS_NAMES)),
            "artifact_hashes": {
                "checkpoint_sha256": challenger["sha256"],
                "inference_config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
            },
        }
    )
    document["models"].append(challenger)
    registry.write_text(json.dumps(document), encoding="utf-8")
    history = tmp_path / "champion_history.jsonl"
    record = promote_model_role(
        "challenger",
        "champion_bodypart",
        registry_path=registry,
        models_root=models_root,
        history_path=history,
    )
    promoted = json.loads(registry.read_text())
    roles = {item["key"]: item["role"] for item in promoted["models"]}
    assert roles == {"fixture": "challenger_bodypart", "challenger": "champion_bodypart"}
    assert resolve_registered_role(
        "champion_bodypart", registry_path=registry, models_root=models_root
    ).is_file()
    assert json.loads(history.read_text())["incumbent_key"] == "fixture"
    visible = champion_status(registry_path=registry, history_path=history)
    assert visible["champions"]["champion_bodypart"]["key"] == "challenger"
    assert len(visible["history"]) == 1
    cli = CliRunner().invoke(
        main,
        ["models", "champions", "--registry", str(registry), "--history", str(history)],
    )
    assert cli.exit_code == 0, cli.output
    assert json.loads(cli.output)["champions"]["champion_bodypart"]["key"] == "challenger"
    rollback_model_role(record, registry_path=registry)
    rolled_back = json.loads(registry.read_text())
    assert {item["key"]: item["role"] for item in rolled_back["models"]} == {
        "fixture": "champion_bodypart",
        "challenger": "challenger_bodypart",
    }


def test_serving_champion_promotion_refuses_unusable_artifacts(tmp_path: Path) -> None:
    models_root = tmp_path / "models"
    models_root.mkdir()
    checkpoint = models_root / "candidate.pth"
    checkpoint.write_bytes(b"candidate")
    config = models_root / "candidate.py"
    config.write_text("model = dict(type='fixture')\n", encoding="utf-8")
    entry = {
        "key": "candidate",
        "file": "models/candidate.pth",
        "role": "challenger_bodypart",
        "version_tag": "fixture-v1",
        "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "verified": True,
        "inference_config": "models/candidate.py",
        "inference_config_sha256": "0" * 64,
        "class_names": ["background", "hair"],
        "ontology_version": V1_ONTOLOGY_VERSION,
    }
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"models": [entry]}), encoding="utf-8")
    with pytest.raises(ModelRegistryError, match="inference_config hash mismatch"):
        promote_model_role(
            "candidate",
            "champion_bodypart",
            registry_path=registry,
            models_root=models_root,
        )
    assert json.loads(registry.read_text())["models"][0]["role"] == "challenger_bodypart"

    entry["inference_config_sha256"] = hashlib.sha256(config.read_bytes()).hexdigest()
    entry["class_names"] = ["background", "clothing_generic"]
    registry.write_text(json.dumps({"models": [entry]}), encoding="utf-8")
    with pytest.raises(ModelRegistryError, match="vocabulary must be exact"):
        promote_model_role(
            "candidate",
            "champion_bodypart",
            registry_path=registry,
            models_root=models_root,
        )


def test_champion_hand_promotion_accepts_only_exact_14_class_crop_contract(
    tmp_path: Path,
) -> None:
    models_root = tmp_path / "models"
    models_root.mkdir()
    checkpoint = models_root / "hand.pth"
    checkpoint.write_bytes(b"hand")
    config = models_root / "hand.py"
    config.write_text("model = dict(type='fixture')\n", encoding="utf-8")
    entry = {
        "key": "hand",
        "file": "models/hand.pth",
        "role": "challenger_hand",
        "version_tag": "fixture-v1",
        "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "verified": True,
        "inference_config": "models/hand.py",
        "inference_config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "class_names": list(CHAMPION_HAND_CLASS_NAMES),
    }
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"models": [entry]}), encoding="utf-8")
    promote_model_role("hand", "champion_hand", registry_path=registry, models_root=models_root)
    assert json.loads(registry.read_text())["models"][0]["role"] == "champion_hand"

    entry["class_names"] = list(CHAMPION_HAND_CLASS_NAMES[:-1])
    entry["role"] = "challenger_hand"
    registry.write_text(json.dumps({"models": [entry]}), encoding="utf-8")
    with pytest.raises(ModelRegistryError, match="14-class crop contract"):
        promote_model_role("hand", "champion_hand", registry_path=registry, models_root=models_root)
    assert json.loads(registry.read_text())["models"][0]["role"] == "challenger_hand"


def test_register_ollama_models_cross_checks_full_and_list_digests(tmp_path: Path):
    names = ["qwen2.5vl:7b", "llava:13b", "qwen2.5:7b-instruct"]
    digests = ["a" * 64, "b" * 64, "c" * 64]
    inventory = {
        "models": [
            {
                "name": name,
                "digest": digest,
                "size": index + 100,
                "details": {
                    "format": "gguf",
                    "family": "fixture",
                    "parameter_size": "7B",
                    "quantization_level": "Q4_K_M",
                },
            }
            for index, (name, digest) in enumerate(zip(names, digests, strict=True))
        ]
    }
    list_output = "NAME ID SIZE MODIFIED\n" + "\n".join(
        f"{name} {digest[:12]} 1 GB now" for name, digest in zip(names, digests, strict=True)
    )
    registry = tmp_path / "registry.json"

    entries = register_ollama_models(
        registry_path=registry,
        inventory=inventory,
        list_output=list_output,
        now=lambda: datetime(2026, 7, 10, 23, 0, tzinfo=UTC),
    )

    assert len(entries) == 3
    assert all(entry["register_status"] == "registered" for entry in entries)
    assert all(entry["managed"] is True for entry in entries)
    assert all(entry["verified"] is True for entry in entries)
    primary = resolve_registered_managed_model("ollama_qwen2_5vl_7b", registry_path=registry)
    assert primary["digest"] == "a" * 64
    assert primary["ollama_list_id"] == "a" * 12
    cached = register_ollama_models(
        registry_path=registry,
        inventory=inventory,
        list_output=list_output,
        now=lambda: datetime(2026, 7, 11, 1, 0, tzinfo=UTC),
    )
    assert all(entry["register_status"] == "cached" for entry in cached)
    assert all(entry["registered_at"] == "2026-07-10T23:00:00Z" for entry in cached)
    try:
        resolve_registered_model("ollama_qwen2_5vl_7b", registry_path=registry)
    except ModelRegistryError as exc:
        assert "managed model has no checkpoint path" in str(exc)
    else:
        raise AssertionError("managed Ollama model was exposed as a checkpoint path")


def test_register_ollama_models_rejects_digest_mismatch(tmp_path: Path):
    inventory = {
        "models": [
            {"name": name, "digest": character * 64, "details": {}}
            for name, character in zip(
                ("qwen2.5vl:7b", "llava:13b", "qwen2.5:7b-instruct"),
                "abc",
                strict=True,
            )
        ]
    }
    bad_list = (
        "NAME ID SIZE MODIFIED\n"
        "qwen2.5vl:7b deadbeefdead 1 GB now\n"
        f"llava:13b {'b' * 12} 1 GB now\n"
        f"qwen2.5:7b-instruct {'c' * 12} 1 GB now\n"
    )
    try:
        register_ollama_models(
            registry_path=tmp_path / "registry.json",
            inventory=inventory,
            list_output=bad_list,
        )
    except ModelRegistryError as exc:
        assert "digest mismatch" in str(exc)
    else:
        raise AssertionError("mismatched Ollama digest was registered")
