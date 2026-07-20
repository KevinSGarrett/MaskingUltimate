"""Isolated Main-side consumer runner (MF-P6-11/12 producer+isolated evidence).

Kevin's mandate, Unblock 3: `C:\\Comfy_UI_Main` is an unrelated active Wave64
project with a dirty tree — we must NOT commit MaskFactory into it. Instead this
tool ships a *producer-side, isolated* Main consumer that:

  * executes the REAL bridge machinery (adapter conformance, consumer-requirements
    admission, signed append-only journal + checkpoint, failure-control circuit,
    and the Main-consumer conformance harness) against real producer contract
    bytes, and
  * emits an adoption receipt signed by an isolated-consumer Ed25519 key it
    controls, labeled ``authority_kind = isolated_main_consumer`` (explicitly NOT
    ``fixture_authority`` and NOT the real Comfy_UI_Main runtime).

Honesty ceiling (binding): this advances producer + isolated-consumer evidence
as far as honestly possible. It NEVER claims real Comfy_UI_Main adoption. The
HARD blockers MF-P6-11.02 / 11.07 / 12.05 / 12.06 that require the real Main
runtime remain OPEN; that is recorded in the run evidence, not hidden.

Usage:
  python tools/run_isolated_main_consumer.py \
      --output runtime_artifacts/main_consumer/isolated_consumer_run_evidence_<ts>.json
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from maskfactory.bridge.cross_project_qualification import (
    build_cross_project_qualification_evidence,
    validate_cross_project_qualification_evidence,
)
from maskfactory.bridge.external_adapter_conformance import (
    build_external_adapter_conformance_evidence,
)
from maskfactory.bridge.failure_control import (
    simulate_fault_injection,
    validate_failure_control_evidence,
)
from maskfactory.bridge.journal import (
    append_bridge_journal_event,
    checkpoint_bridge_journal,
    validate_bridge_journal_history,
)
from maskfactory.bridge.main_consumer_conformance import (
    run_main_consumer_conformance_harness,
    validate_main_consumer_conformance_evidence,
)
from maskfactory.validation import canonical_document_sha256

REPO_ROOT = Path(__file__).resolve().parents[1]
INBOX = REPO_ROOT / "runtime_artifacts" / "main_consumer_conformance" / "inbox"
DECIDED_AT = "2026-07-20T05:00:00Z"

# HARD blockers that genuinely require the real Comfy_UI_Main runtime and cannot
# be closed by a producer-shipped isolated consumer.
HARD_BLOCKERS_REQUIRING_REAL_MAIN = (
    "MF-P6-11.02",
    "MF-P6-11.07",
    "MF-P6-12.05",
    "MF-P6-12.06",
)


def _isolated_key(role: str) -> tuple[Ed25519PrivateKey, str]:
    """Deterministic isolated-consumer key the tool controls (reproducible)."""
    seed = hashlib.sha256(f"maskfactory-isolated-main-consumer-v1:{role}".encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(seed), f"isolated-main-consumer-{role}"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_head() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    value = out.stdout.strip().lower()
    return value if len(value) == 40 and all(c in "0123456789abcdef" for c in value) else None


def relabel_and_sign_adoption_receipt() -> dict[str, Any]:
    """Rewrite the inbox adoption receipt as a real, isolated-consumer-signed one."""
    receipt_path = INBOX / "adoption_receipt.json"
    receipt = _load(receipt_path)
    # Preserve the prior artifact once for provenance/audit.
    backup = receipt_path.with_suffix(".prior_fixture.json")
    if not backup.exists():
        backup.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    private_key, key_id = _isolated_key("adoption")
    public_raw = private_key.public_key().public_bytes_raw()

    consumer = dict(receipt.get("consumer") or {})
    consumer["provenance"] = "isolated_main_consumer"
    consumer["is_real_comfyui_main"] = False
    receipt["consumer"] = consumer
    receipt["isolated_consumer_disclaimer"] = {
        "authority_kind": "isolated_main_consumer",
        "is_real_comfyui_main": False,
        "main_adoption_complete": False,
        "note": (
            "Signed by an isolated producer-side consumer key, not the real "
            "Comfy_UI_Main runtime. Conformant to the pinned adopted receipt shape "
            "but does NOT constitute real Main adoption."
        ),
        "hard_blockers_requiring_real_main": list(HARD_BLOCKERS_REQUIRING_REAL_MAIN),
    }
    # Re-seal and re-sign with the isolated consumer's own key.
    receipt["adoption_payload_sha256"] = canonical_document_sha256(
        receipt, excluded_top_level_fields=("adoption_payload_sha256", "signature")
    )
    digest = bytes.fromhex(receipt["adoption_payload_sha256"])
    receipt["signature"] = {
        "algorithm": "ed25519",
        "key_id": key_id,
        "public_key_base64": base64.b64encode(public_raw).decode(),
        "signed_payload_format": "sha256_digest_bytes",
        "signed_payload_sha256": receipt["adoption_payload_sha256"],
        "value_base64": base64.b64encode(private_key.sign(digest)).decode(),
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Verify our own signature cryptographically (genuine, not decorative).
    private_key.public_key().verify(base64.b64decode(receipt["signature"]["value_base64"]), digest)
    return receipt


def run_signed_journal() -> dict[str, Any]:
    """Real append-only signed journal + checkpoint under the isolated consumer key."""
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
        "passed": issues == () and len(entries) == 3,
        "entry_count": len(entries),
        "checkpoint_sha256": checkpoint.get("checkpoint_sha256"),
        "issues": list(issues),
    }


def run_failure_control() -> dict[str, Any]:
    request = {
        "request_id": "mfareq_isolated_00000001",
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
    ]
    results = []
    for fault in ("outage", "timeout", "oom", "incompatible_authority"):
        evidence = simulate_fault_injection(
            fault_kind=fault,
            request=request,
            route_requirements=route,
            dag_passes=dag,
            decided_at=DECIDED_AT,
        )
        issues = validate_failure_control_evidence(evidence)
        no_fallback = evidence.get("no_silent_fallback") or {}
        results.append(
            {
                "fault": fault,
                "status": evidence.get("status"),
                "no_silent_fallback_enforced": no_fallback.get("enforced") is True,
                "fallback_artifact_present": no_fallback.get("fallback_artifact_present"),
                "valid": issues == (),
            }
        )
    passed = all(
        row["status"] in {"accepted", "rejected"}
        and row["no_silent_fallback_enforced"]
        and row["valid"]
        for row in results
    )
    return {"check": "isolated_failure_control_circuit", "passed": passed, "faults": results}


def _check(name: str, passed: bool, **extra: Any) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), **extra}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []

    # 1. Real, isolated-consumer-signed adoption receipt.
    try:
        receipt = relabel_and_sign_adoption_receipt()
        checks.append(
            _check(
                "isolated_adoption_receipt_signed",
                receipt["signature"]["key_id"] == "isolated-main-consumer-adoption",
                key_id=receipt["signature"]["key_id"],
                adoption_payload_sha256=receipt["adoption_payload_sha256"],
                authority_kind="isolated_main_consumer",
            )
        )
    except Exception as exc:  # pragma: no cover - honest failure capture
        checks.append(_check("isolated_adoption_receipt_signed", False, error=repr(exc)))

    # 2. Real adapter conformance on the observed adapter identity.
    try:
        observation = _load(INBOX / "adapter_observation.json")
        adapter_ev = build_external_adapter_conformance_evidence(observation, decided_at=DECIDED_AT)
        checks.append(
            _check(
                "isolated_adapter_conformance",
                adapter_ev.get("status") == "accepted",
                status=adapter_ev.get("status"),
                rejection_reasons=adapter_ev.get("rejection_reasons"),
            )
        )
    except Exception as exc:  # pragma: no cover
        checks.append(_check("isolated_adapter_conformance", False, error=repr(exc)))

    # 3. Real signed journal + checkpoint.
    try:
        checks.append(run_signed_journal())
    except Exception as exc:  # pragma: no cover
        checks.append(_check("isolated_signed_journal", False, error=repr(exc)))

    # 4. Real failure-control circuit / no-silent-fallback.
    try:
        checks.append(run_failure_control())
    except Exception as exc:  # pragma: no cover
        checks.append(_check("isolated_failure_control_circuit", False, error=repr(exc)))

    # 5. Real Main-consumer conformance harness over the isolated inbox artifacts.
    try:
        harness = run_main_consumer_conformance_harness(decided_at=DECIDED_AT)
        harness_issues = validate_main_consumer_conformance_evidence(harness)
        checks.append(
            _check(
                "isolated_consumer_conformance_harness",
                harness.get("status") == "accepted"
                and harness_issues == ()
                and harness.get("main_adoption_complete") is False,
                status=harness.get("status"),
                main_adoption_complete=harness.get("main_adoption_complete"),
                validation_issues=list(harness_issues),
                decision_sha256=harness.get("decision_sha256"),
            )
        )
    except Exception as exc:  # pragma: no cover
        checks.append(_check("isolated_consumer_conformance_harness", False, error=repr(exc)))

    # 6. Cross-project qualification: producer + isolated-consumer evidence WITHOUT
    #    a fabricated real-Main commit -> honest producer_partial ceiling.
    try:
        xproj = build_cross_project_qualification_evidence(
            observation={"producer_git_commit": _git_head()},
            decided_at=DECIDED_AT,
            bind_fixture_main=False,
        )
        xproj_issues = validate_cross_project_qualification_evidence(xproj)
        claim = xproj.get("claim_boundary") or {}
        checks.append(
            _check(
                "isolated_cross_project_producer_partial",
                xproj.get("status") == "producer_partial"
                and xproj_issues == ()
                and claim.get("mf_p6_12_05_complete") is False
                and claim.get("establishes_production_qualification") is False,
                status=xproj.get("status"),
                mf_p6_12_05_complete=claim.get("mf_p6_12_05_complete"),
                decision_sha256=xproj.get("decision_sha256"),
                validation_issues=list(xproj_issues),
            )
        )
    except Exception as exc:  # pragma: no cover
        checks.append(_check("isolated_cross_project_producer_partial", False, error=repr(exc)))

    evidence: dict[str, Any] = {
        "artifact_type": "isolated_main_consumer_run",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authority_kind": "isolated_main_consumer",
        "is_real_comfyui_main": False,
        "producer_git_commit": _git_head(),
        "decided_at": DECIDED_AT,
        "checks": checks,
        "summary": {check["check"]: check["passed"] for check in checks},
        "claim_boundary": {
            "isolated_consumer_is_not_fixture_authority": True,
            "isolated_consumer_is_not_real_comfyui_main": True,
            "main_adoption_complete": False,
            "establishes_production_qualification": False,
            "advances": ["MF-P6-11 (consumer-side adapter/journal/circuit real execution)"],
            "hard_blockers_still_open": list(HARD_BLOCKERS_REQUIRING_REAL_MAIN),
            "next_agent_step": (
                "Real receipts require a dedicated Comfy_UI_Main-side integration on an "
                "isolated clean maskfactory branch that consumes the producer adapter package "
                "and emits Main-signed adoption/qualification/adapter-execution/result-history "
                "artifacts pinned back here."
            ),
        },
    }
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence["summary"], sort_keys=True))
    return 0 if all(check["passed"] for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
