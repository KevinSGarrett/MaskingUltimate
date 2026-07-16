from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent))
from maskfactory.cli import main  # noqa: E402
from maskfactory.daz.passes import (  # noqa: E402
    RenderPassContractError,
    build_render_pass_plan,
    evaluate_render_pass_execution,
    load_render_pass_policy,
    publish_render_pass_document,
    validate_render_pass_execution_report,
    validate_render_pass_policy,
)
from maskfactory.daz.scenes import seal_resolved_scene_state  # noqa: E402
from test_daz_resolved_scene_state import _chain  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "daz" / "render_pass_profiles.yaml"


def _state() -> dict:
    return seal_resolved_scene_state(*_chain())


def _parent(state: dict) -> dict:
    return {
        "semantic_set_id": "semantic_fixture_001",
        "semantic_set_sha256": "a" * 64,
        "scene_state_sha256": state["scene_state_sha256"],
        "resolution": deepcopy(state["state"]["camera"]["resolution"]),
        "crop": deepcopy(state["state"]["camera"]["crop"]),
    }


def _plan(profile: str = "training_standard") -> tuple[dict, dict, dict]:
    state = _state()
    policy = load_render_pass_policy(POLICY_PATH)
    plan = build_render_pass_plan(
        state,
        policy,
        profile=profile,
        parent_semantic_set=_parent(state) if profile == "rgb_variant" else None,
    )
    return state, policy, plan


def _execution(plan: dict) -> dict:
    integer_roles = {
        output["role"] for output in plan["outputs"] if output["integer_map_rules_required"]
    }
    return {
        "schema_version": "1.0.0",
        "scene_id": plan["scene_id"],
        "plan_id": plan["plan_id"],
        "plan_sha256": plan["plan_sha256"],
        "passes": [
            {
                "sequence": output["sequence"],
                "role": output["role"],
                "encoding": output["encoding"],
                "resolution": deepcopy(output["resolution"]),
                "crop": deepcopy(output["crop"]),
                "file_sha256": f"{index + 1:064x}",
                "bytes": 1024 + index,
                "scene_state_before_sha256": plan["scene_state_sha256"],
                "sidecar_scene_state_sha256": plan["scene_state_sha256"],
                "scene_state_after_sha256": plan["scene_state_sha256"],
                "annotation_restore_scene_state_sha256": plan["scene_state_sha256"],
                "sidecar_plan_sha256": plan["plan_sha256"],
                "effects": [],
                "decode_filter": (
                    "nearest_neighbor_exact"
                    if output["role"] in integer_roles
                    else "native_lossless"
                ),
            }
            for index, output in enumerate(plan["outputs"])
        ],
        "semantic_passes_rendered": (
            0
            if plan["profile"] == "rgb_variant"
            else sum(output["semantic"] for output in plan["outputs"])
        ),
        "parent_semantic_set_sha256": (
            plan["parent_semantic_set"]["semantic_set_sha256"]
            if plan["parent_semantic_set"] is not None
            else None
        ),
        "terminal_scene_state_sha256": plan["scene_state_sha256"],
    }


def _codes(report: dict) -> set[str]:
    return set(report["summary"]["failure_codes"])


def test_policy_has_exact_closed_profiles_and_boundary_contract() -> None:
    policy = load_render_pass_policy(POLICY_PATH)
    validate_render_pass_policy(policy)
    assert list(policy["profiles"]) == [
        "engineering_minimal",
        "training_standard",
        "training_relationship",
        "diagnostic_full",
        "rgb_variant",
    ]
    assert policy["boundary_convention"] == {
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


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda p: p["role_catalog"]["instance"].__setitem__("encoding", "rgb_png"),
            "pass_policy_catalog_invalid",
        ),
        (
            lambda p: p["profiles"]["diagnostic_full"].append("preview_rgb"),
            "pass_policy_profiles_invalid",
        ),
        (
            lambda p: p["boundary_convention"].__setitem__("sample_grid", "2x2"),
            "pass_policy_boundary_invalid",
        ),
        (
            lambda p: p["integer_map_rules"]["forbidden"].reverse(),
            "pass_policy_integer_rules_invalid",
        ),
        (
            lambda p: p["rgb_variant_rules"].__setitem__("undeclared", True),
            "pass_policy_variant_rules_invalid",
        ),
        (
            lambda p: p["freeze_rules"].__setitem__(
                "annotation_override_restore_hash_required", False
            ),
            "pass_policy_freeze_rules_invalid",
        ),
    ],
)
def test_any_closed_policy_drift_fails(mutation, reason: str) -> None:
    policy = load_render_pass_policy(POLICY_PATH)
    mutation(policy)
    with pytest.raises(RenderPassContractError, match=reason):
        validate_render_pass_policy(policy)


@pytest.mark.parametrize(
    ("profile", "roles"),
    [
        ("engineering_minimal", ["preview_rgb", "instance", "part", "material"]),
        (
            "training_standard",
            [
                "rgb_pristine",
                "instance",
                "part",
                "material",
                "protected",
                "depth",
                "normals",
                "coverage_alpha",
            ],
        ),
        (
            "training_relationship",
            [
                "rgb_pristine",
                "instance",
                "part",
                "material",
                "protected",
                "depth",
                "normals",
                "coverage_alpha",
                "contact_pairs",
                "front_owner",
                "boundary_pairs",
            ],
        ),
        (
            "diagnostic_full",
            [
                "rgb_pristine",
                "instance",
                "part",
                "material",
                "protected",
                "depth",
                "normals",
                "coverage_alpha",
                "contact_pairs",
                "front_owner",
                "boundary_pairs",
                "surface",
                "facet",
                "node",
                "mapping_confidence",
                "amodal_geometry",
            ],
        ),
        ("rgb_variant", ["rgb_variant"]),
    ],
)
def test_each_profile_builds_exact_state_bound_outputs(profile: str, roles: list[str]) -> None:
    state, policy, plan = _plan(profile)
    assert [output["role"] for output in plan["outputs"]] == roles
    assert [output["sequence"] for output in plan["outputs"]] == list(range(len(roles)))
    assert {output["scene_state_sha256"] for output in plan["outputs"]} == {
        state["scene_state_sha256"]
    }
    assert all(
        output["resolution"] == state["state"]["camera"]["resolution"]
        and output["crop"] == state["state"]["camera"]["crop"]
        for output in plan["outputs"]
    )
    assert plan["policy_sha256"]
    assert plan["integer_map_rules"] == policy["integer_map_rules"]


def test_valid_execution_passes_and_replays_exactly() -> None:
    _state_document, policy, plan = _plan("diagnostic_full")
    execution = _execution(plan)
    report = evaluate_render_pass_execution(plan, execution, policy)
    assert report["summary"] == {
        "passed": True,
        "finding_count": 0,
        "failure_codes": [],
        "pass_count": 16,
        "scene_state_unchanged": True,
    }
    validate_render_pass_execution_report(report, plan, execution, policy)


@pytest.mark.parametrize(
    "field",
    [
        "scene_state_before_sha256",
        "sidecar_scene_state_sha256",
        "scene_state_after_sha256",
        "annotation_restore_scene_state_sha256",
    ],
)
def test_any_per_pass_state_mutation_invalidates_entire_set(field: str) -> None:
    _state_document, policy, plan = _plan()
    execution = _execution(plan)
    execution["passes"][0][field] = "0" * 64
    report = evaluate_render_pass_execution(plan, execution, policy)
    assert report["summary"]["passed"] is False
    assert report["summary"]["scene_state_unchanged"] is False
    assert "PASS_SCENE_STATE_MUTATION" in _codes(report)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda e: e["passes"].reverse(), "pass_execution_role_set_mismatch"),
        (lambda e: e["passes"].pop(), "pass_execution_role_set_mismatch"),
        (lambda e: e["passes"][0].__setitem__("sequence", 99), "PASS_SEQUENCE_MISMATCH"),
        (lambda e: e["passes"][0].__setitem__("encoding", "jpeg"), "PASS_OUTPUT_CONTRACT_MISMATCH"),
        (
            lambda e: e["passes"][0].__setitem__("resolution", {"width": 1}),
            "PASS_OUTPUT_CONTRACT_MISMATCH",
        ),
        (lambda e: e["passes"][0].__setitem__("crop", {"x": 1}), "PASS_OUTPUT_CONTRACT_MISMATCH"),
        (
            lambda e: e["passes"][0].__setitem__("sidecar_plan_sha256", "0" * 64),
            "PASS_SIDECAR_LINEAGE_MISMATCH",
        ),
        (lambda e: e["passes"][0].__setitem__("bytes", 0), "PASS_OUTPUT_EMPTY"),
        (
            lambda e: e.__setitem__("terminal_scene_state_sha256", "0" * 64),
            "PASS_TERMINAL_STATE_MUTATION",
        ),
    ],
)
def test_execution_contract_mismatches_fail_closed(mutation, code: str) -> None:
    _state_document, policy, plan = _plan()
    execution = _execution(plan)
    mutation(execution)
    if code == "pass_execution_role_set_mismatch":
        with pytest.raises(RenderPassContractError, match=code):
            evaluate_render_pass_execution(plan, execution, policy)
    else:
        assert code in _codes(evaluate_render_pass_execution(plan, execution, policy))


@pytest.mark.parametrize(
    "effect",
    [
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
)
def test_every_forbidden_integer_effect_is_detected(effect: str) -> None:
    _state_document, policy, plan = _plan("engineering_minimal")
    execution = _execution(plan)
    execution["passes"][1]["effects"] = [effect]
    assert "PASS_INTEGER_EFFECT_FORBIDDEN" in _codes(
        evaluate_render_pass_execution(plan, execution, policy)
    )


def test_integer_decode_must_be_exact_nearest_neighbor() -> None:
    _state_document, policy, plan = _plan("engineering_minimal")
    execution = _execution(plan)
    execution["passes"][1]["decode_filter"] = "bilinear"
    assert "PASS_INTEGER_DECODE_INVALID" in _codes(
        evaluate_render_pass_execution(plan, execution, policy)
    )


def test_standard_execution_reports_exact_semantic_pass_count() -> None:
    _state_document, policy, plan = _plan("training_standard")
    execution = _execution(plan)
    execution["semantic_passes_rendered"] -= 1
    assert "PASS_SEMANTIC_PASS_COUNT_MISMATCH" in _codes(
        evaluate_render_pass_execution(plan, execution, policy)
    )


def test_rgb_variant_requires_exact_parent_and_forbids_semantic_rerender() -> None:
    state = _state()
    policy = load_render_pass_policy(POLICY_PATH)
    with pytest.raises(RenderPassContractError, match="pass_variant_parent_invalid"):
        build_render_pass_plan(state, policy, profile="rgb_variant")
    parent = _parent(state)
    for field, replacement in (
        ("scene_state_sha256", "0" * 64),
        ("resolution", {"width": 1}),
        ("crop", {"x": 1}),
    ):
        mismatch = deepcopy(parent)
        mismatch[field] = replacement
        with pytest.raises(RenderPassContractError, match="pass_variant_parent_mismatch"):
            build_render_pass_plan(
                state, policy, profile="rgb_variant", parent_semantic_set=mismatch
            )
    plan = build_render_pass_plan(state, policy, profile="rgb_variant", parent_semantic_set=parent)
    execution = _execution(plan)
    execution["semantic_passes_rendered"] = 1
    execution["parent_semantic_set_sha256"] = "0" * 64
    assert _codes(evaluate_render_pass_execution(plan, execution, policy)) == {
        "PASS_VARIANT_PARENT_MISMATCH",
        "PASS_VARIANT_SEMANTIC_RERENDER",
    }


def test_plan_and_report_tampering_are_rejected() -> None:
    _state_document, policy, plan = _plan()
    tampered_plan = deepcopy(plan)
    tampered_plan["outputs"][0]["encoding"] = "jpeg"
    with pytest.raises(RenderPassContractError, match="pass_plan_hash_invalid"):
        evaluate_render_pass_execution(tampered_plan, _execution(plan), policy)
    execution = _execution(plan)
    report = evaluate_render_pass_execution(plan, execution, policy)
    tampered_report = deepcopy(report)
    tampered_report["summary"]["passed"] = False
    with pytest.raises(RenderPassContractError, match="pass_execution_report_replay_mismatch"):
        validate_render_pass_execution_report(tampered_report, plan, execution, policy)


def test_publication_is_immutable_and_idempotent(tmp_path: Path) -> None:
    _state_document, _policy, plan = _plan()
    target, published = publish_render_pass_document(plan, tmp_path)
    assert published is True
    assert publish_render_pass_document(plan, tmp_path) == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RenderPassContractError, match="pass_publication_conflict"):
        publish_render_pass_document(plan, tmp_path)


def test_cli_plans_and_validates_idempotently(tmp_path: Path) -> None:
    state = _state()
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    plan_output = tmp_path / "plans"
    runner = CliRunner()
    plan_arguments = [
        "daz",
        "recipes",
        "plan-passes",
        "--resolved-state",
        str(state_path),
        "--profile",
        "training_standard",
        "--policy",
        str(POLICY_PATH),
        "--output",
        str(plan_output),
    ]
    first = runner.invoke(main, plan_arguments)
    assert first.exit_code == 0, first.output
    first_payload = json.loads(first.output)
    assert first_payload["data"]["publication"]["published"] is True
    replay = runner.invoke(main, plan_arguments)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
    plan_path = Path(first_payload["data"]["publication"]["path"])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    execution_path = tmp_path / "execution.json"
    execution_path.write_text(json.dumps(_execution(plan)), encoding="utf-8")
    report_output = tmp_path / "reports"
    validate_arguments = [
        "daz",
        "recipes",
        "validate-pass-run",
        "--plan",
        str(plan_path),
        "--execution",
        str(execution_path),
        "--policy",
        str(POLICY_PATH),
        "--output",
        str(report_output),
    ]
    validated = runner.invoke(main, validate_arguments)
    assert validated.exit_code == 0, validated.output
    assert json.loads(validated.output)["data"]["summary"]["passed"] is True
    validated_replay = runner.invoke(main, validate_arguments)
    assert validated_replay.exit_code == 0, validated_replay.output
    assert json.loads(validated_replay.output)["data"]["publication"]["published"] is False
