"""Exact 16-bit person-instance pass planning and decoding."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml
from PIL import Image, UnidentifiedImageError

from ...validation import require_valid_document


class InstancePassContractError(ValueError):
    """An instance-pass policy, contract, execution, or image is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_instance_pass_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_instance_pass_policy(document)
    return document


def validate_instance_pass_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "eligible_pass_profiles",
        "codec",
        "namespace",
        "ownership",
        "freeze",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise InstancePassContractError("instance_policy_fields_invalid", str(policy))
    if policy["schema_version"] != "1.0.0" or policy["policy_version"] != "1.0.0":
        raise InstancePassContractError("instance_policy_version_invalid", "version")
    if policy["eligible_pass_profiles"] != [
        "engineering_minimal",
        "training_standard",
        "training_relationship",
        "diagnostic_full",
    ]:
        raise InstancePassContractError(
            "instance_policy_profiles_invalid", str(policy["eligible_pass_profiles"])
        )
    expected_codec = {
        "role": "instance",
        "encoding": "uint16_png",
        "container_format": "PNG",
        "channels": 1,
        "integer_bits": 16,
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
    }
    if policy["codec"] != expected_codec:
        raise InstancePassContractError("instance_policy_codec_invalid", str(policy["codec"]))
    expected_namespace = {
        "maximum_people": 4,
        "ordered_mapping": [
            {"p_index": "p0", "instance_id": 1},
            {"p_index": "p1", "instance_id": 2},
            {"p_index": "p2", "instance_id": 3},
            {"p_index": "p3", "instance_id": 4},
        ],
        "ranking_authority": "final_camera_prominence",
        "minimum_visible_area_fraction": 0.04,
    }
    if policy["namespace"] != expected_namespace:
        raise InstancePassContractError(
            "instance_policy_namespace_invalid", str(policy["namespace"])
        )
    expected_ownership = {
        "node_ids_required": True,
        "node_ids_unique_across_people": True,
        "visible_id_must_be_declared": True,
        "every_declared_person_nonempty": True,
        "construction_order_separate_from_p_index": True,
    }
    if policy["ownership"] != expected_ownership:
        raise InstancePassContractError(
            "instance_policy_ownership_invalid", str(policy["ownership"])
        )
    expected_freeze = {
        "exact_scene_state_before_sidecar_after_restore_terminal": True,
        "exact_plan_and_contract_sidecars": True,
        "exact_resolution_and_crop": True,
        "repeated_semantic_hash_required": True,
    }
    if policy["freeze"] != expected_freeze:
        raise InstancePassContractError("instance_policy_freeze_invalid", str(policy["freeze"]))


def build_instance_pass_contract(
    resolved_state: Mapping[str, Any],
    pass_plan: Mapping[str, Any],
    owners: list[Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Seal exact p-index/ID/node ownership for one frozen instance pass."""

    validate_instance_pass_policy(policy)
    require_valid_document(resolved_state, "daz_resolved_scene_state")
    _verify_hashed_document(
        resolved_state,
        id_field="resolved_state_id",
        hash_field="resolved_state_sha256",
        prefix="dcrs",
    )
    require_valid_document(pass_plan, "daz_render_pass_plan")
    _verify_hashed_document(pass_plan, id_field="plan_id", hash_field="plan_sha256", prefix="dcrp")
    if pass_plan["profile"] not in policy["eligible_pass_profiles"]:
        raise InstancePassContractError("instance_pass_profile_ineligible", pass_plan["profile"])
    outputs = [output for output in pass_plan["outputs"] if output["role"] == "instance"]
    if len(outputs) != 1 or outputs[0]["encoding"] != policy["codec"]["encoding"]:
        raise InstancePassContractError("instance_output_contract_invalid", str(outputs))
    if (
        pass_plan["scene_id"] != resolved_state["scene_id"]
        or pass_plan["resolved_state_id"] != resolved_state["resolved_state_id"]
        or pass_plan["resolved_state_sha256"] != resolved_state["resolved_state_sha256"]
        or pass_plan["scene_state_sha256"] != resolved_state["scene_state_sha256"]
    ):
        raise InstancePassContractError(
            "instance_state_plan_lineage_mismatch", pass_plan["plan_id"]
        )
    normalized_owners = _validate_owners(owners, resolved_state, policy)
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
        "output": {
            "role": output["role"],
            "encoding": output["encoding"],
            "resolution": output["resolution"],
            "crop": output["crop"],
            "background_value": policy["codec"]["background_value"],
            "decode_filter": policy["codec"]["decode_filter"],
        },
        "owners": normalized_owners,
    }
    digest = _canonical_sha(content)
    document = {
        "schema_version": "1.0.0",
        "contract_id": f"dipc_{digest[:24]}",
        "contract_sha256": digest,
        **content,
    }
    require_valid_document(document, "daz_instance_pass_contract")
    return document


def decode_u16_png_exact(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    """Decode one grayscale PNG without scaling, palette conversion, or resampling."""

    image_path = Path(path)
    if not image_path.is_file():
        raise InstancePassContractError("instance_file_missing", str(image_path))
    try:
        with Image.open(image_path) as image:
            image_format = image.format
            source_mode = image.mode
            metadata_keys = sorted(image.info)
            image.load()
            array = np.asarray(image)
    except (OSError, UnidentifiedImageError) as exc:
        raise InstancePassContractError("instance_file_unreadable", str(exc)) from exc
    if image_format != "PNG" or source_mode not in {"I;16", "I;16L", "I;16B", "I"}:
        raise InstancePassContractError(
            "instance_codec_format_invalid", f"{image_format}:{source_mode}"
        )
    if array.ndim != 2 or not np.issubdtype(array.dtype, np.integer):
        raise InstancePassContractError("instance_codec_shape_invalid", str(array.shape))
    if array.size and (int(array.min()) < 0 or int(array.max()) > 65535):
        raise InstancePassContractError("instance_codec_range_invalid", str(array.dtype))
    forbidden_metadata = sorted(
        set(metadata_keys) & {"icc_profile", "gamma", "srgb", "chromaticity", "transparency"}
    )
    if forbidden_metadata:
        raise InstancePassContractError(
            "instance_codec_color_metadata_forbidden", ",".join(forbidden_metadata)
        )
    decoded = array.astype(np.uint16, copy=False)
    return decoded, {
        "format": image_format,
        "source_mode": source_mode,
        "dtype": str(decoded.dtype),
        "resolution": [int(decoded.shape[1]), int(decoded.shape[0])],
        "minimum": int(decoded.min()) if decoded.size else 0,
        "maximum": int(decoded.max()) if decoded.size else 0,
        "metadata_keys": metadata_keys,
    }


def evaluate_instance_pass(
    contract: Mapping[str, Any],
    execution: Mapping[str, Any],
    image_path: Path,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Decode and validate one exact visible person-instance map."""

    validate_instance_pass_policy(policy)
    require_valid_document(contract, "daz_instance_pass_contract")
    _verify_hashed_document(
        contract, id_field="contract_id", hash_field="contract_sha256", prefix="dipc"
    )
    _validate_execution(execution)
    if (
        execution["scene_id"] != contract["scene_id"]
        or execution["contract_id"] != contract["contract_id"]
        or execution["contract_sha256"] != contract["contract_sha256"]
        or execution["plan_id"] != contract["plan_id"]
        or execution["plan_sha256"] != contract["plan_sha256"]
    ):
        raise InstancePassContractError(
            "instance_execution_lineage_mismatch", execution["contract_id"]
        )
    pixels, codec = decode_u16_png_exact(image_path)
    payload = Path(image_path).read_bytes()
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    findings: list[dict[str, str]] = []
    expected_state = contract["scene_state_sha256"]
    for field in (
        "scene_state_before_sha256",
        "sidecar_scene_state_sha256",
        "scene_state_after_sha256",
        "annotation_restore_scene_state_sha256",
        "terminal_scene_state_sha256",
    ):
        if execution[field] != expected_state:
            _finding(findings, "INSTANCE_SCENE_STATE_MUTATION", f"/{field}", execution[field])
    if execution["sidecar_plan_sha256"] != contract["plan_sha256"]:
        _finding(
            findings,
            "INSTANCE_SIDECAR_PLAN_MISMATCH",
            "/sidecar_plan_sha256",
            execution["sidecar_plan_sha256"],
        )
    if execution["sidecar_contract_sha256"] != contract["contract_sha256"]:
        _finding(
            findings,
            "INSTANCE_SIDECAR_CONTRACT_MISMATCH",
            "/sidecar_contract_sha256",
            execution["sidecar_contract_sha256"],
        )
    output = execution["output"]
    for field in ("role", "encoding", "resolution", "crop", "decode_filter"):
        if output[field] != contract["output"][field]:
            _finding(
                findings,
                "INSTANCE_OUTPUT_CONTRACT_MISMATCH",
                f"/output/{field}",
                str(output[field]),
            )
    forbidden = sorted(set(output["effects"]) & set(policy["codec"]["forbidden_effects"]))
    if forbidden:
        _finding(
            findings,
            "INSTANCE_EFFECT_FORBIDDEN",
            "/output/effects",
            ",".join(forbidden),
        )
    if output["file_sha256"] != actual_sha256:
        _finding(
            findings,
            "INSTANCE_FILE_HASH_MISMATCH",
            "/output/file_sha256",
            output["file_sha256"],
        )
    if output["bytes"] != len(payload) or not payload:
        _finding(findings, "INSTANCE_BYTE_COUNT_MISMATCH", "/output/bytes", str(output["bytes"]))
    if output["completed"] is not True or output["interrupted"] is not False:
        _finding(findings, "INSTANCE_OUTPUT_INCOMPLETE", "/output/completed", str(output))
    if codec["resolution"] != contract["output"]["resolution"]:
        _finding(
            findings,
            "INSTANCE_RESOLUTION_MISMATCH",
            "/codec/resolution",
            str(codec["resolution"]),
        )
    values, counts = np.unique(pixels, return_counts=True)
    count_map = {int(value): int(count) for value, count in zip(values, counts, strict=True)}
    declared_ids = {owner["instance_id"] for owner in contract["owners"]}
    allowed_ids = {0, *declared_ids}
    unknown_ids = sorted(set(count_map) - allowed_ids)
    if unknown_ids:
        _finding(
            findings,
            "INSTANCE_ID_UNDECLARED",
            "/codec/observed_ids",
            ",".join(map(str, unknown_ids)),
        )
    total_pixels = int(pixels.size)
    owner_measurements = []
    for owner in contract["owners"]:
        count = count_map.get(owner["instance_id"], 0)
        fraction = count / total_pixels if total_pixels else 0.0
        owner_measurements.append(
            {
                "p_index": owner["p_index"],
                "instance_id": owner["instance_id"],
                "pixel_count": count,
                "visible_area_fraction": fraction,
            }
        )
        if count == 0:
            _finding(
                findings,
                "INSTANCE_DECLARED_OWNER_EMPTY",
                f"/owners/{owner['p_index']}",
                str(owner["instance_id"]),
            )
        if fraction < policy["namespace"]["minimum_visible_area_fraction"]:
            _finding(
                findings,
                "INSTANCE_PROMINENCE_BELOW_FLOOR",
                f"/owners/{owner['p_index']}",
                str(fraction),
            )
    observed_rank = [
        owner["p_index"]
        for owner in sorted(
            (
                {
                    "p_index": owner["p_index"],
                    "construction_id": owner["construction_id"],
                    "count": count_map.get(owner["instance_id"], 0),
                }
                for owner in contract["owners"]
            ),
            key=lambda row: (-row["count"], row["construction_id"]),
        )
    ]
    expected_rank = [owner["p_index"] for owner in contract["owners"]]
    if observed_rank != expected_rank:
        _finding(
            findings,
            "INSTANCE_PROMINENCE_RANK_MISMATCH",
            "/owners",
            json.dumps(observed_rank),
        )
    if execution["repeated_semantic_file_sha256"] != actual_sha256:
        _finding(
            findings,
            "INSTANCE_SEMANTIC_REPLAY_MISMATCH",
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
        "scene_state_sha256": expected_state,
        "execution_sha256": _canonical_sha(execution),
        "file_sha256": actual_sha256,
        "bytes": len(payload),
        "codec": codec,
        "observed_ids": sorted(count_map),
        "owner_measurements": owner_measurements,
        "findings": findings,
        "summary": {
            "passed": not findings,
            "finding_count": len(findings),
            "failure_codes": sorted({row["code"] for row in findings}),
            "owner_count": len(contract["owners"]),
            "scene_state_unchanged": not any("MUTATION" in row["code"] for row in findings),
            "semantic_replay_identical": "INSTANCE_SEMANTIC_REPLAY_MISMATCH"
            not in {row["code"] for row in findings},
        },
    }
    digest = _canonical_sha(content)
    report = {
        "schema_version": "1.0.0",
        "report_id": f"dipr_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    require_valid_document(report, "daz_instance_pass_report")
    return report


def publish_instance_pass_document(
    document: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    if "report_id" in document:
        require_valid_document(document, "daz_instance_pass_report")
        name = document["report_id"]
    elif "contract_id" in document:
        require_valid_document(document, "daz_instance_pass_contract")
        name = document["contract_id"]
    else:
        raise InstancePassContractError("instance_publication_document_unknown", str(document))
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{name}.json"
    payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise InstancePassContractError("instance_publication_conflict", str(target))
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


def _validate_owners(
    owners: Any, resolved_state: Mapping[str, Any], policy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    maximum = policy["namespace"]["maximum_people"]
    if not isinstance(owners, list) or not 1 <= len(owners) <= maximum:
        raise InstancePassContractError("instance_owners_count_invalid", str(owners))
    known_nodes = {asset["node_id"] for asset in resolved_state["state"]["assets"]}
    normalized = []
    all_nodes: list[str] = []
    construction_ids: list[str] = []
    for index, raw in enumerate(owners):
        if not isinstance(raw, Mapping) or set(raw) != {
            "p_index",
            "instance_id",
            "construction_id",
            "node_ids",
        }:
            raise InstancePassContractError("instance_owner_fields_invalid", str(raw))
        expected = policy["namespace"]["ordered_mapping"][index]
        node_ids = raw["node_ids"]
        if (
            raw["p_index"] != expected["p_index"]
            or raw["instance_id"] != expected["instance_id"]
            or not isinstance(raw["construction_id"], str)
            or not raw["construction_id"]
            or not isinstance(node_ids, list)
            or not node_ids
            or len(node_ids) != len(set(node_ids))
            or any(not isinstance(node, str) or node not in known_nodes for node in node_ids)
        ):
            raise InstancePassContractError("instance_owner_invalid", str(raw))
        construction_ids.append(raw["construction_id"])
        all_nodes.extend(node_ids)
        normalized.append(
            {
                "p_index": raw["p_index"],
                "instance_id": raw["instance_id"],
                "construction_id": raw["construction_id"],
                "node_ids": sorted(node_ids),
            }
        )
    if len(construction_ids) != len(set(construction_ids)) or len(all_nodes) != len(set(all_nodes)):
        raise InstancePassContractError("instance_owner_identity_overlap", str(owners))
    return normalized


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
        "repeated_semantic_file_sha256",
        "output",
    }
    if not isinstance(execution, Mapping) or set(execution) != expected:
        raise InstancePassContractError("instance_execution_fields_invalid", str(execution))
    hashes = [
        execution[field]
        for field in expected
        if field.endswith("_sha256") and field not in {"file_sha256"}
    ]
    if execution["schema_version"] != "1.0.0" or any(not _sha256(value) for value in hashes):
        raise InstancePassContractError("instance_execution_hash_invalid", str(execution))
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
        not isinstance(output, Mapping)
        or set(output) != fields
        or not isinstance(output["effects"], list)
        or any(not isinstance(effect, str) for effect in output["effects"])
        or len(output["effects"]) != len(set(output["effects"]))
        or not _sha256(output["file_sha256"])
        or not isinstance(output["bytes"], int)
        or isinstance(output["bytes"], bool)
        or output["bytes"] < 0
        or not isinstance(output["completed"], bool)
        or not isinstance(output["interrupted"], bool)
    ):
        raise InstancePassContractError("instance_execution_output_invalid", str(output))


def _verify_hashed_document(
    document: Mapping[str, Any], *, id_field: str, hash_field: str, prefix: str
) -> None:
    content = {
        key: value
        for key, value in document.items()
        if key not in {"schema_version", id_field, hash_field}
    }
    digest = _canonical_sha(content)
    if document[hash_field] != digest or document[id_field] != f"{prefix}_{digest[:24]}":
        raise InstancePassContractError("instance_document_hash_invalid", str(document[id_field]))


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
        raise InstancePassContractError("instance_noncanonical_value", str(exc)) from exc
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "InstancePassContractError",
    "build_instance_pass_contract",
    "decode_u16_png_exact",
    "evaluate_instance_pass",
    "load_instance_pass_policy",
    "publish_instance_pass_document",
    "validate_instance_pass_policy",
]
