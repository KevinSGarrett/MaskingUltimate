from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from maskfactory.daz.render import build_package_derivation_contract  # noqa: E402
from maskfactory.daz.s00_adapter import (  # noqa: E402
    S00AdapterError,
    adapt_accepted_scene,
    load_s00_adapter_policy,
    validate_s00_adapter_policy,
    validate_s00_adapter_report,
)
from maskfactory.synthetic_manifest import require_valid_synthetic_manifest  # noqa: E402
from test_daz_acceptance_certificate import (  # noqa: E402
    _build,
    _package_contracts,
    _package_fixture,
    _policy,
    _registry,
    _repair_policy,
)

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_POLICY = ROOT / "configs" / "daz" / "s00_package_adapter.yaml"
ONTOLOGY = ROOT / "configs" / "ontology.yaml"


def _tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _construction(p_index: str) -> dict:
    return {
        "person_id": p_index,
        "figure_asset_id": "asset_figure_g9",
        "character_preset_asset_id": None,
        "body_profile_id": "body_profile_fixture",
        "face_profile_id": "face_profile_fixture",
        "skin_material_asset_id": "asset_skin_fixture",
        "hair_asset_id": None,
        "wardrobe_asset_ids": ["asset_wardrobe_fixture"],
        "anatomy_configuration": "adult_female",
        "anatomy_asset_ids": ["asset_anatomy_fixture"],
        "age_appearance_category": "adult_30_44",
        "presentation_profile": "presentation_fixture",
        "morph_values": {"uri_body_height": 0.25},
        "pose_asset_id": "asset_pose_fixture",
        "pose_adjustments": {"uri_joint_shoulder": [0.0, 1.0, -1.0]},
        "mapping_bundle_id": "mapping_fixture",
    }


def _fixture(tmp_path: Path, owner_count: int = 2):
    def valid_family_contract(*args, **kwargs):
        kwargs["scene_family_id"] = "daz_family_fixture_001"
        return build_package_derivation_contract(*args, **kwargs)

    with (
        patch(
            "test_daz_acceptance_certificate._package_fixture",
            lambda root: _package_fixture(root, owner_count),
        ),
        patch(
            "test_daz_acceptance_certificate._package_contracts",
            lambda: _package_contracts(owner_count),
        ),
        patch(
            "test_daz_package_derivation.build_package_derivation_contract",
            valid_family_contract,
        ),
    ):
        certificate, artifacts = _build(tmp_path)
    _draft, validation, replay, contract, package_report = artifacts
    metadata = {
        "schema_version": "1.0.0",
        "variant_group_id": "variant_fixture001",
        "asset_registry_snapshot_sha256": "8" * 64,
        "operating_profile_snapshot_sha256": "9" * 64,
        "script_bundle_sha256": "a" * 64,
        "renderer_snapshot_sha256": "b" * 64,
        "asset_snapshot_sha256": "c" * 64,
        "pass_profile_id": "training_relationship_1024_v1",
        "pass_profile_sha256": "d" * 64,
        "person_construction_by_p_index": {
            owner["p_index"]: _construction(owner["p_index"]) for owner in contract["owners"]
        },
    }
    return {
        "metadata": metadata,
        "certificate": certificate,
        "validation_report": validation,
        "semantic_replay_report": replay,
        "package_contract": contract,
        "package_report": package_report,
        "repair_history": None,
        "post_repair_reports": {},
        "source_scene_root": tmp_path / "package_exports" / contract["contract_id"],
        "output_root": tmp_path / "adapted",
        "policy": load_s00_adapter_policy(ADAPTER_POLICY),
        "acceptance_policy": _policy(),
        "repair_policy": _repair_policy(),
        "registry": _registry(),
        "ontology_source": ONTOLOGY,
    }


@pytest.mark.parametrize("owner_count", [1, 2, 3, 4])
def test_adapter_supports_one_through_four_promoted_people(
    tmp_path: Path, owner_count: int
) -> None:
    fixture = _fixture(tmp_path, owner_count)
    report, root, published = adapt_accepted_scene(**fixture)
    assert published is True
    assert report["summary"]["package_count"] == owner_count
    assert [row["p_index"] for row in report["packages"]] == [
        f"p{index}" for index in range(owner_count)
    ]
    assert len(list((root / "packages").iterdir())) == owner_count


def test_adapter_copies_verified_packages_and_emits_bound_manifests(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    before = _tree(fixture["source_scene_root"])
    report, output, published = adapt_accepted_scene(**fixture)
    validate_s00_adapter_report(report)
    assert published is True
    assert _tree(fixture["source_scene_root"]) == before
    assert report["summary"]["package_count"] == 2
    assert report["source_record"]["provider_voting_bypassed"] is True
    assert report["source_record"]["package_verification_bypassed"] is False
    source_rows = {row["p_index"]: row for row in fixture["package_report"]["packages"]}
    for row in report["packages"]:
        source = fixture["source_scene_root"] / source_rows[row["p_index"]]["relative_root"]
        target = output / row["relative_root"]
        for name in fixture["policy"]["required_source_package_files"]:
            assert (target / name).read_bytes() == (source / name).read_bytes()
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        require_valid_synthetic_manifest(manifest)
        assert manifest["truth_tier"] == "weighted_pseudo_label"
        assert manifest["evaluation_eligible"] is False
        assert manifest["mask_authority"]["access_mode"] == "mode_a_approved_package"
        assert (
            manifest["mask_authority"]["certificate_sha256"]
            == fixture["certificate"]["certificate_sha256"]
        )
        assert manifest["synthetic_lineage"]["counts_as_human_anchor_gold"] is False
        assert manifest["synthetic_lineage"]["counts_as_autonomous_certified_gold"] is False


def test_adapter_publication_is_idempotent_and_immutable(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    first, root, published = adapt_accepted_scene(**fixture)
    second, same_root, republished = adapt_accepted_scene(**fixture)
    assert published is True and republished is False
    assert first == second and root == same_root
    (root / "synthetic_source_record.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(S00AdapterError, match="adapter_publication_conflict"):
        adapt_accepted_scene(**fixture)


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (
            ("training_contract", "truth_tier"),
            "autonomous_certified_gold",
            "adapter_policy_training_invalid",
        ),
        (
            ("source_registration", "bypass_package_verification"),
            True,
            "adapter_policy_registration_invalid",
        ),
        (
            ("source_registration", "bypass_real_image_mask_provider_voting"),
            False,
            "adapter_policy_registration_invalid",
        ),
        (("publication", "rerender_forbidden"), False, "adapter_policy_publication_invalid"),
        (("body_parts_v2_active",), True, "adapter_policy_identity_invalid"),
    ],
)
def test_adapter_policy_cannot_weaken_truth_verification_or_ontology(
    path: tuple[str, ...], value, reason: str
) -> None:
    policy = load_s00_adapter_policy(ADAPTER_POLICY)
    target = policy
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(S00AdapterError, match=reason):
        validate_s00_adapter_policy(policy)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("anatomy_configuration", "minor_female"),
        ("age_appearance_category", "teen"),
        ("person_id", "p3"),
    ],
)
def test_adapter_rejects_invalid_or_mismatched_adult_construction(
    tmp_path: Path, field: str, value: str
) -> None:
    fixture = _fixture(tmp_path)
    fixture["metadata"]["person_construction_by_p_index"]["p0"][field] = value
    with pytest.raises(S00AdapterError, match="adapter_adult_construction_invalid"):
        adapt_accepted_scene(**fixture)


def test_adapter_rejects_stale_certificate(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture["certificate"]["authority"]["transform_chain_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        adapt_accepted_scene(**fixture)


def test_adapter_rejects_source_hash_drift_and_extra_files(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    package = fixture["source_scene_root"] / "packages" / "p0"
    (package / "full_body.png").write_bytes(b"not-a-png")
    with pytest.raises(S00AdapterError, match="adapter_package_file_hash_invalid"):
        adapt_accepted_scene(**fixture)
    fixture = _fixture(tmp_path / "extra")
    package = fixture["source_scene_root"] / "packages" / "p0"
    (package / "unexpected.txt").write_text("forbidden", encoding="utf-8")
    with pytest.raises(S00AdapterError, match="adapter_package_file_set_invalid"):
        adapt_accepted_scene(**fixture)


def test_adapter_report_hash_and_schema_tamper_fail(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report, _root, _published = adapt_accepted_scene(**fixture)
    tampered = copy.deepcopy(report)
    tampered["summary"]["visible_person_pixels"] += 1
    with pytest.raises(S00AdapterError, match="adapter_report_hash_invalid"):
        validate_s00_adapter_report(tampered)
    tampered = copy.deepcopy(report)
    tampered["invariants"]["no_rerender"] = False
    with pytest.raises(ValueError):
        validate_s00_adapter_report(tampered)
