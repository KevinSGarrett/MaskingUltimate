"""Fail-closed execution preflight for the frozen Mode A/Mode B workflow run."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from PIL import Image

from ..providers.selection import validate_provider_selection
from ..truth_tiers import TruthTierError, normalize_truth_tier
from ..validation import ArtifactValidationError, require_valid_document
from .workflow_performance import (
    DEFAULT_POLICY,
    ROLLBACK_ROLES,
    WorkflowPerformanceError,
    canonical_sha256,
    file_sha256,
    load_policy,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = ROOT / "models" / "model_registry.json"
DEFAULT_PIPELINE = ROOT / "configs" / "pipeline.yaml"
DEFAULT_EXTERNAL_REGISTRY = ROOT / "configs" / "external_sources.yaml"
DEFAULT_PACKAGES_ROOT = ROOT / "data" / "packages"
AUTHORITY = (
    "execution_preflight_only_no_serving_mutation_mask_truth_gold_"
    "promotion_or_completion_authority"
)
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class WorkflowPreflightError(ValueError):
    """The workflow execution input or local control plane cannot be trusted."""


def package_tree_sha256(package_root: Path) -> str:
    """Hash every package-relative file path and byte identity deterministically."""
    root = Path(package_root).resolve()
    if not root.is_dir():
        raise WorkflowPreflightError(f"package root is missing: {root}")
    rows = [
        {"path": path.relative_to(root).as_posix(), "sha256": file_sha256(path)}
        for path in sorted(root.rglob("*"), key=lambda value: value.as_posix())
        if path.is_file()
    ]
    if not rows:
        raise WorkflowPreflightError(f"package root is empty: {root}")
    return canonical_sha256(rows)


def _path(value: Any, root: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise WorkflowPreflightError("artifact path is empty")
    candidate = Path(value)
    return (candidate if candidate.is_absolute() else Path(root) / candidate).resolve()


def _finding(findings: list[dict[str, str]], code: str, subject: str, detail: str) -> None:
    findings.append({"code": code, "subject": subject, "detail": detail})


def _load_json(path: Path, subject: str, findings: list[dict[str, str]]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _finding(findings, "json_unreadable", subject, str(exc))
        return None
    if not isinstance(value, dict):
        _finding(findings, "json_not_object", subject, "artifact must be a JSON object")
        return None
    return value


def _file_identity(path: Path, *, subject: str, findings: list[dict[str, str]]) -> str | None:
    try:
        return file_sha256(path)
    except OSError as exc:
        _finding(findings, "control_plane_artifact_unreadable", subject, str(exc))
        return None


def _artifact(
    row: Mapping[str, Any],
    *,
    path_key: str,
    digest_key: str,
    root: Path,
    subject: str,
    findings: list[dict[str, str]],
) -> Path | None:
    path = _path(row[path_key], root)
    if not path.is_file():
        _finding(findings, "artifact_missing", subject, str(path))
        return None
    actual = file_sha256(path)
    if actual != row[digest_key]:
        _finding(
            findings, "artifact_hash_mismatch", subject, f"expected {row[digest_key]}, got {actual}"
        )
        return None
    return path


def _manifest_truth_tier(manifest: Mapping[str, Any]) -> str:
    explicit = manifest.get("truth_tier")
    if isinstance(explicit, str):
        return normalize_truth_tier(explicit)
    statuses = {
        str(value.get("status"))
        for value in manifest.get("parts", {}).values()
        if isinstance(value, Mapping) and value.get("status") != "n/a"
    }
    if statuses and statuses <= {"human_approved_gold", "human_anchor_gold"}:
        return "human_anchor_gold"
    if statuses and statuses <= {"autonomous_certified_gold"}:
        return "autonomous_certified_gold"
    raise TruthTierError("package manifest has no single eligible truth tier")


def _audit_sources(
    rows: Sequence[Mapping[str, Any]],
    *,
    policy: Mapping[str, Any],
    root: Path,
    packages_root: Path,
    output_root: Path,
    findings: list[dict[str, str]],
) -> None:
    if tuple(row["scope"] for row in rows) != ("single_person", "multi_person"):
        _finding(
            findings,
            "source_scope_order_invalid",
            "sources",
            "expected single_person then multi_person",
        )
    if len({row["source_id"] for row in rows}) != 2 or len({row["image_id"] for row in rows}) != 2:
        _finding(
            findings,
            "source_identity_not_distinct",
            "sources",
            "source_id and image_id must be distinct",
        )
    if len({row["image_sha256"] for row in rows}) != 2:
        _finding(
            findings, "source_images_not_disjoint", "sources", "source image hashes must differ"
        )
    package_roots: list[Path] = []
    for row in rows:
        subject = str(row["source_id"])
        limits = policy["source_scopes"][row["scope"]]
        if not limits["minimum_people"] <= row["person_count"] <= limits["maximum_people"]:
            _finding(findings, "person_count_outside_scope", subject, str(row["person_count"]))
        image_path = _artifact(
            row,
            path_key="image_path",
            digest_key="image_sha256",
            root=root,
            subject=f"{subject}.image",
            findings=findings,
        )
        if image_path is not None:
            try:
                with Image.open(image_path) as opened:
                    opened.verify()
                    if opened.width < 1 or opened.height < 1:
                        raise ValueError("empty raster")
            except (OSError, ValueError) as exc:
                _finding(findings, "source_image_unreadable", subject, str(exc))
        governance_path = _artifact(
            row,
            path_key="governance_decision_path",
            digest_key="governance_decision_sha256",
            root=root,
            subject=f"{subject}.governance",
            findings=findings,
        )
        if governance_path is not None:
            governance = _load_json(governance_path, f"{subject}.governance", findings)
            if governance is not None:
                expected = {
                    "source_id": row["source_id"],
                    "scope": row["scope"],
                    "people": row["person_count"],
                }
                for key, expected_value in expected.items():
                    if governance.get(key) != expected_value:
                        _finding(
                            findings,
                            "governance_source_mismatch",
                            subject,
                            f"{key}: expected {expected_value!r}, got {governance.get(key)!r}",
                        )
                for key in ("rights", "content_lane"):
                    if not isinstance(governance.get(key), str) or not governance[key]:
                        _finding(
                            findings,
                            "governance_decision_incomplete",
                            subject,
                            f"missing non-empty {key}",
                        )
        manifest_path = _artifact(
            row,
            path_key="package_manifest_path",
            digest_key="package_manifest_sha256",
            root=root,
            subject=f"{subject}.package_manifest",
            findings=findings,
        )
        if manifest_path is None:
            continue
        package_root = manifest_path.parent.resolve()
        package_roots.append(package_root)
        try:
            package_root.relative_to(packages_root)
        except ValueError:
            _finding(findings, "package_outside_truth_root", subject, str(package_root))
        manifest = _load_json(manifest_path, f"{subject}.package_manifest", findings)
        if manifest is not None:
            try:
                observed_tier = _manifest_truth_tier(manifest)
            except TruthTierError as exc:
                _finding(findings, "package_truth_tier_ineligible", subject, str(exc))
            else:
                if observed_tier != row["truth_tier"]:
                    _finding(
                        findings,
                        "package_truth_tier_mismatch",
                        subject,
                        f"declared {row['truth_tier']}, observed {observed_tier}",
                    )
        try:
            tree_digest = package_tree_sha256(package_root)
        except WorkflowPreflightError as exc:
            _finding(findings, "package_tree_unreadable", subject, str(exc))
        else:
            if tree_digest != row["package_tree_sha256"]:
                _finding(
                    findings,
                    "package_tree_hash_mismatch",
                    subject,
                    f"expected {row['package_tree_sha256']}, got {tree_digest}",
                )
    try:
        output_root.relative_to(packages_root)
    except ValueError:
        pass
    else:
        _finding(findings, "output_inside_truth_root", "output_root", str(output_root))
    for package_root in package_roots:
        if output_root == package_root or package_root in output_root.parents:
            _finding(findings, "output_inside_package", "output_root", str(output_root))


def _all_hashes(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        return {item for child in value.values() for item in _all_hashes(child)}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return {item for child in value for item in _all_hashes(child)}
    return {value} if isinstance(value, str) and _SHA256.fullmatch(value) else set()


def _certificate_passes(document: Mapping[str, Any], role: str, claimed_sha256: str) -> bool:
    payload = {key: value for key, value in document.items() if key != "sha256"}
    results = document.get("hard_bucket_results")
    return bool(
        document.get("sha256") == claimed_sha256 == canonical_sha256(payload)
        and document.get("target_role") == role
        and document.get("primary_win_or_labor_reduction") is True
        and isinstance(results, list)
        and results
        and all(isinstance(row, Mapping) and row.get("passed") is True for row in results)
    )


def _provider_entry_for_alias(
    alias: str,
    *,
    pipeline: Mapping[str, Any],
    model_entries: Mapping[str, Mapping[str, Any]],
    external_entries: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    catalog = pipeline.get("provider_catalog", {})
    pointer = catalog.get(alias) if isinstance(catalog, Mapping) else None
    if not isinstance(pointer, Mapping):
        return None
    key = pointer.get("key")
    if pointer.get("registry") == "model_registry":
        return model_entries.get(str(key))
    if pointer.get("registry") == "external_sources":
        return external_entries.get(str(key))
    return None


def _audit_roles(
    bindings: Sequence[Mapping[str, Any]],
    *,
    root: Path,
    registry_path: Path,
    pipeline_path: Path,
    external_registry_path: Path,
    findings: list[dict[str, str]],
) -> None:
    if tuple(row["role"] for row in bindings) != ROLLBACK_ROLES:
        _finding(findings, "role_binding_order_invalid", "role_bindings", str(list(ROLLBACK_ROLES)))
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        pipeline = yaml.safe_load(pipeline_path.read_text(encoding="utf-8"))
        external = yaml.safe_load(external_registry_path.read_text(encoding="utf-8"))
        selection = validate_provider_selection(
            pipeline,
            external_registry_path=external_registry_path,
            model_registry_path=registry_path,
        )
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        _finding(findings, "control_plane_unreadable", "role_bindings", str(exc))
        return
    model_entries = {str(row["key"]): row for row in registry.get("models", [])}
    external_entries = external.get("providers", {}) if isinstance(external, Mapping) else {}
    for binding in bindings:
        role = str(binding["role"])
        active_key = str(binding["active_provider"])
        rollback_key = str(binding["rollback_provider"])
        if active_key == rollback_key:
            _finding(findings, "rollback_provider_not_distinct", role, active_key)
        if not str(binding["rollback_command"]).startswith("maskfactory "):
            _finding(
                findings, "rollback_command_not_governed", role, str(binding["rollback_command"])
            )
        active_checkpoint_path = _artifact(
            binding,
            path_key="active_checkpoint_path",
            digest_key="active_checkpoint_sha256",
            root=root,
            subject=f"{role}.active_checkpoint",
            findings=findings,
        )
        _artifact(
            binding,
            path_key="active_runtime_path",
            digest_key="active_runtime_sha256",
            root=root,
            subject=f"{role}.active_runtime",
            findings=findings,
        )
        certificate_path = _artifact(
            binding,
            path_key="benchmark_certificate_path",
            digest_key="benchmark_certificate_file_sha256",
            root=root,
            subject=f"{role}.benchmark_certificate",
            findings=findings,
        )
        if certificate_path is not None:
            certificate = _load_json(certificate_path, f"{role}.benchmark_certificate", findings)
            if certificate is not None and not _certificate_passes(
                certificate, role, str(binding["benchmark_certificate_sha256"])
            ):
                _finding(findings, "benchmark_certificate_not_passing", role, str(certificate_path))
        rollback_path = _artifact(
            binding,
            path_key="rollback_checkpoint_path",
            digest_key="rollback_checkpoint_sha256",
            root=root,
            subject=f"{role}.rollback_checkpoint",
            findings=findings,
        )
        if role == "interactive_segmenter":
            active = _provider_entry_for_alias(
                active_key,
                pipeline=pipeline,
                model_entries=model_entries,
                external_entries=external_entries,
            )
            rollback = _provider_entry_for_alias(
                rollback_key,
                pipeline=pipeline,
                model_entries=model_entries,
                external_entries=external_entries,
            )
            if selection["active"].get(role) != active_key:
                _finding(findings, "active_provider_selection_mismatch", role, active_key)
            if selection["rollback"].get(role) != rollback_key:
                _finding(findings, "rollback_provider_selection_mismatch", role, rollback_key)
        else:
            active_matches = [row for row in model_entries.values() if row.get("role") == role]
            active = active_matches[0] if len(active_matches) == 1 else None
            rollback = model_entries.get(rollback_key)
            if active is None or active.get("key") != active_key:
                _finding(findings, "active_provider_selection_mismatch", role, active_key)
        if active is None:
            _finding(findings, "active_provider_missing", role, active_key)
        else:
            if (
                active.get("lifecycle_state") != binding["active_lifecycle_state"]
                or active.get("lifecycle_state") != "promoted"
            ):
                _finding(
                    findings, "active_lifecycle_mismatch", role, str(active.get("lifecycle_state"))
                )
            if active.get("sha256") != binding["active_checkpoint_sha256"]:
                _finding(
                    findings, "active_checkpoint_identity_mismatch", role, str(active.get("sha256"))
                )
            if active_checkpoint_path is not None and file_sha256(
                active_checkpoint_path
            ) != active.get("sha256"):
                _finding(
                    findings,
                    "active_checkpoint_registry_file_mismatch",
                    role,
                    str(active_checkpoint_path),
                )
            if binding["active_runtime_sha256"] not in _all_hashes(active):
                _finding(
                    findings,
                    "active_runtime_identity_missing",
                    role,
                    str(binding["active_runtime_sha256"]),
                )
            registry_certificate = active.get("benchmark_certificate")
            if (
                not isinstance(registry_certificate, Mapping)
                or registry_certificate.get("sha256") != binding["benchmark_certificate_sha256"]
            ):
                _finding(
                    findings,
                    "active_certificate_registry_mismatch",
                    role,
                    str(binding["benchmark_certificate_sha256"]),
                )
        if rollback is None:
            _finding(findings, "rollback_provider_missing", role, rollback_key)
        else:
            if rollback.get("lifecycle_state") != binding["rollback_lifecycle_state"]:
                _finding(
                    findings,
                    "rollback_lifecycle_mismatch",
                    role,
                    str(rollback.get("lifecycle_state")),
                )
            if rollback.get("lifecycle_state") not in {"benchmarked", "promoted"}:
                _finding(
                    findings,
                    "rollback_lifecycle_ineligible",
                    role,
                    str(rollback.get("lifecycle_state")),
                )
            if rollback.get("sha256") != binding["rollback_checkpoint_sha256"]:
                _finding(
                    findings,
                    "rollback_checkpoint_identity_mismatch",
                    role,
                    str(rollback.get("sha256")),
                )
            if rollback_path is not None and file_sha256(rollback_path) != rollback.get("sha256"):
                _finding(
                    findings, "rollback_checkpoint_registry_file_mismatch", role, str(rollback_path)
                )


def preflight_workflow_execution(
    document: Mapping[str, Any],
    *,
    artifact_root: Path = ROOT,
    policy_path: Path = DEFAULT_POLICY,
    registry_path: Path = DEFAULT_REGISTRY,
    pipeline_path: Path = DEFAULT_PIPELINE,
    external_registry_path: Path = DEFAULT_EXTERNAL_REGISTRY,
    packages_root: Path = DEFAULT_PACKAGES_ROOT,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    """Return a sealed readiness report without launching models or mutating state."""
    value = dict(document)
    try:
        require_valid_document(value, "serving_workflow_execution_input")
    except ArtifactValidationError as exc:
        raise WorkflowPreflightError(str(exc)) from exc
    payload = {key: item for key, item in value.items() if key != "sha256"}
    if value["sha256"] != canonical_sha256(payload):
        raise WorkflowPreflightError("workflow execution input seal mismatch")
    try:
        policy = load_policy(Path(policy_path))
    except WorkflowPerformanceError as exc:
        raise WorkflowPreflightError(str(exc)) from exc
    if value["policy_sha256"] != policy["sha256"]:
        raise WorkflowPreflightError("workflow execution input policy binding mismatch")
    parsed = urlsplit(value["api_url"])
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise WorkflowPreflightError("workflow API URL must be loopback HTTP")
    root = Path(artifact_root).resolve()
    package_root = Path(packages_root).resolve()
    output_root = _path(value["output_root"], root)
    findings: list[dict[str, str]] = []
    _audit_sources(
        value["sources"],
        policy=policy,
        root=root,
        packages_root=package_root,
        output_root=output_root,
        findings=findings,
    )
    _audit_roles(
        value["role_bindings"],
        root=root,
        registry_path=Path(registry_path).resolve(),
        pipeline_path=Path(pipeline_path).resolve(),
        external_registry_path=Path(external_registry_path).resolve(),
        findings=findings,
    )
    control_plane = {
        "registry_sha256": _file_identity(
            Path(registry_path), subject="model_registry", findings=findings
        ),
        "pipeline_sha256": _file_identity(
            Path(pipeline_path), subject="pipeline", findings=findings
        ),
        "external_registry_sha256": _file_identity(
            Path(external_registry_path), subject="external_registry", findings=findings
        ),
    }
    findings.sort(key=lambda row: (row["code"], row["subject"], row["detail"]))
    timestamp = (checked_at or datetime.now(UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "checked_at": timestamp,
        "ready": not findings,
        "policy_sha256": policy["sha256"],
        "input_sha256": value["sha256"],
        "control_plane": control_plane,
        "coverage": {
            "source_scopes": [row["scope"] for row in value["sources"]],
            "case_ids": [row["case_id"] for row in policy["cases"]],
            "rollback_roles": [row["role"] for row in value["role_bindings"]],
        },
        "findings": findings,
        "authority": AUTHORITY,
    }
    report["sha256"] = canonical_sha256(report)
    try:
        require_valid_document(report, "serving_workflow_preflight_report")
    except ArtifactValidationError as exc:
        raise WorkflowPreflightError(f"internal preflight report is invalid: {exc}") from exc
    return report


__all__ = [
    "AUTHORITY",
    "WorkflowPreflightError",
    "package_tree_sha256",
    "preflight_workflow_execution",
]
