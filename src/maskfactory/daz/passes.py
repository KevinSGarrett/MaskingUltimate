"""Closed render-pass profiles and immutable scene-state mutation detection."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..validation import require_valid_document


class RenderPassContractError(ValueError):
    """A pass profile, plan, or execution violates frozen scene-state authority."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_render_pass_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_render_pass_policy(document)
    return document


def validate_render_pass_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "boundary_convention",
        "integer_map_rules",
        "role_catalog",
        "profiles",
        "rgb_variant_rules",
        "freeze_rules",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise RenderPassContractError("pass_policy_fields_invalid", str(policy))
    if policy["schema_version"] != "1.0.0" or policy["policy_version"] != "1.0.0":
        raise RenderPassContractError("pass_policy_version_invalid", "version")
    expected_catalog = {
        "preview_rgb": {"encoding": "lossless_rgb_png", "semantic": False, "train_eligible": False},
        "rgb_pristine": {"encoding": "lossless_rgb_png", "semantic": False, "train_eligible": True},
        "rgb_variant": {"encoding": "lossless_rgb_png", "semantic": False, "train_eligible": True},
        "instance": {"encoding": "uint16_png", "semantic": True, "train_eligible": True},
        "part": {"encoding": "uint16_png", "semantic": True, "train_eligible": True},
        "material": {"encoding": "uint16_png", "semantic": True, "train_eligible": True},
        "protected": {"encoding": "uint16_png", "semantic": True, "train_eligible": True},
        "coverage_alpha": {
            "encoding": "uint16_linear_png",
            "semantic": True,
            "train_eligible": False,
        },
        "depth": {"encoding": "float32_exr", "semantic": True, "train_eligible": False},
        "normals": {
            "encoding": "float_exr_camera_space",
            "semantic": True,
            "train_eligible": False,
        },
        "contact_pairs": {
            "encoding": "two_channel_uint16_png",
            "semantic": True,
            "train_eligible": False,
        },
        "front_owner": {"encoding": "uint16_png", "semantic": True, "train_eligible": False},
        "boundary_pairs": {
            "encoding": "two_channel_uint16_png",
            "semantic": True,
            "train_eligible": False,
        },
        "surface": {"encoding": "uint32_exr", "semantic": True, "train_eligible": False},
        "facet": {"encoding": "uint32_exr", "semantic": True, "train_eligible": False},
        "node": {"encoding": "uint32_exr", "semantic": True, "train_eligible": False},
        "mapping_confidence": {
            "encoding": "uint16_linear_png",
            "semantic": True,
            "train_eligible": False,
        },
        "amodal_geometry": {
            "encoding": "diagnostic_tree",
            "semantic": True,
            "train_eligible": False,
        },
    }
    if policy["role_catalog"] != expected_catalog:
        raise RenderPassContractError("pass_policy_catalog_invalid", str(policy["role_catalog"]))
    standard = [
        "rgb_pristine",
        "instance",
        "part",
        "material",
        "protected",
        "depth",
        "normals",
        "coverage_alpha",
    ]
    relationship = [*standard, "contact_pairs", "front_owner", "boundary_pairs"]
    expected_profiles = {
        "engineering_minimal": ["preview_rgb", "instance", "part", "material"],
        "training_standard": standard,
        "training_relationship": relationship,
        "diagnostic_full": [
            *relationship,
            "surface",
            "facet",
            "node",
            "mapping_confidence",
            "amodal_geometry",
        ],
        "rgb_variant": ["rgb_variant"],
    }
    if policy["profiles"] != expected_profiles:
        raise RenderPassContractError("pass_policy_profiles_invalid", str(policy["profiles"]))
    expected_boundary = {
        "mode": "supersampled_deterministic_ownership",
        "sample_grid": "4x4",
        "alpha_threshold": 1 / 255,
        "ownership_rule": "maximum_visible_coverage",
        "tie_break": ["frontmost_depth", "stable_node_id"],
        "transparent_surface_handling": "evaluated_opacity",
        "hard_map_downsample_filter": "deterministic_ownership",
        "coverage_alpha_downsample_filter": "box_linear",
        "edge_uncertainty_radius_pixels": 1,
    }
    if policy["boundary_convention"] != expected_boundary:
        raise RenderPassContractError(
            "pass_policy_boundary_invalid", str(policy["boundary_convention"])
        )
    expected_integer_rules = {
        "exact_nearest_neighbor_decode": True,
        "forbidden": [
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
        "background_value": 0,
    }
    if policy["integer_map_rules"] != expected_integer_rules:
        raise RenderPassContractError(
            "pass_policy_integer_rules_invalid", str(policy["integer_map_rules"])
        )
    expected_variant_rules = {
        "parent_semantic_set_required": True,
        "semantic_pass_rerender_forbidden": True,
        "geometry_visibility_crop_camera_must_match_parent": True,
        "parent_scene_state_sha256_required": True,
    }
    if policy["rgb_variant_rules"] != expected_variant_rules:
        raise RenderPassContractError(
            "pass_policy_variant_rules_invalid", str(policy["rgb_variant_rules"])
        )
    expected_freeze_rules = {
        "every_sidecar_repeats_scene_state_sha256": True,
        "before_and_after_pass_hash_required": True,
        "annotation_override_restore_hash_required": True,
        "any_mutation_invalidates_entire_set": True,
        "exact_resolution_and_crop_required": True,
    }
    if policy["freeze_rules"] != expected_freeze_rules:
        raise RenderPassContractError(
            "pass_policy_freeze_rules_invalid", str(policy["freeze_rules"])
        )


def build_render_pass_plan(
    resolved_state: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    profile: str,
    parent_semantic_set: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one closed pass plan bound to an immutable resolved scene state."""

    validate_render_pass_policy(policy)
    require_valid_document(resolved_state, "daz_resolved_scene_state")
    _verify_resolved_state_hash(resolved_state)
    if profile not in policy["profiles"]:
        raise RenderPassContractError("pass_profile_unknown", profile)
    is_variant = profile == "rgb_variant"
    parent = None
    if is_variant:
        parent = _validate_parent_semantic_set(parent_semantic_set, resolved_state)
    elif parent_semantic_set is not None:
        raise RenderPassContractError("pass_parent_semantic_set_unexpected", profile)
    outputs = []
    for index, role in enumerate(policy["profiles"][profile]):
        contract = policy["role_catalog"][role]
        outputs.append(
            {
                "sequence": index,
                "role": role,
                "encoding": contract["encoding"],
                "semantic": contract["semantic"],
                "train_eligible": contract["train_eligible"],
                "scene_state_sha256": resolved_state["scene_state_sha256"],
                "resolution": resolved_state["state"]["camera"]["resolution"],
                "crop": resolved_state["state"]["camera"]["crop"],
                "integer_map_rules_required": _is_integer_role(role, contract["encoding"]),
            }
        )
    content = {
        "scene_id": resolved_state["scene_id"],
        "resolved_state_id": resolved_state["resolved_state_id"],
        "resolved_state_sha256": resolved_state["resolved_state_sha256"],
        "scene_state_sha256": resolved_state["scene_state_sha256"],
        "policy_sha256": _canonical_sha(policy),
        "profile": profile,
        "profile_version": policy["policy_version"],
        "boundary_convention": policy["boundary_convention"],
        "integer_map_rules": policy["integer_map_rules"],
        "parent_semantic_set": parent,
        "semantic_rerender_forbidden": is_variant,
        "outputs": outputs,
    }
    digest = _canonical_sha(content)
    document = {
        "schema_version": "1.0.0",
        "plan_id": f"dcrp_{digest[:24]}",
        "plan_sha256": digest,
        **content,
    }
    require_valid_document(document, "daz_render_pass_plan")
    return document


def evaluate_render_pass_execution(
    plan: Mapping[str, Any], execution: Mapping[str, Any], policy: Mapping[str, Any]
) -> dict[str, Any]:
    """Reject any output-set mutation, sidecar drift, missing pass, or forbidden ID effect."""

    validate_render_pass_policy(policy)
    require_valid_document(plan, "daz_render_pass_plan")
    _verify_plan_hash(plan)
    _validate_execution(execution)
    if (
        execution["plan_id"] != plan["plan_id"]
        or execution["plan_sha256"] != plan["plan_sha256"]
        or execution["scene_id"] != plan["scene_id"]
    ):
        raise RenderPassContractError("pass_execution_lineage_mismatch", execution["scene_id"])
    expected_roles = [output["role"] for output in plan["outputs"]]
    actual_roles = [record["role"] for record in execution["passes"]]
    if actual_roles != expected_roles:
        raise RenderPassContractError(
            "pass_execution_role_set_mismatch",
            json.dumps({"expected": expected_roles, "actual": actual_roles}),
        )
    findings = []
    expected_state = plan["scene_state_sha256"]
    for index, (planned, actual) in enumerate(
        zip(plan["outputs"], execution["passes"], strict=True)
    ):
        path = f"/passes/{index}"
        if actual["sequence"] != planned["sequence"]:
            _finding(findings, "PASS_SEQUENCE_MISMATCH", path, str(actual["sequence"]))
        for field in ("encoding", "resolution", "crop"):
            if actual[field] != planned[field]:
                _finding(
                    findings, "PASS_OUTPUT_CONTRACT_MISMATCH", f"{path}/{field}", str(actual[field])
                )
        hashes = {
            "before": actual["scene_state_before_sha256"],
            "sidecar": actual["sidecar_scene_state_sha256"],
            "after": actual["scene_state_after_sha256"],
            "restore": actual["annotation_restore_scene_state_sha256"],
        }
        for name, value in hashes.items():
            if value != expected_state:
                _finding(findings, "PASS_SCENE_STATE_MUTATION", f"{path}/{name}", value)
        if actual["sidecar_plan_sha256"] != plan["plan_sha256"]:
            _finding(findings, "PASS_SIDECAR_LINEAGE_MISMATCH", path, actual["sidecar_plan_sha256"])
        if planned["integer_map_rules_required"]:
            effects = set(actual["effects"])
            forbidden = effects & set(policy["integer_map_rules"]["forbidden"])
            if forbidden:
                _finding(
                    findings,
                    "PASS_INTEGER_EFFECT_FORBIDDEN",
                    f"{path}/effects",
                    ",".join(sorted(forbidden)),
                )
            if actual["decode_filter"] != "nearest_neighbor_exact":
                _finding(
                    findings,
                    "PASS_INTEGER_DECODE_INVALID",
                    f"{path}/decode_filter",
                    actual["decode_filter"],
                )
        if not actual["file_sha256"] or actual["bytes"] <= 0:
            _finding(findings, "PASS_OUTPUT_EMPTY", path, actual["role"])
    if plan["semantic_rerender_forbidden"]:
        if execution["semantic_passes_rendered"] != 0:
            _finding(
                findings,
                "PASS_VARIANT_SEMANTIC_RERENDER",
                "/semantic_passes_rendered",
                str(execution["semantic_passes_rendered"]),
            )
        parent = plan["parent_semantic_set"]
        if execution["parent_semantic_set_sha256"] != parent["semantic_set_sha256"]:
            _finding(
                findings,
                "PASS_VARIANT_PARENT_MISMATCH",
                "/parent_semantic_set_sha256",
                str(execution["parent_semantic_set_sha256"]),
            )
    else:
        expected_semantic_count = sum(output["semantic"] for output in plan["outputs"])
        if execution["semantic_passes_rendered"] != expected_semantic_count:
            _finding(
                findings,
                "PASS_SEMANTIC_PASS_COUNT_MISMATCH",
                "/semantic_passes_rendered",
                str(execution["semantic_passes_rendered"]),
            )
        if execution["parent_semantic_set_sha256"] is not None:
            _finding(
                findings,
                "PASS_PARENT_SEMANTIC_SET_UNEXPECTED",
                "/parent_semantic_set_sha256",
                str(execution["parent_semantic_set_sha256"]),
            )
    if execution["terminal_scene_state_sha256"] != expected_state:
        _finding(
            findings,
            "PASS_TERMINAL_STATE_MUTATION",
            "/terminal_scene_state_sha256",
            execution["terminal_scene_state_sha256"],
        )
    findings.sort(key=lambda row: (row["code"], row["path"], row["detail"]))
    content = {
        "scene_id": plan["scene_id"],
        "plan_id": plan["plan_id"],
        "plan_sha256": plan["plan_sha256"],
        "scene_state_sha256": expected_state,
        "execution_sha256": _canonical_sha(execution),
        "pass_file_map_sha256": _canonical_sha(
            [
                {"role": row["role"], "sha256": row["file_sha256"], "bytes": row["bytes"]}
                for row in execution["passes"]
            ]
        ),
        "findings": findings,
        "summary": {
            "passed": not findings,
            "finding_count": len(findings),
            "failure_codes": sorted({row["code"] for row in findings}),
            "pass_count": len(execution["passes"]),
            "scene_state_unchanged": not any("MUTATION" in row["code"] for row in findings),
        },
    }
    digest = _canonical_sha(content)
    report = {
        "schema_version": "1.0.0",
        "report_id": f"dcrx_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    require_valid_document(report, "daz_render_pass_execution_report")
    return report


def validate_render_pass_execution_report(
    report: Mapping[str, Any],
    plan: Mapping[str, Any],
    execution: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    require_valid_document(report, "daz_render_pass_execution_report")
    if report != evaluate_render_pass_execution(plan, execution, policy):
        raise RenderPassContractError("pass_execution_report_replay_mismatch", report["report_id"])


def publish_render_pass_document(
    document: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    if "report_id" in document:
        require_valid_document(document, "daz_render_pass_execution_report")
        name = document["report_id"]
    elif "plan_id" in document:
        require_valid_document(document, "daz_render_pass_plan")
        name = document["plan_id"]
    else:
        raise RenderPassContractError("pass_publication_document_unknown", str(document))
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{name}.json"
    payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise RenderPassContractError("pass_publication_conflict", str(target))
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


def _validate_parent_semantic_set(parent: Any, resolved_state: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "semantic_set_id",
        "semantic_set_sha256",
        "scene_state_sha256",
        "resolution",
        "crop",
    }
    if not isinstance(parent, Mapping) or set(parent) != expected:
        raise RenderPassContractError("pass_variant_parent_invalid", str(parent))
    if (
        not parent["semantic_set_id"].startswith("semantic_")
        or not _sha256(parent["semantic_set_sha256"])
        or parent["scene_state_sha256"] != resolved_state["scene_state_sha256"]
        or parent["resolution"] != resolved_state["state"]["camera"]["resolution"]
        or parent["crop"] != resolved_state["state"]["camera"]["crop"]
    ):
        raise RenderPassContractError(
            "pass_variant_parent_mismatch", str(parent.get("semantic_set_id"))
        )
    return dict(parent)


def _validate_execution(execution: Any) -> None:
    expected = {
        "schema_version",
        "scene_id",
        "plan_id",
        "plan_sha256",
        "passes",
        "semantic_passes_rendered",
        "parent_semantic_set_sha256",
        "terminal_scene_state_sha256",
    }
    if not isinstance(execution, Mapping) or set(execution) != expected:
        raise RenderPassContractError("pass_execution_fields_invalid", str(execution))
    if (
        execution["schema_version"] != "1.0.0"
        or not isinstance(execution["scene_id"], str)
        or not isinstance(execution["plan_id"], str)
        or not _sha256(execution["plan_sha256"])
        or not isinstance(execution["passes"], list)
        or not _sha256(execution["terminal_scene_state_sha256"])
        or (
            execution["parent_semantic_set_sha256"] is not None
            and not _sha256(execution["parent_semantic_set_sha256"])
        )
    ):
        raise RenderPassContractError("pass_execution_invalid", "version/passes")
    if (
        not isinstance(execution["semantic_passes_rendered"], int)
        or execution["semantic_passes_rendered"] < 0
    ):
        raise RenderPassContractError("pass_execution_semantic_count_invalid", "count")
    for record in execution["passes"]:
        fields = {
            "sequence",
            "role",
            "encoding",
            "resolution",
            "crop",
            "file_sha256",
            "bytes",
            "scene_state_before_sha256",
            "sidecar_scene_state_sha256",
            "scene_state_after_sha256",
            "annotation_restore_scene_state_sha256",
            "sidecar_plan_sha256",
            "effects",
            "decode_filter",
        }
        if (
            not isinstance(record, Mapping)
            or set(record) != fields
            or not isinstance(record["sequence"], int)
            or record["sequence"] < 0
            or not isinstance(record["role"], str)
            or not isinstance(record["encoding"], str)
            or not isinstance(record["bytes"], int)
            or record["bytes"] < 0
            or not isinstance(record["effects"], list)
            or any(not isinstance(effect, str) for effect in record["effects"])
            or len(record["effects"]) != len(set(record["effects"]))
            or not isinstance(record["decode_filter"], str)
        ):
            raise RenderPassContractError("pass_execution_record_invalid", str(record))
        for key in (
            "file_sha256",
            "scene_state_before_sha256",
            "sidecar_scene_state_sha256",
            "scene_state_after_sha256",
            "annotation_restore_scene_state_sha256",
            "sidecar_plan_sha256",
        ):
            if not _sha256(record[key]):
                raise RenderPassContractError(
                    "pass_execution_hash_invalid", f"{record['role']}:{key}"
                )


def _verify_resolved_state_hash(document: Mapping[str, Any]) -> None:
    content = {
        key: value
        for key, value in document.items()
        if key not in {"schema_version", "resolved_state_id", "resolved_state_sha256"}
    }
    digest = _canonical_sha(content)
    if (
        document["resolved_state_sha256"] != digest
        or document["resolved_state_id"] != f"dcrs_{digest[:24]}"
    ):
        raise RenderPassContractError(
            "pass_resolved_state_hash_invalid", document["resolved_state_id"]
        )


def _verify_plan_hash(plan: Mapping[str, Any]) -> None:
    content = {
        key: value
        for key, value in plan.items()
        if key not in {"schema_version", "plan_id", "plan_sha256"}
    }
    digest = _canonical_sha(content)
    if plan["plan_sha256"] != digest or plan["plan_id"] != f"dcrp_{digest[:24]}":
        raise RenderPassContractError("pass_plan_hash_invalid", plan["plan_id"])


def _is_integer_role(role: str, encoding: str) -> bool:
    return role in {
        "instance",
        "part",
        "material",
        "protected",
        "contact_pairs",
        "front_owner",
        "boundary_pairs",
        "surface",
        "facet",
        "node",
    } or encoding.startswith("uint")


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
        raise RenderPassContractError("pass_noncanonical_value", str(exc)) from exc
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "RenderPassContractError",
    "build_render_pass_plan",
    "evaluate_render_pass_execution",
    "load_render_pass_policy",
    "publish_render_pass_document",
    "validate_render_pass_execution_report",
    "validate_render_pass_policy",
]
