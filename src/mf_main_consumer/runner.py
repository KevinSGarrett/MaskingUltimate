"""Runner: execute the four bridge pillars and emit one sealed receipt.

The receipt is labeled ``authority_kind = isolated_main_consumer`` and records,
in the clear, that it is NOT the real Comfy_UI_Main runtime and that the HARD
blockers requiring real Main remain OPEN. The MaskFactory tracker can credit it
honestly as isolated-consumer progress (STATIC_PASS depth), never as a HARD close.
"""

from __future__ import annotations

# Ensures ``maskfactory`` is importable from the sibling producer repo.
from . import ensure_producer_importable  # noqa: F401  (import side effect)

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .pillars import (
    DECIDED_AT,
    HARD_BLOCKERS_REQUIRING_REAL_MAIN,
    consumer_git_head,
    run_adapter_conformance,
    run_adoption_attestation,
    run_cross_project_qualification,
    run_failure_control_circuit,
    run_signed_journal,
)
from .producer_bridge import producer_git_head, producer_root, producer_worktree_dirty

CONSUMER_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = CONSUMER_ROOT / "receipts"

PILLARS: tuple[tuple[str, Callable[[], dict[str, Any]]], ...] = (
    ("isolated_adapter_conformance", run_adapter_conformance),
    ("isolated_signed_journal", run_signed_journal),
    ("isolated_failure_control_circuit", run_failure_control_circuit),
    ("isolated_cross_project_producer_partial", run_cross_project_qualification),
    ("isolated_adoption_attestation_signed", run_adoption_attestation),
)


def _check_error(name: str, exc: Exception) -> dict[str, Any]:
    return {"check": name, "passed": False, "error": repr(exc)}


def build_receipt() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for name, runner in PILLARS:
        try:
            checks.append(runner())
        except Exception as exc:  # honest failure capture
            checks.append(_check_error(name, exc))

    receipt: dict[str, Any] = {
        "artifact_type": "isolated_main_consumer_run",
        "schema_version": "1.0.0",
        "consumer_project": "Comfy_UI_Main_MaskFactory_Consumer",
        "consumer_version": __version__,
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "decided_at": DECIDED_AT,
        "authority_kind": "isolated_main_consumer",
        "is_real_comfyui_main": False,
        "consumer_git_commit": consumer_git_head(),
        "producer_repo": str(producer_root()),
        "producer_git_commit": producer_git_head(),
        "live_producer_worktree_dirty": producer_worktree_dirty(),
        "checks": checks,
        "summary": {check["check"]: check["passed"] for check in checks},
        "claim_boundary": {
            "isolated_consumer_is_not_fixture_authority": True,
            "isolated_consumer_is_not_real_comfyui_main": True,
            "main_adoption_complete": False,
            "establishes_production_qualification": False,
            "advances": [
                "MF-P6-11.01 (external MaskFactoryAdapter boundary: contracts-only "
                "imports accepted by the producer conformance verifier, real sdist "
                "package hash + git identity, no node-id / mutable-path / internal coupling)",
                "MF-P6-11.06 (trusted-signed append-only journal + checkpoint + history "
                "validation + same-key/same-body replay idempotency, real machinery)",
                "MF-P6-11.07 (failure-control circuit: fault-injection provider refusal, "
                "exact scoped-DAG blocking, bounded-retry-budget, no-silent-fallback)",
                "MF-P6-12.05 (producer_partial cross-project qualification matrix, real "
                "execution, honest ceiling)",
                "adoption attestation (isolated-consumer-signed, real Ed25519, "
                "explicitly not a comfy-main-* Main trust key)",
            ],
            "hard_blockers_still_open": list(HARD_BLOCKERS_REQUIRING_REAL_MAIN),
            "advances_are_isolated_consumer_only": True,
            "does_not_close_any_hard_blocker": True,
            "next_agent_step": (
                "Real HARD-close receipts require the actual Comfy_UI_Main runtime to "
                "consume this adapter package and emit Main-trust-key-signed "
                "adoption/qualification/adapter-execution/result-history artifacts. "
                "Comfy_UI_Main is a dirty Wave64 tree and was NOT touched."
            ),
        },
    }
    payload = json.dumps(
        {k: v for k, v in receipt.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    receipt["self_sha256"] = hashlib.sha256(payload).hexdigest()
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to write the sealed receipt (default: receipts/<timestamp>.json)",
    )
    args = parser.parse_args(argv)

    receipt = build_receipt()
    output = args.output
    if output is None:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = DEFAULT_OUTPUT_DIR / f"isolated_main_consumer_run_{ts}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    all_passed = all(check["passed"] for check in receipt["checks"])
    print(json.dumps(receipt["summary"], sort_keys=True))
    print(f"receipt: {output}")
    print(f"self_sha256: {receipt['self_sha256']}")
    print(f"all_pillars_passed: {all_passed}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
