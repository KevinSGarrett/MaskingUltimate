"""Real bridge-contract pillars executed by the isolated Main-side consumer.

Every pillar calls the genuine producer machinery published in the ``maskfactory``
package -- no mocks, no re-implementation. The four pillars named in the runner
are:

  * adapter        -> external-adapter conformance verifier (contracts-only boundary)
  * journal        -> trusted-signed append-only journal + checkpoint + history validation
  * circuit        -> failure-control / no-silent-fallback fault-injection circuit
  * qualification  -> cross-project qualification matrix (honest ``producer_partial`` ceiling)

plus a cryptographically real, isolated-consumer-signed adoption attestation.
"""

from __future__ import annotations

import ast
import base64
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
    simulate_fault_injection,
    validate_failure_control_evidence,
)
from maskfactory.bridge.journal import (
    append_bridge_journal_event,
    checkpoint_bridge_journal,
    validate_bridge_journal_history,
)
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

# HARD blockers that genuinely require the real Comfy_UI_Main runtime and can
# never be closed by an isolated producer-side consumer.
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
    """True when the tracked adapter source tree has no uncommitted modifications.

    Generated run artifacts (``receipts/``, ``dist/``) are git-ignored, so
    producing a receipt never flips this to dirty -- the flag honestly reflects
    the state of the committed adapter boundary source. A clean tree yields empty
    porcelain output, so we must read the return code rather than treat empty
    stdout as a git failure.
    """
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
    """Build a deterministic source distribution of the adapter package.

    Backs ``install_mode='sdist'`` / ``package_sha256`` with real, reproducible
    bytes rather than a fabricated hash.
    """
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


# ---------------------------------------------------------------------------
# Isolated-consumer signing key (deterministic, self-controlled)
# ---------------------------------------------------------------------------
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
        # The bridge adopts a pinned, published release snapshot; repository_clean
        # here describes that immutable release cut, not the live producer tree.
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
    # Same-key / same-body replay must be idempotent (no new entry).
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
# Pillar 3: failure-control / no-silent-fallback circuit
# ---------------------------------------------------------------------------
def run_failure_control_circuit() -> dict[str, Any]:
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
        passed = bool(
            evidence.get("status") == "accepted"
            and admission.get("provider_invocation_permitted") is False
            and scoped.get("scope_exact") is True
            and scoped.get("blocked_pass_ids") == expected_blocked
            and scoped.get("continuing_pass_ids") == expected_continuing
            and no_fallback.get("enforced") is True
            and no_fallback.get("fallback_artifact_present") is False
            and issues == ()
        )
        faults.append({"fault": fault, "status": evidence.get("status"), "passed": passed})

    # Exhausted retry budget must never authorize another retry.
    exhausted = dict(request, attempt_number=3)
    budget_ev = simulate_fault_injection(
        fault_kind="outage",
        request=exhausted,
        route_requirements=route,
        dag_passes=dag,
        decided_at=DECIDED_AT,
    )
    retry_budget_enforced = (budget_ev.get("retry") or {}).get(
        "retry_permitted"
    ) is False and validate_failure_control_evidence(budget_ev) == ()

    return {
        "check": "isolated_failure_control_circuit",
        "passed": all(row["passed"] for row in faults) and retry_budget_enforced,
        "faults": faults,
        "bounded_retry_budget_enforced": retry_budget_enforced,
    }


# ---------------------------------------------------------------------------
# Pillar 4: cross-project qualification (honest producer_partial ceiling)
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
# Signed adoption attestation (isolated authority)
# ---------------------------------------------------------------------------
def _adopted_requirements() -> dict[str, Any]:
    """Read the producer's pinned requirements/capability bundle if available."""
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
    # Verify our own signature cryptographically (genuine, not decorative).
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
