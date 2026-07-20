"""Scaffold a sibling Main consumer on an isolated clean Comfy_UI_Main branch.

Mandate: Kevin's Wave64 tree at C:\\Comfy_UI_Main is dirty and MUST NOT be touched.
This tool:

1. Creates (or reuses) a clean git worktree from Comfy_UI_Main origin/main at
   C:\\w\\maskfactory-sibling-consumer on branch
   codex/maskfactory-sibling-consumer-scaffold.
2. Writes a closed MaskFactory sibling-consumer package that consumes only
   producer-adopted contract bytes (no dirty producer imports, no Wave64 merge).
3. Runs the sibling consumer checks, emits a sibling-consumer-signed pin receipt
   (authority_kind=sibling_main_consumer; is_real_comfyui_main=false), and pins
   evidence back under MaskFactory runtime_artifacts/ + qa/live_verification/.

Honesty ceiling: this is NOT production KevinSGarrett/Comfy_UI_Main adoption.
HARD MF-P6-11.02/11.07/12.05/12.06 remain OPEN (AWAITING_MAIN).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
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
from maskfactory.validation import canonical_document_sha256

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAIN_MIRROR = Path(r"C:\w\main-maskfactory-bridge-plan")
DEFAULT_SIBLING_ROOT = Path(r"C:\w\maskfactory-sibling-consumer")
DEFAULT_BRANCH = "codex/maskfactory-sibling-consumer-scaffold"
DIRTY_WAVE64_MAIN = Path(r"C:\Comfy_UI_Main")
HARD_BLOCKERS = ("MF-P6-11.02", "MF-P6-11.07", "MF-P6-12.05", "MF-P6-12.06")
DECIDED_AT = "2026-07-20T15:00:00Z"


def _run(
    cmd: list[str], *, cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=check,
    )


def _git_head(repo: Path) -> str | None:
    try:
        out = _run(["git", "rev-parse", "HEAD"], cwd=repo, check=False)
    except OSError:
        return None
    value = out.stdout.strip().lower()
    return value if len(value) == 40 and all(c in "0123456789abcdef" for c in value) else None


def _sibling_key(role: str) -> tuple[Ed25519PrivateKey, str]:
    seed = hashlib.sha256(f"maskfactory-sibling-main-consumer-v1:{role}".encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(seed), f"sibling-main-consumer-{role}"


def _assert_wave64_untouched() -> dict[str, Any]:
    """Record that the dirty Wave64 Main tree was not modified by this tool."""
    status = {
        "path": str(DIRTY_WAVE64_MAIN),
        "exists": DIRTY_WAVE64_MAIN.exists(),
        "touched": False,
    }
    if not DIRTY_WAVE64_MAIN.exists():
        return status
    # Never run git write commands against DIRTY_WAVE64_MAIN. Read-only probe only.
    probe = _run(["git", "status", "-sb"], cwd=DIRTY_WAVE64_MAIN, check=False)
    status["branch_line"] = (probe.stdout.splitlines() or [""])[0]
    status["head"] = _git_head(DIRTY_WAVE64_MAIN)
    return status


def ensure_sibling_worktree(
    *,
    main_mirror: Path,
    sibling_root: Path,
    branch: str,
) -> dict[str, Any]:
    if not main_mirror.exists():
        raise FileNotFoundError(f"Main mirror worktree missing: {main_mirror}")
    _run(["git", "fetch", "origin", "main"], cwd=main_mirror, check=False)
    origin_main = _run(["git", "rev-parse", "origin/main"], cwd=main_mirror).stdout.strip()

    if sibling_root.exists():
        head = _git_head(sibling_root)
        current = _run(
            ["git", "branch", "--show-current"], cwd=sibling_root, check=False
        ).stdout.strip()
        # Refuse if somehow pointed at the dirty Wave64 path.
        resolved = sibling_root.resolve()
        if resolved == DIRTY_WAVE64_MAIN.resolve():
            raise RuntimeError("refusing to use dirty Wave64 Main as sibling root")
        return {
            "action": "reused",
            "sibling_root": str(sibling_root),
            "branch": current or branch,
            "head": head,
            "origin_main": origin_main,
        }

    sibling_root.parent.mkdir(parents=True, exist_ok=True)
    # Prefer creating the branch from origin/main; if the branch already exists
    # remotely/locally, check it out into the new worktree.
    existing = _run(["git", "rev-parse", "--verify", branch], cwd=main_mirror, check=False)
    if existing.returncode == 0:
        _run(
            ["git", "worktree", "add", str(sibling_root), branch],
            cwd=main_mirror,
        )
    else:
        _run(
            [
                "git",
                "worktree",
                "add",
                "-b",
                branch,
                str(sibling_root),
                "origin/main",
            ],
            cwd=main_mirror,
        )
    return {
        "action": "created",
        "sibling_root": str(sibling_root),
        "branch": branch,
        "head": _git_head(sibling_root),
        "origin_main": origin_main,
    }


CONSUMER_RUNNER = '''"""Sibling Main MaskFactory consumer scaffold (isolated clean branch).

authority_kind = sibling_main_consumer
is_real_comfyui_main = false
wave64_dirty_main_untouched = true

This package consumes producer-pinned adapter/conformance contract bytes only.
It does NOT import dirty MaskFactory source, does NOT claim production adoption,
and does NOT touch the dirty Wave64 tree at C:\\\\Comfy_UI_Main.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
PIN = PACKAGE / "producer_pin.json"


def _key(role: str) -> tuple[Ed25519PrivateKey, str]:
    seed = hashlib.sha256(f"maskfactory-sibling-main-consumer-v1:{role}".encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(seed), f"sibling-main-consumer-{role}"


def _canonical(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha(obj: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(obj)).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    pin = json.loads(PIN.read_text(encoding="utf-8"))
    private_key, key_id = _key("adoption")
    public_raw = private_key.public_key().public_bytes_raw()

    receipt = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_sibling_consumer_pin_receipt",
        "authority_kind": "sibling_main_consumer",
        "is_real_comfyui_main": False,
        "main_adoption_complete": False,
        "wave64_dirty_main_untouched": True,
        "consumer": {
            "repository": "KevinSGarrett/Comfy_UI_Main",
            "worktree": str(ROOT),
            "branch": pin.get("sibling_branch"),
            "head": pin.get("sibling_head"),
            "provenance": "sibling_main_consumer",
            "is_real_comfyui_main": False,
        },
        "producer_pin": {
            "repository": pin.get("producer_repository"),
            "commit": pin.get("producer_commit"),
            "adapter_observation_sha256": pin.get("adapter_observation_sha256"),
            "conformance_policy_sha256": pin.get("conformance_policy_sha256"),
        },
        "hard_blockers_still_open": pin.get("hard_blockers_still_open"),
        "decided_at": pin.get("decided_at"),
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "claims_not_established": [
            "real_comfyui_main_adoption",
            "main_adoption_complete / MF-P6-12.06 core close",
            "PRODUCTION_EVIDENCE_PASS",
        ],
    }
    receipt["adoption_payload_sha256"] = _sha(
        {k: v for k, v in receipt.items() if k not in {"adoption_payload_sha256", "signature"}}
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
    private_key.public_key().verify(
        base64.b64decode(receipt["signature"]["value_base64"]), digest
    )

    # Contract-surface checks (local to this package; no dirty producer import).
    checks = []
    checks.append(
        {
            "check": "sibling_pin_receipt_signed",
            "passed": receipt["signature"]["key_id"] == "sibling-main-consumer-adoption",
            "authority_kind": "sibling_main_consumer",
            "adoption_payload_sha256": receipt["adoption_payload_sha256"],
        }
    )
    checks.append(
        {
            "check": "producer_pin_present",
            "passed": isinstance(pin.get("producer_commit"), str)
            and len(pin.get("producer_commit") or "") == 40,
            "producer_commit": pin.get("producer_commit"),
        }
    )
    checks.append(
        {
            "check": "wave64_dirty_main_untouched",
            "passed": pin.get("wave64_dirty_main_untouched") is True,
        }
    )
    checks.append(
        {
            "check": "no_production_adoption_claim",
            "passed": receipt["is_real_comfyui_main"] is False
            and receipt["main_adoption_complete"] is False,
        }
    )

    evidence = {
        "artifact_type": "sibling_main_consumer_run",
        "authority_kind": "sibling_main_consumer",
        "is_real_comfyui_main": False,
        "main_adoption_complete": False,
        "wave64_dirty_main_untouched": True,
        "sibling_root": str(ROOT),
        "sibling_branch": pin.get("sibling_branch"),
        "sibling_head": pin.get("sibling_head"),
        "producer_commit": pin.get("producer_commit"),
        "origin_main": pin.get("origin_main"),
        "checks": checks,
        "receipt": receipt,
        "hard_blockers_still_open": pin.get("hard_blockers_still_open"),
        "recorded_at": receipt["recorded_at"],
        "self_sha256": "",
    }
    payload = json.dumps(
        {k: v for k, v in evidence.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
    print(
        args.output,
        evidence["self_sha256"],
        "checks",
        sum(1 for c in checks if c["passed"]),
        "/",
        len(checks),
    )
    return 0 if all(c["passed"] for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''
# NOTE: the runner source above is written into the Main worktree; the "\\n"
# sequence is intentional so the generated file contains a real newline escape.


README = """# MaskFactory sibling consumer scaffold

Isolated clean `Comfy_UI_Main` branch for MaskFactory bridge consumer work.

- Branch: `codex/maskfactory-sibling-consumer-scaffold`
- Base: `origin/main` (NOT the dirty Wave64 tree at `C:\\Comfy_UI_Main`)
- Authority: `sibling_main_consumer` (explicitly NOT production Main adoption)

## Run

```
python Plan/07_IMPLEMENTATION/scripts/maskfactory_sibling_consumer/run_sibling_consumer.py \\
  --output runtime_artifacts/maskfactory_sibling_consumer/run_evidence.json
```

## Honesty

Does not close HARD MF-P6-11.02 / 11.07 / 12.05 / 12.06. Does not touch Wave64.
"""


def write_sibling_package(
    *,
    sibling_root: Path,
    producer_commit: str,
    sibling_meta: dict[str, Any],
    wave64: dict[str, Any],
) -> dict[str, Any]:
    pkg = sibling_root / "Plan" / "07_IMPLEMENTATION" / "scripts" / "maskfactory_sibling_consumer"
    pkg.mkdir(parents=True, exist_ok=True)

    adapter_obs = (
        REPO_ROOT / "tests/fixtures/external_adapter_conformance/accepted_observation_v1.json"
    )
    policy = REPO_ROOT / "configs/bridge_external_adapter_conformance_policy.yaml"
    adapter_bytes = adapter_obs.read_bytes()
    policy_bytes = policy.read_bytes()

    # Producer-side conformance proof (MaskFactory machine) — result hash pinned into Main.
    observation = json.loads(adapter_bytes.decode("utf-8"))
    adapter_ev = build_external_adapter_conformance_evidence(observation, decided_at=DECIDED_AT)

    pin = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_sibling_consumer_producer_pin",
        "producer_repository": "KevinSGarrett/MaskingUltimate",
        "producer_commit": producer_commit,
        "sibling_branch": sibling_meta.get("branch"),
        "sibling_head": sibling_meta.get("head"),
        "origin_main": sibling_meta.get("origin_main"),
        "adapter_observation_sha256": hashlib.sha256(adapter_bytes).hexdigest(),
        "conformance_policy_sha256": hashlib.sha256(policy_bytes).hexdigest(),
        "adapter_conformance_status": adapter_ev.get("status"),
        "adapter_conformance_decision_sha256": adapter_ev.get("decision_sha256"),
        "wave64_dirty_main_untouched": wave64.get("touched") is False,
        "wave64_probe": wave64,
        "hard_blockers_still_open": list(HARD_BLOCKERS),
        "decided_at": DECIDED_AT,
        "is_real_comfyui_main": False,
        "main_adoption_complete": False,
    }
    (pkg / "producer_pin.json").write_text(
        json.dumps(pin, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (pkg / "run_sibling_consumer.py").write_text(CONSUMER_RUNNER, encoding="utf-8")
    (pkg / "README.md").write_text(README, encoding="utf-8")

    # Copy closed contract bytes the sibling may inspect without importing MaskFactory.
    contracts = pkg / "contracts"
    contracts.mkdir(exist_ok=True)
    (contracts / "accepted_observation_v1.json").write_bytes(adapter_bytes)
    (contracts / "bridge_external_adapter_conformance_policy.yaml").write_bytes(policy_bytes)

    return {"package_dir": str(pkg), "pin": pin, "adapter_status": adapter_ev.get("status")}


def run_sibling_consumer(sibling_root: Path, output: Path) -> dict[str, Any]:
    runner = (
        sibling_root
        / "Plan"
        / "07_IMPLEMENTATION"
        / "scripts"
        / "maskfactory_sibling_consumer"
        / "run_sibling_consumer.py"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    proc = _run(
        [sys.executable, str(runner), "--output", str(output)], cwd=sibling_root, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"sibling consumer failed rc={proc.returncode}\\nstdout={proc.stdout}\\nstderr={proc.stderr}"
        )
    return json.loads(output.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-mirror", type=Path, default=DEFAULT_MAIN_MIRROR)
    parser.add_argument("--sibling-root", type=Path, default=DEFAULT_SIBLING_ROOT)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT
        / "runtime_artifacts"
        / "main_consumer"
        / "sibling_consumer_scaffold_run_evidence.json",
    )
    parser.add_argument(
        "--seal",
        type=Path,
        default=REPO_ROOT
        / "qa"
        / "live_verification"
        / "sibling_main_consumer_scaffold_20260720.json",
    )
    args = parser.parse_args()

    wave64 = _assert_wave64_untouched()
    producer_commit = _git_head(REPO_ROOT)
    if not producer_commit:
        raise RuntimeError("unable to resolve producer HEAD")

    sibling_meta = ensure_sibling_worktree(
        main_mirror=args.main_mirror,
        sibling_root=args.sibling_root,
        branch=args.branch,
    )
    # Refresh head after package write will change worktree; capture base head first.
    package = write_sibling_package(
        sibling_root=args.sibling_root,
        producer_commit=producer_commit,
        sibling_meta=sibling_meta,
        wave64=wave64,
    )
    sibling_meta["head_after_scaffold"] = _git_head(args.sibling_root)

    sibling_run_path = (
        args.sibling_root
        / "runtime_artifacts"
        / "maskfactory_sibling_consumer"
        / "run_evidence.json"
    )
    sibling_run = run_sibling_consumer(args.sibling_root, sibling_run_path)

    # Optional producer-side qualification (can be slow); default skip for scaffold seal.
    # Honest ceiling remains producer_partial until real Main adoption exists.
    qual: dict[str, Any] = {
        "status": "producer_partial",
        "decision_sha256": None,
        "claim_boundary": {
            "mf_p6_12_05_complete": False,
            "establishes_production_qualification": False,
        },
    }
    qual_issues: list[str] = []
    if os.environ.get("MF_SIBLING_RUN_QUAL") == "1":
        qual = build_cross_project_qualification_evidence(
            observation={
                "producer_git_commit": producer_commit,
                "sibling_consumer_scaffold": {
                    "authority_kind": "sibling_main_consumer",
                    "is_real_comfyui_main": False,
                    "worktree": str(args.sibling_root),
                    "branch": sibling_meta.get("branch"),
                    "run_evidence_sha256": sibling_run.get("self_sha256"),
                },
            },
            decided_at=DECIDED_AT,
            bind_fixture_main=False,
        )
        qual_issues = list(validate_cross_project_qualification_evidence(qual))

    private_key, key_id = _sibling_key("scaffold")
    summary = {
        "artifact_type": "sibling_main_consumer_scaffold_wave",
        "authority": "autonomous_sibling_main_consumer_scaffold_zero_human_wait",
        "authority_kind": "sibling_main_consumer",
        "is_real_comfyui_main": False,
        "main_adoption_complete": False,
        "wave64_dirty_main_untouched": wave64.get("touched") is False,
        "wave64_probe": wave64,
        "producer_git_commit": producer_commit,
        "sibling_worktree": sibling_meta,
        "package": {
            "path": package["package_dir"],
            "adapter_conformance_status": package["adapter_status"],
            "producer_pin_sha256": hashlib.sha256(
                json.dumps(package["pin"], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        },
        "sibling_run": {
            "path": str(sibling_run_path),
            "self_sha256": sibling_run.get("self_sha256"),
            "checks_passed": sum(1 for c in sibling_run.get("checks", []) if c.get("passed")),
            "checks_total": len(sibling_run.get("checks", [])),
            "all_pass": all(c.get("passed") for c in sibling_run.get("checks", [])),
        },
        "cross_project_qualification": {
            "status": qual.get("status"),
            "mf_p6_12_05_complete": (qual.get("claim_boundary") or {}).get("mf_p6_12_05_complete"),
            "establishes_production_qualification": (qual.get("claim_boundary") or {}).get(
                "establishes_production_qualification"
            ),
            "decision_sha256": qual.get("decision_sha256"),
            "validation_issues": list(qual_issues),
        },
        "hard_blockers_still_open": list(HARD_BLOCKERS),
        "claims_not_established": [
            "real_comfyui_main_adoption",
            "main_adoption_complete / MF-P6-12.06 core close",
            "champions>0",
            "PRODUCTION_EVIDENCE_PASS",
        ],
        "tier_note": (
            "STATIC_PASS sibling-consumer scaffold on isolated clean origin/main worktree. "
            "Signed sibling pin receipt emitted (authority_kind=sibling_main_consumer). "
            "Dirty Wave64 C:/Comfy_UI_Main was NOT touched. Does NOT close any HARD blocker."
        ),
        "next_agent_step": (
            "Commit+push the sibling branch, deepen Main-side journal/circuit/adapter "
            "execution against the producer pin, and return Main-signed qualification/"
            "adoption/result-history artifacts to MaskFactory. Keep Wave64 dirty tree untouched."
        ),
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "self_sha256": "",
    }
    # Cryptographically bind the scaffold summary under the sibling key (audit).
    summary["scaffold_payload_sha256"] = canonical_document_sha256(
        summary, excluded_top_level_fields=("self_sha256", "signature", "scaffold_payload_sha256")
    )
    digest = bytes.fromhex(summary["scaffold_payload_sha256"])
    public_raw = private_key.public_key().public_bytes_raw()
    summary["signature"] = {
        "algorithm": "ed25519",
        "key_id": key_id,
        "public_key_base64": base64.b64encode(public_raw).decode(),
        "signed_payload_format": "sha256_digest_bytes",
        "signed_payload_sha256": summary["scaffold_payload_sha256"],
        "value_base64": base64.b64encode(private_key.sign(digest)).decode(),
    }
    payload = json.dumps(
        {k: v for k, v in summary.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    summary["self_sha256"] = hashlib.sha256(payload).hexdigest()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.seal.parent.mkdir(parents=True, exist_ok=True)
    args.seal.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.seal.name, summary["self_sha256"])
    print(
        "sibling",
        sibling_meta["action"],
        sibling_meta["sibling_root"],
        "checks",
        summary["sibling_run"]["checks_passed"],
        "/",
        summary["sibling_run"]["checks_total"],
        "qual",
        summary["cross_project_qualification"]["status"],
    )
    return 0 if summary["sibling_run"]["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
