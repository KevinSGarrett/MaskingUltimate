from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent))
from maskfactory.cli import main  # noqa: E402
from maskfactory.daz.acceptance_certificate import (  # noqa: E402
    AcceptanceCertificateError,
    build_acceptance_certificate,
    load_acceptance_certificate_policy,
    publish_acceptance_certificate,
    validate_acceptance_certificate_policy,
    verify_acceptance_certificate,
)
from maskfactory.daz.passes import load_render_pass_policy  # noqa: E402
from maskfactory.daz.render import (  # noqa: E402
    derive_scene_packages,
    evaluate_same_state_replay,
    load_same_state_replay_policy,
)
from maskfactory.daz.repair_retry import (  # noqa: E402
    append_repair_decision,
    build_repair_request,
    load_repair_retry_policy,
)
from maskfactory.daz.validation_registry import (  # noqa: E402
    build_validation_set_report,
    load_validation_registry,
)
from test_daz_package_derivation import _contracts as _package_contracts  # noqa: E402
from test_daz_package_derivation import _fixture as _package_fixture  # noqa: E402
from test_daz_same_state_replay import _execution as _replay_execution  # noqa: E402
from test_daz_same_state_replay import _paths as _replay_paths  # noqa: E402
from test_daz_same_state_replay import _run as _replay_run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "daz" / "acceptance_certificate_policy.yaml"
REPAIR_POLICY_PATH = ROOT / "configs" / "daz" / "repair_retry_policy.yaml"
REGISTRY_PATH = ROOT / "configs" / "daz" / "validation_registry.yaml"
REPLAY_POLICY_PATH = ROOT / "configs" / "daz" / "same_state_replay.yaml"
PASS_POLICY_PATH = ROOT / "configs" / "daz" / "render_pass_profiles.yaml"


def _sha(document) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _policy() -> dict:
    return load_acceptance_certificate_policy(POLICY_PATH)


def _repair_policy() -> dict:
    return load_repair_retry_policy(REPAIR_POLICY_PATH)


def _registry() -> dict:
    return load_validation_registry(REGISTRY_PATH)


def _validation(scene_id: str, *, failing: tuple[str, str, str] | None = None) -> dict:
    results = []
    for index in range(9):
        validator_id = f"DAZ-V{index}-001"
        validator = _registry()["validators"][index]
        if failing is not None and validator_id == failing[0]:
            status, reason, retryability = "fail", failing[1], failing[2]
        else:
            status = "pass"
            reason = validator["reason_codes"]["pass"][0]
            retryability = "none"
        results.append(
            {
                "validator_id": validator_id,
                "validator_version": "1.0.0",
                "entity_id": scene_id,
                "status": status,
                "reason_code": reason,
                "metric": "defect_count",
                "observed": {"defect_count": 0 if status == "pass" else 1},
                "expected": {"operator": "eq", "value": 0},
                "evidence_paths": [f"fixtures/{validator_id}.json"],
                "retryability": retryability,
                "affected_asset_ids": [],
                "affected_mapping_ids": [],
            }
        )
    return build_validation_set_report(
        results,
        entity_id=scene_id,
        scope="scene",
        registry=_registry(),
        required_validator_ids=[f"DAZ-V{index}-001" for index in range(9)],
    )


def _artifacts(tmp_path: Path):
    package_policy, contract, _arrays, source_paths, protected_paths = _package_fixture(
        tmp_path / "package"
    )
    package_report, _root, _published = derive_scene_packages(
        contract,
        source_paths=source_paths,
        protected_paths=protected_paths,
        output_root=tmp_path / "package_exports",
        policy=package_policy,
    )
    _state, plan, _instance, _part, _materials = _package_contracts()
    assert plan["plan_id"] == contract["plan_id"]
    original_paths = _replay_paths(tmp_path / "replay" / "original", plan)
    replay_paths = _replay_paths(tmp_path / "replay" / "replayed", plan)
    replay_report = evaluate_same_state_replay(
        plan,
        _replay_execution(plan, original_paths),
        _replay_execution(plan, replay_paths),
        _replay_run("acceptance_original", 301),
        _replay_run("acceptance_replay", 302),
        original_paths=original_paths,
        replay_paths=replay_paths,
        pass_policy=load_render_pass_policy(PASS_POLICY_PATH),
        policy=load_same_state_replay_policy(REPLAY_POLICY_PATH),
    )
    assert replay_report["scene_id"] == contract["scene_id"]
    validation = _validation(contract["scene_id"])
    source = _policy()["source_lineage_declaration"]
    package_rows = [
        {
            "package_id": row["package_id"],
            "package_tree_sha256": row["package_tree_sha256"],
            "file_hashes": row["file_hashes"],
        }
        for row in package_report["packages"]
    ]
    draft = {
        "schema_version": "1.0.0",
        "issued_at": "2026-07-17T01:00:00Z",
        "worker_identity": "maskfactory-worker-fixture",
        "use_profile": "private_personal_noncommercial",
        "scene_id": contract["scene_id"],
        "bindings": {
            "scene_sha256": contract["scene_state_sha256"],
            "package_sha256": _sha(package_rows),
            "recipe_sha256": "1" * 64,
            "registry_sha256": _sha(_registry()),
            "runtime_sha256": "3" * 64,
            "mapping_set_sha256": "4" * 64,
            "label_table_sha256": "5" * 64,
            "training_weight_sha256": "6" * 64,
            "source_lineage_sha256": _sha(source),
        },
        "authority": {
            "provider_id": "daz_exact_geometry",
            "authority_tier": "synthetic_exact",
            "ontology_version": contract["ontology_version"],
            "ontology_sha256": contract["ontology_snapshot_sha256"],
            "owner": "maskfactory",
            "package_revision": contract["contract_id"],
            "certificate_scope": "scene_and_packages",
            "transform_chain_sha256": "7" * 64,
        },
        "source_lineage_declaration": deepcopy(source),
        "train_eligible_requested": True,
    }
    return draft, validation, replay_report, contract, package_report


def _build(tmp_path: Path, *, history=None, post_reports=None):
    draft, validation, replay, contract, package = _artifacts(tmp_path)
    certificate = build_acceptance_certificate(
        draft,
        validation,
        replay,
        contract,
        package,
        repair_history=history,
        post_repair_reports=post_reports or {},
        policy=_policy(),
        repair_policy=_repair_policy(),
        registry=_registry(),
    )
    return certificate, (draft, validation, replay, contract, package)


def test_positive_certificate_promotes_only_after_exact_scoped_proof(tmp_path: Path) -> None:
    certificate, artifacts = _build(tmp_path)
    assert certificate["accepted"] is True and certificate["train_eligible"] is True
    assert certificate["package"]["input_truth_tier"] == "weighted_pseudo_label"
    assert certificate["package"]["certified_truth_tier"] == "synthetic_exact"
    assert certificate["authority"]["owner"] == "maskfactory"
    summary = verify_acceptance_certificate(
        certificate,
        artifacts[1],
        artifacts[2],
        artifacts[3],
        artifacts[4],
        repair_history=None,
        post_repair_reports={},
        policy=_policy(),
        repair_policy=_repair_policy(),
        registry=_registry(),
    )
    assert summary["authority_tier"] == "synthetic_exact"


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda p: p["required_scene_validator_ids"].pop(), "validators"),
        (lambda p: p.__setitem__("warnings_satisfy_acceptance", True), "authority"),
        (
            lambda p: p["package"].__setitem__("certified_output_truth_tier", "human_gold"),
            "package",
        ),
        (
            lambda p: p["repair"].__setitem__("authority_freeze_must_match_certificate", False),
            "repair",
        ),
        (
            lambda p: p["train_eligibility"].__setitem__(
                "machine_draft_or_mode_b_forbidden", False
            ),
            "train",
        ),
        (
            lambda p: p["source_lineage_declaration"].__setitem__("live_mode_b_result", True),
            "source",
        ),
    ],
)
def test_policy_cannot_weaken_acceptance_authority(mutation, reason: str) -> None:
    policy = _policy()
    mutation(policy)
    with pytest.raises(AcceptanceCertificateError, match=f"acceptance_policy_{reason}_invalid"):
        validate_acceptance_certificate_policy(policy)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("use_profile", "commercial", "use_profile"),
        ("train_eligible_requested", False, "train_eligibility"),
        ("issued_at", "2026-07-17T01:00:00+00:00", "timestamp"),
    ],
)
def test_draft_profile_train_and_timestamp_are_closed(
    tmp_path: Path, field: str, value, reason: str
) -> None:
    draft, validation, replay, contract, package = _artifacts(tmp_path)
    draft[field] = value
    with pytest.raises(AcceptanceCertificateError, match=f"acceptance_{reason}"):
        build_acceptance_certificate(
            draft,
            validation,
            replay,
            contract,
            package,
            repair_history=None,
            post_repair_reports={},
            policy=_policy(),
            repair_policy=_repair_policy(),
            registry=_registry(),
        )


def test_mode_b_or_foreign_owner_cannot_be_certified(tmp_path: Path) -> None:
    draft, validation, replay, contract, package = _artifacts(tmp_path)
    draft["source_lineage_declaration"]["live_mode_b_result"] = True
    with pytest.raises(AcceptanceCertificateError, match="source_lineage_invalid"):
        build_acceptance_certificate(
            draft,
            validation,
            replay,
            contract,
            package,
            repair_history=None,
            post_repair_reports={},
            policy=_policy(),
            repair_policy=_repair_policy(),
            registry=_registry(),
        )
    draft, validation, replay, contract, package = _artifacts(tmp_path / "owner")
    draft["authority"]["owner"] = "bundle_selector"
    with pytest.raises(AcceptanceCertificateError, match="authority_invalid"):
        build_acceptance_certificate(
            draft,
            validation,
            replay,
            contract,
            package,
            repair_history=None,
            post_repair_reports={},
            policy=_policy(),
            repair_policy=_repair_policy(),
            registry=_registry(),
        )


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda draft: draft["bindings"].__setitem__("scene_sha256", "8" * 64),
            "package_binding_invalid",
        ),
        (
            lambda draft: draft["bindings"].__setitem__("registry_sha256", "8" * 64),
            "package_binding_invalid",
        ),
        (
            lambda draft: draft["authority"].__setitem__("ontology_sha256", "8" * 64),
            "package_authority_invalid",
        ),
        (
            lambda draft: draft["authority"].__setitem__("package_revision", "stale-r0"),
            "package_authority_invalid",
        ),
    ],
)
def test_scene_registry_ontology_and_package_revision_are_cross_bound(
    tmp_path: Path, mutate, reason: str
) -> None:
    draft, validation, replay, contract, package = _artifacts(tmp_path)
    mutate(draft)
    with pytest.raises(AcceptanceCertificateError, match=reason):
        build_acceptance_certificate(
            draft,
            validation,
            replay,
            contract,
            package,
            repair_history=None,
            post_repair_reports={},
            policy=_policy(),
            repair_policy=_repair_policy(),
            registry=_registry(),
        )


def test_failed_v0_v8_set_cannot_be_certified(tmp_path: Path) -> None:
    draft, _validation_report, replay, contract, package = _artifacts(tmp_path)
    failed = _validation(
        draft["scene_id"], failing=("DAZ-V6-001", "ID_UNKNOWN_VALUE", "asset_retest")
    )
    with pytest.raises(AcceptanceCertificateError, match="validation_set_invalid"):
        build_acceptance_certificate(
            draft,
            failed,
            replay,
            contract,
            package,
            repair_history=None,
            post_repair_reports={},
            policy=_policy(),
            repair_policy=_repair_policy(),
            registry=_registry(),
        )


def test_package_truth_contract_cannot_claim_prior_certification(tmp_path: Path) -> None:
    draft, validation, replay, contract, package = _artifacts(tmp_path)
    tampered = deepcopy(contract)
    tampered["truth_contract"]["counts_as_autonomous_certified_gold"] = True
    content = {
        k: v
        for k, v in tampered.items()
        if k not in {"schema_version", "contract_id", "contract_sha256"}
    }
    tampered["contract_sha256"] = _sha(content)
    tampered["contract_id"] = f"dpdc_{tampered['contract_sha256'][:24]}"
    with pytest.raises(AcceptanceCertificateError, match="package_report_invalid"):
        build_acceptance_certificate(
            draft,
            validation,
            replay,
            tampered,
            package,
            repair_history=None,
            post_repair_reports={},
            policy=_policy(),
            repair_policy=_repair_policy(),
            registry=_registry(),
        )


def test_certificate_replay_detects_stale_or_rebound_content(tmp_path: Path) -> None:
    certificate, artifacts = _build(tmp_path)
    tampered = deepcopy(certificate)
    tampered["worker_identity"] = "different-worker"
    with pytest.raises(AcceptanceCertificateError, match="replay_mismatch"):
        verify_acceptance_certificate(
            tampered,
            artifacts[1],
            artifacts[2],
            artifacts[3],
            artifacts[4],
            repair_history=None,
            post_repair_reports={},
            policy=_policy(),
            repair_policy=_repair_policy(),
            registry=_registry(),
        )


def test_publication_is_immutable_and_idempotent(tmp_path: Path) -> None:
    certificate, _artifacts_tuple = _build(tmp_path / "inputs")
    first, published = publish_acceptance_certificate(certificate, tmp_path / "certificates")
    replay, replay_published = publish_acceptance_certificate(
        certificate, tmp_path / "certificates"
    )
    assert first == replay and published is True and replay_published is False


def test_cli_builds_replays_and_publishes_certificate(tmp_path: Path) -> None:
    draft, validation, replay, contract, package = _artifacts(tmp_path / "inputs")
    inputs = {
        "draft": draft,
        "validation": validation,
        "replay": replay,
        "contract": contract,
        "package": package,
    }
    paths = {}
    for name, document in inputs.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[name] = path
    output = tmp_path / "certificates"
    arguments = [
        "daz",
        "recipes",
        "certify-acceptance",
        "--draft",
        str(paths["draft"]),
        "--validation-set",
        str(paths["validation"]),
        "--semantic-replay",
        str(paths["replay"]),
        "--package-contract",
        str(paths["contract"]),
        "--package-report",
        str(paths["package"]),
        "--policy",
        str(POLICY_PATH),
        "--repair-policy",
        str(REPAIR_POLICY_PATH),
        "--registry",
        str(REGISTRY_PATH),
        "--output",
        str(output),
    ]
    first = CliRunner().invoke(main, arguments)
    assert first.exit_code == 0, first.output
    payload = json.loads(first.output)
    assert payload["reason"] == "daz_acceptance_certified"
    assert payload["data"]["replay"]["accepted"] is True
    assert Path(payload["data"]["publication"]["path"]).is_file()
    second = CliRunner().invoke(main, arguments)
    assert second.exit_code == 0, second.output
    assert json.loads(second.output)["data"]["publication"]["published"] is False
    draft["authority"]["owner"] = "bundle_selector"
    paths["draft"].write_text(json.dumps(draft), encoding="utf-8")
    rejected = CliRunner().invoke(main, arguments)
    assert rejected.exit_code == 91
    assert json.loads(rejected.output)["reason"] == "acceptance_authority_invalid"


def test_scheduled_repair_requires_matching_final_full_revalidation(tmp_path: Path) -> None:
    draft, final_validation, replay, contract, package = _artifacts(tmp_path)
    failure = _validation(
        draft["scene_id"], failing=("DAZ-V5-001", "RENDER_PROCESS_FAILED", "same_recipe")
    )
    repair_draft = {
        "schema_version": "1.0.0",
        "demand_id": "demand_acceptance_fixture",
        "entity_id": draft["scene_id"],
        "parent_recipe_sha256": draft["bindings"]["recipe_sha256"],
        "parent_recipe_revision": 0,
        "validator_id": "DAZ-V5-001",
        "defect_code": "CLEAN_WORKER_RERENDER",
        "proposed_delta": {"worker_restart_nonce": "acceptance-clean-restart"},
        "authority_freeze": {
            "ontology_sha256": draft["authority"]["ontology_sha256"],
            "mapping_set_sha256": draft["bindings"]["mapping_set_sha256"],
            "label_table_sha256": draft["bindings"]["label_table_sha256"],
            "truth_tier": draft["authority"]["authority_tier"],
            "training_weight_sha256": draft["bindings"]["training_weight_sha256"],
            "required_validator_set_sha256": _sha(_policy()["required_scene_validator_ids"]),
        },
    }
    request = build_repair_request(
        repair_draft, failure, policy=_repair_policy(), registry=_registry()
    )
    history = append_repair_decision(
        request, failure, None, policy=_repair_policy(), registry=_registry()
    )
    revision_id = history["entries"][0]["next_recipe_revision_id"]
    with pytest.raises(AcceptanceCertificateError, match="repair_report_set_invalid"):
        build_acceptance_certificate(
            draft,
            final_validation,
            replay,
            contract,
            package,
            repair_history=history,
            post_repair_reports={},
            policy=_policy(),
            repair_policy=_repair_policy(),
            registry=_registry(),
        )
    certificate = build_acceptance_certificate(
        draft,
        final_validation,
        replay,
        contract,
        package,
        repair_history=history,
        post_repair_reports={revision_id: final_validation},
        policy=_policy(),
        repair_policy=_repair_policy(),
        registry=_registry(),
    )
    assert certificate["repair"]["scheduled_count"] == 1
    assert certificate["repair"]["post_repair_validations"] == [
        {
            "recipe_revision_id": revision_id,
            "report_id": final_validation["report_id"],
            "report_sha256": final_validation["report_sha256"],
        }
    ]
