"""Geometry-derived contact, occlusion, boundary-pair, and diagnostic outputs."""

from __future__ import annotations

import binascii
import hashlib
import itertools
import json
import math
import os
import struct
import tempfile
import zlib
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import yaml

from ...validation import require_valid_document
from .geometry import decode_float32_exr
from .instance import decode_u16_png_exact


class RelationshipPassContractError(ValueError):
    """A relationship policy, contract, observation, execution, or raster is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_relationship_pass_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_relationship_pass_policy(document)
    return document


def validate_relationship_pass_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "eligible_profiles",
        "namespace",
        "contact",
        "occlusion",
        "rasters",
        "diagnostic",
        "freeze",
        "forbidden_effects",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise RelationshipPassContractError("relationship_policy_fields_invalid", str(policy))
    if policy["schema_version"] != "1.0.0" or policy["policy_version"] != "1.0.0":
        raise RelationshipPassContractError("relationship_policy_identity_invalid", str(policy))
    if policy["eligible_profiles"] != ["training_relationship", "diagnostic_full"]:
        raise RelationshipPassContractError(
            "relationship_policy_profiles_invalid", str(policy["eligible_profiles"])
        )
    if policy["namespace"] != {
        "minimum_instance_id": 1,
        "maximum_instance_id": 4,
        "pair_order": "ascending_instance_id",
        "background_pair": [0, 0],
    }:
        raise RelationshipPassContractError(
            "relationship_policy_namespace_invalid", str(policy["namespace"])
        )
    if policy["contact"] != {
        "intended_distance_mm": [0.0, 4.0],
        "maximum_penetration_mm": 2.0,
        "minimum_normal_dot": 0.0,
        "positive_area_required": True,
        "geometry_only_no_rgb_inference": True,
    }:
        raise RelationshipPassContractError(
            "relationship_policy_contact_invalid", str(policy["contact"])
        )
    if policy["occlusion"] != {
        "depth_unit": "meter",
        "depth_tie_epsilon_m": 0.00001,
        "minimum_confidence": 0.5,
        "directions": ["none", "a_front", "b_front", "mixed"],
        "visible_instance_and_linear_depth_authority": True,
        "reciprocal_directed_records_required": True,
    }:
        raise RelationshipPassContractError(
            "relationship_policy_occlusion_invalid", str(policy["occlusion"])
        )
    if policy["rasters"] != {
        "contact_pairs": {
            "encoding": "two_channel_uint16_png",
            "channels": ["a_instance_id", "b_instance_id"],
            "train_eligible": False,
        },
        "front_owner": {
            "encoding": "uint16_png",
            "background_value": 0,
            "train_eligible": False,
        },
        "boundary_pairs": {
            "encoding": "two_channel_uint16_png",
            "channels": ["a_instance_id", "b_instance_id"],
            "train_eligible": False,
        },
        "boundary_adjacency": "eight_connected",
        "contact_raster_must_be_boundary_subset": True,
    }:
        raise RelationshipPassContractError(
            "relationship_policy_rasters_invalid", str(policy["rasters"])
        )
    if policy["diagnostic"] != {
        "roles": ["surface", "facet", "node", "mapping_confidence", "amodal_geometry"],
        "diagnostic_full_only": True,
        "all_train_eligible_false": True,
        "amodal_physical_root": "13_annotations/amodal_diagnostic",
        "amodal_absent_from_normal_training_exports": True,
    }:
        raise RelationshipPassContractError(
            "relationship_policy_diagnostic_invalid", str(policy["diagnostic"])
        )
    if policy["freeze"] != {
        "exact_scene_state_before_sidecar_after_restore_terminal": True,
        "exact_plan_instance_geometry_contract_sidecars": True,
        "exact_instance_depth_authority_hashes": True,
        "repeated_relationship_raster_hashes_required": True,
    }:
        raise RelationshipPassContractError(
            "relationship_policy_freeze_invalid", str(policy["freeze"])
        )
    if policy["forbidden_effects"] != [
        "jpeg",
        "palette_quantization",
        "color_management",
        "tone_mapping",
        "denoising",
        "bloom",
        "motion_blur",
        "depth_of_field",
        "lossy_resize",
    ]:
        raise RelationshipPassContractError(
            "relationship_policy_effects_invalid", str(policy["forbidden_effects"])
        )


def build_relationship_pass_contract(
    instance_contract: Mapping[str, Any],
    geometry_contract: Mapping[str, Any],
    pass_plan: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind every unordered person pair and optional diagnostics to frozen render authority."""

    validate_relationship_pass_policy(policy)
    require_valid_document(instance_contract, "daz_instance_pass_contract")
    _verify_hashed_document(instance_contract, "contract_id", "contract_sha256", "dipc")
    require_valid_document(geometry_contract, "daz_geometry_pass_contract")
    _verify_hashed_document(geometry_contract, "contract_id", "contract_sha256", "dgpc")
    require_valid_document(pass_plan, "daz_render_pass_plan")
    _verify_hashed_document(pass_plan, "plan_id", "plan_sha256", "dcrp")
    if pass_plan["profile"] not in policy["eligible_profiles"] or any(
        document["scene_id"] != pass_plan["scene_id"]
        or document["scene_state_sha256"] != pass_plan["scene_state_sha256"]
        or document["plan_id"] != pass_plan["plan_id"]
        or document["plan_sha256"] != pass_plan["plan_sha256"]
        for document in (instance_contract, geometry_contract)
    ):
        raise RelationshipPassContractError("relationship_lineage_invalid", pass_plan["plan_id"])
    owner_ids = [row["instance_id"] for row in instance_contract["owners"]]
    if owner_ids != list(range(1, len(owner_ids) + 1)):
        raise RelationshipPassContractError("relationship_owner_namespace_invalid", str(owner_ids))
    pairs = [list(pair) for pair in itertools.combinations(owner_ids, 2)]
    outputs_by_role = {row["role"]: row for row in pass_plan["outputs"]}
    relationship_roles = ["contact_pairs", "front_owner", "boundary_pairs"]
    if any(role not in outputs_by_role for role in relationship_roles):
        raise RelationshipPassContractError("relationship_outputs_missing", pass_plan["profile"])
    expected_encodings = {
        "contact_pairs": "two_channel_uint16_png",
        "front_owner": "uint16_png",
        "boundary_pairs": "two_channel_uint16_png",
    }
    if any(
        outputs_by_role[role]["encoding"] != expected_encodings[role] for role in relationship_roles
    ):
        raise RelationshipPassContractError(
            "relationship_output_encoding_invalid", pass_plan["profile"]
        )
    resolution = outputs_by_role["front_owner"]["resolution"]
    crop = outputs_by_role["front_owner"]["crop"]
    if (
        any(
            outputs_by_role[role]["resolution"] != resolution
            or outputs_by_role[role]["crop"] != crop
            for role in relationship_roles
        )
        or instance_contract["output"]["resolution"] != resolution
    ):
        raise RelationshipPassContractError(
            "relationship_output_alignment_invalid", pass_plan["plan_id"]
        )
    diagnostic_roles = (
        policy["diagnostic"]["roles"] if pass_plan["profile"] == "diagnostic_full" else []
    )
    if any(role not in outputs_by_role for role in diagnostic_roles):
        raise RelationshipPassContractError(
            "relationship_diagnostic_output_missing", pass_plan["profile"]
        )
    outputs = {
        role: {
            "role": role,
            "encoding": outputs_by_role[role]["encoding"],
            "resolution": outputs_by_role[role]["resolution"],
            "crop": outputs_by_role[role]["crop"],
            "train_eligible": False,
        }
        for role in [*relationship_roles, *diagnostic_roles]
    }
    content = {
        "scene_id": pass_plan["scene_id"],
        "scene_state_sha256": pass_plan["scene_state_sha256"],
        "plan_id": pass_plan["plan_id"],
        "plan_sha256": pass_plan["plan_sha256"],
        "instance_contract_id": instance_contract["contract_id"],
        "instance_contract_sha256": instance_contract["contract_sha256"],
        "geometry_contract_id": geometry_contract["contract_id"],
        "geometry_contract_sha256": geometry_contract["contract_sha256"],
        "policy_sha256": _canonical_sha(policy),
        "policy_version": policy["policy_version"],
        "profile": pass_plan["profile"],
        "owner_ids": owner_ids,
        "pairs": pairs,
        "depth_tie_epsilon_m": policy["occlusion"]["depth_tie_epsilon_m"],
        "contact_distance_mm": policy["contact"]["intended_distance_mm"],
        "maximum_penetration_mm": policy["contact"]["maximum_penetration_mm"],
        "minimum_normal_dot": policy["contact"]["minimum_normal_dot"],
        "amodal_physical_root": policy["diagnostic"]["amodal_physical_root"],
        "outputs": outputs,
    }
    digest = _canonical_sha(content)
    document = {
        "schema_version": "1.0.0",
        "contract_id": f"drpc_{digest[:24]}",
        "contract_sha256": digest,
        **content,
    }
    require_valid_document(document, "daz_relationship_pass_contract")
    return document


def decode_pair_u16_png(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    """Decode an exact non-interlaced 16-bit grayscale+alpha PNG into two uint16 channels."""

    payload = Path(path).read_bytes()
    if payload[:8] != b"\x89PNG\r\n\x1a\n":
        raise RelationshipPassContractError("relationship_pair_png_signature_invalid", str(path))
    position = 8
    chunks: list[tuple[bytes, bytes]] = []
    while position < len(payload):
        if position + 12 > len(payload):
            raise RelationshipPassContractError("relationship_pair_png_truncated", str(position))
        length = struct.unpack_from(">I", payload, position)[0]
        position += 4
        chunk_type = payload[position : position + 4]
        position += 4
        if length > 1_073_741_824 or position + length + 4 > len(payload):
            raise RelationshipPassContractError("relationship_pair_png_chunk_invalid", str(length))
        data = payload[position : position + length]
        position += length
        expected_crc = struct.unpack_from(">I", payload, position)[0]
        position += 4
        actual_crc = binascii.crc32(chunk_type + data) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise RelationshipPassContractError(
                "relationship_pair_png_crc_invalid", chunk_type.decode("ascii", "replace")
            )
        chunks.append((chunk_type, data))
        if chunk_type == b"IEND":
            break
    if (
        position != len(payload)
        or [row[0] for row in chunks].count(b"IHDR") != 1
        or chunks[-1][0] != b"IEND"
    ):
        raise RelationshipPassContractError("relationship_pair_png_structure_invalid", str(path))
    if any(kind not in {b"IHDR", b"IDAT", b"IEND"} for kind, _data in chunks):
        raise RelationshipPassContractError("relationship_pair_png_ancillary_forbidden", str(path))
    ihdr = chunks[0]
    if ihdr[0] != b"IHDR" or len(ihdr[1]) != 13:
        raise RelationshipPassContractError("relationship_pair_png_ihdr_invalid", str(path))
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
        ">IIBBBBB", ihdr[1]
    )
    if (
        width < 1
        or height < 1
        or bit_depth != 16
        or color_type != 4
        or compression != 0
        or filter_method != 0
        or interlace != 0
    ):
        raise RelationshipPassContractError(
            "relationship_pair_png_format_invalid",
            str((width, height, bit_depth, color_type, compression, filter_method, interlace)),
        )
    compressed = b"".join(data for kind, data in chunks if kind == b"IDAT")
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed) + decoder.flush()
    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise RelationshipPassContractError("relationship_pair_png_deflate_invalid", str(path))
    stride = width * 4
    if len(raw) != height * (stride + 1):
        raise RelationshipPassContractError("relationship_pair_png_size_invalid", str(len(raw)))
    decoded = np.empty((height, stride), dtype=np.uint8)
    previous = np.zeros(stride, dtype=np.uint8)
    for row_index in range(height):
        start = row_index * (stride + 1)
        filter_type = raw[start]
        current = np.frombuffer(raw[start + 1 : start + 1 + stride], dtype=np.uint8).copy()
        _undo_png_filter(current, previous, filter_type, bytes_per_pixel=4)
        decoded[row_index] = current
        previous = current
    result = decoded.reshape(height, width, 4).view(">u2").reshape(height, width, 2)
    return result.astype(np.uint16), {
        "format": "PNG",
        "bit_depth": 16,
        "color_type": 4,
        "channels": 2,
        "resolution": [width, height],
        "interlace": 0,
        "bytes": len(payload),
    }


def evaluate_relationship_passes(
    contract: Mapping[str, Any],
    instance_contract: Mapping[str, Any],
    geometry_contract: Mapping[str, Any],
    execution: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    *,
    instance_path: Path,
    depth_path: Path,
    contact_pairs_path: Path,
    front_owner_path: Path,
    boundary_pairs_path: Path,
    diagnostic_paths: Mapping[str, Path],
    policy: Mapping[str, Any],
    geometry_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate relationship rasters against instances, depth samples, and 3D observations."""

    validate_relationship_pass_policy(policy)
    require_valid_document(contract, "daz_relationship_pass_contract")
    _verify_hashed_document(contract, "contract_id", "contract_sha256", "drpc")
    require_valid_document(instance_contract, "daz_instance_pass_contract")
    _verify_hashed_document(instance_contract, "contract_id", "contract_sha256", "dipc")
    require_valid_document(geometry_contract, "daz_geometry_pass_contract")
    _verify_hashed_document(geometry_contract, "contract_id", "contract_sha256", "dgpc")
    _validate_execution(execution, contract)
    expected_diagnostic_roles = set(contract["outputs"]) - {
        "contact_pairs",
        "front_owner",
        "boundary_pairs",
    }
    if set(diagnostic_paths) != expected_diagnostic_roles:
        raise RelationshipPassContractError(
            "relationship_diagnostic_paths_invalid",
            str(sorted(diagnostic_paths)),
        )
    if (
        instance_contract["contract_id"] != contract["instance_contract_id"]
        or instance_contract["contract_sha256"] != contract["instance_contract_sha256"]
        or geometry_contract["contract_id"] != contract["geometry_contract_id"]
        or geometry_contract["contract_sha256"] != contract["geometry_contract_sha256"]
        or any(
            execution[field] != contract[field]
            for field in ("scene_id", "contract_id", "contract_sha256", "plan_id", "plan_sha256")
        )
    ):
        raise RelationshipPassContractError(
            "relationship_execution_lineage_invalid", execution["contract_id"]
        )
    instance, instance_codec = decode_u16_png_exact(instance_path)
    depth, depth_codec = decode_float32_exr(
        depth_path,
        role="depth",
        expected_resolution=contract["outputs"]["front_owner"]["resolution"],
        policy=geometry_policy,
    )
    contact_pairs, contact_codec = decode_pair_u16_png(contact_pairs_path)
    front_owner, front_codec = decode_u16_png_exact(front_owner_path)
    boundary_pairs, boundary_codec = decode_pair_u16_png(boundary_pairs_path)
    paths: dict[str, Path] = {
        "instance": Path(instance_path),
        "depth": Path(depth_path),
        "contact_pairs": Path(contact_pairs_path),
        "front_owner": Path(front_owner_path),
        "boundary_pairs": Path(boundary_pairs_path),
        **{role: Path(path) for role, path in diagnostic_paths.items()},
    }
    hashes = {role: hashlib.sha256(path.read_bytes()).hexdigest() for role, path in paths.items()}
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
            _finding(findings, "RELATIONSHIP_SCENE_STATE_MUTATION", f"/{field}", execution[field])
    for field, expected, code in (
        ("sidecar_plan_sha256", contract["plan_sha256"], "RELATIONSHIP_SIDECAR_PLAN_MISMATCH"),
        (
            "sidecar_contract_sha256",
            contract["contract_sha256"],
            "RELATIONSHIP_SIDECAR_CONTRACT_MISMATCH",
        ),
        (
            "sidecar_instance_contract_sha256",
            contract["instance_contract_sha256"],
            "RELATIONSHIP_SIDECAR_INSTANCE_MISMATCH",
        ),
        (
            "sidecar_geometry_contract_sha256",
            contract["geometry_contract_sha256"],
            "RELATIONSHIP_SIDECAR_GEOMETRY_MISMATCH",
        ),
        ("instance_file_sha256", hashes["instance"], "RELATIONSHIP_INSTANCE_HASH_MISMATCH"),
        ("depth_file_sha256", hashes["depth"], "RELATIONSHIP_DEPTH_HASH_MISMATCH"),
    ):
        if execution[field] != expected:
            _finding(findings, code, f"/{field}", execution[field])
    for role in contract["outputs"]:
        output = execution["outputs"][role]
        expected_output = contract["outputs"][role]
        for field in ("role", "encoding", "resolution", "crop", "train_eligible"):
            if output[field] != expected_output[field]:
                _finding(
                    findings,
                    "RELATIONSHIP_OUTPUT_CONTRACT_MISMATCH",
                    f"/outputs/{role}/{field}",
                    str(output[field]),
                )
        forbidden = sorted(set(output["effects"]) & set(policy["forbidden_effects"]))
        if forbidden:
            _finding(
                findings,
                "RELATIONSHIP_EFFECT_FORBIDDEN",
                f"/outputs/{role}/effects",
                ",".join(forbidden),
            )
        if output["file_sha256"] != hashes[role]:
            _finding(
                findings,
                "RELATIONSHIP_FILE_HASH_MISMATCH",
                f"/outputs/{role}/file_sha256",
                output["file_sha256"],
            )
        if output["bytes"] != paths[role].stat().st_size or output["bytes"] <= 0:
            _finding(
                findings,
                "RELATIONSHIP_BYTE_COUNT_MISMATCH",
                f"/outputs/{role}/bytes",
                str(output["bytes"]),
            )
        if output["completed"] is not True or output["interrupted"] is not False:
            _finding(
                findings,
                "RELATIONSHIP_OUTPUT_INCOMPLETE",
                f"/outputs/{role}/completed",
                str(output),
            )
        if execution["repeated_file_sha256s"][role] != hashes[role]:
            _finding(
                findings,
                "RELATIONSHIP_REPLAY_MISMATCH",
                f"/repeated_file_sha256s/{role}",
                execution["repeated_file_sha256s"][role],
            )
    shape_set = {
        instance.shape,
        depth.shape,
        front_owner.shape,
        contact_pairs.shape[:2],
        boundary_pairs.shape[:2],
    }
    pair_records: list[dict[str, Any]] = []
    directed_relationships: list[dict[str, Any]] = []
    if len(shape_set) != 1:
        _finding(findings, "RELATIONSHIP_RESOLUTION_MISMATCH", "/rasters", str(shape_set))
        metrics = _empty_metrics()
    else:
        metrics = _raster_metrics(
            contract,
            instance,
            contact_pairs,
            front_owner,
            boundary_pairs,
            findings,
        )
        observation_by_pair = _validate_observations(observations, contract)
        for pair in contract["pairs"]:
            key = tuple(pair)
            observation = observation_by_pair[key]
            record, directed = _evaluate_pair_observation(
                pair,
                observation,
                instance,
                depth,
                front_owner,
                boundary_pairs,
                policy,
                findings,
            )
            pair_records.append(record)
            directed_relationships.extend(directed)
            contact_pixels = np.all(contact_pairs == pair, axis=2)
            if np.any(contact_pixels) and not record["contact"]:
                _finding(
                    findings,
                    "RELATIONSHIP_CONTACT_RASTER_WITHOUT_3D_CONTACT",
                    f"/pairs/{pair[0]}-{pair[1]}",
                    str(int(np.count_nonzero(contact_pixels))),
                )
    if contract["profile"] == "diagnostic_full":
        amodal = execution["outputs"]["amodal_geometry"]
        if (
            amodal["logical_path"] != contract["amodal_physical_root"]
            or amodal["physically_separate"] is not True
            or amodal["absent_from_normal_training_exports"] is not True
        ):
            _finding(
                findings,
                "RELATIONSHIP_AMODAL_BOUNDARY_INVALID",
                "/outputs/amodal_geometry",
                str(amodal),
            )
    findings.sort(key=lambda row: (row["code"], row["path"], row["detail"]))
    pair_records.sort(key=lambda row: row["pair"])
    directed_relationships.sort(
        key=lambda row: (row["source_instance_id"], row["target_instance_id"], row["type"])
    )
    content = {
        "scene_id": contract["scene_id"],
        "contract_id": contract["contract_id"],
        "contract_sha256": contract["contract_sha256"],
        "plan_id": contract["plan_id"],
        "plan_sha256": contract["plan_sha256"],
        "scene_state_sha256": contract["scene_state_sha256"],
        "instance_contract_sha256": contract["instance_contract_sha256"],
        "geometry_contract_sha256": contract["geometry_contract_sha256"],
        "execution_sha256": _canonical_sha(execution),
        "file_hashes": hashes,
        "instance_codec": instance_codec,
        "depth_codec": depth_codec,
        "contact_pairs_codec": contact_codec,
        "front_owner_codec": front_codec,
        "boundary_pairs_codec": boundary_codec,
        "pair_records": pair_records,
        "directed_relationships": directed_relationships,
        "metrics": metrics,
        "findings": findings,
        "summary": {
            "passed": not findings,
            "finding_count": len(findings),
            "failure_codes": sorted({row["code"] for row in findings}),
            "scene_state_unchanged": not any("MUTATION" in row["code"] for row in findings),
            "pair_count": len(contract["pairs"]),
            "contact_pair_count": sum(record["contact"] for record in pair_records),
            "reciprocal_relationships_exact": not any(
                "RECIPROCAL" in row["code"] for row in findings
            ),
        },
    }
    digest = _canonical_sha(content)
    report = {
        "schema_version": "1.0.0",
        "report_id": f"drpr_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    require_valid_document(report, "daz_relationship_pass_report")
    return report


def publish_relationship_document(
    document: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    if "report_id" in document:
        schema, name = "daz_relationship_pass_report", document["report_id"]
    elif "contract_id" in document:
        schema, name = "daz_relationship_pass_contract", document["contract_id"]
    else:
        raise RelationshipPassContractError(
            "relationship_publication_document_unknown", str(document)
        )
    require_valid_document(document, schema)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{name}.json"
    payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise RelationshipPassContractError("relationship_publication_conflict", str(target))
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


def _raster_metrics(
    contract: Mapping[str, Any],
    instance: np.ndarray,
    contact_pairs: np.ndarray,
    front_owner: np.ndarray,
    boundary_pairs: np.ndarray,
    findings: list[dict[str, str]],
) -> dict[str, int]:
    allowed_pairs = {tuple(pair) for pair in contract["pairs"]}
    contact_nonzero = np.any(contact_pairs != 0, axis=2)
    boundary_nonzero = np.any(boundary_pairs != 0, axis=2)
    invalid_pair_order = 0
    unknown_pair = 0
    for name, raster, nonzero in (
        ("contact", contact_pairs, contact_nonzero),
        ("boundary", boundary_pairs, boundary_nonzero),
    ):
        invalid = nonzero & (
            (raster[..., 0] == 0) | (raster[..., 1] == 0) | (raster[..., 0] >= raster[..., 1])
        )
        count = int(np.count_nonzero(invalid))
        invalid_pair_order += count
        if count:
            _finding(
                findings,
                "RELATIONSHIP_PAIR_ENCODING_INVALID",
                f"/rasters/{name}",
                str(count),
            )
        for pair in np.unique(raster.reshape(-1, 2), axis=0):
            key = tuple(int(value) for value in pair)
            if key != (0, 0) and key not in allowed_pairs:
                unknown_pair += int(np.count_nonzero(np.all(raster == pair, axis=2)))
    if unknown_pair:
        _finding(
            findings,
            "RELATIONSHIP_PAIR_UNKNOWN",
            "/rasters",
            str(unknown_pair),
        )
    contact_outside_boundary = int(
        np.count_nonzero(contact_nonzero & np.any(contact_pairs != boundary_pairs, axis=2))
    )
    if contact_outside_boundary:
        _finding(
            findings,
            "RELATIONSHIP_CONTACT_NOT_BOUNDARY_SUBSET",
            "/rasters/contact_pairs",
            str(contact_outside_boundary),
        )
    front_mismatch = int(
        np.count_nonzero(
            boundary_nonzero
            & (
                (front_owner != instance)
                | (
                    (front_owner != boundary_pairs[..., 0])
                    & (front_owner != boundary_pairs[..., 1])
                )
            )
        )
    )
    front_orphan = int(np.count_nonzero(~boundary_nonzero & (front_owner != 0)))
    if front_mismatch or front_orphan:
        _finding(
            findings,
            "RELATIONSHIP_FRONT_OWNER_INVALID",
            "/rasters/front_owner",
            str(front_mismatch + front_orphan),
        )
    adjacency_invalid = 0
    ys, xs = np.nonzero(boundary_nonzero)
    height, width = instance.shape
    for y, x in zip(ys.tolist(), xs.tolist(), strict=True):
        pair = boundary_pairs[y, x]
        other = int(pair[1] if instance[y, x] == pair[0] else pair[0])
        y0, y1 = max(0, y - 1), min(height, y + 2)
        x0, x1 = max(0, x - 1), min(width, x + 2)
        if not np.any(instance[y0:y1, x0:x1] == other):
            adjacency_invalid += 1
    if adjacency_invalid:
        _finding(
            findings,
            "RELATIONSHIP_BOUNDARY_ADJACENCY_INVALID",
            "/rasters/boundary_pairs",
            str(adjacency_invalid),
        )
    observed_boundary_pairs = {
        tuple(int(value) for value in pair)
        for pair in np.unique(boundary_pairs[boundary_nonzero], axis=0)
    }
    actual_adjacency_pairs = _instance_adjacency_pairs(instance, set(contract["owner_ids"]))
    missing_pairs = sorted(actual_adjacency_pairs - observed_boundary_pairs)
    if missing_pairs:
        _finding(
            findings,
            "RELATIONSHIP_BOUNDARY_PAIR_MISSING",
            "/rasters/boundary_pairs",
            str(missing_pairs),
        )
    return {
        "contact_pixels": int(np.count_nonzero(contact_nonzero)),
        "boundary_pixels": int(np.count_nonzero(boundary_nonzero)),
        "invalid_pair_order_pixels": invalid_pair_order,
        "unknown_pair_pixels": unknown_pair,
        "contact_outside_boundary_pixels": contact_outside_boundary,
        "front_owner_invalid_pixels": front_mismatch + front_orphan,
        "boundary_adjacency_invalid_pixels": adjacency_invalid,
        "missing_adjacent_pair_count": len(missing_pairs),
    }


def _validate_observations(
    observations: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]
) -> dict[tuple[int, int], Mapping[str, Any]]:
    if not isinstance(observations, list):
        raise RelationshipPassContractError("relationship_observations_invalid", str(observations))
    result: dict[tuple[int, int], Mapping[str, Any]] = {}
    fields = {
        "pair",
        "minimum_surface_distance_mm",
        "maximum_penetration_mm",
        "minimum_normal_dot",
        "contact_regions",
        "depth_samples",
    }
    for observation in observations:
        if not isinstance(observation, Mapping) or set(observation) != fields:
            raise RelationshipPassContractError(
                "relationship_observation_fields_invalid", str(observation)
            )
        pair = observation["pair"]
        pair_is_valid = (
            isinstance(pair, list)
            and len(pair) == 2
            and all(isinstance(value, int) and not isinstance(value, bool) for value in pair)
        )
        key = tuple(pair) if pair_is_valid else ()
        if (
            not pair_is_valid
            or pair not in contract["pairs"]
            or key in result
            or not _finite_nonnegative(observation["minimum_surface_distance_mm"])
            or not _finite_nonnegative(observation["maximum_penetration_mm"])
            or not _finite_range(observation["minimum_normal_dot"], -1, 1)
            or not isinstance(observation["contact_regions"], list)
            or not isinstance(observation["depth_samples"], list)
        ):
            raise RelationshipPassContractError(
                "relationship_observation_invalid", str(observation)
            )
        for region in observation["contact_regions"]:
            if (
                not isinstance(region, Mapping)
                or set(region) != {"a_part_id", "b_part_id", "area_mm2"}
                or any(
                    isinstance(region[field], bool)
                    or not isinstance(region[field], int)
                    or not 0 <= region[field] <= 65535
                    for field in ("a_part_id", "b_part_id")
                )
                or not _finite_positive(region["area_mm2"])
            ):
                raise RelationshipPassContractError(
                    "relationship_contact_region_invalid", str(region)
                )
        result[key] = observation
    expected = {tuple(pair) for pair in contract["pairs"]}
    if set(result) != expected:
        raise RelationshipPassContractError(
            "relationship_observation_pair_set_invalid", str(sorted(result))
        )
    return result


def _evaluate_pair_observation(
    pair: list[int],
    observation: Mapping[str, Any],
    instance: np.ndarray,
    depth: np.ndarray,
    front_owner: np.ndarray,
    boundary_pairs: np.ndarray,
    policy: Mapping[str, Any],
    findings: list[dict[str, str]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    minimum_distance, maximum_distance = policy["contact"]["intended_distance_mm"]
    contact = (
        minimum_distance <= observation["minimum_surface_distance_mm"] <= maximum_distance
        and observation["maximum_penetration_mm"] <= policy["contact"]["maximum_penetration_mm"]
        and observation["minimum_normal_dot"] >= policy["contact"]["minimum_normal_dot"]
        and bool(observation["contact_regions"])
    )
    a_front = b_front = ties = 0
    for index, sample in enumerate(observation["depth_samples"]):
        if (
            not isinstance(sample, Mapping)
            or set(sample) != {"x", "y", "a_depth_m", "b_depth_m", "visible_owner"}
            or any(
                isinstance(sample[field], bool) or not isinstance(sample[field], int)
                for field in ("x", "y", "visible_owner")
            )
            or not _finite_positive(sample["a_depth_m"])
            or not _finite_positive(sample["b_depth_m"])
            or sample["visible_owner"] not in pair
            or not 0 <= sample["y"] < instance.shape[0]
            or not 0 <= sample["x"] < instance.shape[1]
        ):
            raise RelationshipPassContractError("relationship_depth_sample_invalid", str(sample))
        x, y = sample["x"], sample["y"]
        if (
            list(int(value) for value in boundary_pairs[y, x]) != pair
            or int(instance[y, x]) != sample["visible_owner"]
            or int(front_owner[y, x]) != sample["visible_owner"]
            or not math.isclose(
                float(depth[y, x]),
                sample["a_depth_m"] if sample["visible_owner"] == pair[0] else sample["b_depth_m"],
                abs_tol=1e-6,
                rel_tol=0,
            )
        ):
            _finding(
                findings,
                "RELATIONSHIP_DEPTH_SAMPLE_AUTHORITY_MISMATCH",
                f"/pairs/{pair[0]}-{pair[1]}/depth_samples/{index}",
                str(sample),
            )
        difference = sample["a_depth_m"] - sample["b_depth_m"]
        epsilon = policy["occlusion"]["depth_tie_epsilon_m"]
        if abs(difference) <= epsilon:
            ties += 1
        elif difference < 0:
            a_front += 1
            if sample["visible_owner"] != pair[0]:
                _finding(
                    findings,
                    "RELATIONSHIP_DEPTH_ORDER_INVALID",
                    f"/pairs/{pair[0]}-{pair[1]}/depth_samples/{index}",
                    str(sample),
                )
        else:
            b_front += 1
            if sample["visible_owner"] != pair[1]:
                _finding(
                    findings,
                    "RELATIONSHIP_DEPTH_ORDER_INVALID",
                    f"/pairs/{pair[0]}-{pair[1]}/depth_samples/{index}",
                    str(sample),
                )
    sample_count = len(observation["depth_samples"])
    confidence = (a_front + b_front) / sample_count if sample_count else 0.0
    if a_front and b_front:
        direction = "mixed"
    elif a_front:
        direction = "a_front"
    elif b_front:
        direction = "b_front"
    else:
        direction = "none"
    boundary_mask = np.all(boundary_pairs == pair, axis=2)
    visible_boundary_pixels = int(np.count_nonzero(boundary_mask))
    if visible_boundary_pixels and confidence < policy["occlusion"]["minimum_confidence"]:
        _finding(
            findings,
            "RELATIONSHIP_DEPTH_CONFIDENCE_LOW",
            f"/pairs/{pair[0]}-{pair[1]}",
            str(confidence),
        )
    record = {
        "pair": pair,
        "minimum_surface_distance_mm": observation["minimum_surface_distance_mm"],
        "maximum_penetration_mm": observation["maximum_penetration_mm"],
        "minimum_normal_dot": observation["minimum_normal_dot"],
        "contact": contact,
        "contact_regions": [dict(region) for region in observation["contact_regions"]],
        "visible_boundary_pixels": visible_boundary_pixels,
        "front_owner_counts": {
            str(pair[0]): int(np.count_nonzero(boundary_mask & (front_owner == pair[0]))),
            str(pair[1]): int(np.count_nonzero(boundary_mask & (front_owner == pair[1]))),
        },
        "depth_sample_count": sample_count,
        "depth_tie_count": ties,
        "occlusion_direction": direction,
        "depth_order_confidence": confidence,
    }
    directed: list[dict[str, Any]] = []
    if contact:
        directed.extend(
            [
                {"source_instance_id": pair[0], "target_instance_id": pair[1], "type": "contact"},
                {"source_instance_id": pair[1], "target_instance_id": pair[0], "type": "contact"},
            ]
        )
    if direction in {"a_front", "mixed"}:
        directed.extend(
            [
                {"source_instance_id": pair[0], "target_instance_id": pair[1], "type": "occludes"},
                {
                    "source_instance_id": pair[1],
                    "target_instance_id": pair[0],
                    "type": "occluded_by",
                },
            ]
        )
    if direction in {"b_front", "mixed"}:
        directed.extend(
            [
                {"source_instance_id": pair[1], "target_instance_id": pair[0], "type": "occludes"},
                {
                    "source_instance_id": pair[0],
                    "target_instance_id": pair[1],
                    "type": "occluded_by",
                },
            ]
        )
    return record, directed


def _instance_adjacency_pairs(instance: np.ndarray, allowed: set[int]) -> set[tuple[int, int]]:
    pairs: set[tuple[int, int]] = set()
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
        y1 = slice(max(0, dy), instance.shape[0] + min(0, dy))
        y2 = slice(max(0, -dy), instance.shape[0] + min(0, -dy))
        x1 = slice(max(0, dx), instance.shape[1] + min(0, dx))
        x2 = slice(max(0, -dx), instance.shape[1] + min(0, -dx))
        left, right = instance[y1, x1], instance[y2, x2]
        mask = (left != right) & np.isin(left, tuple(allowed)) & np.isin(right, tuple(allowed))
        for a, b in zip(left[mask].tolist(), right[mask].tolist(), strict=True):
            pairs.add(tuple(sorted((int(a), int(b)))))
    return pairs


def _undo_png_filter(
    current: np.ndarray, previous: np.ndarray, filter_type: int, *, bytes_per_pixel: int
) -> None:
    if filter_type == 0:
        return
    for index in range(len(current)):
        left = int(current[index - bytes_per_pixel]) if index >= bytes_per_pixel else 0
        up = int(previous[index])
        up_left = int(previous[index - bytes_per_pixel]) if index >= bytes_per_pixel else 0
        if filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = up
        elif filter_type == 3:
            predictor = (left + up) // 2
        elif filter_type == 4:
            predictor = _paeth(left, up, up_left)
        else:
            raise RelationshipPassContractError(
                "relationship_pair_png_filter_invalid", str(filter_type)
            )
        current[index] = (int(current[index]) + predictor) & 0xFF


def _paeth(a: int, b: int, c: int) -> int:
    prediction = a + b - c
    distance_a = abs(prediction - a)
    distance_b = abs(prediction - b)
    distance_c = abs(prediction - c)
    if distance_a <= distance_b and distance_a <= distance_c:
        return a
    if distance_b <= distance_c:
        return b
    return c


def _validate_execution(execution: Any, contract: Mapping[str, Any]) -> None:
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
        "sidecar_instance_contract_sha256",
        "sidecar_geometry_contract_sha256",
        "instance_file_sha256",
        "depth_file_sha256",
        "outputs",
        "repeated_file_sha256s",
    }
    if not isinstance(execution, Mapping) or set(execution) != expected:
        raise RelationshipPassContractError("relationship_execution_fields_invalid", str(execution))
    for field, value in execution.items():
        if field.endswith("_sha256") and not _sha256(value):
            raise RelationshipPassContractError("relationship_execution_hash_invalid", field)
    if (
        execution["schema_version"] != "1.0.0"
        or set(execution["outputs"]) != set(contract["outputs"])
        or set(execution["repeated_file_sha256s"]) != set(contract["outputs"])
    ):
        raise RelationshipPassContractError(
            "relationship_execution_outputs_invalid", str(execution["outputs"])
        )
    base_fields = {
        "role",
        "encoding",
        "resolution",
        "crop",
        "train_eligible",
        "effects",
        "file_sha256",
        "bytes",
        "completed",
        "interrupted",
    }
    amodal_extra = {"logical_path", "physically_separate", "absent_from_normal_training_exports"}
    for role, output in execution["outputs"].items():
        expected_fields = base_fields | (amodal_extra if role == "amodal_geometry" else set())
        if (
            not isinstance(output, Mapping)
            or set(output) != expected_fields
            or output["role"] != role
            or output["train_eligible"] is not False
            or not isinstance(output["effects"], list)
        ):
            raise RelationshipPassContractError("relationship_execution_output_invalid", role)


def _empty_metrics() -> dict[str, int]:
    return {
        "contact_pixels": -1,
        "boundary_pixels": -1,
        "invalid_pair_order_pixels": -1,
        "unknown_pair_pixels": -1,
        "contact_outside_boundary_pixels": -1,
        "front_owner_invalid_pixels": -1,
        "boundary_adjacency_invalid_pixels": -1,
        "missing_adjacent_pair_count": -1,
    }


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
        raise RelationshipPassContractError(
            "relationship_document_hash_invalid", str(document.get(id_field))
        )


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
        raise RelationshipPassContractError("relationship_noncanonical_value", str(exc)) from exc
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _finite_nonnegative(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) >= 0
    )


def _finite_positive(value: Any) -> bool:
    return _finite_nonnegative(value) and float(value) > 0


def _finite_range(value: Any, minimum: float, maximum: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and minimum <= float(value) <= maximum
    )


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _finding(findings: list[dict[str, str]], code: str, path: str, detail: str) -> None:
    findings.append({"code": code, "path": path, "detail": detail})
