"""Synthetic Main consumer runtime (fixture_authority / synthetic_main_consumer).

Produces signed inbox artifacts and related evidence paths for producer verify
loops MF-P6-11.01–11.08 and MF-P6-12.02–12.06. Claim firewall stays honest:
production Main adoption remains false; keys are conformance-only fixture roles.
"""

from __future__ import annotations

import copy
import hashlib
import json
import runpy
from pathlib import Path
from typing import Any, Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from maskfactory.bridge.external_adapter_conformance import (
    build_external_adapter_conformance_evidence,
)
from maskfactory.bridge.failure_control import (
    EXTERNAL_MAIN_DEPENDENCIES as FAILURE_CONTROL_EXTERNAL_MAIN,
)
from maskfactory.bridge.failure_control import (
    build_failure_control_evidence,
    simulate_fault_injection,
    validate_failure_control_evidence,
)
from maskfactory.bridge.journal import (
    EXTERNAL_MAIN_DEPENDENCIES as JOURNAL_EXTERNAL_MAIN,
)
from maskfactory.bridge.journal import (
    append_bridge_journal_event,
    checkpoint_bridge_journal,
    reconstruct_bridge_journal_state,
    validate_bridge_journal_history,
    validate_bridge_journal_reconstruction_evidence,
)
from maskfactory.bridge.main_consumer_conformance import (
    load_adapter_observation_template,
    load_receipt_shape,
    run_main_consumer_conformance_harness,
    validate_main_consumer_conformance_evidence,
)
from maskfactory.bridge.receipt_arbitration_conformance import (
    build_receipt_arbitration_conformance_evidence,
    normalize_and_arbitrate_receipts,
    validate_receipt_arbitration_conformance_evidence,
)
from maskfactory.bridge.recovery import (
    EXTERNAL_MAIN_DEPENDENCIES as RECOVERY_EXTERNAL_MAIN,
)
from maskfactory.bridge.recovery import (
    simulate_kill_at_boundary,
    validate_recovery_evidence,
)
from maskfactory.validation import (
    ADOPTION_COMPATIBILITY_CHECKS,
    ADOPTION_REVALIDATION_TRIGGERS,
    canonical_document_sha256,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
INBOX_RELATIVE = Path("runtime_artifacts/main_consumer_conformance/inbox")
EVIDENCE_RELATIVE = Path("runtime_artifacts/main_consumer_conformance")
AUTHORITY_KIND = "fixture_authority"
CONSUMER_KIND = "synthetic_main_consumer"
SYNTHETIC_MAIN_GIT_COMMIT = hashlib.sha256(
    b"maskfactory.fixture_main.synthetic_main_consumer.v1"
).hexdigest()[:40]
DECIDED_AT_DEFAULT = "2026-07-19T15:00:00Z"
RELEASE_ID = "mfr_20260719_f1c700e00001"
JOURNAL_ID = "fixture-main-journal-v1"
PRODUCER_VERIFY_ITEMS = (
    "MF-P6-11.01",
    "MF-P6-11.02",
    "MF-P6-11.03",
    "MF-P6-11.04",
    "MF-P6-11.05",
    "MF-P6-11.06",
    "MF-P6-11.07",
    "MF-P6-11.08",
    "MF-P6-12.02",
    "MF-P6-12.03",
    "MF-P6-12.04",
    "MF-P6-12.05",
    "MF-P6-12.06",
)


class FixtureMainError(ValueError):
    """Raised when the synthetic Main consumer cannot be materialized."""


def _builder() -> dict[str, Any]:
    path = REPO_ROOT / "tests" / "fixtures" / "mask_bridge_contracts" / "build_contract_fixtures.py"
    return runpy.run_path(str(path))


def _write_json(path: Path, document: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dict(document), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(payload, encoding="utf-8")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _claim_boundary(**extra: Any) -> dict[str, Any]:
    boundary = {
        "authority_kind": AUTHORITY_KIND,
        "consumer_kind": CONSUMER_KIND,
        "synthetic_main_consumer": True,
        "fixture_authority": True,
        "production_main_adoption_complete": False,
        "main_adoption_complete": False,
        "claims_kevin_sgarrett_comfy_ui_main_production_commit": False,
        "trusted_keys_usage_scope": "conformance_only",
        "synthetic_main_git_commit": SYNTHETIC_MAIN_GIT_COMMIT,
    }
    boundary.update(extra)
    return boundary


def _sha_doc(document: Mapping[str, Any], *excluded: str) -> str:
    return canonical_document_sha256(document, excluded_top_level_fields=excluded)


class FixtureMainRuntime:
    """Build and persist synthetic Main-consumer artifacts for producer verify."""

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        decided_at: str = DECIDED_AT_DEFAULT,
    ) -> None:
        self.repo_root = Path(repo_root) if repo_root is not None else REPO_ROOT
        self.decided_at = decided_at
        self._builder = _builder()
        self.trusted_keys: dict[str, Any] = copy.deepcopy(self._builder["TRUSTED_KEYS"])
        self.inbox_root = self.repo_root / INBOX_RELATIVE
        self.evidence_root = self.repo_root / EVIDENCE_RELATIVE

    def claim_boundary(self, **extra: Any) -> dict[str, Any]:
        return _claim_boundary(**extra)

    def build_adapter_observation(self) -> dict[str, Any]:
        template = load_adapter_observation_template("adapter_observation_accepted_v1")
        observation = copy.deepcopy(template["observation"])
        identity = observation["adapter_identity"]
        identity["git_commit"] = SYNTHETIC_MAIN_GIT_COMMIT
        identity["git_tree"] = hashlib.sha256(
            b"maskfactory.fixture_main.adapter_tree.v1"
        ).hexdigest()
        identity["package_name"] = "comfy-main-maskfactory-adapter-fixture"
        identity["package_version"] = "1.0.0"
        identity["package_sha256"] = hashlib.sha256(
            b"maskfactory.fixture_main.adapter_package.v1"
        ).hexdigest()
        identity["install_mode"] = "wheel"
        identity["repository_clean"] = True
        observation["producer_state"] = {
            "release_status": "published",
            "adoption_decision": "adopted",
            "repository_clean": True,
        }
        return observation

    def build_adoption_receipt(self) -> dict[str, Any]:
        """Build an adopted-shape receipt signed by the fixture consumer_adoption key.

        Matches the pinned Main-consumer harness shape so the inbox harness can
        accept it, while companion claim_boundary evidence keeps production
        adoption false.
        """
        shape = load_receipt_shape("adopted")
        builder = self._builder
        producer = builder["key_set_fields"]("producer_release")
        consumer = builder["key_set_fields"]("consumer_adoption")
        checks = sorted(shape["required_compatibility_checks"] or ADOPTION_COMPATIBILITY_CHECKS)
        receipt: dict[str, Any] = {
            "schema_version": "1.0.0",
            "record_type": "maskfactory_adoption_receipt",
            "adoption_id": "mfadopt_f1c700e00000000000000001",
            "decided_at": self.decided_at,
            "adoption_scope": shape["adoption_scope"],
            "evidence_context": shape["evidence_context"],
            "fixture_only": shape["fixture_only"],
            "production_use_authorized": shape["production_use_authorized"],
            "consumer": {
                "project": "Comfy_UI_Main",
                "controller_version": "1.0.0",
                "git_commit": SYNTHETIC_MAIN_GIT_COMMIT,
            },
            "release_id": RELEASE_ID,
            "release_payload_sha256": hashlib.sha256(
                b"maskfactory.fixture_main.release_payload.v1"
            ).hexdigest(),
            "capability_snapshot_id": "mfcap_f1c700e00000000000000001",
            "capability_snapshot_sha256": hashlib.sha256(
                b"maskfactory.fixture_main.capability.v1"
            ).hexdigest(),
            "consumer_requirements_id": "mfreq_f1c700e00000000000000001",
            "consumer_requirements_sha256": hashlib.sha256(
                b"maskfactory.fixture_main.requirements.v1"
            ).hexdigest(),
            "qualification_bundle_id": "mfqual_f1c700e00000000000000001",
            "qualification_bundle_sha256": hashlib.sha256(
                b"maskfactory.fixture_main.qualification.v1"
            ).hexdigest(),
            "trust_binding": {
                "producer_key_set_id": producer["key_set_id"],
                "producer_key_set_version": producer["key_set_version"],
                "producer_key_set_sha256": producer["key_set_sha256"],
                "producer_release_key_id": builder["KEY_SPECS"]["producer_release"][1],
                "producer_release_public_key_sha256": hashlib.sha256(
                    builder["public_bytes"]("producer_release")
                ).hexdigest(),
                "consumer_key_set_id": consumer["key_set_id"],
                "consumer_key_set_version": consumer["key_set_version"],
                "consumer_key_set_sha256": consumer["key_set_sha256"],
                "consumer_adoption_key_id": builder["KEY_SPECS"]["consumer_adoption"][1],
                "consumer_adoption_public_key_sha256": hashlib.sha256(
                    builder["public_bytes"]("consumer_adoption")
                ).hexdigest(),
                "rotation_policy_sha256": builder["h"]("fixture-main-rotation-policy"),
                "revocation_policy_sha256": builder["h"]("fixture-main-revocation-policy"),
            },
            "journal_checkpoint": builder["journal_checkpoint"](),
            "decision": "adopted",
            "required_capabilities_satisfied": True,
            "compatibility_checks": [
                {
                    "check": check,
                    "result": "pass",
                    "evidence_sha256": builder["h"](f"fixture-main-check:{check}"),
                }
                for check in checks
            ],
            "capability_decisions": [
                {
                    "capability_id": "mask.package.read",
                    "requirement_class": "required",
                    "decision": "accepted",
                    "reason": "synthetic_main_consumer fixture acceptance",
                    "evidence_sha256": builder["h"]("fixture-main:mask.package.read"),
                },
                {
                    "capability_id": "mask.live.predict",
                    "requirement_class": "optional",
                    "decision": "accepted",
                    "reason": "synthetic_main_consumer fixture acceptance",
                    "evidence_sha256": builder["h"]("fixture-main:mask.live.predict"),
                },
            ],
            "pinned_artifacts": [
                {
                    "kind": "adapter",
                    "sha256": hashlib.sha256(
                        b"maskfactory.fixture_main.adapter_package.v1"
                    ).hexdigest(),
                }
            ],
            "accepted_capabilities": ["mask.package.read", "mask.live.predict"],
            "rejected_capabilities": [],
            "valid_until": "2026-07-20T15:00:00Z",
            "use_time_recheck_required": True,
            "revalidation_triggers": sorted(ADOPTION_REVALIDATION_TRIGGERS),
            "adoption_payload_sha256": "0" * 64,
        }
        builder["sign"](
            receipt,
            "adoption_payload_sha256",
            "consumer_adoption",
            ("adoption_payload_sha256", "signature"),
        )
        return receipt

    def build_requirements_capability_bundle(self) -> dict[str, Any]:
        builder = self._builder
        requirements = builder["build_consumer_requirements"]()
        builder["sign"](
            requirements,
            "requirements_sha256",
            "consumer_requirements",
            ("requirements_sha256", "signature"),
        )
        offer = {
            "capability_id": "mask.package.read",
            "access_modes": ["mode_a_package_read", "mode_b_live_predict"],
            "labels": ["left_hand", "torso"],
            "artifact_kinds": ["atomic_visible", "protected_qa"],
            "media_scopes": ["still_image"],
            "transform_operations": ["inverse_project"],
            "maximum_person_count": 2,
            "authority_states": ["qa_passed_noncertified", "certified"],
            "truth_tiers": [
                "machine_candidate",
                "qa_passed_machine_candidate",
                "operationally_certified_artifact",
            ],
            "certificate_kinds": ["exact_serving_route_output"],
            "issuer_kinds": ["maskfactory_autonomous"],
            "versions": {
                "api_contracts": ["maskfactory-api/1.0"],
                "package_formats": ["maskfactory-package/1.0"],
                "ontology_versions": ["body_parts_v1"],
                "node_pack_versions": ["1.0.0"],
            },
            "runtime": {
                "maximum_p50_latency_ms": 2000,
                "maximum_p95_latency_ms": 4000,
                "maximum_vram_mb": 8192,
                "maximum_ram_mb": 16384,
                "maximum_output_bytes": 1000000,
                "minimum_concurrency": 1,
            },
            "evidence": [
                {
                    "evidence_id": "certificate",
                    "kind": "authority_certificate",
                    "sha256": "a" * 64,
                },
                {"evidence_id": "benchmark", "kind": "route_benchmark", "sha256": "b" * 64},
            ],
        }
        return {
            "requirements": requirements,
            "offered_capabilities": [offer],
            "trusted_signing_keys": self.trusted_keys,
            # Must fall inside the fixture requirements authentication window.
            "observed_at": "2026-07-17T00:01:00Z",
            "expected_status": "accepted",
            "claim_boundary": self.claim_boundary(artifact="requirements_capability_bundle"),
        }

    def build_circuit_evidence(self, *, state: str = "closed") -> dict[str, Any]:
        body = {
            "route_key": "mode-b/predict",
            "release_id": RELEASE_ID,
            "state": state,
            "failure_threshold": 3,
            "observation_window_ms": 60000,
            "cooldown_ms": 5000,
            "opened_at": self.decided_at if state != "closed" else None,
            "half_open_probe_allowed": state == "half_open",
            "authority_kind": AUTHORITY_KIND,
            "consumer_kind": CONSUMER_KIND,
        }
        body["evidence_sha256"] = _sha_doc(body, "evidence_sha256")
        return body

    def build_retry_evidence(self) -> dict[str, Any]:
        body = {
            "attempt_number": 1,
            "maximum_attempts": 3,
            "retry_only_typed_transient_errors": True,
            "allow_silent_fallback": False,
            "retry_permitted": False,
            "authority_kind": AUTHORITY_KIND,
            "consumer_kind": CONSUMER_KIND,
        }
        body["evidence_sha256"] = _sha_doc(body, "evidence_sha256")
        return body

    def build_scoped_block_evidence(self) -> dict[str, Any]:
        body = {
            "blocked_pass_ids": ["pass_refine"],
            "continuing_pass_ids": ["pass_unrelated"],
            "affected_scope": "dependent_passes_only",
            "contains_fallback_artifact": False,
            "authority_kind": AUTHORITY_KIND,
            "consumer_kind": CONSUMER_KIND,
        }
        body["evidence_sha256"] = _sha_doc(body, "evidence_sha256")
        return body

    def build_failure_control_observation(self) -> dict[str, Any]:
        return {
            "at_time": self.decided_at,
            "request": {
                "request_id": "mfareq_fixture_main_00000001",
                "pass_id": "pass_predict",
                "attempt_number": 1,
                "created_at": "2026-07-19T14:00:00Z",
                "deadline_at": "2026-07-19T16:00:00Z",
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
            },
            "route_requirements": {
                "required_vram_mb": 4096,
                "required_ram_mb": 8192,
                "required_runtime_ms": 5000,
                "observed_queue_ms": 100,
                "required_output_bytes": 1_000_000,
                "selected_device": "cuda",
                "signed_cpu_route_permitted": False,
            },
            "failure": {},
            "main_circuit_evidence": self.build_circuit_evidence(state="closed"),
            # Healthy closed-circuit admission omits retry/scoped-block claims; separate
            # fault-injection evidence below carries explicit Main circuit/DAG markers.
            "main_retry_evidence": {},
            "main_scoped_block_evidence": {},
            "fallback_attempt": {},
            "dag_passes": [
                {"pass_id": "pass_predict", "depends_on": []},
                {"pass_id": "pass_refine", "depends_on": ["pass_predict"]},
                {"pass_id": "pass_unrelated", "depends_on": []},
            ],
            "claim_boundary": self.claim_boundary(artifact="failure_control_observation"),
        }

    def build_fault_injection_evidence(self) -> dict[str, Any]:
        """Typed outage drill with Main circuit/retry/scoped-block evidence."""
        healthy = self.build_failure_control_observation()
        evidence = simulate_fault_injection(
            fault_kind="outage",
            request=healthy["request"],
            route_requirements=healthy["route_requirements"],
            dag_passes=healthy["dag_passes"],
            main_circuit_evidence=self.build_circuit_evidence(state="open"),
            decided_at=self.decided_at,
            at_time=self.decided_at,
        )
        return {
            "evidence": evidence,
            "external_main_dependencies": list(FAILURE_CONTROL_EXTERNAL_MAIN),
            "claim_boundary": self.claim_boundary(artifact="fault_injection_evidence"),
        }

    def build_journal_bundle(self) -> dict[str, Any]:
        private_key = Ed25519PrivateKey.from_private_bytes(
            self._builder["KEY_SPECS"]["producer_journal"][2]
        )
        key_id = self._builder["KEY_SPECS"]["producer_journal"][1]
        trusted = {
            key_id: {
                "public_key_sha256": hashlib.sha256(
                    self._builder["public_bytes"]("producer_journal")
                ).hexdigest(),
                "roles": ["producer_journal"],
                "status": "active",
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_until": "2027-01-01T00:00:00Z",
            }
        }
        entries: tuple[dict[str, Any], ...] = ()
        for index, state in enumerate(
            ("admit", "route", "submit", "reconcile", "result", "decision")
        ):
            body = {
                "phase": state,
                "authority_kind": AUTHORITY_KIND,
                "consumer_kind": CONSUMER_KIND,
            }
            entries, _, _ = append_bridge_journal_event(
                entries,
                journal_id=JOURNAL_ID,
                state=state,
                idempotency_key=f"fixture-main-{state}-001",
                event_body=body,
                occurred_at=f"2026-07-19T14:0{index}:00Z",
                private_key=private_key,
                signing_key_id=key_id,
            )
        checkpoint = checkpoint_bridge_journal(
            entries,
            journal_id=JOURNAL_ID,
            checkpoint_id="fixture-main-ckpt-001",
            created_at="2026-07-19T14:10:00Z",
            private_key=private_key,
            signing_key_id=key_id,
        )
        history_issues = validate_bridge_journal_history(
            entries, checkpoints=(checkpoint,), trusted_signing_keys=trusted
        )
        reconstruction = reconstruct_bridge_journal_state(
            entries,
            checkpoints=(checkpoint,),
            trusted_signing_keys=trusted,
            decided_at=self.decided_at,
            main_prerequisites_satisfied=list(JOURNAL_EXTERNAL_MAIN),
        )
        return {
            "journal_id": JOURNAL_ID,
            "entries": list(entries),
            "checkpoint": checkpoint,
            "trusted_signing_keys": trusted,
            "history_valid": history_issues == (),
            "history_issues": list(history_issues),
            "reconstruction": reconstruction,
            "main_prerequisites_satisfied": list(JOURNAL_EXTERNAL_MAIN),
            "claim_boundary": self.claim_boundary(artifact="journal_bundle"),
        }

    def build_restart_recovery_marker(self) -> dict[str, Any]:
        evidence = simulate_kill_at_boundary(
            kill_boundary="submitted_unknown",
            request_id="mfareq_fixture_main_restart_0001",
            decided_at=self.decided_at,
        )
        return {
            "kill_boundary": "submitted_unknown",
            "recovery_evidence": evidence,
            "external_main_dependencies": list(RECOVERY_EXTERNAL_MAIN),
            "restart_store_marker": {
                "marker_id": "fixture-main-restart-store-v1",
                "authority_kind": AUTHORITY_KIND,
                "consumer_kind": CONSUMER_KIND,
                "unknown_outcome_reconciler": "fixture_not_found",
                "marker_sha256": "",
            },
            "claim_boundary": self.claim_boundary(artifact="restart_recovery_marker"),
        }

    def build_comfyui_result_history_receipt(self) -> dict[str, Any]:
        workflow_sha = hashlib.sha256(b"maskfactory.fixture_main.intended_inpaint.v1").hexdigest()
        result_bytes = b"fixture-main-comfyui-result-v1"
        history_bytes = b"fixture-main-comfyui-history-v1"
        receipt = {
            "schema_version": "1.0.0",
            "record_type": "fixture_main_comfyui_result_history_receipt",
            "authority_kind": AUTHORITY_KIND,
            "consumer_kind": CONSUMER_KIND,
            "decided_at": self.decided_at,
            "operation": "comfyui_inpaint_edit",
            "synthetic_main_git_commit": SYNTHETIC_MAIN_GIT_COMMIT,
            "workflow_sha256": workflow_sha,
            "result_sha256": hashlib.sha256(result_bytes).hexdigest(),
            "history_sha256": hashlib.sha256(history_bytes).hexdigest(),
            "adapter_execution_receipt": {
                "receipt_id": "fixture-main-adapter-exec-0001",
                "adapter_package_sha256": hashlib.sha256(
                    b"maskfactory.fixture_main.adapter_package.v1"
                ).hexdigest(),
                "execution_sha256": hashlib.sha256(
                    b"maskfactory.fixture_main.adapter_execution.v1"
                ).hexdigest(),
                "status": "succeeded",
            },
            "person_bindings": [
                {
                    "person_index": 0,
                    "character_id": "character-fixture",
                    "mask_encoded_sha256": "c" * 64,
                },
                {
                    "person_index": 1,
                    "character_id": "character-fixture-002",
                    "mask_encoded_sha256": "d" * 64,
                },
            ],
            "claim_boundary": self.claim_boundary(
                artifact="comfyui_result_history_receipt",
                production_comfyui_execution_complete=False,
                closed_fixture_execution_complete=True,
            ),
            "receipt_sha256": "",
        }
        receipt["receipt_sha256"] = _sha_doc(receipt, "receipt_sha256")
        return receipt

    def build_arbitration_bundle(self) -> dict[str, Any]:
        release = "ffbef9cea69a8bbe7c51bf464d127c0d3ffbc9cdc24798d5ccb8eb1b969f215a"
        capability = "0515eaeff6a2242c1877d7ae7bce072736a8cebddb249bf28b25e119857fd230"
        revocation = "4" * 64
        source = "3" * 64
        transform = "361555fb909a4648d3c4efc6e65458d9f4e50c7bd711b7aabc4495c1b09fae1f"

        def _region(region_id: str, *, authority_state: str = "certified") -> dict[str, Any]:
            certified = authority_state == "certified"
            return {
                "region_id": region_id,
                "artifact_identity_sha256": "a" * 64,
                "encoded_sha256": "b" * 64,
                "decoded_mask_sha256": "c" * 64,
                "source_decoded_pixel_sha256": source,
                "artifact_type": "atomic",
                "owner_identity_sha256": "d" * 64,
                "coordinate_space": "output_pixel",
                "width": 512,
                "height": 512,
                "transform_chain_sha256": transform,
                "transform_step_sequence": 0,
                "required_minimum_authority_state": authority_state,
                "authority_state": authority_state,
                "issuer_kind": "maskfactory_autonomous",
                "certificate_kind": ("exact_serving_route_output" if certified else "none"),
                "certificate_id": ("mfac_aaaaaaaaaaaaaaaaaaaaaaaa" if certified else None),
                "certificate_sha256": "e" * 64 if certified else None,
                "certificate_scope_sha256": "f" * 64 if certified else None,
                "certificate_status": "active" if certified else "none",
                "certificate_exact_scope_match": certified,
                "revocation_checked_at": self.decided_at if certified else None,
                "revocation_checkpoint_sha256": revocation if certified else None,
            }

        def _receipt(
            *,
            access_mode: str,
            authority_state: str,
            receipt_suffix: str,
        ) -> dict[str, Any]:
            certified = authority_state == "certified"
            receipt = {
                "schema_version": "1.0.0",
                "record_type": "mask_acquisition_receipt",
                "receipt_id": f"mfarec_{receipt_suffix}",
                "request_id": f"mfareq_{receipt_suffix}",
                "request_payload_sha256": "1" * 64,
                "project_id": "comfy-main-fixture",
                "run_id": "run-fixture-main",
                "job_id": "job-fixture-main",
                "pass_id": "pass-mask-fixture",
                "attempt_id": "attempt-1",
                "result": "succeeded",
                "access_mode": access_mode,
                "completed_at": self.decided_at,
                "media_scope": {
                    "scope_kind": "still_image",
                    "sequence_id": "sequence-fixture",
                    "shot_id": "shot-fixture",
                    "take_id": "take-fixture",
                    "source_video_sha256": None,
                    "decoded_frame_sha256": None,
                    "frame_index": None,
                },
                "release_binding": {
                    "release_payload_sha256": release,
                    "capability_snapshot_sha256": capability,
                },
                "source_binding": {"decoded_pixel_sha256": source},
                "authority": {
                    "authority_state": authority_state,
                    "certificate_status": "active" if certified else "none",
                    "certificate_exact_scope_match": certified,
                    "package_certificate_active": True,
                },
                "qa": {"status": "pass"},
                "cost": {"total_ms": 4000, "peak_vram_mb": 2048},
                "uncertainty": 0.01,
                "preservation_risk": 0.1,
                "regions": [_region("region-0", authority_state=authority_state)],
                "artifacts": [
                    {
                        "intent_id": "intent-left_hand",
                        "label": "left_hand",
                        "artifact_kind": "atomic_visible",
                        "mask_type": "part",
                        "coordinate_space": "output_pixel",
                        "decoded_mask_sha256": "c" * 64,
                    }
                ],
                "receipt_payload_sha256": "0" * 64,
            }
            receipt["receipt_payload_sha256"] = _sha_doc(
                receipt, "receipt_payload_sha256", "signature"
            )
            return receipt

        candidates = [
            {
                "candidate_id": "mode-a-certified",
                "receipt": _receipt(
                    access_mode="mode_a_package_read",
                    authority_state="certified",
                    receipt_suffix="aaaaaaaaaaaaaaaaaaaaaaaa",
                ),
            },
            {
                "candidate_id": "mode-b-draft",
                "receipt": _receipt(
                    access_mode="mode_b_live_predict",
                    authority_state="draft",
                    receipt_suffix="bbbbbbbbbbbbbbbbbbbbbbbb",
                ),
            },
        ]
        heads = {
            "release_payload_sha256": release,
            "capability_snapshot_sha256": capability,
            "revocation_index_sha256": revocation,
            "ontology_version": "body_parts_v1",
            "required_authority_floor": "draft",
            "required_qa_status": "pass",
            "max_preservation_risk": 0.5,
            "max_total_ms": 60000,
            "max_peak_vram_mb": 24576,
            "max_uncertainty": 0.2,
        }
        arbitration = normalize_and_arbitrate_receipts(
            candidates, decided_at=self.decided_at, producer_heads=heads
        )
        decision_body = {
            "outcome": arbitration["oracle_decision"]["outcome"],
            "selected_candidate_ids": list(
                arbitration["oracle_decision"]["selected_candidate_ids"]
            ),
            "comparable_scope_sha256": arbitration["comparable_scope_sha256"],
            "receipt_payload_sha256s": sorted(
                row["receipt_payload_sha256"] for row in arbitration["evaluated"]
            ),
            "policy_sha256": arbitration["policy_sha256"],
            "authority_kind": AUTHORITY_KIND,
            "consumer_kind": CONSUMER_KIND,
            "decision_payload_sha256": "0" * 64,
        }
        self._builder["sign"](
            decision_body,
            "decision_payload_sha256",
            "consumer_adoption",
            ("decision_payload_sha256", "signature"),
        )
        # Arbitration evidence only requires signature shape fields; keep fixture key_id.
        main_decision = {
            "outcome": decision_body["outcome"],
            "selected_candidate_ids": decision_body["selected_candidate_ids"],
            "comparable_scope_sha256": decision_body["comparable_scope_sha256"],
            "receipt_payload_sha256s": decision_body["receipt_payload_sha256s"],
            "policy_sha256": decision_body["policy_sha256"],
            "signature": decision_body["signature"],
            "claim_boundary": self.claim_boundary(artifact="arbitration_decision"),
        }
        evidence = build_receipt_arbitration_conformance_evidence(
            candidates, main_decision, decided_at=self.decided_at, producer_heads=heads
        )
        return {
            "candidates": candidates,
            "producer_heads": heads,
            "main_decision": main_decision,
            "evidence": evidence,
            "claim_boundary": self.claim_boundary(artifact="arbitration_bundle"),
        }

    def materialize(self) -> dict[str, Any]:
        """Write inbox + related evidence paths; return path/hash index."""
        receipt = self.build_adoption_receipt()
        observation = self.build_adapter_observation()
        bundle = self.build_requirements_capability_bundle()
        arbitration = self.build_arbitration_bundle()
        journal = self.build_journal_bundle()
        failure = self.build_failure_control_observation()
        fault = self.build_fault_injection_evidence()
        recovery = self.build_restart_recovery_marker()
        # Fill restart marker hash after body is complete.
        marker = recovery["restart_store_marker"]
        marker["marker_sha256"] = _sha_doc(marker, "marker_sha256")
        comfyui = self.build_comfyui_result_history_receipt()

        paths: dict[str, dict[str, str]] = {}
        inbox = self.inbox_root
        paths["adoption_receipt"] = {
            "path": str(inbox / "adoption_receipt.json"),
            "sha256": _write_json(inbox / "adoption_receipt.json", receipt),
        }
        paths["adapter_observation"] = {
            "path": str(inbox / "adapter_observation.json"),
            "sha256": _write_json(inbox / "adapter_observation.json", observation),
        }
        paths["requirements_capability_bundle"] = {
            "path": str(inbox / "requirements_capability_bundle.json"),
            "sha256": _write_json(inbox / "requirements_capability_bundle.json", bundle),
        }

        related = self.evidence_root
        paths["claim_boundary"] = {
            "path": str(related / "fixture_main_claim_boundary.json"),
            "sha256": _write_json(
                related / "fixture_main_claim_boundary.json",
                self.claim_boundary(pack="fixture_main_v1"),
            ),
        }
        paths["arbitration_decision"] = {
            "path": str(related / "arbitration" / "main_decision.json"),
            "sha256": _write_json(
                related / "arbitration" / "main_decision.json", arbitration["main_decision"]
            ),
        }
        paths["arbitration_evidence"] = {
            "path": str(related / "arbitration" / "conformance_evidence.json"),
            "sha256": _write_json(
                related / "arbitration" / "conformance_evidence.json", arbitration["evidence"]
            ),
        }
        paths["journal_bundle"] = {
            "path": str(related / "journal" / "checkpoint_bundle.json"),
            "sha256": _write_json(related / "journal" / "checkpoint_bundle.json", journal),
        }
        paths["failure_control_observation"] = {
            "path": str(related / "failure_control" / "observation.json"),
            "sha256": _write_json(related / "failure_control" / "observation.json", failure),
        }
        paths["fault_injection_evidence"] = {
            "path": str(related / "failure_control" / "fault_injection_evidence.json"),
            "sha256": _write_json(
                related / "failure_control" / "fault_injection_evidence.json", fault
            ),
        }
        paths["restart_recovery_marker"] = {
            "path": str(related / "recovery" / "restart_marker.json"),
            "sha256": _write_json(related / "recovery" / "restart_marker.json", recovery),
        }
        paths["comfyui_result_history"] = {
            "path": str(related / "comfyui" / "result_history_receipt.json"),
            "sha256": _write_json(related / "comfyui" / "result_history_receipt.json", comfyui),
        }

        index = {
            "schema_version": "1.0.0",
            "record_type": "fixture_main_materialization_index",
            "authority_kind": AUTHORITY_KIND,
            "consumer_kind": CONSUMER_KIND,
            "decided_at": self.decided_at,
            "synthetic_main_git_commit": SYNTHETIC_MAIN_GIT_COMMIT,
            "paths": paths,
            "claim_boundary": self.claim_boundary(artifact="materialization_index"),
            "index_sha256": "",
        }
        index["index_sha256"] = _sha_doc(index, "index_sha256")
        paths["materialization_index"] = {
            "path": str(related / "fixture_main_materialization_index.json"),
            "sha256": _write_json(related / "fixture_main_materialization_index.json", index),
        }
        return index

    def run_producer_verify(self) -> dict[str, Any]:
        """Materialize artifacts and exercise producer verify surfaces against them."""
        index = self.materialize()
        harness = run_main_consumer_conformance_harness(
            decided_at=self.decided_at, main_artifact_root=self.inbox_root
        )
        harness_issues = validate_main_consumer_conformance_evidence(harness)

        observation = json.loads(
            (self.inbox_root / "adapter_observation.json").read_text(encoding="utf-8")
        )
        adapter = build_external_adapter_conformance_evidence(
            observation, decided_at=self.decided_at
        )

        arbitration_path = self.evidence_root / "arbitration" / "conformance_evidence.json"
        arbitration_evidence = json.loads(arbitration_path.read_text(encoding="utf-8"))
        arbitration_issues = validate_receipt_arbitration_conformance_evidence(arbitration_evidence)

        journal = json.loads(
            (self.evidence_root / "journal" / "checkpoint_bundle.json").read_text(encoding="utf-8")
        )
        reconstruction = journal["reconstruction"]
        reconstruction_issues = validate_bridge_journal_reconstruction_evidence(reconstruction)

        failure_obs = json.loads(
            (self.evidence_root / "failure_control" / "observation.json").read_text(
                encoding="utf-8"
            )
        )
        failure_evidence = build_failure_control_evidence(failure_obs, decided_at=self.decided_at)
        failure_issues = validate_failure_control_evidence(failure_evidence)
        fault_doc = json.loads(
            (self.evidence_root / "failure_control" / "fault_injection_evidence.json").read_text(
                encoding="utf-8"
            )
        )
        fault_evidence = fault_doc["evidence"]
        fault_issues = validate_failure_control_evidence(fault_evidence)

        recovery = json.loads(
            (self.evidence_root / "recovery" / "restart_marker.json").read_text(encoding="utf-8")
        )
        recovery_evidence = recovery["recovery_evidence"]
        recovery_issues = validate_recovery_evidence(recovery_evidence)

        comfyui = json.loads(
            (self.evidence_root / "comfyui" / "result_history_receipt.json").read_text(
                encoding="utf-8"
            )
        )

        loops = {
            "MF-P6-11.01": {
                "surface": "external_adapter_conformance",
                "passed": adapter.get("status") == "accepted",
                "detail": f"adapter_status={adapter.get('status')}",
            },
            "MF-P6-11.02": {
                "surface": "mode_a_package_read_via_adopted_inbox",
                "passed": harness.get("status") == "accepted"
                and harness.get("main_adoption_complete") is False,
                "detail": "inbox adoption+adapter accepted without production adoption claim",
            },
            "MF-P6-11.03": {
                "surface": "mode_b_capability_offer_bundle",
                "passed": harness.get("status") == "accepted",
                "detail": "requirements/capability bundle present and harness-accepted",
            },
            "MF-P6-11.04": {
                "surface": "receipt_arbitration_main_decision",
                "passed": arbitration_evidence.get("status") == "accepted"
                and arbitration_issues == (),
                "detail": f"arbitration_status={arbitration_evidence.get('status')}",
            },
            "MF-P6-11.05": {
                "surface": "consumer_feedback_fixture_key",
                "passed": "comfy-main-feedback-fixture" in self.trusted_keys,
                "detail": "trusted consumer_feedback fixture key available for intake",
            },
            "MF-P6-11.06": {
                "surface": "journal_checkpoint_and_reconstruction",
                "passed": (
                    journal.get("history_valid") is True
                    and reconstruction.get("status") == "reconstructed"
                    and set(reconstruction.get("external_main_prerequisites", {}).get("unmet", ()))
                    == set()
                    and reconstruction_issues == ()
                ),
                "detail": (
                    f"history_valid={journal.get('history_valid')};"
                    f"reconstruction={reconstruction.get('status')};"
                    f"unmet={reconstruction.get('external_main_prerequisites', {}).get('unmet')}"
                ),
            },
            "MF-P6-11.07": {
                "surface": "failure_control_circuit_dag",
                "passed": (
                    failure_evidence.get("status") == "accepted"
                    and failure_issues == ()
                    and fault_evidence.get("status") == "accepted"
                    and fault_issues == ()
                    and fault_evidence.get("scoped_dag", {}).get("scope_exact") is True
                ),
                "detail": (
                    f"healthy={failure_evidence.get('status')};"
                    f"fault={fault_evidence.get('status')};"
                    f"deps={list(FAILURE_CONTROL_EXTERNAL_MAIN)}"
                ),
            },
            "MF-P6-11.08": {
                "surface": "restart_recovery_marker",
                "passed": recovery_evidence.get("status") == "accepted" and recovery_issues == (),
                "detail": f"recovery_status={recovery_evidence.get('status')}",
            },
            "MF-P6-12.02": {
                "surface": "comfyui_result_history_fixture_receipt",
                "passed": (
                    isinstance(comfyui.get("result_sha256"), str)
                    and isinstance(comfyui.get("history_sha256"), str)
                    and comfyui.get("authority_kind") == AUTHORITY_KIND
                ),
                "detail": "hash-bound synthetic ComfyUI result/history receipt present",
            },
            "MF-P6-12.03": {
                "surface": "multi_person_comfyui_bindings",
                "passed": len(comfyui.get("person_bindings") or ()) >= 2,
                "detail": "duo person bindings present on fixture ComfyUI receipt",
            },
            "MF-P6-12.04": {
                "surface": "mode_b_offer_and_circuit_closed",
                "passed": harness.get("status") == "accepted"
                and failure_evidence.get("status") == "accepted"
                and fault_evidence.get("status") == "accepted",
                "detail": "Mode B offer bundle + closed/open circuit evidence accepted",
            },
            "MF-P6-12.05": {
                "surface": "pinned_cross_project_adoption_evidence",
                "passed": harness.get("status") == "accepted"
                and harness.get("main_artifacts_present") is True,
                "detail": "pinned inbox adoption/observation/bundle present for qualification bind",
            },
            "MF-P6-12.06": {
                "surface": "handoff_ready_fixture_pack",
                "passed": (
                    harness.get("status") == "accepted"
                    and harness.get("main_adoption_complete") is False
                    and index.get("authority_kind") == AUTHORITY_KIND
                ),
                "detail": "fixture pack ready for handoff evaluator; production close still gated",
            },
        }

        all_passed = all(row["passed"] for row in loops.values())
        evidence = {
            "schema_version": "1.0.0",
            "record_type": "fixture_main_producer_verify_evidence",
            "authority_kind": AUTHORITY_KIND,
            "consumer_kind": CONSUMER_KIND,
            "decided_at": self.decided_at,
            "synthetic_main_git_commit": SYNTHETIC_MAIN_GIT_COMMIT,
            "status": "accepted" if all_passed else "rejected",
            "producer_verify_items": list(PRODUCER_VERIFY_ITEMS),
            "loops": loops,
            "harness": {
                "status": harness.get("status"),
                "main_artifacts_present": harness.get("main_artifacts_present"),
                "main_adoption_complete": harness.get("main_adoption_complete"),
                "rejection_reasons": list(harness.get("rejection_reasons") or ()),
                "validation_issues": list(harness_issues),
            },
            "adapter_conformance_status": adapter.get("status"),
            "arbitration_status": arbitration_evidence.get("status"),
            "journal_reconstruction_status": reconstruction.get("status"),
            "failure_control_status": failure_evidence.get("status"),
            "fault_injection_status": fault_evidence.get("status"),
            "recovery_status": recovery_evidence.get("status"),
            "materialization_index_sha256": index.get("index_sha256"),
            "claim_boundary": self.claim_boundary(
                artifact="producer_verify_evidence",
                production_core_close_authorized=False,
                closed_fixture_producer_verify_complete=all_passed,
            ),
            "decision_sha256": "",
        }
        evidence["decision_sha256"] = _sha_doc(evidence, "decision_sha256")
        _write_json(self.evidence_root / "fixture_main_producer_verify_evidence.json", evidence)
        return evidence


def materialize_fixture_main(
    *, repo_root: Path | None = None, decided_at: str = DECIDED_AT_DEFAULT
) -> dict[str, Any]:
    return FixtureMainRuntime(repo_root=repo_root, decided_at=decided_at).materialize()


def run_fixture_main_producer_verify(
    *, repo_root: Path | None = None, decided_at: str = DECIDED_AT_DEFAULT
) -> dict[str, Any]:
    return FixtureMainRuntime(repo_root=repo_root, decided_at=decided_at).run_producer_verify()


__all__ = [
    "AUTHORITY_KIND",
    "CONSUMER_KIND",
    "SYNTHETIC_MAIN_GIT_COMMIT",
    "FixtureMainError",
    "FixtureMainRuntime",
    "materialize_fixture_main",
    "run_fixture_main_producer_verify",
]
