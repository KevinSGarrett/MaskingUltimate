from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
TRACKER_SOURCE = ROOT / "Plan" / "Tracker" / "tracker.py"
REGISTRY = ROOT / "Plan" / "Tracker" / "completion_track_registry.json"
TRACKER_JSON = ROOT / "Plan" / "Tracker" / "tracker.json"


def _tracker_module() -> dict:
    return runpy.run_path(str(TRACKER_SOURCE))


def _data_for_profiles(module: dict, status: str = "open") -> dict:
    parsed = module["parse_items_files"]()
    return {
        "items": {
            item_id: {
                **item,
                "status": status,
                "orphaned": False,
                "percent_complete": 100 if status == "complete" else 0,
                "evidence": "fixture evidence" if status == "complete" else None,
                "blocked_reason": None,
                "notes": [],
            }
            for item_id, item in parsed.items()
        }
    }


def test_doc24_addendum_contributes_exactly_forty_three_unique_open_p6_rows() -> None:
    module = _tracker_module()
    items = module["parse_items_files"]()
    addendum = [
        item
        for item in items.values()
        if item["source_file"] == "21_ITEMS_P6_AUTONOMOUS_CORE_AND_CROSS_PROJECT_BRIDGE.md"
    ]
    assert len(items) == 798
    assert len(addendum) == 43
    assert {item["cluster_id"] for item in addendum} == {
        "MF-P6-07",
        "MF-P6-08",
        "MF-P6-09",
        "MF-P6-10",
        "MF-P6-11",
        "MF-P6-12",
    }
    for item in addendum:
        assert item["phase"] == "P6"
        assert "Verify:" in item["description"]
        assert "Blocked by:" in item["description"]

    state = json.loads(TRACKER_JSON.read_text(encoding="utf-8"))["items"]
    for item in addendum:
        assert state[item["id"]]["status"] == "open"
        assert state[item["id"]]["percent_complete"] == 0
        assert state[item["id"]]["evidence"] is None


def test_completion_registry_and_tracker_freeze_three_claim_scoped_profiles() -> None:
    module = _tracker_module()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    profiles = {row["profile_id"]: row for row in registry["profiles"]}
    assert set(profiles) == {
        "core_autonomous_runtime",
        "independent_real_accuracy",
        "scale_daz_maturity",
    }
    assert set(profiles) == set(module["COMPLETION_PROFILES"])
    assert profiles["core_autonomous_runtime"]["classification"] == "required"
    assert profiles["core_autonomous_runtime"]["blocking_for_core_completion"] is True
    assert profiles["independent_real_accuracy"]["blocking_for_core_completion"] is False
    assert profiles["scale_daz_maturity"]["blocking_for_core_completion"] is False
    assert set(profiles["core_autonomous_runtime"]["excluded_core_dependencies"]) == set(
        module["CORE_EXCLUDED_DEPENDENCIES"]
    )
    addendum_ids = {
        item_id
        for item_id, item in module["parse_items_files"]().items()
        if item["source_file"] == "21_ITEMS_P6_AUTONOMOUS_CORE_AND_CROSS_PROJECT_BRIDGE.md"
    }
    assert set(profiles["core_autonomous_runtime"]["required_item_ids"]) == addendum_ids
    assert (
        module["validate_completion_track_registry"](
            {"items": {item_id: {"orphaned": False} for item_id in module["parse_items_files"]()}}
        )
        == []
    )


def test_closed_registry_validation_rejects_unknown_fields() -> None:
    module = _tracker_module()
    validate = module["validate_completion_track_registry"]
    globals_ = validate.__globals__
    original_loader = globals_["load_completion_track_registry"]
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry["unexpected"] = True
    registry["profiles"][0]["unexpected"] = True
    globals_["load_completion_track_registry"] = lambda: registry
    try:
        problems = validate(
            {"items": {item_id: {"orphaned": False} for item_id in module["parse_items_files"]()}}
        )
    finally:
        globals_["load_completion_track_registry"] = original_loader
    assert any("unknown top-level fields" in problem for problem in problems)
    assert any("core_autonomous_runtime has unknown fields" in problem for problem in problems)


def test_completion_registry_binds_its_canonical_content_and_governing_spec_bytes() -> None:
    module = _tracker_module()
    validate = module["validate_completion_track_registry"]
    globals_ = validate.__globals__
    original_loader = globals_["load_completion_track_registry"]
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    data = {"items": {item_id: {"orphaned": False} for item_id in module["parse_items_files"]()}}

    registry["authoritative_spec_sha256"] = "0" * 64
    globals_["load_completion_track_registry"] = lambda: registry
    try:
        problems = validate(data)
    finally:
        globals_["load_completion_track_registry"] = original_loader
    assert any("authoritative_spec_sha256 drifted" in problem for problem in problems)
    assert any("registry sha256 drifted" in problem for problem in problems)

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry["purpose"] = "tampered"
    globals_["load_completion_track_registry"] = lambda: registry
    try:
        problems = validate(data)
    finally:
        globals_["load_completion_track_registry"] = original_loader
    assert any("registry sha256 drifted" in problem for problem in problems)


def test_dependency_parser_expands_same_cluster_ranges() -> None:
    parse = _tracker_module()["parse_dependency_ids"]
    assert parse("Verify: x · Blocked by: MF-P6-07.02 through MF-P6-07.06, MF-P8-05.01") == [
        "MF-P6-07.02",
        "MF-P6-07.06",
        "MF-P8-05.01",
        "MF-P6-07.03",
        "MF-P6-07.04",
        "MF-P6-07.05",
    ]


def test_profile_statuses_are_computed_independently() -> None:
    module = _tracker_module()
    data = _data_for_profiles(module, "complete")
    compute = module["compute_completion_profile_status"]
    assert compute(data, "core_autonomous_runtime") == "complete"
    assert compute(data, "independent_real_accuracy") == "complete"
    assert compute(data, "scale_daz_maturity") == "complete"

    core_closure = module["completion_profile_dependency_closure"](data, "core_autonomous_runtime")
    optional_id = next(
        item_id
        for item_id in module["COMPLETION_PROFILES"]["independent_real_accuracy"]["driven_by"]
        if item_id not in core_closure
    )
    data["items"][optional_id]["status"] = "blocked"
    assert compute(data, "independent_real_accuracy") == "blocked"
    assert compute(data, "core_autonomous_runtime") == "complete"

    core_id = module["COMPLETION_PROFILES"]["core_autonomous_runtime"]["driven_by"][0]
    data["items"][core_id]["status"] = "open"
    assert compute(data, "core_autonomous_runtime") == "in_progress"
    assert compute(data, "scale_daz_maturity") == "waiting_for_prerequisite"


def test_core_completion_requires_full_dependency_closure_and_never_accepts_na() -> None:
    module = _tracker_module()
    data = _data_for_profiles(module, "complete")
    compute = module["compute_completion_profile_status"]
    direct = set(module["COMPLETION_PROFILES"]["core_autonomous_runtime"]["driven_by"])
    closure = module["completion_profile_dependency_closure"](data, "core_autonomous_runtime")
    external = sorted(closure.difference(direct))
    assert external

    data["items"][external[0]]["status"] = "blocked"
    assert compute(data, "core_autonomous_runtime") == "blocked"
    data["items"][external[0]]["status"] = "complete"

    for item_id in direct:
        data["items"][item_id]["status"] = "not_applicable"
    assert compute(data, "core_autonomous_runtime") != "complete"


def test_set_rejects_na_for_mandatory_core_and_allows_evidenced_optional_conditional() -> None:
    module = _tracker_module()
    data = _data_for_profiles(module, "open")
    cmd_set = module["cmd_set"]
    globals_ = cmd_set.__globals__
    originals = {
        name: globals_[name]
        for name in ("load_tracker_or_exit", "save_tracker", "append_changelog")
    }
    saved = []
    globals_["load_tracker_or_exit"] = lambda: data
    globals_["save_tracker"] = lambda value: saved.append(value)
    globals_["append_changelog"] = lambda _value: None
    try:
        core_id = module["COMPLETION_PROFILES"]["core_autonomous_runtime"]["driven_by"][0]
        with pytest.raises(SystemExit, match="non-conditional item"):
            cmd_set(
                SimpleNamespace(
                    id=core_id,
                    status="not_applicable",
                    note=None,
                    evidence="trigger did not fire",
                    percent=None,
                    blocked_reason=None,
                    actor="test",
                )
            )

        closure = module["completion_profile_dependency_closure"](data, "core_autonomous_runtime")
        optional_conditional = next(
            item_id
            for item_id, item in data["items"].items()
            if item["conditional"] and item_id not in closure
        )
        cmd_set(
            SimpleNamespace(
                id=optional_conditional,
                status="not_applicable",
                note=None,
                evidence="documented conditional trigger did not fire",
                percent=None,
                blocked_reason=None,
                actor="test",
            )
        )
        assert saved
        assert data["items"][optional_conditional]["status"] == "not_applicable"
    finally:
        globals_.update(originals)


def test_registry_is_validated_against_draft_2020_12_schema() -> None:
    module = _tracker_module()
    validate = module["validate_completion_track_registry"]
    globals_ = validate.__globals__
    original_loader = globals_["load_completion_track_registry"]
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry["policy_version"] = "not-a-date"
    globals_["load_completion_track_registry"] = lambda: registry
    try:
        problems = validate(
            {"items": {item_id: {"orphaned": False} for item_id in module["parse_items_files"]()}}
        )
    finally:
        globals_["load_completion_track_registry"] = original_loader
    assert any("schema violation" in problem for problem in problems)


def test_default_next_prioritizes_core_and_profile_filter_is_exact() -> None:
    module = _tracker_module()
    parsed = module["parse_items_files"]()
    data = {
        "items": {
            item_id: {
                **item,
                "status": "open",
                "orphaned": False,
                "percent_complete": 0,
            }
            for item_id, item in parsed.items()
        }
    }
    next_default = module["suggest_next"](data, 5)
    core_ids = module["completion_profile_dependency_closure"](data, "core_autonomous_runtime")
    assert next_default
    assert all(item["id"] in core_ids for item in next_default)

    next_accuracy = module["suggest_next"](
        data, len(data["items"]), profile="independent_real_accuracy"
    )
    accuracy_ids = module["completion_profile_dependency_closure"](
        data, "independent_real_accuracy"
    )
    assert {item["id"] for item in next_accuracy} == accuracy_ids


def test_core_dependency_firewall_detects_transitive_human_dependency() -> None:
    module = _tracker_module()
    parsed = module["parse_items_files"]()
    data = {
        "items": {
            item_id: {**item, "status": "open", "orphaned": False}
            for item_id, item in parsed.items()
        }
    }
    assert module["validate_core_dependency_firewall"](data) == []

    root = "MF-P6-08.06"
    dependency = "MF-P6-08.05"
    original = data["items"][dependency]["description"]
    data["items"][dependency]["description"] = (
        original + " · Blocked by: NEEDS KEVIN: human-anchor masks and CVAT correction"
    )
    problems = module["validate_core_dependency_firewall"](data)
    assert any(root in problem and dependency in problem for problem in problems)


def test_dashboard_leads_with_core_and_separates_optional_blockers(tmp_path: Path) -> None:
    module = _tracker_module()
    parsed = module["parse_items_files"]()
    data = {
        "items": {
            item_id: {
                **item,
                "status": "open",
                "orphaned": False,
                "percent_complete": 0,
                "notes": [],
                "evidence": None,
                "blocked_reason": None,
            }
            for item_id, item in parsed.items()
        },
        "metrics": dict(module["DEFAULT_METRICS"]),
        "goals": {goal_id: {"status": "pending", "measured": None} for goal_id in module["GOALS"]},
    }
    output = tmp_path / "DASHBOARD.md"
    original = module["DASHBOARD"]
    module["render_dashboard"].__globals__["DASHBOARD"] = output
    try:
        module["render_dashboard"](data)
    finally:
        module["render_dashboard"].__globals__["DASHBOARD"] = original
    text = output.read_text(encoding="utf-8")
    assert text.index("Required Core Status") < text.index("Portfolio Progress")
    assert "Core Blockers (required autonomous-runtime profile)" in text
    assert "Optional / Portfolio Blockers (do not redefine core completion)" in text
    assert "DAZ is part of the post-core optional" in text
    assert "Active priority:** complete the first live verified DAZ" not in text


def test_p6_phase_report_groups_each_source_and_cluster_contiguously(tmp_path: Path) -> None:
    module = _tracker_module()
    parsed = module["parse_items_files"]()
    data = {
        "items": {
            item_id: {
                **item,
                "status": "open",
                "orphaned": False,
                "percent_complete": 0,
                "notes": [],
                "evidence": None,
                "blocked_reason": None,
            }
            for item_id, item in parsed.items()
        }
    }
    output_dir = tmp_path / "phases"
    output_dir.mkdir()
    original = module["PHASES_DIR"]
    module["render_phase_file"].__globals__["PHASES_DIR"] = output_dir
    try:
        module["render_phase_file"](data, "P6")
    finally:
        module["render_phase_file"].__globals__["PHASES_DIR"] = original
    text = (output_dir / "P6.md").read_text(encoding="utf-8")
    assert "07_ITEMS_P6_COMFYUI_SERVING.md" in text
    assert "17_ITEMS_P6_MODERN_SERVING.md" in text
    assert "21_ITEMS_P6_AUTONOMOUS_CORE_AND_CROSS_PROJECT_BRIDGE.md" in text
    for cluster_id in {item["cluster_id"] for item in parsed.values() if item["phase"] == "P6"}:
        assert text.count(f"### {cluster_id} ") <= 1


def test_legacy_human_and_scale_completion_language_is_profile_scoped() -> None:
    active_surfaces = {
        "ontology": ROOT / "Plan" / "02_MASK_ONTOLOGY_SPEC.md",
        "gold_format": ROOT / "Plan" / "03_GOLD_MASK_FORMAT_SPEC.md",
        "manifests": ROOT / "Plan" / "04_DATA_SCHEMAS_AND_MANIFESTS.md",
        "architecture": ROOT / "Plan" / "05_SYSTEM_ARCHITECTURE.md",
        "installation": ROOT / "Plan" / "06_ENVIRONMENT_AND_INSTALLATION.md",
        "stages": ROOT / "Plan" / "07_PIPELINE_STAGE_SPECS.md",
        "specialists": ROOT / "Plan" / "08_SPECIALIST_LANES_SPEC.md",
        "auto_qa": ROOT / "Plan" / "09_AUTO_QA_VALIDATION_SPEC.md",
        "llm_vlm": ROOT / "Plan" / "10_LLM_VLM_QA_LAYER.md",
        "human_review": ROOT / "Plan" / "11_HUMAN_REVIEW_WORKFLOW.md",
        "dataset": ROOT / "Plan" / "12_DATASET_TRAINING_ACTIVE_LEARNING.md",
        "roadmap": ROOT / "Plan" / "14_IMPLEMENTATION_ROADMAP_WBS.md",
        "multi_person": ROOT / "Plan" / "17_MULTI_PERSON_MULTI_CHARACTER_MASKING_SPEC.md",
        "foundation": ROOT / "Plan" / "16_EXTERNAL_FOUNDATION_BOOTSTRAP.md",
        "multi_provider": ROOT
        / "Plan"
        / "19_MULTI_PROVIDER_TEACHER_AND_CONTINUOUS_IMPROVEMENT_SPEC.md",
        "population_certificate": ROOT / "Plan" / "20_PROGRESSIVE_AUTONOMOUS_MASK_FACTORY_SPEC.md",
        "repair": ROOT / "Plan" / "21_AUTONOMOUS_REPAIR_EXECUTION_SPEC.md",
        "currency": ROOT / "Plan" / "22_TECHNOLOGY_CURRENCY_AND_MODEL_CHALLENGE_SPEC.md",
        "operations": ROOT / "Plan" / "15_RISKS_OPERATIONS_RUNBOOK.md",
        "ontology_v2": ROOT / "Plan" / "18_ADULT_ANATOMY_ONTOLOGY_V2_SPEC.md",
        "core": ROOT / "Plan" / "24_AUTONOMOUS_CORE_COMPLETION_AND_COMFYUI_BRIDGE.md",
        "multi_person_horizon": ROOT / "Plan" / "HORIZON_MULTI_PERSON_GO_NO_GO.md",
        "video_horizon": ROOT / "Plan" / "HORIZON_VIDEO_GO_NO_GO.md",
        "civitai_intake": ROOT / "Plan" / "CIVITAI_WORKFLOW_INTAKE.md",
        "p1_items": ROOT / "Plan" / "Items" / "02_ITEMS_P1_GOLD_FACTORY_MVP.md",
        "p2_items": ROOT / "Plan" / "Items" / "03_ITEMS_P2_BODY_AWARE_DRAFTING.md",
        "p3_items": ROOT / "Plan" / "Items" / "04_ITEMS_P3_SPECIALIST_LANES.md",
        "p4_items": ROOT / "Plan" / "Items" / "05_ITEMS_P4_VLM_QA_ACTIVE_LEARNING.md",
        "p5_items": ROOT / "Plan" / "Items" / "06_ITEMS_P5_TRAINING.md",
        "p6_items": ROOT / "Plan" / "Items" / "07_ITEMS_P6_COMFYUI_SERVING.md",
        "p7_items": ROOT / "Plan" / "Items" / "08_ITEMS_P7_SCALE_OPERATIONS.md",
        "p1_v2_items": ROOT / "Plan" / "Items" / "12_ITEMS_P1_ONTOLOGY_V2_AND_TRUTH.md",
        "p2_provider_items": ROOT / "Plan" / "Items" / "13_ITEMS_P2_PROVIDER_MODERNIZATION.md",
        "p3_modern_items": ROOT / "Plan" / "Items" / "14_ITEMS_P3_MODERN_SPECIALISTS.md",
        "p4_autonomy_items": ROOT / "Plan" / "Items" / "15_ITEMS_P4_AUTONOMY_AND_TEACHERS.md",
        "p5_certified_items": ROOT / "Plan" / "Items" / "16_ITEMS_P5_CERTIFIED_TRAINING.md",
        "p6_modern_items": ROOT / "Plan" / "Items" / "17_ITEMS_P6_MODERN_SERVING.md",
        "p7_currency_items": ROOT / "Plan" / "Items" / "18_ITEMS_P7_CURRENCY_OPERATIONS.md",
        "p8_autonomy_items": ROOT / "Plan" / "Items" / "19_ITEMS_P8_AUTONOMOUS_MULTI_PERSON.md",
        "p9_daz_items": ROOT / "Plan" / "Items" / "20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md",
        "quick_reference": ROOT / "Plan" / "Instructions" / "07_PHASE_QUICK_REFERENCE.md",
        "tracker_readme": ROOT / "Plan" / "Tracker" / "README.md",
    }
    joined = "\n".join(path.read_text(encoding="utf-8") for path in active_surfaces.values())
    normalized = {
        key: " ".join(path.read_text(encoding="utf-8").replace("\n>", "\n").split())
        for key, path in active_surfaces.items()
    }
    assert "D2 core" not in joined
    assert "P7 / PROJECT Exit Gate" not in joined
    assert 'system is "done" at 300 gold' not in joined
    assert "core_autonomous_runtime" in joined
    assert "independent_real_accuracy" in joined
    assert "scale_daz_maturity" in joined

    assert "not a `core_autonomous_runtime` dependency" in active_surfaces[
        "population_certificate"
    ].read_text(encoding="utf-8")
    assert "cannot block or revoke" in active_surfaces["currency"].read_text(encoding="utf-8")
    assert "never unilateral pixel or certificate authority" in " ".join(
        active_surfaces["llm_vlm"].read_text(encoding="utf-8").split()
    )
    assert "not the execution path or completion gate" in " ".join(
        active_surfaces["human_review"].read_text(encoding="utf-8").split()
    )
    assert "Human review and model-library completeness are not core-runtime prerequisites" in (
        " ".join(active_surfaces["foundation"].read_text(encoding="utf-8").split())
    )
    assert "cannot block `core_autonomous_runtime`" in " ".join(
        active_surfaces["multi_provider"].read_text(encoding="utf-8").split()
    )
    assert (
        "Human review and a minimum package count are not core prerequisites"
        in normalized["gold_format"]
    )
    assert "cannot self-upgrade" in active_surfaces["manifests"].read_text(encoding="utf-8")
    assert (
        "CVAT availability or human approval cannot block that route" in normalized["architecture"]
    )
    assert "core release doctor must report them separately" in normalized["installation"]
    assert "not a required CVAT task" in normalized["stages"]
    assert "typed autonomous abstention" in normalized["specialists"]
    assert "BLOCK** vetoes operational certification and gold alike" in normalized["auto_qa"]
    assert "cannot make the core runtime unhealthy" in normalized["operations"]
    assert "documents 18 and 21" in normalized["core"]
    assert "exact operational certificate policy or return typed abstention" in normalized["core"]
    assert "optional human/training-truth route" in normalized["ontology"]
    assert "Governed pipeline transaction; optional human correction" in normalized["ontology"]
    assert "Dataset construction, human correction" in normalized["dataset"]
    assert "not prerequisites for `core_autonomous_runtime`" in normalized["dataset"]
    assert (
        "Human review, CVAT, human-approved gold, training-data expansion"
        in normalized["multi_person"]
    )
    assert "cloud reviewer is never intrinsically required" in normalized["core"]
    assert (
        "Human approval is required only to create human-approved gold"
        in normalized["civitai_intake"]
    )
    core = active_surfaces["core"].read_text(encoding="utf-8")
    normalized_core = " ".join(core.split())
    assert "legacy portfolio/research evidence index only" in normalized_core
    assert "carries no core completion authority" in normalized_core
    assert "operationally_certified_artifact" in normalized_core
    assert (
        "No bridge receipt, LLM decision, or downstream acceptance can perform that promotion"
        in (normalized_core)
    )
    assert "trusted Ed25519 key registries" in normalized_core
    assert "canonical decoded-pixel hash" in normalized_core
    assert "signed/checkpointed append-only JSONL event journals" in normalized_core
    assert "source-video hash, frame index" in normalized_core
    assert "outcome_unknown" in normalized_core
    assert "Conversation history and LLM-generated summaries are caches only" in normalized_core
    assert "Free-form model text is never executed" in normalized_core
    assert "Mode A is an access path, not authority" in normalized_core
    assert (
        "raw package manifest, review status, filename, or certificate reference" in normalized_core
    )
    assert "not blocked by D11/G9 human evidence" in normalized["multi_person_horizon"]
    assert "Human review cannot block or revoke that route" in normalized["multi_person_horizon"]
    assert "GO FOR DOC-24 CONTRACT/RUNTIME IMPLEMENTATION" in normalized["video_horizon"]
    assert (
        "Human keyframes or CVAT cannot block or revoke this route" in normalized["video_horizon"]
    )
    assert "otherwise repair or abstain" in normalized["video_horizon"]
    for key in (
        "p1_v2_items",
        "p2_provider_items",
        "p3_modern_items",
        "p4_autonomy_items",
        "p5_certified_items",
        "p6_modern_items",
        "p7_currency_items",
        "p8_autonomy_items",
        "p9_daz_items",
    ):
        assert "Completion-profile scope (doc 24)" in normalized[key]
        assert "cannot block or revoke" in normalized[key]
    p7_scale = normalized["p7_items"]
    assert "`operationally_certified_artifact` is explicitly ineligible" in p7_scale
    assert "reject `operationally_certified_artifact`" in p7_scale
    assert "cannot be relabeled as `human_approved_gold` or `autonomous_certified_gold`" in p7_scale


def test_cross_project_session_handoff_pins_tasks_worktrees_and_adoption_order() -> None:
    handoff = (
        ROOT / "Plan" / "Instructions" / "09_CROSS_PROJECT_BRIDGE_RELEASE_AND_SESSION_HANDOFF.md"
    ).read_text(encoding="utf-8")
    doc24 = (ROOT / "Plan" / "24_AUTONOMOUS_CORE_COMPLETION_AND_COMFYUI_BRIDGE.md").read_text(
        encoding="utf-8"
    )
    start = (ROOT / "Plan" / "Instructions" / "00_START_HERE.md").read_text(encoding="utf-8")
    playbook = (ROOT / "Plan" / "Instructions" / "03_SESSION_PLAYBOOK.md").read_text(
        encoding="utf-8"
    )
    kickoff = (ROOT / "KICKOFF_PROMPT.md").read_text(encoding="utf-8")
    normalized_handoff = " ".join(handoff.split())

    for text in (handoff, doc24):
        assert "019f4cfc-60c3-7500-8626-261dcf70db5d" in text
        assert "019f422f-88b1-7382-872b-21de2089e983" in text
    assert "C:\\w\\mask-autonomy-bridge-plan" in handoff
    assert "codex/mask-autonomy-bridge-plan" in handoff
    assert "C:\\w\\main-maskfactory-bridge-plan" in handoff
    assert "codex/w64-maskfactory-bridge-plan" in handoff
    assert "producer release snapshot → Main" in normalized_handoff
    assert "outcome_unknown" in normalized_handoff
    assert "deferred_waiting_for_complete_model_download" in normalized_handoff
    assert "dirty bytes are planning work only" in normalized_handoff
    assert "09_CROSS_PROJECT_BRIDGE_RELEASE_AND_SESSION_HANDOFF.md" in start
    assert "09_CROSS_PROJECT_BRIDGE_RELEASE_AND_SESSION_HANDOFF.md" in kickoff
    assert "09_CROSS_PROJECT_BRIDGE_RELEASE_AND_SESSION_HANDOFF.md" in playbook
    assert "retain both isolated" in playbook
    assert "preservation signal, not adoption authority" in playbook


def test_planning_preservation_manifest_is_frozen_complete_and_hash_bound() -> None:
    manifest_path = (
        ROOT
        / "Plan"
        / "Instructions"
        / "10_AUTONOMOUS_CORE_BRIDGE_PLANNING_PRESERVATION_MANIFEST.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    claimed = manifest["manifest_sha256"]
    payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == claimed
    assert manifest["producer_contract_freeze_state"] == "frozen_for_review"
    assert manifest["runtime_completion_claimed"] is False
    assert manifest["manifest_path"] == (
        "Plan/Instructions/10_AUTONOMOUS_CORE_BRIDGE_PLANNING_PRESERVATION_MANIFEST.json"
    )
    assert manifest["self_inventory_policy"] == (
        "manifest_self_excluded_from_entries_and_bound_by_manifest_sha256"
    )
    assert manifest["producer"]["task_id"] == "019f4cfc-60c3-7500-8626-261dcf70db5d"
    assert manifest["consumer"]["task_id"] == "019f422f-88b1-7382-872b-21de2089e983"
    assert manifest["model_library_activation"]["state"] == (
        "deferred_waiting_for_complete_model_download"
    )
    entries = manifest["source_state"]["entries"]
    assert manifest["source_state"]["entry_count"] == len(entries)
    entries_canonical = json.dumps(
        entries, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert (
        hashlib.sha256(entries_canonical).hexdigest() == manifest["source_state"]["entries_sha256"]
    )
    paths = {entry["path"] for entry in entries}
    assert manifest["manifest_path"] not in paths
    assert {
        "Plan/24_AUTONOMOUS_CORE_COMPLETION_AND_COMFYUI_BRIDGE.md",
        "Plan/Items/21_ITEMS_P6_AUTONOMOUS_CORE_AND_CROSS_PROJECT_BRIDGE.md",
        "Plan/Tracker/completion_track_registry.json",
        "src/maskfactory/schemas/maskfactory_release_snapshot.schema.json",
        "src/maskfactory/schemas/maskfactory_qualification_bundle.schema.json",
        "tests/test_mask_bridge_contracts_v1.py",
        "tools/build_maskfactory_bridge_planning_preservation_manifest.py",
    }.issubset(paths)
    reconciliation_path = (
        ROOT
        / "Plan"
        / "Instructions"
        / "11_AUTONOMOUS_CORE_BRIDGE_INTEGRATION_RECONCILIATION_MANIFEST.json"
    )
    reconciliation = json.loads(reconciliation_path.read_text(encoding="utf-8"))
    reconciliation_claimed = reconciliation["manifest_sha256"]
    reconciliation_payload = {
        key: value for key, value in reconciliation.items() if key != "manifest_sha256"
    }
    assert (
        hashlib.sha256(
            json.dumps(
                reconciliation_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        == reconciliation_claimed
    )
    assert reconciliation["source_preservation_manifest"]["manifest_sha256"] == claimed
    assert reconciliation["git_lineage"]["immutable_producer_packet_commit"] == (
        "938b46949e277d92f26d9411fd5710005c506677"
    )
    assert reconciliation["git_lineage"]["integrated_base_commit"] == (
        "85d4c19b7974c1b64f48176d91211defbaba35a0"
    )
    drift_rows = {
        row["path"]: row for row in reconciliation["reconciliation"]["reconciled_changes"]
    }
    observed_drift = set()
    for entry in entries:
        assert entry["exists"] is True
        path = ROOT / entry["path"]
        assert path.is_file()
        content = path.read_bytes()
        live_sha256 = hashlib.sha256(content).hexdigest()
        if len(content) == entry["size_bytes"] and live_sha256 == entry["sha256"]:
            assert entry["path"] not in drift_rows
            continue
        observed_drift.add(entry["path"])
        row = drift_rows[entry["path"]]
        assert row["classification"] in {
            "base_owned_supersession_after_packet_freeze",
            "integration_reconciliation_protocol_update",
        }
        assert row["producer_size_bytes"] == entry["size_bytes"]
        assert row["producer_sha256"] == entry["sha256"]
        assert row["integration_size_bytes"] == len(content)
        assert row["integration_sha256"] == live_sha256
    assert observed_drift == set(drift_rows)
    assert reconciliation["reconciliation"]["reconciled_change_count"] == len(observed_drift)
    assert reconciliation["reconciliation"]["base_owned_supersession_count"] == 6
    assert reconciliation["reconciliation"]["integration_protocol_update_count"] == 2
    assert reconciliation["reconciliation"]["unaccounted_drift_count"] == 0
    assert reconciliation["wire_contract_freeze"]["contract_count"] == 12
    assert reconciliation["wire_contract_freeze"]["all_exactly_unchanged"] is True
    validation = reconciliation["post_integration_validation"]
    assert validation["classification"] == (
        "hermetic_ci_governed_asset_partition_no_release_authority"
    )
    validation_rows = {row["path"]: row for row in validation["paths"]}
    assert set(validation_rows) == {
        ".github/workflows/ci.yml",
        "pyproject.toml",
        "tests/conftest.py",
        "tests/test_ci_test_partition.py",
        "tools/build_maskfactory_bridge_integration_reconciliation_manifest.py",
    }
    assert validation["path_count"] == len(validation_rows)
    for relative_path, row in validation_rows.items():
        content = (ROOT / relative_path).read_bytes()
        assert row["size_bytes"] == len(content)
        assert row["sha256"] == hashlib.sha256(content).hexdigest()


def test_latest_decision_supersedes_historical_human_and_scale_core_gates() -> None:
    decisions = (ROOT / "Plan" / "DECISIONS_LOG.md").read_text(encoding="utf-8")
    latest_heading = (
        "## 2026-07-17 — Separate autonomous core completion from human research and scale claims"
    )
    assert decisions.rfind("\n## ") == decisions.rfind(f"\n{latest_heading}")
    latest = decisions[decisions.rfind(latest_heading) :]
    normalized = " ".join(latest.split())
    assert "`core_autonomous_runtime` as the sole required finish line" in normalized
    assert "`operationally_certified_artifact` cannot be counted as or relabeled" in normalized
    assert "Earlier conflicting log/horizon text is historical evidence" in normalized
    assert "without letting it silently block or revoke the autonomous core" in normalized
