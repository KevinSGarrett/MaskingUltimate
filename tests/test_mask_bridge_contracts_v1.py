from __future__ import annotations

import ast
import copy
import hashlib
import io
import json
import runpy
import stat
import warnings
import zipfile
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import maskfactory.validation as validation
from maskfactory.validation import (
    ADOPTION_COMPATIBILITY_CHECKS,
    ADOPTION_REVALIDATION_TRIGGERS,
    BRIDGE_SCHEMA_NAMES,
    INVALIDATION_REASON_POLICY,
    OPERATIONAL_QA_GATES,
    canonical_document_sha256,
    canonical_json_bytes,
    schema_validator,
    validate_bridge_event_chain,
    validate_bridge_exchange,
    validate_canonical_json_golden_vectors,
    validate_document,
    validate_idempotency_records,
    validate_mask_acquisition_receipt,
    validate_mask_acquisition_request,
    validate_mask_authority_invalidation_event,
    validate_mask_bridge_error,
    validate_mask_bridge_semantic_profile,
    validate_mask_repair_feedback,
    validate_maskfactory_adoption_receipt,
    validate_maskfactory_capability_snapshot,
    validate_maskfactory_consumer_requirements,
    validate_maskfactory_qualification_bundle,
    validate_maskfactory_release_bundle,
    validate_maskfactory_release_snapshot,
    validate_operational_autonomy_certificate,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/mask_bridge_contracts"
SCHEMAS = ROOT / "src/maskfactory/schemas"
COMPLETION = ROOT / "qa/governance/completion"
BRIDGE_GOVERNANCE = ROOT / "qa/governance/bridge"
BUILDER = runpy.run_path(str(FIXTURES / "build_contract_fixtures.py"))
TRUSTED_KEYS = BUILDER["TRUSTED_KEYS"]


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _bridge_set() -> dict:
    return _json(FIXTURES / "positive_contract_set_v1.json")


def _profiles() -> list[dict]:
    return [
        _json(COMPLETION / f"{name}_v1.json")
        for name in ("core_autonomous_runtime", "independent_real_accuracy", "scale_daz_maturity")
    ]


def _fixture_exchange() -> tuple[dict, dict, dict]:
    return (
        _json(FIXTURES / "positive_mode_b_predict_request_v1.json"),
        _json(FIXTURES / "positive_certified_mode_b_receipt_v1.json"),
        _json(FIXTURES / "positive_operational_autonomy_certificate_v1.json"),
    )


def _sign(document: dict, field: str, role: str) -> None:
    BUILDER["sign"](document, field, role, (field, "signature"))


def _production_keys() -> dict:
    keys = copy.deepcopy(TRUSTED_KEYS)
    for record in keys.values():
        record["usage_scope"] = "production"
    return keys


def _pretty_bytes(document: dict) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _execution(execution_id: str) -> dict:
    return {
        "execution_id": execution_id,
        "command_sha256": hashlib.sha256(f"command:{execution_id}".encode()).hexdigest(),
        "started_at": "2026-07-17T00:00:02Z",
        "completed_at": "2026-07-17T00:00:03Z",
        "exit_code": 0,
        "status": "pass",
        "stdout_sha256": hashlib.sha256(f"stdout:{execution_id}".encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
    }


def _build_qualification(
    evidence_root: Path,
    release: dict,
    capability: dict,
    requirements: dict,
    profiles: list[dict],
) -> dict:
    evidence_root.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_root / "qualification" / "evidence.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_raw = b'{"result":"pass"}\n'
    evidence_path.write_bytes(evidence_raw)
    catalog = [
        {
            "evidence_id": "evidence-all-checks",
            "relative_path": "qualification/evidence.json",
            "sha256": hashlib.sha256(evidence_raw).hexdigest(),
            "size_bytes": len(evidence_raw),
            "media_type": "application/json",
        }
    ]
    checks = []
    for check_id in sorted(ADOPTION_COMPATIBILITY_CHECKS):
        row = {
            "check": check_id,
            "result": "pass",
            "test_ids": [f"test:{check_id}"],
            "execution": _execution(f"exec:{check_id}"),
            "evidence_ids": ["evidence-all-checks"],
            "result_sha256": "0" * 64,
        }
        row["result_sha256"] = canonical_document_sha256(
            row, excluded_top_level_fields=("result_sha256",)
        )
        checks.append(row)
    semantic = release["semantic_invariant_profile"]
    bundle = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_qualification_bundle",
        "qualification_id": "mfqual_0123456789abcdef01234567",
        "executed_at": "2026-07-17T00:00:04Z",
        "evidence_context": "runtime_evidence",
        "fixture_only": False,
        "consumer": {
            "project": "Comfy_UI_Main",
            "controller_version": "1.0.0",
            "git_commit": "1" * 40,
        },
        "canonicalization": {
            "algorithm": "maskfactory-canonical-json-v1",
            "excluded_top_level_fields": ["qualification_payload_sha256", "signature"],
        },
        "authentication": BUILDER["authentication"](
            "consumer_qualification",
            "qualification-runtime-nonce-0001",
            "2026-07-17T00:00:00Z",
            "2026-07-17T00:05:00Z",
        ),
        "trust_binding": BUILDER["trust_binding"]("consumer_qualification"),
        "release_binding": {
            "release_id": release["release_id"],
            "release_payload_sha256": release["release_payload_sha256"],
            "capability_snapshot_id": capability["snapshot_id"],
            "capability_snapshot_sha256": capability["snapshot_sha256"],
            "adopted_wire_schema_manifest_sha256": hashlib.sha256(
                canonical_json_bytes(release["wire_schemas"])
            ).hexdigest(),
        },
        "requirements_binding": {
            "requirements_id": requirements["requirements_id"],
            "requirements_sha256": requirements["requirements_sha256"],
        },
        "semantic_profile_binding": {
            "profile_id": "maskfactory-comfyui-bridge-semantics",
            "profile_sha256": semantic["profile_sha256"],
            "verifier_sha256": hashlib.sha256(
                (ROOT / "src/maskfactory/validation.py").read_bytes()
            ).hexdigest(),
        },
        "core_completion_profile_binding": {
            "profile_id": "core_autonomous_runtime",
            "policy_sha256": next(
                row for row in profiles if row["profile_id"] == "core_autonomous_runtime"
            )["policy_sha256"],
        },
        "executor_manifest": {
            "executor_id": "qualification-runner",
            "executor_version": "1.0.0",
            "executable_sha256": hashlib.sha256(b"runner").hexdigest(),
            "command_manifest_sha256": hashlib.sha256(b"commands").hexdigest(),
            "test_registry_sha256": hashlib.sha256(b"tests").hexdigest(),
        },
        "environment_manifest": {
            "environment_id": "qualification-env",
            "os_sha256": hashlib.sha256(b"os").hexdigest(),
            "python_sha256": hashlib.sha256(b"python").hexdigest(),
            "dependency_lock_sha256": hashlib.sha256(b"lock").hexdigest(),
            "node_inventory_sha256": release["node_inventory"]["sha256"],
            "hardware_profile_sha256": hashlib.sha256(b"hardware").hexdigest(),
        },
        "compatibility_checks": checks,
        "installation_verification": _execution("install-verify"),
        "vertical_slices": [
            {
                "access_mode": mode,
                "execution": _execution(f"slice:{mode}"),
                "request_payload_sha256": hashlib.sha256(f"request:{mode}".encode()).hexdigest(),
                "receipt_payload_sha256": hashlib.sha256(f"receipt:{mode}".encode()).hexdigest(),
                "certificate_payload_sha256": (
                    None
                    if mode == "mode_a_package_read"
                    else hashlib.sha256(f"certificate:{mode}".encode()).hexdigest()
                ),
                "observed_authority_state": (
                    "qa_passed_noncertified" if mode == "mode_a_package_read" else "certified"
                ),
            }
            for mode in ("mode_a_package_read", "mode_b_live_predict", "mode_b_live_refine")
        ],
        "evidence_catalog": catalog,
        "evidence_catalog_sha256": hashlib.sha256(canonical_json_bytes(catalog)).hexdigest(),
        "all_required_checks_passed": True,
        "claim_limits": {
            "establishes_adoption_evidence_only": True,
            "operational_artifact_authority_claim": False,
            "training_gold_claim": False,
            "independent_accuracy_claim": False,
        },
        "qualification_payload_sha256": "0" * 64,
    }
    _sign(bundle, "qualification_payload_sha256", "consumer_qualification")
    return bundle


def _production_documents(tmp_path: Path) -> tuple[dict, dict, dict, dict, dict, Path, dict]:
    documents = copy.deepcopy(_bridge_set())
    profiles = _profiles()
    capability = documents["maskfactory_capability_snapshot"]
    capability.update(evidence_context="runtime_evidence", fixture_only=False)
    capability["snapshot_sha256"] = canonical_document_sha256(
        capability, excluded_top_level_fields=("snapshot_sha256",)
    )
    requirements = documents["maskfactory_consumer_requirements"]
    for key_set in requirements["trusted_signing_key_sets"]:
        for key in key_set["trusted_keys"]:
            key["usage_scope"] = "production"
    _sign(requirements, "requirements_sha256", "consumer_requirements")
    release = documents["maskfactory_release_snapshot"]
    release.update(
        release_status="published",
        evidence_context="runtime_evidence",
        fixture_only=False,
        known_limitations=[],
    )
    release["capability_snapshot"]["payload_sha256"] = capability["snapshot_sha256"]
    release["capability_snapshot"]["document_sha256"] = hashlib.sha256(
        _pretty_bytes(capability)
    ).hexdigest()
    release["artifact_security_policy"]["policy_sha256"] = canonical_document_sha256(
        release["artifact_security_policy"], excluded_top_level_fields=("policy_sha256",)
    )
    _sign(release, "release_payload_sha256", "producer_release")
    evidence_root = tmp_path / "qualification-evidence"
    qualification = _build_qualification(evidence_root, release, capability, requirements, profiles)
    adoption = documents["maskfactory_adoption_receipt"]
    adoption.update(
        adoption_scope="production_authority",
        evidence_context="runtime_evidence",
        fixture_only=False,
        production_use_authorized=True,
        decision="adopted",
        required_capabilities_satisfied=True,
        release_payload_sha256=release["release_payload_sha256"],
        capability_snapshot_sha256=capability["snapshot_sha256"],
        consumer_requirements_sha256=requirements["requirements_sha256"],
        qualification_bundle_id=qualification["qualification_id"],
        qualification_bundle_sha256=qualification["qualification_payload_sha256"],
        rejected_capabilities=[],
        accepted_capabilities=["mask.package.read", "mask.live.predict"],
    )
    stack = capability["provider_stacks"][0]
    requirement_rows = {
        row["capability_id"]: row
        for row in requirements["required_capabilities"] + requirements["optional_capabilities"]
    }
    for row in adoption["capability_decisions"]:
        row["decision"] = "accepted"
        row["reason"] = "exact promoted qualified route"
        requirement = requirement_rows[row["capability_id"]]
        row["evidence_sha256"] = canonical_document_sha256(
            {
                "requirement": requirement,
                "snapshot_id": capability["snapshot_id"],
                "snapshot_sha256": capability["snapshot_sha256"],
                "stack_id": stack["stack_id"],
                "stack_sha256": stack["stack_sha256"],
                "qualification_scope_sha256": stack["qualification_scope"]["scope_sha256"],
            }
        )
    qualified = {row["check"]: row for row in qualification["compatibility_checks"]}
    for row in adoption["compatibility_checks"]:
        row["evidence_sha256"] = qualified[row["check"]]["result_sha256"]
    adoption["pinned_artifacts"] = BUILDER["adoption_pins"](release)
    _sign(adoption, "adoption_payload_sha256", "consumer_adoption")
    return (
        release,
        capability,
        requirements,
        adoption,
        qualification,
        evidence_root,
        _production_keys(),
    )


def _zip_bytes(members: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in members:
            archive.writestr(name, raw)
    return buffer.getvalue()


def _materialize_release_root(tmp_path: Path) -> tuple[dict, Path, list[dict]]:
    release = copy.deepcopy(_bridge_set()["maskfactory_release_snapshot"])
    profiles = _profiles()
    root = tmp_path / "release-root"
    root.mkdir()

    def write(relative: str, raw: bytes) -> tuple[str, int]:
        path = root / Path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest(), len(raw)

    for row in release["wire_schemas"]:
        row["sha256"], _ = write(row["relative_path"], (ROOT / row["relative_path"]).read_bytes())
    canonical = release["canonicalization_spec"]
    canonical["sha256"], _ = write(
        canonical["relative_path"], (ROOT / canonical["relative_path"]).read_bytes()
    )
    canonical["golden_vectors_sha256"], _ = write(
        canonical["golden_vectors_relative_path"],
        (ROOT / canonical["golden_vectors_relative_path"]).read_bytes(),
    )
    semantic = release["semantic_invariant_profile"]
    raw = (ROOT / semantic["relative_path"]).read_bytes()
    semantic["document_sha256"], _ = write(semantic["relative_path"], raw)
    semantic["profile_sha256"] = _json(ROOT / semantic["relative_path"])["profile_sha256"]
    capability = _bridge_set()["maskfactory_capability_snapshot"]
    raw = _pretty_bytes(capability)
    release["capability_snapshot"]["payload_sha256"] = capability["snapshot_sha256"]
    release["capability_snapshot"]["document_sha256"], _ = write(
        release["capability_snapshot"]["relative_path"], raw
    )
    for row, profile in zip(release["completion_profiles"], profiles, strict=True):
        raw = (ROOT / row["relative_path"]).read_bytes()
        row["document_sha256"], _ = write(row["relative_path"], raw)
        row["policy_sha256"] = profile["policy_sha256"]
    for field in ("workflow_inventory", "node_inventory", "evidence_index"):
        row = release[field]
        row["sha256"], _ = write(
            row["relative_path"], _pretty_bytes({"id": row.get("inventory_id"), "records": []})
        )
    artifact_bytes = {
        "python_wheel": _zip_bytes([("maskfactory/__init__.py", b"")]),
        "comfyui_node_pack": _zip_bytes([("nodes.py", b"NODE_CLASS_MAPPINGS = {}\n")]),
        "schema_bundle": _zip_bytes([("schema.json", b"{}\n")]),
        "openapi_document": b'{"openapi":"3.1.0"}\n',
        "compatibility_manifest": b'{"bridge":"1.0"}\n',
        "certificate_index": b'{"certificates":[]}\n',
    }
    for row in release["artifacts"]:
        row["sha256"], row["size_bytes"] = write(row["relative_path"], artifact_bytes[row["kind"]])
    by_kind = {row["kind"]: row for row in release["artifacts"]}
    release["openapi"].update(
        relative_path=by_kind["openapi_document"]["relative_path"],
        sha256=by_kind["openapi_document"]["sha256"],
    )
    release["certificate_index"].update(
        relative_path=by_kind["certificate_index"]["relative_path"],
        sha256=by_kind["certificate_index"]["sha256"],
    )

    catalog: list[dict] = []
    paths = [(row["relative_path"], row["sha256"]) for row in release["wire_schemas"]]
    paths += [
        (canonical["relative_path"], canonical["sha256"]),
        (canonical["golden_vectors_relative_path"], canonical["golden_vectors_sha256"]),
    ]
    paths += [
        (semantic["relative_path"], semantic["document_sha256"]),
        (
            release["capability_snapshot"]["relative_path"],
            release["capability_snapshot"]["document_sha256"],
        ),
    ]
    paths += [
        (row["relative_path"], row["document_sha256"]) for row in release["completion_profiles"]
    ]
    paths += [
        (release[field]["relative_path"], release[field]["sha256"])
        for field in ("workflow_inventory", "node_inventory", "evidence_index")
    ]
    paths += [(row["relative_path"], row["sha256"]) for row in release["artifacts"]]
    for relative, digest in paths:
        catalog.append(
            {
                "relative_path": relative,
                "sha256": digest,
                "size_bytes": (root / relative).stat().st_size,
            }
        )
    manifest = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_allowed_root_manifest",
        "files": catalog,
    }
    manifest_raw = _pretty_bytes(manifest)
    policy = release["artifact_security_policy"]
    policy["allowed_root_manifest_sha256"], _ = write(
        policy["allowed_root_manifest_relative_path"], manifest_raw
    )
    policy["policy_sha256"] = canonical_document_sha256(
        policy, excluded_top_level_fields=("policy_sha256",)
    )
    _sign(release, "release_payload_sha256", "producer_release")
    return release, root, profiles


def _validators(issues) -> set[str]:
    return {issue.validator for issue in issues}


def test_schema_registry_meta_schema_strictness_and_no_duplicate_functions() -> None:
    assert len(BRIDGE_SCHEMA_NAMES) == 12
    for name in (*BRIDGE_SCHEMA_NAMES, "completion_profile", "maskfactory_qualification_bundle"):
        schema = _json(SCHEMAS / f"{name}.schema.json")
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False
        assert schema_validator(name).schema["$id"].endswith(f"/{name}.schema.json")
    tree = ast.parse((ROOT / "src/maskfactory/validation.py").read_text(encoding="utf-8"))
    names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert len(names) == len(set(names))


def test_all_positive_documents_are_structurally_and_semantically_clean() -> None:
    documents = _bridge_set()
    assert set(documents) == set(BRIDGE_SCHEMA_NAMES) - {
        "operational_autonomy_certificate",
        "mask_bridge_semantic_invariant_profile",
    }
    for name, document in documents.items():
        assert validate_document(document, name) == (), name
    request, receipt, certificate = _fixture_exchange()
    assert validate_mask_acquisition_request(request, trusted_signing_keys=TRUSTED_KEYS) == ()
    assert validate_mask_acquisition_receipt(receipt, trusted_signing_keys=TRUSTED_KEYS) == ()
    assert (
        validate_operational_autonomy_certificate(certificate, trusted_signing_keys=TRUSTED_KEYS)
        == ()
    )
    assert (
        validate_bridge_exchange(
            request,
            receipt,
            certificate,
            trusted_signing_keys=TRUSTED_KEYS,
            production_required=False,
        )
        == ()
    )
    assert (
        validate_maskfactory_capability_snapshot(
            documents["maskfactory_capability_snapshot"], at_time="2026-07-17T00:00:01Z"
        )
        == ()
    )
    assert (
        validate_maskfactory_consumer_requirements(
            documents["maskfactory_consumer_requirements"], trusted_signing_keys=TRUSTED_KEYS
        )
        == ()
    )
    assert (
        validate_maskfactory_release_snapshot(
            documents["maskfactory_release_snapshot"],
            completion_profiles=_profiles(),
            trusted_signing_keys=TRUSTED_KEYS,
            at_time="2026-07-17T00:00:01Z",
        )
        == ()
    )
    assert (
        validate_maskfactory_adoption_receipt(
            documents["maskfactory_adoption_receipt"],
            trusted_signing_keys=TRUSTED_KEYS,
            release_snapshot=documents["maskfactory_release_snapshot"],
            consumer_requirements=documents["maskfactory_consumer_requirements"],
            capability_snapshot=documents["maskfactory_capability_snapshot"],
            completion_profiles=_profiles(),
        )
        == ()
    )
    assert (
        validate_mask_authority_invalidation_event(
            documents["mask_authority_invalidation_event"], trusted_signing_keys=TRUSTED_KEYS
        )
        == ()
    )
    assert validate_mask_bridge_error(documents["mask_bridge_error"]) == ()
    assert (
        validate_bridge_event_chain(
            [documents["mask_bridge_event"]], trusted_signing_keys=TRUSTED_KEYS
        )
        == ()
    )


def test_canonical_vectors_completion_profiles_and_semantic_index() -> None:
    vectors = _json(BRIDGE_GOVERNANCE / "maskfactory_canonical_json_golden_vectors_v1.json")
    assert validate_canonical_json_golden_vectors(vectors) == ()
    for profile in _profiles():
        assert validate_document(profile, "completion_profile") == ()
        assert profile["policy_sha256"] == canonical_document_sha256(
            profile, excluded_top_level_fields=("policy_sha256",)
        )
    core = _profiles()[0]
    assert core["required_for_core_runtime"] is True
    assert set(core["dependency_policy"].values()) == {"not_required"}
    assert "verified remote not-found" in json.dumps(core["required_gates"])
    semantic = _json(BRIDGE_GOVERNANCE / "mask_bridge_semantic_invariants_v1.json")
    assert validate_mask_bridge_semantic_profile(semantic, fixture_root=FIXTURES) == ()


def test_trust_anchor_role_revocation_and_self_signed_substitution_fail_closed() -> None:
    request, _, _ = _fixture_exchange()
    assert "missing_trust_anchor" in _validators(validate_mask_acquisition_request(request))
    revoked = copy.deepcopy(TRUSTED_KEYS)
    revoked[request["signature"]["key_id"]]["status"] = "revoked"
    assert "trusted_key_status" in _validators(
        validate_mask_acquisition_request(request, trusted_signing_keys=revoked)
    )
    wrong_role = copy.deepcopy(TRUSTED_KEYS)
    wrong_role[request["signature"]["key_id"]]["roles"] = ["consumer_feedback"]
    assert "trusted_key_role" in _validators(
        validate_mask_acquisition_request(request, trusted_signing_keys=wrong_role)
    )
    substituted = copy.deepcopy(request)
    substituted["signature"]["key_id"] = "comfy-main-request-attacker"
    assert "missing_trust_anchor" in _validators(
        validate_mask_acquisition_request(substituted, trusted_signing_keys=TRUSTED_KEYS)
    )


def test_request_ownership_transform_and_video_frame_identity_fail_closed() -> None:
    request, _, _ = _fixture_exchange()
    tampered = copy.deepcopy(request)
    tampered["protected_regions"][0]["owner"]["scene_instance_id"] = "unregistered"
    _sign(tampered, "request_payload_sha256", "consumer_request")
    assert "protected_owner_authorized" in _validators(
        validate_mask_acquisition_request(tampered, trusted_signing_keys=TRUSTED_KEYS)
    )
    tampered = copy.deepcopy(request)
    tampered["transform_chain"]["steps"][0]["sequence"] = 2
    _sign(tampered, "request_payload_sha256", "consumer_request")
    assert "transform_sequence" in _validators(
        validate_mask_acquisition_request(tampered, trusted_signing_keys=TRUSTED_KEYS)
    )
    video = copy.deepcopy(request)
    video["media_scope"].update(
        scope_kind="video_frame",
        source_video_sha256="9" * 64,
        decoded_frame_sha256=video["source"]["decoded_pixel_sha256"],
        frame_index=10,
        pts=1000,
        timebase_numerator=1,
        timebase_denominator=1000,
        timestamp_ns=1_000_000_000,
    )
    video["source"]["frame_extraction"] = {
        "source_video_sha256": "9" * 64,
        "frame_index": 10,
        "pts": 1000,
        "timebase_numerator": 1,
        "timebase_denominator": 1000,
        "extractor_sha256": hashlib.sha256(b"extractor").hexdigest(),
    }
    _sign(video, "request_payload_sha256", "consumer_request")
    assert validate_mask_acquisition_request(video, trusted_signing_keys=TRUSTED_KEYS) == ()
    video["source"]["frame_extraction"]["frame_index"] = 11
    _sign(video, "request_payload_sha256", "consumer_request")
    assert "source_media_binding" in _validators(
        validate_mask_acquisition_request(video, trusted_signing_keys=TRUSTED_KEYS)
    )


def test_receipt_authority_parent_ceiling_qa_and_execution_honesty() -> None:
    _, receipt, _ = _fixture_exchange()
    tampered = copy.deepcopy(receipt)
    tampered["lineage"]["operation_kind"] = "refinement"
    tampered["access_mode"] = "mode_b_live_refine"
    tampered["lineage"]["parents"] = [
        {
            "artifact_sha256": "8" * 64,
            "authority_state": "draft",
            "truth_tier": "machine_candidate",
            "certificate_kind": "none",
            "certificate_id": None,
            "certificate_sha256": None,
            "certificate_status": "none",
            "certificate_exact_scope_match": False,
        }
    ]
    _sign(tampered, "receipt_payload_sha256", "producer_receipt")
    assert {
        "derived_authority_not_above_parent",
        "certified_refine_requires_certified_parents",
    }.issubset(
        _validators(validate_mask_acquisition_receipt(tampered, trusted_signing_keys=TRUSTED_KEYS))
    )
    tampered = copy.deepcopy(receipt)
    tampered["qa"]["blocking_failures"] = ["boundary"]
    _sign(tampered, "receipt_payload_sha256", "producer_receipt")
    assert "qa_evidence_honesty" in _validators(
        validate_mask_acquisition_receipt(tampered, trusted_signing_keys=TRUSTED_KEYS)
    )
    tampered = copy.deepcopy(receipt)
    tampered["execution_observation"]["runtime_ms"] += 1
    _sign(tampered, "receipt_payload_sha256", "producer_receipt")
    assert "execution_duration" in _validators(
        validate_mask_acquisition_receipt(tampered, trusted_signing_keys=TRUSTED_KEYS)
    )


def test_certificate_gate_vector_claim_firewall_and_critic_identity_separation() -> None:
    _, _, certificate = _fixture_exchange()
    assert len(certificate["qa_evidence"]["gate_results"]) == len(OPERATIONAL_QA_GATES) == 19
    tampered = copy.deepcopy(certificate)
    critic = tampered["qa_evidence"]["critic_binding"]
    generator = tampered["execution_binding"]
    critic.update(
        critic_stack_id=generator["provider_stack_id"],
        critic_stack_sha256=generator["provider_stack_sha256"],
        workflow_sha256=generator["workflow_sha256"],
        execution_fingerprint_sha256=generator["execution_fingerprint_sha256"],
        model_artifacts=copy.deepcopy(generator["model_artifacts"]),
    )
    _sign(tampered, "certificate_payload_sha256", "producer_authority")
    assert "critic_identity_separation" in _validators(
        validate_operational_autonomy_certificate(tampered, trusted_signing_keys=TRUSTED_KEYS)
    )
    tampered = copy.deepcopy(certificate)
    tampered["claim_limits"]["training_gold_claim"] = True
    _sign(tampered, "certificate_payload_sha256", "producer_authority")
    assert "operational_truth_firewall" in _validators(
        validate_operational_autonomy_certificate(tampered, trusted_signing_keys=TRUSTED_KEYS)
    )


def test_fixture_certificate_cannot_escape_into_production_and_time_of_use_expires() -> None:
    request, receipt, certificate = _fixture_exchange()
    issues = validate_bridge_exchange(
        request,
        receipt,
        certificate,
        trusted_signing_keys=TRUSTED_KEYS,
        production_required=True,
        at_time="2026-07-17T00:00:05Z",
    )
    assert {
        "fixture_certificate_use_forbidden",
        "production_trust_anchor_required",
        "production_release_evidence_required",
    }.issubset(_validators(issues))
    production_cert = copy.deepcopy(certificate)
    production_cert.update(fixture_only=False, evidence_context="runtime_evidence")
    _sign(production_cert, "certificate_payload_sha256", "producer_authority")
    assert "certificate_use_time" in _validators(
        validate_operational_autonomy_certificate(
            production_cert,
            trusted_signing_keys=_production_keys(),
            production_required=True,
            at_time="2026-07-19T00:00:00Z",
        )
    )


def test_production_qualification_and_adoption_are_executed_byte_bound(tmp_path: Path) -> None:
    release, capability, requirements, adoption, qualification, evidence_root, keys = (
        _production_documents(tmp_path)
    )
    assert (
        validate_maskfactory_qualification_bundle(
            qualification,
            trusted_signing_keys=keys,
            evidence_root=evidence_root,
            release_snapshot=release,
            capability_snapshot=capability,
            consumer_requirements=requirements,
            completion_profiles=_profiles(),
        )
        == ()
    )
    assert (
        validate_maskfactory_adoption_receipt(
            adoption,
            trusted_signing_keys=keys,
            release_snapshot=release,
            consumer_requirements=requirements,
            capability_snapshot=capability,
            completion_profiles=_profiles(),
            qualification_bundle=qualification,
            qualification_evidence_root=evidence_root,
            production_required=True,
            at_time="2026-07-17T00:00:05Z",
        )
        == ()
    )
    evidence = next(evidence_root.rglob("evidence.json"))
    evidence.write_bytes(b"tampered\n")
    issues = validate_maskfactory_adoption_receipt(
        adoption,
        trusted_signing_keys=keys,
        release_snapshot=release,
        consumer_requirements=requirements,
        capability_snapshot=capability,
        completion_profiles=_profiles(),
        qualification_bundle=qualification,
        qualification_evidence_root=evidence_root,
        production_required=True,
        at_time="2026-07-17T00:00:05Z",
    )
    assert "qualification_evidence_byte_binding" in _validators(issues)


def test_fixture_adoption_replay_and_missing_production_evidence_fail_closed(
    tmp_path: Path,
) -> None:
    fixture = _bridge_set()["maskfactory_adoption_receipt"]
    assert "production_adoption_required" in _validators(
        validate_maskfactory_adoption_receipt(
            fixture,
            trusted_signing_keys=TRUSTED_KEYS,
            production_required=True,
            at_time="2026-07-17T00:00:05Z",
        )
    )
    _, _, _, adoption, _, _, keys = _production_documents(tmp_path)
    issues = validate_maskfactory_adoption_receipt(
        adoption,
        trusted_signing_keys=keys,
        production_required=True,
        at_time="2026-07-17T00:00:05Z",
    )
    assert "production_adoption_evidence_required" in _validators(issues)


def test_adoption_derives_required_capability_from_promoted_qualified_route(tmp_path: Path) -> None:
    release, capability, requirements, adoption, qualification, evidence_root, keys = (
        _production_documents(tmp_path)
    )
    broken = copy.deepcopy(capability)
    broken["provider_stacks"][0]["qualification_scope"]["labels"] = ["torso"]
    broken["snapshot_sha256"] = canonical_document_sha256(
        broken, excluded_top_level_fields=("snapshot_sha256",)
    )
    issues = validate_maskfactory_adoption_receipt(
        adoption,
        trusted_signing_keys=keys,
        release_snapshot=release,
        consumer_requirements=requirements,
        capability_snapshot=broken,
        completion_profiles=_profiles(),
        qualification_bundle=qualification,
        qualification_evidence_root=evidence_root,
        production_required=True,
        at_time="2026-07-17T00:00:05Z",
    )
    assert "accepted_capability_qualified_route" in _validators(issues)
    extra = copy.deepcopy(adoption)
    extra["capability_decisions"].append(
        {
            "capability_id": "invented.extra",
            "requirement_class": "producer_extra",
            "decision": "accepted",
            "reason": "invented",
            "evidence_sha256": "a" * 64,
        }
    )
    extra["accepted_capabilities"].append("invented.extra")
    _sign(extra, "adoption_payload_sha256", "consumer_adoption")
    assert "producer_extra_snapshot_binding" in _validators(
        validate_maskfactory_adoption_receipt(
            extra,
            trusted_signing_keys=keys,
            release_snapshot=release,
            consumer_requirements=requirements,
            capability_snapshot=capability,
            completion_profiles=_profiles(),
            qualification_bundle=qualification,
            qualification_evidence_root=evidence_root,
            at_time="2026-07-17T00:00:05Z",
        )
    )


def test_release_requires_exact_profile_documents_and_policy_self_hash(tmp_path: Path) -> None:
    release, _, _, _, _, _, keys = _production_documents(tmp_path)
    assert "completion_profile_evidence_required" in _validators(
        validate_maskfactory_release_snapshot(
            release, trusted_signing_keys=keys, at_time="2026-07-17T00:00:05Z"
        )
    )
    tampered = copy.deepcopy(release)
    tampered["artifact_security_policy"]["maximum_file_bytes"] += 1
    _sign(tampered, "release_payload_sha256", "producer_release")
    assert "artifact_security_policy_hash" in _validators(
        validate_maskfactory_release_snapshot(
            tampered,
            completion_profiles=_profiles(),
            trusted_signing_keys=keys,
            at_time="2026-07-17T00:00:05Z",
        )
    )


def test_release_bundle_is_exact_byte_closed_and_rejects_unmanifested_files(tmp_path: Path) -> None:
    release, root, profiles = _materialize_release_root(tmp_path)
    assert (
        validate_maskfactory_release_bundle(
            release, root=root, trusted_signing_keys=TRUSTED_KEYS, completion_profiles=profiles
        )
        == ()
    )
    (root / "unmanifested.txt").write_text("no", encoding="utf-8")
    assert "release_root_closed_set" in _validators(
        validate_maskfactory_release_bundle(
            release, root=root, trusted_signing_keys=TRUSTED_KEYS, completion_profiles=profiles
        )
    )


@pytest.mark.parametrize("archive_kind", ["symlink", "duplicate", "case_alias"])
def test_archive_indirection_duplicates_and_case_aliases_fail_closed(
    tmp_path: Path, archive_kind: str
) -> None:
    path = tmp_path / "bad.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(path, "w") as archive:
            if archive_kind == "symlink":
                info = zipfile.ZipInfo("link")
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, "target")
            elif archive_kind == "duplicate":
                archive.writestr("same.txt", "a")
                archive.writestr("same.txt", "b")
            else:
                archive.writestr("Node.py", "a")
                archive.writestr("node.py", "b")
    policy = _bridge_set()["maskfactory_release_snapshot"]["artifact_security_policy"]
    issues = validation._archive_security_issues(path, policy, pointer="/archive")
    expected = {
        "symlink": "archive_indirection_or_special",
        "duplicate": "archive_duplicate_member",
        "case_alias": "archive_member_case_collision",
    }[archive_kind]
    assert expected in _validators(issues)


def _invalidation_for_reason(reason: str) -> dict:
    event = copy.deepcopy(_bridge_set()["mask_authority_invalidation_event"])
    targets, actions = INVALIDATION_REASON_POLICY[reason]
    target = sorted(targets)[0]
    event["reason"] = reason
    transition = event["target_transitions"][0]
    transition.update(
        target_kind=target,
        target_id=f"target:{reason}",
        target_sha256=hashlib.sha256(reason.encode()).hexdigest(),
        previous_authority_state="certified",
        new_authority_state="draft",
        previous_certificate_status="active",
        new_certificate_status="revoked",
    )
    event["required_actions"] = [
        {
            "action_id": f"action:{index}",
            "transition_ids": [transition["transition_id"]],
            "action": action,
            "deadline_at": "2026-07-17T00:02:00Z",
            "verification_evidence_required": True,
            "verification_policy_sha256": hashlib.sha256(f"policy:{action}".encode()).hexdigest(),
        }
        for index, action in enumerate(sorted(actions))
    ]
    event["superseding_binding"] = (
        {
            "release_id": "mfr_20260718_abcdef012345",
            "release_payload_sha256": "b" * 64,
            "adoption_required": True,
        }
        if reason == "release_superseded"
        else None
    )
    _sign(event, "event_payload_sha256", "producer_journal")
    return event


def test_invalidation_taxonomy_is_lossless_actionable_and_equals_adoption_triggers() -> None:
    assert set(INVALIDATION_REASON_POLICY) == set(ADOPTION_REVALIDATION_TRIGGERS)
    assert len(INVALIDATION_REASON_POLICY) == 27
    for reason in sorted(INVALIDATION_REASON_POLICY):
        assert (
            validate_mask_authority_invalidation_event(
                _invalidation_for_reason(reason), trusted_signing_keys=TRUSTED_KEYS
            )
            == ()
        ), reason
    tampered = _invalidation_for_reason("certificate_revoked")
    tampered["required_actions"] = tampered["required_actions"][:1]
    _sign(tampered, "event_payload_sha256", "producer_journal")
    assert "invalidation_reason_action_matrix" in _validators(
        validate_mask_authority_invalidation_event(tampered, trusted_signing_keys=TRUSTED_KEYS)
    )


def _journal_event(
    event_type: str,
    sequence: int,
    producer: str,
    resource_kind: str,
    from_state: str,
    to_state: str,
    *,
    previous: dict | None = None,
    reconciliation=None,
    invalidation: dict | None = None,
) -> dict:
    base = copy.deepcopy(_bridge_set()["mask_bridge_event"])
    base.update(
        event_id=f"mfbevt_{sequence:024x}",
        sequence=sequence,
        event_type=event_type,
        producer=producer,
        occurred_at=f"2026-07-17T00:00:{sequence:02d}Z",
        causation_id=previous["event_id"] if previous else None,
        previous_event_sha256=previous["event_payload_sha256"] if previous else None,
        correlation_id="journal-correlation",
    )
    base["trust_binding"] = BUILDER["trust_binding"](
        "producer_journal" if producer == "MaskFactory" else "consumer_journal"
    )
    base["subject"] = {
        "release_id": BUILDER["RELEASE_ID"] if resource_kind == "release" else None,
        "adoption_id": None,
        "capability_snapshot_id": None,
        "consumer_requirements_id": None,
        "request_id": (
            "mfareq_bbbbbbbbbbbbbbbbbbbbbbbb" if resource_kind in {"request", "receipt"} else None
        ),
        "receipt_id": None,
        "certificate_id": None,
        "artifact_sha256": None,
    }
    base["state_transition"] = {
        "resource_kind": resource_kind,
        "from_state": from_state,
        "to_state": to_state,
        "submission_identity_sha256": hashlib.sha256(b"submission").hexdigest(),
        "receipt_last_atomic_commit": event_type == "receipt_committed",
        "invalidation_event_id": invalidation["event_id"] if invalidation else None,
        "invalidation_event_sha256": invalidation["event_payload_sha256"] if invalidation else None,
        "reconciliation": reconciliation,
    }
    if invalidation:
        base["payload_schema"] = {
            "name": "mask_authority_invalidation_event",
            "version": "1.0.0",
            "sha256": hashlib.sha256(
                (SCHEMAS / "mask_authority_invalidation_event.schema.json").read_bytes()
            ).hexdigest(),
        }
        base["payload_sha256"] = invalidation["event_payload_sha256"]
    role = "producer_journal" if producer == "MaskFactory" else "consumer_journal"
    _sign(base, "event_payload_sha256", role)
    return base


def test_event_vocabulary_equals_transition_matrix_and_invalidation_replays_adoption_block() -> (
    None
):
    event_types = set(
        _json(SCHEMAS / "mask_bridge_event.schema.json")["properties"]["event_type"]["enum"]
    )
    assert event_types == set(validation._EVENT_TRANSITIONS)
    published = _journal_event(
        "release_published", 1, "MaskFactory", "release", "none", "published"
    )
    adopted = _journal_event(
        "release_adopted", 2, "Comfy_UI_Main", "release", "published", "adopted", previous=published
    )
    invalidation = _invalidation_for_reason("certificate_revoked")
    revalidation = _journal_event(
        "adoption_revalidation_required",
        3,
        "Comfy_UI_Main",
        "release",
        "adopted",
        "revalidation_required",
        previous=adopted,
        invalidation=invalidation,
    )
    assert (
        validate_bridge_event_chain(
            [published, adopted, revalidation], trusted_signing_keys=TRUSTED_KEYS
        )
        == ()
    )
    broken = copy.deepcopy(revalidation)
    broken["state_transition"]["invalidation_event_sha256"] = "f" * 64
    _sign(broken, "event_payload_sha256", "consumer_journal")
    assert "invalidation_event_binding" in _validators(
        validate_bridge_event_chain([published, adopted, broken], trusted_signing_keys=TRUSTED_KEYS)
    )


@pytest.mark.parametrize(
    ("event_type", "outcome", "status", "to_state", "remote", "result", "not_found", "resubmit"),
    [
        (
            "submission_reconciled_found_running",
            "found_running",
            "running",
            "running",
            True,
            False,
            False,
            False,
        ),
        (
            "submission_reconciled_found_completed_pending_receipt",
            "found_completed_pending_receipt",
            "completed",
            "completed_pending_receipt",
            True,
            True,
            False,
            False,
        ),
        (
            "submission_reconciled_found_failed",
            "found_failed",
            "failed",
            "failed",
            True,
            False,
            False,
            False,
        ),
        (
            "submission_reconciled_not_found_safe_to_submit",
            "not_found_safe_to_submit",
            "not_found",
            "reconciled_not_found",
            False,
            False,
            True,
            True,
        ),
    ],
)
def test_unknown_submission_reconciliation_is_outcome_specific(
    event_type, outcome, status, to_state, remote, result, not_found, resubmit
) -> None:
    submitted = _journal_event(
        "request_submitted", 1, "Comfy_UI_Main", "request", "none", "submitted"
    )
    unknown = _journal_event(
        "submission_unknown",
        2,
        "Comfy_UI_Main",
        "request",
        "submitted",
        "submission_unknown",
        previous=submitted,
    )
    reconciliation = {
        "outcome": outcome,
        "remote_execution_id": "remote-1" if remote else None,
        "remote_execution_sha256": "a" * 64 if remote else None,
        "remote_status": status,
        "remote_result_sha256": "b" * 64 if result else None,
        "checked_at": "2026-07-17T00:00:03Z",
        "not_found_evidence_sha256": "c" * 64 if not_found else None,
        "resubmission_authorized": resubmit,
    }
    reconciled = _journal_event(
        event_type,
        3,
        "MaskFactory",
        "request",
        "submission_unknown",
        to_state,
        previous=unknown,
        reconciliation=reconciliation,
    )
    events = [submitted, unknown, reconciled]
    if resubmit:
        events.append(
            _journal_event(
                "request_submitted",
                4,
                "Comfy_UI_Main",
                "request",
                "reconciled_not_found",
                "submitted",
                previous=reconciled,
            )
        )
    assert validate_bridge_event_chain(events, trusted_signing_keys=TRUSTED_KEYS) == ()
    if not resubmit:
        duplicate = _journal_event(
            "request_submitted",
            4,
            "Comfy_UI_Main",
            "request",
            to_state,
            "submitted",
            previous=reconciled,
        )
        assert validate_bridge_event_chain(events + [duplicate], trusted_signing_keys=TRUSTED_KEYS)


def test_repair_feedback_error_policy_and_idempotency_guards() -> None:
    documents = _bridge_set()
    request, receipt, certificate = _fixture_exchange()
    feedback = documents["mask_repair_feedback"]
    assert (
        validate_mask_repair_feedback(
            feedback,
            trusted_signing_keys=TRUSTED_KEYS,
            parent_receipt=receipt,
            parent_request=request,
            certificate=certificate,
        )
        == ()
    )
    tampered = copy.deepcopy(feedback)
    tampered["retry_budget"]["remaining_attempts"] += 1
    _sign(tampered, "feedback_payload_sha256", "consumer_feedback")
    assert "repair_retry_budget" in _validators(
        validate_mask_repair_feedback(tampered, trusted_signing_keys=TRUSTED_KEYS)
    )
    error = copy.deepcopy(documents["mask_bridge_error"])
    error["remediation"]["action"] = "silent_fallback"
    assert validate_mask_bridge_error(error)
    duplicate = copy.deepcopy(request)
    duplicate["request_payload_sha256"] = "f" * 64
    assert "idempotency_collision" in _validators(
        validate_idempotency_records([request, duplicate])
    )
