"""STATIC train-only packaging and external-label batch-cap enforcement.

MF-P9-13.06 / MF-P9-13.07 host-side contracts. Fixture evidence may satisfy
gates for hermetic tests; live warehouse admission and gold remain refused.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from PIL import Image

from .external_supervision import (
    EXTERNAL_LABEL_ROLE,
    TRAIN_PARTITION,
    ExternalSupervisionError,
    load_external_supervision_registry,
)
from .external_supervision_evidence import (
    CANONICAL_REQUIRED_GATES_BY_SOURCE,
    canonical_json_sha256,
    publish_immutable_evidence,
)
from .external_supervision_holdout_ablation import (
    ExternalHoldoutAblationError,
    active_scope_keys,
    assert_only_ablation_active_external_rows,
    require_ablation_report,
)
from .external_supervision_qualification import verify_external_qualification_evidence
from .io.png_strict import write_label_map
from .truth_tiers import (
    AUTONOMOUS_CERTIFIED_GOLD,
    HUMAN_ANCHOR_GOLD,
    WEIGHTED_PSEUDO_LABEL,
)

PROOF_TIER = "STATIC_PASS"
AUTHORITY = "external_supervision_package_static_only_no_live_admission"
LIVE_PROOF_TIER = "LIVE_PASS"
LIVE_AUTHORITY = "external_supervision_train_only_live_qualified"
DEFAULT_MAXIMUM_COMBINED_EXTERNAL_BATCH_FRACTION = 0.35


class ExternalSupervisionPackageError(ValueError):
    """Qualified external package or batch-cap contract violated."""


@dataclass(frozen=True)
class ExternalPackageSelection:
    """One converted external sample eligible for train-only packaging."""

    source: str
    image_id: str
    part_map: np.ndarray
    material_map: np.ndarray
    label_names: tuple[str, ...]
    training_loss_weight: float
    source_rgb: np.ndarray | None = None
    source_sha256: str | None = None
    source_relative_path: str | None = None
    annotation_sha256: str | None = None
    annotation_relative_path: str | None = None
    split_group_id: str | None = None


def maximum_combined_external_batch_fraction(
    registry: Mapping[str, Any] | None = None,
) -> float:
    if registry is None:
        return DEFAULT_MAXIMUM_COMBINED_EXTERNAL_BATCH_FRACTION
    policy = registry.get("policy")
    if not isinstance(policy, Mapping):
        raise ExternalSupervisionPackageError("external registry policy missing")
    value = policy.get("maximum_combined_external_batch_fraction")
    if not isinstance(value, (int, float)) or not 0 < float(value) < 0.5:
        raise ExternalSupervisionPackageError("external batch cap invalid")
    return float(value)


def is_external_labeled_row(row: Mapping[str, Any]) -> bool:
    return row.get("source_role") == EXTERNAL_LABEL_ROLE


def is_certified_real_row(row: Mapping[str, Any]) -> bool:
    if is_external_labeled_row(row):
        return False
    return row.get("truth_tier") in {HUMAN_ANCHOR_GOLD, AUTONOMOUS_CERTIFIED_GOLD}


def require_external_package_qualification(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    """Fail closed unless an external package binds admitted qualification evidence."""

    source_role = manifest.get("source_role")
    lineage = manifest.get("source_lineage")
    if isinstance(lineage, Mapping) and lineage.get("kind") == EXTERNAL_LABEL_ROLE:
        source_role = EXTERNAL_LABEL_ROLE
    if source_role != EXTERNAL_LABEL_ROLE:
        raise ExternalSupervisionPackageError(
            "manifest is not an external_labeled_reference package"
        )
    qualification = manifest.get("external_qualification")
    if not isinstance(qualification, Mapping):
        raise ExternalSupervisionPackageError(
            "ungated external package: qualification binding missing"
        )
    if qualification.get("admitted") is not True:
        raise ExternalSupervisionPackageError("ungated external package: not admitted")
    if qualification.get("truth_tier") != WEIGHTED_PSEUDO_LABEL:
        raise ExternalSupervisionPackageError(
            "external package truth_tier must be weighted_pseudo_label"
        )
    if qualification.get("truth_partition") != TRAIN_PARTITION:
        raise ExternalSupervisionPackageError("external package must be train-only")
    if qualification.get("holdout_eligible") is not False:
        raise ExternalSupervisionPackageError("external package must set holdout_eligible=false")
    if qualification.get("dataset_volume_eligible") is not False:
        raise ExternalSupervisionPackageError(
            "external package must set dataset_volume_eligible=false"
        )
    if qualification.get("counts_as_human_anchor_gold") not in {None, False}:
        raise ExternalSupervisionPackageError("external package cannot claim human-anchor gold")
    if qualification.get("counts_as_autonomous_certified_gold") not in {None, False}:
        raise ExternalSupervisionPackageError("external package cannot claim certified gold")
    source = qualification.get("source")
    if not isinstance(source, str) or not source:
        raise ExternalSupervisionPackageError("external qualification source missing")
    if not isinstance(qualification.get("evidence_bundle_sha256"), str):
        raise ExternalSupervisionPackageError("external qualification evidence hash missing")
    gates = qualification.get("completed_gates")
    if not isinstance(gates, list) or not gates:
        raise ExternalSupervisionPackageError("external qualification completed_gates missing")
    return qualification


def assert_builder_accepts_only_gated_external_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    ablation_report: Mapping[str, Any] | None = None,
) -> None:
    """Builder-side refuse of ungated external labeled rows."""

    materialized = list(rows)
    for row in materialized:
        if not is_external_labeled_row(row):
            continue
        if row.get("external_qualification_admitted") is not True:
            raise ExternalSupervisionPackageError(
                f"builder refused ungated external row: {row.get('image_id', '<unknown>')}"
            )
        if row.get("truth_tier") != WEIGHTED_PSEUDO_LABEL:
            raise ExternalSupervisionPackageError("builder refused non-pseudo external row")
        if row.get("truth_partition") != TRAIN_PARTITION:
            raise ExternalSupervisionPackageError("builder refused non-train external row")
        if row.get("dataset_volume_eligible") is not False:
            raise ExternalSupervisionPackageError("builder refused volume-eligible external row")
    try:
        assert_only_ablation_active_external_rows(materialized, ablation_report)
    except ExternalHoldoutAblationError as exc:
        raise ExternalSupervisionPackageError(str(exc)) from exc


def assert_launcher_accepts_only_gated_external_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    ablation_report: Mapping[str, Any] | None = None,
) -> None:
    """Launcher-side refuse of ungated external labeled rows."""

    materialized = list(rows)
    for row in materialized:
        if not is_external_labeled_row(row):
            continue
        if row.get("external_qualification_admitted") is not True:
            raise ExternalSupervisionPackageError(
                f"launcher refused ungated external row: {row.get('image_id', '<unknown>')}"
            )
        if row.get("truth_tier") != WEIGHTED_PSEUDO_LABEL:
            raise ExternalSupervisionPackageError("launcher refused non-pseudo external row")
        if row.get("truth_partition") != TRAIN_PARTITION:
            raise ExternalSupervisionPackageError("launcher refused non-train external row")
        weight = row.get("training_loss_weight")
        if not isinstance(weight, (int, float)) or not 0.10 <= float(weight) <= 0.25:
            raise ExternalSupervisionPackageError(
                "launcher refused external weight outside 0.10..0.25"
            )
    try:
        assert_only_ablation_active_external_rows(materialized, ablation_report)
    except ExternalHoldoutAblationError as exc:
        raise ExternalSupervisionPackageError(str(exc)) from exc


def validate_external_batch_cap(
    records: Iterable[Mapping[str, Any]],
    *,
    maximum_fraction: float | None = None,
    registry: Mapping[str, Any] | None = None,
) -> dict[str, int | float | bool]:
    """Enforce combined external-label batch cap and certified-real dominance."""

    cap = (
        float(maximum_fraction)
        if maximum_fraction is not None
        else maximum_combined_external_batch_fraction(registry)
    )
    if not 0 < cap < 0.5:
        raise ExternalSupervisionPackageError("external batch cap must be in (0, 0.5)")

    by_image: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(records):
        image_id = row.get("image_id")
        if not isinstance(image_id, str) or not image_id:
            image_id = f"row_{index}"
        previous = by_image.get(image_id)
        if previous is not None and bool(is_external_labeled_row(previous)) != bool(
            is_external_labeled_row(row)
        ):
            raise ExternalSupervisionPackageError(
                f"one image has mixed external/non-external authority: {image_id}"
            )
        by_image[image_id] = row

    total = len(by_image)
    external = sum(1 for row in by_image.values() if is_external_labeled_row(row))
    certified_real = sum(1 for row in by_image.values() if is_certified_real_row(row))
    external_share = external / total if total else 0.0
    certified_real_share = certified_real / total if total else 0.0

    if external_share > cap + 1e-12:
        raise ExternalSupervisionPackageError(
            f"external label share {external_share:.6f} exceeds cap {cap:.2f}"
        )
    if external > 0 and certified_real_share <= external_share + 1e-12:
        raise ExternalSupervisionPackageError(
            "certified real supervision must dominate external labeled share"
        )
    if external > 0 and certified_real_share < 0.5 - 1e-12:
        raise ExternalSupervisionPackageError(
            "certified real supervision must remain majority when external labels are present"
        )

    return {
        "total_images": total,
        "external_images": external,
        "certified_real_images": certified_real,
        "external_image_share": external_share,
        "certified_real_image_share": certified_real_share,
        "maximum_combined_external_batch_fraction": cap,
        "certified_real_dominant": certified_real_share > external_share,
    }


def _require_non_fixture_evidence_bundle(bundle: Mapping[str, Any], *, project_root: Path) -> None:
    """Refuse a live-admission claim backed by hermetic fixture gate artifacts."""

    gates = bundle.get("gates")
    if not isinstance(gates, list) or not gates:
        raise ExternalSupervisionPackageError("live qualification gate bindings missing")
    root = Path(project_root).resolve(strict=True)
    for record in gates:
        if not isinstance(record, Mapping) or not isinstance(record.get("artifact_path"), str):
            raise ExternalSupervisionPackageError("live qualification gate binding malformed")
        relative = Path(record["artifact_path"])
        if relative.is_absolute():
            raise ExternalSupervisionPackageError("live qualification gate path is unsafe")
        try:
            artifact_path = (root / relative).resolve(strict=True)
            artifact_path.relative_to(root)
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
            raise ExternalSupervisionPackageError(
                "live qualification gate cannot be read safely"
            ) from exc
        if not isinstance(artifact, Mapping) or artifact.get("fixture") is True:
            raise ExternalSupervisionPackageError(
                "live warehouse admission cannot use fixture qualification evidence"
            )


def _require_live_selection_lineage(selection: ExternalPackageSelection) -> None:
    for name in ("source_sha256", "annotation_sha256"):
        value = getattr(selection, name)
        if not isinstance(value, str) or len(value) != 64:
            raise ExternalSupervisionPackageError(f"live package lineage missing {name}")
        try:
            int(value, 16)
        except ValueError as exc:
            raise ExternalSupervisionPackageError(f"live package lineage invalid {name}") from exc
    for name in ("source_relative_path", "annotation_relative_path"):
        value = getattr(selection, name)
        if not isinstance(value, str) or not value or Path(value).is_absolute():
            raise ExternalSupervisionPackageError(f"live package lineage invalid {name}")
    group = selection.split_group_id
    if not isinstance(group, str) or not group.startswith("external_group_"):
        raise ExternalSupervisionPackageError("live package lineage missing split_group_id")


def materialize_qualified_train_only_packages(
    selections: Sequence[ExternalPackageSelection],
    *,
    destination: Path,
    provenance: Mapping[str, Any],
    inventory: Mapping[str, Any],
    evidence_bundles_by_source: Mapping[str, Mapping[str, Any]],
    project_root: Path,
    companion_certified_rows: Sequence[Mapping[str, Any]] | None = None,
    registry_path: Path | None = None,
    inventory_path: Path | None = None,
    ablation_report: Mapping[str, Any] | None = None,
    live_warehouse_admission: bool = False,
) -> dict[str, Any]:
    """Materialize gated train-only packages plus a composition dataset card.

    Live admission is explicit and rejects fixture-backed evidence. Neither mode grants gold.
    """

    if not selections:
        raise ExternalSupervisionPackageError("no external selections to materialize")

    if registry_path is not None and inventory_path is not None:
        registry = load_external_supervision_registry(registry_path, inventory_path)
    else:
        registry = dict(provenance)

    active_ablation_keys: set[tuple[str, tuple[str, ...]]] | None = None
    sealed_ablation: Mapping[str, Any] | None = None
    if ablation_report is not None:
        try:
            sealed_ablation = require_ablation_report(ablation_report)
            active_ablation_keys = active_scope_keys(sealed_ablation)
        except ExternalHoldoutAblationError as exc:
            raise ExternalSupervisionPackageError(str(exc)) from exc

    destination = Path(destination)
    packages_root = destination / "packages"
    packages_root.mkdir(parents=True, exist_ok=True)

    package_records: list[dict[str, Any]] = []
    label_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    weight_sum = 0.0

    for selection in selections:
        if selection.source not in evidence_bundles_by_source:
            raise ExternalSupervisionPackageError(
                f"missing qualification evidence bundle for source: {selection.source}"
            )
        if not 0.10 <= float(selection.training_loss_weight) <= 0.25:
            raise ExternalSupervisionPackageError(
                f"selection weight out of range: {selection.image_id}"
            )
        if selection.part_map.shape != selection.material_map.shape:
            raise ExternalSupervisionPackageError(
                f"part/material shape mismatch: {selection.image_id}"
            )

        decision = verify_external_qualification_evidence(
            provenance,
            inventory,
            source=selection.source,
            evidence_bundle=evidence_bundles_by_source[selection.source],
            project_root=project_root,
        )
        if not decision.admitted:
            raise ExternalSupervisionPackageError(
                f"builder refused ungated external source {selection.source}: {decision.reason}"
            )
        if live_warehouse_admission:
            _require_non_fixture_evidence_bundle(
                evidence_bundles_by_source[selection.source], project_root=project_root
            )
            _require_live_selection_lineage(selection)

        admission = registry["sources"][selection.source]["training_admission"]
        allowed_scope = set(admission.get("allowed_label_scope", ()))
        unknown = sorted(set(selection.label_names) - allowed_scope)
        if unknown:
            raise ExternalSupervisionPackageError(
                f"labels outside allowed scope for {selection.source}: {unknown}"
            )

        package = packages_root / selection.image_id / "instances" / "p0"
        package.mkdir(parents=True, exist_ok=True)
        height, width = selection.part_map.shape
        if selection.source_rgb is None:
            Image.new("RGB", (width, height), "gray").save(package / "source.png")
        else:
            rgb = np.asarray(selection.source_rgb)
            if rgb.shape[:2] != (height, width):
                raise ExternalSupervisionPackageError(
                    f"source_rgb shape mismatch: {selection.image_id}"
                )
            Image.fromarray(rgb.astype(np.uint8), mode="RGB").save(package / "source.png")
        write_label_map(
            package / "label_map_part.png", selection.part_map.astype(np.uint16), bits=16
        )
        write_label_map(
            package / "label_map_material.png",
            selection.material_map.astype(np.uint8),
            bits=8,
        )
        (package / ".maskfactory_frozen.json").write_text("{}", encoding="utf-8")
        package_file_sha256 = {
            name: hashlib.sha256((package / name).read_bytes()).hexdigest()
            for name in (
                "source.png",
                "label_map_part.png",
                "label_map_material.png",
                ".maskfactory_frozen.json",
            )
        }

        bundle = evidence_bundles_by_source[selection.source]
        raw_gates = bundle.get("completed_gates", bundle.get("gates"))
        if isinstance(raw_gates, list) and raw_gates and isinstance(raw_gates[0], Mapping):
            completed = [
                str(record["gate"])
                for record in raw_gates
                if isinstance(record, Mapping) and isinstance(record.get("gate"), str)
            ]
        elif isinstance(raw_gates, list) and raw_gates:
            completed = [str(gate) for gate in raw_gates]
        else:
            completed = list(CANONICAL_REQUIRED_GATES_BY_SOURCE[selection.source])
        label_key = (selection.source, tuple(sorted(selection.label_names)))
        ablation_active = bool(
            active_ablation_keys is not None and label_key in active_ablation_keys
        )
        qualification = {
            "admitted": True,
            "source": selection.source,
            "truth_tier": WEIGHTED_PSEUDO_LABEL,
            "truth_partition": TRAIN_PARTITION,
            "holdout_eligible": False,
            "dataset_volume_eligible": False,
            "counts_as_human_anchor_gold": False,
            "counts_as_autonomous_certified_gold": False,
            "completed_gates": completed,
            "evidence_bundle_sha256": decision.evidence_bundle_sha256,
            "qualification_reason": decision.reason,
            "proof_tier": LIVE_PROOF_TIER if live_warehouse_admission else PROOF_TIER,
            "live_warehouse_admission": live_warehouse_admission,
            "ablation_active": ablation_active,
        }

        parts = {
            name: {"status": WEIGHTED_PSEUDO_LABEL, "visibility": "visible"}
            for name in selection.label_names
        }
        manifest = {
            "image_id": selection.image_id,
            "mask_ontology_version": "body_parts_v1",
            "truth_tier": WEIGHTED_PSEUDO_LABEL,
            "truth_partition": TRAIN_PARTITION,
            "training_loss_weight": float(selection.training_loss_weight),
            "source_role": EXTERNAL_LABEL_ROLE,
            "source": {
                "source_origin": "external_dataset",
                "external_source": selection.source,
            },
            "source_lineage": {
                "kind": EXTERNAL_LABEL_ROLE,
                "source": selection.source,
                "source_relative_path": selection.source_relative_path,
                "source_sha256": selection.source_sha256,
                "annotation_relative_path": selection.annotation_relative_path,
                "annotation_sha256": selection.annotation_sha256,
                "split_group_id": selection.split_group_id,
            },
            "external_qualification": qualification,
            "ablation_active": ablation_active,
            "parts": parts,
            "files": {
                "source.png": "source.png",
                "label_map_part.png": "label_map_part.png",
                "label_map_material.png": "label_map_material.png",
            },
            "file_sha256": package_file_sha256,
            "person": {"view": "front", "person_count": 1, "pose_tags": ["standing"]},
        }
        require_external_package_qualification(manifest)
        manifest_path = package / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        package_record_file_sha256 = {
            **package_file_sha256,
            "manifest.json": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        }

        package_records.append(
            {
                "image_id": selection.image_id,
                "package": package.relative_to(destination).as_posix(),
                "source": selection.source,
                "external_source": selection.source,
                "source_role": EXTERNAL_LABEL_ROLE,
                "truth_tier": WEIGHTED_PSEUDO_LABEL,
                "truth_partition": TRAIN_PARTITION,
                "training_loss_weight": float(selection.training_loss_weight),
                "label_names": list(selection.label_names),
                "external_qualification_admitted": True,
                "dataset_volume_eligible": False,
                "evidence_bundle_sha256": decision.evidence_bundle_sha256,
                "source_sha256": selection.source_sha256,
                "annotation_sha256": selection.annotation_sha256,
                "split_group_id": selection.split_group_id,
                "package_file_sha256": package_record_file_sha256,
                "ablation_active": ablation_active,
            }
        )
        source_counts[selection.source] = source_counts.get(selection.source, 0) + 1
        weight_sum += float(selection.training_loss_weight)
        for name in selection.label_names:
            label_counts[name] = label_counts.get(name, 0) + 1

    training_composition_supplied = companion_certified_rows is not None
    companion = list(companion_certified_rows or ())
    composition_rows = [
        {
            "image_id": row["image_id"],
            "source_role": EXTERNAL_LABEL_ROLE,
            "truth_tier": WEIGHTED_PSEUDO_LABEL,
            "truth_partition": TRAIN_PARTITION,
            "training_loss_weight": row["training_loss_weight"],
            "external_qualification_admitted": True,
            "dataset_volume_eligible": False,
            "external_source": row["source"],
            "label_names": list(row["label_names"]),
            "ablation_active": row["ablation_active"],
        }
        for row in package_records
    ] + list(companion)
    batch_metrics: Mapping[str, Any] | None = None
    if training_composition_supplied:
        assert_builder_accepts_only_gated_external_rows(
            composition_rows, ablation_report=sealed_ablation
        )
        assert_launcher_accepts_only_gated_external_rows(
            composition_rows, ablation_report=sealed_ablation
        )
        batch_metrics = validate_external_batch_cap(composition_rows, registry=registry)

    card = _composition_dataset_card(
        package_records,
        source_counts=source_counts,
        label_counts=label_counts,
        weight_sum=weight_sum,
        batch_metrics=batch_metrics,
        proof_tier=LIVE_PROOF_TIER if live_warehouse_admission else PROOF_TIER,
        live_warehouse_admission=live_warehouse_admission,
    )
    (destination / "dataset_card.md").write_text(card, encoding="utf-8")

    report = {
        "schema_version": "1.0.0",
        "artifact_type": "external_supervision_train_only_batch",
        "proof_tier": LIVE_PROOF_TIER if live_warehouse_admission else PROOF_TIER,
        "authority": LIVE_AUTHORITY if live_warehouse_admission else AUTHORITY,
        "admission_ready": live_warehouse_admission,
        "live_warehouse_admission": live_warehouse_admission,
        "any_source_admitted_live": live_warehouse_admission,
        "training_batch_eligible": training_composition_supplied,
        "batch_cap_enforced": training_composition_supplied,
        "package_count": len(package_records),
        "packages": package_records,
        "source_composition": source_counts,
        "label_composition": label_counts,
        "weight_composition": {
            "sum_training_loss_weight": weight_sum,
            "mean_training_loss_weight": weight_sum / len(package_records),
        },
        "external_batch_metrics": batch_metrics,
        "holdout_ablation": (
            {
                "bound": True,
                "seal_sha256": sealed_ablation["seal_sha256"],
                "active_count": sealed_ablation["active_count"],
                "inactive_count": sealed_ablation["inactive_count"],
                "live_holdout_executed": False,
                "report_path": "holdout_ablation_report.json",
            }
            if sealed_ablation is not None
            else {
                "bound": False,
                "active_count": 0,
                "inactive_count": 0,
                "live_holdout_executed": False,
            }
        ),
        "dataset_card": "dataset_card.md",
    }
    report["seal_sha256"] = canonical_json_sha256(
        {key: value for key, value in report.items() if key != "seal_sha256"}
    )
    publish_immutable_evidence(report, destination / "batch_manifest.json")
    if sealed_ablation is not None:
        publish_immutable_evidence(
            dict(sealed_ablation), destination / "holdout_ablation_report.json"
        )
        # Also publish beside packages/ so dataset builder discovery finds it.
        publish_immutable_evidence(
            dict(sealed_ablation), packages_root / "holdout_ablation_report.json"
        )
    return report


def _composition_dataset_card(
    packages: Sequence[Mapping[str, Any]],
    *,
    source_counts: Mapping[str, int],
    label_counts: Mapping[str, int],
    weight_sum: float,
    batch_metrics: Mapping[str, Any] | None,
    proof_tier: str,
    live_warehouse_admission: bool,
) -> str:
    lines = [
        f"# External supervision train-only package population ({proof_tier})",
        "",
        "- Authority: gated `external_labeled_reference` / `weighted_pseudo_label` / train only",
        "- Gold / holdout / certified-volume claims: blocked",
        f"- Packages: `{len(packages)}`",
        f"- Proof tier: `{proof_tier}`",
        f"- Live warehouse admission: `{str(live_warehouse_admission).lower()}`",
        f"- Training batch composition supplied: `{str(batch_metrics is not None).lower()}`",
        "",
        "## Source composition",
        "",
    ]
    for source, count in sorted(source_counts.items()):
        lines.append(f"- {source}: {count}")
    lines.extend(("", "## Label composition", ""))
    for label, count in sorted(label_counts.items()):
        lines.append(f"- {label}: {count}")
    lines.extend(
        (
            "",
            "## Weight composition",
            "",
            f"- Sum training_loss_weight: `{weight_sum:.6f}`",
            f"- Mean training_loss_weight: `{weight_sum / len(packages):.6f}`",
            "",
            "## Batch cap / certified-real dominance",
            "",
        )
    )
    if batch_metrics is None:
        lines.extend(
            (
                "- Not evaluated during package population.",
                "- Dataset builder and training launcher must supply the full composition and enforce the cap before use.",
                "",
            )
        )
    else:
        lines.extend(
            (
                f"- External share: `{float(batch_metrics['external_image_share']):.6f}`",
                f"- Cap: `{float(batch_metrics['maximum_combined_external_batch_fraction']):.2f}`",
                f"- Certified real share: `{float(batch_metrics['certified_real_image_share']):.6f}`",
                f"- Certified real dominant: `{bool(batch_metrics['certified_real_dominant'])}`",
                "",
            )
        )
    return "\n".join(lines)


def load_registry_pair(
    provenance_path: Path,
    inventory_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        registry = load_external_supervision_registry(provenance_path, inventory_path)
    except (ExternalSupervisionError, OSError, ValueError) as exc:
        raise ExternalSupervisionPackageError(str(exc)) from exc
    inventory = json.loads(Path(inventory_path).read_text(encoding="utf-8"))
    return registry, inventory


__all__ = [
    "AUTHORITY",
    "DEFAULT_MAXIMUM_COMBINED_EXTERNAL_BATCH_FRACTION",
    "ExternalPackageSelection",
    "ExternalSupervisionPackageError",
    "LIVE_AUTHORITY",
    "LIVE_PROOF_TIER",
    "PROOF_TIER",
    "assert_builder_accepts_only_gated_external_rows",
    "assert_launcher_accepts_only_gated_external_rows",
    "is_certified_real_row",
    "is_external_labeled_row",
    "load_registry_pair",
    "materialize_qualified_train_only_packages",
    "maximum_combined_external_batch_fraction",
    "require_external_package_qualification",
    "validate_external_batch_cap",
]
