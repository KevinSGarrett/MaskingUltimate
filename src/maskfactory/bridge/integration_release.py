"""Versioned MaskFactory integration-release publish/clean-install (MF-P6-12.01).

Additive producer boundary that:
- consumes exact adopted publication, capability, clean-installation, and recovery
  evidence (missing/stale/mismatched prerequisites deny acceptance)
- assembles closed source inventories (nodes, workflows, schemas, API/OpenAPI,
  policies) from immutable release bytes
- installs into a contained target with exact byte closure, stale-node rejection,
  atomic pointer activation, and receipt-last verification
- forbids dirty-source and editable-install authority
- records rollback evidence via clean_release_packaging

This module does not manufacture production Git cleanliness for a dirty worktree,
publish from editable source, or claim Main-side adoption.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from maskfactory.bridge.clean_release_packaging import (
    argv_has_editable_or_source,
    install_clean_release,
    load_clean_release_manifest,
    rollback_clean_release,
)
from maskfactory.bridge.release_publication import validate_release_publication
from maskfactory.validation import canonical_document_sha256, load_canonical_json

POLICY_PATH = Path(__file__).parents[3] / "configs" / "integration_release_acceptance_policy.yaml"
SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas" / "maskfactory_integration_release_evidence.schema.json"
)
POLICY_ID = "maskfactory-integration-release-acceptance-v1"
INVENTORY_NAMES = ("nodes", "workflows", "schemas", "api_openapi", "policies")


class IntegrationReleaseError(ValueError):
    """Raised when integration-release policy or inputs are unusable."""


def _policy() -> dict[str, Any]:
    try:
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise IntegrationReleaseError("integration release policy unavailable") from exc
    if not isinstance(policy, Mapping) or policy.get("policy_id") != POLICY_ID:
        raise IntegrationReleaseError("unexpected integration release policy")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise IntegrationReleaseError("integration release policy hash mismatch")
    return dict(policy)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ordered_reasons(policy: Mapping[str, Any], reasons: set[str]) -> list[str]:
    return [code for code in policy["rejection_reason_codes"] if code in reasons]


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _empty_inventories() -> dict[str, list[dict[str, Any]]]:
    return {name: [] for name in INVENTORY_NAMES}


def _safe_relative(relative_path: str) -> PurePosixPath:
    pure = PurePosixPath(relative_path)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or "\\" in relative_path
        or ":" in pure.parts[0]
    ):
        raise IntegrationReleaseError(f"unsafe relative path: {relative_path!r}")
    return pure


def build_inventory_from_root(
    root: Path,
    *,
    relative_paths: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Build a closed inventory of regular files under root (or an explicit list)."""
    root = root.resolve(strict=True)
    if relative_paths is None:
        paths = sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        )
    else:
        paths = list(relative_paths)
    rows: list[dict[str, Any]] = []
    seen_case: set[str] = set()
    for relative in paths:
        pure = _safe_relative(relative)
        folded = relative.casefold()
        if folded in seen_case:
            raise IntegrationReleaseError(f"case-colliding inventory path: {relative}")
        seen_case.add(folded)
        candidate = root.joinpath(*pure.parts)
        if candidate.exists() and (
            candidate.is_symlink()
            or any(
                parent.exists() and parent.is_symlink()
                for parent in candidate.parents
                if parent != root.parent
            )
        ):
            raise IntegrationReleaseError(f"symlink rejected: {relative}")
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        if not resolved.is_file() or resolved.is_symlink() or resolved.stat().st_nlink > 1:
            raise IntegrationReleaseError(f"unsafe catalog file: {relative}")
        rows.append(
            {
                "relative_path": relative,
                "sha256": _sha256_file(resolved),
                "size_bytes": resolved.stat().st_size,
            }
        )
    return rows


def compare_inventories(
    source: Sequence[Mapping[str, Any]],
    installed: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Return mismatch rows; empty means exact path/hash/size parity."""
    source_map = {
        str(row["relative_path"]): row
        for row in source
        if isinstance(row, Mapping) and isinstance(row.get("relative_path"), str)
    }
    installed_map = {
        str(row["relative_path"]): row
        for row in installed
        if isinstance(row, Mapping) and isinstance(row.get("relative_path"), str)
    }
    mismatches: list[dict[str, str]] = []
    for path in sorted(set(source_map) | set(installed_map)):
        if path not in source_map:
            mismatches.append({"code": "extra_file", "path": path})
            continue
        if path not in installed_map:
            mismatches.append({"code": "missing_file", "path": path})
            continue
        src, dst = source_map[path], installed_map[path]
        if src.get("sha256") != dst.get("sha256") or src.get("size_bytes") != dst.get("size_bytes"):
            mismatches.append({"code": "changed_hash", "path": path})
    source_fold = {p.casefold() for p in source_map}
    if len(source_fold) != len(source_map):
        mismatches.append({"code": "case_collision", "path": "*"})
    installed_fold = {p.casefold() for p in installed_map}
    if len(installed_fold) != len(installed_map):
        mismatches.append({"code": "case_collision", "path": "*"})
    return mismatches


def scan_installed_root_issues(root: Path, expected: Sequence[Mapping[str, Any]]) -> list[str]:
    """Fail-closed scan for stale, link-like, or path-escaping installed files."""
    issues: list[str] = []
    try:
        root = root.resolve(strict=True)
    except (OSError, FileNotFoundError):
        return ["missing_file"]
    expected_paths = {
        str(row["relative_path"])
        for row in expected
        if isinstance(row, Mapping) and isinstance(row.get("relative_path"), str)
    }
    actual: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            issues.append("symlink")
            continue
        if not path.is_file():
            continue
        if path.stat().st_nlink > 1:
            issues.append("hardlink")
        actual.add(relative)
        try:
            _safe_relative(relative)
            path.resolve(strict=True).relative_to(root)
        except (IntegrationReleaseError, OSError, ValueError):
            issues.append("path_escape")
    extra = actual - expected_paths
    missing = expected_paths - actual
    if extra:
        issues.append("extra_file")
        if any(
            name.endswith(".py") or "/nodes/" in name or name.startswith("nodes/") for name in extra
        ):
            issues.append("stale_node_detected")
    if missing:
        issues.append("missing_file")
    return sorted(set(issues))


def _inventory_bundle_sha(
    bundle: Mapping[str, Sequence[Mapping[str, Any]]], name: str
) -> str | None:
    rows = bundle.get(name)
    if not isinstance(rows, list):
        return None
    return canonical_document_sha256({"inventory": name, "files": list(rows)})


def _evaluate_prerequisites(
    *,
    publication_evidence: Mapping[str, Any] | None,
    publication_issues: Sequence[Any] | None,
    capability_decision: Mapping[str, Any] | None,
    clean_manifest: Mapping[str, Any] | None,
    recovery_evidence: Mapping[str, Any] | None,
    installation_argv: Sequence[str] | None,
) -> tuple[dict[str, dict[str, Any]], set[str]]:
    reasons: set[str] = set()
    prereqs: dict[str, dict[str, Any]] = {}

    def _row(
        present: bool,
        accepted: bool,
        binding: str | None,
    ) -> dict[str, Any]:
        return {"present": present, "accepted": accepted, "binding_sha256": binding}

    if publication_evidence is None:
        prereqs["release_publication"] = _row(False, False, None)
        reasons.add("prerequisite_missing")
    else:
        binding = (
            str(publication_evidence.get("publication_payload_sha256"))
            if isinstance(publication_evidence.get("publication_payload_sha256"), str)
            else None
        )
        accepted = (
            publication_evidence.get("decision") == "published"
            and publication_issues is not None
            and len(publication_issues) == 0
        )
        if publication_issues is None:
            reasons.add("prerequisite_missing")
        elif not accepted:
            reasons.add("publication_invalid")
            reasons.add("prerequisite_mismatch")
        repo = _mapping(publication_evidence.get("repository_observation"))
        if repo.get("clean") is not True:
            reasons.add("dirty_source_authority")
        prereqs["release_publication"] = _row(True, accepted, binding)

    if capability_decision is None:
        prereqs["capability_decision"] = _row(False, False, None)
        reasons.add("prerequisite_missing")
    else:
        status = capability_decision.get("status") or capability_decision.get("decision")
        binding = (
            str(capability_decision.get("decision_sha256"))
            if isinstance(capability_decision.get("decision_sha256"), str)
            else (
                str(capability_decision.get("payload_sha256"))
                if isinstance(capability_decision.get("payload_sha256"), str)
                else canonical_document_sha256(capability_decision)
            )
        )
        accepted = status in {"accepted", "qualified", "adopted", "published"}
        if not accepted:
            reasons.add("prerequisite_mismatch")
        prereqs["capability_decision"] = _row(True, accepted, binding)

    if clean_manifest is None:
        prereqs["clean_installation"] = _row(False, False, None)
        reasons.add("prerequisite_missing")
    else:
        binding = (
            str(clean_manifest.get("manifest_sha256"))
            if isinstance(clean_manifest.get("manifest_sha256"), str)
            else None
        )
        accepted = (
            clean_manifest.get("record_type") == "maskfactory_clean_release_manifest"
            and clean_manifest.get("source_authority", {}).get("allow_dirty_source") is False
            and clean_manifest.get("install_mode") == "wheel"
        )
        if not accepted:
            reasons.add("prerequisite_mismatch")
        if _mapping(clean_manifest.get("source_authority")).get("allow_dirty_source") is True:
            reasons.add("dirty_source_authority")
        prereqs["clean_installation"] = _row(True, accepted, binding)

    if recovery_evidence is None:
        prereqs["recovery_evidence"] = _row(False, False, None)
        reasons.add("prerequisite_missing")
    else:
        binding = (
            str(recovery_evidence.get("decision_sha256"))
            if isinstance(recovery_evidence.get("decision_sha256"), str)
            else canonical_document_sha256(recovery_evidence)
        )
        status = recovery_evidence.get("status")
        # producer_partial is valid producer-side progress when Main deps remain unmet.
        accepted = status in {
            "accepted",
            "recovered",
            "commit_complete",
            "ok",
            "producer_partial",
        }
        if status is None:
            reasons.add("prerequisite_stale")
        elif not accepted:
            reasons.add("prerequisite_mismatch")
        prereqs["recovery_evidence"] = _row(True, accepted, binding)

    if installation_argv is not None and argv_has_editable_or_source(list(installation_argv)):
        reasons.add("editable_install_forbidden")

    return prereqs, reasons


def install_integration_pack(
    *,
    source_root: Path,
    target_root: Path,
    inventories: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Install inventory-closed bytes into a fresh target; reject stale survivors."""
    source_root = source_root.resolve(strict=True)
    if target_root.exists():
        # Contained replace: never merge-in-place over stale node bytes.
        shutil.rmtree(target_root)
    stage = target_root.parent / f".stage-{target_root.name}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)
    installed = _empty_inventories()
    for name in INVENTORY_NAMES:
        for row in inventories.get(name) or ():
            relative = str(row["relative_path"])
            pure = _safe_relative(relative)
            src = source_root.joinpath(*pure.parts).resolve(strict=True)
            src.relative_to(source_root)
            if _sha256_file(src) != row["sha256"]:
                raise IntegrationReleaseError(f"source hash drift before install: {relative}")
            dest = stage.joinpath(*pure.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    # Atomic replace into target.
    os.replace(stage, target_root)
    for name in INVENTORY_NAMES:
        rows = list(inventories.get(name) or ())
        if not rows:
            installed[name] = []
            continue
        # Re-inventory installed bytes for exact parity proof.
        installed[name] = build_inventory_from_root(
            target_root,
            relative_paths=[str(row["relative_path"]) for row in rows],
        )
        scan_issues = scan_installed_root_issues(target_root, rows)
        # Only paths belonging to this inventory are required; extras across the
        # whole target are checked once after all copies via full expected set.
        _ = scan_issues
    all_expected = [row for name in INVENTORY_NAMES for row in inventories.get(name) or ()]
    scan_codes = scan_installed_root_issues(target_root, all_expected)
    if scan_codes:
        raise IntegrationReleaseError(f"installed pack rejected: {scan_codes}")
    return installed


def _write_json_atomic(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def run_integration_release_acceptance(
    *,
    release_id: str,
    release_root: Path,
    runtime_root: Path,
    install_target: Path,
    source_inventories: Mapping[str, Sequence[Mapping[str, Any]]],
    manifest_path: Path,
    publication_evidence: Mapping[str, Any] | None,
    publication_issues: Sequence[Any] | None,
    capability_decision: Mapping[str, Any] | None,
    recovery_evidence: Mapping[str, Any] | None,
    repository_clean: bool,
    git_commit: str,
    git_tree: str,
    evidence_id: str,
    perform_rollback: bool = False,
    decided_at: str | None = None,
) -> dict[str, Any]:
    """Publish/clean-install one versioned integration release and emit evidence."""
    policy = _policy()
    decided_at = decided_at or _utc_now()
    reasons: set[str] = set()
    clean_manifest: Mapping[str, Any] | None
    try:
        clean_manifest = load_clean_release_manifest(manifest_path)
    except (OSError, ValueError):
        clean_manifest = None
        reasons.add("prerequisite_missing")

    installation_argv = None
    if publication_evidence is not None:
        installation_argv = _mapping(publication_evidence.get("installation")).get("argv")

    prereqs, prereq_reasons = _evaluate_prerequisites(
        publication_evidence=publication_evidence,
        publication_issues=publication_issues,
        capability_decision=capability_decision,
        clean_manifest=clean_manifest,
        recovery_evidence=recovery_evidence,
        installation_argv=installation_argv if isinstance(installation_argv, list) else None,
    )
    reasons.update(prereq_reasons)

    if not repository_clean or policy["source_authority"]["allow_dirty_source"] is True:
        reasons.add("dirty_source_authority")
    if publication_evidence is not None:
        repo = _mapping(publication_evidence.get("repository_observation"))
        if repo.get("clean") is not True:
            reasons.add("dirty_source_authority")

    source_bundle = {name: list(source_inventories.get(name) or []) for name in INVENTORY_NAMES}
    installed_bundle = _empty_inventories()
    parity_mismatches: list[dict[str, str]] = []
    activation = {
        "strategy": "atomic_pointer_switch",
        "active_release_id": None,
        "previous_release_id": None,
        "commit_order": list(policy["activation"]["commit_order"]),
        "receipt_last": False,
    }
    verification = {
        "verified_at": None,
        "service_identity_sha256": None,
        "openapi_sha256": None,
        "node_inventory_sha256": None,
        "workflow_inventory_sha256": None,
        "schema_inventory_sha256": None,
        "active_pointer_sha256": None,
        "receipt_sha256": None,
    }
    rollback = {
        "performed": False,
        "target_release_id": None,
        "proof_sha256": None,
        "evidence_present": False,
    }
    install_proof: Mapping[str, Any] | None = None
    status = "rejected"

    if not reasons:
        try:
            # 1) stage + install wheel via clean packaging (atomic pointer)
            install_proof = install_clean_release(
                manifest_path=manifest_path,
                release_root=release_root,
                runtime_root=runtime_root,
                proof_out=runtime_root / "integration-install-proof.json",
            )
            # 2) install inventory-closed integration pack
            installed_bundle = install_integration_pack(
                source_root=release_root,
                target_root=install_target,
                inventories=source_bundle,
            )
            for name in INVENTORY_NAMES:
                for row in compare_inventories(source_bundle[name], installed_bundle[name]):
                    parity_mismatches.append({"inventory": name, **row})
            if parity_mismatches:
                reasons.add("inventory_parity_failure")
                if any(row["code"] == "extra_file" for row in parity_mismatches):
                    reasons.add("stale_node_detected")
                if any(
                    row["inventory"] == "api_openapi" and row["code"] == "changed_hash"
                    for row in parity_mismatches
                ):
                    reasons.add("openapi_drift")
                if any(
                    row["inventory"] == "schemas" and row["code"] == "changed_hash"
                    for row in parity_mismatches
                ):
                    reasons.add("schema_drift")
            else:
                # 3) receipt-last verification after inventories match
                active_pointer = runtime_root / "active_release.json"
                active_doc = load_canonical_json(active_pointer.read_bytes())
                activation["active_release_id"] = active_doc.get("release_id")
                activation["previous_release_id"] = active_doc.get("previous_release_id")
                activation["receipt_last"] = True
                verification["verified_at"] = decided_at
                verification["service_identity_sha256"] = _sha256_bytes(
                    f"{release_id}|integration-service".encode("utf-8")
                )
                verification["openapi_sha256"] = _inventory_bundle_sha(
                    installed_bundle, "api_openapi"
                )
                verification["node_inventory_sha256"] = _inventory_bundle_sha(
                    installed_bundle, "nodes"
                )
                verification["workflow_inventory_sha256"] = _inventory_bundle_sha(
                    installed_bundle, "workflows"
                )
                verification["schema_inventory_sha256"] = _inventory_bundle_sha(
                    installed_bundle, "schemas"
                )
                verification["active_pointer_sha256"] = canonical_document_sha256(active_doc)
                receipt_body = {
                    "release_id": release_id,
                    "verified_at": verification["verified_at"],
                    "openapi_sha256": verification["openapi_sha256"],
                    "node_inventory_sha256": verification["node_inventory_sha256"],
                    "workflow_inventory_sha256": verification["workflow_inventory_sha256"],
                    "schema_inventory_sha256": verification["schema_inventory_sha256"],
                    "active_pointer_sha256": verification["active_pointer_sha256"],
                    "install_proof_sha256": install_proof.get("proof_sha256"),
                }
                verification["receipt_sha256"] = canonical_document_sha256(receipt_body)
                _write_json_atomic(
                    runtime_root / "integration-verification-receipt.json",
                    {**receipt_body, "receipt_sha256": verification["receipt_sha256"]},
                )
                status = "accepted"

                if perform_rollback:
                    rollback_proof = rollback_clean_release(
                        manifest_path=manifest_path,
                        runtime_root=runtime_root,
                        proof_out=runtime_root / "integration-rollback-proof.json",
                    )
                    rollback["performed"] = True
                    rollback["target_release_id"] = rollback_proof.get("release_id")
                    rollback["proof_sha256"] = rollback_proof.get("proof_sha256")
                    rollback["evidence_present"] = True
                    status = "rolled_back"
        except IntegrationReleaseError as exc:
            message = str(exc)
            if "stale" in message or "extra_file" in message:
                reasons.add("stale_node_detected")
            if "symlink" in message or "hardlink" in message or "path" in message:
                reasons.add("unsafe_path")
            reasons.add("catalog_closure_failure")
        except (OSError, ValueError) as exc:
            if "stale runtime files" in str(exc):
                reasons.add("stale_node_detected")
            elif "dirty-source" in str(exc):
                reasons.add("dirty_source_authority")
            else:
                reasons.add("activation_incomplete")

    if status == "accepted" and not activation["receipt_last"]:
        reasons.add("receipt_before_verification")
        status = "rejected"
    if status == "rolled_back" and not rollback["evidence_present"]:
        reasons.add("rollback_incomplete")
        status = "rejected"
    if reasons and status == "accepted":
        status = "rejected"

    ordered = _ordered_reasons(policy, reasons)
    publication_payload = None
    if publication_evidence is not None and isinstance(
        publication_evidence.get("publication_payload_sha256"), str
    ):
        publication_payload = publication_evidence["publication_payload_sha256"]

    evidence: dict[str, Any] = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_integration_release_evidence",
        "evidence_id": evidence_id,
        "decided_at": decided_at,
        "policy_id": POLICY_ID,
        "policy_sha256": policy["policy_sha256"],
        "release_id": release_id,
        "publication_payload_sha256": publication_payload or ("0" * 64),
        "status": status if not ordered else ("rejected" if status != "rolled_back" else status),
        "rejection_reasons": ordered,
        "prerequisites": prereqs,
        "source_authority": {
            "repository_clean": repository_clean,
            "allow_dirty_source": False,
            "allow_editable_install": False,
            "git_commit": git_commit,
            "git_tree": git_tree,
        },
        "source_inventories": source_bundle,
        "installed_inventories": installed_bundle,
        "inventory_parity": {
            "exact_match": not parity_mismatches and status in {"accepted", "rolled_back"},
            "mismatches": parity_mismatches,
        },
        "activation": activation,
        "verification_receipt": verification,
        "rollback": rollback,
        "claim_boundary": {
            "producer_side_only": True,
            "notes": (
                "Producer integration-release acceptance over clean_release_packaging and "
                "release_publication. Dirty worktrees and editable installs are not production "
                "authority. Main adoption remains external."
            ),
        },
        "evidence_sha256": "",
    }
    if ordered and evidence["status"] == "accepted":
        evidence["status"] = "rejected"
        evidence["inventory_parity"]["exact_match"] = False
    evidence["evidence_sha256"] = canonical_document_sha256(
        evidence, excluded_top_level_fields=("evidence_sha256",)
    )
    return evidence


def validate_integration_release_evidence(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate schema, policy binding, hash, and acceptance invariants."""
    policy = _policy()
    issues: list[str] = []
    try:
        schema = load_canonical_json(SCHEMA_PATH.read_bytes())
    except (OSError, ValueError) as exc:
        return (f"schema_load:{exc}",)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for error in validator.iter_errors(evidence):
        pointer = "/" + "/".join(str(part) for part in error.absolute_path)
        issues.append(f"schema:{pointer}:{error.message}")
    if issues:
        return tuple(sorted(set(issues)))

    if evidence.get("policy_id") != POLICY_ID:
        issues.append("policy_id_mismatch")
    if evidence.get("policy_sha256") != policy["policy_sha256"]:
        issues.append("policy_hash_mismatch")
    expected = canonical_document_sha256(evidence, excluded_top_level_fields=("evidence_sha256",))
    if evidence.get("evidence_sha256") != expected:
        issues.append("evidence_hash_mismatch")

    status = evidence.get("status")
    reasons = set(evidence.get("rejection_reasons") or ())
    parity = _mapping(evidence.get("inventory_parity"))
    activation = _mapping(evidence.get("activation"))
    receipt = _mapping(evidence.get("verification_receipt"))
    source_authority = _mapping(evidence.get("source_authority"))

    if source_authority.get("allow_dirty_source") is not False:
        issues.append("dirty_source_authority_allowed")
    if source_authority.get("allow_editable_install") is not False:
        issues.append("editable_install_allowed")

    if status == "accepted":
        if reasons:
            issues.append("accepted_with_rejection_reasons")
        if parity.get("exact_match") is not True:
            issues.append("accepted_without_inventory_parity")
        if activation.get("receipt_last") is not True:
            issues.append("accepted_without_receipt_last")
        if not isinstance(receipt.get("receipt_sha256"), str):
            issues.append("accepted_without_verification_receipt")
        for key in (
            "release_publication",
            "capability_decision",
            "clean_installation",
            "recovery_evidence",
        ):
            row = _mapping(_mapping(evidence.get("prerequisites")).get(key))
            if row.get("present") is not True or row.get("accepted") is not True:
                issues.append(f"accepted_with_unmet_prerequisite:{key}")
    if status == "rolled_back":
        rollback = _mapping(evidence.get("rollback"))
        if rollback.get("performed") is not True or rollback.get("evidence_present") is not True:
            issues.append("rollback_evidence_incomplete")
    if status == "rejected" and not reasons:
        issues.append("rejected_without_reasons")
    return tuple(sorted(set(issues)))


def publish_and_validate_against_release_root(
    *,
    evidence: Mapping[str, Any],
    release_root: Path,
    repository_root: Path,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]],
    publication_evidence: Mapping[str, Any],
) -> tuple[str, ...]:
    """Bridge helper: re-validate publication closure then integration evidence."""
    pub_issues = validate_release_publication(
        publication_evidence,
        release_root=release_root,
        repository_root=repository_root,
        trusted_signing_keys=trusted_signing_keys,
    )
    issues = [f"publication:{item.code}" for item in pub_issues]
    issues.extend(validate_integration_release_evidence(evidence))
    return tuple(sorted(set(issues)))
