"""Vectorized lossless derivation of per-person packages from shared DAZ passes."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import yaml
from PIL import Image

from ...validation import require_valid_document
from .instance import decode_u16_png_exact


class PackageDerivationError(ValueError):
    """A derivation policy, contract, source pass, or publication is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_package_derivation_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_package_derivation_policy(document)
    return document


def validate_package_derivation_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "eligible_profiles",
        "truth_contract",
        "derivation",
        "required_package_files",
        "forbidden_human_fields",
        "publication",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise PackageDerivationError("package_policy_fields_invalid", str(policy))
    if policy["schema_version"] != "1.0.0" or policy["policy_version"] != "1.0.0":
        raise PackageDerivationError("package_policy_identity_invalid", str(policy))
    if policy["eligible_profiles"] != [
        "training_standard",
        "training_relationship",
        "diagnostic_full",
    ]:
        raise PackageDerivationError("package_policy_profiles_invalid", str(policy))
    if policy["truth_contract"] != {
        "source_origin": "synthetic",
        "annotation_authority": "geometry_render",
        "truth_tier": "weighted_pseudo_label",
        "truth_partition": "train",
        "train_eligible": True,
        "evaluation_eligible": False,
        "training_loss_weight": 0.20,
        "source_attributes": ["synthetic_geometry_exact", "visible_pixel_truth"],
        "counts_as_human_anchor_gold": False,
        "counts_as_autonomous_certified_gold": False,
    }:
        raise PackageDerivationError("package_policy_truth_invalid", str(policy))
    if policy["derivation"] != {
        "vectorized_full_image_only": True,
        "rerender_forbidden": True,
        "shared_rgb_bytes_identical": True,
        "per_person_part_and_material_masked_by_instance": True,
        "other_person_exact_non_target_union": True,
        "protected_other_person_id": 50,
        "allowed_protected_ids": [0, 50, 51, 52, 53],
        "binary_foreground_value": 255,
        "binary_background_value": 0,
        "integer_background_value": 0,
        "output_png_compress_level": 9,
    }:
        raise PackageDerivationError("package_policy_derivation_invalid", str(policy))
    if policy["required_package_files"] != [
        "source_rgb.png",
        "full_body.png",
        "indexed_part.png",
        "material.png",
        "other_person.png",
        "protected.png",
        "source_manifest.json",
        "instance_manifest.json",
        "synthetic_lineage.json",
        "qa_report.json",
        "hashes.json",
    ]:
        raise PackageDerivationError("package_policy_files_invalid", str(policy))
    if policy["forbidden_human_fields"] != [
        "reviewer_identity",
        "cvat_task_id",
        "cvat_job_id",
        "manual_edit_timestamp",
        "human_review_complete",
        "autonomous_certified_real_evidence",
        "calibration_authority",
    ]:
        raise PackageDerivationError("package_policy_human_fields_invalid", str(policy))
    if policy["publication"] != {
        "immutable": True,
        "atomic_scene_directory": True,
        "exhaustive_hash_manifest": True,
    }:
        raise PackageDerivationError("package_policy_publication_invalid", str(policy))


def build_package_derivation_contract(
    instance_contract: Mapping[str, Any],
    part_contract: Mapping[str, Any],
    material_contracts: Sequence[Mapping[str, Any]],
    *,
    image_id: str,
    scene_family_id: str,
    source_paths: Mapping[str, Path],
    protected_paths: Mapping[str, Path],
    authority_report_sha256s: Mapping[str, str],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind exact shared pass bytes and one target-specific protected map per p-index."""

    validate_package_derivation_policy(policy)
    require_valid_document(instance_contract, "daz_instance_pass_contract")
    _verify_hashed_document(instance_contract, "contract_id", "contract_sha256", "dipc")
    require_valid_document(part_contract, "daz_part_pass_contract")
    _verify_hashed_document(part_contract, "contract_id", "contract_sha256", "dppc")
    if not _identifier(image_id) or not _identifier(scene_family_id):
        raise PackageDerivationError(
            "package_group_identity_invalid", f"{image_id}:{scene_family_id}"
        )
    if (
        instance_contract["scene_id"] != part_contract["scene_id"]
        or instance_contract["scene_state_sha256"] != part_contract["scene_state_sha256"]
        or instance_contract["plan_id"] != part_contract["plan_id"]
        or instance_contract["plan_sha256"] != part_contract["plan_sha256"]
        or instance_contract["output"]["resolution"] != part_contract["output"]["resolution"]
        or part_contract["ontology_version"] != "body_parts_v1"
    ):
        raise PackageDerivationError("package_semantic_lineage_invalid", str(part_contract))
    owners = [
        {"p_index": owner["p_index"], "instance_id": owner["instance_id"]}
        for owner in instance_contract["owners"]
    ]
    expected_owners = [
        {"p_index": f"p{index}", "instance_id": index + 1} for index in range(len(owners))
    ]
    if owners != expected_owners:
        raise PackageDerivationError("package_owner_namespace_invalid", str(owners))
    material_by_p_index: dict[str, Mapping[str, Any]] = {}
    for material_contract in material_contracts:
        require_valid_document(material_contract, "daz_material_protected_contract")
        _verify_hashed_document(material_contract, "contract_id", "contract_sha256", "dmpc")
        p_index = material_contract["target_p_index"]
        if p_index in material_by_p_index:
            raise PackageDerivationError("package_material_contract_duplicate", p_index)
        material_by_p_index[p_index] = material_contract
    if not material_by_p_index:
        raise PackageDerivationError("package_material_contract_set_invalid", "empty")
    profile = next(iter(material_by_p_index.values()))["profile"]
    if profile not in policy["eligible_profiles"]:
        raise PackageDerivationError("package_profile_ineligible", profile)
    if set(material_by_p_index) != {owner["p_index"] for owner in owners}:
        raise PackageDerivationError(
            "package_material_contract_set_invalid", str(sorted(material_by_p_index))
        )
    for owner in owners:
        material_contract = material_by_p_index[owner["p_index"]]
        if (
            material_contract["scene_id"] != instance_contract["scene_id"]
            or material_contract["scene_state_sha256"] != instance_contract["scene_state_sha256"]
            or material_contract["plan_id"] != instance_contract["plan_id"]
            or material_contract["plan_sha256"] != instance_contract["plan_sha256"]
            or material_contract["part_contract_id"] != part_contract["contract_id"]
            or material_contract["part_contract_sha256"] != part_contract["contract_sha256"]
            or material_contract["ontology_snapshot_sha256"]
            != part_contract["ontology_snapshot_sha256"]
            or material_contract["target_instance_id"] != owner["instance_id"]
            or material_contract["profile"] != profile
            or "protected" not in material_contract["outputs"]
        ):
            raise PackageDerivationError("package_material_lineage_invalid", owner["p_index"])
    expected_source_roles = {"rgb", "instance", "part", "material"}
    if set(source_paths) != expected_source_roles or set(protected_paths) != {
        owner["p_index"] for owner in owners
    }:
        raise PackageDerivationError(
            "package_source_path_set_invalid",
            str((sorted(source_paths), sorted(protected_paths))),
        )
    expected_authorities = {
        "instance",
        "part",
        "material",
        "coverage_alpha",
        "geometry",
    }
    if profile in {"training_relationship", "diagnostic_full"}:
        expected_authorities.add("relationship")
    if set(authority_report_sha256s) != expected_authorities or not all(
        _sha256(value) for value in authority_report_sha256s.values()
    ):
        raise PackageDerivationError(
            "package_authority_report_set_invalid", str(authority_report_sha256s)
        )
    source_hashes = {role: _file_sha256(path) for role, path in source_paths.items()}
    source_bytes = {role: Path(path).stat().st_size for role, path in source_paths.items()}
    protected_hashes = {p_index: _file_sha256(path) for p_index, path in protected_paths.items()}
    protected_bytes = {
        p_index: Path(path).stat().st_size for p_index, path in protected_paths.items()
    }
    source_hashes["protected_by_p_index"] = protected_hashes
    source_bytes["protected_by_p_index"] = protected_bytes
    content = {
        "scene_id": instance_contract["scene_id"],
        "scene_state_sha256": instance_contract["scene_state_sha256"],
        "plan_id": instance_contract["plan_id"],
        "plan_sha256": instance_contract["plan_sha256"],
        "image_id": image_id,
        "scene_family_id": scene_family_id,
        "profile": profile,
        "ontology_version": part_contract["ontology_version"],
        "ontology_snapshot_sha256": part_contract["ontology_snapshot_sha256"],
        "policy_sha256": _canonical_sha(policy),
        "policy_version": policy["policy_version"],
        "resolution": instance_contract["output"]["resolution"],
        "owners": owners,
        "active_part_ids": part_contract["active_part_ids"],
        "active_material_ids": next(iter(material_by_p_index.values()))["active_material_ids"],
        "source_file_sha256s": source_hashes,
        "source_file_bytes": source_bytes,
        "authority_report_sha256s": dict(sorted(authority_report_sha256s.items())),
        "truth_contract": policy["truth_contract"],
        "required_package_files": policy["required_package_files"],
    }
    digest = _canonical_sha(content)
    contract = {
        "schema_version": "1.0.0",
        "contract_id": f"dpdc_{digest[:24]}",
        "contract_sha256": digest,
        **content,
    }
    require_valid_document(contract, "daz_package_derivation_contract")
    return contract


def derive_scene_packages(
    contract: Mapping[str, Any],
    *,
    source_paths: Mapping[str, Path],
    protected_paths: Mapping[str, Path],
    output_root: Path,
    policy: Mapping[str, Any],
) -> tuple[dict[str, Any], Path, bool]:
    """Derive and atomically publish every promoted-person package without rerendering."""

    validate_package_derivation_policy(policy)
    require_valid_document(contract, "daz_package_derivation_contract")
    _verify_hashed_document(contract, "contract_id", "contract_sha256", "dpdc")
    if contract["policy_sha256"] != _canonical_sha(policy):
        raise PackageDerivationError("package_policy_hash_mismatch", contract["policy_sha256"])
    owner_p_indices = {owner["p_index"] for owner in contract["owners"]}
    if (
        set(source_paths) != {"rgb", "instance", "part", "material"}
        or set(protected_paths) != owner_p_indices
    ):
        raise PackageDerivationError("package_source_path_set_invalid", str(source_paths))
    _verify_source_files(contract, source_paths, protected_paths)
    rgb_codec = _decode_rgb_png(source_paths["rgb"], contract["resolution"])
    instance, instance_codec = decode_u16_png_exact(source_paths["instance"])
    part, part_codec = decode_u16_png_exact(source_paths["part"])
    material, material_codec = decode_u16_png_exact(source_paths["material"])
    expected_shape = (contract["resolution"][1], contract["resolution"][0])
    if any(array.shape != expected_shape for array in (instance, part, material)):
        raise PackageDerivationError(
            "package_source_resolution_mismatch",
            str((instance.shape, part.shape, material.shape, expected_shape)),
        )
    owner_ids = [owner["instance_id"] for owner in contract["owners"]]
    observed_instances = set(int(value) for value in np.unique(instance))
    if not observed_instances <= {0, *owner_ids} or any(
        not np.any(instance == instance_id) for instance_id in owner_ids
    ):
        raise PackageDerivationError(
            "package_instance_namespace_invalid", str(sorted(observed_instances))
        )
    visible = instance > 0
    if np.any(visible & (part == 0)) or np.any((part > 0) & ~visible):
        raise PackageDerivationError("package_part_instance_equation_invalid", "part")
    if np.any(visible & (material == 0)):
        raise PackageDerivationError("package_material_instance_equation_invalid", "material")
    observed_parts = set(int(value) for value in np.unique(part))
    observed_materials = set(int(value) for value in np.unique(material))
    if not observed_parts <= set(contract["active_part_ids"]):
        raise PackageDerivationError("package_part_namespace_invalid", str(sorted(observed_parts)))
    if not observed_materials <= set(contract["active_material_ids"]):
        raise PackageDerivationError(
            "package_material_namespace_invalid", str(sorted(observed_materials))
        )
    protected_arrays: dict[str, np.ndarray] = {}
    protected_codecs: dict[str, Any] = {}
    allowed_protected = set(policy["derivation"]["allowed_protected_ids"])
    for owner in contract["owners"]:
        p_index, instance_id = owner["p_index"], owner["instance_id"]
        protected, codec = decode_u16_png_exact(protected_paths[p_index])
        if protected.shape != expected_shape:
            raise PackageDerivationError("package_protected_resolution_mismatch", p_index)
        observed = set(int(value) for value in np.unique(protected))
        target = instance == instance_id
        other = visible & ~target
        if not observed <= allowed_protected:
            raise PackageDerivationError(
                "package_protected_namespace_invalid", f"{p_index}:{sorted(observed)}"
            )
        if not np.array_equal(protected == 50, other) or np.any(target & (protected != 0)):
            raise PackageDerivationError("package_protected_other_person_invalid", p_index)
        protected_arrays[p_index] = protected
        protected_codecs[p_index] = codec
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target_root = root / contract["contract_id"]
    temporary = Path(tempfile.mkdtemp(prefix=f".{contract['contract_id']}.", dir=root))
    report: dict[str, Any]
    try:
        report = _materialize_scene(
            temporary,
            contract,
            source_paths,
            instance,
            part,
            material,
            protected_arrays,
            policy,
            source_codecs={
                "rgb": rgb_codec,
                "instance": instance_codec,
                "part": part_codec,
                "material": material_codec,
                "protected_by_p_index": protected_codecs,
            },
        )
        if target_root.exists():
            if _tree_hashes(target_root) != _tree_hashes(temporary):
                raise PackageDerivationError("package_publication_conflict", str(target_root))
            shutil.rmtree(temporary)
            existing_report = json.loads(
                (target_root / "decoder_report.json").read_text(encoding="utf-8")
            )
            require_valid_document(existing_report, "daz_package_derivation_report")
            return existing_report, target_root, False
        os.replace(temporary, target_root)
        return report, target_root, True
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _materialize_scene(
    root: Path,
    contract: Mapping[str, Any],
    source_paths: Mapping[str, Path],
    instance: np.ndarray,
    part: np.ndarray,
    material: np.ndarray,
    protected_arrays: Mapping[str, np.ndarray],
    policy: Mapping[str, Any],
    *,
    source_codecs: Mapping[str, Any],
) -> dict[str, Any]:
    packages_root = root / "packages"
    packages_root.mkdir(parents=True)
    visible = instance > 0
    target_masks: list[np.ndarray] = []
    package_records: list[dict[str, Any]] = []
    shared_rgb_bytes = Path(source_paths["rgb"]).read_bytes()
    for owner in contract["owners"]:
        p_index, instance_id = owner["p_index"], owner["instance_id"]
        package_root = packages_root / p_index
        package_root.mkdir()
        target = instance == instance_id
        other = visible & ~target
        target_masks.append(target)
        target_part = np.where(target, part, 0).astype(np.uint16)
        target_material = np.where(target, material, 0).astype(np.uint16)
        protected = protected_arrays[p_index]
        package_seed = {
            "contract_sha256": contract["contract_sha256"],
            "p_index": p_index,
            "instance_id": instance_id,
        }
        package_digest = _canonical_sha(package_seed)
        package_id = f"dppk_{package_digest[:24]}"
        (package_root / "source_rgb.png").write_bytes(shared_rgb_bytes)
        _write_binary_png(package_root / "full_body.png", target, policy)
        _write_u16_png(package_root / "indexed_part.png", target_part, policy)
        _write_u16_png(package_root / "material.png", target_material, policy)
        _write_binary_png(package_root / "other_person.png", other, policy)
        _write_u16_png(package_root / "protected.png", protected, policy)
        source_manifest = {
            "schema_version": "1.0.0",
            "package_id": package_id,
            "source_origin": "synthetic",
            "annotation_authority": "geometry_render",
            "scene_id": contract["scene_id"],
            "image_id": contract["image_id"],
            "scene_family_id": contract["scene_family_id"],
            "scene_state_sha256": contract["scene_state_sha256"],
            "shared_source_file_sha256s": contract["source_file_sha256s"],
        }
        instance_manifest = {
            "schema_version": "1.0.0",
            "package_id": package_id,
            "p_index": p_index,
            "instance_id": instance_id,
            "prominence_order": instance_id - 1,
            "target_pixels": int(np.count_nonzero(target)),
            "other_person_pixels": int(np.count_nonzero(other)),
            "resolution": contract["resolution"],
            "derivation": "vectorized_from_shared_instance_map",
        }
        lineage = {
            "schema_version": "1.0.0",
            "package_id": package_id,
            "contract_id": contract["contract_id"],
            "contract_sha256": contract["contract_sha256"],
            "plan_id": contract["plan_id"],
            "plan_sha256": contract["plan_sha256"],
            "ontology_version": contract["ontology_version"],
            "ontology_snapshot_sha256": contract["ontology_snapshot_sha256"],
            "authority_report_sha256s": contract["authority_report_sha256s"],
            **contract["truth_contract"],
            "visible_only": True,
            "amodal_included": False,
            "rerendered": False,
        }
        qa = {
            "schema_version": "1.0.0",
            "package_id": package_id,
            "passed": True,
            "checks": {
                "target_nonempty": True,
                "part_mask_exact": bool(np.array_equal(target_part, np.where(target, part, 0))),
                "material_mask_exact": bool(
                    np.array_equal(target_material, np.where(target, material, 0))
                ),
                "other_person_exact": bool(np.array_equal(other, visible & ~target)),
                "protected_other_person_exact": bool(np.array_equal(protected == 50, other)),
                "shared_rgb_hash_exact": _file_sha256(package_root / "source_rgb.png")
                == contract["source_file_sha256s"]["rgb"],
            },
        }
        _write_json(package_root / "source_manifest.json", source_manifest)
        _write_json(package_root / "instance_manifest.json", instance_manifest)
        _write_json(package_root / "synthetic_lineage.json", lineage)
        _write_json(package_root / "qa_report.json", qa)
        non_hash_files = [
            name for name in policy["required_package_files"] if name != "hashes.json"
        ]
        non_hash_file_hashes = {name: _file_sha256(package_root / name) for name in non_hash_files}
        package_tree_sha256 = _canonical_sha(non_hash_file_hashes)
        _write_json(
            package_root / "hashes.json",
            {
                "schema_version": "1.0.0",
                "package_id": package_id,
                "files": non_hash_file_hashes,
                "package_tree_sha256": package_tree_sha256,
            },
        )
        all_file_hashes = {
            name: _file_sha256(package_root / name) for name in policy["required_package_files"]
        }
        package_records.append(
            {
                "p_index": p_index,
                "instance_id": instance_id,
                "package_id": package_id,
                "relative_root": f"packages/{p_index}",
                "target_pixels": int(np.count_nonzero(target)),
                "other_person_pixels": int(np.count_nonzero(other)),
                "file_hashes": all_file_hashes,
                "package_tree_sha256": package_tree_sha256,
            }
        )
    target_stack = np.stack(target_masks)
    if np.any(np.sum(target_stack, axis=0) > 1) or not np.array_equal(
        np.any(target_stack, axis=0), visible
    ):
        raise PackageDerivationError("package_target_partition_invalid", contract["scene_id"])
    scene_manifest = {
        "schema_version": "1.0.0",
        "contract_id": contract["contract_id"],
        "contract_sha256": contract["contract_sha256"],
        "scene_id": contract["scene_id"],
        "image_id": contract["image_id"],
        "scene_family_id": contract["scene_family_id"],
        "scene_state_sha256": contract["scene_state_sha256"],
        "shared_rgb_sha256": contract["source_file_sha256s"]["rgb"],
        "packages": [
            {
                "p_index": record["p_index"],
                "instance_id": record["instance_id"],
                "package_id": record["package_id"],
                "relative_root": record["relative_root"],
            }
            for record in package_records
        ],
    }
    _write_json(root / "scene_manifest.json", scene_manifest)
    invariants = {
        "all_pixels_vectorized": True,
        "target_masks_pairwise_disjoint": True,
        "target_union_equals_visible_instance": True,
        "per_person_part_mask_exact": True,
        "per_person_material_mask_exact": True,
        "other_person_complements_exact": True,
        "protected_other_person_exact": True,
        "shared_rgb_hash_identical": True,
        "no_rerender": True,
        "forbidden_human_fields_absent": True,
    }
    content = {
        "contract_id": contract["contract_id"],
        "contract_sha256": contract["contract_sha256"],
        "scene_id": contract["scene_id"],
        "image_id": contract["image_id"],
        "scene_family_id": contract["scene_family_id"],
        "source_file_sha256s": contract["source_file_sha256s"],
        "source_codecs": source_codecs,
        "packages": package_records,
        "invariants": invariants,
        "summary": {
            "passed": True,
            "package_count": len(package_records),
            "visible_person_pixels": int(np.count_nonzero(visible)),
        },
    }
    digest = _canonical_sha(content)
    report = {
        "schema_version": "1.0.0",
        "report_id": f"dpdr_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    forbidden = set(policy["forbidden_human_fields"])
    emitted_json_documents = [
        json.loads(path.read_text(encoding="utf-8")) for path in root.rglob("*.json")
    ]
    if _contains_forbidden_key([*emitted_json_documents, report], forbidden):
        raise PackageDerivationError("package_forbidden_human_field", contract["scene_id"])
    require_valid_document(report, "daz_package_derivation_report")
    _write_json(root / "decoder_report.json", report)
    return report


def _verify_source_files(
    contract: Mapping[str, Any],
    source_paths: Mapping[str, Path],
    protected_paths: Mapping[str, Path],
) -> None:
    for role, path in source_paths.items():
        if (
            _file_sha256(path) != contract["source_file_sha256s"][role]
            or Path(path).stat().st_size != contract["source_file_bytes"][role]
        ):
            raise PackageDerivationError("package_source_file_mismatch", role)
    for p_index, path in protected_paths.items():
        if (
            _file_sha256(path) != contract["source_file_sha256s"]["protected_by_p_index"][p_index]
            or Path(path).stat().st_size
            != contract["source_file_bytes"]["protected_by_p_index"][p_index]
        ):
            raise PackageDerivationError("package_source_file_mismatch", p_index)


def _decode_rgb_png(path: Path, resolution: Sequence[int]) -> dict[str, Any]:
    payload = Path(path).read_bytes()
    if payload[:8] != b"\x89PNG\r\n\x1a\n":
        raise PackageDerivationError("package_rgb_png_invalid", str(path))
    with Image.open(path) as image:
        image.load()
        if image.format != "PNG" or image.mode != "RGB" or list(image.size) != list(resolution):
            raise PackageDerivationError(
                "package_rgb_codec_invalid", str((image.format, image.mode, image.size))
            )
        return {
            "format": "PNG",
            "mode": "RGB",
            "resolution": list(image.size),
            "bytes": len(payload),
        }


def _write_binary_png(path: Path, mask: np.ndarray, policy: Mapping[str, Any]) -> None:
    array = np.where(
        mask,
        policy["derivation"]["binary_foreground_value"],
        policy["derivation"]["binary_background_value"],
    ).astype(np.uint8)
    Image.fromarray(array).save(
        path,
        format="PNG",
        compress_level=policy["derivation"]["output_png_compress_level"],
        optimize=False,
    )
    with Image.open(path) as image:
        decoded = np.asarray(image)
    if not np.array_equal(decoded, array):
        raise PackageDerivationError("package_binary_roundtrip_mismatch", str(path))


def _write_u16_png(path: Path, array: np.ndarray, policy: Mapping[str, Any]) -> None:
    Image.fromarray(array.astype(np.uint16)).save(
        path,
        format="PNG",
        compress_level=policy["derivation"]["output_png_compress_level"],
        optimize=False,
    )
    decoded, _codec = decode_u16_png_exact(path)
    if not np.array_equal(decoded, array):
        raise PackageDerivationError("package_u16_roundtrip_mismatch", str(path))


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _file_sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _contains_forbidden_key(document: Any, forbidden: set[str]) -> bool:
    if isinstance(document, Mapping):
        return bool(set(document) & forbidden) or any(
            _contains_forbidden_key(value, forbidden) for value in document.values()
        )
    if isinstance(document, list):
        return any(_contains_forbidden_key(value, forbidden) for value in document)
    return False


def _verify_hashed_document(
    document: Mapping[str, Any], id_field: str, hash_field: str, prefix: str
) -> None:
    content = {
        key: value
        for key, value in document.items()
        if key not in {"schema_version", id_field, hash_field}
    }
    digest = _canonical_sha(content)
    if document.get(hash_field) != digest or document.get(id_field) != f"{prefix}_{digest[:24]}":
        raise PackageDerivationError("package_document_hash_invalid", str(document.get(id_field)))


def _canonical_sha(document: Any) -> str:
    try:
        payload = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PackageDerivationError("package_noncanonical_value", str(exc)) from exc
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _identifier(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and value[0].isalnum()
        and all(character.isalnum() or character in "._-" for character in value)
    )
