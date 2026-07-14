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
from PIL import Image

from ..io.png_strict import write_label_map
from ..ontology import Ontology, get_ontology, load_ontology
from ..ontology_v2 import DEFAULT_ONTOLOGY_V2
from ..ontology_v2_manifest import (
    OntologyV2ManifestError,
    require_v2_supervision_eligible,
)
from ..packager import verify_packages
from ..review_package import update_package_workflow_status
from ..state import transition_image_status, writer_connection
from .cocorle import encode_binary_mask
from .coverage import build_coverage_matrix, write_coverage_matrix
from .splits import SplitRecord, assign_splits, validate_instance_split_integrity


@dataclass(frozen=True)
class DatasetPublicationPlan:
    version: int
    ontology_version: str
    destination: Path
    git_tag: str


def build_dataset(
    *,
    packages_root: Path,
    output_root: Path,
    version: int,
    hard_case_file: Path | None = None,
    ontology_version: str | None = None,
) -> Path:
    """Verify approved gold and export MMSeg/COCO layouts without holdout trainer paths."""
    if version < 1:
        raise ValueError("dataset version must be positive")
    packages = _approved_packages(Path(packages_root), ontology_version=ontology_version)
    if not packages:
        raise ValueError("no frozen human-approved gold packages")
    for package in packages:
        verification = verify_packages(package)[0]
        if not verification.passed:
            raise ValueError(f"gold package verification failed: {package}")
    by_image: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    ontology_versions: set[str] = set()
    for package in packages:
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
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
    splits = assign_splits(records, hard_case_ids=hard_ids)
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
        "holdout/test",
        "holdout/hard_case",
    ):
        (destination / directory).mkdir(parents=True, exist_ok=True)
    coco_images, coco_annotations = [], []
    annotation_id = 1
    split_instances: dict[str, list[str]] = {
        "train": [],
        "val": [],
        "test_holdout": [],
        "hard_case_holdout": [],
    }
    for image_id, entries in sorted(by_image.items()):
        split = splits[image_id]
        for index, (package, manifest) in enumerate(sorted(entries, key=lambda item: item[0].name)):
            instance = package.name if package.name.startswith("p") else f"p{index}"
            sample_id = f"{image_id}_{instance}"
            split_instances[split].append(sample_id)
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
    for entries in by_image.values():
        for _, manifest in entries:
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
    card = _dataset_card(
        version,
        ontology.version,
        splits,
        split_instances,
        records,
        class_annotations=coco_annotations,
        coverage=coverage,
        ontology=ontology,
    )
    (destination / "dataset_card.md").write_text(card, encoding="utf-8")
    (destination / "build_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "dataset": f"bodyparts@v{version}",
                "ontology_version": ontology.version,
                "seed": 1337,
                "git_sha": _git_sha(),
                "splits": splits,
                "instances": split_instances,
                "source_packages": [
                    package.relative_to(Path(packages_root)).as_posix() for package in packages
                ],
                "trainer_inputs": [
                    "train.txt",
                    "val.txt",
                    "part_seg",
                    "material_seg",
                    "hand_crops",
                    "matting",
                    "projected",
                ],
                "holdout_trainer_read_path": None,
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
        if manifest.get("workflow_status") not in {"approved_gold", "exported"}:
            raise ValueError(f"dataset source package is not approved gold: {value}")
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
    return len(_approved_packages(Path(packages_root), ontology_version=ontology_version))


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
    if ontology_version not in {None, "body_parts_v1", "body_parts_v2"}:
        raise ValueError(f"unsupported dataset ontology version: {ontology_version}")
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
            results.append(package)
            continue
        visible = [
            entry for entry in manifest.get("parts", {}).values() if entry.get("status") != "n/a"
        ]
        if visible and all(entry.get("status") == "human_approved_gold" for entry in visible):
            results.append(package)
    return tuple(results)


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
        "- Holdouts are excluded from trainer inputs.",
        "",
        "## Counts",
        "",
    ]
    for split in ("train", "val", "test_holdout", "hard_case_holdout"):
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
