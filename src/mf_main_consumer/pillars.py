"""Real bridge-contract pillars executed by the isolated Main-side consumer.

Every pillar calls the genuine producer machinery published in the ``maskfactory``
package -- no mocks, no re-implementation. Pillars:

  * adapter        -> external-adapter conformance verifier (contracts-only boundary)
  * journal        -> trusted-signed append-only journal + checkpoint + history validation
  * circuit        -> deepened failure-control / no-silent-fallback fault-injection (11.07)
  * mode_a         -> adversarial Mode A immutable package-read matrix (11.02)
  * qualification  -> honest producer_partial + adversarial depth matrix (12.05)
  * firewall       -> final-release core-close firewall depth matrix (12.06)
  * adoption       -> cryptographically real, isolated-consumer-signed attestation

HARD blockers that require the real Comfy_UI_Main runtime stay OPEN.
"""

from __future__ import annotations

import ast
import base64
import copy
import gzip
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from maskfactory.bridge.cross_project_qualification import (
    build_cross_project_qualification_evidence,
    validate_cross_project_qualification_evidence,
)
from maskfactory.bridge.external_adapter_conformance import (
    build_external_adapter_conformance_evidence,
    validate_external_adapter_conformance_evidence,
)
from maskfactory.bridge.failure_control import (
    build_failure_control_evidence,
    simulate_fault_injection,
    validate_failure_control_evidence,
)
from maskfactory.bridge.final_release_handoff import (
    evaluate_final_release_handoff,
    validate_final_release_handoff_evidence,
)
from maskfactory.bridge.journal import (
    append_bridge_journal_event,
    checkpoint_bridge_journal,
    validate_bridge_journal_history,
)
from maskfactory.bridge.mode_a_package_read import (
    evaluate_mode_a_package_read,
    validate_mode_a_package_read_evidence,
)
from maskfactory.bridge.mode_a_vertical_slice import build_fixture_adopted_package
from maskfactory.contracts import (
    ADOPTED_CONTRACT_VERSIONS,
    ADOPTED_OPENAPI_PATHS,
    ADOPTED_WIRE_SCHEMA_VERSIONS,
)
from maskfactory.validation import canonical_document_sha256

from . import adapter as adapter_module
from .producer_bridge import producer_git_head, producer_root

CONSUMER_ROOT = Path(__file__).resolve().parents[2]
PKG_DIR = Path(__file__).resolve().parent
DIST_DIR = CONSUMER_ROOT / "dist"
DECIDED_AT = "2026-07-20T05:00:00Z"
MODE_A_DECIDED_AT = "2026-07-19T14:00:00Z"

HARD_BLOCKERS_REQUIRING_REAL_MAIN: tuple[str, ...] = (
    "MF-P6-11.02",
    "MF-P6-11.07",
    "MF-P6-12.05",
    "MF-P6-12.06",
)


# ---------------------------------------------------------------------------
# Consumer identity helpers
# ---------------------------------------------------------------------------
def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=CONSUMER_ROOT, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    value = out.stdout.strip()
    return value or None


def consumer_git_head() -> str | None:
    value = (_git("rev-parse", "HEAD") or "").lower()
    return value if len(value) == 40 and all(c in "0123456789abcdef" for c in value) else None


def _consumer_git_tree() -> str | None:
    value = (_git("rev-parse", "HEAD^{tree}") or "").lower()
    return value if len(value) == 40 and all(c in "0123456789abcdef" for c in value) else None


def _consumer_source_clean() -> bool:
    """True when the tracked adapter source tree has no uncommitted modifications."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=CONSUMER_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    if out.returncode != 0:
        return False
    tracked_mods = [
        line for line in out.stdout.splitlines() if line and not line.startswith("??")
    ]
    return not tracked_mods


def _adapter_imports() -> tuple[list[str], list[str]]:
    """Parse the adapter module's real imports (AST), returning (all, maskfactory)."""
    tree = ast.parse(Path(adapter_module.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    mf = sorted(n for n in names if n.startswith("maskfactory."))
    return sorted(names), mf


def build_consumer_sdist() -> tuple[Path, str]:
    """Build a deterministic source distribution of the adapter package."""
    files = sorted(PKG_DIR.rglob("*.py"))
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tf:
        for path in files:
            data = path.read_bytes()
            arcname = f"mf_main_consumer/{path.relative_to(PKG_DIR).as_posix()}"
            info = tarfile.TarInfo(arcname)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tf.addfile(info, io.BytesIO(data))
    gz_buf = io.BytesIO()
    with gzip.GzipFile(fileobj=gz_buf, mode="wb", mtime=0) as gz:
        gz.write(tar_buf.getvalue())
    gz_bytes = gz_buf.getvalue()
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    out = DIST_DIR / "comfy-main-maskfactory-consumer-1.0.0.tar.gz"
    out.write_bytes(gz_bytes)
    return out, hashlib.sha256(gz_bytes).hexdigest()


def _isolated_key(role: str) -> tuple[Ed25519PrivateKey, str]:
    seed = hashlib.sha256(
        f"comfy-main-maskfactory-consumer-isolated-v1:{role}".encode()
    ).digest()
    return Ed25519PrivateKey.from_private_bytes(seed), f"isolated-main-consumer-{role}"


# ---------------------------------------------------------------------------
# Pillar 1: adapter conformance
# ---------------------------------------------------------------------------
def run_adapter_conformance() -> dict[str, Any]:
    _, sdist_sha = build_consumer_sdist()
    all_imports, mf_imports = _adapter_imports()
    observation = {
        "adapter_identity": {
            "package_name": "comfy-main-maskfactory-consumer",
            "package_version": "1.0.0",
            "package_sha256": sdist_sha,
            "git_commit": consumer_git_head(),
            "git_tree": _consumer_git_tree(),
            "repository_clean": _consumer_source_clean(),
            "install_mode": "sdist",
        },
        "producer_state": {
            "release_status": "published",
            "adoption_decision": "adopted",
            "repository_clean": True,
        },
        "contract_bindings": {
            "bridge_contract": ADOPTED_CONTRACT_VERSIONS["bridge_contract"],
            "api_contract": ADOPTED_CONTRACT_VERSIONS["api_contract"],
            "package_format": ADOPTED_CONTRACT_VERSIONS["package_format"],
            "ontology_version": ADOPTED_CONTRACT_VERSIONS["ontology_version"],
            "node_pack_version": ADOPTED_CONTRACT_VERSIONS["node_pack_version"],
            "wire_schemas": [
                {"name": name, "version": version}
                for name, version in sorted(ADOPTED_WIRE_SCHEMA_VERSIONS.items())
            ],
            "used_openapi_paths": sorted(ADOPTED_OPENAPI_PATHS),
        },
        "boundary_observations": {
            "imports": all_imports,
            "documented_dependencies": list(adapter_module.DOCUMENTED_DEPENDENCIES),
            "comfyui_node_ids": [],
            "mutable_path_dependencies": [],
        },
    }
    evidence = build_external_adapter_conformance_evidence(observation, decided_at=DECIDED_AT)
    issues = validate_external_adapter_conformance_evidence(evidence)
    return {
        "check": "isolated_adapter_conformance",
        "passed": evidence.get("status") == "accepted" and issues == (),
        "status": evidence.get("status"),
        "rejection_reasons": evidence.get("rejection_reasons"),
        "decision_sha256": evidence.get("decision_sha256"),
        "adapter_maskfactory_imports": mf_imports,
        "validation_issues": list(issues),
    }


# ---------------------------------------------------------------------------
# Pillar 2: trusted-signed append-only journal
# ---------------------------------------------------------------------------
def run_signed_journal() -> dict[str, Any]:
    key, key_id = _isolated_key("journal")
    trusted = {
        key_id: {
            "public_key_sha256": hashlib.sha256(key.public_key().public_bytes_raw()).hexdigest(),
            "roles": ["producer_journal"],
            "status": "active",
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_until": "2027-01-01T00:00:00Z",
        }
    }
    entries: tuple[dict[str, Any], ...] = ()
    for state in ("admit", "route", "submit"):
        entries, _, _ = append_bridge_journal_event(
            entries,
            journal_id="isolated-main-consumer-journal-v1",
            state=state,
            idempotency_key=f"isolated-{state}-001",
            event_body={"isolated_consumer": True, "state": state},
            occurred_at=DECIDED_AT,
            private_key=key,
            signing_key_id=key_id,
        )
    replay_entries, _, replayed = append_bridge_journal_event(
        entries,
        journal_id="isolated-main-consumer-journal-v1",
        state="submit",
        idempotency_key="isolated-submit-001",
        event_body={"isolated_consumer": True, "state": "submit"},
        occurred_at=DECIDED_AT,
        private_key=key,
        signing_key_id=key_id,
    )
    checkpoint = checkpoint_bridge_journal(
        entries,
        journal_id="isolated-main-consumer-journal-v1",
        checkpoint_id="isolated-checkpoint-001",
        created_at=DECIDED_AT,
        private_key=key,
        signing_key_id=key_id,
    )
    issues = validate_bridge_journal_history(
        entries, checkpoints=(checkpoint,), trusted_signing_keys=trusted
    )
    return {
        "check": "isolated_signed_journal",
        "passed": issues == () and len(entries) == 3 and replayed and len(replay_entries) == 3,
        "entry_count": len(entries),
        "replay_idempotent": bool(replayed and len(replay_entries) == 3),
        "checkpoint_sha256": checkpoint.get("checkpoint_sha256"),
        "issues": list(issues),
    }


# ---------------------------------------------------------------------------
# Pillar 3: deepened failure-control / no-silent-fallback (MF-P6-11.07)
# ---------------------------------------------------------------------------
def _fc_circuit(*, state: str = "closed", half_open_probe_allowed: bool = False) -> dict[str, Any]:
    body = {
        "route_key": "mode-b/predict",
        "release_id": "mfrel_sibling_consumer_circuit",
        "state": state,
        "failure_threshold": 3,
        "observation_window_ms": 60000,
        "cooldown_ms": 5000,
        "opened_at": "2026-07-20T04:00:00Z" if state != "closed" else None,
        "half_open_probe_allowed": half_open_probe_allowed,
    }
    body["evidence_sha256"] = canonical_document_sha256(
        body, excluded_top_level_fields=("evidence_sha256",)
    )
    return body


def run_failure_control_circuit() -> dict[str, Any]:
    request = {
        "request_id": "mfareq_sibling_consumer_0001",
        "pass_id": "pass_predict",
        "attempt_number": 1,
        "created_at": "2026-07-20T04:00:00Z",
        "deadline_at": "2026-07-20T06:00:00Z",
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
    route = {
        "required_vram_mb": 4096,
        "required_ram_mb": 8192,
        "required_runtime_ms": 5000,
        "observed_queue_ms": 100,
        "required_output_bytes": 1_000_000,
        "selected_device": "cuda",
        "signed_cpu_route_permitted": False,
    }
    dag = [
        {"pass_id": "pass_predict", "depends_on": []},
        {"pass_id": "pass_refine", "depends_on": ["pass_predict"]},
        {"pass_id": "pass_unrelated", "depends_on": []},
    ]
    expected_blocked = ["pass_predict", "pass_refine"]
    expected_continuing = ["pass_unrelated"]
    faults: list[dict[str, Any]] = []
    for fault in ("outage", "timeout", "oom", "incompatible_authority"):
        evidence = simulate_fault_injection(
            fault_kind=fault,
            request=request,
            route_requirements=route,
            dag_passes=dag,
            decided_at=DECIDED_AT,
        )
        issues = validate_failure_control_evidence(evidence)
        admission = evidence.get("admission") or {}
        scoped = evidence.get("scoped_dag") or {}
        no_fallback = evidence.get("no_silent_fallback") or {}
        faults.append(
            {
                "fault": fault,
                "status": evidence.get("status"),
                "passed": bool(
                    evidence.get("status") == "accepted"
                    and admission.get("provider_invocation_permitted") is False
                    and scoped.get("scope_exact") is True
                    and scoped.get("blocked_pass_ids") == expected_blocked
                    and scoped.get("continuing_pass_ids") == expected_continuing
                    and no_fallback.get("enforced") is True
                    and no_fallback.get("fallback_artifact_present") is False
                    and issues == ()
                ),
            }
        )

    deadline_ev = simulate_fault_injection(
        fault_kind="timeout",
        request=request,
        route_requirements=route,
        dag_passes=dag,
        decided_at=DECIDED_AT,
        at_time="2026-07-20T07:00:00Z",
    )
    deadline_enforced = (
        (deadline_ev.get("admission") or {}).get("deadline_met") is False
        and (deadline_ev.get("admission") or {}).get("provider_invocation_permitted") is False
        and validate_failure_control_evidence(deadline_ev) == ()
    )

    resource_ev = simulate_fault_injection(
        fault_kind="timeout",
        request=request,
        route_requirements=dict(route, required_vram_mb=999_999_999),
        dag_passes=dag,
        decided_at=DECIDED_AT,
    )
    resource_enforced = (
        (resource_ev.get("admission") or {}).get("resource_feasible") is False
        and (resource_ev.get("admission") or {}).get("provider_invocation_permitted") is False
        and validate_failure_control_evidence(resource_ev) == ()
    )

    budget_ev = simulate_fault_injection(
        fault_kind="outage",
        request=dict(request, attempt_number=3),
        route_requirements=route,
        dag_passes=dag,
        decided_at=DECIDED_AT,
    )
    retry_budget_enforced = (budget_ev.get("retry") or {}).get(
        "retry_permitted"
    ) is False and validate_failure_control_evidence(budget_ev) == ()

    def _obs(circuit: dict[str, Any], **extra: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "at_time": DECIDED_AT,
            "request": request,
            "route_requirements": route,
            "failure": {},
            "main_circuit_evidence": circuit,
            "main_retry_evidence": {},
            "main_scoped_block_evidence": {},
            "fallback_attempt": {},
            "dag_passes": dag,
        }
        body.update(extra)
        return body

    healthy_ev = build_failure_control_evidence(
        _obs(_fc_circuit(state="closed")), decided_at=DECIDED_AT
    )
    healthy_admits = (
        healthy_ev.get("status") == "accepted"
        and (healthy_ev.get("admission") or {}).get("provider_invocation_permitted") is True
        and (healthy_ev.get("circuit") or {}).get("blocks_route") is False
        and (healthy_ev.get("no_silent_fallback") or {}).get("fallback_artifact_present") is False
        and validate_failure_control_evidence(healthy_ev) == ()
    )

    open_ev = build_failure_control_evidence(_obs(_fc_circuit(state="open")), decided_at=DECIDED_AT)
    circuit_open_blocks = (
        (open_ev.get("circuit") or {}).get("state") == "open"
        and (open_ev.get("circuit") or {}).get("blocks_route") is True
        and (open_ev.get("admission") or {}).get("provider_invocation_permitted") is False
        and (open_ev.get("no_silent_fallback") or {}).get("fallback_artifact_present") is False
        and validate_failure_control_evidence(open_ev) == ()
    )

    half_blocked_ev = build_failure_control_evidence(
        _obs(_fc_circuit(state="half_open", half_open_probe_allowed=False)),
        decided_at=DECIDED_AT,
    )
    half_probe_ev = build_failure_control_evidence(
        _obs(_fc_circuit(state="half_open", half_open_probe_allowed=True)),
        decided_at=DECIDED_AT,
    )
    half_open_gated = (
        (half_blocked_ev.get("admission") or {}).get("provider_invocation_permitted") is False
        and (half_probe_ev.get("admission") or {}).get("provider_invocation_permitted") is True
        and validate_failure_control_evidence(half_blocked_ev) == ()
        and validate_failure_control_evidence(half_probe_ev) == ()
    )

    fallback_ev = build_failure_control_evidence(
        _obs(
            _fc_circuit(state="closed"),
            fallback_attempt={
                "artifact_present": True,
                "artifact_kind": "empty_mask",
                "allow_silent_fallback": False,
            },
        ),
        decided_at=DECIDED_AT,
    )
    fallback_refused = (
        fallback_ev.get("status") == "rejected"
        and "silent_fallback_forbidden" in (fallback_ev.get("rejection_reasons") or [])
        and "fallback_artifact_present" in (fallback_ev.get("rejection_reasons") or [])
        and (fallback_ev.get("admission") or {}).get("provider_invocation_permitted") is False
        and (fallback_ev.get("no_silent_fallback") or {}).get("fallback_artifact_present") is True
        and (fallback_ev.get("no_silent_fallback") or {}).get("enforced") is True
        and validate_failure_control_evidence(fallback_ev) == ()
    )

    overreach_ev = build_failure_control_evidence(
        {
            "at_time": DECIDED_AT,
            "request": request,
            "route_requirements": route,
            "failure": {"fault_kind": "outage"},
            "main_circuit_evidence": _fc_circuit(state="closed"),
            "main_retry_evidence": {},
            "main_scoped_block_evidence": {
                "blocked_pass_ids": ["pass_predict", "pass_refine", "pass_unrelated"],
                "continuing_pass_ids": [],
                "contains_fallback_artifact": False,
            },
            "fallback_attempt": {},
            "dag_passes": dag,
        },
        decided_at=DECIDED_AT,
    )
    underreach_ev = build_failure_control_evidence(
        {
            "at_time": DECIDED_AT,
            "request": request,
            "route_requirements": route,
            "failure": {"fault_kind": "outage"},
            "main_circuit_evidence": _fc_circuit(state="closed"),
            "main_retry_evidence": {},
            "main_scoped_block_evidence": {
                "blocked_pass_ids": ["pass_predict"],
                "continuing_pass_ids": ["pass_refine", "pass_unrelated"],
                "contains_fallback_artifact": False,
            },
            "fallback_attempt": {},
            "dag_passes": dag,
        },
        decided_at=DECIDED_AT,
    )
    scoped_overreach_rejected = (
        (overreach_ev.get("scoped_dag") or {}).get("scope_exact") is False
        and (overreach_ev.get("admission") or {}).get("provider_invocation_permitted") is False
    )
    scoped_underreach_rejected = (
        (underreach_ev.get("scoped_dag") or {}).get("scope_exact") is False
        and (underreach_ev.get("admission") or {}).get("provider_invocation_permitted") is False
    )

    bad_retry_ev = build_failure_control_evidence(
        {
            "at_time": DECIDED_AT,
            "request": request,
            "route_requirements": route,
            "failure": {"fault_kind": "incompatible_authority"},
            "main_circuit_evidence": _fc_circuit(state="closed"),
            "main_retry_evidence": {
                "retry_requested": True,
                "retry_reason": "authority_mismatch",
                "allow_silent_fallback": False,
            },
            "main_scoped_block_evidence": {},
            "fallback_attempt": {},
            "dag_passes": dag,
        },
        decided_at=DECIDED_AT,
    )
    bad_retry_rejected = (
        bad_retry_ev.get("status") == "rejected"
        and bool(
            {"main_retry_evidence_invalid", "non_transient_retry_forbidden"}
            & set(bad_retry_ev.get("rejection_reasons") or [])
        )
        and (bad_retry_ev.get("admission") or {}).get("provider_invocation_permitted") is False
    )

    return {
        "check": "isolated_failure_control_circuit",
        "passed": (
            all(row["passed"] for row in faults)
            and deadline_enforced
            and resource_enforced
            and retry_budget_enforced
            and healthy_admits
            and circuit_open_blocks
            and half_open_gated
            and fallback_refused
            and scoped_overreach_rejected
            and scoped_underreach_rejected
            and bad_retry_rejected
        ),
        "faults": faults,
        "deadline_enforced": deadline_enforced,
        "resource_envelope_enforced": resource_enforced,
        "bounded_retry_budget_enforced": retry_budget_enforced,
        "healthy_admission_permits_provider": healthy_admits,
        "circuit_open_blocks_route": circuit_open_blocks,
        "half_open_probe_gated": half_open_gated,
        "silent_fallback_refused": fallback_refused,
        "scoped_dag_overreach_rejected": scoped_overreach_rejected,
        "scoped_dag_underreach_rejected": scoped_underreach_rejected,
        "incoherent_main_retry_rejected": bad_retry_rejected,
    }


# ---------------------------------------------------------------------------
# Pillar 4: Mode A immutable package-read adversarial matrix (MF-P6-11.02)
# ---------------------------------------------------------------------------
def run_mode_a_package_read() -> dict[str, Any]:
    """Exercise real Mode A package-read accept + fail-closed refusals from the sibling."""
    cases: list[dict[str, Any]] = []

    def _evaluate(
        name: str,
        request: dict[str, Any],
        evidence: dict[str, Any],
        *,
        expect_accepted: bool,
        expect_reason: str | None = None,
        expect_ceiling: str | None = None,
        expect_production_eligible: bool | None = None,
    ) -> None:
        result = evaluate_mode_a_package_read(request, evidence, decided_at=MODE_A_DECIDED_AT)
        issues = validate_mode_a_package_read_evidence(result)
        reasons = result.get("rejection_reasons") or []
        accepted = result.get("status") == "accepted"
        reason_ok = expect_reason is None or expect_reason in reasons
        ceiling_ok = expect_ceiling is None or result.get("authority_ceiling") == expect_ceiling
        prod_ok = (
            expect_production_eligible is None
            or result.get("production_eligible") is expect_production_eligible
        )
        authority_ok = accepted or (
            result.get("production_eligible") is False
            and result.get("authority_ceiling") != "certified"
        )
        cases.append(
            {
                "case": name,
                "status": result.get("status"),
                "authority_ceiling": result.get("authority_ceiling"),
                "production_eligible": result.get("production_eligible"),
                "rejection_reasons": reasons,
                "passed": bool(
                    accepted == expect_accepted
                    and reason_ok
                    and ceiling_ok
                    and prod_ok
                    and issues == ()
                    and result.get("write_methods_exposed") is False
                    and authority_ok
                ),
            }
        )

    request, evidence = build_fixture_adopted_package()
    _evaluate("valid_wrapper_certified", request, evidence, expect_accepted=True)
    baseline = evaluate_mode_a_package_read(request, evidence, decided_at=MODE_A_DECIDED_AT)
    baseline_certified = (
        baseline.get("authority_ceiling") == "certified"
        and baseline.get("production_eligible") is True
    )

    request, evidence = build_fixture_adopted_package()
    request["escalate_raw_status"] = True
    _evaluate(
        "raw_status_escalation",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="raw_status_escalation",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["relative_paths"]["mask"] = "../../escape/secrets.png"
    _evaluate("path_escape", request, evidence, expect_accepted=False, expect_reason="path_escape")

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["bytes"]["mask_encoded"] = b"tampered-mask-encoded!!"
    _evaluate(
        "mask_hash_drift", request, evidence, expect_accepted=False, expect_reason="mask_hash_drift"
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["wrapper"]["status"] = "expired"
    _evaluate(
        "stale_wrapper", request, evidence, expect_accepted=False, expect_reason="wrapper_stale"
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["wrapper"]["permitted_use_scopes"] = ["thumbnail_preview"]
    _evaluate(
        "wrapper_out_of_scope",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="wrapper_out_of_scope",
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["subject"]["canonical_person_id"] = "attacker-person"
    _evaluate("wrong_owner", request, evidence, expect_accepted=False, expect_reason="wrong_owner")

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["write_requested"] = True
    _evaluate(
        "mutation_attempt",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="mutation_attempt",
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    evidence = copy.deepcopy(evidence)
    request["exact_use_scope"] = "qa"
    evidence["wrapper"] = None
    _evaluate(
        "qa_noncertified_read_accepts_capped",
        request,
        evidence,
        expect_accepted=True,
        expect_ceiling="qa_passed_noncertified",
        expect_production_eligible=False,
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["wrapper"] = None
    _evaluate(
        "wrapper_missing_production",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="wrapper_missing",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["wrapper"]["revocation_status"] = "revoked"
    _evaluate(
        "wrapper_revoked",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="wrapper_revoked",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["catalog"]["adoption_decision"] = "pending"
    _evaluate(
        "catalog_not_adopted",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="catalog_not_adopted",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["bytes"]["source_encoded"] = b"tampered-source-encoded!"
    _evaluate(
        "source_hash_drift",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="source_hash_drift",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["bytes"]["manifest"] = b'{"parts":{"left_forearm":{"status":"tampered"}}}'
    _evaluate(
        "manifest_hash_drift",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="manifest_hash_drift",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["catalog"]["packages"][0]["package_sha256"] = "0" * 64
    _evaluate(
        "package_hash_drift",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="package_hash_drift",
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["ontology_version"] = "body_parts_v2"
    _evaluate(
        "ontology_mismatch",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="ontology_mismatch",
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["subject"]["scene_instance_id"] = "scene-instance-attacker"
    _evaluate(
        "instance_mismatch",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="instance_mismatch",
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["subject"]["character_revision"] = "char-rev-attacker"
    _evaluate(
        "character_revision_mismatch",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="character_revision_mismatch",
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["raw_part_status"] = "rejected_needs_fix"
    _evaluate(
        "rejected_part_status",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="rejected_part_status",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["bytes"]["revocation_identity"] = b"not-a-signed-revocation-record"
    _evaluate(
        "revocation_not_current",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="revocation_not_current",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["catalog"]["packages"][0]["transform_chain_sha256"] = "a" * 64
    _evaluate(
        "transform_drift",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="transform_drift",
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["artifact_kind"] = "refinement"
    request["claim_parent_authority"] = True
    _evaluate(
        "derived_authority_escalation",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="derived_authority_escalation",
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    evidence = copy.deepcopy(evidence)
    request["claimed_authority_state"] = "certified"
    evidence["wrapper"] = None
    _evaluate(
        "claimed_certified_without_wrapper",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="raw_status_escalation",
    )

    request, evidence = build_fixture_adopted_package(person_index=1)
    _evaluate(
        "multi_person_wrapper_certified",
        request,
        evidence,
        expect_accepted=True,
        expect_ceiling="certified",
        expect_production_eligible=True,
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["person_index"] = 9
    _evaluate(
        "missing_person_catalog_refused",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="catalog_not_adopted",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["bytes"]["release"] = b"tampered-release-bytes"
    _evaluate(
        "release_capability_drift",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="release_capability_drift",
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    evidence = copy.deepcopy(evidence)
    request["exact_use_scope"] = "diagnostic"
    evidence["wrapper"] = None
    _evaluate(
        "diagnostic_noncertified_accepts_capped",
        request,
        evidence,
        expect_accepted=True,
        expect_ceiling="qa_passed_noncertified",
        expect_production_eligible=False,
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["mutation_target"] = "masks/left_forearm.png"
    _evaluate(
        "mutation_target_write_forbidden",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="mutation_attempt",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["bytes"]["source_decoded_pixels"] = b"tampered-source-pixels!!"
    _evaluate(
        "source_pixel_hash_drift",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="source_hash_drift",
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["raw_part_status"] = "withdrawn"
    _evaluate(
        "withdrawn_part_status",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="rejected_part_status",
    )

    return {
        "check": "isolated_mode_a_package_read",
        "passed": baseline_certified and all(c["passed"] for c in cases),
        "baseline_certified": baseline_certified,
        "case_count": len(cases),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# Pillar 5: cross-project qualification (honest producer_partial ceiling)
# ---------------------------------------------------------------------------
def run_cross_project_qualification() -> dict[str, Any]:
    evidence = build_cross_project_qualification_evidence(
        observation={"producer_git_commit": producer_git_head()},
        decided_at=DECIDED_AT,
        repo_root=producer_root(),
        bind_fixture_main=False,
    )
    issues = validate_cross_project_qualification_evidence(evidence)
    claim = evidence.get("claim_boundary") or {}
    return {
        "check": "isolated_cross_project_producer_partial",
        "passed": bool(
            evidence.get("status") == "producer_partial"
            and issues == ()
            and claim.get("mf_p6_12_05_complete") is False
            and claim.get("establishes_production_qualification") is False
        ),
        "status": evidence.get("status"),
        "mf_p6_12_05_complete": claim.get("mf_p6_12_05_complete"),
        "establishes_production_qualification": claim.get("establishes_production_qualification"),
        "decision_sha256": evidence.get("decision_sha256"),
        "validation_issues": list(issues),
    }


# ---------------------------------------------------------------------------
# Pillar 5b: qualification adversarial depth (MF-P6-12.05)
# ---------------------------------------------------------------------------
def run_cross_project_qualification_depth() -> dict[str, Any]:
    head = producer_git_head()
    rows: list[dict[str, Any]] = []

    def _xproj(observation: dict[str, Any] | None) -> dict[str, Any]:
        return build_cross_project_qualification_evidence(
            observation=observation,
            decided_at=DECIDED_AT,
            repo_root=producer_root(),
            bind_fixture_main=False,
        )

    baseline = _xproj({"producer_git_commit": head})
    baseline_issues = validate_cross_project_qualification_evidence(baseline)
    baseline_claim = baseline.get("claim_boundary") or {}
    matrix_rows_pass = all(
        row.get("result") == "pass" for row in (baseline.get("matrix_results") or [])
    )
    rows.append(
        {
            "case": "honest_producer_partial_baseline",
            "passed": bool(
                baseline.get("status") == "producer_partial"
                and baseline_issues == ()
                and matrix_rows_pass
                and baseline_claim.get("mf_p6_12_05_complete") is False
                and baseline_claim.get("establishes_production_qualification") is False
            ),
            "status": baseline.get("status"),
            "decision_sha256": baseline.get("decision_sha256"),
        }
    )

    fabricated = _xproj(
        {
            "producer_git_commit": head,
            "fabricated_main_receipt": {
                "main_adapter_execution_receipt_present": True,
                "result_sha256": "a" * 64,
                "history_sha256": "b" * 64,
                "claim_mf_p6_12_05_complete": True,
            },
        }
    )
    rows.append(
        {
            "case": "fabricated_main_receipt_rejected",
            "passed": bool(
                fabricated.get("status") == "rejected"
                and "fabricated_main_receipt" in (fabricated.get("rejection_reasons") or [])
                and validate_cross_project_qualification_evidence(fabricated) == ()
                and (fabricated.get("claim_boundary") or {}).get("mf_p6_12_05_complete") is False
            ),
        }
    )

    claimed = _xproj({"producer_git_commit": head, "claim_production_qualification": True})
    rows.append(
        {
            "case": "fixture_claimed_as_production_rejected",
            "passed": bool(
                claimed.get("status") == "rejected"
                and "fixture_evidence_claimed_as_production"
                in (claimed.get("rejection_reasons") or [])
                and validate_cross_project_qualification_evidence(claimed) == ()
            ),
        }
    )

    relabel = _xproj({"producer_git_commit": head, "claimed_currency_status": "pass"})
    rows.append(
        {
            "case": "currency_relabel_rejected",
            "passed": bool(
                relabel.get("status") == "rejected"
                and "currency_policy_relabel_forbidden" in (relabel.get("rejection_reasons") or [])
                and validate_cross_project_qualification_evidence(relabel) == ()
            ),
        }
    )

    tampered_hash = copy.deepcopy(baseline)
    tampered_hash["decision_sha256"] = "0" * 64
    rows.append(
        {
            "case": "decision_hash_drift_detected",
            "passed": "decision_hash_drift"
            in validate_cross_project_qualification_evidence(tampered_hash),
        }
    )

    overclaim = copy.deepcopy(baseline)
    overclaim["claim_boundary"] = dict(overclaim.get("claim_boundary") or {})
    overclaim["claim_boundary"]["mf_p6_12_05_complete"] = True
    rows.append(
        {
            "case": "completion_overclaim_detected",
            "passed": "completion_overclaim"
            in validate_cross_project_qualification_evidence(overclaim),
        }
    )

    row_drift = copy.deepcopy(baseline)
    if isinstance(row_drift.get("matrix_results"), list) and row_drift["matrix_results"]:
        row_drift["matrix_results"] = row_drift["matrix_results"][:-1]
    rows.append(
        {
            "case": "matrix_row_set_drift_detected",
            "passed": "matrix_row_set_drift"
            in validate_cross_project_qualification_evidence(row_drift),
        }
    )

    commit_only = _xproj(
        {
            "producer_git_commit": head,
            "pinned_main_runtime_git_commit": "c" * 40,
        }
    )
    consumer_binding = commit_only.get("consumer_binding") or {}
    rows.append(
        {
            "case": "pinned_main_commit_alone_insufficient",
            "passed": bool(
                commit_only.get("status") == "producer_partial"
                and consumer_binding.get("complete") is False
                and validate_cross_project_qualification_evidence(commit_only) == ()
                and (commit_only.get("claim_boundary") or {}).get(
                    "establishes_production_qualification"
                )
                is False
            ),
        }
    )

    # climb5 depth additions (align with producer tools/run_isolated_main_consumer_climb5.py)
    adoption_only = _xproj(
        {
            "producer_git_commit": head,
            "pinned_main_runtime_git_commit": "c" * 40,
            "adoption_receipt": {
                "adoption_id": "mfadopt_sibling_climb5_adoption_only",
                "adoption_payload_sha256": "1" * 64,
                "signature": {"key_id": "comfy-main-adoption-prod"},
            },
        }
    )
    adoption_reasons = set(adoption_only.get("rejection_reasons") or [])
    rows.append(
        {
            "case": "adoption_alone_external_prereq_unmet",
            "passed": bool(
                adoption_only.get("status") == "producer_partial"
                and "external_main_prerequisite_unmet" in adoption_reasons
                and "main_qualification_signature_absent" in adoption_reasons
                and (adoption_only.get("consumer_binding") or {}).get("complete") is False
                and validate_cross_project_qualification_evidence(adoption_only) == ()
            ),
        }
    )

    qual_only = _xproj(
        {
            "producer_git_commit": head,
            "pinned_main_runtime_git_commit": "c" * 40,
            "qualification_bundle": {
                "qualification_id": "mfqual_sibling_climb5_only",
                "qualification_payload_sha256": "2" * 64,
                "signature": {
                    "key_id": "comfy-main-qualification-prod",
                    "value_base64": "c2libGluZy1jbGltYi1xdWFs",
                },
            },
        }
    )
    qual_reasons = set(qual_only.get("rejection_reasons") or [])
    rows.append(
        {
            "case": "qualification_alone_external_prereq_unmet",
            "passed": bool(
                qual_only.get("status") == "producer_partial"
                and "external_main_prerequisite_unmet" in qual_reasons
                and "main_adapter_execution_absent" in qual_reasons
                and (qual_only.get("consumer_binding") or {}).get("complete") is False
                and validate_cross_project_qualification_evidence(qual_only) == ()
            ),
        }
    )

    adapter_hist = _xproj(
        {
            "producer_git_commit": head,
            "pinned_main_runtime_git_commit": "c" * 40,
            "main_adapter_execution_receipt_present": True,
            "comfyui_result_history_present": True,
        }
    )
    ah_reasons = set(adapter_hist.get("rejection_reasons") or [])
    rows.append(
        {
            "case": "adapter_history_without_adoption_insufficient",
            "passed": bool(
                adapter_hist.get("status") == "producer_partial"
                and "external_main_prerequisite_unmet" in ah_reasons
                and "adoption_receipt_absent" in ah_reasons
                and (adapter_hist.get("consumer_binding") or {}).get("complete") is False
                and validate_cross_project_qualification_evidence(adapter_hist) == ()
                and (adapter_hist.get("claim_boundary") or {}).get("mf_p6_12_05_complete") is False
            ),
        }
    )

    prod_over = copy.deepcopy(baseline)
    prod_over["claim_boundary"] = dict(prod_over.get("claim_boundary") or {})
    prod_over["claim_boundary"]["establishes_production_qualification"] = True
    rows.append(
        {
            "case": "production_qualification_overclaim_detected",
            "passed": "production_qualification_overclaim"
            in validate_cross_project_qualification_evidence(prod_over),
        }
    )

    acc_over = copy.deepcopy(baseline)
    acc_over["claim_boundary"] = dict(acc_over.get("claim_boundary") or {})
    acc_over["claim_boundary"]["independent_real_accuracy_claim"] = True
    rows.append(
        {
            "case": "independent_real_accuracy_overclaim_detected",
            "passed": "independent_real_accuracy_overclaim"
            in validate_cross_project_qualification_evidence(acc_over),
        }
    )

    forged_accept = copy.deepcopy(baseline)
    forged_accept["status"] = "accepted"
    forged_accept["consumer_binding"] = dict(forged_accept.get("consumer_binding") or {})
    forged_accept["consumer_binding"]["complete"] = False
    rows.append(
        {
            "case": "accepted_without_main_bindings_detected",
            "passed": "accepted_without_main_bindings"
            in validate_cross_project_qualification_evidence(forged_accept),
        }
    )

    return {
        "check": "isolated_cross_project_qualification_depth",
        "passed": all(row["passed"] for row in rows),
        "baseline_decision_sha256": baseline.get("decision_sha256"),
        "prior_case_count": 8,
        "case_count": len(rows),
        "cases": rows,
    }


# ---------------------------------------------------------------------------
# Pillar 5c: final-release firewall depth (MF-P6-12.06)
# ---------------------------------------------------------------------------
def _released_snapshot(*, fixture_only: bool) -> dict[str, Any]:
    return {
        "release_id": "mfrel_sibling_firewall_depth",
        "release_payload_sha256": "d" * 64,
        "release_status": "published",
        "fixture_only": fixture_only,
        "producer": {"git_commit": "e" * 40},
    }


def run_final_release_firewall_depth() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []

    honest = evaluate_final_release_handoff(decided_at=DECIDED_AT)
    honest_claim = honest.get("claim_boundary") or {}
    rows.append(
        {
            "case": "honest_incomplete_core",
            "passed": bool(
                honest.get("status") == "incomplete_core"
                and honest.get("core_autonomous_runtime_close_authorized") is False
                and "core_close_refused_without_exact_gates"
                in (honest.get("rejection_reasons") or [])
                and honest_claim.get("core_closed") is False
                and validate_final_release_handoff_evidence(honest) == ()
            ),
            "decision_sha256": honest.get("decision_sha256"),
        }
    )

    fabricated = evaluate_final_release_handoff(
        decided_at=DECIDED_AT, fabricated_core_complete_claim=True
    )
    rows.append(
        {
            "case": "fabricated_core_claim_rejected",
            "passed": bool(
                fabricated.get("status") == "rejected"
                and fabricated.get("core_autonomous_runtime_close_authorized") is False
                and "fabricated_core_complete_claim" in (fabricated.get("rejection_reasons") or [])
                and validate_final_release_handoff_evidence(fabricated) == ()
            ),
        }
    )

    fixture_release = evaluate_final_release_handoff(
        decided_at=DECIDED_AT,
        release_snapshot=_released_snapshot(fixture_only=True),
        release_publication_issues=[],
    )
    gate_by_id = {
        g.get("gate_id"): g for g in (fixture_release.get("exact_core_close_gates") or [])
    }
    rows.append(
        {
            "case": "fixture_only_release_refused",
            "passed": bool(
                fixture_release.get("status") == "incomplete_core"
                and "final_producer_release_fixture_only"
                in (fixture_release.get("rejection_reasons") or [])
                and gate_by_id.get("final_producer_release_published", {}).get("status") != "met"
                and fixture_release.get("core_autonomous_runtime_close_authorized") is False
                and validate_final_release_handoff_evidence(fixture_release) == ()
            ),
        }
    )

    fixture_adoption = evaluate_final_release_handoff(
        decided_at=DECIDED_AT,
        adoption_receipt={"signature": {"key_id": "comfy-main-adoption-fixture"}},
    )
    rows.append(
        {
            "case": "fixture_authority_cannot_close_core",
            "passed": bool(
                fixture_adoption.get("status") == "incomplete_core"
                and "fixture_authority_cannot_close_core"
                in (fixture_adoption.get("rejection_reasons") or [])
                and (fixture_adoption.get("claim_boundary") or {}).get("fixture_main_bound") is True
                and fixture_adoption.get("core_autonomous_runtime_close_authorized") is False
                and validate_final_release_handoff_evidence(fixture_adoption) == ()
            ),
        }
    )

    pin_mismatch = evaluate_final_release_handoff(
        decided_at=DECIDED_AT,
        release_snapshot=_released_snapshot(fixture_only=False),
        release_publication_issues=[],
        adoption_receipt={
            "adoption_id": "mfadopt_sibling_firewall_depth",
            "adoption_payload_sha256": "f" * 64,
            "adoption_scope": "production_authority",
            "decision": "adopted",
            "production_use_authorized": True,
            "fixture_only": False,
            "release_id": "mfrel_some_other_release",
            "release_payload_sha256": "1" * 64,
            "signature": {"key_id": "comfy-main-adoption-prod"},
        },
    )
    rows.append(
        {
            "case": "adoption_release_pin_mismatch_refused",
            "passed": bool(
                pin_mismatch.get("status") == "incomplete_core"
                and "adoption_release_hash_pin_mismatch"
                in (pin_mismatch.get("rejection_reasons") or [])
                and pin_mismatch.get("core_autonomous_runtime_close_authorized") is False
                and validate_final_release_handoff_evidence(pin_mismatch) == ()
            ),
        }
    )

    honest_gate_by_id = {g.get("gate_id"): g for g in (honest.get("exact_core_close_gates") or [])}
    independence = (honest.get("profile_status_inputs") or {}).get("independence_proof") or {}
    rows.append(
        {
            "case": "optional_profile_independence_held",
            "passed": bool(
                independence.get("optional_failure_cannot_revoke_core") is True
                and independence.get("core_close_requires_exact_gates") is True
                and honest_gate_by_id.get("optional_profiles_remain_independent", {}).get("status")
                == "met"
            ),
        }
    )

    tampered_hash = copy.deepcopy(honest)
    tampered_hash["decision_sha256"] = "0" * 64
    rows.append(
        {
            "case": "decision_hash_drift_detected",
            "passed": "decision_hash_drift"
            in validate_final_release_handoff_evidence(tampered_hash),
        }
    )

    gate_drift = copy.deepcopy(honest)
    if (
        isinstance(gate_drift.get("exact_core_close_gates"), list)
        and gate_drift["exact_core_close_gates"]
    ):
        gate_drift["exact_core_close_gates"] = gate_drift["exact_core_close_gates"][:-1]
    rows.append(
        {
            "case": "gate_set_drift_detected",
            "passed": "gate_set_drift" in validate_final_release_handoff_evidence(gate_drift),
        }
    )

    # climb5 depth additions (align with producer tools/run_isolated_main_consumer_climb5.py)
    commit_pin = evaluate_final_release_handoff(
        decided_at=DECIDED_AT,
        release_snapshot={
            **_released_snapshot(fixture_only=False),
            "producer": {"git_commit": "a" * 40},
        },
        release_publication_issues=[],
        producer_git_commit="b" * 40,
        consumer_git_commit="c" * 40,
        adoption_receipt={
            "adoption_id": "mfadopt_sibling_climb5_commit_pin",
            "adoption_payload_sha256": "3" * 64,
            "adoption_scope": "production_authority",
            "decision": "adopted",
            "production_use_authorized": True,
            "fixture_only": False,
            "release_id": "mfrel_sibling_firewall_depth",
            "release_payload_sha256": "d" * 64,
            "consumer_git_commit": "d" * 40,
            "signature": {"key_id": "comfy-main-adoption-prod"},
        },
    )
    rows.append(
        {
            "case": "producer_consumer_commit_pin_mismatch_refused",
            "passed": bool(
                commit_pin.get("core_autonomous_runtime_close_authorized") is False
                and "producer_consumer_commit_pin_mismatch"
                in (commit_pin.get("rejection_reasons") or [])
                and validate_final_release_handoff_evidence(commit_pin) == ()
            ),
        }
    )

    qual_bind = evaluate_final_release_handoff(
        decided_at=DECIDED_AT,
        release_snapshot=_released_snapshot(fixture_only=False),
        release_publication_issues=[],
        adoption_receipt={
            "adoption_id": "mfadopt_sibling_climb5_qual_bind",
            "adoption_payload_sha256": "4" * 64,
            "adoption_scope": "production_authority",
            "decision": "adopted",
            "production_use_authorized": True,
            "fixture_only": False,
            "release_id": "mfrel_sibling_firewall_depth",
            "release_payload_sha256": "d" * 64,
            "qualification_bundle_id": "mfqual_wrong",
            "qualification_bundle_sha256": "5" * 64,
            "signature": {"key_id": "comfy-main-adoption-prod"},
        },
        qualification_bundle={
            "qualification_id": "mfqual_sibling_climb5",
            "qualification_payload_sha256": "6" * 64,
            "fixture_only": False,
        },
    )
    rows.append(
        {
            "case": "qualification_bundle_binding_failed_refused",
            "passed": bool(
                qual_bind.get("core_autonomous_runtime_close_authorized") is False
                and "qualification_bundle_binding_failed"
                in (qual_bind.get("rejection_reasons") or [])
                and validate_final_release_handoff_evidence(qual_bind) == ()
            ),
        }
    )

    ack_incomplete = evaluate_final_release_handoff(
        decided_at=DECIDED_AT,
        release_snapshot=_released_snapshot(fixture_only=False),
        release_publication_issues=[],
        adoption_receipt={
            "adoption_id": "mfadopt_sibling_climb5_ack",
            "adoption_payload_sha256": "7" * 64,
            "adoption_scope": "production_authority",
            "decision": "adopted",
            "production_use_authorized": True,
            "fixture_only": False,
            "release_id": "mfrel_sibling_firewall_depth",
            "release_payload_sha256": "d" * 64,
            "signature": {"key_id": "comfy-main-adoption-prod"},
        },
        reciprocal_acknowledgement={
            "acknowledgement_id": "mfack_sibling_climb5_incomplete",
        },
    )
    ack_reasons = set(ack_incomplete.get("rejection_reasons") or [])
    ack_gates = {
        g.get("gate_id"): g for g in (ack_incomplete.get("exact_core_close_gates") or [])
    }
    rows.append(
        {
            "case": "acknowledgement_binding_incomplete_refused",
            "passed": bool(
                ack_incomplete.get("core_autonomous_runtime_close_authorized") is False
                and (
                    "reciprocal_acknowledgement_binding_failed" in ack_reasons
                    or ack_gates.get("reciprocal_producer_acknowledgement", {}).get("status")
                    in ("failed", "missing")
                )
                and validate_final_release_handoff_evidence(ack_incomplete) == ()
            ),
        }
    )

    isolated_auth = evaluate_final_release_handoff(
        decided_at=DECIDED_AT,
        release_snapshot=_released_snapshot(fixture_only=False),
        release_publication_issues=[],
        adoption_receipt={
            "adoption_id": "mfadopt_sibling_climb5_isolated_auth",
            "adoption_payload_sha256": "8" * 64,
            "adoption_scope": "production_authority",
            "decision": "adopted",
            "production_use_authorized": True,
            "fixture_only": False,
            "release_id": "mfrel_sibling_firewall_depth",
            "release_payload_sha256": "d" * 64,
            "authority_kind": "isolated_main_consumer",
            "signature": {"key_id": "isolated-main-consumer-adoption"},
        },
    )
    rows.append(
        {
            "case": "isolated_consumer_authority_cannot_close_core",
            "passed": bool(
                isolated_auth.get("core_autonomous_runtime_close_authorized") is False
                and isolated_auth.get("status") in ("incomplete_core", "rejected")
                and validate_final_release_handoff_evidence(isolated_auth) == ()
                and (isolated_auth.get("claim_boundary") or {}).get("core_closed") is not True
            ),
        }
    )

    return {
        "check": "isolated_final_release_firewall_depth",
        "passed": all(row["passed"] for row in rows),
        "honest_decision_sha256": honest.get("decision_sha256"),
        "prior_case_count": 8,
        "case_count": len(rows),
        "cases": rows,
    }


# ---------------------------------------------------------------------------
# Signed adoption attestation (isolated authority)
# ---------------------------------------------------------------------------
def _adopted_requirements() -> dict[str, Any]:
    bundle_path = (
        producer_root()
        / "runtime_artifacts"
        / "main_consumer_conformance"
        / "inbox"
        / "requirements_capability_bundle.json"
    )
    if not bundle_path.exists():
        return {"requirements_id": None, "requirements_sha256": None}
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    req = bundle.get("requirements") or {}
    return {
        "requirements_id": req.get("requirements_id"),
        "requirements_sha256": req.get("requirements_sha256"),
    }


def sign_adoption_attestation() -> dict[str, Any]:
    private_key, key_id = _isolated_key("adoption")
    public_raw = private_key.public_key().public_bytes_raw()
    adopted = _adopted_requirements()
    attestation: dict[str, Any] = {
        "record_type": "isolated_main_consumer_adoption_attestation",
        "schema_version": "1.0.0",
        "decided_at": DECIDED_AT,
        "authority_kind": "isolated_main_consumer",
        "is_real_comfyui_main": False,
        "main_adoption_complete": False,
        "consumer": {
            "project": "Comfy_UI_Main_MaskFactory_Consumer",
            "controller_version": "1.0.0",
            "git_commit": consumer_git_head(),
            "provenance": "isolated_main_consumer",
            "is_real_comfyui_main": False,
        },
        "adopted": {
            "producer_git_commit": producer_git_head(),
            "bridge_contract": ADOPTED_CONTRACT_VERSIONS["bridge_contract"],
            "api_contract": ADOPTED_CONTRACT_VERSIONS["api_contract"],
            "wire_schema_versions": dict(ADOPTED_WIRE_SCHEMA_VERSIONS),
            **adopted,
        },
        "disclaimer": (
            "Signed by an isolated producer-side consumer key "
            "(key_id 'isolated-main-consumer-adoption', NOT a 'comfy-main-*' Main "
            "trust-anchored key). This attestation is real cryptographic evidence "
            "of isolated-consumer adoption of the producer contracts; it deliberately "
            "does NOT satisfy validate_maskfactory_adoption_receipt for production "
            "Comfy_UI_Main adoption, and does NOT close HARD blockers "
            "MF-P6-11.02/11.07/12.05/12.06."
        ),
    }
    attestation["adoption_payload_sha256"] = canonical_document_sha256(
        attestation, excluded_top_level_fields=("adoption_payload_sha256", "signature")
    )
    digest = bytes.fromhex(attestation["adoption_payload_sha256"])
    attestation["signature"] = {
        "algorithm": "ed25519",
        "key_id": key_id,
        "public_key_base64": base64.b64encode(public_raw).decode(),
        "signed_payload_format": "sha256_digest_bytes",
        "signed_payload_sha256": attestation["adoption_payload_sha256"],
        "value_base64": base64.b64encode(private_key.sign(digest)).decode(),
    }
    private_key.public_key().verify(
        base64.b64decode(attestation["signature"]["value_base64"]), digest
    )
    return attestation


def run_adoption_attestation() -> dict[str, Any]:
    attestation = sign_adoption_attestation()
    return {
        "check": "isolated_adoption_attestation_signed",
        "passed": attestation["signature"]["key_id"] == "isolated-main-consumer-adoption",
        "key_id": attestation["signature"]["key_id"],
        "adoption_payload_sha256": attestation["adoption_payload_sha256"],
        "attestation": attestation,
    }
