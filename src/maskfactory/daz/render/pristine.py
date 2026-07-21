"""Pristine photographic RGB render request and fixture validation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import yaml
from PIL import Image, UnidentifiedImageError

from ...validation import require_valid_document


class PristineRgbContractError(ValueError):
    """A pristine RGB policy, request, or fixture violates its closed contract."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_pristine_rgb_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_pristine_rgb_policy(document)
    return document


def validate_pristine_rgb_policy(policy: Mapping[str, Any]) -> None:
    expected_fields = {
        "schema_version",
        "policy_version",
        "eligible_pass_profiles",
        "output_contract",
        "renderer_contract",
        "fixture_acceptance",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected_fields:
        raise PristineRgbContractError("pristine_policy_fields_invalid", str(policy))
    if policy["schema_version"] != "1.0.0" or policy["policy_version"] != "1.0.0":
        raise PristineRgbContractError("pristine_policy_version_invalid", "version")
    if policy["eligible_pass_profiles"] != [
        "training_standard",
        "training_relationship",
        "diagnostic_full",
    ]:
        raise PristineRgbContractError(
            "pristine_policy_profiles_invalid", str(policy["eligible_pass_profiles"])
        )
    expected_output = {
        "role": "rgb_pristine",
        "encoding": "lossless_rgb_png",
        "container_format": "PNG",
        "pixel_mode": "RGB",
        "output_color_space": "srgb",
        "output_bit_depth": 8,
        "transparent_background": False,
        "source_kind": "direct_renderer_pristine",
        "derived_effects_allowed": [],
    }
    if policy["output_contract"] != expected_output:
        raise PristineRgbContractError(
            "pristine_policy_output_invalid", str(policy["output_contract"])
        )
    expected_settings = [
        "engine_id",
        "engine_version",
        "render_mode",
        "render_seed",
        "max_samples",
        "convergence_ratio",
        "stop_condition",
        "pixel_filter",
        "pixel_filter_radius",
        "tone_mapping_enabled",
        "denoiser_enabled",
        "depth_of_field",
        "motion_blur",
        "transparent_background",
        "output_color_space",
        "output_bit_depth",
        "output_encoding",
        "resolution",
        "crop",
        "camera_sha256",
        "lighting_environment_sha256",
    ]
    expected_renderer = {
        "engine_ids": ["iray"],
        "render_modes": ["photoreal"],
        "stop_condition": "samples_or_convergence",
        "wall_clock_limit_allowed": False,
        "required_settings": expected_settings,
    }
    if policy["renderer_contract"] != expected_renderer:
        raise PristineRgbContractError(
            "pristine_policy_renderer_invalid", str(policy["renderer_contract"])
        )
    expected_acceptance = {
        "exact_file_hash_required": True,
        "exact_byte_count_required": True,
        "exact_format_mode_resolution_required": True,
        "exact_renderer_readback_required": True,
        "exact_scene_state_before_after_terminal_required": True,
        "sidecar_plan_and_request_hashes_required": True,
        "minimum_unique_colors": 2,
        "all_black_or_all_white_forbidden": True,
        "interrupted_or_partial_output_forbidden": True,
    }
    if policy["fixture_acceptance"] != expected_acceptance:
        raise PristineRgbContractError(
            "pristine_policy_acceptance_invalid", str(policy["fixture_acceptance"])
        )


def build_pristine_rgb_request(
    resolved_state: Mapping[str, Any],
    pass_plan: Mapping[str, Any],
    renderer_settings: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Seal one direct-render pristine RGB request against frozen scene authority."""

    validate_pristine_rgb_policy(policy)
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
        raise PristineRgbContractError("pristine_pass_profile_ineligible", pass_plan["profile"])
    outputs = [output for output in pass_plan["outputs"] if output["role"] == "rgb_pristine"]
    if len(outputs) != 1:
        raise PristineRgbContractError("pristine_output_role_invalid", str(len(outputs)))
    output = outputs[0]
    if output["encoding"] != policy["output_contract"]["encoding"]:
        raise PristineRgbContractError("pristine_output_encoding_invalid", output["encoding"])
    if (
        pass_plan["scene_id"] != resolved_state["scene_id"]
        or pass_plan["resolved_state_id"] != resolved_state["resolved_state_id"]
        or pass_plan["resolved_state_sha256"] != resolved_state["resolved_state_sha256"]
        or pass_plan["scene_state_sha256"] != resolved_state["scene_state_sha256"]
    ):
        raise PristineRgbContractError("pristine_state_plan_lineage_mismatch", pass_plan["plan_id"])
    settings = _validate_renderer_settings(renderer_settings, resolved_state, output, policy)
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
            "container_format": policy["output_contract"]["container_format"],
            "pixel_mode": policy["output_contract"]["pixel_mode"],
            "source_kind": policy["output_contract"]["source_kind"],
            "derived_effects": [],
        },
        "renderer_settings": settings,
    }
    digest = _canonical_sha(content)
    document = {
        "schema_version": "1.0.0",
        "request_id": f"dprr_{digest[:24]}",
        "request_sha256": digest,
        **content,
    }
    require_valid_document(document, "daz_pristine_rgb_request")
    return document


def validate_pristine_rgb_request(
    request: Mapping[str, Any],
    resolved_state: Mapping[str, Any],
    pass_plan: Mapping[str, Any],
    renderer_settings: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    require_valid_document(request, "daz_pristine_rgb_request")
    expected = build_pristine_rgb_request(resolved_state, pass_plan, renderer_settings, policy)
    if request != expected:
        raise PristineRgbContractError("pristine_request_replay_mismatch", request["request_id"])


def evaluate_pristine_rgb_fixture(
    request: Mapping[str, Any],
    execution: Mapping[str, Any],
    image_path: Path,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Inspect one renderer-produced RGB fixture and emit deterministic findings."""

    validate_pristine_rgb_policy(policy)
    require_valid_document(request, "daz_pristine_rgb_request")
    _verify_hashed_document(
        request, id_field="request_id", hash_field="request_sha256", prefix="dprr"
    )
    _validate_execution(execution)
    path = Path(image_path)
    if not path.is_file():
        raise PristineRgbContractError("pristine_fixture_missing", str(path))
    payload = path.read_bytes()
    actual_file_sha256 = hashlib.sha256(payload).hexdigest()
    actual_bytes = len(payload)
    findings: list[dict[str, str]] = []
    if (
        execution["request_id"] != request["request_id"]
        or execution["request_sha256"] != request["request_sha256"]
        or execution["plan_id"] != request["plan_id"]
        or execution["plan_sha256"] != request["plan_sha256"]
        or execution["scene_id"] != request["scene_id"]
    ):
        raise PristineRgbContractError(
            "pristine_execution_lineage_mismatch", execution["request_id"]
        )
    expected_state = request["scene_state_sha256"]
    for field in (
        "scene_state_before_sha256",
        "sidecar_scene_state_sha256",
        "scene_state_after_sha256",
        "terminal_scene_state_sha256",
    ):
        if execution[field] != expected_state:
            _finding(findings, "PRISTINE_SCENE_STATE_MUTATION", f"/{field}", execution[field])
    if execution["sidecar_plan_sha256"] != request["plan_sha256"]:
        _finding(
            findings,
            "PRISTINE_SIDECAR_PLAN_MISMATCH",
            "/sidecar_plan_sha256",
            execution["sidecar_plan_sha256"],
        )
    if execution["sidecar_request_sha256"] != request["request_sha256"]:
        _finding(
            findings,
            "PRISTINE_SIDECAR_REQUEST_MISMATCH",
            "/sidecar_request_sha256",
            execution["sidecar_request_sha256"],
        )
    if execution["renderer_settings_readback"] != request["renderer_settings"]:
        _finding(
            findings,
            "PRISTINE_RENDERER_READBACK_MISMATCH",
            "/renderer_settings_readback",
            _canonical_sha(execution["renderer_settings_readback"]),
        )
    output = execution["output"]
    for field in ("role", "encoding", "resolution", "crop", "source_kind", "derived_effects"):
        if output[field] != request["output"][field]:
            _finding(
                findings,
                "PRISTINE_OUTPUT_CONTRACT_MISMATCH",
                f"/output/{field}",
                str(output[field]),
            )
    if output["file_sha256"] != actual_file_sha256:
        _finding(
            findings,
            "PRISTINE_FILE_HASH_MISMATCH",
            "/output/file_sha256",
            output["file_sha256"],
        )
    if output["bytes"] != actual_bytes or actual_bytes == 0:
        _finding(findings, "PRISTINE_BYTE_COUNT_MISMATCH", "/output/bytes", str(output["bytes"]))
    if output["completed"] is not True or output["interrupted"] is not False:
        _finding(
            findings,
            "PRISTINE_OUTPUT_INCOMPLETE",
            "/output/completed",
            f"completed={output['completed']},interrupted={output['interrupted']}",
        )
    measurements = _inspect_rgb_image(path, policy, findings)
    for field, expected in (
        ("format", request["output"]["container_format"]),
        ("mode", request["output"]["pixel_mode"]),
        ("resolution", request["output"]["resolution"]),
    ):
        if measurements[field] != expected:
            _finding(
                findings,
                "PRISTINE_IMAGE_FORMAT_MISMATCH",
                f"/measurements/{field}",
                str(measurements[field]),
            )
    findings.sort(key=lambda row: (row["code"], row["path"], row["detail"]))
    content = {
        "scene_id": request["scene_id"],
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "plan_id": request["plan_id"],
        "plan_sha256": request["plan_sha256"],
        "scene_state_sha256": expected_state,
        "execution_sha256": _canonical_sha(execution),
        "file_sha256": actual_file_sha256,
        "bytes": actual_bytes,
        "measurements": measurements,
        "findings": findings,
        "summary": {
            "passed": not findings,
            "finding_count": len(findings),
            "failure_codes": sorted({row["code"] for row in findings}),
            "scene_state_unchanged": not any("MUTATION" in row["code"] for row in findings),
            "direct_pristine_rgb_verified": not findings,
        },
    }
    digest = _canonical_sha(content)
    report = {
        "schema_version": "1.0.0",
        "report_id": f"dprf_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    require_valid_document(report, "daz_pristine_rgb_fixture_report")
    return report


def validate_pristine_rgb_fixture_report(
    report: Mapping[str, Any],
    request: Mapping[str, Any],
    execution: Mapping[str, Any],
    image_path: Path,
    policy: Mapping[str, Any],
) -> None:
    require_valid_document(report, "daz_pristine_rgb_fixture_report")
    expected = evaluate_pristine_rgb_fixture(request, execution, image_path, policy)
    if report != expected:
        raise PristineRgbContractError("pristine_report_replay_mismatch", report["report_id"])


def publish_pristine_rgb_document(
    document: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    if "report_id" in document:
        require_valid_document(document, "daz_pristine_rgb_fixture_report")
        name = document["report_id"]
    elif "request_id" in document:
        require_valid_document(document, "daz_pristine_rgb_request")
        name = document["request_id"]
    else:
        raise PristineRgbContractError("pristine_publication_document_unknown", str(document))
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{name}.json"
    payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise PristineRgbContractError("pristine_publication_conflict", str(target))
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


def _validate_renderer_settings(
    settings: Any,
    resolved_state: Mapping[str, Any],
    output: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    required = policy["renderer_contract"]["required_settings"]
    if not isinstance(settings, Mapping) or set(settings) != set(required):
        raise PristineRgbContractError("pristine_renderer_settings_fields_invalid", str(settings))
    renderer = resolved_state["state"]["renderer"]
    camera = resolved_state["state"]["camera"]
    if (
        settings["engine_id"] not in policy["renderer_contract"]["engine_ids"]
        or settings["engine_id"] != renderer["id"]
        or settings["engine_version"] != renderer["version"]
        or settings["render_mode"] not in policy["renderer_contract"]["render_modes"]
        or settings["stop_condition"] != policy["renderer_contract"]["stop_condition"]
    ):
        raise PristineRgbContractError("pristine_renderer_identity_invalid", str(renderer))
    if (
        not isinstance(settings["render_seed"], int)
        or isinstance(settings["render_seed"], bool)
        or not 0 <= settings["render_seed"] < 2**64
        or not isinstance(settings["max_samples"], int)
        or isinstance(settings["max_samples"], bool)
        or settings["max_samples"] < 1
        or not _finite_number(settings["convergence_ratio"])
        or not 0 < settings["convergence_ratio"] <= 1
        or not isinstance(settings["pixel_filter"], str)
        or not settings["pixel_filter"]
        or not _finite_number(settings["pixel_filter_radius"])
        or settings["pixel_filter_radius"] <= 0
    ):
        raise PristineRgbContractError("pristine_renderer_numeric_invalid", str(settings))
    for field in ("tone_mapping_enabled", "denoiser_enabled"):
        if not isinstance(settings[field], bool):
            raise PristineRgbContractError("pristine_renderer_boolean_invalid", field)
    contract = policy["output_contract"]
    if (
        settings["depth_of_field"] != camera["depth_of_field"]
        or settings["motion_blur"] != camera["motion_blur"]
        or settings["transparent_background"] != contract["transparent_background"]
        or settings["output_color_space"] != contract["output_color_space"]
        or settings["output_bit_depth"] != contract["output_bit_depth"]
        or settings["output_encoding"] != contract["encoding"]
        or settings["resolution"] != output["resolution"]
        or settings["crop"] != output["crop"]
        or settings["camera_sha256"] != _canonical_sha(camera)
        or settings["lighting_environment_sha256"]
        != _canonical_sha(resolved_state["state"]["lighting_environment"])
    ):
        raise PristineRgbContractError("pristine_renderer_scene_binding_invalid", str(settings))
    return dict(settings)


def _validate_execution(execution: Any) -> None:
    expected = {
        "schema_version",
        "scene_id",
        "request_id",
        "request_sha256",
        "plan_id",
        "plan_sha256",
        "scene_state_before_sha256",
        "sidecar_scene_state_sha256",
        "scene_state_after_sha256",
        "terminal_scene_state_sha256",
        "sidecar_plan_sha256",
        "sidecar_request_sha256",
        "renderer_settings_readback",
        "output",
    }
    if not isinstance(execution, Mapping) or set(execution) != expected:
        raise PristineRgbContractError("pristine_execution_fields_invalid", str(execution))
    hash_fields = (
        "request_sha256",
        "plan_sha256",
        "scene_state_before_sha256",
        "sidecar_scene_state_sha256",
        "scene_state_after_sha256",
        "terminal_scene_state_sha256",
        "sidecar_plan_sha256",
        "sidecar_request_sha256",
    )
    if (
        execution["schema_version"] != "1.0.0"
        or any(
            not isinstance(execution[field], str) for field in ("scene_id", "request_id", "plan_id")
        )
        or any(not _sha256(execution[field]) for field in hash_fields)
        or not isinstance(execution["renderer_settings_readback"], Mapping)
    ):
        raise PristineRgbContractError("pristine_execution_invalid", "lineage/hash/readback")
    output = execution["output"]
    output_fields = {
        "role",
        "encoding",
        "resolution",
        "crop",
        "source_kind",
        "derived_effects",
        "file_sha256",
        "bytes",
        "completed",
        "interrupted",
    }
    if (
        not isinstance(output, Mapping)
        or set(output) != output_fields
        or not isinstance(output["role"], str)
        or not isinstance(output["encoding"], str)
        or not isinstance(output["source_kind"], str)
        or not isinstance(output["derived_effects"], list)
        or any(not isinstance(effect, str) for effect in output["derived_effects"])
        or len(output["derived_effects"]) != len(set(output["derived_effects"]))
        or not _sha256(output["file_sha256"])
        or not isinstance(output["bytes"], int)
        or isinstance(output["bytes"], bool)
        or output["bytes"] < 0
        or not isinstance(output["completed"], bool)
        or not isinstance(output["interrupted"], bool)
    ):
        raise PristineRgbContractError("pristine_execution_output_invalid", str(output))


def _inspect_rgb_image(
    path: Path, policy: Mapping[str, Any], findings: list[dict[str, str]]
) -> dict[str, Any]:
    try:
        with Image.open(path) as image:
            image.load()
            image_format = image.format
            mode = image.mode
            resolution = [image.width, image.height]
            if mode == "RGB":
                extrema = [list(channel) for channel in image.getextrema()]
                minimum = policy["fixture_acceptance"]["minimum_unique_colors"]
                colors = image.getcolors(maxcolors=minimum)
                unique_color_count_lower_bound = minimum + 1 if colors is None else len(colors)
                all_black = all(channel == [0, 0] for channel in extrema)
                all_white = all(channel == [255, 255] for channel in extrema)
            else:
                extrema = []
                unique_color_count_lower_bound = 0
                all_black = False
                all_white = False
    except (OSError, UnidentifiedImageError) as exc:
        raise PristineRgbContractError("pristine_fixture_unreadable", str(exc)) from exc
    minimum = policy["fixture_acceptance"]["minimum_unique_colors"]
    if unique_color_count_lower_bound < minimum:
        _finding(
            findings,
            "PRISTINE_IMAGE_UNIFORM",
            "/measurements/unique_color_count_lower_bound",
            str(unique_color_count_lower_bound),
        )
    if all_black or all_white:
        _finding(
            findings,
            "PRISTINE_IMAGE_EMPTY_EXTREME",
            "/measurements/channel_extrema",
            "all_black" if all_black else "all_white",
        )
    return {
        "format": image_format,
        "mode": mode,
        "resolution": resolution,
        "channel_extrema": extrema,
        "unique_color_count_lower_bound": unique_color_count_lower_bound,
        "all_black": all_black,
        "all_white": all_white,
    }


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
        raise PristineRgbContractError("pristine_document_hash_invalid", str(document[id_field]))


def _finding(findings: list[dict[str, str]], code: str, path: str, detail: str) -> None:
    findings.append({"code": code, "path": path, "detail": detail})


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


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
        raise PristineRgbContractError("pristine_noncanonical_value", str(exc)) from exc
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "PristineRgbContractError",
    "build_pristine_rgb_request",
    "evaluate_pristine_rgb_fixture",
    "load_pristine_rgb_policy",
    "publish_pristine_rgb_document",
    "validate_pristine_rgb_fixture_report",
    "validate_pristine_rgb_policy",
    "validate_pristine_rgb_request",
]
