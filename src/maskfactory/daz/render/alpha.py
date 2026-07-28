"""Exact linear coverage alpha, deterministic ownership, and hair transparency."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import yaml

from ...validation import require_valid_document
from .instance import decode_u16_png_exact


class CoverageAlphaContractError(ValueError):
    """A coverage-alpha policy, certificate, contract, execution, or raster is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_coverage_alpha_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_coverage_alpha_policy(document)
    return document


def validate_coverage_alpha_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "eligible_profiles",
        "codec",
        "boundary",
        "hair",
        "freeze",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise CoverageAlphaContractError("alpha_policy_fields_invalid", str(policy))
    if policy["schema_version"] != "1.0.0" or policy["policy_version"] != "1.0.0":
        raise CoverageAlphaContractError("alpha_policy_identity_invalid", str(policy))
    if policy["eligible_profiles"] != [
        "training_standard",
        "training_relationship",
        "diagnostic_full",
    ]:
        raise CoverageAlphaContractError(
            "alpha_policy_profiles_invalid", str(policy["eligible_profiles"])
        )
    if policy["codec"] != {
        "encoding": "uint16_linear_png",
        "color_space": "linear",
        "background_value": 0,
        "minimum_value": 0,
        "maximum_value": 65535,
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
        raise CoverageAlphaContractError("alpha_policy_codec_invalid", str(policy["codec"]))
    if policy["boundary"] != {
        "sample_grid": "4x4",
        "sample_count": 16,
        "visibility_threshold": 1 / 255,
        "minimum_nonzero_code": 257,
        "binary_ownership_threshold": 0.5,
        "hard_owner_minimum_code": 32768,
        "ownership_rule": "maximum_visible_coverage",
        "tie_break": ["frontmost_depth", "stable_node_id"],
        "transparent_surface_handling": "evaluated_opacity",
        "downsample_filter": "box_linear",
        "edge_uncertainty_radius_pixels": 1,
    }:
        raise CoverageAlphaContractError("alpha_policy_boundary_invalid", str(policy["boundary"]))
    if policy["hair"] != {
        "canonical_part_id": 1,
        "canonical_material_id": 2,
        "certificate_required_for_visible_hair": True,
        "constructions": {
            "polygonal": "ordinary_depth_visibility",
            "transmapped_cards": "evaluated_opacity",
            "strand_based": "renderer_coverage_or_exact_opacity",
            "fibermesh": "ordinary_depth_visibility",
            "mixed": "evaluated_opacity_and_depth",
        },
        "opacity_below_binary_threshold_defers_to_underlying_owner": True,
        "mixed_pixels_retain_continuous_alpha": True,
        "shadows_never_create_hair_ownership": True,
        "continuous_alpha_train_eligible": False,
    }:
        raise CoverageAlphaContractError("alpha_policy_hair_invalid", str(policy["hair"]))
    if policy["freeze"] != {
        "exact_scene_state_before_sidecar_after_restore_terminal": True,
        "exact_plan_contract_mapping_and_ontology_sidecars": True,
        "material_part_instance_authority_hashes_required": True,
        "repeated_coverage_alpha_hash_required": True,
    }:
        raise CoverageAlphaContractError("alpha_policy_freeze_invalid", str(policy["freeze"]))


def build_hair_alpha_certificate(
    *,
    asset_id: str,
    asset_sha256: str,
    mapping_sha256: str,
    construction: str,
    renderer_id: str,
    renderer_version: str,
    pass_route: str,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Seal one hair asset to its supported opacity route and exact thresholds."""

    validate_coverage_alpha_policy(policy)
    route = policy["hair"]["constructions"].get(construction)
    if not asset_id or not renderer_id or not renderer_version:
        raise CoverageAlphaContractError("alpha_certificate_identity_invalid", asset_id)
    if not _sha256(asset_sha256) or not _sha256(mapping_sha256):
        raise CoverageAlphaContractError("alpha_certificate_hash_invalid", asset_id)
    if route is None or pass_route != route:
        raise CoverageAlphaContractError(
            "alpha_certificate_route_invalid", f"{construction}:{pass_route}"
        )
    content = {
        "asset_id": asset_id,
        "asset_sha256": asset_sha256,
        "mapping_sha256": mapping_sha256,
        "construction": construction,
        "renderer_id": renderer_id,
        "renderer_version": renderer_version,
        "pass_route": pass_route,
        "visibility_threshold": policy["boundary"]["visibility_threshold"],
        "binary_ownership_threshold": policy["boundary"]["binary_ownership_threshold"],
        "evaluated_opacity_required": construction
        in {"transmapped_cards", "strand_based", "mixed"},
        "shadow_ownership_forbidden": True,
        "approved": True,
    }
    digest = _canonical_sha(content)
    return {
        "schema_version": "1.0.0",
        "certificate_id": f"dhac_{digest[:24]}",
        "certificate_sha256": digest,
        **content,
    }


def resolve_visible_coverage_owner(
    candidates: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]
) -> dict[str, Any]:
    """Resolve one pixel from 16 visible-opacity samples using the frozen tie break."""

    validate_coverage_alpha_policy(policy)
    normalized: list[tuple[int, float, float, str]] = []
    seen: set[int] = set()
    sample_totals = np.zeros(policy["boundary"]["sample_count"], dtype=np.float64)
    for candidate in candidates:
        if set(candidate) != {
            "owner_id",
            "visible_opacity_samples",
            "frontmost_depth",
            "stable_node_id",
        }:
            raise CoverageAlphaContractError("alpha_candidate_fields_invalid", str(candidate))
        owner_id = candidate["owner_id"]
        samples = candidate["visible_opacity_samples"]
        depth = candidate["frontmost_depth"]
        node_id = candidate["stable_node_id"]
        if (
            isinstance(owner_id, bool)
            or not isinstance(owner_id, int)
            or owner_id <= 0
            or owner_id in seen
            or not isinstance(samples, list)
            or len(samples) != policy["boundary"]["sample_count"]
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0 <= float(value) <= 1
                for value in samples
            )
            or isinstance(depth, bool)
            or not isinstance(depth, (int, float))
            or not math.isfinite(float(depth))
            or float(depth) < 0
            or not isinstance(node_id, str)
            or not node_id
        ):
            raise CoverageAlphaContractError("alpha_candidate_invalid", str(candidate))
        seen.add(owner_id)
        sample_totals += np.asarray(samples, dtype=np.float64)
        normalized.append((owner_id, float(np.mean(samples)), float(depth), node_id))
    if np.any(sample_totals > 1.0 + 1e-9):
        raise CoverageAlphaContractError(
            "alpha_candidate_visibility_overflow", str(float(sample_totals.max()))
        )
    if not normalized:
        return {"hard_owner_id": 0, "coverage": 0.0, "coverage_u16": 0}
    normalized.sort(key=lambda row: (-row[1], row[2], row[3]))
    winner, coverage, _depth, _node = normalized[0]
    if coverage < policy["boundary"]["visibility_threshold"]:
        return {"hard_owner_id": 0, "coverage": 0.0, "coverage_u16": 0}
    coverage_u16 = int(math.floor(coverage * 65535 + 0.5))
    hard_owner = winner if coverage >= policy["boundary"]["binary_ownership_threshold"] else 0
    return {
        "hard_owner_id": hard_owner,
        "coverage": coverage,
        "coverage_u16": coverage_u16,
    }


def build_coverage_alpha_contract(
    material_contract: Mapping[str, Any],
    pass_plan: Mapping[str, Any],
    hair_certificates: list[Mapping[str, Any]],
    *,
    expected_hair_material_present: bool,
    expected_mixed_coverage: bool,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind continuous alpha and hair rules to frozen semantic authority."""

    validate_coverage_alpha_policy(policy)
    require_valid_document(material_contract, "daz_material_protected_contract")
    _verify_hashed_document(material_contract, "contract_id", "contract_sha256", "dmpc")
    require_valid_document(pass_plan, "daz_render_pass_plan")
    _verify_hashed_document(pass_plan, "plan_id", "plan_sha256", "dcrp")
    if (
        pass_plan["profile"] not in policy["eligible_profiles"]
        or pass_plan["plan_id"] != material_contract["plan_id"]
        or pass_plan["plan_sha256"] != material_contract["plan_sha256"]
        or pass_plan["scene_id"] != material_contract["scene_id"]
        or pass_plan["scene_state_sha256"] != material_contract["scene_state_sha256"]
    ):
        raise CoverageAlphaContractError("alpha_plan_lineage_invalid", pass_plan["plan_id"])
    outputs = {row["role"]: row for row in pass_plan["outputs"]}
    output = outputs.get("coverage_alpha")
    if output is None or output["encoding"] != "uint16_linear_png":
        raise CoverageAlphaContractError("alpha_output_missing", pass_plan["profile"])
    if not isinstance(expected_hair_material_present, bool) or not isinstance(
        expected_mixed_coverage, bool
    ):
        raise CoverageAlphaContractError("alpha_expectation_invalid", "bool")
    certificates = [_validate_certificate(document, policy) for document in hair_certificates]
    asset_ids = [document["asset_id"] for document in certificates]
    if asset_ids != sorted(set(asset_ids)):
        raise CoverageAlphaContractError("alpha_certificates_unsorted_or_duplicate", str(asset_ids))
    if expected_hair_material_present and not certificates:
        raise CoverageAlphaContractError("alpha_visible_hair_certificate_missing", "hair")
    if not expected_hair_material_present and certificates:
        raise CoverageAlphaContractError("alpha_unexpected_hair_certificate", str(asset_ids))
    if any(
        certificate["mapping_sha256"] != material_contract["mapping_sha256"]
        for certificate in certificates
    ):
        raise CoverageAlphaContractError("alpha_certificate_mapping_mismatch", str(asset_ids))
    content = {
        "scene_id": material_contract["scene_id"],
        "scene_state_sha256": material_contract["scene_state_sha256"],
        "plan_id": pass_plan["plan_id"],
        "plan_sha256": pass_plan["plan_sha256"],
        "material_contract_id": material_contract["contract_id"],
        "material_contract_sha256": material_contract["contract_sha256"],
        "ontology_snapshot_sha256": material_contract["ontology_snapshot_sha256"],
        "mapping_sha256": material_contract["mapping_sha256"],
        "policy_sha256": _canonical_sha(policy),
        "policy_version": policy["policy_version"],
        "profile": pass_plan["profile"],
        "boundary": policy["boundary"],
        "hair_part_id": policy["hair"]["canonical_part_id"],
        "hair_material_id": policy["hair"]["canonical_material_id"],
        "hair_certificates": certificates,
        "expected_hair_material_present": expected_hair_material_present,
        "expected_mixed_coverage": expected_mixed_coverage,
        "output": {
            "role": "coverage_alpha",
            "encoding": "uint16_linear_png",
            "resolution": output["resolution"],
            "crop": output["crop"],
            "color_space": "linear",
            "background_value": 0,
            "downsample_filter": "box_linear",
        },
    }
    digest = _canonical_sha(content)
    document = {
        "schema_version": "1.0.0",
        "contract_id": f"dcac_{digest[:24]}",
        "contract_sha256": digest,
        **content,
    }
    require_valid_document(document, "daz_coverage_alpha_contract")
    return document


def evaluate_coverage_alpha(
    contract: Mapping[str, Any],
    execution: Mapping[str, Any],
    *,
    alpha_path: Path,
    material_path: Path,
    part_path: Path,
    instance_path: Path,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Decode alpha and verify hard ownership, hair thresholds, lineage, and replay."""

    validate_coverage_alpha_policy(policy)
    require_valid_document(contract, "daz_coverage_alpha_contract")
    _verify_hashed_document(contract, "contract_id", "contract_sha256", "dcac")
    _validate_execution(execution)
    if any(
        execution[field] != contract[field]
        for field in ("scene_id", "contract_id", "contract_sha256", "plan_id", "plan_sha256")
    ):
        raise CoverageAlphaContractError(
            "alpha_execution_lineage_invalid", execution["contract_id"]
        )
    alpha, alpha_codec = decode_u16_png_exact(alpha_path)
    material, material_codec = decode_u16_png_exact(material_path)
    part, part_codec = decode_u16_png_exact(part_path)
    instance, instance_codec = decode_u16_png_exact(instance_path)
    payloads = {
        "coverage_alpha": Path(alpha_path).read_bytes(),
        "material": Path(material_path).read_bytes(),
        "part": Path(part_path).read_bytes(),
        "instance": Path(instance_path).read_bytes(),
    }
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
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
            _finding(findings, "ALPHA_SCENE_STATE_MUTATION", f"/{field}", execution[field])
    for field, expected, code in (
        ("sidecar_plan_sha256", contract["plan_sha256"], "ALPHA_SIDECAR_PLAN_MISMATCH"),
        (
            "sidecar_contract_sha256",
            contract["contract_sha256"],
            "ALPHA_SIDECAR_CONTRACT_MISMATCH",
        ),
        (
            "sidecar_ontology_snapshot_sha256",
            contract["ontology_snapshot_sha256"],
            "ALPHA_SIDECAR_ONTOLOGY_MISMATCH",
        ),
        ("sidecar_mapping_sha256", contract["mapping_sha256"], "ALPHA_SIDECAR_MAPPING_MISMATCH"),
        ("material_file_sha256", hashes["material"], "ALPHA_AUTHORITY_HASH_MISMATCH"),
        ("part_file_sha256", hashes["part"], "ALPHA_AUTHORITY_HASH_MISMATCH"),
        ("instance_file_sha256", hashes["instance"], "ALPHA_AUTHORITY_HASH_MISMATCH"),
        (
            "repeated_coverage_alpha_file_sha256",
            hashes["coverage_alpha"],
            "ALPHA_SEMANTIC_REPLAY_MISMATCH",
        ),
    ):
        if execution[field] != expected:
            _finding(findings, code, f"/{field}", execution[field])
    output = execution["output"]
    for field in (
        "role",
        "encoding",
        "resolution",
        "crop",
        "color_space",
        "downsample_filter",
    ):
        if output[field] != contract["output"][field]:
            _finding(
                findings, "ALPHA_OUTPUT_CONTRACT_MISMATCH", f"/output/{field}", str(output[field])
            )
    forbidden = sorted(set(output["effects"]) & set(policy["codec"]["forbidden_effects"]))
    if forbidden:
        _finding(findings, "ALPHA_EFFECT_FORBIDDEN", "/output/effects", ",".join(forbidden))
    if output["file_sha256"] != hashes["coverage_alpha"]:
        _finding(findings, "ALPHA_FILE_HASH_MISMATCH", "/output/file_sha256", output["file_sha256"])
    if output["bytes"] != len(payloads["coverage_alpha"]) or not payloads["coverage_alpha"]:
        _finding(findings, "ALPHA_BYTE_COUNT_MISMATCH", "/output/bytes", str(output["bytes"]))
    if output["completed"] is not True or output["interrupted"] is not False:
        _finding(findings, "ALPHA_OUTPUT_INCOMPLETE", "/output/completed", str(output))
    shapes = {alpha.shape, material.shape, part.shape, instance.shape}
    if len(shapes) != 1:
        _finding(findings, "ALPHA_RESOLUTION_MISMATCH", "/rasters", str(shapes))
        metrics = _empty_metrics()
    else:
        metrics = _alpha_metrics(alpha, material, part, instance, contract)
        for key, code in (
            ("subvisibility_nonzero_pixels", "ALPHA_SUBVISIBILITY_NONZERO"),
            ("hard_owner_below_threshold_pixels", "ALPHA_HARD_OWNER_BELOW_THRESHOLD"),
            ("missing_hard_owner_pixels", "ALPHA_HARD_OWNER_MISSING"),
            ("hair_part_material_mismatch_pixels", "ALPHA_HAIR_SEMANTIC_MISMATCH"),
            ("hair_below_threshold_pixels", "ALPHA_HAIR_BELOW_THRESHOLD"),
        ):
            if metrics[key]:
                _finding(findings, code, f"/metrics/{key}", str(metrics[key]))
        if contract["expected_hair_material_present"] and not metrics["hair_hard_pixels"]:
            _finding(findings, "ALPHA_EXPECTED_HAIR_EMPTY", "/metrics/hair_hard_pixels", "0")
        if not contract["expected_hair_material_present"] and metrics["hair_hard_pixels"]:
            _finding(
                findings,
                "ALPHA_UNCERTIFIED_HAIR_VISIBLE",
                "/metrics/hair_hard_pixels",
                str(metrics["hair_hard_pixels"]),
            )
        if contract["expected_mixed_coverage"] and not metrics["mixed_coverage_pixels"]:
            _finding(findings, "ALPHA_EXPECTED_MIXED_EMPTY", "/metrics/mixed_coverage_pixels", "0")
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
        "alpha_codec": alpha_codec,
        "material_codec": material_codec,
        "part_codec": part_codec,
        "instance_codec": instance_codec,
        "metrics": metrics,
        "findings": findings,
        "summary": {
            "passed": not findings,
            "finding_count": len(findings),
            "failure_codes": sorted({row["code"] for row in findings}),
            "scene_state_unchanged": not any("MUTATION" in row["code"] for row in findings),
            "thresholds_exact": not any(
                token in row["code"]
                for row in findings
                for token in ("SUBVISIBILITY", "BELOW_THRESHOLD", "HARD_OWNER", "HAIR")
            ),
            "hair_certificate_count": len(contract["hair_certificates"]),
        },
    }
    digest = _canonical_sha(content)
    report = {
        "schema_version": "1.0.0",
        "report_id": f"dcar_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    require_valid_document(report, "daz_coverage_alpha_report")
    return report


def publish_coverage_alpha_document(
    document: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    if "report_id" in document:
        require_valid_document(document, "daz_coverage_alpha_report")
        name = document["report_id"]
    elif "contract_id" in document:
        require_valid_document(document, "daz_coverage_alpha_contract")
        name = document["contract_id"]
    else:
        raise CoverageAlphaContractError("alpha_publication_document_unknown", str(document))
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{name}.json"
    payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise CoverageAlphaContractError("alpha_publication_conflict", str(target))
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


def _validate_certificate(
    certificate: Mapping[str, Any], policy: Mapping[str, Any]
) -> dict[str, Any]:
    expected = {
        "schema_version",
        "certificate_id",
        "certificate_sha256",
        "asset_id",
        "asset_sha256",
        "mapping_sha256",
        "construction",
        "renderer_id",
        "renderer_version",
        "pass_route",
        "visibility_threshold",
        "binary_ownership_threshold",
        "evaluated_opacity_required",
        "shadow_ownership_forbidden",
        "approved",
    }
    if not isinstance(certificate, Mapping) or set(certificate) != expected:
        raise CoverageAlphaContractError("alpha_certificate_fields_invalid", str(certificate))
    _verify_hashed_document(certificate, "certificate_id", "certificate_sha256", "dhac")
    route = policy["hair"]["constructions"].get(certificate["construction"])
    if (
        route is None
        or certificate["pass_route"] != route
        or certificate["visibility_threshold"] != policy["boundary"]["visibility_threshold"]
        or certificate["binary_ownership_threshold"]
        != policy["boundary"]["binary_ownership_threshold"]
        or certificate["evaluated_opacity_required"]
        != (certificate["construction"] in {"transmapped_cards", "strand_based", "mixed"})
        or certificate["shadow_ownership_forbidden"] is not True
        or certificate["approved"] is not True
        or not _sha256(certificate["asset_sha256"])
        or not _sha256(certificate["mapping_sha256"])
    ):
        raise CoverageAlphaContractError("alpha_certificate_invalid", certificate["asset_id"])
    return dict(certificate)


def _alpha_metrics(
    alpha: np.ndarray,
    material: np.ndarray,
    part: np.ndarray,
    instance: np.ndarray,
    contract: Mapping[str, Any],
) -> dict[str, int]:
    minimum = contract["boundary"]["minimum_nonzero_code"]
    hard_minimum = contract["boundary"]["hard_owner_minimum_code"]
    hard = (material > 0) | (part > 0) | (instance > 0)
    hair_part = part == contract["hair_part_id"]
    hair_material = material == contract["hair_material_id"]
    return {
        "subvisibility_nonzero_pixels": int(np.count_nonzero((alpha > 0) & (alpha < minimum))),
        "hard_owner_below_threshold_pixels": int(np.count_nonzero(hard & (alpha < hard_minimum))),
        "missing_hard_owner_pixels": int(np.count_nonzero(~hard & (alpha >= hard_minimum))),
        "hair_part_material_mismatch_pixels": int(np.count_nonzero(hair_part ^ hair_material)),
        "hair_below_threshold_pixels": int(
            np.count_nonzero(hair_material & (alpha < hard_minimum))
        ),
        "hair_hard_pixels": int(np.count_nonzero(hair_material & hard)),
        "mixed_coverage_pixels": int(np.count_nonzero((alpha >= minimum) & (alpha < 65535))),
        "subthreshold_support_pixels": int(
            np.count_nonzero((alpha >= minimum) & (alpha < hard_minimum) & ~hard)
        ),
        "opaque_pixels": int(np.count_nonzero(alpha == 65535)),
    }


def _empty_metrics() -> dict[str, int]:
    return {
        "subvisibility_nonzero_pixels": -1,
        "hard_owner_below_threshold_pixels": -1,
        "missing_hard_owner_pixels": -1,
        "hair_part_material_mismatch_pixels": -1,
        "hair_below_threshold_pixels": -1,
        "hair_hard_pixels": -1,
        "mixed_coverage_pixels": -1,
        "subthreshold_support_pixels": -1,
        "opaque_pixels": -1,
    }


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
        "sidecar_ontology_snapshot_sha256",
        "sidecar_mapping_sha256",
        "material_file_sha256",
        "part_file_sha256",
        "instance_file_sha256",
        "repeated_coverage_alpha_file_sha256",
        "output",
    }
    if not isinstance(execution, Mapping) or set(execution) != expected:
        raise CoverageAlphaContractError("alpha_execution_fields_invalid", str(execution))
    for key, value in execution.items():
        if key.endswith("_sha256") and not _sha256(value):
            raise CoverageAlphaContractError("alpha_execution_hash_invalid", key)
    output_fields = {
        "role",
        "encoding",
        "resolution",
        "crop",
        "color_space",
        "downsample_filter",
        "effects",
        "file_sha256",
        "bytes",
        "completed",
        "interrupted",
    }
    if (
        execution["schema_version"] != "1.0.0"
        or not isinstance(execution["output"], Mapping)
        or set(execution["output"]) != output_fields
        or execution["output"]["role"] != "coverage_alpha"
        or not isinstance(execution["output"]["effects"], list)
    ):
        raise CoverageAlphaContractError("alpha_execution_output_invalid", str(execution["output"]))


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
        raise CoverageAlphaContractError("alpha_document_hash_invalid", str(document.get(id_field)))


def _canonical_sha(document: Mapping[str, Any]) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _finding(findings: list[dict[str, str]], code: str, path: str, detail: str) -> None:
    findings.append({"code": code, "path": path, "detail": detail})
