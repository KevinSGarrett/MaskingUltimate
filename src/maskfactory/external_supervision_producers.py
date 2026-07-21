"""Project-contained sealed gate producers for MaskedWarehouse external supervision.

Builds license/remap/alignment evidence, materializes hash/identity artifacts under
the project root, and emits an honest gap report when live gates remain incomplete.
External source masks are never MaskFactory gold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .external_supervision import (
    EXTERNAL_LABEL_ROLE,
    PRIVATE_NONCOMMERCIAL_PROFILE,
    TRAIN_PARTITION,
)
from .external_supervision_evidence import (
    CANONICAL_REQUIRED_GATES_BY_SOURCE,
    GATE_ARTIFACT_TYPES,
    SHARED_GATE_SOURCES,
    publish_immutable_evidence,
    seal_payload,
)
from .truth_tiers import WEIGHTED_PSEUDO_LABEL

ELIGIBLE_SOURCES = ("celebamask_hq", "lapa", "lv_mhp_v1")
DEFAULT_OFF_PROJECT_MANIFEST_ROOT = Path(r"C:\MaskFactory_ExternalSupervision\manifests")
DEFAULT_EVIDENCE_ROOT = Path("qa/external_supervision")
DEFAULT_LIVE_ARTIFACT_ROOT = Path("runtime_artifacts/external_supervision")
# Soft floor: keep headroom for OS + parallel work while materializing ~70 MB of manifests.
MIN_FREE_BYTES_FOR_MATERIALIZE = 2 * 1024**3
NEVER_GOLD_AUTHORITIES = frozenset(
    {
        "external_source_masks_never_gold",
        "external_source_maps_never_gold",
    }
)
ALIGNMENT_SOURCE_KEYS: dict[str, frozenset[str]] = {
    "lapa": frozenset({"face_lapa", "lapa"}),
    "lv_mhp_v1": frozenset({"body_lv_mhp_v1", "lv_mhp_v1"}),
    "celebamask_hq": frozenset({"face_celebamask_hq", "celebamask_hq"}),
}
ALIGNMENT_ARTIFACT_PATHS: dict[str, tuple[str, str]] = {
    "lapa": (
        "qa/reports/maskedwarehouse_alignment_manifest.json",
        "qa/reports/maskedwarehouse_alignment_review.json",
    ),
    "lv_mhp_v1": (
        "qa/reports/maskedwarehouse_alignment_manifest.json",
        "qa/reports/maskedwarehouse_alignment_review.json",
    ),
    "celebamask_hq": (
        "qa/reports/celebamask_hq_alignment_manifest.json",
        "qa/reports/celebamask_hq_alignment_review.json",
    ),
}
OFF_PROJECT_MANIFEST_NAMES = {
    "celebamask_hq": "celebamask_hq_source_hash_manifest_v1.json",
    "lapa": "lapa_source_hash_manifest_v1.json",
    "lv_mhp_v1": "lv_mhp_v1_source_hash_manifest_v1.json",
}
OFF_PROJECT_IDENTITY_NAME = "lv_mhp_v1_identity_evidence_v1.json"


class ExternalSupervisionProducerError(ValueError):
    """A sealed gate artifact cannot be produced without violating fail-closed rules."""


@dataclass(frozen=True)
class DiskCapacityAssessment:
    """Local disk check for project-contained materialization."""

    path: str
    free_bytes: int
    required_bytes: int
    feasible: bool
    reason: str


@dataclass(frozen=True)
class MaterializeResult:
    """Result of binding one off-project sealed artifact into the project tree."""

    source: str
    gate: str
    project_relative_path: str
    file_sha256: str
    seal_sha256: str
    method: str


def assess_materialize_capacity(
    target_root: Path,
    *,
    required_bytes: int,
    min_free_bytes: int = MIN_FREE_BYTES_FOR_MATERIALIZE,
) -> DiskCapacityAssessment:
    """Fail closed when the target volume lacks headroom for sealed materialization."""

    root = Path(target_root)
    root.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(root)
    needed = max(required_bytes, 0) + min_free_bytes
    feasible = usage.free >= needed
    reason = (
        "sufficient free space for project-contained sealed artifact materialization"
        if feasible
        else (
            f"insufficient free space: free={usage.free} required_with_floor={needed} "
            f"(artifact_bytes={required_bytes}, floor={min_free_bytes})"
        )
    )
    return DiskCapacityAssessment(
        path=str(root.resolve()),
        free_bytes=usage.free,
        required_bytes=needed,
        feasible=feasible,
        reason=reason,
    )


def build_license_evidence(
    *,
    source: str,
    provenance: Mapping[str, Any],
    inventory: Mapping[str, Any],
) -> dict[str, Any]:
    """Seal official-license evidence from the locked provenance/inventory registries."""

    _require_eligible_source(source)
    _validate_locked_profile(provenance)
    entry = _provenance_entry(provenance, source)
    inventory_entry = _inventory_entry(inventory, source)
    admission = entry.get("training_admission")
    if not isinstance(admission, Mapping):
        raise ExternalSupervisionProducerError(f"{source}: training_admission missing")
    if entry.get("source_role") != EXTERNAL_LABEL_ROLE:
        raise ExternalSupervisionProducerError(f"{source}: source_role must remain external")
    if entry.get("gold_gate") != "blocked_external_source_masks_are_not_gold":
        raise ExternalSupervisionProducerError(f"{source}: gold_gate must stay blocked")
    if "gold_package_inputs" not in set(entry.get("prohibited_uses") or ()):
        raise ExternalSupervisionProducerError(f"{source}: gold_package_inputs must be prohibited")
    if admission.get("truth_tier") != WEIGHTED_PSEUDO_LABEL:
        raise ExternalSupervisionProducerError(f"{source}: truth_tier drift")
    if admission.get("truth_partition") != TRAIN_PARTITION:
        raise ExternalSupervisionProducerError(f"{source}: truth_partition drift")
    if admission.get("holdout_eligible") is not False:
        raise ExternalSupervisionProducerError(f"{source}: holdout must remain ineligible")
    if admission.get("dataset_volume_eligible") is not False:
        raise ExternalSupervisionProducerError(f"{source}: dataset volume must remain ineligible")

    evidence: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": GATE_ARTIFACT_TYPES["official_license_recorded"],
        "source": source,
        "gate": "official_license_recorded",
        "status": "PASS",
        "use_profile_id": PRIVATE_NONCOMMERCIAL_PROFILE,
        "source_role": EXTERNAL_LABEL_ROLE,
        "truth_tier": WEIGHTED_PSEUDO_LABEL,
        "truth_partition": TRAIN_PARTITION,
        "source_masks_are_gold": False,
        "gold_gate": entry["gold_gate"],
        "license_status": entry.get("license_status"),
        "provenance_status": entry.get("provenance_status"),
        "official_source_url": entry.get("official_source_url"),
        "inventory_counts": dict(
            inventory_entry.get("counts") or entry.get("inventory_counts") or {}
        ),
        "provenance_entry_sha256": _mapping_sha256(entry),
        "inventory_entry_sha256": _mapping_sha256(inventory_entry),
    }
    _reject_gold_claims(evidence)
    evidence["seal_sha256"] = seal_payload(evidence)
    return evidence


def build_remap_evidence(
    *,
    source: str,
    remap_plan: Mapping[str, Any],
    remap_path: Path,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Seal deterministic-remap evidence from a never-gold remap plan."""

    _require_eligible_source(source)
    if remap_plan.get("source") != source:
        raise ExternalSupervisionProducerError(f"{source}: remap plan source mismatch")
    authority = remap_plan.get("source_authority")
    if authority not in NEVER_GOLD_AUTHORITIES:
        raise ExternalSupervisionProducerError(
            f"{source}: remap source_authority must declare never-gold"
        )
    if remap_plan.get("training_allowed") is not True:
        raise ExternalSupervisionProducerError(f"{source}: remap training_allowed must be true")
    training_authority = remap_plan.get("training_authority")
    if not isinstance(training_authority, Mapping):
        raise ExternalSupervisionProducerError(f"{source}: remap training_authority missing")
    if training_authority.get("truth_tier") != WEIGHTED_PSEUDO_LABEL:
        raise ExternalSupervisionProducerError(f"{source}: remap truth_tier drift")
    if training_authority.get("truth_partition") != TRAIN_PARTITION:
        raise ExternalSupervisionProducerError(f"{source}: remap truth_partition drift")
    if training_authority.get("holdout_eligible") is not False:
        raise ExternalSupervisionProducerError(f"{source}: remap holdout must remain ineligible")
    path = Path(remap_path)
    readable = path if path.is_absolute() else Path(project_root or Path.cwd()) / path
    raw = readable.read_bytes()
    stored_path = path.as_posix()
    if path.is_absolute() and project_root is not None:
        stored_path = path.resolve(strict=True).relative_to(Path(project_root).resolve()).as_posix()
    evidence: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": GATE_ARTIFACT_TYPES["deterministic_remap_tested"],
        "source": source,
        "gate": "deterministic_remap_tested",
        "status": "PASS",
        "source_authority": authority,
        "source_masks_are_gold": False,
        "remap_plan_path": stored_path,
        "remap_plan_sha256": hashlib.sha256(raw).hexdigest(),
        "training_authority": {
            "truth_tier": training_authority["truth_tier"],
            "truth_partition": training_authority["truth_partition"],
            "loss_weight": training_authority.get("loss_weight"),
            "holdout_eligible": False,
        },
        "mapping_count": len(remap_plan.get("mappings") or {}),
    }
    _reject_gold_claims(evidence)
    evidence["seal_sha256"] = seal_payload(evidence)
    return evidence


def build_alignment_evidence(
    *,
    source: str,
    alignment_manifest: Mapping[str, Any],
    alignment_review: Mapping[str, Any],
) -> dict[str, Any]:
    """Seal visual-alignment evidence only when source-specific QA panels exist."""

    _require_eligible_source(source)
    purpose = str(alignment_manifest.get("purpose") or "")
    if "never gold" not in purpose.casefold():
        raise ExternalSupervisionProducerError(
            f"{source}: alignment manifest must state external masks are never gold"
        )
    if alignment_review.get("status") != "passed":
        raise ExternalSupervisionProducerError(f"{source}: alignment review status is not passed")
    checks = alignment_review.get("checks")
    if not isinstance(checks, Mapping) or checks.get("training_or_gold_admission") is not False:
        raise ExternalSupervisionProducerError(
            f"{source}: alignment review must keep training/gold admission false"
        )
    allowed = ALIGNMENT_SOURCE_KEYS[source]
    if not allowed:
        raise ExternalSupervisionProducerError(
            f"{source}: no sealed visual alignment panels exist for this source"
        )
    records = alignment_manifest.get("records")
    if not isinstance(records, list) or not records:
        raise ExternalSupervisionProducerError(f"{source}: alignment manifest records missing")
    selected = [
        record
        for record in records
        if isinstance(record, Mapping) and str(record.get("source") or "") in allowed
    ]
    if not selected:
        raise ExternalSupervisionProducerError(
            f"{source}: alignment manifest has no panels for this source"
        )
    if any(record.get("dimension_match") is not True for record in selected):
        raise ExternalSupervisionProducerError(f"{source}: alignment dimension mismatch present")

    panel_bindings = [
        {
            "panel_source": record.get("source"),
            "category": record.get("category"),
            "source_sha256": record.get("source_sha256"),
            "mask_sha256": record.get("mask_sha256"),
            "panel_sha256": record.get("panel_sha256"),
            "dimension_match": True,
        }
        for record in selected
    ]
    face_sheet = alignment_review.get("face_contact_sheet_sha256")
    if face_sheet is None:
        face_sheet = alignment_review.get("face_celebamask_hq_contact_sheet_sha256")
    evidence: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": GATE_ARTIFACT_TYPES["visual_alignment_qa_passed"],
        "source": source,
        "gate": "visual_alignment_qa_passed",
        "status": "PASS",
        "source_masks_are_gold": False,
        "alignment_purpose": purpose,
        "review_status": alignment_review.get("status"),
        "face_contact_sheet_sha256": face_sheet,
        "body_contact_sheet_sha256": alignment_review.get("body_contact_sheet_sha256"),
        "panel_count": len(panel_bindings),
        "panels": panel_bindings,
        "manifest_sha256": _mapping_sha256(alignment_manifest),
        "review_sha256": _mapping_sha256(alignment_review),
    }
    _reject_gold_claims(evidence)
    evidence["seal_sha256"] = seal_payload(evidence)
    return evidence


def materialize_sealed_artifact(
    *,
    source: str,
    gate: str,
    source_path: Path,
    destination: Path,
    expected_source: str | None = None,
) -> MaterializeResult:
    """Copy or hardlink a sealed PASS artifact into a project-contained path."""

    _require_eligible_source(source)
    expected_type = GATE_ARTIFACT_TYPES[gate]
    raw = Path(source_path).read_bytes()
    try:
        artifact = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalSupervisionProducerError(f"{source}:{gate}: invalid JSON") from exc
    if not isinstance(artifact, Mapping):
        raise ExternalSupervisionProducerError(f"{source}:{gate}: artifact must be an object")
    bound_source = expected_source or SHARED_GATE_SOURCES.get(gate, source)
    if (
        artifact.get("schema_version") != "1.0.0"
        or artifact.get("artifact_type") != expected_type
        or artifact.get("source") != bound_source
        or artifact.get("gate") != gate
        or artifact.get("status") != "PASS"
        or artifact.get("seal_sha256") != seal_payload(artifact)
    ):
        raise ExternalSupervisionProducerError(
            f"{source}:{gate}: sealed artifact contract or seal failed"
        )
    _reject_gold_claims(artifact)
    capacity = assess_materialize_capacity(destination.parent, required_bytes=len(raw))
    if not capacity.feasible:
        raise ExternalSupervisionProducerError(capacity.reason)

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    method = _link_or_copy(Path(source_path), destination)
    # Re-validate destination bytes match source and remain immutable-publishable.
    published = publish_immutable_evidence(artifact, destination)
    return MaterializeResult(
        source=source,
        gate=gate,
        project_relative_path=destination.as_posix(),
        file_sha256=published,
        seal_sha256=str(artifact["seal_sha256"]),
        method=method,
    )


def publish_gate_artifact(artifact: Mapping[str, Any], output_path: Path) -> str:
    """Publish one producer-built sealed gate artifact immutably."""

    _reject_gold_claims(artifact)
    if artifact.get("seal_sha256") != seal_payload(artifact):
        raise ExternalSupervisionProducerError("artifact seal_sha256 does not match payload")
    if artifact.get("status") != "PASS":
        raise ExternalSupervisionProducerError("only PASS artifacts may be published as gates")
    return publish_immutable_evidence(artifact, output_path)


def build_qualification_gap_report(
    *,
    project_root: Path,
    evidence_root: Path,
    live_artifact_root: Path,
    off_project_manifest_root: Path = DEFAULT_OFF_PROJECT_MANIFEST_ROOT,
) -> dict[str, Any]:
    """Describe which project-contained sealed gates exist versus what still blocks admission."""

    root = Path(project_root).resolve(strict=True)
    evidence = (
        (root / evidence_root).resolve() if not evidence_root.is_absolute() else evidence_root
    )
    live = (
        (root / live_artifact_root).resolve()
        if not live_artifact_root.is_absolute()
        else live_artifact_root
    )
    sources: dict[str, Any] = {}
    for source in ELIGIBLE_SOURCES:
        present: dict[str, Any] = {}
        missing: list[str] = []
        for gate in CANONICAL_REQUIRED_GATES_BY_SOURCE[source]:
            candidates = [
                evidence / source / f"{gate}.json",
                live / source / f"{gate}.json",
                live / "manifests" / f"{source}_{gate}.json",
            ]
            if gate == "split_dedup_passed":
                candidates.extend(
                    [
                        evidence / "shared" / f"{gate}.json",
                        live / "shared" / f"{gate}.json",
                    ]
                )
            found = next((path for path in candidates if path.is_file()), None)
            if found is None:
                missing.append(gate)
                continue
            try:
                relative = found.resolve(strict=True).relative_to(root).as_posix()
            except ValueError:
                missing.append(gate)
                continue
            present[gate] = {
                "path": relative,
                "file_sha256": hashlib.sha256(found.read_bytes()).hexdigest(),
            }
        off_manifest = off_project_manifest_root / OFF_PROJECT_MANIFEST_NAMES[source]
        sources[source] = {
            "present_gates": present,
            "missing_gates": missing,
            "off_project_manifest_available": off_manifest.is_file(),
            "off_project_manifest_path": str(off_manifest) if off_manifest.is_file() else None,
            "admission_ready": not missing,
            "source_masks_are_gold": False,
        }
    identity_off = off_project_manifest_root / OFF_PROJECT_IDENTITY_NAME
    capacity = assess_materialize_capacity(
        live,
        required_bytes=sum(
            (off_project_manifest_root / name).stat().st_size
            for name in OFF_PROJECT_MANIFEST_NAMES.values()
            if (off_project_manifest_root / name).is_file()
        ),
    )
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "external_supervision_qualification_gap_report",
        "use_profile_id": PRIVATE_NONCOMMERCIAL_PROFILE,
        "source_masks_are_gold": False,
        "gold_authority_granted": False,
        "holdout_authority_granted": False,
        "any_source_admitted": False,
        "disk_capacity": {
            "path": capacity.path,
            "free_bytes": capacity.free_bytes,
            "required_bytes": capacity.required_bytes,
            "feasible": capacity.feasible,
            "reason": capacity.reason,
        },
        "off_project_identity_available": identity_off.is_file(),
        "blockers": _collect_blockers(sources, capacity, identity_off.is_file()),
        "sources": sources,
    }
    report["seal_sha256"] = seal_payload(report)
    return report


def produce_project_contained_evidence(
    *,
    project_root: Path,
    provenance_path: Path | None = None,
    inventory_path: Path | None = None,
    remap_root: Path | None = None,
    alignment_manifest_path: Path | None = None,
    alignment_review_path: Path | None = None,
    off_project_manifest_root: Path = DEFAULT_OFF_PROJECT_MANIFEST_ROOT,
    evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
    live_artifact_root: Path = DEFAULT_LIVE_ARTIFACT_ROOT,
    materialize_live_manifests: bool = True,
    materialize_identity: bool = True,
) -> dict[str, Any]:
    """Produce sealed project-contained gate artifacts and a gap report."""

    root = Path(project_root).resolve(strict=True)
    provenance_path = provenance_path or root / "configs" / "maskedwarehouse_provenance.yaml"
    inventory_path = inventory_path or root / "configs" / "maskedwarehouse_inventory.json"
    remap_root = remap_root or root / "configs" / "remap"
    provenance = yaml.safe_load(provenance_path.read_text(encoding="utf-8"))
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))

    published: dict[str, Any] = {"sources": {}, "materialized": [], "errors": []}
    evidence_base = root / evidence_root
    live_base = root / live_artifact_root

    for source in ELIGIBLE_SOURCES:
        source_dir = evidence_base / source
        source_dir.mkdir(parents=True, exist_ok=True)
        source_published: dict[str, str] = {}
        try:
            license_artifact = build_license_evidence(
                source=source, provenance=provenance, inventory=inventory
            )
            license_path = source_dir / "official_license_recorded.json"
            publish_gate_artifact(license_artifact, license_path)
            source_published["official_license_recorded"] = license_path.relative_to(
                root
            ).as_posix()
        except (ExternalSupervisionProducerError, OSError, KeyError, TypeError) as exc:
            published["errors"].append(f"{source}:official_license_recorded:{exc}")

        try:
            remap_path = Path(remap_root) / f"{source}.yaml"
            remap_plan = yaml.safe_load(remap_path.read_text(encoding="utf-8"))
            relative_remap = Path(remap_path.resolve(strict=True).relative_to(root).as_posix())
            remap_artifact = build_remap_evidence(
                source=source,
                remap_plan=remap_plan,
                remap_path=relative_remap,
                project_root=root,
            )
            remap_out = source_dir / "deterministic_remap_tested.json"
            publish_gate_artifact(remap_artifact, remap_out)
            source_published["deterministic_remap_tested"] = remap_out.relative_to(root).as_posix()
        except (ExternalSupervisionProducerError, OSError, KeyError, TypeError, ValueError) as exc:
            published["errors"].append(f"{source}:deterministic_remap_tested:{exc}")

        try:
            manifest_rel, review_rel = ALIGNMENT_ARTIFACT_PATHS[source]
            if alignment_manifest_path is not None and source != "celebamask_hq":
                source_manifest_path = Path(alignment_manifest_path)
            else:
                source_manifest_path = root / manifest_rel
            if alignment_review_path is not None and source != "celebamask_hq":
                source_review_path = Path(alignment_review_path)
            else:
                source_review_path = root / review_rel
            alignment_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
            alignment_review = json.loads(source_review_path.read_text(encoding="utf-8"))
            alignment_artifact = build_alignment_evidence(
                source=source,
                alignment_manifest=alignment_manifest,
                alignment_review=alignment_review,
            )
            alignment_out = source_dir / "visual_alignment_qa_passed.json"
            publish_gate_artifact(alignment_artifact, alignment_out)
            source_published["visual_alignment_qa_passed"] = alignment_out.relative_to(
                root
            ).as_posix()
        except (ExternalSupervisionProducerError, OSError, KeyError, TypeError) as exc:
            published["errors"].append(f"{source}:visual_alignment_qa_passed:{exc}")

        if materialize_live_manifests:
            off_path = Path(off_project_manifest_root) / OFF_PROJECT_MANIFEST_NAMES[source]
            if off_path.is_file():
                try:
                    dest = live_base / source / "source_hash_manifested.json"
                    result = materialize_sealed_artifact(
                        source=source,
                        gate="source_hash_manifested",
                        source_path=off_path,
                        destination=dest,
                    )
                    # Store project-relative path in result for consumers.
                    relative = dest.resolve(strict=True).relative_to(root).as_posix()
                    published["materialized"].append(
                        {
                            "source": source,
                            "gate": "source_hash_manifested",
                            "path": relative,
                            "file_sha256": result.file_sha256,
                            "seal_sha256": result.seal_sha256,
                            "method": result.method,
                        }
                    )
                    source_published["source_hash_manifested"] = relative
                except (ExternalSupervisionProducerError, OSError, ValueError) as exc:
                    published["errors"].append(f"{source}:source_hash_manifested:{exc}")
            else:
                published["errors"].append(
                    f"{source}:source_hash_manifested:off-project manifest missing: {off_path}"
                )

        published["sources"][source] = source_published

    if materialize_identity:
        identity_off = Path(off_project_manifest_root) / OFF_PROJECT_IDENTITY_NAME
        if identity_off.is_file():
            try:
                dest = live_base / "lv_mhp_v1" / "instance_identity_validated.json"
                result = materialize_sealed_artifact(
                    source="lv_mhp_v1",
                    gate="instance_identity_validated",
                    source_path=identity_off,
                    destination=dest,
                )
                relative = dest.resolve(strict=True).relative_to(root).as_posix()
                published["materialized"].append(
                    {
                        "source": "lv_mhp_v1",
                        "gate": "instance_identity_validated",
                        "path": relative,
                        "file_sha256": result.file_sha256,
                        "seal_sha256": result.seal_sha256,
                        "method": result.method,
                    }
                )
                published["sources"].setdefault("lv_mhp_v1", {})[
                    "instance_identity_validated"
                ] = relative
            except (ExternalSupervisionProducerError, OSError, ValueError) as exc:
                published["errors"].append(f"lv_mhp_v1:instance_identity_validated:{exc}")
        else:
            published["errors"].append(
                f"lv_mhp_v1:instance_identity_validated:off-project identity missing: {identity_off}"
            )

    gap = build_qualification_gap_report(
        project_root=root,
        evidence_root=evidence_root,
        live_artifact_root=live_artifact_root,
        off_project_manifest_root=Path(off_project_manifest_root),
    )
    gap_path = evidence_base / "qualification_gap_report.json"
    # Gap reports are regenerable status ledgers (not admission seals).
    _publish_regenerable_gap_report(
        gap, gap_path, archive_root=evidence_base / "gap_report_archive"
    )
    published["gap_report_path"] = gap_path.relative_to(root).as_posix()
    published["gap_report_seal_sha256"] = gap["seal_sha256"]
    published["any_source_admitted"] = False
    published["source_masks_are_gold"] = False
    return published


def build_deterministic_fixture_gate_set(tmp_root: Path, source: str) -> dict[str, Path]:
    """Create minimal sealed PASS gate artifacts for unit tests (not live admission)."""

    _require_eligible_source(source)
    paths: dict[str, Path] = {}
    source_dir = Path(tmp_root) / source
    source_dir.mkdir(parents=True, exist_ok=True)
    for gate in CANONICAL_REQUIRED_GATES_BY_SOURCE[source]:
        artifact = {
            "schema_version": "1.0.0",
            "artifact_type": GATE_ARTIFACT_TYPES[gate],
            "source": SHARED_GATE_SOURCES.get(gate, source),
            "gate": gate,
            "status": "PASS",
            "source_masks_are_gold": False,
            "fixture": True,
        }
        _reject_gold_claims(artifact)
        artifact["seal_sha256"] = seal_payload(artifact)
        path = source_dir / f"{gate}.json"
        publish_gate_artifact(artifact, path)
        paths[gate] = path.relative_to(tmp_root)
    return paths


def _collect_blockers(
    sources: Mapping[str, Any], capacity: DiskCapacityAssessment, identity_available: bool
) -> list[str]:
    blockers: list[str] = []
    if not capacity.feasible:
        blockers.append(f"disk_capacity:{capacity.reason}")
    for source, info in sources.items():
        for gate in info["missing_gates"]:
            blockers.append(f"{source}:missing_gate:{gate}")
        if source == "celebamask_hq" and "visual_alignment_qa_passed" in info["missing_gates"]:
            blockers.append(
                "celebamask_hq:visual_alignment_qa_passed:"
                "bounded CelebAMask-HQ contact-sheet/panel QA not sealed under "
                "qa/reports/celebamask_hq_alignment_*"
            )
        if "split_dedup_passed" in info["missing_gates"]:
            blockers.append(
                f"{source}:split_dedup_passed:"
                "full ~57k cross-source dHash deferred per "
                "Plan/MASKEDWAREHOUSE_SPLIT_DEDUP_STRATEGY.md; "
                "STATIC sample/strategy receipt is not admission"
            )
    if not identity_available and "instance_identity_validated" in sources.get("lv_mhp_v1", {}).get(
        "missing_gates", ()
    ):
        blockers.append("lv_mhp_v1:instance_identity_validated:off-project identity unavailable")
    # Deduplicate while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for item in blockers:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _publish_regenerable_gap_report(
    gap: Mapping[str, Any],
    gap_path: Path,
    *,
    archive_root: Path,
) -> str:
    """Publish current gap report; archive prior distinct bytes instead of failing closed."""

    payload = (
        json.dumps(gap, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")
    path = Path(gap_path)
    if path.exists() and path.read_bytes() != payload:
        previous = json.loads(path.read_text(encoding="utf-8"))
        previous_seal = str(
            previous.get("seal_sha256") or hashlib.sha256(path.read_bytes()).hexdigest()
        )
        archive_root = Path(archive_root)
        archive_root.mkdir(parents=True, exist_ok=True)
        archive_path = archive_root / f"{previous_seal[:24]}.json"
        if not archive_path.exists():
            archive_path.write_bytes(path.read_bytes())
        path.unlink()
    return publish_immutable_evidence(gap, path)


def _link_or_copy(source: Path, destination: Path) -> str:
    if destination.exists():
        if destination.read_bytes() == source.read_bytes():
            return "already_identical"
        raise ExternalSupervisionProducerError(
            f"destination already exists with different bytes: {destination}"
        )
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.partial")
    try:
        try:
            os.link(source, temporary)
            method = "hardlink"
        except OSError:
            shutil.copy2(source, temporary)
            method = "copy"
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return method


def _reject_gold_claims(artifact: Mapping[str, Any]) -> None:
    forbidden_true = (
        "source_masks_are_gold",
        "gold_authority_granted",
        "holdout_authority_granted",
        "dataset_volume_eligible",
        "training_or_gold_admission",
    )
    for key in forbidden_true:
        if artifact.get(key) is True:
            raise ExternalSupervisionProducerError(
                f"fail-closed: artifact must not claim {key}=true"
            )
    text_blobs = []
    for key in ("truth_tier", "source_role", "source_authority", "gold_gate", "status_label"):
        value = artifact.get(key)
        if isinstance(value, str):
            text_blobs.append(value.casefold())
    joined = " ".join(text_blobs)
    if "maskfactory gold" in joined or joined.strip() == "gold":
        raise ExternalSupervisionProducerError(
            "fail-closed: external source masks must not be labeled MaskFactory gold"
        )


def _validate_locked_profile(provenance: Mapping[str, Any]) -> None:
    profile = provenance.get("project_use_profile")
    if not isinstance(profile, Mapping) or profile.get("id") != PRIVATE_NONCOMMERCIAL_PROFILE:
        raise ExternalSupervisionProducerError("locked private/noncommercial profile missing")
    policy = provenance.get("policy")
    if not isinstance(policy, Mapping) or policy.get("source_masks_are_gold") is not False:
        raise ExternalSupervisionProducerError("policy.source_masks_are_gold must be false")


def _require_eligible_source(source: str) -> None:
    if source not in ELIGIBLE_SOURCES:
        raise ExternalSupervisionProducerError(
            f"source is not an eligible external source: {source}"
        )


def _provenance_entry(provenance: Mapping[str, Any], source: str) -> Mapping[str, Any]:
    sources = provenance.get("sources")
    if not isinstance(sources, Mapping) or source not in sources:
        raise ExternalSupervisionProducerError(f"{source}: missing provenance entry")
    entry = sources[source]
    if not isinstance(entry, Mapping):
        raise ExternalSupervisionProducerError(f"{source}: provenance entry malformed")
    return entry


def _inventory_entry(inventory: Mapping[str, Any], source: str) -> Mapping[str, Any]:
    raw = inventory.get("sources")
    if not isinstance(raw, list):
        raise ExternalSupervisionProducerError("inventory sources malformed")
    for item in raw:
        if isinstance(item, Mapping) and item.get("source") == source:
            return item
    raise ExternalSupervisionProducerError(f"{source}: missing inventory entry")


def _mapping_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--off-project-manifest-root",
        type=Path,
        default=DEFAULT_OFF_PROJECT_MANIFEST_ROOT,
    )
    parser.add_argument("--skip-live-manifests", action="store_true")
    parser.add_argument("--skip-identity", action="store_true")
    args = parser.parse_args(argv)
    result = produce_project_contained_evidence(
        project_root=args.project_root,
        off_project_manifest_root=args.off_project_manifest_root,
        materialize_live_manifests=not args.skip_live_manifests,
        materialize_identity=not args.skip_identity,
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ALIGNMENT_ARTIFACT_PATHS",
    "ALIGNMENT_SOURCE_KEYS",
    "DEFAULT_EVIDENCE_ROOT",
    "DEFAULT_LIVE_ARTIFACT_ROOT",
    "DEFAULT_OFF_PROJECT_MANIFEST_ROOT",
    "DiskCapacityAssessment",
    "ELIGIBLE_SOURCES",
    "ExternalSupervisionProducerError",
    "MaterializeResult",
    "MIN_FREE_BYTES_FOR_MATERIALIZE",
    "assess_materialize_capacity",
    "build_alignment_evidence",
    "build_deterministic_fixture_gate_set",
    "build_license_evidence",
    "build_qualification_gap_report",
    "build_remap_evidence",
    "materialize_sealed_artifact",
    "produce_project_contained_evidence",
    "publish_gate_artifact",
]
