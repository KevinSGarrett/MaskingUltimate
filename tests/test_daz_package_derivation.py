from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from maskfactory.cli import main  # noqa: E402
from maskfactory.daz.mapping import build_v1_ontology_snapshot  # noqa: E402
from maskfactory.daz.render import (  # noqa: E402
    PackageDerivationError,
    build_instance_pass_contract,
    build_material_protected_contract,
    build_package_derivation_contract,
    build_part_pass_contract,
    derive_scene_packages,
    load_instance_pass_policy,
    load_material_protected_policy,
    load_package_derivation_policy,
    load_part_pass_policy,
    validate_package_derivation_policy,
)
from test_daz_instance_pass import _owners  # noqa: E402
from test_daz_part_pass import _mapping  # noqa: E402
from test_daz_render_pass_profiles import _plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "daz" / "package_derivation.yaml"
INSTANCE_POLICY = ROOT / "configs" / "daz" / "instance_pass.yaml"
PART_POLICY = ROOT / "configs" / "daz" / "part_pass.yaml"
MATERIAL_POLICY = ROOT / "configs" / "daz" / "material_protected_pass.yaml"
ONTOLOGY = ROOT / "configs" / "ontology.yaml"


def _sha(document: dict) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _compact(state: dict, plan: dict) -> dict:
    result = deepcopy(plan)
    for output in result["outputs"]:
        output["resolution"] = [64, 48]
        output["crop"] = [0, 0, 64, 48]
    content = {
        key: value
        for key, value in result.items()
        if key not in {"schema_version", "plan_id", "plan_sha256"}
    }
    digest = _sha(content)
    result["plan_id"] = f"dcrp_{digest[:24]}"
    result["plan_sha256"] = digest
    assert result["resolved_state_id"] == state["resolved_state_id"]
    return result


def _contracts(owner_count: int = 2, profile: str = "training_relationship"):
    state, _pass_policy, raw_plan = _plan(profile)
    plan = _compact(state, raw_plan)
    instance = build_instance_pass_contract(
        state,
        plan,
        _owners(state, owner_count),
        load_instance_pass_policy(INSTANCE_POLICY),
    )
    snapshot = build_v1_ontology_snapshot(ONTOLOGY)
    active = [row["id"] for row in snapshot["part_labels"] if row["enabled"]]
    part = build_part_pass_contract(
        state,
        plan,
        snapshot,
        _mapping(state, snapshot, active),
        [1, 2],
        load_part_pass_policy(PART_POLICY),
    )
    material_policy = load_material_protected_policy(MATERIAL_POLICY)
    materials = [
        build_material_protected_contract(
            part,
            plan,
            snapshot,
            target_p_index=f"p{index}",
            expected_material_ids=[1, 3],
            policy=material_policy,
        )
        for index in range(owner_count)
    ]
    return state, plan, instance, part, materials


def _arrays(owner_count: int = 2) -> dict[str, object]:
    height, width = 48, 64
    instance = np.zeros((height, width), dtype=np.uint16)
    part = np.zeros_like(instance)
    material = np.zeros_like(instance)
    usable_width = 56
    start = 4
    edges = np.linspace(start, start + usable_width, owner_count + 1, dtype=int)
    for index in range(owner_count):
        region = np.zeros_like(instance, dtype=bool)
        region[6:42, edges[index] : edges[index + 1]] = True
        instance[region] = index + 1
        part[region] = 1 if index % 2 == 0 else 2
        material[region] = 1 if index % 2 == 0 else 3
    visible = instance > 0
    protected = {}
    for index in range(owner_count):
        array = np.zeros_like(instance)
        array[visible & (instance != index + 1)] = 50
        protected[f"p{index}"] = array
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    rgb[..., 0] = np.arange(width, dtype=np.uint8)
    rgb[..., 1] = np.arange(height, dtype=np.uint8)[:, None]
    rgb[..., 2] = 127
    return {
        "rgb": rgb,
        "instance": instance,
        "part": part,
        "material": material,
        "protected": protected,
    }


def _write_sources(
    root: Path, arrays: dict[str, object]
) -> tuple[dict[str, Path], dict[str, Path]]:
    root.mkdir(parents=True, exist_ok=True)
    paths = {role: root / f"{role}.png" for role in ("rgb", "instance", "part", "material")}
    Image.fromarray(arrays["rgb"]).save(paths["rgb"], format="PNG")
    for role in ("instance", "part", "material"):
        Image.fromarray(arrays[role]).save(paths[role], format="PNG")
    protected_paths = {}
    for p_index, array in arrays["protected"].items():
        path = root / f"protected_{p_index}.png"
        Image.fromarray(array).save(path, format="PNG")
        protected_paths[p_index] = path
    return paths, protected_paths


def _authorities(profile: str = "training_relationship") -> dict[str, str]:
    roles = ["instance", "part", "material", "coverage_alpha", "geometry"]
    if profile in {"training_relationship", "diagnostic_full"}:
        roles.append("relationship")
    return {role: hashlib.sha256(f"authority:{role}".encode()).hexdigest() for role in roles}


def _fixture(tmp_path: Path, owner_count: int = 2):
    _state, _plan_document, instance, part, materials = _contracts(owner_count)
    arrays = _arrays(owner_count)
    source_paths, protected_paths = _write_sources(tmp_path / "source", arrays)
    policy = load_package_derivation_policy(POLICY_PATH)
    contract = build_package_derivation_contract(
        instance,
        part,
        materials,
        image_id="image_fixture_001",
        scene_family_id="scene_family_fixture_001",
        source_paths=source_paths,
        protected_paths=protected_paths,
        authority_report_sha256s=_authorities(),
        policy=policy,
    )
    return policy, contract, arrays, source_paths, protected_paths


def test_policy_closes_truth_derivation_and_publication() -> None:
    policy = load_package_derivation_policy(POLICY_PATH)
    validate_package_derivation_policy(policy)
    assert policy["truth_contract"]["truth_tier"] == "weighted_pseudo_label"
    assert policy["truth_contract"]["counts_as_human_anchor_gold"] is False
    assert policy["truth_contract"]["counts_as_autonomous_certified_gold"] is False
    assert policy["derivation"]["rerender_forbidden"] is True


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda p: p.__setitem__("policy_version", "2.0.0"), "identity"),
        (lambda p: p["eligible_profiles"].pop(), "profiles"),
        (lambda p: p["truth_contract"].__setitem__("truth_tier", "human_anchor_gold"), "truth"),
        (lambda p: p["derivation"].__setitem__("rerender_forbidden", False), "derivation"),
        (lambda p: p["required_package_files"].pop(), "files"),
        (lambda p: p["forbidden_human_fields"].pop(), "human_fields"),
        (lambda p: p["publication"].__setitem__("immutable", False), "publication"),
    ],
)
def test_closed_policy_drift_fails(mutation, reason: str) -> None:
    policy = load_package_derivation_policy(POLICY_PATH)
    mutation(policy)
    with pytest.raises(PackageDerivationError, match=f"package_policy_{reason}_invalid"):
        validate_package_derivation_policy(policy)


@pytest.mark.parametrize("owner_count", [1, 2, 3, 4])
def test_contract_covers_one_through_four_promoted_people(tmp_path: Path, owner_count: int) -> None:
    _policy, contract, _arrays_document, _sources, protected = _fixture(tmp_path, owner_count)
    assert contract["owners"] == [
        {"p_index": f"p{index}", "instance_id": index + 1} for index in range(owner_count)
    ]
    assert set(contract["source_file_sha256s"]["protected_by_p_index"]) == set(protected)


def test_training_standard_omits_relationship_authority(tmp_path: Path) -> None:
    _state, _plan_document, instance, part, materials = _contracts(1, profile="training_standard")
    arrays = _arrays(1)
    source_paths, protected_paths = _write_sources(tmp_path / "standard", arrays)
    contract = build_package_derivation_contract(
        instance,
        part,
        materials,
        image_id="standard_image",
        scene_family_id="standard_family",
        source_paths=source_paths,
        protected_paths=protected_paths,
        authority_report_sha256s=_authorities("training_standard"),
        policy=load_package_derivation_policy(POLICY_PATH),
    )
    assert contract["profile"] == "training_standard"
    assert "relationship" not in contract["authority_report_sha256s"]


def test_vectorized_derivation_is_lossless_and_complement_exact(tmp_path: Path) -> None:
    policy, contract, arrays, source_paths, protected_paths = _fixture(tmp_path)
    report, root, published = derive_scene_packages(
        contract,
        source_paths=source_paths,
        protected_paths=protected_paths,
        output_root=tmp_path / "exports",
        policy=policy,
    )
    assert published is True
    assert report["summary"] == {
        "passed": True,
        "package_count": 2,
        "visible_person_pixels": int(np.count_nonzero(arrays["instance"])),
    }
    for index in range(2):
        package = root / "packages" / f"p{index}"
        target = arrays["instance"] == index + 1
        other = (arrays["instance"] > 0) & ~target
        assert (package / "source_rgb.png").read_bytes() == source_paths["rgb"].read_bytes()
        assert np.array_equal(np.asarray(Image.open(package / "full_body.png")) > 0, target)
        assert np.array_equal(
            np.asarray(Image.open(package / "indexed_part.png")),
            np.where(target, arrays["part"], 0),
        )
        assert np.array_equal(
            np.asarray(Image.open(package / "material.png")),
            np.where(target, arrays["material"], 0),
        )
        assert np.array_equal(np.asarray(Image.open(package / "other_person.png")) > 0, other)
        assert np.array_equal(
            np.asarray(Image.open(package / "protected.png")),
            arrays["protected"][f"p{index}"],
        )
        assert sorted(path.name for path in package.iterdir()) == sorted(
            policy["required_package_files"]
        )
        lineage = json.loads((package / "synthetic_lineage.json").read_text())
        assert lineage["truth_tier"] == "weighted_pseudo_label"
        assert lineage["rerendered"] is False
        assert not set(policy["forbidden_human_fields"]) & set(lineage)
        hashes = json.loads((package / "hashes.json").read_text())
        for name, digest in hashes["files"].items():
            assert hashlib.sha256((package / name).read_bytes()).hexdigest() == digest
    assert report["invariants"] == {key: True for key in report["invariants"]}


def test_all_active_part_ids_roundtrip_exactly(tmp_path: Path) -> None:
    policy, contract, arrays, source_paths, protected_paths = _fixture(tmp_path, 1)
    target = arrays["instance"] == 1
    active_ids = np.arange(1, 54, dtype=np.uint16)
    arrays["part"][target] = np.resize(active_ids, int(np.count_nonzero(target)))
    source_paths, protected_paths = _write_sources(tmp_path / "all_parts", arrays)
    _state, _plan_document, instance, part, materials = _contracts(1)
    contract = build_package_derivation_contract(
        instance,
        part,
        materials,
        image_id="image_all_parts",
        scene_family_id="family_all_parts",
        source_paths=source_paths,
        protected_paths=protected_paths,
        authority_report_sha256s=_authorities(),
        policy=policy,
    )
    _report, root, _published = derive_scene_packages(
        contract,
        source_paths=source_paths,
        protected_paths=protected_paths,
        output_root=tmp_path / "exports",
        policy=policy,
    )
    assert np.array_equal(
        np.asarray(Image.open(root / "packages" / "p0" / "indexed_part.png")),
        arrays["part"],
    )


def test_publication_is_atomic_immutable_and_idempotent(tmp_path: Path) -> None:
    policy, contract, _arrays_document, source_paths, protected_paths = _fixture(tmp_path)
    first, root, published = derive_scene_packages(
        contract,
        source_paths=source_paths,
        protected_paths=protected_paths,
        output_root=tmp_path / "exports",
        policy=policy,
    )
    replay, replay_root, replay_published = derive_scene_packages(
        contract,
        source_paths=source_paths,
        protected_paths=protected_paths,
        output_root=tmp_path / "exports",
        policy=policy,
    )
    assert (replay, replay_root, replay_published) == (first, root, False)
    (root / "packages" / "p0" / "full_body.png").write_bytes(b"tampered")
    with pytest.raises(PackageDerivationError, match="package_publication_conflict"):
        derive_scene_packages(
            contract,
            source_paths=source_paths,
            protected_paths=protected_paths,
            output_root=tmp_path / "exports",
            policy=policy,
        )


def test_source_hash_tamper_fails_before_decode(tmp_path: Path) -> None:
    policy, contract, _arrays_document, source_paths, protected_paths = _fixture(tmp_path)
    source_paths["part"].write_bytes(source_paths["part"].read_bytes() + b"tamper")
    with pytest.raises(PackageDerivationError, match="package_source_file_mismatch"):
        derive_scene_packages(
            contract,
            source_paths=source_paths,
            protected_paths=protected_paths,
            output_root=tmp_path / "exports",
            policy=policy,
        )


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda a: a["instance"].__setitem__((0, 0), 9), "instance_namespace"),
        (lambda a: a["part"].__setitem__((10, 10), 0), "part_instance_equation"),
        (lambda a: a["material"].__setitem__((10, 10), 0), "material_instance_equation"),
        (lambda a: a["part"].__setitem__((10, 10), 65535), "part_namespace"),
        (lambda a: a["material"].__setitem__((10, 10), 65535), "material_namespace"),
        (
            lambda a: a["protected"]["p0"].__setitem__((10, 10), 50),
            "protected_other_person",
        ),
        (
            lambda a: a["protected"]["p0"].__setitem__((0, 0), 49),
            "protected_namespace",
        ),
    ],
)
def test_seeded_full_image_semantic_defects_fail(tmp_path: Path, mutate, reason: str) -> None:
    policy, _old_contract, arrays, _old_sources, _old_protected = _fixture(tmp_path)
    mutate(arrays)
    source_paths, protected_paths = _write_sources(tmp_path / "mutated", arrays)
    _state, _plan_document, instance, part, materials = _contracts(2)
    contract = build_package_derivation_contract(
        instance,
        part,
        materials,
        image_id="image_mutated",
        scene_family_id="family_mutated",
        source_paths=source_paths,
        protected_paths=protected_paths,
        authority_report_sha256s=_authorities(),
        policy=policy,
    )
    with pytest.raises(PackageDerivationError, match=f"package_{reason}_invalid"):
        derive_scene_packages(
            contract,
            source_paths=source_paths,
            protected_paths=protected_paths,
            output_root=tmp_path / "exports",
            policy=policy,
        )


def test_cli_contract_and_derivation_are_idempotent(tmp_path: Path) -> None:
    _state, _plan_document, instance, part, materials = _contracts(2)
    arrays = _arrays(2)
    source_paths, protected_paths = _write_sources(tmp_path / "source", arrays)
    document_paths = {}
    for name, document in {"instance": instance, "part": part}.items():
        path = tmp_path / f"{name}_contract.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        document_paths[name] = path
    material_paths = []
    for index, material_contract in enumerate(materials):
        path = tmp_path / f"material_contract_p{index}.json"
        path.write_text(json.dumps(material_contract), encoding="utf-8")
        material_paths.append(path)
    protected_document = tmp_path / "protected_paths.json"
    protected_document.write_text(
        json.dumps({key: str(value) for key, value in protected_paths.items()}),
        encoding="utf-8",
    )
    authority_document = tmp_path / "authority_hashes.json"
    authority_document.write_text(json.dumps(_authorities()), encoding="utf-8")
    contract_output = tmp_path / "contracts"
    plan_arguments = [
        "daz",
        "recipes",
        "plan-package-derivation",
        "--instance-contract",
        str(document_paths["instance"]),
        "--part-contract",
        str(document_paths["part"]),
    ]
    for path in material_paths:
        plan_arguments.extend(["--material-contract", str(path)])
    plan_arguments.extend(
        [
            "--image-id",
            "cli_image_001",
            "--scene-family-id",
            "cli_family_001",
            "--source-rgb",
            str(source_paths["rgb"]),
            "--instance-image",
            str(source_paths["instance"]),
            "--part-image",
            str(source_paths["part"]),
            "--material-image",
            str(source_paths["material"]),
            "--protected-paths",
            str(protected_document),
            "--authority-hashes",
            str(authority_document),
            "--policy",
            str(POLICY_PATH),
            "--output",
            str(contract_output),
        ]
    )
    runner = CliRunner()
    planned = runner.invoke(main, plan_arguments)
    assert planned.exit_code == 0, planned.output
    planned_payload = json.loads(planned.output)
    assert planned_payload["data"]["publication"]["published"] is True
    replay = runner.invoke(main, plan_arguments)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
    contract_path = Path(planned_payload["data"]["publication"]["path"])
    export_output = tmp_path / "exports"
    derive_arguments = [
        "daz",
        "recipes",
        "derive-scene-packages",
        "--contract",
        str(contract_path),
        "--source-rgb",
        str(source_paths["rgb"]),
        "--instance-image",
        str(source_paths["instance"]),
        "--part-image",
        str(source_paths["part"]),
        "--material-image",
        str(source_paths["material"]),
        "--protected-paths",
        str(protected_document),
        "--policy",
        str(POLICY_PATH),
        "--output",
        str(export_output),
    ]
    derived = runner.invoke(main, derive_arguments)
    assert derived.exit_code == 0, derived.output
    derived_payload = json.loads(derived.output)
    assert derived_payload["data"]["summary"]["passed"] is True
    assert derived_payload["data"]["publication"]["published"] is True
    derived_replay = runner.invoke(main, derive_arguments)
    assert derived_replay.exit_code == 0, derived_replay.output
    assert json.loads(derived_replay.output)["data"]["publication"]["published"] is False
