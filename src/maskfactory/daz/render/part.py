"""Canonical-ontology exact PART pass contract and validation."""

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


class PartPassContractError(ValueError):
    """A PART policy, mapping, contract, execution, or raster is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_part_pass_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_part_pass_policy(document)
    return document


def validate_part_pass_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "active_ontology_versions",
        "inactive_ontology_versions",
        "eligible_pass_profiles",
        "codec",
        "mapping",
        "pixel_invariants",
        "freeze",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise PartPassContractError("part_policy_fields_invalid", str(policy))
    if policy["schema_version"] != "1.0.0" or policy["policy_version"] != "1.0.0":
        raise PartPassContractError("part_policy_version_invalid", "version")
    if policy["active_ontology_versions"] != ["body_parts_v1"]:
        raise PartPassContractError("part_policy_active_ontology_invalid", str(policy))
    if policy["inactive_ontology_versions"] != ["body_parts_v2"]:
        raise PartPassContractError("part_policy_inactive_ontology_invalid", str(policy))
    if policy["eligible_pass_profiles"] != [
        "engineering_minimal",
        "training_standard",
        "training_relationship",
        "diagnostic_full",
    ]:
        raise PartPassContractError("part_policy_profiles_invalid", str(policy))
    if policy["codec"] != {
        "role": "part",
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
        raise PartPassContractError("part_policy_codec_invalid", str(policy["codec"]))
    if policy["mapping"] != {
        "approved_status": "approved",
        "exact_ontology_snapshot_binding": True,
        "exact_active_id_set_required": True,
        "topology_mapping_sha256_required": True,
        "disabled_ids_forbidden": True,
    }:
        raise PartPassContractError("part_policy_mapping_invalid", str(policy["mapping"]))
    if policy["pixel_invariants"] != {
        "every_visible_instance_pixel_has_part": True,
        "every_nonbackground_part_pixel_has_instance": True,
        "expected_visible_ids_nonempty": True,
        "unknown_ids_forbidden": True,
    }:
        raise PartPassContractError("part_policy_pixels_invalid", str(policy["pixel_invariants"]))
    if policy["freeze"] != {
        "exact_scene_state_before_sidecar_after_restore_terminal": True,
        "exact_plan_contract_and_mapping_sidecars": True,
        "repeated_semantic_hash_required": True,
    }:
        raise PartPassContractError("part_policy_freeze_invalid", str(policy["freeze"]))


def build_part_pass_contract(
    resolved_state: Mapping[str, Any],
    pass_plan: Mapping[str, Any],
    ontology_snapshot: Mapping[str, Any],
    mapping_binding: Mapping[str, Any],
    expected_visible_part_ids: list[int],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Seal one PART pass to canonical ontology and approved topology mapping hashes."""

    validate_part_pass_policy(policy)
    require_valid_document(resolved_state, "daz_resolved_scene_state")
    _verify_hashed_document(resolved_state, "resolved_state_id", "resolved_state_sha256", "dcrs")
    require_valid_document(pass_plan, "daz_render_pass_plan")
    _verify_hashed_document(pass_plan, "plan_id", "plan_sha256", "dcrp")
    require_valid_document(ontology_snapshot, "daz_ontology_snapshot")
    _verify_snapshot(ontology_snapshot)
    version = ontology_snapshot["ontology_version"]
    if version not in policy["active_ontology_versions"]:
        code = (
            "part_ontology_inactive"
            if version in policy["inactive_ontology_versions"]
            else "part_ontology_unknown"
        )
        raise PartPassContractError(code, version)
    if pass_plan["profile"] not in policy["eligible_pass_profiles"]:
        raise PartPassContractError("part_pass_profile_ineligible", pass_plan["profile"])
    outputs = [row for row in pass_plan["outputs"] if row["role"] == "part"]
    if len(outputs) != 1 or outputs[0]["encoding"] != "uint16_png":
        raise PartPassContractError("part_output_contract_invalid", str(outputs))
    if (
        pass_plan["scene_id"] != resolved_state["scene_id"]
        or pass_plan["resolved_state_id"] != resolved_state["resolved_state_id"]
        or pass_plan["resolved_state_sha256"] != resolved_state["resolved_state_sha256"]
        or pass_plan["scene_state_sha256"] != resolved_state["scene_state_sha256"]
        or resolved_state["mapping_set_sha256"] != mapping_binding.get("mapping_set_sha256")
    ):
        raise PartPassContractError("part_lineage_mismatch", pass_plan["plan_id"])
    active_ids = [row["id"] for row in ontology_snapshot["part_labels"] if row["enabled"]]
    disabled_ids = [row["id"] for row in ontology_snapshot["part_labels"] if not row["enabled"]]
    _validate_mapping(mapping_binding, ontology_snapshot, active_ids, policy)
    if (
        not isinstance(expected_visible_part_ids, list)
        or not expected_visible_part_ids
        or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in expected_visible_part_ids
        )
        or expected_visible_part_ids != sorted(set(expected_visible_part_ids))
        or 0 in expected_visible_part_ids
        or not set(expected_visible_part_ids) <= set(active_ids)
    ):
        raise PartPassContractError("part_expected_ids_invalid", str(expected_visible_part_ids))
    output = outputs[0]
    content = {
        "scene_id": resolved_state["scene_id"],
        "resolved_state_id": resolved_state["resolved_state_id"],
        "resolved_state_sha256": resolved_state["resolved_state_sha256"],
        "scene_state_sha256": resolved_state["scene_state_sha256"],
        "plan_id": pass_plan["plan_id"],
        "plan_sha256": pass_plan["plan_sha256"],
        "policy_sha256": _canonical_sha(policy),
        "policy_version": policy["policy_version"],
        "ontology_snapshot_id": ontology_snapshot["snapshot_id"],
        "ontology_snapshot_sha256": ontology_snapshot["canonical_sha256"],
        "ontology_version": version,
        "mapping_id": mapping_binding["mapping_id"],
        "mapping_sha256": mapping_binding["mapping_sha256"],
        "mapping_set_sha256": mapping_binding["mapping_set_sha256"],
        "active_part_ids": active_ids,
        "disabled_part_ids": disabled_ids,
        "expected_visible_part_ids": expected_visible_part_ids,
        "output": {
            "role": "part",
            "encoding": "uint16_png",
            "resolution": output["resolution"],
            "crop": output["crop"],
            "background_value": 0,
            "decode_filter": "nearest_neighbor_exact",
        },
    }
    digest = _canonical_sha(content)
    document = {
        "schema_version": "1.0.0",
        "contract_id": f"dppc_{digest[:24]}",
        "contract_sha256": digest,
        **content,
    }
    require_valid_document(document, "daz_part_pass_contract")
    return document


def evaluate_part_pass(
    contract: Mapping[str, Any],
    execution: Mapping[str, Any],
    part_path: Path,
    instance_path: Path,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate exact PART IDs and full visible-instance/part coverage."""

    validate_part_pass_policy(policy)
    require_valid_document(contract, "daz_part_pass_contract")
    _verify_hashed_document(contract, "contract_id", "contract_sha256", "dppc")
    _validate_execution(execution)
    if any(
        execution[key] != contract[key]
        for key in ("scene_id", "contract_id", "contract_sha256", "plan_id", "plan_sha256")
    ):
        raise PartPassContractError("part_execution_lineage_mismatch", execution["contract_id"])
    part, codec = decode_u16_png_exact(part_path)
    instance, instance_codec = decode_u16_png_exact(instance_path)
    part_bytes = Path(part_path).read_bytes()
    instance_bytes = Path(instance_path).read_bytes()
    part_sha = hashlib.sha256(part_bytes).hexdigest()
    instance_sha = hashlib.sha256(instance_bytes).hexdigest()
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
            _finding(findings, "PART_SCENE_STATE_MUTATION", f"/{field}", execution[field])
    for field, expected, code in (
        ("sidecar_plan_sha256", contract["plan_sha256"], "PART_SIDECAR_PLAN_MISMATCH"),
        ("sidecar_contract_sha256", contract["contract_sha256"], "PART_SIDECAR_CONTRACT_MISMATCH"),
        ("sidecar_mapping_sha256", contract["mapping_sha256"], "PART_SIDECAR_MAPPING_MISMATCH"),
        (
            "sidecar_ontology_snapshot_sha256",
            contract["ontology_snapshot_sha256"],
            "PART_SIDECAR_ONTOLOGY_MISMATCH",
        ),
    ):
        if execution[field] != expected:
            _finding(findings, code, f"/{field}", execution[field])
    output = execution["output"]
    for field in ("role", "encoding", "resolution", "crop", "decode_filter"):
        if output[field] != contract["output"][field]:
            _finding(
                findings, "PART_OUTPUT_CONTRACT_MISMATCH", f"/output/{field}", str(output[field])
            )
    forbidden = sorted(set(output["effects"]) & set(policy["codec"]["forbidden_effects"]))
    if forbidden:
        _finding(findings, "PART_EFFECT_FORBIDDEN", "/output/effects", ",".join(forbidden))
    if output["file_sha256"] != part_sha:
        _finding(findings, "PART_FILE_HASH_MISMATCH", "/output/file_sha256", output["file_sha256"])
    if output["bytes"] != len(part_bytes) or not part_bytes:
        _finding(findings, "PART_BYTE_COUNT_MISMATCH", "/output/bytes", str(output["bytes"]))
    if output["completed"] is not True or output["interrupted"] is not False:
        _finding(findings, "PART_OUTPUT_INCOMPLETE", "/output/completed", str(output))
    if execution["instance_file_sha256"] != instance_sha:
        _finding(
            findings,
            "PART_INSTANCE_HASH_MISMATCH",
            "/instance_file_sha256",
            execution["instance_file_sha256"],
        )
    if (
        codec["resolution"] != contract["output"]["resolution"]
        or instance_codec["resolution"] != codec["resolution"]
    ):
        _finding(
            findings, "PART_RESOLUTION_MISMATCH", "/codec/resolution", str(codec["resolution"])
        )
    if part.shape == instance.shape:
        missing_part = int(np.count_nonzero((instance > 0) & (part == 0)))
        orphan_part = int(np.count_nonzero((part > 0) & (instance == 0)))
    else:
        missing_part = orphan_part = -1
    if missing_part:
        _finding(findings, "PART_VISIBLE_INSTANCE_UNLABELED", "/pixels", str(missing_part))
    if orphan_part:
        _finding(findings, "PART_WITHOUT_INSTANCE", "/pixels", str(orphan_part))
    values, counts = np.unique(part, return_counts=True)
    count_map = {int(value): int(count) for value, count in zip(values, counts, strict=True)}
    observed = sorted(count_map)
    unknown = sorted(set(observed) - {0, *contract["active_part_ids"]})
    if unknown:
        _finding(
            findings, "PART_ID_INACTIVE_OR_UNKNOWN", "/observed_ids", ",".join(map(str, unknown))
        )
    missing_expected = sorted(set(contract["expected_visible_part_ids"]) - set(observed))
    if missing_expected:
        _finding(
            findings,
            "PART_EXPECTED_ID_EMPTY",
            "/observed_ids",
            ",".join(map(str, missing_expected)),
        )
    if execution["repeated_semantic_file_sha256"] != part_sha:
        _finding(
            findings,
            "PART_SEMANTIC_REPLAY_MISMATCH",
            "/repeated_semantic_file_sha256",
            execution["repeated_semantic_file_sha256"],
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
        "file_sha256": part_sha,
        "instance_file_sha256": instance_sha,
        "bytes": len(part_bytes),
        "codec": codec,
        "observed_ids": observed,
        "id_pixel_counts": [{"part_id": key, "pixel_count": count_map[key]} for key in observed],
        "coverage": {
            "visible_instance_without_part_pixels": missing_part,
            "part_without_instance_pixels": orphan_part,
        },
        "findings": findings,
        "summary": {
            "passed": not findings,
            "finding_count": len(findings),
            "failure_codes": sorted({row["code"] for row in findings}),
            "active_id_count": len(contract["active_part_ids"]),
            "expected_id_count": len(contract["expected_visible_part_ids"]),
            "scene_state_unchanged": not any("MUTATION" in row["code"] for row in findings),
            "semantic_replay_identical": "PART_SEMANTIC_REPLAY_MISMATCH"
            not in {row["code"] for row in findings},
        },
    }
    digest = _canonical_sha(content)
    report = {
        "schema_version": "1.0.0",
        "report_id": f"dppr_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    require_valid_document(report, "daz_part_pass_report")
    return report


def publish_part_pass_document(document: Mapping[str, Any], output_root: Path) -> tuple[Path, bool]:
    if "report_id" in document:
        require_valid_document(document, "daz_part_pass_report")
        name = document["report_id"]
    elif "contract_id" in document:
        require_valid_document(document, "daz_part_pass_contract")
        name = document["contract_id"]
    else:
        raise PartPassContractError("part_publication_document_unknown", str(document))
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{name}.json"
    payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise PartPassContractError("part_publication_conflict", str(target))
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


def _validate_mapping(
    mapping: Any, snapshot: Mapping[str, Any], active_ids: list[int], policy: Mapping[str, Any]
) -> None:
    fields = {
        "mapping_id",
        "mapping_sha256",
        "mapping_set_sha256",
        "ontology_snapshot_id",
        "ontology_snapshot_sha256",
        "topology_mapping_sha256",
        "active_part_ids",
        "status",
    }
    if not isinstance(mapping, Mapping) or set(mapping) != fields:
        raise PartPassContractError("part_mapping_fields_invalid", str(mapping))
    payload = {
        key: value for key, value in mapping.items() if key not in {"mapping_id", "mapping_sha256"}
    }
    digest = _canonical_sha(payload)
    if (
        mapping["mapping_id"] != f"dpm_{digest[:24]}"
        or mapping["mapping_sha256"] != digest
        or mapping["status"] != policy["mapping"]["approved_status"]
        or mapping["ontology_snapshot_id"] != snapshot["snapshot_id"]
        or mapping["ontology_snapshot_sha256"] != snapshot["canonical_sha256"]
        or mapping["active_part_ids"] != active_ids
        or not _sha256(mapping["mapping_set_sha256"])
        or not _sha256(mapping["topology_mapping_sha256"])
    ):
        raise PartPassContractError("part_mapping_invalid", str(mapping.get("mapping_id")))


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
        raise PartPassContractError("part_snapshot_hash_invalid", str(snapshot.get("snapshot_id")))


def _validate_execution(execution: Any) -> None:
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
        "sidecar_mapping_sha256",
        "sidecar_ontology_snapshot_sha256",
        "instance_file_sha256",
        "repeated_semantic_file_sha256",
        "output",
    }
    if not isinstance(execution, Mapping) or set(execution) != expected:
        raise PartPassContractError("part_execution_fields_invalid", str(execution))
    for key, value in execution.items():
        if key.endswith("_sha256") and not _sha256(value):
            raise PartPassContractError("part_execution_hash_invalid", key)
    output = execution["output"]
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
    if (
        execution["schema_version"] != "1.0.0"
        or not isinstance(output, Mapping)
        or set(output) != fields
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
        raise PartPassContractError("part_execution_output_invalid", str(output))


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
        raise PartPassContractError("part_document_hash_invalid", str(document[id_field]))


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
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PartPassContractError("part_noncanonical_value", str(exc)) from exc
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "PartPassContractError",
    "build_part_pass_contract",
    "evaluate_part_pass",
    "load_part_pass_policy",
    "publish_part_pass_document",
    "validate_part_pass_policy",
]
