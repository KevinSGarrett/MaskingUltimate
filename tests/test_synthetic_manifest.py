from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from maskfactory.ontology_v2_manifest import migrate_v1_manifest_document
from maskfactory.synthetic_manifest import (
    SYNTHETIC_SCHEMA_BY_ONTOLOGY,
    SYNTHETIC_SCHEMA_VERSION,
    SyntheticManifestError,
    build_synthetic_manifest,
    require_valid_synthetic_manifest,
    synthetic_manifest_schema_name,
    validate_synthetic_manifest,
)
from maskfactory.validation import (
    ArtifactValidationError,
    require_valid_document,
    schema_validator,
    validate_document,
)
from test_manifest_schema import valid_manifest
from test_ontology_v2_migration import _v1_manifest as valid_v2_source

ROOT = Path(__file__).resolve().parents[1]
V1_SCHEMA = ROOT / "src" / "maskfactory" / "schemas" / "manifest.schema.json"
V2_SCHEMA = ROOT / "src" / "maskfactory" / "schemas" / "manifest_v2.schema.json"
HISTORICAL_SCHEMA_SHA256S = {
    "manifest": "d6e2f004a73099b3089d952f3d7479952d28b2b446c9741772931b909032f285",
    "manifest_v2": "abb2f1afba611e0377952d0481e4ddc8e44644a22faf16047b68f20d433a7c2c",
}
SHA = "a" * 64


def _draft(ontology: str = "body_parts_v1", p_index: str = "p0") -> dict:
    instance_id = int(p_index[1:]) + 1
    scene = "daz_scene_fixture001"
    family = "daz_family_fixture001"
    variant = "variant_fixture001"
    file_names = {
        "source_rgb": "source_rgb.png",
        "full_body": "full_body.png",
        "indexed_part": "indexed_part.png",
        "material": "material.png",
        "other_person": "other_person.png",
        "protected": "protected.png",
        "qa_report": "qa_report.json",
    }
    return {
        "schema_version": SYNTHETIC_SCHEMA_VERSION,
        "package_id": f"mf_daz_fixture_{p_index}",
        "image_id": scene,
        "scene_id": scene,
        "scene_family_id": family,
        "variant_group_id": variant,
        "promoted_person_id": p_index,
        "source_origin": "synthetic",
        "annotation_authority": "geometry_render",
        "truth_tier": "weighted_pseudo_label",
        "truth_partition": "train",
        "train_eligible": True,
        "evaluation_eligible": False,
        "training_loss_weight": 0.2,
        "source_attributes": ["synthetic_geometry_exact", "visible_pixel_truth"],
        "ontology": {"name": ontology, "snapshot_sha256": "1" * 64},
        "mask_authority": {
            "provider_id": "daz_exact_geometry",
            "authority_tier": "synthetic_exact",
            "ontology_version": ontology,
            "ontology_sha256": "1" * 64,
            "owner": "maskfactory",
            "package_revision": "dpdc_fixture_revision",
            "certificate_id": f"dacc_{'d' * 24}",
            "certificate_sha256": "d" * 64,
            "certificate_scope": "scene_and_packages",
            "transform_chain_sha256": "f" * 64,
            "access_mode": "mode_a_approved_package",
        },
        "person_construction": {
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
        },
        "synthetic_lineage": {
            "generator": "daz_studio",
            "scene_id": scene,
            "scene_family_id": family,
            "variant_group_id": variant,
            "scene_state_sha256": "e" * 64,
            "recipe_sha256": "2" * 64,
            "asset_registry_snapshot_sha256": "3" * 64,
            "operating_profile_snapshot_sha256": "4" * 64,
            "registry_snapshot_sha256": "5" * 64,
            "runtime_snapshot_sha256": "6" * 64,
            "script_bundle_sha256": "7" * 64,
            "renderer_snapshot_sha256": "8" * 64,
            "asset_snapshot_sha256": "9" * 64,
            "mapping_set_sha256": "b" * 64,
            "mapping_ontology_version": ontology,
            "pass_profile_id": "training_relationship_1024_v1",
            "pass_profile_sha256": "c" * 64,
            "scene_certificate_id": f"dacc_{'d' * 24}",
            "scene_certificate_sha256": "d" * 64,
            "instance_mapping": {
                "promoted_person_id": p_index,
                "instance_id": instance_id,
            },
            "geometry_exact": True,
            "semantic_mapping_status": "validated",
            "visible_only": True,
            "amodal_train_eligible": False,
            "train_only": True,
            "counts_as_human_anchor_gold": False,
            "counts_as_autonomous_certified_gold": False,
        },
        "files": {
            role: {"path": name, "sha256": hashlib.sha256(name.encode()).hexdigest()}
            for role, name in file_names.items()
        },
    }


@pytest.mark.parametrize("ontology", ["body_parts_v1", "body_parts_v2"])
@pytest.mark.parametrize("p_index", ["p0", "p1", "p2", "p3"])
def test_v1_v2_synthetic_versions_accept_one_through_four_people(
    ontology: str, p_index: str
) -> None:
    manifest = build_synthetic_manifest(_draft(ontology, p_index))
    require_valid_synthetic_manifest(manifest)
    assert synthetic_manifest_schema_name(manifest) == SYNTHETIC_SCHEMA_BY_ONTOLOGY[ontology]
    assert schema_validator(SYNTHETIC_SCHEMA_BY_ONTOLOGY[ontology])
    assert manifest["truth_tier"] == "weighted_pseudo_label"
    assert manifest["mask_authority"]["authority_tier"] == "synthetic_exact"
    assert manifest["mask_authority"]["access_mode"] == "mode_a_approved_package"


def test_historical_v1_and_v2_schemas_are_byte_locked_and_validate_unchanged() -> None:
    for name, path in (("manifest", V1_SCHEMA), ("manifest_v2", V2_SCHEMA)):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == HISTORICAL_SCHEMA_SHA256S[name]
    historical_v1 = valid_manifest()
    require_valid_document(historical_v1, "manifest")
    historical_v2 = migrate_v1_manifest_document(valid_v2_source())
    require_valid_document(historical_v2, "manifest_v2")
    assert validate_synthetic_manifest(historical_v1)[0].validator == "synthetic_schema_dispatch"
    assert validate_synthetic_manifest(historical_v2)[0].validator == "synthetic_schema_dispatch"


def test_synthetic_origin_is_rejected_by_both_historical_versions() -> None:
    historical_v1 = valid_manifest()
    historical_v1["source"]["source_origin"] = "synthetic"
    assert validate_document(historical_v1, "manifest")
    historical_v2 = migrate_v1_manifest_document(valid_v2_source())
    historical_v2["source"]["source_origin"] = "synthetic"
    assert validate_document(historical_v2, "manifest_v2")


@pytest.mark.parametrize("weight", [0.1, 0.2, 0.25])
def test_synthetic_weight_inclusive_bounds_pass(weight: float) -> None:
    draft = _draft()
    draft["training_loss_weight"] = weight
    require_valid_synthetic_manifest(build_synthetic_manifest(draft))


@pytest.mark.parametrize("weight", [0.099999, 0.250001, 0.0, 1.0])
def test_synthetic_weight_outside_bounds_fails(weight: float) -> None:
    draft = _draft()
    draft["training_loss_weight"] = weight
    with pytest.raises(ArtifactValidationError):
        build_synthetic_manifest(draft)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("truth_tier", "autonomous_certified_gold"),
        ("truth_partition", "holdout"),
        ("train_eligible", False),
        ("evaluation_eligible", True),
        ("annotation_authority", "human_review"),
        ("source_origin", "generated"),
    ],
)
def test_synthetic_cannot_claim_real_gold_review_or_evaluation_authority(field: str, value) -> None:
    draft = _draft()
    draft[field] = value
    with pytest.raises(ArtifactValidationError):
        build_synthetic_manifest(draft)


@pytest.mark.parametrize(
    "field",
    json.loads(
        (ROOT / "src" / "maskfactory" / "schemas" / "manifest_synthetic_v1.schema.json").read_text(
            encoding="utf-8"
        )
    )["$defs"]["syntheticLineage"]["required"],
)
def test_every_synthetic_lineage_field_is_required(field: str) -> None:
    draft = _draft()
    del draft["synthetic_lineage"][field]
    with pytest.raises(ArtifactValidationError):
        build_synthetic_manifest(draft)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("synthetic_lineage", "scene_id"), "daz_scene_stale"),
        (("synthetic_lineage", "scene_family_id"), "daz_family_stale"),
        (("synthetic_lineage", "variant_group_id"), "variant_stale"),
        (("synthetic_lineage", "mapping_ontology_version"), "body_parts_v2"),
        (("synthetic_lineage", "instance_mapping", "promoted_person_id"), "p1"),
        (("synthetic_lineage", "instance_mapping", "instance_id"), 2),
        (("person_construction", "person_id"), "p1"),
    ],
)
def test_shared_scene_person_instance_and_ontology_fields_are_cross_bound(
    path: tuple[str, ...], value
) -> None:
    draft = _draft()
    target = draft
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ArtifactValidationError):
        build_synthetic_manifest(draft)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("owner", "bundle_selector"),
        ("access_mode", "mode_b_live"),
        ("provider_id", "inferred_provider"),
        ("authority_tier", "human_anchor_gold"),
        ("ontology_sha256", "0" * 64),
        ("certificate_id", f"dacc_{'0' * 24}"),
        ("certificate_sha256", "0" * 64),
    ],
)
def test_mask_authority_is_explicit_mode_a_and_cross_bound(field: str, value) -> None:
    draft = _draft()
    draft["mask_authority"][field] = value
    with pytest.raises(ArtifactValidationError):
        build_synthetic_manifest(draft)


def test_human_review_fields_are_forbidden_at_any_depth() -> None:
    draft = _draft()
    draft["person_construction"]["reviewer_identity"] = "kevin"
    draft["synthetic_lineage"]["human_edit"] = True
    with pytest.raises(ArtifactValidationError) as caught:
        build_synthetic_manifest(draft)
    validators = {issue.validator for issue in caught.value.issues}
    assert "synthetic_human_authority_forbidden" in validators


def test_source_attributes_are_exact_and_amodal_or_gold_flags_cannot_drift() -> None:
    draft = _draft()
    draft["source_attributes"].append("autonomous_certified_real")
    with pytest.raises(ArtifactValidationError):
        build_synthetic_manifest(draft)
    for field, value in (
        ("geometry_exact", False),
        ("visible_only", False),
        ("amodal_train_eligible", True),
        ("counts_as_human_anchor_gold", True),
        ("counts_as_autonomous_certified_gold", True),
    ):
        drifted = _draft()
        drifted["synthetic_lineage"][field] = value
        with pytest.raises(ArtifactValidationError):
            build_synthetic_manifest(drifted)


def test_package_hash_is_canonical_stable_and_tamper_evident() -> None:
    draft = _draft()
    reversed_draft = json.loads(
        json.dumps(draft, sort_keys=True), object_pairs_hook=lambda pairs: dict(reversed(pairs))
    )
    first = build_synthetic_manifest(draft)
    second = build_synthetic_manifest(reversed_draft)
    assert first["package_sha256"] == second["package_sha256"]
    tampered = copy.deepcopy(first)
    tampered["person_construction"]["morph_values"]["uri_body_height"] = 0.5
    issues = validate_synthetic_manifest(tampered)
    assert any(issue.validator == "synthetic_package_hash" for issue in issues)


def test_canonical_hash_is_stable_across_fresh_processes() -> None:
    script = (
        "import json,sys; "
        "from maskfactory.synthetic_manifest import build_synthetic_manifest; "
        "print(build_synthetic_manifest(json.load(sys.stdin))['package_sha256'])"
    )
    payload = json.dumps(_draft())
    observed = [
        subprocess.run(
            [sys.executable, "-c", script],
            input=payload,
            text=True,
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout.strip()
        for _ in range(2)
    ]
    assert observed[0] == observed[1] == build_synthetic_manifest(_draft())["package_sha256"]


def test_unknown_schema_or_ontology_cannot_fall_back_to_historical_meaning() -> None:
    draft = _draft()
    draft["schema_version"] = "1.0.0"
    with pytest.raises(SyntheticManifestError):
        synthetic_manifest_schema_name(draft)
    draft = _draft()
    draft["ontology"]["name"] = "body_parts_v3"
    with pytest.raises(SyntheticManifestError):
        synthetic_manifest_schema_name(draft)
