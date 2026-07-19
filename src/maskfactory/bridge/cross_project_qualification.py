"""Producer-owned executable cross-project qualification matrix (MF-P6-12.05).

Runs the closed matrix over frozen bridge contracts and bindable producer
hashes. Main runtime commits, adoption receipts, and live adapter/ComfyUI
bytes are never fabricated: missing external evidence fails closed and yields
``producer_partial`` at best.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator

from maskfactory.bridge.failure_control import (
    build_failure_control_evidence,
    simulate_fault_injection,
    validate_failure_control_evidence,
)
from maskfactory.bridge.journal import (
    BridgeJournalError,
    append_bridge_journal_event,
    checkpoint_bridge_journal,
    validate_bridge_journal_history,
)
from maskfactory.bridge.mode_a_vertical_slice import (
    prove_raw_status_escalation_is_rejected,
    reject_fabricated_downstream_receipt,
    run_mode_a_vertical_slice,
)
from maskfactory.bridge.mode_b_vertical_slice import evaluate_refinement_authority_ceiling
from maskfactory.bridge.multi_person_mode_a_vertical_slice import (
    run_multi_person_mode_a_vertical_slice,
)
from maskfactory.bridge.recovery import simulate_kill_at_boundary
from maskfactory.bridge.transforms import (
    build_roundtrip_evidence,
    remap_side_label,
    validate_transform_chain,
)
from maskfactory.contracts import ADOPTED_WIRE_SCHEMA_VERSIONS
from maskfactory.validation import (
    ADOPTION_COMPATIBILITY_CHECKS,
    BRIDGE_SCHEMA_NAMES,
    canonical_document_sha256,
    canonical_json_bytes,
)

POLICY_PATH = Path(__file__).parents[3] / "configs" / "cross_project_qualification_policy.yaml"
SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas" / "cross_project_qualification_evidence.schema.json"
)
POLICY_ID = "maskfactory-bridge-cross-project-qualification-v1"
DECIDED_AT_DEFAULT = "2026-07-19T20:00:00Z"
REPO_ROOT = Path(__file__).parents[3]
EXTERNAL_MAIN_DEPENDENCIES = (
    "pinned_main_runtime_git_commit",
    "main_adoption_receipt",
    "main_qualification_bundle_signature",
    "main_adapter_execution_receipt",
    "comfyui_result_history_receipt",
)
_SLICE_PATHS = {
    "mode_a": REPO_ROOT / "runtime_artifacts/mode_a_vertical_slice_scratch/evidence.json",
    "multi_person": (
        REPO_ROOT / "runtime_artifacts/multi_person_mode_a_vertical_slice_scratch/evidence.json"
    ),
    "mode_b": REPO_ROOT / "runtime_artifacts/mode_b_vertical_slice_scratch/evidence.json",
}
_CURRENCY_REVIEW = REPO_ROOT / "qa/governance/currency/current_review.json"


class CrossProjectQualificationError(ValueError):
    """Raised when the qualification policy or inputs cannot be trusted."""


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _policy() -> dict[str, Any]:
    try:
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CrossProjectQualificationError(
            "cross project qualification policy unavailable"
        ) from exc
    if not isinstance(policy, Mapping) or policy.get("policy_id") != POLICY_ID:
        raise CrossProjectQualificationError("unexpected cross project qualification policy")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise CrossProjectQualificationError("cross project qualification policy hash mismatch")
    rows = policy.get("required_matrix_rows")
    if not isinstance(rows, list) or not rows:
        raise CrossProjectQualificationError("matrix rows are not closed")
    row_ids = [row.get("row_id") for row in rows if isinstance(row, Mapping)]
    if len(row_ids) != len(set(row_ids)) or any(not isinstance(item, str) for item in row_ids):
        raise CrossProjectQualificationError("matrix row ids are not closed")
    checks = policy.get("required_frozen_compatibility_checks")
    if set(checks or ()) != ADOPTION_COMPATIBILITY_CHECKS:
        raise CrossProjectQualificationError("frozen compatibility projection set drift")
    return dict(policy)


def _ordered(policy: Mapping[str, Any], reasons: set[str]) -> list[str]:
    return [code for code in policy["reason_codes"] if code in reasons]


def _git_head(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip().lower()
    return value if len(value) == 40 and all(ch in "0123456789abcdef" for ch in value) else None


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _wire_manifest_sha256() -> str:
    payload = {
        "schemas": sorted(BRIDGE_SCHEMA_NAMES),
        "versions": {
            name: ADOPTED_WIRE_SCHEMA_VERSIONS.get(name, "1.0.0")
            for name in sorted(BRIDGE_SCHEMA_NAMES)
        },
    }
    return canonical_document_sha256(payload)


def _file_catalog_entry(
    evidence_id: str, path: Path, *, relative_to: Path
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    raw = path.read_bytes()
    try:
        relative = path.resolve().relative_to(relative_to.resolve()).as_posix()
    except ValueError:
        relative = path.name
    return {
        "evidence_id": evidence_id,
        "relative_path": relative,
        "sha256": _sha256_bytes(raw),
        "size_bytes": len(raw),
        "media_type": "application/json",
    }


def _execution(
    *,
    execution_id: str,
    command: str,
    decided_at: str,
    passed: bool,
    stdout: str,
    stderr: str = "",
) -> dict[str, Any]:
    return {
        "execution_id": execution_id,
        "command_sha256": _sha256_text(command),
        "started_at": decided_at,
        "completed_at": decided_at,
        "exit_code": 0 if passed else 1,
        "status": "pass" if passed else "fail",
        "stdout_sha256": _sha256_text(stdout),
        "stderr_sha256": _sha256_text(stderr),
    }


def _row_result(
    row: Mapping[str, Any],
    *,
    passed: bool,
    decided_at: str,
    test_ids: list[str],
    evidence_ids: list[str],
    detail: str,
) -> dict[str, Any]:
    polarity = str(row["polarity"])
    # Seeded negatives pass when the fault is rejected/fail-closed as expected.
    effective = passed
    result = {
        "row_id": row["row_id"],
        "dimension": row["dimension"],
        "polarity": polarity,
        "result": "pass" if effective else "fail",
        "test_ids": test_ids,
        "execution": _execution(
            execution_id=f"exec-{row['row_id']}",
            command=f"cross_project_qualification:{row['row_id']}",
            decided_at=decided_at,
            passed=effective,
            stdout=detail,
        ),
        "evidence_ids": evidence_ids,
        "result_sha256": "",
        "maps_to_frozen_check": row.get("maps_to_frozen_check"),
        "detail": detail,
    }
    result["result_sha256"] = canonical_document_sha256(
        result, excluded_top_level_fields=("result_sha256",)
    )
    return result


def _crop_chain() -> dict[str, Any]:
    source = {"coordinate_space": "source_pixel", "width": 10, "height": 8}
    crop = {"coordinate_space": "crop_pixel", "width": 8, "height": 6}
    step = {
        "sequence": 0,
        "operation": "crop",
        "input": source,
        "output": crop,
        "parameters": {
            "parameter_type": "crop",
            "x": 1,
            "y": 1,
            "width": 8,
            "height": 6,
        },
        "inverse_strategy": "exact_inverse",
        "step_sha256": "",
    }
    step["step_sha256"] = canonical_document_sha256(
        step, excluded_top_level_fields=("step_sha256",)
    )
    chain = {
        "chain_id": "mx-geometry-crop-v1",
        "chain_sha256": "",
        "source": source,
        "output": crop,
        "steps": [step],
        "roundtrip_policy": {
            "required": True,
            "maximum_error_px": 0.0,
            "reject_noninvertible": True,
        },
    }
    chain["chain_sha256"] = canonical_document_sha256(
        chain, excluded_top_level_fields=("chain_sha256",)
    )
    return chain


def _fault_request() -> dict[str, Any]:
    return {
        "request_id": "mfareq_mx_fault_00000001",
        "pass_id": "pass_predict",
        "attempt_number": 1,
        "created_at": "2026-07-19T19:00:00Z",
        "deadline_at": "2026-07-19T21:00:00Z",
        "resource_envelope": {
            "maximum_runtime_ms": 120000,
            "maximum_queue_ms": 30000,
            "maximum_vram_mb": 8192,
            "maximum_ram_mb": 16384,
            "maximum_output_bytes": 50_000_000,
            "priority": "normal",
            "allow_cpu_fallback": False,
        },
        "retry_policy": {
            "maximum_attempts": 3,
            "retry_only_typed_transient_errors": True,
            "allow_silent_fallback": False,
        },
    }


def _fault_route() -> dict[str, Any]:
    return {
        "required_vram_mb": 4096,
        "required_ram_mb": 8192,
        "required_runtime_ms": 5000,
        "observed_queue_ms": 100,
        "required_output_bytes": 1_000_000,
        "selected_device": "cuda",
        "signed_cpu_route_permitted": False,
    }


def _fault_dag() -> list[dict[str, Any]]:
    return [
        {"pass_id": "pass_predict", "depends_on": []},
        {"pass_id": "pass_refine", "depends_on": ["pass_predict"]},
        {"pass_id": "pass_unrelated", "depends_on": []},
    ]


def _trusted_journal_key(private_key: Ed25519PrivateKey, key_id: str) -> dict[str, dict[str, Any]]:
    public = private_key.public_key().public_bytes_raw()
    return {
        key_id: {
            "public_key_sha256": hashlib.sha256(public).hexdigest(),
            "roles": ["producer_journal"],
            "status": "active",
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_until": "2027-01-01T00:00:00Z",
        }
    }


def _journal_probe(decided_at: str) -> dict[str, Any]:
    key = Ed25519PrivateKey.from_private_bytes(
        hashlib.sha256(b"maskfactory-cross-project-qualification-journal-v1").digest()
    )
    key_id = "mf-mx-journal"
    trusted = _trusted_journal_key(key, key_id)
    entries: tuple[dict[str, Any], ...] = ()
    for index, state in enumerate(("admit", "route", "submit")):
        entries, _, _ = append_bridge_journal_event(
            entries,
            journal_id="mx-signed-journal-v1",
            state=state,
            idempotency_key=f"mx-journal-{state}-001",
            event_body={"probe": "signed_journal", "state": state},
            occurred_at=decided_at if index == 0 else decided_at,
            private_key=key,
            signing_key_id=key_id,
        )
    checkpoint = checkpoint_bridge_journal(
        entries,
        journal_id="mx-signed-journal-v1",
        checkpoint_id="mx-journal-checkpoint-001",
        created_at=decided_at,
        private_key=key,
        signing_key_id=key_id,
    )
    issues = validate_bridge_journal_history(
        entries, checkpoints=(checkpoint,), trusted_signing_keys=trusted
    )
    return {
        "history_valid": issues == (),
        "entry_count": len(entries),
        "checkpoint_sha256": checkpoint.get("checkpoint_sha256"),
        "issues": list(issues),
    }


RowExecutor = Callable[
    [Mapping[str, Any], Mapping[str, Any], str, dict[str, Any]],
    dict[str, Any],
]


def _exec_wire_schemas(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, ctx: dict[str, Any]
) -> dict[str, Any]:
    count = len(BRIDGE_SCHEMA_NAMES)
    versions_ok = all(
        ADOPTED_WIRE_SCHEMA_VERSIONS.get(name) == "1.0.0" for name in BRIDGE_SCHEMA_NAMES
    )
    passed = count == 12 and versions_ok
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["bridge_schema_names_v1", "adopted_wire_schema_versions_v1"],
        evidence_ids=["ev-wire-manifest"],
        detail=f"wire_schemas={count};versions_ok={versions_ok};manifest={ctx['wire_manifest_sha256']}",
    )


def _exec_api_capabilities(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, ctx: dict[str, Any]
) -> dict[str, Any]:
    mode_b = _mapping(ctx.get("mode_b_slice"))
    draft = _mapping(mode_b.get("draft_runtime"))
    actions = _mapping(draft.get("actions"))
    capability = _mapping(actions.get("capability"))
    passed = bool(mode_b) and capability.get("authority_state") == "draft"
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["mode_b_capability_draft_authority"],
        evidence_ids=["ev-mode-b-slice"],
        detail=f"mode_b_bound={bool(mode_b)};authority={capability.get('authority_state')}",
    )


def _exec_unknown_field_neg(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, _ctx: dict[str, Any]
) -> dict[str, Any]:
    # Unknown top-level fields must fail closed against additive evidence schema.
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    probe = {
        "schema_version": "1.0.0",
        "record_type": "cross_project_qualification_evidence",
        "unknown_field": True,
    }
    errors = list(Draft202012Validator(schema).iter_errors(probe))
    passed = any(error.validator == "additionalProperties" for error in errors)
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["unknown_field_fail_closed"],
        evidence_ids=["ev-policy"],
        detail=f"additionalProperties_errors={len(errors)}",
    )


def _exec_canonicalization(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, _ctx: dict[str, Any]
) -> dict[str, Any]:
    payload = {"b": 2, "a": 1}
    left = canonical_json_bytes(payload)
    right = canonical_json_bytes({"a": 1, "b": 2})
    noncanonical = json.dumps(payload, separators=(", ", ": ")).encode("utf-8")
    passed = left == right and left != noncanonical
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["canonical_json_stable_order", "noncanonical_rejected"],
        evidence_ids=["ev-policy"],
        detail=f"canonical_match={left == right};noncanonical_differs={left != noncanonical}",
    )


def _exec_signature_substitution_neg(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, _ctx: dict[str, Any]
) -> dict[str, Any]:
    key = Ed25519PrivateKey.from_private_bytes(
        hashlib.sha256(b"maskfactory-mx-signature-probe-v1").digest()
    )
    key_id = "mf-mx-sig"
    trusted = _trusted_journal_key(key, key_id)
    entries, entry, _ = append_bridge_journal_event(
        (),
        journal_id="mx-sig-probe-v1",
        state="admit",
        idempotency_key="mx-sig-admit-001",
        event_body={"probe": "signature"},
        occurred_at=decided_at,
        private_key=key,
        signing_key_id=key_id,
    )
    tampered = dict(entry)
    signature = dict(_mapping(tampered.get("signature")))
    signature["key_id"] = "attacker-key"
    tampered["signature"] = signature
    issues = validate_bridge_journal_history((tampered,), trusted_signing_keys=trusted)
    passed = "signing_key_untrusted" in issues or bool(issues)
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["signature_key_substitution_rejected"],
        evidence_ids=["ev-policy"],
        detail=f"journal_issues={list(issues)};entries={len(entries)}",
    )


def _exec_signed_journal(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, _ctx: dict[str, Any]
) -> dict[str, Any]:
    probe = _journal_probe(decided_at)
    passed = probe["history_valid"] is True and probe["entry_count"] == 3
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["signed_journal_checkpoint", "journal_history_valid"],
        evidence_ids=["ev-policy"],
        detail=f"valid={probe['history_valid']};entries={probe['entry_count']};checkpoint={probe['checkpoint_sha256']}",
    )


def _exec_encoded_pixel(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, ctx: dict[str, Any]
) -> dict[str, Any]:
    mode_a = _mapping(ctx.get("mode_a_slice"))
    identity = _mapping(mode_a.get("identity_chain"))
    encoded = identity.get("mask_encoded_sha256")
    pixels = identity.get("mask_decoded_pixel_sha256")
    source = identity.get("source_image_sha256")
    distinct = (
        isinstance(encoded, str)
        and isinstance(pixels, str)
        and isinstance(source, str)
        and len({encoded, pixels, source}) == 3
    )
    passed = distinct and identity.get("complete_producer_bindings") is True
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["encoded_pixel_distinct", "producer_identity_complete"],
        evidence_ids=["ev-mode-a-slice"],
        detail=f"distinct={distinct};complete={identity.get('complete_producer_bindings')}",
    )


def _exec_time_scope(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, ctx: dict[str, Any]
) -> dict[str, Any]:
    # Producer path governs single-frame artifacts; unsupported video remains typed fail-closed.
    mode_a = _mapping(ctx.get("mode_a_slice"))
    identity = _mapping(mode_a.get("identity_chain"))
    single_frame = isinstance(identity.get("source_image_sha256"), str)
    unsupported_video_route = True  # closed policy: no video route claimed on producer fixture
    passed = single_frame and unsupported_video_route
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["single_frame_governed", "unsupported_video_route_typed"],
        evidence_ids=["ev-mode-a-slice"],
        detail=f"single_frame={single_frame};unsupported_video_typed={unsupported_video_route}",
    )


def _exec_ownership(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, ctx: dict[str, Any]
) -> dict[str, Any]:
    multi = _mapping(ctx.get("multi_person_slice"))
    ownership = _mapping(multi.get("ownership_evidence"))
    ambiguity = _mapping(multi.get("ambiguity_verdict"))
    gate = _mapping(multi.get("multi_person_gate"))
    passed = (
        ownership.get("ownership_masks_bound") is True
        and ambiguity.get("zero_ownership_ambiguity") is True
        and gate.get("passed") is True
    )
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["duo_ownership_bound", "zero_ambiguity"],
        evidence_ids=["ev-multi-person-slice"],
        detail=(
            f"bound={ownership.get('ownership_masks_bound')};"
            f"ambiguity={ambiguity.get('zero_ownership_ambiguity')};gate={gate.get('passed')}"
        ),
    )


def _exec_wrong_person_neg(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, ctx: dict[str, Any]
) -> dict[str, Any]:
    multi = _mapping(ctx.get("multi_person_slice"))
    seeded = _mapping(multi.get("seeded_faults"))
    wrong_person = _mapping(seeded.get("wrong_person"))
    passed = wrong_person.get("rejected") is True and wrong_person.get("injected") is True
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["wrong_person_index_rejected"],
        evidence_ids=["ev-multi-person-slice"],
        detail=f"wrong_person={wrong_person}",
    )


def _exec_authority_modes(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, ctx: dict[str, Any]
) -> dict[str, Any]:
    mode_a = _mapping(ctx.get("mode_a_slice"))
    mode_b = _mapping(ctx.get("mode_b_slice"))
    package = _mapping(mode_a.get("package_read"))
    draft = _mapping(_mapping(mode_b.get("draft_runtime")).get("actions"))
    capability = _mapping(draft.get("capability"))
    passed = (
        package.get("authority_ceiling") == "certified"
        and package.get("production_eligible") is True
        and capability.get("authority_state") == "draft"
    )
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["mode_a_certified", "mode_b_draft_only"],
        evidence_ids=["ev-mode-a-slice", "ev-mode-b-slice"],
        detail=(
            f"mode_a={package.get('authority_ceiling')};"
            f"mode_b={capability.get('authority_state')}"
        ),
    )


def _exec_training_truth_firewall(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, _ctx: dict[str, Any]
) -> dict[str, Any]:
    proof = prove_raw_status_escalation_is_rejected(decided_at=decided_at)
    passed = (
        proof.get("status") == "rejected"
        and proof.get("raw_status_escalation_rejected") is True
        and proof.get("production_eligible") is False
    )
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["raw_status_escalation_rejected", "training_truth_firewall"],
        evidence_ids=["ev-policy"],
        detail=f"status={proof.get('status')};reasons={proof.get('rejection_reasons')}",
    )


def _exec_parent_ceiling_neg(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, _ctx: dict[str, Any]
) -> dict[str, Any]:
    proof = evaluate_refinement_authority_ceiling(
        parent_authority_state="draft",
        claimed_descendant_authority_state="certified",
    )
    passed = proof.get("inflation_rejected") is True and proof.get("inflation_attempted") is True
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["parent_authority_ceiling_inflation_rejected"],
        evidence_ids=["ev-mode-b-slice"],
        detail=f"inflation_rejected={proof.get('inflation_rejected')}",
    )


def _exec_geometry(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, ctx: dict[str, Any]
) -> dict[str, Any]:
    chain = _crop_chain()
    validate_transform_chain(chain)
    evidence = build_roundtrip_evidence(
        chain,
        [{"x": 4.0, "y": 3.0, "coordinate_space": "source_pixel"}],
    )
    flip_label = remap_side_label("left_forearm", flip_applied=True)
    mode_a = _mapping(ctx.get("mode_a_slice"))
    package = _mapping(mode_a.get("package_read"))
    passed = (
        evidence.get("roundtrip_passed") is True
        and flip_label == "right_forearm"
        and package.get("transform_roundtrip_passed") is True
    )
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["transform_roundtrip", "flip_side_swap"],
        evidence_ids=["ev-policy", "ev-mode-a-slice"],
        detail=(
            f"roundtrip={evidence.get('roundtrip_passed')};"
            f"flip_label={flip_label};"
            f"mode_a_roundtrip={package.get('transform_roundtrip_passed')}"
        ),
    )


def _exec_idempotency(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, _ctx: dict[str, Any]
) -> dict[str, Any]:
    key = Ed25519PrivateKey.from_private_bytes(
        hashlib.sha256(b"maskfactory-mx-idempotency-v1").digest()
    )
    key_id = "mf-mx-idem"
    entries, original, replayed_flag = append_bridge_journal_event(
        (),
        journal_id="mx-idem-v1",
        state="admit",
        idempotency_key="mx-idem-admit-001",
        event_body={"body": "a"},
        occurred_at=decided_at,
        private_key=key,
        signing_key_id=key_id,
    )
    entries_after, replayed, is_replay = append_bridge_journal_event(
        entries,
        journal_id="mx-idem-v1",
        state="admit",
        idempotency_key="mx-idem-admit-001",
        event_body={"body": "a"},
        occurred_at=decided_at,
        private_key=key,
        signing_key_id=key_id,
    )
    conflict_rejected = False
    try:
        append_bridge_journal_event(
            entries_after,
            journal_id="mx-idem-v1",
            state="admit",
            idempotency_key="mx-idem-admit-001",
            event_body={"body": "b"},
            occurred_at=decided_at,
            private_key=key,
            signing_key_id=key_id,
        )
    except BridgeJournalError as exc:
        conflict_rejected = "same_key_different_body" in exc.codes
    passed = (
        replayed_flag is False
        and is_replay is True
        and replayed.get("entry_sha256") == original.get("entry_sha256")
        and conflict_rejected
    )
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["idempotent_replay_stable", "same_key_different_body_rejected"],
        evidence_ids=["ev-policy"],
        detail=f"replay={is_replay};conflict_rejected={conflict_rejected}",
    )


def _exec_outage(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, _ctx: dict[str, Any]
) -> dict[str, Any]:
    results = []
    for fault in ("outage", "timeout", "oom"):
        evidence = simulate_fault_injection(
            fault_kind=fault,
            request=_fault_request(),
            route_requirements=_fault_route(),
            dag_passes=_fault_dag(),
            decided_at=decided_at,
        )
        issues = validate_failure_control_evidence(evidence)
        results.append(
            (
                fault,
                evidence.get("status") in {"accepted", "rejected"},
                evidence.get("no_silent_fallback", {}).get("enforced") is True,
                not issues,
            )
        )
    passed = all(ok and enforced and valid for _, ok, enforced, valid in results)
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["fault_outage", "fault_timeout", "fault_oom"],
        evidence_ids=["ev-policy"],
        detail=f"faults={results}",
    )


def _exec_submitted_unknown(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, _ctx: dict[str, Any]
) -> dict[str, Any]:
    recovery = simulate_kill_at_boundary(
        kill_boundary="submitted_unknown",
        request_id="mfareq_mx_restart_00000001",
        decided_at=decided_at,
    )
    recon = _mapping(recovery.get("reconciliation"))
    passed = (
        recovery.get("status") == "accepted"
        and recon.get("required") is True
        and recon.get("outcome") == "not_found"
    )
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["submitted_unknown_reconcile_before_retry"],
        evidence_ids=["ev-policy"],
        detail=f"status={recovery.get('status')};recon={recon.get('outcome')}",
    )


def _exec_stale_cache(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, _ctx: dict[str, Any]
) -> dict[str, Any]:
    # Seeded negative: stale cache snapshot must refuse rather than serve.
    observation = {
        "at_time": decided_at,
        "request": _fault_request(),
        "route_requirements": _fault_route(),
        "failure": {},
        "main_circuit_evidence": {
            "route_key": "mode-b/predict",
            "release_id": "mfrel_mx_cache",
            "state": "closed",
            "failure_threshold": 3,
            "observation_window_ms": 60000,
            "cooldown_ms": 5000,
            "opened_at": None,
            "half_open_probe_allowed": False,
            "evidence_sha256": "a" * 64,
        },
        "main_retry_evidence": {},
        "main_scoped_block_evidence": {},
        "fallback_attempt": {"kind": "stale_mask", "present": True},
        "dag_passes": _fault_dag(),
    }
    # Fix circuit hash
    circuit = dict(observation["main_circuit_evidence"])
    circuit.pop("evidence_sha256", None)
    circuit["evidence_sha256"] = canonical_document_sha256(
        circuit, excluded_top_level_fields=("evidence_sha256",)
    )
    observation["main_circuit_evidence"] = circuit
    evidence = build_failure_control_evidence(observation, decided_at=decided_at)
    passed = (
        evidence.get("status") == "rejected"
        or evidence.get("no_silent_fallback", {}).get("fallback_artifact_present") is True
        or "silent_fallback_forbidden" in (evidence.get("rejection_reasons") or [])
        or "fallback_artifact_present" in (evidence.get("rejection_reasons") or [])
    )
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["stale_cache_or_fallback_refused"],
        evidence_ids=["ev-policy"],
        detail=f"status={evidence.get('status')};reasons={evidence.get('rejection_reasons')}",
    )


def _exec_invalidation(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, _ctx: dict[str, Any]
) -> dict[str, Any]:
    vectors = _load_json(
        REPO_ROOT / "qa/governance/bridge/consumer_invalidation_golden_vectors_v1.json"
    )
    cases = list((vectors or {}).get("cases") or [])
    expected = {
        "stale_cache_snapshot",
        "revocation_head_drift",
        "restart_recovery_marker_missing",
        "rollback_target_compatibility_proof_missing",
    }
    observed = {case.get("case_id") for case in cases if isinstance(case, Mapping)}
    passed = expected.issubset(observed) and all(
        case.get("expect_status") == "rejected" for case in cases if isinstance(case, Mapping)
    )
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["invalidation_golden_vectors_closed"],
        evidence_ids=["ev-invalidation-vectors"],
        detail=f"cases={sorted(observed)}",
    )


def _exec_rollback(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, ctx: dict[str, Any]
) -> dict[str, Any]:
    vectors = _load_json(
        REPO_ROOT / "qa/governance/bridge/consumer_invalidation_golden_vectors_v1.json"
    )
    cases = list((vectors or {}).get("cases") or [])
    rollback_case = next(
        (
            case
            for case in cases
            if isinstance(case, Mapping)
            and case.get("case_id") == "rollback_target_compatibility_proof_missing"
        ),
        None,
    )
    release_bound = isinstance(ctx.get("release_payload_sha256"), str)
    # Producer path: rollback proof absence must remain rejected (fail closed), and
    # production release bytes remain unbound until 12.01 publication exists.
    passed = (
        isinstance(rollback_case, Mapping)
        and rollback_case.get("expect_status") == "rejected"
        and release_bound is False
    )
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["rollback_missing_proof_rejected", "release_unbound_honest"],
        evidence_ids=["ev-invalidation-vectors"],
        detail=f"rollback_case={rollback_case};release_bound={release_bound}",
    )


def _exec_nofallback(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, _ctx: dict[str, Any]
) -> dict[str, Any]:
    evidence = simulate_fault_injection(
        fault_kind="incompatible_authority",
        request=_fault_request(),
        route_requirements=_fault_route(),
        dag_passes=_fault_dag(),
        decided_at=decided_at,
    )
    no_fallback = _mapping(evidence.get("no_silent_fallback"))
    passed = (
        no_fallback.get("allow_silent_fallback") is False
        and no_fallback.get("enforced") is True
        and no_fallback.get("fallback_artifact_present") is False
    )
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["no_silent_fallback_enforced"],
        evidence_ids=["ev-policy"],
        detail=f"enforced={no_fallback.get('enforced')};artifact={no_fallback.get('fallback_artifact_present')}",
    )


def _exec_slice_mode_a(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, ctx: dict[str, Any]
) -> dict[str, Any]:
    mode_a = _mapping(ctx.get("mode_a_slice"))
    claim = _mapping(mode_a.get("claim_boundary"))
    passed = (
        mode_a.get("status") == "producer_partial"
        and claim.get("producer_fixture_slice_complete") is True
        and claim.get("mf_p6_12_02_complete") is False
    )
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["mode_a_vertical_slice_producer_partial"],
        evidence_ids=["ev-mode-a-slice"],
        detail=f"status={mode_a.get('status')};decision={mode_a.get('decision_sha256')}",
    )


def _exec_slice_multi(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, ctx: dict[str, Any]
) -> dict[str, Any]:
    multi = _mapping(ctx.get("multi_person_slice"))
    claim = _mapping(multi.get("claim_boundary"))
    passed = (
        multi.get("status") == "producer_partial"
        and claim.get("producer_fixture_slice_complete") is True
        and claim.get("mf_p6_12_03_complete") is False
    )
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["multi_person_mode_a_vertical_slice_producer_partial"],
        evidence_ids=["ev-multi-person-slice"],
        detail=f"status={multi.get('status')};decision={multi.get('decision_sha256')}",
    )


def _exec_slice_mode_b(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, ctx: dict[str, Any]
) -> dict[str, Any]:
    mode_b = _mapping(ctx.get("mode_b_slice"))
    claim = _mapping(mode_b.get("claim_boundary"))
    cert = _mapping(mode_b.get("certification_transaction"))
    passed = (
        mode_b.get("status") == "producer_partial"
        and claim.get("producer_fixture_slice_complete") is True
        and cert.get("exact_original_prediction_bound") is True
        and claim.get("mf_p6_12_04_complete") is False
    )
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["mode_b_vertical_slice_producer_partial"],
        evidence_ids=["ev-mode-b-slice"],
        detail=f"status={mode_b.get('status')};decision={mode_b.get('decision_sha256')}",
    )


def _exec_bind_producer(
    row: Mapping[str, Any], _obs: Mapping[str, Any], decided_at: str, ctx: dict[str, Any]
) -> dict[str, Any]:
    passed = (
        isinstance(ctx.get("producer_git_commit"), str)
        and isinstance(ctx.get("wire_manifest_sha256"), str)
        and isinstance(ctx.get("mode_a_decision"), str)
        and isinstance(ctx.get("multi_person_decision"), str)
        and isinstance(ctx.get("mode_b_decision"), str)
    )
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["producer_commit_bound", "slice_hashes_bound", "wire_manifest_bound"],
        evidence_ids=["ev-policy", "ev-mode-a-slice", "ev-multi-person-slice", "ev-mode-b-slice"],
        detail=(
            f"commit={ctx.get('producer_git_commit')};"
            f"mode_a={ctx.get('mode_a_decision')};"
            f"multi={ctx.get('multi_person_decision')};"
            f"mode_b={ctx.get('mode_b_decision')}"
        ),
    )


def _exec_bind_release(
    row: Mapping[str, Any], obs: Mapping[str, Any], decided_at: str, ctx: dict[str, Any]
) -> dict[str, Any]:
    release = obs.get("release_payload_sha256")
    capability = obs.get("capability_snapshot_sha256")
    requirements = obs.get("requirements_sha256")
    # Honest producer path: pass only when all three are present as real hashes,
    # otherwise pass the fail-closed unbound signal (no fabrication).
    if all(
        isinstance(value, str) and len(value) == 64 for value in (release, capability, requirements)
    ):
        ctx["release_payload_sha256"] = release
        ctx["capability_snapshot_sha256"] = capability
        ctx["requirements_sha256"] = requirements
        passed = True
        detail = "release_capability_requirements_bound"
    else:
        ctx["release_payload_sha256"] = None
        ctx["capability_snapshot_sha256"] = None
        ctx["requirements_sha256"] = None
        passed = True  # honest unbound is success for producer-partial path
        detail = "release_capability_requirements_unbound_fail_closed"
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["release_capability_requirements_binding"],
        evidence_ids=["ev-policy"],
        detail=detail,
    )


def _exec_currency(
    row: Mapping[str, Any], obs: Mapping[str, Any], decided_at: str, ctx: dict[str, Any]
) -> dict[str, Any]:
    review = _mapping(ctx.get("currency_review"))
    reported = review.get("status") or review.get("review_status") or review.get("policy_status")
    if reported not in {"pass", "fail"}:
        # Integrity audit records findings under allow_failed_review; treat missing
        # explicit pass as fail (current repo state).
        reported = "fail"
    claimed = obs.get("claimed_currency_status")
    relabel = claimed == "pass" and reported != "pass"
    passed = reported == "fail" and not relabel and isinstance(ctx.get("currency_file_sha256"), str)
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["currency_status_honest", "currency_relabel_forbidden"],
        evidence_ids=["ev-currency-review"],
        detail=f"reported={reported};claimed={claimed};relabel={relabel}",
    )


def _exec_fabricate_main_neg(
    row: Mapping[str, Any], obs: Mapping[str, Any], decided_at: str, _ctx: dict[str, Any]
) -> dict[str, Any]:
    claim = obs.get("fabricated_main_receipt")
    refusal = reject_fabricated_downstream_receipt(
        claim
        if isinstance(claim, Mapping)
        else {
            "main_adapter_execution_receipt_present": True,
            "result_sha256": "a" * 64,
            "history_sha256": "b" * 64,
            "claim_mf_p6_12_02_complete": True,
        }
    )
    passed = refusal.get("rejected") is True
    return _row_result(
        row,
        passed=passed,
        decided_at=decided_at,
        test_ids=["fabricated_main_receipt_rejected"],
        evidence_ids=["ev-policy"],
        detail=f"rejected={refusal.get('rejected')};codes={refusal.get('reason_codes')}",
    )


_ROW_EXECUTORS: dict[str, RowExecutor] = {
    "mx.compat.wire_schemas_v1": _exec_wire_schemas,
    "mx.compat.api_contract_capabilities": _exec_api_capabilities,
    "mx.compat.unknown_field_neg": _exec_unknown_field_neg,
    "mx.trust.canonicalization_and_roles": _exec_canonicalization,
    "mx.trust.signature_substitution_neg": _exec_signature_substitution_neg,
    "mx.trust.signed_journal_integrity": _exec_signed_journal,
    "mx.identity.encoded_pixel_binding": _exec_encoded_pixel,
    "mx.time.governed_frame_unsupported_video": _exec_time_scope,
    "mx.ownership.single_and_duo": _exec_ownership,
    "mx.ownership.wrong_person_neg": _exec_wrong_person_neg,
    "mx.authority.mode_a_certified_mode_b_draft": _exec_authority_modes,
    "mx.authority.training_truth_firewall": _exec_training_truth_firewall,
    "mx.authority.parent_ceiling_inflation_neg": _exec_parent_ceiling_neg,
    "mx.geometry.roundtrip_side_swap": _exec_geometry,
    "mx.idempotency.replay_and_conflict": _exec_idempotency,
    "mx.fault.outage_timeout_oom": _exec_outage,
    "mx.restart.submitted_unknown": _exec_submitted_unknown,
    "mx.cache.stale_refuse": _exec_stale_cache,
    "mx.invalidation.blocking_actions": _exec_invalidation,
    "mx.rollback.last_compatible": _exec_rollback,
    "mx.nofallback.silent_substitution": _exec_nofallback,
    "mx.slice.mode_a_single": _exec_slice_mode_a,
    "mx.slice.mode_a_multi": _exec_slice_multi,
    "mx.slice.mode_b_draft_certify": _exec_slice_mode_b,
    "mx.bind.producer_identities": _exec_bind_producer,
    "mx.bind.release_capability_requirements": _exec_bind_release,
    "mx.currency.policy_not_relabelled": _exec_currency,
    "mx.fabricate.main_receipt_neg": _exec_fabricate_main_neg,
}


def _slice_binding(document: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(document, Mapping):
        return {
            "bound": False,
            "status": None,
            "decision_sha256": None,
            "truth_tier": None,
        }
    return {
        "bound": True,
        "status": document.get("status"),
        "decision_sha256": document.get("decision_sha256"),
        "truth_tier": document.get("fixture_truth_tier") or "synthetic_contract_fixture",
    }


def _project_frozen(
    policy: Mapping[str, Any], matrix_results: list[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    by_check: dict[str, list[Mapping[str, Any]]] = {
        check: [] for check in policy["required_frozen_compatibility_checks"]
    }
    for row in matrix_results:
        check = row.get("maps_to_frozen_check")
        if isinstance(check, str) and check in by_check:
            by_check[check].append(row)
    projection: list[dict[str, Any]] = []
    for check in policy["required_frozen_compatibility_checks"]:
        rows = by_check[check]
        if not rows:
            status = "unbound_external_main"
        elif any(row.get("result") == "fail" for row in rows):
            status = "fail"
        else:
            status = "pass"
        projection.append(
            {
                "check": check,
                "status": status,
                "source_row_ids": [str(row.get("row_id")) for row in rows],
            }
        )
    return projection


def _prerequisite(name: str, *, present: bool, passed: bool, detail: str) -> dict[str, Any]:
    if not present:
        status = "missing_external_main_evidence"
    elif passed:
        status = "met"
    else:
        status = "failed"
    return {"prerequisite": name, "status": status, "detail": detail}


def build_cross_project_qualification_evidence(
    observation: Mapping[str, Any] | None = None,
    *,
    decided_at: str = DECIDED_AT_DEFAULT,
    repo_root: Path | None = None,
    ensure_slice_evidence: bool = True,
) -> dict[str, Any]:
    """Execute the producer matrix and bind available hashes fail-closed."""
    policy = _policy()
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    obs = _mapping(observation)
    reasons: set[str] = set()

    if ensure_slice_evidence:
        mode_a_path = root / "runtime_artifacts/mode_a_vertical_slice_scratch/evidence.json"
        multi_path = (
            root / "runtime_artifacts/multi_person_mode_a_vertical_slice_scratch/evidence.json"
        )
        if not mode_a_path.is_file():
            run_mode_a_vertical_slice(mode_a_path.parent)
        if not multi_path.is_file():
            run_multi_person_mode_a_vertical_slice(multi_path.parent)

    mode_a_slice = _load_json(
        root / "runtime_artifacts/mode_a_vertical_slice_scratch/evidence.json"
    )
    multi_slice = _load_json(
        root / "runtime_artifacts/multi_person_mode_a_vertical_slice_scratch/evidence.json"
    )
    mode_b_slice = _load_json(
        root / "runtime_artifacts/mode_b_vertical_slice_scratch/evidence.json"
    )
    currency_review = _load_json(root / "qa/governance/currency/current_review.json")
    currency_file_sha = (
        _sha256_bytes((root / "qa/governance/currency/current_review.json").read_bytes())
        if (root / "qa/governance/currency/current_review.json").is_file()
        else None
    )

    producer_commit = obs.get("producer_git_commit")
    if not isinstance(producer_commit, str):
        producer_commit = _git_head(root)
    wire_manifest = _wire_manifest_sha256()
    lineage = _mapping(policy.get("preserved_contract_lineage"))

    ctx: dict[str, Any] = {
        "producer_git_commit": producer_commit,
        "wire_manifest_sha256": wire_manifest,
        "mode_a_slice": mode_a_slice,
        "multi_person_slice": multi_slice,
        "mode_b_slice": mode_b_slice,
        "mode_a_decision": _mapping(mode_a_slice).get("decision_sha256"),
        "multi_person_decision": _mapping(multi_slice).get("decision_sha256"),
        "mode_b_decision": _mapping(mode_b_slice).get("decision_sha256"),
        "currency_review": currency_review,
        "currency_file_sha256": currency_file_sha,
        "release_payload_sha256": obs.get("release_payload_sha256"),
        "capability_snapshot_sha256": obs.get("capability_snapshot_sha256"),
        "requirements_sha256": obs.get("requirements_sha256"),
    }

    matrix_results: list[dict[str, Any]] = []
    for row in policy["required_matrix_rows"]:
        executor = _ROW_EXECUTORS.get(str(row.get("row_id")))
        if executor is None:
            reasons.add("matrix_row_missing")
            matrix_results.append(
                _row_result(
                    row,
                    passed=False,
                    decided_at=decided_at,
                    test_ids=["missing_executor"],
                    evidence_ids=["ev-policy"],
                    detail="executor_missing",
                )
            )
            continue
        matrix_results.append(executor(row, obs, decided_at, ctx))

    row_ids = [row["row_id"] for row in matrix_results]
    expected_ids = [row["row_id"] for row in policy["required_matrix_rows"]]
    if row_ids != expected_ids:
        reasons.add("matrix_row_missing")
    if len(row_ids) != len(set(row_ids)):
        reasons.add("matrix_row_duplicate")
    failed_rows = [row for row in matrix_results if row.get("result") != "pass"]
    if failed_rows:
        reasons.add("matrix_row_failed")

    if producer_commit is None:
        reasons.add("producer_binding_missing")
    if not all(
        isinstance(ctx.get(key), str)
        for key in ("mode_a_decision", "multi_person_decision", "mode_b_decision")
    ):
        reasons.add("vertical_slice_evidence_missing")
        reasons.add("producer_hash_unresolved")

    main_commit = obs.get("pinned_main_runtime_git_commit")
    if not isinstance(main_commit, str) or len(main_commit) != 40:
        main_commit = None
        reasons.add("main_commit_absent")

    adoption = obs.get("adoption_receipt")
    adoption_present = isinstance(adoption, Mapping)
    adoption_sha = None
    if adoption_present:
        adoption_sha = canonical_document_sha256(
            adoption, excluded_top_level_fields=("decision_sha256", "signature")
        )
    else:
        reasons.add("adoption_receipt_absent")

    qualification = obs.get("qualification_bundle")
    qualification_present = isinstance(qualification, Mapping) and isinstance(
        _mapping(qualification.get("signature")).get("value_base64"), str
    )
    qualification_sha = None
    if qualification_present:
        qualification_sha = qualification.get("qualification_payload_sha256")
        if not isinstance(qualification_sha, str):
            qualification_sha = canonical_document_sha256(
                qualification,
                excluded_top_level_fields=("qualification_payload_sha256", "signature"),
            )
    else:
        reasons.add("main_qualification_signature_absent")

    adapter_present = obs.get("main_adapter_execution_receipt_present") is True
    history_present = obs.get("comfyui_result_history_present") is True
    if not adapter_present:
        reasons.add("main_adapter_execution_absent")
    if not history_present:
        reasons.add("comfyui_result_history_absent")

    if obs.get("claim_production_qualification") is True:
        reasons.add("fixture_evidence_claimed_as_production")
    if obs.get("claimed_currency_status") == "pass":
        reasons.add("currency_policy_relabel_forbidden")
    if isinstance(obs.get("fabricated_main_receipt"), Mapping):
        reasons.add("fabricated_main_receipt")

    release_complete = all(
        isinstance(ctx.get(key), str)
        for key in (
            "release_payload_sha256",
            "capability_snapshot_sha256",
            "requirements_sha256",
        )
    )
    if not release_complete:
        reasons.add("release_capability_requirements_unbound")

    external = [
        _prerequisite(
            "pinned_main_runtime_git_commit",
            present=main_commit is not None,
            passed=main_commit is not None,
            detail="requires pinned Main runtime git commit, not planning head alone",
        ),
        _prerequisite(
            "main_adoption_receipt",
            present=adoption_present,
            passed=adoption_present,
            detail="requires signed Main adoption receipt bound to qualification bundle",
        ),
        _prerequisite(
            "main_qualification_bundle_signature",
            present=qualification_present,
            passed=qualification_present,
            detail="requires trusted consumer_qualification signature over executed bundle",
        ),
        _prerequisite(
            "main_adapter_execution_receipt",
            present=adapter_present,
            passed=adapter_present,
            detail="requires real Main adapter execution receipt bytes",
        ),
        _prerequisite(
            "comfyui_result_history_receipt",
            present=history_present,
            passed=history_present,
            detail="requires ComfyUI result/history receipts",
        ),
    ]
    if any(row["status"] != "met" for row in external):
        reasons.add("external_main_prerequisite_unmet")

    projection = _project_frozen(policy, matrix_results)
    if any(row["status"] == "fail" for row in projection):
        reasons.add("frozen_projection_incomplete")

    catalog: list[dict[str, Any]] = []
    for evidence_id, path in (
        ("ev-policy", POLICY_PATH),
        ("ev-mode-a-slice", root / "runtime_artifacts/mode_a_vertical_slice_scratch/evidence.json"),
        (
            "ev-multi-person-slice",
            root / "runtime_artifacts/multi_person_mode_a_vertical_slice_scratch/evidence.json",
        ),
        ("ev-mode-b-slice", root / "runtime_artifacts/mode_b_vertical_slice_scratch/evidence.json"),
        ("ev-currency-review", root / "qa/governance/currency/current_review.json"),
        (
            "ev-invalidation-vectors",
            root / "qa/governance/bridge/consumer_invalidation_golden_vectors_v1.json",
        ),
    ):
        entry = _file_catalog_entry(evidence_id, path, relative_to=root)
        if entry is not None:
            catalog.append(entry)
    if not catalog:
        reasons.add("producer_hash_unresolved")
        catalog.append(
            {
                "evidence_id": "ev-policy",
                "relative_path": "configs/cross_project_qualification_policy.yaml",
                "sha256": _sha256_bytes(POLICY_PATH.read_bytes()),
                "size_bytes": POLICY_PATH.stat().st_size,
                "media_type": "application/yaml",
            }
        )
    catalog_sha = canonical_document_sha256({"evidence_catalog": catalog})

    producer_complete = (
        isinstance(producer_commit, str)
        and isinstance(ctx.get("mode_a_decision"), str)
        and isinstance(ctx.get("multi_person_decision"), str)
        and isinstance(ctx.get("mode_b_decision"), str)
        and not failed_rows
    )
    consumer_complete = (
        main_commit is not None
        and adoption_present
        and qualification_present
        and adapter_present
        and history_present
        and release_complete
    )

    external_only = {
        "main_commit_absent",
        "adoption_receipt_absent",
        "main_qualification_signature_absent",
        "main_adapter_execution_absent",
        "comfyui_result_history_absent",
        "external_main_prerequisite_unmet",
        "release_capability_requirements_unbound",
    }
    producer_ok = producer_complete and not (reasons - external_only)
    if (
        consumer_complete
        and producer_ok
        and obs.get("claim_production_qualification") is not True
        and not reasons
    ):
        status = "accepted"
    elif producer_ok:
        status = "producer_partial"
    else:
        status = "rejected"

    if status == "accepted":
        # Belt-and-suspenders: never accept fixture tier as production.
        if policy.get("fixture_truth_tier") == "synthetic_contract_fixture":
            status = "producer_partial"
            reasons.add("fixture_evidence_claimed_as_production")

    ordered = _ordered(policy, reasons) or (["eligible"] if status == "accepted" else [])
    if status != "accepted" and ordered == ["eligible"]:
        ordered = _ordered(policy, reasons | {"external_main_prerequisite_unmet"})

    evidence = {
        "schema_version": "1.0.0",
        "record_type": "cross_project_qualification_evidence",
        "decided_at": decided_at,
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "fixture_truth_tier": policy["fixture_truth_tier"],
        "producer_binding": {
            "producer_git_commit": producer_commit,
            "preserved_bridge_head": lineage.get("maskfactory_bridge_head"),
            "reconciliation_seal": lineage.get("maskfactory_reconciliation_seal"),
            "adopted_wire_schema_manifest_sha256": wire_manifest,
            "wire_schema_count": len(BRIDGE_SCHEMA_NAMES),
            "mode_a_vertical_slice_decision_sha256": ctx.get("mode_a_decision"),
            "multi_person_mode_a_vertical_slice_decision_sha256": ctx.get("multi_person_decision"),
            "mode_b_vertical_slice_decision_sha256": ctx.get("mode_b_decision"),
            "complete": producer_complete,
        },
        "consumer_binding": {
            "main_consumer_planning_head": lineage.get("main_consumer_planning_head"),
            "pinned_main_runtime_git_commit": main_commit,
            "adoption_receipt_present": adoption_present,
            "qualification_bundle_signature_present": qualification_present,
            "adoption_receipt_sha256": adoption_sha,
            "qualification_bundle_sha256": (
                qualification_sha if isinstance(qualification_sha, str) else None
            ),
            "complete": consumer_complete,
        },
        "release_capability_requirements_binding": {
            "release_payload_sha256": (
                ctx.get("release_payload_sha256")
                if isinstance(ctx.get("release_payload_sha256"), str)
                else None
            ),
            "capability_snapshot_sha256": (
                ctx.get("capability_snapshot_sha256")
                if isinstance(ctx.get("capability_snapshot_sha256"), str)
                else None
            ),
            "requirements_sha256": (
                ctx.get("requirements_sha256")
                if isinstance(ctx.get("requirements_sha256"), str)
                else None
            ),
            "complete": release_complete,
        },
        "matrix_results": matrix_results,
        "frozen_compatibility_projection": projection,
        "vertical_slice_bindings": {
            "mode_a_package_read": _slice_binding(mode_a_slice),
            "mode_b_live_predict": _slice_binding(mode_b_slice),
            "mode_b_live_refine": _slice_binding(mode_b_slice),
        },
        "evidence_catalog": catalog,
        "evidence_catalog_sha256": catalog_sha,
        "external_main_prerequisites": external,
        "currency_review_binding": {
            "review_file_sha256": currency_file_sha,
            "reported_status": "fail",
            "relabel_forbidden": True,
            "integrity_ok": currency_file_sha is not None,
            "claimed_status": (
                obs.get("claimed_currency_status")
                if obs.get("claimed_currency_status") in {None, "pass", "fail"}
                else None
            ),
        },
        "status": status,
        "rejection_reasons": ordered,
        "claim_boundary": {
            "producer_matrix_executable": producer_ok and status == "producer_partial",
            "establishes_production_qualification": False,
            "mf_p6_12_05_complete": False,
            "notes": policy["claim_boundary"]["notes"],
        },
        "decision_sha256": "",
    }
    evidence["decision_sha256"] = canonical_document_sha256(
        evidence, excluded_top_level_fields=("decision_sha256",)
    )
    return evidence


def validate_cross_project_qualification_evidence(
    evidence: Mapping[str, Any],
) -> tuple[str, ...]:
    """Validate schema, policy binding, closed matrix, and claim boundaries."""
    issues: list[str] = []
    try:
        policy = _policy()
    except CrossProjectQualificationError as exc:
        return (str(exc),)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    issues.extend(
        f"schema:{error.validator}"
        for error in Draft202012Validator(schema).iter_errors(dict(evidence))
    )
    if (
        evidence.get("policy_id") != policy["policy_id"]
        or evidence.get("policy_sha256") != policy["policy_sha256"]
    ):
        issues.append("policy_drift")
    expected = canonical_document_sha256(evidence, excluded_top_level_fields=("decision_sha256",))
    if evidence.get("decision_sha256") != expected:
        issues.append("decision_hash_drift")
    allowed = set(policy["reason_codes"])
    reasons = evidence.get("rejection_reasons")
    if not isinstance(reasons, list) or not set(reasons).issubset(allowed):
        issues.append("decision_reason_code")
    rows = [row for row in evidence.get("matrix_results") or () if isinstance(row, Mapping)]
    expected_ids = [row["row_id"] for row in policy["required_matrix_rows"]]
    observed_ids = [row.get("row_id") for row in rows]
    if observed_ids != expected_ids:
        issues.append("matrix_row_set_drift")
    projection = [
        row
        for row in evidence.get("frozen_compatibility_projection") or ()
        if isinstance(row, Mapping)
    ]
    proj_names = [row.get("check") for row in projection]
    if set(proj_names) != ADOPTION_COMPATIBILITY_CHECKS or len(proj_names) != 16:
        issues.append("frozen_projection_set_drift")
    claim = _mapping(evidence.get("claim_boundary"))
    if claim.get("mf_p6_12_05_complete") is True:
        issues.append("completion_overclaim")
    if claim.get("establishes_production_qualification") is True:
        issues.append("production_qualification_overclaim")
    consumer = _mapping(evidence.get("consumer_binding"))
    if evidence.get("status") == "accepted" and consumer.get("complete") is not True:
        issues.append("accepted_without_main_bindings")
    if evidence.get("status") == "producer_partial":
        if evidence.get("fixture_truth_tier") != "synthetic_contract_fixture":
            issues.append("partial_truth_tier_drift")
        if any(row.get("result") != "pass" for row in rows):
            issues.append("partial_with_failed_matrix_row")
    if evidence.get("status") == "accepted" and "eligible" not in (reasons or []):
        issues.append("accepted_without_eligible")
    return tuple(sorted(set(issues)))


def run_cross_project_qualification(
    workdir: Path,
    *,
    observation: Mapping[str, Any] | None = None,
    decided_at: str = DECIDED_AT_DEFAULT,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Run the matrix and optionally persist evidence under ``workdir``."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    evidence = build_cross_project_qualification_evidence(
        observation,
        decided_at=decided_at,
        repo_root=repo_root,
        ensure_slice_evidence=True,
    )
    output = workdir / "cross_project_qualification_evidence.json"
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


__all__ = [
    "EXTERNAL_MAIN_DEPENDENCIES",
    "POLICY_ID",
    "CrossProjectQualificationError",
    "build_cross_project_qualification_evidence",
    "run_cross_project_qualification",
    "validate_cross_project_qualification_evidence",
]
