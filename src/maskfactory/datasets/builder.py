"""Deterministic S14 export from verified frozen gold packages."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image

from ..daz.policy import validate_synthetic_authority, validate_synthetic_share
from ..io.hashing import sha256_file
from ..io.png_strict import write_label_map
from ..ontology import Ontology, get_ontology, load_ontology
from ..ontology_v2 import DEFAULT_ONTOLOGY_V2
from ..ontology_v2_manifest import (
    OntologyV2ManifestError,
    require_v2_supervision_eligible,
)
from ..packager import verify_packages
from ..reference_library import (
    evaluate_benchmark_training_isolation,
    reference_dhash64,
)
from ..review_package import update_package_workflow_status
from ..state import transition_image_status, writer_connection
from ..truth_tiers import (
    AUTONOMOUS_CERTIFIED_GOLD,
    HUMAN_ANCHOR_GOLD,
    MACHINE_CANDIDATE,
    WEIGHTED_PSEUDO_LABEL,
    TruthTierPolicy,
    require_training_truth_tier,
    validate_truth_tier_policy,
)
from .authority import evaluate_certified_volume_gates, serialized_reader_capabilities
from .cocorle import encode_binary_mask
from .coverage import build_coverage_matrix, write_coverage_matrix
from .splits import SplitRecord, assign_splits, validate_instance_split_integrity


@dataclass(frozen=True)
class DatasetPublicationPlan:
    version: int
    ontology_version: str
    destination: Path
    git_tag: str


@dataclass(frozen=True)
class PackageTruth:
    tier: str
    partition: str | None
    training_loss_weight: float
    source_origin: str | None = None
    source_role: str | None = None


def build_dataset(
    *,
    packages_root: Path,
    output_root: Path,
    version: int,
    reference_database: Path,
    hard_case_file: Path | None = None,
    ontology_version: str | None = None,
) -> Path:
    """Export truth-tiered supervision with strict train/calibration/holdout isolation."""
    if version < 1:
        raise ValueError("dataset version must be positive")
    reference_database = Path(reference_database)
    if not reference_database.is_file():
        raise ValueError("dataset build requires the frozen reference benchmark database")
    policy = _truth_tier_policy()
    packages = _approved_packages(Path(packages_root), ontology_version=ontology_version)
    if not packages:
        raise ValueError("no frozen training-eligible truth packages")
    for package in packages:
        verification = verify_packages(package)[0]
        if not verification.passed:
            raise ValueError(f"gold package verification failed: {package}")
    by_image: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    truth_by_package: dict[Path, PackageTruth] = {}
    ontology_versions: set[str] = set()
    for package in packages:
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        truth_by_package[package] = _package_truth(manifest, policy=policy)
        ontology_versions.add(str(manifest.get("mask_ontology_version", "body_parts_v1")))
        by_image.setdefault(manifest["image_id"], []).append((package, manifest))
    if len(ontology_versions) != 1:
        raise ValueError(f"dataset cannot mix ontology versions: {sorted(ontology_versions)}")
    ontology_version = next(iter(ontology_versions))
    if ontology_version == "body_parts_v1":
        ontology = get_ontology()
    elif ontology_version == "body_parts_v2":
        ontology = load_ontology(DEFAULT_ONTOLOGY_V2)
    else:
        raise ValueError(f"unsupported dataset ontology version: {ontology_version}")
    records = tuple(
        SplitRecord(
            image_id,
            str(entries[0][1]["source"].get("phash64", _fallback_phash(image_id))),
            str(entries[0][1]["source"]["source_origin"]),
        )
        for image_id, entries in sorted(by_image.items())
    )
    hard_ids = _hard_ids(hard_case_file)
    splits = _truth_aware_splits(
        assign_splits(records, hard_case_ids=hard_ids),
        by_image,
        truth_by_package,
        hard_case_ids=hard_ids,
    )
    reference_isolation_records = []
    for image_id, entries in sorted(by_image.items()):
        package, manifest = sorted(entries, key=lambda item: item[0].name)[0]
        source = manifest["source"]
        reference_isolation_records.append(
            {
                "image_id": image_id,
                "relative_path": source.get("source_file", f"{image_id}/source.png"),
                "source_sha256": source.get("source_sha256", sha256_file(package / "source.png")),
                "dhash64": reference_dhash64(package / "source.png"),
                "partition": splits[image_id],
            }
        )
    reference_isolation = evaluate_benchmark_training_isolation(
        reference_database,
        reference_isolation_records,
        expected_benchmark_count=2500,
    )
    if not reference_isolation["passed"]:
        raise ValueError(
            "dataset source overlaps or cannot be compared with the frozen reference benchmark: "
            + "; ".join(reference_isolation["issues"][:10])
        )
    destination = Path(output_root) / f"bodyparts@v{version}"
    if destination.exists():
        raise FileExistsError(f"dataset version already exists: {destination}")
    for directory in (
        "part_seg/images",
        "part_seg/annotations",
        "material_seg/images",
        "material_seg/annotations",
        "hand_crops",
        "matting",
        "projected",
        "coco",
        "calibration",
        "holdout/test",
        "holdout/hard_case",
    ):
        (destination / directory).mkdir(parents=True, exist_ok=True)
    coco_images, coco_annotations = [], []
    annotation_id = 1
    split_instances: dict[str, list[str]] = {
        "train": [],
        "val": [],
        "calibration": [],
        "test_holdout": [],
        "hard_case_holdout": [],
    }
    sample_truth: dict[str, dict[str, Any]] = {}
    for image_id, entries in sorted(by_image.items()):
        split = splits[image_id]
        for index, (package, manifest) in enumerate(sorted(entries, key=lambda item: item[0].name)):
            instance = package.name if package.name.startswith("p") else f"p{index}"
            sample_id = f"{image_id}_{instance}"
            truth = truth_by_package[package]
            split_instances[split].append(sample_id)
            sample_truth[sample_id] = {
                "image_id": image_id,
                "truth_tier": truth.tier,
                "truth_partition": _effective_truth_partition(truth, split),
                "split": split,
                "training_loss_weight": (truth.training_loss_weight if split == "train" else 0.0),
                "dataset_volume_eligible": bool(
                    policy[truth.tier].dataset_volume_eligible
                    and _effective_truth_partition(truth, split) == "train"
                ),
                "source_origin": truth.source_origin,
                "source_role": truth.source_role,
            }
            if truth.source_origin == "synthetic":
                sample_truth[sample_id].update(
                    {
                        "holdout_eligible": False,
                        "calibration_eligible": False,
                        "counts_as_human_anchor_gold": False,
                        "counts_as_autonomous_certified_gold": False,
                        "maximum_synthetic_image_fraction": 0.30,
                    }
                )
            if split == "calibration":
                _copy_sample(
                    package,
                    destination / "calibration",
                    sample_id,
                    holdout=True,
                    ontology=ontology,
                )
                continue
            target_root = (
                destination / "holdout" / ("hard_case" if split == "hard_case_holdout" else "test")
                if split.endswith("holdout")
                else destination
            )
            if split.endswith("holdout"):
                _copy_sample(package, target_root, sample_id, holdout=True, ontology=ontology)
                continue
            _copy_sample(package, target_root, sample_id, holdout=False, ontology=ontology)
            with Image.open(package / "source.png") as opened:
                width, height = opened.size
            image_number = len(coco_images) + 1
            coco_images.append(
                {
                    "id": image_number,
                    "file_name": f"{sample_id}.png",
                    "width": width,
                    "height": height,
                }
            )
            part = np.asarray(Image.open(package / "label_map_part.png"))
            for label in ontology.labels_for_map("part", enabled_only=True):
                if not label.id:
                    continue
                mask = part == int(label.id)
                if not mask.any():
                    continue
                ys, xs = np.nonzero(mask)
                coco_annotations.append(
                    {
                        "id": annotation_id,
                        "image_id": image_number,
                        "category_id": int(label.id),
                        "segmentation": encode_binary_mask(mask),
                        "area": int(mask.sum()),
                        "bbox": [
                            int(xs.min()),
                            int(ys.min()),
                            int(xs.max() - xs.min() + 1),
                            int(ys.max() - ys.min() + 1),
                        ],
                        "iscrowd": 0,
                    }
                )
                annotation_id += 1
            for optional in ("crops", "matting", "projected"):
                if (package / optional).is_dir():
                    shutil.copytree(
                        package / optional,
                        destination
                        / ("hand_crops" if optional == "crops" else optional)
                        / sample_id,
                    )
    for split in ("train", "val"):
        instance_ids = sorted(split_instances[split])
        (destination / f"{split}.txt").write_text(
            "".join(f"{value}\n" for value in instance_ids), encoding="utf-8"
        )
    (destination / "calibration/ids.txt").write_text(
        "".join(f"{value}\n" for value in sorted(split_instances["calibration"])),
        encoding="utf-8",
    )
    protected_anchor_ids = sorted(
        image_id
        for image_id, split in splits.items()
        if split in {"calibration", "test_holdout", "hard_case_holdout"}
    )
    (destination / "protected_anchor_ids.txt").write_text(
        "".join(f"{value}\n" for value in protected_anchor_ids), encoding="utf-8"
    )
    (destination / "sample_weights.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "samples": sample_truth,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    validate_instance_split_integrity(
        {
            instance_id: split
            for split, instance_ids in split_instances.items()
            for instance_id in instance_ids
        }
    )
    coco = {
        "images": coco_images,
        "annotations": coco_annotations,
        "categories": [
            {"id": int(label.id), "name": label.name}
            for label in ontology.labels_for_map("part", enabled_only=True)
            if label.id
        ],
    }
    (destination / "coco/annotations.json").write_text(
        json.dumps(coco, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    coverage_rows = []
    for image_id, entries in by_image.items():
        for package, manifest in entries:
            truth = truth_by_package[package]
            if (
                not policy[truth.tier].dataset_volume_eligible
                or _effective_truth_partition(truth, splits[image_id]) != "train"
            ):
                continue
            person = manifest.get("person", {})
            if person.get("view") is None:
                continue
            count = int(person.get("person_count", 1))
            coverage_rows.append(
                {
                    "status": "human_approved_gold",
                    "view": person["view"],
                    "pose_tags": person.get("pose_tags", ()),
                    "instance_context": (
                        "solo" if count == 1 else "duo" if count == 2 else "small_group"
                    ),
                    "attributes": (),
                }
            )
    coverage = build_coverage_matrix(coverage_rows, generated_at=datetime(1970, 1, 1, tzinfo=UTC))
    write_coverage_matrix(destination / "coverage_matrix.json", coverage)
    truth_metrics = _truth_metrics(
        sample_truth,
        machine_candidate_count=_machine_candidate_count(
            Path(packages_root), ontology_version=ontology_version
        ),
    )
    synthetic_metrics = validate_synthetic_share(
        _one_authority_record_per_image(sample_truth.values())
    )
    volume_gates = evaluate_certified_volume_gates(
        int(truth_metrics["certified_training_package_count"]), coverage
    )
    card = _dataset_card(
        version,
        ontology.version,
        splits,
        split_instances,
        records,
        class_annotations=coco_annotations,
        coverage=coverage,
        ontology=ontology,
        truth_metrics=truth_metrics,
    )
    (destination / "dataset_card.md").write_text(card, encoding="utf-8")
    (destination / "build_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "dataset": f"bodyparts@v{version}",
                "ontology_version": ontology.version,
                "seed": 1337,
                "git_sha": _git_sha(),
                "splits": splits,
                "instances": split_instances,
                "truth_metrics": truth_metrics,
                "synthetic_metrics": synthetic_metrics,
                "certified_volume_gates": volume_gates,
                "reference_benchmark_isolation": reference_isolation,
                "sample_weights": "sample_weights.json",
                "source_packages": [
                    package.relative_to(Path(packages_root)).as_posix() for package in packages
                ],
                "trainer_inputs": [
                    "train.txt",
                    "val.txt",
                    "sample_weights.json",
                    "part_seg",
                    "material_seg",
                    "hand_crops",
                    "matting",
                    "projected",
                ],
                "holdout_trainer_read_path": None,
                "calibration_trainer_read_path": None,
                "calibration_reader_path": "calibration",
                "protected_anchor_ids": "protected_anchor_ids.txt",
                "reader_capabilities": serialized_reader_capabilities(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return destination


def mark_dataset_exported(
    dataset_root: Path,
    *,
    packages_root: Path,
    database: Path,
    updated_at: str | None = None,
) -> tuple[str, ...]:
    """Atomically synchronize a successfully published dataset back to package/SQLite state."""
    build_path = Path(dataset_root) / "build_manifest.json"
    build = json.loads(build_path.read_text(encoding="utf-8"))
    relative_packages = build.get("source_packages")
    if not isinstance(relative_packages, list) or not relative_packages:
        raise ValueError("dataset build manifest has no source_packages authority")

    root = Path(packages_root).resolve()
    packages: list[Path] = []
    manifests: dict[Path, dict[str, Any]] = {}
    for value in relative_packages:
        if not isinstance(value, str) or not value:
            raise ValueError("dataset source_packages entries must be non-empty strings")
        package = (root / value).resolve()
        if package == root or root not in package.parents:
            raise ValueError(f"dataset source package escapes packages root: {value}")
        if package in manifests:
            raise ValueError(f"duplicate dataset source package: {value}")
        manifest_path = package / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("workflow_status") not in {
            "approved_gold",
            "autonomous_certified",
            "weighted_pseudo",
            "exported",
        }:
            raise ValueError(f"dataset source package is not training-authorized: {value}")
        if not (package / ".maskfactory_frozen.json").is_file():
            raise ValueError(f"dataset source package is not frozen: {value}")
        packages.append(package)
        manifests[package] = manifest

    image_ids = tuple(sorted({str(manifest["image_id"]) for manifest in manifests.values()}))
    timestamp = updated_at or datetime.now(UTC).isoformat()
    original_bytes = {
        package / "manifest.json": (package / "manifest.json").read_bytes() for package in packages
    }
    changed = False
    try:
        with writer_connection(Path(database)) as connection:
            rows = {
                str(row[0]): str(row[1])
                for row in connection.execute(
                    f"SELECT image_id, status FROM images WHERE image_id IN "
                    f"({','.join('?' for _ in image_ids)})",
                    image_ids,
                )
            }
            missing = sorted(set(image_ids) - set(rows))
            if missing:
                raise ValueError(f"dataset source images missing from SQLite: {missing}")
            invalid = {
                key: value
                for key, value in rows.items()
                if value not in {"approved_gold", "exported"}
            }
            if invalid:
                raise ValueError(f"dataset source images are not approved gold: {invalid}")
            for package in packages:
                changed = (
                    update_package_workflow_status(package, "exported", updated_at=timestamp)
                    or changed
                )
            for image_id in image_ids:
                if rows[image_id] == "approved_gold":
                    transition_image_status(
                        connection,
                        image_id,
                        "exported",
                        updated_at=timestamp,
                        current_stage="S14",
                    )
                    changed = True
    except BaseException:
        if changed:
            for path, content in original_bytes.items():
                _write_bytes_atomic(path, content)
        raise
    return image_ids


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.restore-{uuid.uuid4().hex}")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def approved_package_count(packages_root: Path, *, ontology_version: str | None = None) -> int:
    """Backward-compatible name for the certified P5 training-volume count."""
    policy = _truth_tier_policy()
    count = 0
    for package in _approved_packages(Path(packages_root), ontology_version=ontology_version):
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        truth = _package_truth(manifest, policy=policy)
        if truth.tier in {HUMAN_ANCHOR_GOLD, AUTONOMOUS_CERTIFIED_GOLD} and truth.partition not in {
            "calibration",
            "holdout",
        }:
            count += 1
    return count


def next_dataset_version(output_root: Path) -> int:
    versions = []
    for path in Path(output_root).glob("bodyparts@v*"):
        try:
            versions.append(int(path.name.rsplit("@v", 1)[1]))
        except ValueError:
            continue
    return max(versions, default=0) + 1


def plan_dataset_publication(
    output_root: Path,
    *,
    ontology_version: str,
    existing_tags: tuple[str, ...] = (),
) -> DatasetPublicationPlan:
    """Plan a never-reused dataset path/tag before any build or DVC mutation."""
    if ontology_version not in {"body_parts_v1", "body_parts_v2"}:
        raise ValueError(f"unsupported dataset ontology version: {ontology_version}")
    version = next_dataset_version(output_root)
    destination = Path(output_root) / f"bodyparts@v{version}"
    tag = f"dataset/bodyparts-v{version}"
    if destination.exists():
        raise FileExistsError(f"dataset version already exists: {destination}")
    if tag in set(existing_tags):
        raise FileExistsError(f"dataset git tag already exists and cannot be rewritten: {tag}")
    return DatasetPublicationPlan(version, ontology_version, destination, tag)


def _approved_packages(root: Path, *, ontology_version: str | None = None) -> tuple[Path, ...]:
    """Return frozen training-eligible truth packages; keep the legacy private name."""
    if ontology_version not in {None, "body_parts_v1", "body_parts_v2"}:
        raise ValueError(f"unsupported dataset ontology version: {ontology_version}")
    policy = _truth_tier_policy()
    results = []
    for path in sorted(root.rglob("manifest.json")):
        package = path.parent
        if not (package / ".maskfactory_frozen.json").is_file():
            continue
        manifest = json.loads(path.read_text(encoding="utf-8"))
        package_ontology = str(manifest.get("mask_ontology_version", "body_parts_v1"))
        if ontology_version is not None and package_ontology != ontology_version:
            continue
        if manifest.get("mask_ontology_version") == "body_parts_v2":
            try:
                require_v2_supervision_eligible(manifest)
            except OntologyV2ManifestError as exc:
                raise ValueError(
                    f"frozen v2 package is ineligible for supervision: {package}"
                ) from exc
        try:
            truth = _package_truth(manifest, policy=policy)
        except ValueError as exc:
            raise ValueError(f"invalid truth authority in frozen package: {package}") from exc
        if not policy[truth.tier].training_eligible:
            continue
        if manifest.get("mask_ontology_version") == "body_parts_v2":
            results.append(package)
            continue
        results.append(package)
    return tuple(results)


def _truth_tier_policy() -> dict[str, TruthTierPolicy]:
    path = Path(__file__).resolve().parents[3] / "configs" / "autonomous_masks.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return validate_truth_tier_policy(document["truth_tiers"])


def _package_truth(manifest: dict[str, Any], *, policy: dict[str, TruthTierPolicy]) -> PackageTruth:
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    source_origin = source.get("source_origin")
    lineage = manifest.get("source_lineage")
    source_role = lineage.get("kind") if isinstance(lineage, dict) else manifest.get("source_role")
    explicit = manifest.get("truth_tier")
    if isinstance(explicit, str):
        # Operational / synthetic_exact labels fail closed before volume accounting.
        tier = require_training_truth_tier(explicit)
    else:
        statuses = {
            entry.get("status")
            for entry in manifest.get("parts", {}).values()
            if isinstance(entry, dict) and entry.get("status") != "n/a"
        }
        if statuses and statuses <= {"human_approved_gold", "human_anchor_gold"}:
            tier = HUMAN_ANCHOR_GOLD
        else:
            raise ValueError("package has no explicit or legacy-compatible truth tier")

    partition = manifest.get("truth_partition")
    if partition is not None and partition not in {"train", "calibration", "holdout", "residual"}:
        raise ValueError(f"invalid truth partition: {partition}")
    if tier == HUMAN_ANCHOR_GOLD:
        if partition == "residual":
            raise ValueError("human anchor truth cannot use the residual partition")
        expected_weight = 0.0 if partition in {"calibration", "holdout"} else 1.0
    elif tier == AUTONOMOUS_CERTIFIED_GOLD:
        if partition != "train":
            raise ValueError("autonomous certified truth must be explicitly train-only")
        certification = manifest.get("certification")
        required = {
            "certificates",
            "pipeline_fingerprint",
            "evidence_sha256",
            "final_mask_set_sha256",
        }
        if not isinstance(certification, dict) or not required <= set(certification):
            raise ValueError("autonomous certified truth lacks certificate-bound provenance")
        certificates = certification.get("certificates")
        if not isinstance(certificates, list) or not certificates:
            raise ValueError("autonomous certified truth has no risk certificates")
        expected_weight = policy[tier].training_weight
    elif tier == WEIGHTED_PSEUDO_LABEL:
        if partition != "train":
            raise ValueError("weighted pseudo-label truth must be explicitly train-only")
        expected_weight = policy[tier].training_weight
    else:
        if partition not in {None, "residual"}:
            raise ValueError("machine candidates are residual-only")
        expected_weight = 0.0

    configured = manifest.get("training_loss_weight")
    if configured is None:
        if explicit is not None:
            raise ValueError("explicit truth tier lacks training_loss_weight")
        configured = expected_weight
    weight = float(configured)
    flexible_pseudo = tier == WEIGHTED_PSEUDO_LABEL and source_role in {
        "external_labeled_reference",
        "synthetic_geometry_exact",
    }
    if flexible_pseudo and not 0.10 <= weight <= 0.25:
        raise ValueError("source-scoped weighted pseudo-label weight must be 0.10..0.25")
    if not flexible_pseudo and abs(weight - expected_weight) > 1e-9:
        raise ValueError(
            f"training_loss_weight {weight} does not match {tier} policy {expected_weight}"
        )
    if source_origin == "synthetic":
        validate_synthetic_authority(
            {
                "source_origin": source_origin,
                "source_role": source_role,
                "truth_tier": tier,
                "truth_partition": partition,
                "training_loss_weight": weight,
                "holdout_eligible": manifest.get("holdout_eligible"),
                "calibration_eligible": manifest.get("calibration_eligible"),
                "dataset_volume_eligible": manifest.get("dataset_volume_eligible"),
                "counts_as_human_anchor_gold": manifest.get("counts_as_human_anchor_gold"),
                "counts_as_autonomous_certified_gold": manifest.get(
                    "counts_as_autonomous_certified_gold"
                ),
                "maximum_synthetic_image_fraction": manifest.get(
                    "maximum_synthetic_image_fraction"
                ),
            }
        )

    allowed_part_statuses = {
        HUMAN_ANCHOR_GOLD: {"human_approved_gold", "human_anchor_gold", "n/a"},
        AUTONOMOUS_CERTIFIED_GOLD: {"autonomous_certified_gold", "n/a"},
        WEIGHTED_PSEUDO_LABEL: {"weighted_pseudo_label", "n/a"},
        MACHINE_CANDIDATE: {"machine_candidate", "draft_model_generated", "n/a"},
    }[tier]
    mismatched = sorted(
        name
        for name, entry in manifest.get("parts", {}).items()
        if isinstance(entry, dict) and entry.get("status") not in allowed_part_statuses
    )
    if mismatched:
        raise ValueError(f"part truth status disagrees with package tier: {mismatched}")
    return PackageTruth(
        tier=tier,
        partition=partition,
        training_loss_weight=weight,
        source_origin=str(source_origin) if source_origin is not None else None,
        source_role=str(source_role) if source_role is not None else None,
    )


def _one_authority_record_per_image(
    records: Any,
) -> tuple[dict[str, Any], ...]:
    by_image: dict[str, dict[str, Any]] = {}
    for row in records:
        image_id = str(row["image_id"])
        previous = by_image.get(image_id)
        if previous is not None and previous.get("source_origin") != row.get("source_origin"):
            raise ValueError(f"one image has mixed source origins: {image_id}")
        by_image[image_id] = dict(row)
    return tuple(by_image[key] for key in sorted(by_image))


def _truth_aware_splits(
    base_splits: dict[str, str],
    by_image: dict[str, list[tuple[Path, dict[str, Any]]]],
    truth_by_package: dict[Path, PackageTruth],
    *,
    hard_case_ids: frozenset[str],
) -> dict[str, str]:
    splits = dict(base_splits)
    for image_id, entries in by_image.items():
        truths = [truth_by_package[package] for package, _ in entries]
        explicit_partitions = {truth.partition for truth in truths if truth.partition is not None}
        if len(explicit_partitions) > 1:
            raise ValueError(
                f"image-disjoint truth partition conflict for {image_id}: "
                f"{sorted(explicit_partitions)}"
            )
        if any(truth.tier != HUMAN_ANCHOR_GOLD for truth in truths):
            if explicit_partitions - {"train"}:
                raise ValueError(f"non-anchor truth shares a calibration/holdout image: {image_id}")
            splits[image_id] = "train"
            continue
        partition = next(iter(explicit_partitions), None)
        if partition == "train":
            base = base_splits[image_id]
            if base == "hard_case_holdout":
                raise ValueError(
                    f"explicit training anchor cannot be named as a hard-case holdout: {image_id}"
                )
            splits[image_id] = "train" if base == "train" else "val"
        elif partition == "calibration":
            splits[image_id] = "calibration"
        elif partition == "holdout":
            splits[image_id] = "hard_case_holdout" if image_id in hard_case_ids else "test_holdout"
    image_hashes = {
        image_id: int(str(entries[0][1]["source"].get("phash64", _fallback_phash(image_id))), 16)
        for image_id, entries in by_image.items()
    }
    ordered_images = sorted(image_hashes)
    for left_index, left in enumerate(ordered_images):
        for right in ordered_images[left_index + 1 :]:
            if (image_hashes[left] ^ image_hashes[right]).bit_count() <= 6 and splits[
                left
            ] != splits[right]:
                raise ValueError(
                    "image-disjoint truth partition conflict across pHash duplicate group: "
                    f"{left}={splits[left]}, {right}={splits[right]}"
                )
    return splits


def _effective_truth_partition(truth: PackageTruth, split: str) -> str:
    if truth.partition is not None:
        return truth.partition
    if split == "train":
        return "train"
    if split == "val":
        return "train"
    if split == "calibration":
        return "calibration"
    return "holdout"


def _machine_candidate_count(root: Path, *, ontology_version: str | None) -> int:
    count = 0
    for path in sorted(Path(root).rglob("manifest.json")):
        package = path.parent
        if not (package / ".maskfactory_frozen.json").is_file():
            continue
        manifest = json.loads(path.read_text(encoding="utf-8"))
        package_ontology = str(manifest.get("mask_ontology_version", "body_parts_v1"))
        if ontology_version is not None and package_ontology != ontology_version:
            continue
        if manifest.get("truth_tier") == MACHINE_CANDIDATE:
            count += 1
    return count


def _truth_metrics(
    samples: dict[str, dict[str, Any]], *, machine_candidate_count: int
) -> dict[str, int | float]:
    values = tuple(samples.values())
    human_train = sum(
        row["truth_tier"] == HUMAN_ANCHOR_GOLD and row["truth_partition"] == "train"
        for row in values
    )
    human_calibration = sum(
        row["truth_tier"] == HUMAN_ANCHOR_GOLD and row["truth_partition"] == "calibration"
        for row in values
    )
    human_holdout = sum(
        row["truth_tier"] == HUMAN_ANCHOR_GOLD and row["truth_partition"] == "holdout"
        for row in values
    )
    autonomous = sum(row["truth_tier"] == AUTONOMOUS_CERTIFIED_GOLD for row in values)
    pseudo = sum(row["truth_tier"] == WEIGHTED_PSEUDO_LABEL for row in values)
    return {
        "human_anchor_train_count": human_train,
        "human_anchor_calibration_count": human_calibration,
        "human_anchor_holdout_count": human_holdout,
        "autonomous_certified_gold_count": autonomous,
        "weighted_pseudo_label_count": pseudo,
        "machine_candidate_count": machine_candidate_count,
        "certified_training_package_count": human_train + autonomous,
        "effective_training_weight_units": round(
            sum(float(row["training_loss_weight"]) for row in values), 6
        ),
    }


def _copy_sample(
    package: Path,
    root: Path,
    sample_id: str,
    *,
    holdout: bool,
    ontology: Ontology,
) -> None:
    part, material = _training_label_maps(package, ontology=ontology)
    if holdout:
        target = root / sample_id
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package / "source.png", target / "source.png")
        write_label_map(target / "label_map_part.png", part, bits=16)
        write_label_map(target / "label_map_material.png", material, bits=8)
    else:
        for group in ("part_seg/images", "material_seg/images"):
            shutil.copy2(package / "source.png", root / group / f"{sample_id}.png")
        write_label_map(root / "part_seg/annotations" / f"{sample_id}.png", part, bits=16)
        write_label_map(root / "material_seg/annotations" / f"{sample_id}.png", material, bits=8)


def _training_label_maps(
    package: Path, *, ontology: Ontology | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Return maps with every honestly ambiguous part region burned to ignore 255."""
    part = np.asarray(Image.open(package / "label_map_part.png")).copy()
    material = np.asarray(Image.open(package / "label_map_material.png")).copy()
    if part.shape != material.shape:
        raise ValueError(f"gold label-map dimensions differ: {package}")
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    authority = ontology or get_ontology()
    ambiguity = np.zeros(part.shape, dtype=bool)
    for name, entry in manifest.get("parts", {}).items():
        if entry.get("visibility") != "ambiguous_do_not_use":
            continue
        ambiguity_file = entry.get("ambiguity_file")
        if ambiguity_file is not None:
            if not isinstance(ambiguity_file, str) or not ambiguity_file:
                raise ValueError(f"ambiguous training label has invalid ignore path: {name}")
            ignore_path = package / ambiguity_file
            if not ignore_path.is_file():
                raise ValueError(f"ambiguous training ignore mask is missing: {ignore_path}")
            with Image.open(ignore_path) as opened:
                if opened.format != "PNG" or opened.mode != "L":
                    raise ValueError(
                        f"ambiguous training ignore mask must be mode-L PNG: {ignore_path}"
                    )
                ignore = np.asarray(opened)
            if ignore.shape != part.shape or not set(np.unique(ignore).tolist()).issubset({0, 255}):
                raise ValueError(
                    f"ambiguous training ignore mask must be same-size strict binary: {ignore_path}"
                )
            ambiguity |= ignore > 0
            continue
        label = authority.label(name)
        if label.map != "part" or label.id is None:
            raise ValueError(f"ambiguous training label is not an indexed part: {name}")
        ambiguity |= part == int(label.id)
    if ambiguity.any():
        part[ambiguity] = 255
        material[ambiguity] = 255
    return part, material


def _hard_ids(path: Path | None) -> frozenset[str]:
    if path is None or not Path(path).is_file():
        return frozenset()
    return frozenset(
        line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()
    )


def _fallback_phash(image_id: str) -> str:
    import hashlib

    return hashlib.sha256(image_id.encode()).hexdigest()[:16]


def _dataset_card(
    version,
    ontology_version,
    splits,
    split_instances,
    records,
    *,
    class_annotations,
    coverage,
    ontology: Ontology,
    truth_metrics: dict[str, int | float],
) -> str:
    synthetic = sum(record.source_origin in {"synthetic", "generated"} for record in records)
    ratio = synthetic / len(records)
    lines = [
        f"# MaskFactory bodyparts@v{version}",
        "",
        f"- Ontology: `{ontology_version}`",
        "- Build command: `maskfactory dataset build --name bodyparts`",
        f"- Git SHA: `{_git_sha()}`",
        "- Seed: `1337`",
        f"- Source images: `{len(records)}`",
        f"- Synthetic ratio: `{ratio:.6f}`",
        "- Split key: `image_id` (never instance ID)",
        "- Calibration and holdouts are excluded from trainer inputs.",
        "",
        "## Truth authority",
        "",
        f"- Human anchor train: {truth_metrics['human_anchor_train_count']}",
        f"- Human anchor calibration: {truth_metrics['human_anchor_calibration_count']}",
        f"- Human anchor holdout: {truth_metrics['human_anchor_holdout_count']}",
        f"- Autonomous certified gold: {truth_metrics['autonomous_certified_gold_count']}",
        f"- Weighted pseudo-label: {truth_metrics['weighted_pseudo_label_count']}",
        f"- Machine candidate (excluded): {truth_metrics['machine_candidate_count']}",
        f"- Certified training packages: {truth_metrics['certified_training_package_count']}",
        f"- Effective training weight units: {truth_metrics['effective_training_weight_units']}",
        "",
        "## Counts",
        "",
    ]
    for split in ("train", "val", "calibration", "test_holdout", "hard_case_holdout"):
        lines.append(
            f"- {split}: {sum(value == split for value in splits.values())} images / {len(split_instances[split])} instances"
        )
    counts: dict[int, int] = {}
    for annotation in class_annotations:
        counts[annotation["category_id"]] = counts.get(annotation["category_id"], 0) + 1
    lines.extend(("", "## Visible instance masks", ""))
    for label in ontology.labels_for_map("part", enabled_only=True):
        if label.id:
            lines.append(f"- {label.name}: {counts.get(int(label.id), 0)}")
    lines.extend(("", "## Coverage cells", ""))
    for cell in coverage["cells"]:
        lines.append(
            f"- {cell['view']} / {cell['pose']} / {cell['instance_context']}: "
            f"{cell['approved_gold_count']}"
        )
    return "\n".join(lines) + "\n"


def _git_sha() -> str:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False
    )
    return process.stdout.strip() if process.returncode == 0 else "unavailable"
