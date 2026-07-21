from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.daz.assets import (
    AssetSmokeError,
    build_asset_change_impact,
    build_asset_compatibility_graph,
    build_asset_quarantine_record,
    build_asset_smoke_plan,
    decide_asset_retest,
    evaluate_asset_smoke_result,
    issue_asset_smoke_certificate,
    load_asset_smoke_policy,
    load_asset_vocabularies,
    project_active_qualified_asset_ids,
    publish_asset_smoke_document,
    validate_asset_smoke_certificate,
)

ROOT = Path(__file__).resolve().parents[1]
VOCABULARIES = ROOT / "configs" / "daz" / "asset_vocabularies.yaml"
POLICY = ROOT / "configs" / "daz" / "asset_smoke.yaml"


def _id(token: str) -> str:
    return "ast_" + token * 24


def _record(token: str, primary_class: str, **overrides) -> dict:
    record = {
        "asset_id": _id(token),
        "asset_sha256": token * 64,
        "primary_asset_class": primary_class,
        "identity_status": "unique",
        "mapping_requirement": "none",
        "character_scope": "adult_human",
        "figure_generations": ["genesis_9"],
        "scene_categories": ["clothed"],
        "compatibility_bases": [],
        "required_plugins": [],
        "capabilities": [],
        "facets": {},
        "dependencies": [],
    }
    record.update(overrides)
    return record


def _policy_and_vocabularies() -> tuple[dict, dict]:
    vocabularies = load_asset_vocabularies(VOCABULARIES)
    policy = load_asset_smoke_policy(POLICY, asset_classes=vocabularies["primary_asset_classes"])
    return policy, vocabularies


def _plan(tmp_path: Path, primary_class: str = "figure_base", **record_overrides) -> dict:
    policy, vocabularies = _policy_and_vocabularies()
    record = _record("a", primary_class, **record_overrides)
    graph = build_asset_compatibility_graph([record], vocabularies)
    first = tmp_path / "primary"
    second = tmp_path / "user"
    first.mkdir()
    second.mkdir()
    mapping_required = record["mapping_requirement"] != "none"
    return build_asset_smoke_plan(
        graph,
        policy,
        asset_id=record["asset_id"],
        created_at="2026-07-16T12:00:00Z",
        bundle_version="1.0.0",
        runtime_snapshot_sha256="b" * 64,
        script_bundle_sha256="c" * 64,
        content_directories=(first, second),
        mapping_bundle_id="map_v1" if mapping_required else None,
        mapping_bundle_sha256="d" * 64 if mapping_required else None,
    )


def _result(plan: dict) -> dict:
    executions = []
    for repetition in (1, 2):
        artifacts = []
        for index, role in enumerate(plan["required_artifact_roles"], start=1):
            token = format(index, "x")
            artifacts.append({"role": role, "sha256": token * 64, "bytes": index})
        executions.append(
            {
                "repetition": repetition,
                "process_identity": f"daz-process-{repetition}",
                "checks": {check: "pass" for check in plan["required_checks"]},
                "artifacts": artifacts,
                "dialog_count": 0,
                "fatal_log_count": 0,
                "duration_ms": 1000,
                "peak_memory_bytes": 1024,
                "peak_vram_bytes": 2048,
            }
        )
    return {
        "schema_version": "1.0.0",
        "result_id": "dsmr_" + "e" * 24,
        "plan_id": plan["plan_id"],
        "plan_sha256": plan["plan_sha256"],
        "asset_id": plan["asset_id"],
        "asset_sha256": plan["asset_sha256"],
        "dependency_snapshot_sha256": plan["dependency_snapshot_sha256"],
        "runtime_snapshot_sha256": plan["runtime_snapshot_sha256"],
        "script_bundle_sha256": plan["script_bundle_sha256"],
        "mapping_bundle_id": plan["mapping_bundle_id"],
        "mapping_bundle_sha256": plan["mapping_bundle_sha256"],
        "executions": executions,
    }


def test_policy_covers_every_known_asset_class_once_and_exact_quarantine_taxonomy() -> None:
    policy, vocabularies = _policy_and_vocabularies()
    covered = [
        asset_class
        for profile in policy["profiles"].values()
        for asset_class in profile["asset_classes"]
    ]
    assert sorted(covered) == sorted(set(vocabularies["primary_asset_classes"]) - {"unknown"})
    assert sorted(policy["quarantine_codes"].values()) == [
        f"Q-ASSET-{index:03d}" for index in range(1, 23)
    ]


@pytest.mark.parametrize(
    "primary_class,profile_id",
    [
        ("figure_base", "figure"),
        ("body_morph", "morph"),
        ("material_skin", "material"),
        ("hair_fitted", "hair"),
        ("wardrobe_top", "wardrobe"),
        ("pose_full_body", "pose"),
        ("expression", "expression"),
        ("anatomy_geograft", "anatomy"),
        ("prop_occluder", "scene_component"),
        ("script", "tool"),
        ("documentation_support", "documentation"),
    ],
)
def test_every_type_profile_builds_two_clean_process_recipes(
    tmp_path: Path, primary_class: str, profile_id: str
) -> None:
    plan = _plan(tmp_path, primary_class)
    assert plan["profile_id"] == profile_id
    assert [recipe["payload"]["repetition"] for recipe in plan["recipes"]] == [1, 2]
    assert all(recipe["operation"] == "asset_smoke" for recipe in plan["recipes"])
    assert all(recipe["payload"]["clean_process_required"] for recipe in plan["recipes"])


def test_mapping_required_asset_requires_and_binds_mapping_bundle(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "anatomy_geograft", mapping_requirement="asset_specific")
    assert plan["mapping_bundle_id"] == "map_v1"
    assert plan["mapping_bundle_sha256"] == "d" * 64

    policy, vocabularies = _policy_and_vocabularies()
    graph = build_asset_compatibility_graph(
        [_record("a", "anatomy_geograft", mapping_requirement="asset_specific")],
        vocabularies,
    )
    with pytest.raises(AssetSmokeError, match="smoke_mapping_binding_missing"):
        build_asset_smoke_plan(
            graph,
            policy,
            asset_id=_id("a"),
            created_at="2026-07-16T12:00:00Z",
            bundle_version="1.0.0",
            runtime_snapshot_sha256="b" * 64,
            script_bundle_sha256="c" * 64,
            content_directories=(tmp_path / "primary", tmp_path / "user"),
        )


def test_passing_result_requires_complete_checks_artifacts_and_semantic_replay(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    policy, _ = _policy_and_vocabularies()
    evaluation = evaluate_asset_smoke_result(plan, _result(plan), policy)
    assert evaluation["passed"] is True
    assert evaluation["issues"] == []
    assert evaluation["quarantine_codes"] == []


def test_binding_process_and_semantic_drift_fail_closed(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    policy, _ = _policy_and_vocabularies()
    result = _result(plan)
    result["runtime_snapshot_sha256"] = "f" * 64
    result["executions"][1]["process_identity"] = result["executions"][0]["process_identity"]
    result["executions"][1]["artifacts"][1]["sha256"] = "f" * 64
    evaluation = evaluate_asset_smoke_result(plan, result, policy)
    assert evaluation["passed"] is False
    assert "binding_mismatch:runtime_snapshot_sha256" in evaluation["issues"]
    assert "separate_process_repetition_missing" in evaluation["issues"]
    assert "semantic_hash_drift:silhouette" in evaluation["issues"]
    assert "Q-ASSET-020" in evaluation["quarantine_codes"]


def test_failed_check_dialog_duplicate_artifact_and_repetition_are_quarantined(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, "wardrobe_top")
    policy, _ = _policy_and_vocabularies()
    result = _result(plan)
    result["executions"][0]["checks"]["texture_maps_resolved"] = "fail"
    result["executions"][0]["dialog_count"] = 1
    result["executions"][1]["repetition"] = 1
    result["executions"][0]["artifacts"].append(deepcopy(result["executions"][0]["artifacts"][0]))
    evaluation = evaluate_asset_smoke_result(plan, result, policy)
    assert evaluation["passed"] is False
    assert "Q-ASSET-007" in evaluation["quarantine_codes"]
    assert "Q-ASSET-009" in evaluation["quarantine_codes"]
    assert "Q-ASSET-020" in evaluation["quarantine_codes"]
    assert "artifact_duplicate:1" in evaluation["issues"]
    assert "execution_repetitions_invalid" in evaluation["issues"]


def test_unknown_or_statically_ineligible_asset_cannot_be_planned(tmp_path: Path) -> None:
    policy, vocabularies = _policy_and_vocabularies()
    graph = build_asset_compatibility_graph(
        [_record("a", "unknown", character_scope="unknown")], vocabularies
    )
    primary = tmp_path / "primary"
    user = tmp_path / "user"
    primary.mkdir()
    user.mkdir()
    with pytest.raises(AssetSmokeError, match="smoke_asset_not_statically_eligible"):
        build_asset_smoke_plan(
            graph,
            policy,
            asset_id=_id("a"),
            created_at="2026-07-16T12:00:00Z",
            bundle_version="1.0.0",
            runtime_snapshot_sha256="b" * 64,
            script_bundle_sha256="c" * 64,
            content_directories=(primary, user),
        )


def test_smoke_publication_is_immutable_and_idempotent(tmp_path: Path) -> None:
    document = {"schema_version": "1.0.0", "value": 1}
    target, published = publish_asset_smoke_document(document, tmp_path, document_id="example")
    assert published is True
    assert publish_asset_smoke_document(document, tmp_path, document_id="example") == (
        target,
        False,
    )
    with pytest.raises(AssetSmokeError, match="smoke_immutable_publication_conflict"):
        publish_asset_smoke_document(
            {"schema_version": "1.0.0", "value": 2},
            tmp_path,
            document_id="example",
        )


def test_smoke_cli_builds_and_evaluates_an_immutable_plan(tmp_path: Path) -> None:
    _, vocabularies = _policy_and_vocabularies()
    graph = build_asset_compatibility_graph([_record("a", "figure_base")], vocabularies)
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    primary = tmp_path / "primary"
    user = tmp_path / "user"
    primary.mkdir()
    user.mkdir()
    plan_root = tmp_path / "plans"
    runner = CliRunner()
    invocation = runner.invoke(
        main,
        [
            "daz",
            "assets",
            "smoke-plan",
            "--graph",
            str(graph_path),
            "--asset-id",
            _id("a"),
            "--created-at",
            "2026-07-16T12:00:00Z",
            "--bundle-version",
            "1.0.0",
            "--runtime-snapshot-sha256",
            "b" * 64,
            "--script-bundle-sha256",
            "c" * 64,
            "--content-directory",
            str(primary),
            "--content-directory",
            str(user),
            "--output",
            str(plan_root),
        ],
    )
    assert invocation.exit_code == 0, invocation.output
    plan_envelope = json.loads(invocation.output)
    plan_path = Path(plan_envelope["data"]["publication"]["path"])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(_result(plan)), encoding="utf-8")

    evaluated = runner.invoke(
        main,
        [
            "daz",
            "assets",
            "smoke-evaluate",
            "--plan",
            str(plan_path),
            "--result",
            str(result_path),
            "--output",
            str(tmp_path / "evaluations"),
        ],
    )
    assert evaluated.exit_code == 0, evaluated.output
    evaluation_envelope = json.loads(evaluated.output)
    assert evaluation_envelope["reason"] == "asset_smoke_passed"

    certified = runner.invoke(
        main,
        [
            "daz",
            "assets",
            "smoke-certify",
            "--plan",
            str(plan_path),
            "--result",
            str(result_path),
            "--evaluation",
            evaluation_envelope["data"]["publication"]["path"],
            "--graph",
            str(graph_path),
            "--created-at",
            "2026-07-16T12:05:00Z",
            "--output",
            str(tmp_path / "certificates"),
        ],
    )
    assert certified.exit_code == 0, certified.output
    assert json.loads(certified.output)["reason"] == "asset_smoke_certificate_issued"


def test_passing_evaluation_issues_hash_bound_certificate_and_change_invalidates_it(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    result = _result(plan)
    policy, vocabularies = _policy_and_vocabularies()
    evaluation = evaluate_asset_smoke_result(plan, result, policy)
    graph = build_asset_compatibility_graph([_record("a", "figure_base")], vocabularies)
    certificate = issue_asset_smoke_certificate(
        plan,
        result,
        evaluation,
        graph,
        created_at="2026-07-16T12:05:00Z",
    )
    active = validate_asset_smoke_certificate(
        certificate,
        graph,
        runtime_snapshot_sha256="b" * 64,
        script_bundle_sha256="c" * 64,
    )
    assert active["state"] == "active"
    assert active["reasons"] == []
    projection = project_active_qualified_asset_ids(
        [certificate],
        graph,
        runtime_snapshot_sha256="b" * 64,
        script_bundle_sha256="c" * 64,
    )
    assert projection["qualified_asset_ids"] == [plan["asset_id"]]
    assert projection["excluded"] == []
    graph_path = tmp_path / "qualified_graph.json"
    certificates_path = tmp_path / "certificates.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    certificates_path.write_text(json.dumps([certificate]), encoding="utf-8")
    pool_invocation = CliRunner().invoke(
        main,
        [
            "daz",
            "assets",
            "pool-report",
            "--graph",
            str(graph_path),
            "--certificates",
            str(certificates_path),
            "--runtime-snapshot-sha256",
            "b" * 64,
            "--script-bundle-sha256",
            "c" * 64,
            "--output",
            str(tmp_path / "qualified_pools"),
        ],
    )
    assert pool_invocation.exit_code == 0, pool_invocation.output
    pool_envelope = json.loads(pool_invocation.output)
    assert pool_envelope["data"]["qualification_projection"]["qualified_asset_ids"] == [
        plan["asset_id"]
    ]

    stale = validate_asset_smoke_certificate(
        certificate,
        graph,
        runtime_snapshot_sha256="f" * 64,
        script_bundle_sha256="c" * 64,
    )
    assert stale["state"] == "revoked_or_stale"
    assert stale["reasons"] == ["runtime_snapshot_changed"]
    stale_projection = project_active_qualified_asset_ids(
        [certificate],
        graph,
        runtime_snapshot_sha256="f" * 64,
        script_bundle_sha256="c" * 64,
    )
    assert stale_projection["qualified_asset_ids"] == []
    assert stale_projection["excluded"][0]["reasons"] == ["runtime_snapshot_changed"]


def test_asset_change_revokes_downstream_certificate_and_blocks_queued_recipe(
    tmp_path: Path,
) -> None:
    policy, vocabularies = _policy_and_vocabularies()
    base = _record("a", "figure_base")
    wardrobe = _record(
        "b",
        "wardrobe_top",
        compatibility_bases=[base["asset_id"]],
        dependencies=[
            {
                "target_asset_id": base["asset_id"],
                "relation": "fits_to",
                "required": True,
            }
        ],
    )
    graph = build_asset_compatibility_graph([base, wardrobe], vocabularies)
    primary = tmp_path / "primary"
    user = tmp_path / "user"
    primary.mkdir()
    user.mkdir()
    certificates = []
    plans = []
    for record in (base, wardrobe):
        plan = build_asset_smoke_plan(
            graph,
            policy,
            asset_id=record["asset_id"],
            created_at="2026-07-16T12:00:00Z",
            bundle_version="1.0.0",
            runtime_snapshot_sha256="b" * 64,
            script_bundle_sha256="c" * 64,
            content_directories=(primary, user),
        )
        result = _result(plan)
        evaluation = evaluate_asset_smoke_result(plan, result, policy)
        certificates.append(
            issue_asset_smoke_certificate(
                plan,
                result,
                evaluation,
                graph,
                created_at="2026-07-16T12:05:00Z",
            )
        )
        plans.append(plan)

    impact = build_asset_change_impact(
        graph,
        certificates,
        [plan["recipes"][0] for plan in plans],
        changed_asset_ids=[base["asset_id"]],
        runtime_snapshot_sha256="b" * 64,
        script_bundle_sha256="c" * 64,
    )
    assert impact["affected_asset_ids"] == [base["asset_id"], wardrobe["asset_id"]]
    assert {row["asset_id"] for row in impact["revoked_certificates"]} == {
        base["asset_id"],
        wardrobe["asset_id"],
    }
    assert {row["asset_id"] for row in impact["blocked_recipes"]} == {
        base["asset_id"],
        wardrobe["asset_id"],
    }
    dependent = next(
        row for row in impact["revoked_certificates"] if row["asset_id"] == wardrobe["asset_id"]
    )
    assert dependent["reasons"] == ["asset_or_dependency_changed"]


def test_failed_smoke_creates_quarantine_and_change_gated_retest(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "material_skin")
    policy, _ = _policy_and_vocabularies()
    result = _result(plan)
    result["executions"][0]["checks"]["texture_maps_resolved"] = "fail"
    evaluation = evaluate_asset_smoke_result(plan, result, policy)
    quarantine = build_asset_quarantine_record(
        plan,
        result,
        evaluation,
        observed_at="2026-07-16T12:05:00Z",
        log_excerpt_sha256="f" * 64,
        retry_count=0,
    )
    assert quarantine["quarantine_codes"] == ["Q-ASSET-007"]
    assert decide_asset_retest(quarantine)["decision"] == "retest_blocked"
    allowed = decide_asset_retest(quarantine, content_repaired=True)
    assert allowed["decision"] == "eligible_for_retest"
    assert allowed["next_clean_process_retry"] == 1
