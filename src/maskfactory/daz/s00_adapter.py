"""Accepted DAZ scene to immutable MaskFactory synthetic S00 package adapter."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml
from PIL import Image

from ..synthetic_manifest import SYNTHETIC_SCHEMA_VERSION, build_synthetic_manifest
from ..validation import require_valid_document
from .acceptance_certificate import verify_acceptance_certificate
from .mapping import build_v1_ontology_snapshot
from .render import decode_u16_png_exact


class S00AdapterError(ValueError):
    """An adapter policy, accepted input, source package, or publication is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_s00_adapter_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_s00_adapter_policy(document)
    return document


def validate_s00_adapter_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "active_ontology",
        "body_parts_v2_active",
        "training_contract",
        "required_source_package_files",
        "file_roles",
        "source_registration",
        "publication",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise S00AdapterError("adapter_policy_fields_invalid", str(policy))
    required_files = [
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
    ]
    if (
        policy["schema_version"] != "1.0.0"
        or policy["policy_version"] != "1.0.0"
        or policy["active_ontology"] != "body_parts_v1"
        or policy["body_parts_v2_active"] is not False
        or policy["required_source_package_files"] != required_files
    ):
        raise S00AdapterError("adapter_policy_identity_invalid", str(policy))
    expected_roles = {
        "source_rgb": "source_rgb.png",
        "full_body": "full_body.png",
        "indexed_part": "indexed_part.png",
        "material": "material.png",
        "other_person": "other_person.png",
        "protected": "protected.png",
        "source_manifest": "source_manifest.json",
        "instance_manifest": "instance_manifest.json",
        "synthetic_lineage": "synthetic_lineage.json",
        "qa_report": "qa_report.json",
        "hashes": "hashes.json",
    }
    if policy["file_roles"] != expected_roles:
        raise S00AdapterError("adapter_policy_file_roles_invalid", str(policy))
    if policy["training_contract"] != {
        "truth_tier": "weighted_pseudo_label",
        "truth_partition": "train",
        "train_eligible": True,
        "evaluation_eligible": False,
        "training_loss_weight": 0.2,
        "source_attributes": ["synthetic_geometry_exact", "visible_pixel_truth"],
    }:
        raise S00AdapterError("adapter_policy_training_invalid", str(policy))
    if policy["source_registration"] != {
        "source_origin": "synthetic",
        "adult_construction_required": True,
        "bypass_real_image_mask_provider_voting": True,
        "bypass_package_verification": False,
        "split_group_field": "scene_family_id",
    }:
        raise S00AdapterError("adapter_policy_registration_invalid", str(policy))
    if policy["publication"] != {
        "immutable": True,
        "atomic_scene_directory": True,
        "source_packages_read_only": True,
        "rerender_forbidden": True,
    }:
        raise S00AdapterError("adapter_policy_publication_invalid", str(policy))


def adapt_accepted_scene(
    metadata: Mapping[str, Any],
    certificate: Mapping[str, Any],
    validation_report: Mapping[str, Any],
    semantic_replay_report: Mapping[str, Any],
    package_contract: Mapping[str, Any],
    package_report: Mapping[str, Any],
    *,
    repair_history: Mapping[str, Any] | None,
    post_repair_reports: Mapping[str, Mapping[str, Any]],
    source_scene_root: Path,
    output_root: Path,
    policy: Mapping[str, Any],
    acceptance_policy: Mapping[str, Any],
    repair_policy: Mapping[str, Any],
    registry: Mapping[str, Any],
    ontology_source: Path,
) -> tuple[dict[str, Any], Path, bool]:
    """Replay all authorities and atomically materialize one intake-ready scene."""

    validate_s00_adapter_policy(policy)
    _validate_metadata(metadata, package_contract)
    replay = verify_acceptance_certificate(
        certificate,
        validation_report,
        semantic_replay_report,
        package_contract,
        package_report,
        repair_history=repair_history,
        post_repair_reports=post_repair_reports,
        policy=acceptance_policy,
        repair_policy=repair_policy,
        registry=registry,
    )
    if replay["accepted"] is not True or replay["train_eligible"] is not True:
        raise S00AdapterError("adapter_certificate_not_accepted", str(replay))
    _validate_authority(certificate, package_contract, policy)
    ontology = _load_ontology_authority(package_contract, policy, ontology_source)
    source_root = Path(source_scene_root).resolve(strict=True)
    source_before = _tree_digest(source_root)
    _verify_scene_root(source_root, package_contract, package_report)
    decoded = _verify_source_packages(source_root, package_contract, package_report, policy)
    temporary_parent = Path(output_root)
    temporary_parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".s00_adapter.", dir=temporary_parent))
    try:
        package_rows = _materialize_packages(
            temporary,
            source_root,
            metadata,
            certificate,
            package_contract,
            package_report,
            decoded,
            policy,
        )
        source_record = {
            "source_origin": "synthetic",
            "image_id": package_contract["image_id"],
            "scene_id": package_contract["scene_id"],
            "group_id": package_contract["scene_family_id"],
            "pristine_rgb_sha256": package_contract["source_file_sha256s"]["rgb"],
            "provider_voting_bypassed": True,
            "package_verification_bypassed": False,
        }
        _write_json(temporary / "synthetic_source_record.json", source_record)
        _write_json(
            temporary / "promoted_person_candidates.json",
            [
                {
                    "p_index": row["p_index"],
                    "instance_id": row["instance_id"],
                    "package_id": row["maskfactory_package_id"],
                    "candidate_bbox": row["candidate_bbox"],
                    "prominence_order": row["instance_id"] - 1,
                }
                for row in package_rows
            ],
        )
        content = {
            "policy_version": policy["policy_version"],
            "policy_sha256": _canonical_sha(policy),
            "certificate_id": certificate["certificate_id"],
            "certificate_sha256": certificate["certificate_sha256"],
            "contract_id": package_contract["contract_id"],
            "contract_sha256": package_contract["contract_sha256"],
            "scene_id": package_contract["scene_id"],
            "image_id": package_contract["image_id"],
            "scene_family_id": package_contract["scene_family_id"],
            "variant_group_id": metadata["variant_group_id"],
            "ontology_version": ontology["ontology_version"],
            "ontology_sha256": ontology["canonical_sha256"],
            "source_record": source_record,
            "packages": package_rows,
            "invariants": {
                "certificate_replayed": True,
                "source_tree_hashes_exact": True,
                "strict_pngs_decoded": True,
                "prominence_mapping_exact": True,
                "targets_pairwise_disjoint": True,
                "target_union_exact": True,
                "other_person_complements_exact": True,
                "protected_other_person_exact": True,
                "indexed_parts_target_scoped": True,
                "materials_target_scoped": True,
                "shared_rgb_exact": True,
                "canonical_ontology_loaded": True,
                "provider_voting_bypassed": True,
                "package_verification_preserved": True,
                "no_rerender": True,
                "source_packages_unchanged": True,
                "human_authority_absent": True,
            },
            "summary": {
                "passed": True,
                "package_count": len(package_rows),
                "visible_person_pixels": int(np.count_nonzero(decoded["visible"])),
                "train_eligible_packages": len(package_rows),
            },
        }
        digest = _canonical_sha(content)
        report = {
            "schema_version": "1.0.0",
            "report_id": f"dsar_{digest[:24]}",
            "report_sha256": digest,
            **content,
        }
        require_valid_document(report, "daz_s00_adapter_report")
        _write_json(temporary / "adapter_report.json", report)
        if _tree_digest(source_root) != source_before:
            raise S00AdapterError("adapter_source_tree_mutated", str(source_root))
        target = temporary_parent / report["report_id"]
        if target.exists():
            if _tree_digest(target) != _tree_digest(temporary):
                raise S00AdapterError("adapter_publication_conflict", str(target))
            shutil.rmtree(temporary)
            return report, target, False
        os.replace(temporary, target)
        return report, target, True
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def validate_s00_adapter_report(report: Mapping[str, Any]) -> None:
    require_valid_document(report, "daz_s00_adapter_report")
    content = {
        key: value
        for key, value in report.items()
        if key not in {"schema_version", "report_id", "report_sha256"}
    }
    digest = _canonical_sha(content)
    if report["report_sha256"] != digest or report["report_id"] != f"dsar_{digest[:24]}":
        raise S00AdapterError("adapter_report_hash_invalid", str(report.get("report_id")))


def _validate_metadata(metadata: Mapping[str, Any], contract: Mapping[str, Any]) -> None:
    fields = {
        "schema_version",
        "variant_group_id",
        "asset_registry_snapshot_sha256",
        "operating_profile_snapshot_sha256",
        "script_bundle_sha256",
        "renderer_snapshot_sha256",
        "asset_snapshot_sha256",
        "pass_profile_id",
        "pass_profile_sha256",
        "person_construction_by_p_index",
    }
    if not isinstance(metadata, Mapping) or set(metadata) != fields:
        raise S00AdapterError("adapter_metadata_fields_invalid", str(metadata))
    hashes = [metadata[field] for field in fields if field.endswith("_sha256")]
    if (
        metadata["schema_version"] != "1.0.0"
        or not _text(metadata["variant_group_id"])
        or not _text(metadata["pass_profile_id"])
        or any(not _sha256(value) for value in hashes)
    ):
        raise S00AdapterError("adapter_metadata_identity_invalid", str(metadata))
    expected = [owner["p_index"] for owner in contract["owners"]]
    constructions = metadata["person_construction_by_p_index"]
    if not isinstance(constructions, Mapping) or list(constructions) != expected:
        raise S00AdapterError("adapter_construction_set_invalid", str(constructions))
    for p_index, construction in constructions.items():
        if (
            not isinstance(construction, Mapping)
            or construction.get("person_id") != p_index
            or construction.get("anatomy_configuration") not in {"adult_male", "adult_female"}
            or construction.get("age_appearance_category")
            not in {"adult_21_29", "adult_30_44", "adult_45_64", "adult_65_plus"}
        ):
            raise S00AdapterError("adapter_adult_construction_invalid", p_index)


def _validate_authority(
    certificate: Mapping[str, Any], contract: Mapping[str, Any], policy: Mapping[str, Any]
) -> None:
    authority = certificate["authority"]
    if (
        authority["ontology_version"] != contract["ontology_version"]
        or authority["ontology_sha256"] != contract["ontology_snapshot_sha256"]
        or authority["package_revision"] != contract["contract_id"]
        or authority["owner"] != "maskfactory"
        or authority["provider_id"] != "daz_exact_geometry"
        or authority["authority_tier"] != "synthetic_exact"
        or certificate["source_lineage_declaration"]["live_mode_b_result"] is not False
        or certificate["use_profile"] != "private_personal_noncommercial"
    ):
        raise S00AdapterError("adapter_authority_invalid", contract["scene_id"])
    if contract["ontology_version"] != policy["active_ontology"]:
        raise S00AdapterError("adapter_ontology_inactive", contract["ontology_version"])


def _load_ontology_authority(
    contract: Mapping[str, Any], policy: Mapping[str, Any], ontology_source: Path
) -> dict[str, Any]:
    if contract["ontology_version"] == "body_parts_v2" and not policy["body_parts_v2_active"]:
        raise S00AdapterError("adapter_v2_not_active", contract["scene_id"])
    if contract["ontology_version"] != "body_parts_v1":
        raise S00AdapterError("adapter_ontology_unsupported", contract["ontology_version"])
    snapshot = build_v1_ontology_snapshot(Path(ontology_source))
    if snapshot["canonical_sha256"] != contract["ontology_snapshot_sha256"]:
        raise S00AdapterError("adapter_ontology_snapshot_mismatch", contract["scene_id"])
    return snapshot


def _verify_scene_root(root: Path, contract: Mapping[str, Any], report: Mapping[str, Any]) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise S00AdapterError("adapter_source_link_forbidden", str(path))
    decoder = _load_json(root / "decoder_report.json")
    scene = _load_json(root / "scene_manifest.json")
    if decoder != report:
        raise S00AdapterError("adapter_decoder_report_mismatch", str(root))
    expected_scene = {
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
                "p_index": row["p_index"],
                "instance_id": row["instance_id"],
                "package_id": row["package_id"],
                "relative_root": row["relative_root"],
            }
            for row in report["packages"]
        ],
    }
    if scene != expected_scene:
        raise S00AdapterError("adapter_scene_manifest_mismatch", str(root))


def _verify_source_packages(
    root: Path,
    contract: Mapping[str, Any],
    report: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    targets: dict[str, np.ndarray] = {}
    others: dict[str, np.ndarray] = {}
    parts: dict[str, np.ndarray] = {}
    materials: dict[str, np.ndarray] = {}
    protected: dict[str, np.ndarray] = {}
    rgbs: dict[str, str] = {}
    rows = {row["p_index"]: row for row in report["packages"]}
    if list(rows) != [owner["p_index"] for owner in contract["owners"]]:
        raise S00AdapterError("adapter_package_order_invalid", contract["scene_id"])
    required = policy["required_source_package_files"]
    for owner in contract["owners"]:
        p_index, instance_id = owner["p_index"], owner["instance_id"]
        row = rows[p_index]
        package_root = root / row["relative_root"]
        actual_names = sorted(path.name for path in package_root.iterdir() if path.is_file())
        if actual_names != sorted(required) or any(
            path.is_dir() for path in package_root.iterdir()
        ):
            raise S00AdapterError("adapter_package_file_set_invalid", p_index)
        actual_hashes = {name: _file_sha(package_root / name) for name in required}
        if actual_hashes != row["file_hashes"]:
            raise S00AdapterError("adapter_package_file_hash_invalid", p_index)
        hashes = _load_json(package_root / "hashes.json")
        expected_non_hash = {
            name: actual_hashes[name] for name in required if name != "hashes.json"
        }
        if (
            hashes.get("package_id") != row["package_id"]
            or hashes.get("files") != expected_non_hash
            or hashes.get("package_tree_sha256") != row["package_tree_sha256"]
            or _canonical_sha(expected_non_hash) != row["package_tree_sha256"]
        ):
            raise S00AdapterError("adapter_package_tree_hash_invalid", p_index)
        _verify_package_sidecars(package_root, contract, row, owner)
        targets[p_index] = _binary_png(package_root / "full_body.png")
        others[p_index] = _binary_png(package_root / "other_person.png")
        parts[p_index], _codec = decode_u16_png_exact(package_root / "indexed_part.png")
        materials[p_index], _codec = decode_u16_png_exact(package_root / "material.png")
        protected[p_index], _codec = decode_u16_png_exact(package_root / "protected.png")
        rgbs[p_index] = _rgb_png_hash(package_root / "source_rgb.png")
        if (
            row["instance_id"] != instance_id
            or int(np.count_nonzero(targets[p_index])) != row["target_pixels"]
            or int(np.count_nonzero(others[p_index])) != row["other_person_pixels"]
            or not np.array_equal(parts[p_index] > 0, targets[p_index])
            or not np.array_equal(materials[p_index] > 0, targets[p_index])
            or not np.array_equal(protected[p_index] == 50, others[p_index])
            or np.any(targets[p_index] & others[p_index])
        ):
            raise S00AdapterError("adapter_package_semantics_invalid", p_index)
    stack = np.stack([targets[owner["p_index"]] for owner in contract["owners"]])
    if np.any(stack.sum(axis=0) > 1):
        raise S00AdapterError("adapter_target_overlap", contract["scene_id"])
    visible = stack.any(axis=0)
    for owner in contract["owners"]:
        p_index = owner["p_index"]
        if not np.array_equal(others[p_index], visible & ~targets[p_index]):
            raise S00AdapterError("adapter_other_person_complement_invalid", p_index)
    if (
        len(set(rgbs.values())) != 1
        or next(iter(rgbs.values())) != contract["source_file_sha256s"]["rgb"]
    ):
        raise S00AdapterError("adapter_shared_rgb_invalid", contract["scene_id"])
    return {
        "targets": targets,
        "others": others,
        "parts": parts,
        "materials": materials,
        "protected": protected,
        "visible": visible,
    }


def _verify_package_sidecars(
    root: Path,
    contract: Mapping[str, Any],
    row: Mapping[str, Any],
    owner: Mapping[str, Any],
) -> None:
    source = _load_json(root / "source_manifest.json")
    instance = _load_json(root / "instance_manifest.json")
    lineage = _load_json(root / "synthetic_lineage.json")
    qa = _load_json(root / "qa_report.json")
    if (
        source.get("package_id") != row["package_id"]
        or source.get("scene_id") != contract["scene_id"]
        or source.get("scene_state_sha256") != contract["scene_state_sha256"]
        or instance.get("p_index") != owner["p_index"]
        or instance.get("instance_id") != owner["instance_id"]
        or instance.get("prominence_order") != owner["instance_id"] - 1
        or lineage.get("contract_id") != contract["contract_id"]
        or lineage.get("contract_sha256") != contract["contract_sha256"]
        or lineage.get("counts_as_human_anchor_gold") is not False
        or lineage.get("counts_as_autonomous_certified_gold") is not False
        or qa.get("passed") is not True
        or not all(qa.get("checks", {}).values())
    ):
        raise S00AdapterError("adapter_package_sidecar_invalid", owner["p_index"])


def _materialize_packages(
    root: Path,
    source_scene_root: Path,
    metadata: Mapping[str, Any],
    certificate: Mapping[str, Any],
    contract: Mapping[str, Any],
    report: Mapping[str, Any],
    decoded: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    output_packages = root / "packages"
    output_packages.mkdir()
    rows = {row["p_index"]: row for row in report["packages"]}
    package_rows = []
    for owner in contract["owners"]:
        p_index, instance_id = owner["p_index"], owner["instance_id"]
        source_row = rows[p_index]
        source_package = source_scene_root / source_row["relative_root"]
        output_package = output_packages / p_index
        output_package.mkdir()
        for name in policy["required_source_package_files"]:
            shutil.copyfile(source_package / name, output_package / name)

        package_identity = {
            "certificate_sha256": certificate["certificate_sha256"],
            "source_package_id": source_row["package_id"],
            "variant_group_id": metadata["variant_group_id"],
            "p_index": p_index,
        }
        package_id = f"mf_daz_{_canonical_sha(package_identity)[:24]}"
        file_entries = {
            role: {
                "path": name,
                "sha256": source_row["file_hashes"][name],
            }
            for role, name in policy["file_roles"].items()
        }
        training = policy["training_contract"]
        bindings = certificate["bindings"]
        authority = certificate["authority"]
        draft = {
            "schema_version": SYNTHETIC_SCHEMA_VERSION,
            "package_id": package_id,
            "image_id": contract["image_id"],
            "scene_id": contract["scene_id"],
            "scene_family_id": contract["scene_family_id"],
            "variant_group_id": metadata["variant_group_id"],
            "promoted_person_id": p_index,
            "source_origin": "synthetic",
            "annotation_authority": "geometry_render",
            "truth_tier": training["truth_tier"],
            "truth_partition": training["truth_partition"],
            "train_eligible": training["train_eligible"],
            "evaluation_eligible": training["evaluation_eligible"],
            "training_loss_weight": training["training_loss_weight"],
            "source_attributes": training["source_attributes"],
            "ontology": {
                "name": contract["ontology_version"],
                "snapshot_sha256": contract["ontology_snapshot_sha256"],
            },
            "mask_authority": {
                "provider_id": authority["provider_id"],
                "authority_tier": authority["authority_tier"],
                "ontology_version": authority["ontology_version"],
                "ontology_sha256": authority["ontology_sha256"],
                "owner": authority["owner"],
                "package_revision": authority["package_revision"],
                "certificate_id": certificate["certificate_id"],
                "certificate_sha256": certificate["certificate_sha256"],
                "certificate_scope": authority["certificate_scope"],
                "transform_chain_sha256": authority["transform_chain_sha256"],
                "access_mode": "mode_a_approved_package",
            },
            "person_construction": dict(metadata["person_construction_by_p_index"][p_index]),
            "synthetic_lineage": {
                "generator": "daz_studio",
                "scene_id": contract["scene_id"],
                "scene_family_id": contract["scene_family_id"],
                "variant_group_id": metadata["variant_group_id"],
                "scene_state_sha256": contract["scene_state_sha256"],
                "recipe_sha256": bindings["recipe_sha256"],
                "asset_registry_snapshot_sha256": metadata["asset_registry_snapshot_sha256"],
                "operating_profile_snapshot_sha256": metadata["operating_profile_snapshot_sha256"],
                "registry_snapshot_sha256": bindings["registry_sha256"],
                "runtime_snapshot_sha256": bindings["runtime_sha256"],
                "script_bundle_sha256": metadata["script_bundle_sha256"],
                "renderer_snapshot_sha256": metadata["renderer_snapshot_sha256"],
                "asset_snapshot_sha256": metadata["asset_snapshot_sha256"],
                "mapping_set_sha256": bindings["mapping_set_sha256"],
                "mapping_ontology_version": contract["ontology_version"],
                "pass_profile_id": metadata["pass_profile_id"],
                "pass_profile_sha256": metadata["pass_profile_sha256"],
                "scene_certificate_id": certificate["certificate_id"],
                "scene_certificate_sha256": certificate["certificate_sha256"],
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
            "files": file_entries,
        }
        manifest = build_synthetic_manifest(draft)
        _write_json(output_package / "manifest.json", manifest)
        package_rows.append(
            {
                "p_index": p_index,
                "instance_id": instance_id,
                "source_package_id": source_row["package_id"],
                "maskfactory_package_id": package_id,
                "manifest_sha256": manifest["package_sha256"],
                "source_package_tree_sha256": source_row["package_tree_sha256"],
                "output_tree_sha256": _tree_digest(output_package),
                "target_pixels": source_row["target_pixels"],
                "other_person_pixels": source_row["other_person_pixels"],
                "candidate_bbox": _bbox(decoded["targets"][p_index]),
                "relative_root": f"packages/{p_index}",
            }
        )
    return package_rows


def _binary_png(path: Path) -> np.ndarray:
    try:
        with Image.open(path) as image:
            if image.format != "PNG" or image.mode != "L":
                raise S00AdapterError("adapter_binary_png_codec_invalid", str(path))
            array = np.asarray(image)
    except (OSError, ValueError) as exc:
        raise S00AdapterError("adapter_binary_png_decode_failed", str(path)) from exc
    values = set(int(value) for value in np.unique(array))
    if not values <= {0, 255}:
        raise S00AdapterError("adapter_binary_png_values_invalid", f"{path}:{sorted(values)}")
    return array == 255


def _rgb_png_hash(path: Path) -> str:
    try:
        with Image.open(path) as image:
            if image.format != "PNG" or image.mode not in {"RGB", "RGBA"}:
                raise S00AdapterError("adapter_rgb_png_codec_invalid", str(path))
            image.load()
    except (OSError, ValueError) as exc:
        raise S00AdapterError("adapter_rgb_png_decode_failed", str(path)) from exc
    return _file_sha(path)


def _bbox(mask: np.ndarray) -> list[int]:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise S00AdapterError("adapter_target_empty", "mask")
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise S00AdapterError("adapter_json_invalid", str(path)) from exc


def _write_json(path: Path, document: Any) -> None:
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _tree_digest(root: Path) -> str:
    records = []
    for path in sorted(Path(root).rglob("*")):
        if path.is_file():
            records.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": _file_sha(path),
                    "bytes": path.stat().st_size,
                }
            )
    if not records:
        raise S00AdapterError("adapter_tree_empty", str(root))
    return _canonical_sha(records)


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha(document: Any) -> str:
    try:
        payload = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise S00AdapterError("adapter_canonical_json_invalid", str(exc)) from exc
    return hashlib.sha256(payload).hexdigest()


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 128
