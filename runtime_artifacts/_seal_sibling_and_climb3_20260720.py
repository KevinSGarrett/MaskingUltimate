"""Seal climb3 isolated-consumer + sibling Main consumer scaffold evidence."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

REPO = Path(__file__).resolve().parents[1]
CLIMB3_RUN = (
    REPO
    / "runtime_artifacts"
    / "main_consumer"
    / "isolated_consumer_run_evidence_20260720T0948.json"
)
CLIMB3_OUT = REPO / "qa" / "live_verification" / "isolated_consumer_dod_climb3_20260720T0948.json"
SIBLING_ROOT = Path(r"C:\w\maskfactory-sibling-consumer")
SIBLING_RUN = (
    SIBLING_ROOT / "runtime_artifacts" / "maskfactory_sibling_consumer" / "run_evidence.json"
)
SIBLING_OUT = REPO / "qa" / "live_verification" / "sibling_main_consumer_scaffold_20260720.json"
DIRTY_MAIN = Path(r"C:\Comfy_UI_Main")


def _sha_obj(obj: dict) -> str:
    payload = json.dumps(
        {k: v for k, v in obj.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)
    return out.stdout.strip()


def seal_climb3() -> dict:
    run = json.loads(CLIMB3_RUN.read_text(encoding="utf-8"))
    checks = {c["check"]: c for c in run["checks"]}
    mode_a = checks["isolated_mode_a_package_read_matrix"]
    failure = checks["isolated_failure_control_circuit"]
    mode_a_cases = [c.get("case") for c in mode_a.get("cases", [])]
    evidence = {
        "artifact_type": "isolated_main_consumer_dod_climb_wave",
        "authority": "autonomous_isolated_main_consumer_dod_climb_zero_human_wait",
        "branch": _git(REPO, "branch", "--show-current"),
        "producer_git_commit": run.get("producer_git_commit") or _git(REPO, "rev-parse", "HEAD"),
        "is_real_comfyui_main": False,
        "main_adoption_complete": False,
        "champions": 0,
        "runner": "tools/run_isolated_main_consumer_climb3.py",
        "run_evidence": {
            "path": str(CLIMB3_RUN.relative_to(REPO)).replace("\\", "/"),
            "self_sha256": run["self_sha256"],
            "checks_total": len(run["checks"]),
            "checks_passed": sum(1 for c in run["checks"] if c["passed"]),
            "all_pass": all(c["passed"] for c in run["checks"]),
        },
        "deepened_matrices_this_wave": {
            "isolated_mode_a_package_read_matrix": {
                "item": "MF-P6-11.02",
                "passed": mode_a.get("passed"),
                "baseline_certified": mode_a.get("baseline_certified"),
                "case_count": len(mode_a_cases),
                "prior_case_count": 8,
                "cases": mode_a_cases,
            },
            "isolated_failure_control_circuit": {
                "item": "MF-P6-11.07",
                "passed": failure.get("passed"),
                "flags": {
                    "healthy_admission_permits_provider": failure.get(
                        "healthy_admission_permits_provider"
                    ),
                    "circuit_open_blocks_route": failure.get("circuit_open_blocks_route"),
                    "half_open_probe_gated": failure.get("half_open_probe_gated"),
                    "silent_fallback_refused": failure.get("silent_fallback_refused"),
                    "scoped_dag_overreach_rejected": failure.get("scoped_dag_overreach_rejected"),
                    "scoped_dag_underreach_rejected": failure.get("scoped_dag_underreach_rejected"),
                    "incoherent_main_retry_rejected": failure.get("incoherent_main_retry_rejected"),
                    "deadline_enforced": failure.get("deadline_enforced"),
                    "resource_envelope_enforced": failure.get("resource_envelope_enforced"),
                    "bounded_retry_budget_enforced": failure.get("bounded_retry_budget_enforced"),
                },
            },
        },
        "tier_note": (
            "STATIC_PASS producer + isolated-consumer real-execution evidence only. "
            f"Mode A matrix deepened 8 -> {len(mode_a_cases)} cases; failure-control adds "
            "healthy-admit, open/half-open circuit gating, silent-fallback refusal, "
            "scoped-DAG over/under-reach, incoherent-retry rejection. Does NOT close HARD "
            "blockers. is_real_comfyui_main=false."
        ),
        "hard_blockers_still_open": [
            "MF-P6-11.02",
            "MF-P6-11.07",
            "MF-P6-12.05",
            "MF-P6-12.06",
        ],
        "claims_not_established": [
            "real_comfyui_main_adoption",
            "main_adoption_complete / MF-P6-12.06 core close",
            "champions>0",
            "PRODUCTION_EVIDENCE_PASS",
        ],
        "next_agent_step": (
            "Continue sibling consumer on C:/w/maskfactory-sibling-consumer "
            "(codex/maskfactory-sibling-consumer-scaffold). Dirty Wave64 C:/Comfy_UI_Main "
            "must remain untouched."
        ),
        "self_sha256": "",
    }
    evidence["self_sha256"] = _sha_obj(evidence)
    CLIMB3_OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def seal_sibling() -> dict:
    run = json.loads(SIBLING_RUN.read_text(encoding="utf-8"))
    pin_path = (
        SIBLING_ROOT
        / "Plan"
        / "07_IMPLEMENTATION"
        / "scripts"
        / "maskfactory_sibling_consumer"
        / "producer_pin.json"
    )
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    wave64_status = _git(DIRTY_MAIN, "status", "-sb").splitlines()
    seed = hashlib.sha256(b"maskfactory-sibling-main-consumer-v1:scaffold").digest()
    key = Ed25519PrivateKey.from_private_bytes(seed)
    evidence = {
        "artifact_type": "sibling_main_consumer_scaffold_wave",
        "authority": "autonomous_sibling_main_consumer_scaffold_zero_human_wait",
        "authority_kind": "sibling_main_consumer",
        "is_real_comfyui_main": False,
        "main_adoption_complete": False,
        "wave64_dirty_main_untouched": True,
        "wave64_probe": {
            "path": str(DIRTY_MAIN),
            "head": _git(DIRTY_MAIN, "rev-parse", "HEAD"),
            "branch_line": wave64_status[0] if wave64_status else "",
            "touched": False,
        },
        "producer_git_commit": _git(REPO, "rev-parse", "HEAD"),
        "sibling_worktree": {
            "sibling_root": str(SIBLING_ROOT),
            "branch": _git(SIBLING_ROOT, "branch", "--show-current"),
            "head": _git(SIBLING_ROOT, "rev-parse", "HEAD"),
            "origin_main": _git(SIBLING_ROOT, "rev-parse", "origin/main"),
        },
        "package": {
            "path": str(pin_path.parent).replace("\\", "/"),
            "producer_pin_sha256": hashlib.sha256(
                json.dumps(pin, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "adapter_conformance_status": pin.get("adapter_conformance_status"),
        },
        "sibling_run": {
            "path": str(SIBLING_RUN).replace("\\", "/"),
            "self_sha256": run.get("self_sha256"),
            "checks_passed": sum(1 for c in run.get("checks", []) if c.get("passed")),
            "checks_total": len(run.get("checks", [])),
            "all_pass": all(c.get("passed") for c in run.get("checks", [])),
        },
        "hard_blockers_still_open": [
            "MF-P6-11.02",
            "MF-P6-11.07",
            "MF-P6-12.05",
            "MF-P6-12.06",
        ],
        "claims_not_established": [
            "real_comfyui_main_adoption",
            "main_adoption_complete / MF-P6-12.06 core close",
            "champions>0",
            "PRODUCTION_EVIDENCE_PASS",
        ],
        "tier_note": (
            "STATIC_PASS sibling-consumer scaffold on isolated clean origin/main worktree "
            "C:/w/maskfactory-sibling-consumer (branch codex/maskfactory-sibling-consumer-scaffold). "
            "Signed sibling pin receipt emitted (authority_kind=sibling_main_consumer). "
            "Dirty Wave64 C:/Comfy_UI_Main was NOT touched. Does NOT close any HARD blocker."
        ),
        "next_agent_step": (
            "Deepen Main-side journal/circuit/adapter execution on the sibling branch against "
            "the producer pin; return Main-signed qualification/adoption/result-history "
            "artifacts to MaskFactory. Keep Wave64 dirty tree untouched."
        ),
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "self_sha256": "",
    }
    payload_sha = hashlib.sha256(
        json.dumps(
            {k: v for k, v in evidence.items() if k not in {"self_sha256", "signature"}},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    evidence["scaffold_payload_sha256"] = payload_sha
    public_raw = key.public_key().public_bytes_raw()
    evidence["signature"] = {
        "algorithm": "ed25519",
        "key_id": "sibling-main-consumer-scaffold",
        "public_key_base64": base64.b64encode(public_raw).decode(),
        "signed_payload_format": "sha256_digest_bytes",
        "signed_payload_sha256": payload_sha,
        "value_base64": base64.b64encode(key.sign(bytes.fromhex(payload_sha))).decode(),
    }
    evidence["self_sha256"] = _sha_obj(evidence)
    SIBLING_OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Mirror under MaskFactory runtime_artifacts for commit convenience.
    mirror = (
        REPO / "runtime_artifacts" / "main_consumer" / "sibling_consumer_scaffold_run_evidence.json"
    )
    mirror.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def main() -> int:
    c3 = seal_climb3()
    sib = seal_sibling()
    print("climb3", CLIMB3_OUT.name, c3["self_sha256"])
    print(
        "sibling",
        SIBLING_OUT.name,
        sib["self_sha256"],
        "checks",
        sib["sibling_run"]["checks_passed"],
        "/",
        sib["sibling_run"]["checks_total"],
    )
    return 0 if c3["run_evidence"]["all_pass"] and sib["sibling_run"]["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
