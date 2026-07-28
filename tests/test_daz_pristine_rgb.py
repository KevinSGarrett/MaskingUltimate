from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from maskfactory.cli import main  # noqa: E402
from maskfactory.daz.render import (  # noqa: E402
    PristineRgbContractError,
    build_pristine_rgb_request,
    evaluate_pristine_rgb_fixture,
    load_pristine_rgb_policy,
    publish_pristine_rgb_document,
    validate_pristine_rgb_fixture_report,
    validate_pristine_rgb_policy,
    validate_pristine_rgb_request,
)
from test_daz_render_pass_profiles import _plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "daz" / "pristine_rgb.yaml"


def _sha(document) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _settings(state: dict, plan: dict) -> dict:
    output = next(output for output in plan["outputs"] if output["role"] == "rgb_pristine")
    return {
        "engine_id": state["state"]["renderer"]["id"],
        "engine_version": state["state"]["renderer"]["version"],
        "render_mode": "photoreal",
        "render_seed": 761239,
        "max_samples": 256,
        "convergence_ratio": 0.95,
        "stop_condition": "samples_or_convergence",
        "pixel_filter": "mitchell",
        "pixel_filter_radius": 1.5,
        "tone_mapping_enabled": True,
        "denoiser_enabled": True,
        "depth_of_field": deepcopy(state["state"]["camera"]["depth_of_field"]),
        "motion_blur": deepcopy(state["state"]["camera"]["motion_blur"]),
        "transparent_background": False,
        "output_color_space": "srgb",
        "output_bit_depth": 8,
        "output_encoding": "lossless_rgb_png",
        "resolution": deepcopy(output["resolution"]),
        "crop": deepcopy(output["crop"]),
        "camera_sha256": _sha(state["state"]["camera"]),
        "lighting_environment_sha256": _sha(state["state"]["lighting_environment"]),
    }


def _request(profile: str = "training_standard") -> tuple[dict, dict, dict, dict]:
    state, _pass_policy, plan = _plan(profile)
    settings = _settings(state, plan)
    policy = load_pristine_rgb_policy(POLICY_PATH)
    request = build_pristine_rgb_request(state, plan, settings, policy)
    return state, plan, settings, request


def _write_image(
    path: Path,
    resolution: list[int],
    *,
    mode: str = "RGB",
    image_format: str = "PNG",
    uniform: int | None = None,
) -> None:
    width, height = resolution
    if mode == "RGB":
        color = (uniform, uniform, uniform) if uniform is not None else (20, 40, 80)
    else:
        color = uniform if uniform is not None else 20
    image = Image.new(mode, (width, height), color)
    if uniform is None:
        draw = ImageDraw.Draw(image)
        fill = (180, 120, 60) if mode == "RGB" else 180
        draw.rectangle((width // 4, height // 4, width - 1, height - 1), fill=fill)
    image.save(path, format=image_format)


def _execution(request: dict, image_path: Path) -> dict:
    payload = image_path.read_bytes()
    return {
        "schema_version": "1.0.0",
        "scene_id": request["scene_id"],
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "plan_id": request["plan_id"],
        "plan_sha256": request["plan_sha256"],
        "scene_state_before_sha256": request["scene_state_sha256"],
        "sidecar_scene_state_sha256": request["scene_state_sha256"],
        "scene_state_after_sha256": request["scene_state_sha256"],
        "terminal_scene_state_sha256": request["scene_state_sha256"],
        "sidecar_plan_sha256": request["plan_sha256"],
        "sidecar_request_sha256": request["request_sha256"],
        "renderer_settings_readback": deepcopy(request["renderer_settings"]),
        "output": {
            "role": request["output"]["role"],
            "encoding": request["output"]["encoding"],
            "resolution": deepcopy(request["output"]["resolution"]),
            "crop": deepcopy(request["output"]["crop"]),
            "source_kind": request["output"]["source_kind"],
            "derived_effects": [],
            "file_sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "completed": True,
            "interrupted": False,
        },
    }


def _codes(report: dict) -> set[str]:
    return set(report["summary"]["failure_codes"])


def test_policy_is_closed_direct_lossless_rgb() -> None:
    policy = load_pristine_rgb_policy(POLICY_PATH)
    validate_pristine_rgb_policy(policy)
    assert policy["output_contract"] == {
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
    assert policy["renderer_contract"]["wall_clock_limit_allowed"] is False


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda p: p["eligible_pass_profiles"].append("engineering_minimal"), "profiles"),
        (lambda p: p["output_contract"].__setitem__("encoding", "jpeg"), "output"),
        (lambda p: p["renderer_contract"]["engine_ids"].append("filament"), "renderer"),
        (lambda p: p["renderer_contract"]["required_settings"].pop(), "renderer"),
        (lambda p: p["fixture_acceptance"].__setitem__("minimum_unique_colors", 1), "acceptance"),
    ],
)
def test_policy_drift_fails_closed(mutation, reason: str) -> None:
    policy = load_pristine_rgb_policy(POLICY_PATH)
    mutation(policy)
    with pytest.raises(PristineRgbContractError, match=f"pristine_policy_{reason}_invalid"):
        validate_pristine_rgb_policy(policy)


def test_request_binds_state_plan_camera_lighting_and_renderer() -> None:
    state, plan, settings, request = _request()
    assert request["scene_state_sha256"] == state["scene_state_sha256"]
    assert request["plan_sha256"] == plan["plan_sha256"]
    assert request["output"]["role"] == "rgb_pristine"
    assert request["renderer_settings"] == settings
    validate_pristine_rgb_request(
        request, state, plan, settings, load_pristine_rgb_policy(POLICY_PATH)
    )


@pytest.mark.parametrize("profile", ["engineering_minimal", "rgb_variant"])
def test_nonpristine_pass_profiles_cannot_build_request(profile: str) -> None:
    state, _pass_policy, plan = _plan(profile)
    with pytest.raises(PristineRgbContractError, match="pristine_pass_profile_ineligible"):
        build_pristine_rgb_request(
            state,
            plan,
            {},
            load_pristine_rgb_policy(POLICY_PATH),
        )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda s: s.__setitem__("engine_id", "filament"), "identity"),
        (lambda s: s.__setitem__("engine_version", "wrong"), "identity"),
        (lambda s: s.__setitem__("render_mode", "interactive"), "identity"),
        (lambda s: s.__setitem__("render_seed", -1), "numeric"),
        (lambda s: s.__setitem__("max_samples", 0), "numeric"),
        (lambda s: s.__setitem__("convergence_ratio", 0), "numeric"),
        (lambda s: s.__setitem__("pixel_filter", ""), "numeric"),
        (lambda s: s.__setitem__("pixel_filter_radius", 0), "numeric"),
        (lambda s: s.__setitem__("tone_mapping_enabled", 1), "boolean"),
        (lambda s: s.__setitem__("depth_of_field", {"enabled": True}), "scene_binding"),
        (lambda s: s.__setitem__("motion_blur", {"enabled": True}), "scene_binding"),
        (lambda s: s.__setitem__("transparent_background", True), "scene_binding"),
        (lambda s: s.__setitem__("output_color_space", "display_p3"), "scene_binding"),
        (lambda s: s.__setitem__("output_bit_depth", 16), "scene_binding"),
        (lambda s: s.__setitem__("resolution", [1, 1]), "scene_binding"),
        (lambda s: s.__setitem__("camera_sha256", "0" * 64), "scene_binding"),
        (lambda s: s.__setitem__("lighting_environment_sha256", "0" * 64), "scene_binding"),
    ],
)
def test_renderer_setting_drift_fails_closed(mutation, reason: str) -> None:
    state, _pass_policy, plan = _plan("training_standard")
    settings = _settings(state, plan)
    mutation(settings)
    with pytest.raises(PristineRgbContractError, match=f"pristine_renderer_{reason}_invalid"):
        build_pristine_rgb_request(state, plan, settings, load_pristine_rgb_policy(POLICY_PATH))


def test_valid_renderer_fixture_passes_and_replays(tmp_path: Path) -> None:
    _state_document, _plan_document, _settings_document, request = _request()
    image_path = tmp_path / "pristine.png"
    _write_image(image_path, request["output"]["resolution"])
    execution = _execution(request, image_path)
    policy = load_pristine_rgb_policy(POLICY_PATH)
    report = evaluate_pristine_rgb_fixture(request, execution, image_path, policy)
    assert report["summary"] == {
        "passed": True,
        "finding_count": 0,
        "failure_codes": [],
        "scene_state_unchanged": True,
        "direct_pristine_rgb_verified": True,
    }
    assert report["measurements"]["format"] == "PNG"
    assert report["measurements"]["mode"] == "RGB"
    assert report["measurements"]["unique_color_count_lower_bound"] >= 2
    validate_pristine_rgb_fixture_report(report, request, execution, image_path, policy)


@pytest.mark.parametrize(
    "field",
    [
        "scene_state_before_sha256",
        "sidecar_scene_state_sha256",
        "scene_state_after_sha256",
        "terminal_scene_state_sha256",
    ],
)
def test_any_scene_state_mutation_invalidates_fixture(tmp_path: Path, field: str) -> None:
    _state_document, _plan_document, _settings_document, request = _request()
    image_path = tmp_path / "pristine.png"
    _write_image(image_path, request["output"]["resolution"])
    execution = _execution(request, image_path)
    execution[field] = "0" * 64
    report = evaluate_pristine_rgb_fixture(
        request, execution, image_path, load_pristine_rgb_policy(POLICY_PATH)
    )
    assert "PRISTINE_SCENE_STATE_MUTATION" in _codes(report)
    assert report["summary"]["scene_state_unchanged"] is False


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda e: e.__setitem__("sidecar_plan_sha256", "0" * 64),
            "PRISTINE_SIDECAR_PLAN_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("sidecar_request_sha256", "0" * 64),
            "PRISTINE_SIDECAR_REQUEST_MISMATCH",
        ),
        (
            lambda e: e["renderer_settings_readback"].__setitem__("max_samples", 2),
            "PRISTINE_RENDERER_READBACK_MISMATCH",
        ),
        (
            lambda e: e["output"].__setitem__("role", "rgb_variant"),
            "PRISTINE_OUTPUT_CONTRACT_MISMATCH",
        ),
        (
            lambda e: e["output"].__setitem__("encoding", "jpeg"),
            "PRISTINE_OUTPUT_CONTRACT_MISMATCH",
        ),
        (
            lambda e: e["output"].__setitem__("resolution", [1, 1]),
            "PRISTINE_OUTPUT_CONTRACT_MISMATCH",
        ),
        (
            lambda e: e["output"].__setitem__("crop", [0, 0, 1, 1]),
            "PRISTINE_OUTPUT_CONTRACT_MISMATCH",
        ),
        (
            lambda e: e["output"].__setitem__("source_kind", "derived"),
            "PRISTINE_OUTPUT_CONTRACT_MISMATCH",
        ),
        (
            lambda e: e["output"].__setitem__("derived_effects", ["noise"]),
            "PRISTINE_OUTPUT_CONTRACT_MISMATCH",
        ),
        (lambda e: e["output"].__setitem__("file_sha256", "0" * 64), "PRISTINE_FILE_HASH_MISMATCH"),
        (lambda e: e["output"].__setitem__("bytes", 1), "PRISTINE_BYTE_COUNT_MISMATCH"),
        (lambda e: e["output"].__setitem__("completed", False), "PRISTINE_OUTPUT_INCOMPLETE"),
        (lambda e: e["output"].__setitem__("interrupted", True), "PRISTINE_OUTPUT_INCOMPLETE"),
    ],
)
def test_fixture_metadata_drift_is_reported(tmp_path: Path, mutation, code: str) -> None:
    _state_document, _plan_document, _settings_document, request = _request()
    image_path = tmp_path / "pristine.png"
    _write_image(image_path, request["output"]["resolution"])
    execution = _execution(request, image_path)
    mutation(execution)
    report = evaluate_pristine_rgb_fixture(
        request, execution, image_path, load_pristine_rgb_policy(POLICY_PATH)
    )
    assert code in _codes(report)


@pytest.mark.parametrize(
    ("mode", "image_format", "resolution_delta", "uniform", "expected"),
    [
        ("L", "PNG", 0, None, "PRISTINE_IMAGE_FORMAT_MISMATCH"),
        ("RGB", "JPEG", 0, None, "PRISTINE_IMAGE_FORMAT_MISMATCH"),
        ("RGB", "PNG", -1, None, "PRISTINE_IMAGE_FORMAT_MISMATCH"),
        ("RGB", "PNG", 0, 0, "PRISTINE_IMAGE_EMPTY_EXTREME"),
        ("RGB", "PNG", 0, 255, "PRISTINE_IMAGE_EMPTY_EXTREME"),
        ("RGB", "PNG", 0, 127, "PRISTINE_IMAGE_UNIFORM"),
    ],
)
def test_invalid_image_payload_is_rejected(
    tmp_path: Path,
    mode: str,
    image_format: str,
    resolution_delta: int,
    uniform: int | None,
    expected: str,
) -> None:
    _state_document, _plan_document, _settings_document, request = _request()
    suffix = ".jpg" if image_format == "JPEG" else ".png"
    image_path = tmp_path / f"fixture{suffix}"
    resolution = deepcopy(request["output"]["resolution"])
    resolution[0] += resolution_delta
    _write_image(
        image_path,
        resolution,
        mode=mode,
        image_format=image_format,
        uniform=uniform,
    )
    execution = _execution(request, image_path)
    report = evaluate_pristine_rgb_fixture(
        request, execution, image_path, load_pristine_rgb_policy(POLICY_PATH)
    )
    assert expected in _codes(report)


def test_report_tamper_and_publication_conflict_fail(tmp_path: Path) -> None:
    _state_document, _plan_document, _settings_document, request = _request()
    image_path = tmp_path / "pristine.png"
    _write_image(image_path, request["output"]["resolution"])
    execution = _execution(request, image_path)
    policy = load_pristine_rgb_policy(POLICY_PATH)
    report = evaluate_pristine_rgb_fixture(request, execution, image_path, policy)
    tampered = deepcopy(report)
    tampered["summary"]["passed"] = False
    with pytest.raises(PristineRgbContractError, match="pristine_report_replay_mismatch"):
        validate_pristine_rgb_fixture_report(tampered, request, execution, image_path, policy)
    target, published = publish_pristine_rgb_document(report, tmp_path / "reports")
    assert published is True
    assert publish_pristine_rgb_document(report, tmp_path / "reports") == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(PristineRgbContractError, match="pristine_publication_conflict"):
        publish_pristine_rgb_document(report, tmp_path / "reports")


def test_cli_request_and_fixture_publication_are_idempotent(tmp_path: Path) -> None:
    state, plan, settings, request = _request()
    paths = {}
    for name, document in (("state", state), ("plan", plan), ("settings", settings)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[name] = path
    request_output = tmp_path / "requests"
    request_args = [
        "daz",
        "recipes",
        "plan-pristine-rgb",
        "--resolved-state",
        str(paths["state"]),
        "--pass-plan",
        str(paths["plan"]),
        "--renderer-settings",
        str(paths["settings"]),
        "--policy",
        str(POLICY_PATH),
        "--output",
        str(request_output),
    ]
    runner = CliRunner()
    first = runner.invoke(main, request_args)
    assert first.exit_code == 0, first.output
    first_payload = json.loads(first.output)
    assert first_payload["data"]["publication"]["published"] is True
    replay = runner.invoke(main, request_args)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
    request_path = Path(first_payload["data"]["publication"]["path"])
    published_request = json.loads(request_path.read_text(encoding="utf-8"))
    assert published_request == request
    image_path = tmp_path / "pristine.png"
    _write_image(image_path, request["output"]["resolution"])
    execution_path = tmp_path / "execution.json"
    execution_path.write_text(json.dumps(_execution(request, image_path)), encoding="utf-8")
    report_output = tmp_path / "fixture_reports"
    report_args = [
        "daz",
        "recipes",
        "validate-pristine-rgb-fixture",
        "--request",
        str(request_path),
        "--execution",
        str(execution_path),
        "--image",
        str(image_path),
        "--policy",
        str(POLICY_PATH),
        "--output",
        str(report_output),
    ]
    validated = runner.invoke(main, report_args)
    assert validated.exit_code == 0, validated.output
    assert json.loads(validated.output)["data"]["summary"]["passed"] is True
    validated_replay = runner.invoke(main, report_args)
    assert validated_replay.exit_code == 0, validated_replay.output
    assert json.loads(validated_replay.output)["data"]["publication"]["published"] is False
