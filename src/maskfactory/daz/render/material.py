"""Exact canonical MATERIAL/protected maps and cross-map orthogonality."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml

from ...validation import require_valid_document
from .instance import decode_u16_png_exact


class MaterialProtectedContractError(ValueError):
    """A MATERIAL/protected policy, contract, execution, or map is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_material_protected_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_material_protected_policy(document)
    return document


def validate_material_protected_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "active_ontology_version",
        "profile_outputs",
        "codec",
        "protected_namespace",
        "material_relations",
        "orthogonality",
        "freeze",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise MaterialProtectedContractError("material_policy_fields_invalid", str(policy))
    if (
        policy["schema_version"] != "1.0.0"
        or policy["policy_version"] != "1.0.0"
        or policy["active_ontology_version"] != "body_parts_v1"
    ):
        raise MaterialProtectedContractError("material_policy_identity_invalid", str(policy))
    if policy["profile_outputs"] != {
        "engineering_minimal": ["material"],
        "training_standard": ["material", "protected"],
        "training_relationship": ["material", "protected"],
        "diagnostic_full": ["material", "protected"],
    }:
        raise MaterialProtectedContractError(
            "material_policy_profiles_invalid", str(policy["profile_outputs"])
        )
    if policy["codec"] != {
        "encoding": "uint16_png",
        "background_value": 0,
        "decode_filter": "nearest_neighbor_exact",
        "forbidden_effects": [
            "jpeg",
            "palette_quantization",
            "color_management",
            "tone_mapping",
            "denoising",
            "bloom",
            "motion_blur",
            "depth_of_field",
            "lossy_resize",
        ],
    }:
        raise MaterialProtectedContractError("material_policy_codec_invalid", str(policy["codec"]))
    if policy["protected_namespace"] != {
        "other_person": 50,
        "occluding_object": 51,
        "support_surface": 52,
        "accessory_or_prop": 53,
    }:
        raise MaterialProtectedContractError(
            "material_policy_protected_invalid", str(policy["protected_namespace"])
        )
    if policy["material_relations"] != {
        "other_person_material": 13,
        "object_material": 14,
        "accessory_material": 9,
        "protected_allowed_material_ids": {
            50: [13],
            51: [14],
            52: [14],
            53: [9, 14],
        },
    }:
        raise MaterialProtectedContractError(
            "material_policy_relations_invalid", str(policy["material_relations"])
        )
    if policy["orthogonality"] != {
        "background_all_zero": True,
        "every_instance_pixel_has_material": True,
        "every_material_pixel_has_instance_or_protected": True,
        "protected_equals_protected_part": True,
        "unprotected_person_part_excludes_protected_ids": True,
        "other_person_instance_requires_protected_other_person": True,
        "target_person_cannot_be_other_person": True,
        "special_material_requires_matching_protected": True,
        "expected_material_ids_nonempty": True,
    }:
        raise MaterialProtectedContractError(
            "material_policy_orthogonality_invalid", str(policy["orthogonality"])
        )
    if policy["freeze"] != {
        "exact_scene_state_before_sidecar_after_restore_terminal": True,
        "exact_plan_contract_ontology_mapping_sidecars": True,
        "repeated_material_and_protected_hashes_required": True,
    }:
        raise MaterialProtectedContractError(
            "material_policy_freeze_invalid", str(policy["freeze"])
        )


def build_material_protected_contract(
    part_contract: Mapping[str, Any],
    pass_plan: Mapping[str, Any],
    ontology_snapshot: Mapping[str, Any],
    *,
    target_p_index: str,
    expected_material_ids: list[int],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Seal MATERIAL/protected outputs to PART, ontology, mapping, and target ownership."""

    validate_material_protected_policy(policy)
    require_valid_document(part_contract, "daz_part_pass_contract")
    _verify_hashed_document(part_contract, "contract_id", "contract_sha256", "dppc")
    require_valid_document(pass_plan, "daz_render_pass_plan")
    _verify_hashed_document(pass_plan, "plan_id", "plan_sha256", "dcrp")
    require_valid_document(ontology_snapshot, "daz_ontology_snapshot")
    _verify_snapshot(ontology_snapshot)
    if (
        ontology_snapshot["ontology_version"] != policy["active_ontology_version"]
        or ontology_snapshot["snapshot_id"] != part_contract["ontology_snapshot_id"]
        or ontology_snapshot["canonical_sha256"] != part_contract["ontology_snapshot_sha256"]
    ):
        raise MaterialProtectedContractError(
            "material_ontology_lineage_mismatch", str(ontology_snapshot)
        )
    if (
        pass_plan["plan_id"] != part_contract["plan_id"]
        or pass_plan["plan_sha256"] != part_contract["plan_sha256"]
        or pass_plan["scene_id"] != part_contract["scene_id"]
        or pass_plan["scene_state_sha256"] != part_contract["scene_state_sha256"]
    ):
        raise MaterialProtectedContractError("material_plan_lineage_mismatch", pass_plan["plan_id"])
    required_roles = policy["profile_outputs"].get(pass_plan["profile"])
    if required_roles is None:
        raise MaterialProtectedContractError("material_profile_ineligible", pass_plan["profile"])
    outputs_by_role = {row["role"]: row for row in pass_plan["outputs"]}
    if any(role not in outputs_by_role for role in required_roles):
        raise MaterialProtectedContractError("material_profile_output_missing", str(required_roles))
    for role in required_roles:
        if outputs_by_role[role]["encoding"] != "uint16_png":
            raise MaterialProtectedContractError("material_output_encoding_invalid", role)
    material_labels = ontology_snapshot["material_labels"]
    active_material_ids = [row["id"] for row in material_labels if row["enabled"]]
    if active_material_ids != list(range(16)):
        raise MaterialProtectedContractError(
            "material_ontology_ids_invalid", str(active_material_ids)
        )
    protected_names = ontology_snapshot["protected_classes"]
    protected = policy["protected_namespace"]
    if protected_names != list(protected) or any(
        ontology_snapshot["part_labels"][protected[name]]["name"] != name for name in protected
    ):
        raise MaterialProtectedContractError(
            "material_protected_namespace_mismatch", str(protected_names)
        )
    if (
        not isinstance(expected_material_ids, list)
        or not expected_material_ids
        or expected_material_ids != sorted(set(expected_material_ids))
        or 0 in expected_material_ids
        or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value not in active_material_ids
            for value in expected_material_ids
        )
    ):
        raise MaterialProtectedContractError(
            "material_expected_ids_invalid", str(expected_material_ids)
        )
    if target_p_index not in {"p0", "p1", "p2", "p3"}:
        raise MaterialProtectedContractError("material_target_p_index_invalid", target_p_index)
    target_instance_id = int(target_p_index[1:]) + 1
    outputs = {
        role: {
            "role": role,
            "encoding": "uint16_png",
            "resolution": outputs_by_role[role]["resolution"],
            "crop": outputs_by_role[role]["crop"],
            "background_value": 0,
            "decode_filter": "nearest_neighbor_exact",
        }
        for role in required_roles
    }
    content = {
        "scene_id": part_contract["scene_id"],
        "scene_state_sha256": part_contract["scene_state_sha256"],
        "plan_id": pass_plan["plan_id"],
        "plan_sha256": pass_plan["plan_sha256"],
        "part_contract_id": part_contract["contract_id"],
        "part_contract_sha256": part_contract["contract_sha256"],
        "ontology_snapshot_id": ontology_snapshot["snapshot_id"],
        "ontology_snapshot_sha256": ontology_snapshot["canonical_sha256"],
        "ontology_version": ontology_snapshot["ontology_version"],
        "mapping_sha256": part_contract["mapping_sha256"],
        "mapping_set_sha256": part_contract["mapping_set_sha256"],
        "policy_sha256": _canonical_sha(policy),
        "policy_version": policy["policy_version"],
        "profile": pass_plan["profile"],
        "target_p_index": target_p_index,
        "target_instance_id": target_instance_id,
        "active_material_ids": active_material_ids,
        "material_labels": [{"id": row["id"], "name": row["name"]} for row in material_labels],
        "protected_namespace": protected,
        "protected_allowed_material_ids": {
            str(protected_id): allowed_material_ids
            for protected_id, allowed_material_ids in policy["material_relations"][
                "protected_allowed_material_ids"
            ].items()
        },
        "expected_material_ids": expected_material_ids,
        "outputs": outputs,
    }
    digest = _canonical_sha(content)
    document = {
        "schema_version": "1.0.0",
        "contract_id": f"dmpc_{digest[:24]}",
        "contract_sha256": digest,
        **content,
    }
    require_valid_document(document, "daz_material_protected_contract")
    return document


def evaluate_material_protected_passes(
    contract: Mapping[str, Any],
    execution: Mapping[str, Any],
    *,
    material_path: Path,
    protected_path: Path | None,
    part_path: Path,
    instance_path: Path,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate exact MATERIAL/protected rasters and full cross-map ownership equations."""

    validate_material_protected_policy(policy)
    require_valid_document(contract, "daz_material_protected_contract")
    _verify_hashed_document(contract, "contract_id", "contract_sha256", "dmpc")
    _validate_execution(execution, protected_required="protected" in contract["outputs"])
    if any(
        execution[field] != contract[field]
        for field in ("scene_id", "contract_id", "contract_sha256", "plan_id", "plan_sha256")
    ):
        raise MaterialProtectedContractError(
            "material_execution_lineage_mismatch", execution["contract_id"]
        )
    material, material_codec = decode_u16_png_exact(material_path)
    part, part_codec = decode_u16_png_exact(part_path)
    instance, instance_codec = decode_u16_png_exact(instance_path)
    if protected_path is None:
        protected = np.zeros_like(material)
        protected_codec = None
        protected_bytes = b""
        protected_sha = None
    else:
        protected, protected_codec = decode_u16_png_exact(protected_path)
        protected_bytes = Path(protected_path).read_bytes()
        protected_sha = hashlib.sha256(protected_bytes).hexdigest()
    material_bytes = Path(material_path).read_bytes()
    part_bytes = Path(part_path).read_bytes()
    instance_bytes = Path(instance_path).read_bytes()
    hashes = {
        "material": hashlib.sha256(material_bytes).hexdigest(),
        "protected": protected_sha,
        "part": hashlib.sha256(part_bytes).hexdigest(),
        "instance": hashlib.sha256(instance_bytes).hexdigest(),
    }
    findings: list[dict[str, str]] = []
    state = contract["scene_state_sha256"]
    for field in (
        "scene_state_before_sha256",
        "sidecar_scene_state_sha256",
        "scene_state_after_sha256",
        "annotation_restore_scene_state_sha256",
        "terminal_scene_state_sha256",
    ):
        if execution[field] != state:
            _finding(findings, "MATERIAL_SCENE_STATE_MUTATION", f"/{field}", execution[field])
    for field, expected, code in (
        ("sidecar_plan_sha256", contract["plan_sha256"], "MATERIAL_SIDECAR_PLAN_MISMATCH"),
        (
            "sidecar_contract_sha256",
            contract["contract_sha256"],
            "MATERIAL_SIDECAR_CONTRACT_MISMATCH",
        ),
        (
            "sidecar_ontology_snapshot_sha256",
            contract["ontology_snapshot_sha256"],
            "MATERIAL_SIDECAR_ONTOLOGY_MISMATCH",
        ),
        ("sidecar_mapping_sha256", contract["mapping_sha256"], "MATERIAL_SIDECAR_MAPPING_MISMATCH"),
    ):
        if execution[field] != expected:
            _finding(findings, code, f"/{field}", execution[field])
    for role, output_contract in contract["outputs"].items():
        output = execution["outputs"][role]
        for field in ("role", "encoding", "resolution", "crop", "decode_filter"):
            if output[field] != output_contract[field]:
                _finding(
                    findings,
                    "MATERIAL_OUTPUT_CONTRACT_MISMATCH",
                    f"/outputs/{role}/{field}",
                    str(output[field]),
                )
        forbidden = sorted(set(output["effects"]) & set(policy["codec"]["forbidden_effects"]))
        if forbidden:
            _finding(
                findings,
                "MATERIAL_EFFECT_FORBIDDEN",
                f"/outputs/{role}/effects",
                ",".join(forbidden),
            )
        payload = material_bytes if role == "material" else protected_bytes
        if output["file_sha256"] != hashes[role]:
            _finding(
                findings,
                "MATERIAL_FILE_HASH_MISMATCH",
                f"/outputs/{role}/file_sha256",
                output["file_sha256"],
            )
        if output["bytes"] != len(payload) or not payload:
            _finding(
                findings,
                "MATERIAL_BYTE_COUNT_MISMATCH",
                f"/outputs/{role}/bytes",
                str(output["bytes"]),
            )
        if output["completed"] is not True or output["interrupted"] is not False:
            _finding(
                findings,
                "MATERIAL_OUTPUT_INCOMPLETE",
                f"/outputs/{role}/completed",
                str(output),
            )
    for role in ("part", "instance"):
        if execution[f"{role}_file_sha256"] != hashes[role]:
            _finding(
                findings,
                "MATERIAL_AUTHORITY_HASH_MISMATCH",
                f"/{role}_file_sha256",
                execution[f"{role}_file_sha256"],
            )
    shapes = {material.shape, protected.shape, part.shape, instance.shape}
    if len(shapes) != 1:
        _finding(findings, "MATERIAL_RESOLUTION_MISMATCH", "/rasters", str(shapes))
        metrics = _empty_metrics()
        observed_material_ids: list[int] = []
        observed_protected_ids: list[int] = []
    else:
        metrics, observed_material_ids, observed_protected_ids = _orthogonality_metrics(
            material, protected, part, instance, contract
        )
        for key, code in (
            ("visible_without_material_pixels", "MATERIAL_VISIBLE_UNLABELED"),
            ("orphan_material_pixels", "MATERIAL_ORPHAN_PIXEL"),
            ("protected_part_mismatch_pixels", "MATERIAL_PROTECTED_PART_MISMATCH"),
            ("unprotected_person_part_invalid_pixels", "MATERIAL_PERSON_PART_INVALID"),
            ("other_person_protection_mismatch_pixels", "MATERIAL_OTHER_PERSON_MISMATCH"),
            ("target_marked_other_person_pixels", "MATERIAL_TARGET_OTHER_PERSON"),
            ("protected_material_relation_pixels", "MATERIAL_PROTECTED_RELATION_INVALID"),
            ("material_protected_relation_pixels", "MATERIAL_RELATION_PROTECTED_INVALID"),
            ("background_nonzero_pixels", "MATERIAL_BACKGROUND_NONZERO"),
        ):
            if metrics[key]:
                _finding(findings, code, f"/orthogonality/{key}", str(metrics[key]))
        unknown_material = sorted(set(observed_material_ids) - set(contract["active_material_ids"]))
        unknown_protected = sorted(
            set(observed_protected_ids) - {0, *contract["protected_namespace"].values()}
        )
        if unknown_material:
            _finding(
                findings,
                "MATERIAL_ID_UNKNOWN",
                "/observed_material_ids",
                ",".join(map(str, unknown_material)),
            )
        if unknown_protected:
            _finding(
                findings,
                "PROTECTED_ID_UNKNOWN",
                "/observed_protected_ids",
                ",".join(map(str, unknown_protected)),
            )
        missing_expected = sorted(
            set(contract["expected_material_ids"]) - set(observed_material_ids)
        )
        if missing_expected:
            _finding(
                findings,
                "MATERIAL_EXPECTED_ID_EMPTY",
                "/observed_material_ids",
                ",".join(map(str, missing_expected)),
            )
    if execution["repeated_material_file_sha256"] != hashes["material"]:
        _finding(
            findings,
            "MATERIAL_SEMANTIC_REPLAY_MISMATCH",
            "/repeated_material_file_sha256",
            execution["repeated_material_file_sha256"],
        )
    expected_protected_replay = hashes["protected"] if "protected" in contract["outputs"] else None
    if execution["repeated_protected_file_sha256"] != expected_protected_replay:
        _finding(
            findings,
            "PROTECTED_SEMANTIC_REPLAY_MISMATCH",
            "/repeated_protected_file_sha256",
            str(execution["repeated_protected_file_sha256"]),
        )
    findings.sort(key=lambda row: (row["code"], row["path"], row["detail"]))
    content = {
        "scene_id": contract["scene_id"],
        "contract_id": contract["contract_id"],
        "contract_sha256": contract["contract_sha256"],
        "plan_id": contract["plan_id"],
        "plan_sha256": contract["plan_sha256"],
        "scene_state_sha256": state,
        "ontology_snapshot_sha256": contract["ontology_snapshot_sha256"],
        "mapping_sha256": contract["mapping_sha256"],
        "execution_sha256": _canonical_sha(execution),
        "file_hashes": hashes,
        "material_codec": material_codec,
        "protected_codec": protected_codec,
        "part_codec": part_codec,
        "instance_codec": instance_codec,
        "observed_material_ids": observed_material_ids,
        "observed_protected_ids": observed_protected_ids,
        "orthogonality": metrics,
        "findings": findings,
        "summary": {
            "passed": not findings,
            "finding_count": len(findings),
            "failure_codes": sorted({row["code"] for row in findings}),
            "material_id_count": len(contract["active_material_ids"]),
            "protected_required": "protected" in contract["outputs"],
            "scene_state_unchanged": not any("MUTATION" in row["code"] for row in findings),
            "orthogonality_exact": not any(
                row["code"].startswith("MATERIAL_")
                and any(
                    token in row["code"]
                    for token in (
                        "VISIBLE",
                        "ORPHAN",
                        "PART",
                        "PERSON",
                        "TARGET",
                        "RELATION",
                        "BACKGROUND",
                    )
                )
                for row in findings
            ),
        },
    }
    digest = _canonical_sha(content)
    report = {
        "schema_version": "1.0.0",
        "report_id": f"dmpr_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    require_valid_document(report, "daz_material_protected_report")
    return report


def publish_material_protected_document(
    document: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    if "report_id" in document:
        require_valid_document(document, "daz_material_protected_report")
        name = document["report_id"]
    elif "contract_id" in document:
        require_valid_document(document, "daz_material_protected_contract")
        name = document["contract_id"]
    else:
        raise MaterialProtectedContractError("material_publication_document_unknown", str(document))
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{name}.json"
    payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise MaterialProtectedContractError("material_publication_conflict", str(target))
        return target, False
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=root
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target, True


def _orthogonality_metrics(
    material: np.ndarray,
    protected: np.ndarray,
    part: np.ndarray,
    instance: np.ndarray,
    contract: Mapping[str, Any],
) -> tuple[dict[str, int], list[int], list[int]]:
    protected_ids = set(contract["protected_namespace"].values())
    target = contract["target_instance_id"]
    visible_authority = (instance > 0) | (protected > 0) | (part > 0)
    metrics = {
        "visible_without_material_pixels": int(
            np.count_nonzero(visible_authority & (material == 0))
        ),
        "orphan_material_pixels": int(
            np.count_nonzero((material > 0) & (instance == 0) & (protected == 0))
        ),
        "protected_part_mismatch_pixels": int(
            np.count_nonzero(
                ((protected > 0) | np.isin(part, tuple(protected_ids))) & (part != protected)
            )
        ),
        "unprotected_person_part_invalid_pixels": int(
            np.count_nonzero(
                (instance > 0)
                & (protected == 0)
                & ((part == 0) | np.isin(part, tuple(protected_ids)))
            )
        ),
        "other_person_protection_mismatch_pixels": int(
            np.count_nonzero(
                (instance > 0)
                & (instance != target)
                & (protected != contract["protected_namespace"]["other_person"])
            )
        ),
        "target_marked_other_person_pixels": int(
            np.count_nonzero(
                (instance == target)
                & (protected == contract["protected_namespace"]["other_person"])
            )
        ),
        "protected_material_relation_pixels": 0,
        "material_protected_relation_pixels": 0,
        "background_nonzero_pixels": int(
            np.count_nonzero((instance == 0) & (protected == 0) & (part == 0) & (material != 0))
        ),
    }
    for protected_id, allowed in contract["protected_allowed_material_ids"].items():
        metrics["protected_material_relation_pixels"] += int(
            np.count_nonzero((protected == int(protected_id)) & ~np.isin(material, allowed))
        )
    reverse_relations = {
        13: {contract["protected_namespace"]["other_person"]},
        14: {
            contract["protected_namespace"]["occluding_object"],
            contract["protected_namespace"]["support_surface"],
            contract["protected_namespace"]["accessory_or_prop"],
        },
        9: {contract["protected_namespace"]["accessory_or_prop"]},
    }
    for material_id, allowed_protected in reverse_relations.items():
        metrics["material_protected_relation_pixels"] += int(
            np.count_nonzero(
                (material == material_id) & ~np.isin(protected, tuple(allowed_protected))
            )
        )
    observed_material = sorted(int(value) for value in np.unique(material))
    observed_protected = sorted(int(value) for value in np.unique(protected))
    return metrics, observed_material, observed_protected


def _empty_metrics() -> dict[str, int]:
    return {
        "visible_without_material_pixels": -1,
        "orphan_material_pixels": -1,
        "protected_part_mismatch_pixels": -1,
        "unprotected_person_part_invalid_pixels": -1,
        "other_person_protection_mismatch_pixels": -1,
        "target_marked_other_person_pixels": -1,
        "protected_material_relation_pixels": -1,
        "material_protected_relation_pixels": -1,
        "background_nonzero_pixels": -1,
    }


def _validate_execution(execution: Any, *, protected_required: bool) -> None:
    expected = {
        "schema_version",
        "scene_id",
        "contract_id",
        "contract_sha256",
        "plan_id",
        "plan_sha256",
        "scene_state_before_sha256",
        "sidecar_scene_state_sha256",
        "scene_state_after_sha256",
        "annotation_restore_scene_state_sha256",
        "terminal_scene_state_sha256",
        "sidecar_plan_sha256",
        "sidecar_contract_sha256",
        "sidecar_ontology_snapshot_sha256",
        "sidecar_mapping_sha256",
        "part_file_sha256",
        "instance_file_sha256",
        "repeated_material_file_sha256",
        "repeated_protected_file_sha256",
        "outputs",
    }
    if not isinstance(execution, Mapping) or set(execution) != expected:
        raise MaterialProtectedContractError("material_execution_fields_invalid", str(execution))
    for key, value in execution.items():
        if key.endswith("_sha256") and value is not None and not _sha256(value):
            raise MaterialProtectedContractError("material_execution_hash_invalid", key)
    expected_roles = {"material", "protected"} if protected_required else {"material"}
    outputs = execution["outputs"]
    if (
        execution["schema_version"] != "1.0.0"
        or not isinstance(outputs, Mapping)
        or set(outputs) != expected_roles
    ):
        raise MaterialProtectedContractError("material_execution_outputs_invalid", str(outputs))
    if protected_required != (execution["repeated_protected_file_sha256"] is not None):
        raise MaterialProtectedContractError(
            "material_execution_protected_replay_invalid", str(execution)
        )
    fields = {
        "role",
        "encoding",
        "resolution",
        "crop",
        "decode_filter",
        "effects",
        "file_sha256",
        "bytes",
        "completed",
        "interrupted",
    }
    for role, output in outputs.items():
        if (
            not isinstance(output, Mapping)
            or set(output) != fields
            or output["role"] != role
            or not isinstance(output["effects"], list)
            or any(not isinstance(value, str) for value in output["effects"])
            or len(output["effects"]) != len(set(output["effects"]))
            or not _sha256(output["file_sha256"])
            or not isinstance(output["bytes"], int)
            or isinstance(output["bytes"], bool)
            or output["bytes"] < 0
            or not isinstance(output["completed"], bool)
            or not isinstance(output["interrupted"], bool)
        ):
            raise MaterialProtectedContractError("material_execution_output_invalid", str(output))


def _verify_snapshot(snapshot: Mapping[str, Any]) -> None:
    core = {
        key: value
        for key, value in snapshot.items()
        if key not in {"snapshot_id", "canonical_sha256"}
    }
    digest = _canonical_sha(core)
    if (
        snapshot["canonical_sha256"] != digest
        or snapshot["snapshot_id"] != f"ontology_v1_{digest[:24]}"
    ):
        raise MaterialProtectedContractError("material_snapshot_hash_invalid", str(snapshot))


def _verify_hashed_document(
    document: Mapping[str, Any], id_field: str, hash_field: str, prefix: str
) -> None:
    content = {
        key: value
        for key, value in document.items()
        if key not in {"schema_version", id_field, hash_field}
    }
    digest = _canonical_sha(content)
    if document[hash_field] != digest or document[id_field] != f"{prefix}_{digest[:24]}":
        raise MaterialProtectedContractError(
            "material_document_hash_invalid", str(document[id_field])
        )


def _finding(findings: list[dict[str, str]], code: str, path: str, detail: str) -> None:
    findings.append({"code": code, "path": path, "detail": detail})


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


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
        raise MaterialProtectedContractError("material_noncanonical_value", str(exc)) from exc
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "MaterialProtectedContractError",
    "build_material_protected_contract",
    "evaluate_material_protected_passes",
    "load_material_protected_policy",
    "publish_material_protected_document",
    "validate_material_protected_policy",
]
