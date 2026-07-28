"""Fail-closed LaPa head-face calibration candidates and panel evidence."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image, ImageDraw

from ..external_supervision_evidence import seal_payload
from ..external_supervision_qualification import verify_external_qualification_evidence
from .canonical_polygon_panels import PANEL_NAMES, render_candidate_panels
from .canonical_polygon_source_candidates import sha256_file
from .critic_catalog import canonical_sha256

SCHEMA_VERSION = "maskfactory.lapa_control_candidates.v1"
PANEL_SCHEMA_VERSION = "maskfactory.lapa_control_panels.v1"
HEAD_FACE_VALUES = frozenset(range(1, 10))
PARTITIONS = ("qualification_train", "qualification_test")


class LaPaControlCandidateError(ValueError):
    """A LaPa calibration input is incomplete, drifted, or authority-unsafe."""


def _document(path: Path, *, yaml_input: bool = False) -> Mapping[str, Any]:
    try:
        value = (
            yaml.safe_load(path.read_text(encoding="utf-8"))
            if yaml_input
            else json.loads(path.read_text(encoding="utf-8"))
        )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise LaPaControlCandidateError(f"invalid evidence document:{path}") from exc
    if not isinstance(value, Mapping):
        raise LaPaControlCandidateError(f"document is not a mapping:{path}")
    return value


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise LaPaControlCandidateError(f"invalid SHA-256:{field}")
    try:
        int(value, 16)
    except ValueError as exc:
        raise LaPaControlCandidateError(f"invalid SHA-256:{field}") from exc
    return value


def _relative(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise LaPaControlCandidateError(f"invalid relative path:{field}")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise LaPaControlCandidateError(f"unsafe relative path:{field}")
    return path.as_posix()


def _inside(root: Path, relative: str, identifier: str) -> Path:
    path = (root / relative).resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise LaPaControlCandidateError(f"path escapes source root:{identifier}") from exc
    return path


def _partition(split: str) -> str:
    if split == "train":
        return "qualification_train"
    if split in {"val", "test"}:
        return "qualification_test"
    raise LaPaControlCandidateError(f"unsupported LaPa upstream split:{split}")


def _manifest_index(document: Mapping[str, Any]) -> dict[str, str]:
    if (
        document.get("schema_version") != "1.0.0"
        or document.get("artifact_type") != "external_supervision_source_hash_manifest"
        or document.get("source") != "lapa"
        or document.get("gate") != "source_hash_manifested"
        or document.get("status") != "PASS"
        or document.get("seal_sha256") != seal_payload(document)
    ):
        raise LaPaControlCandidateError("source-hash manifest contract drift")
    files = document.get("files")
    if not isinstance(files, list) or not files:
        raise LaPaControlCandidateError("source-hash manifest files are missing")
    result: dict[str, str] = {}
    for item in files:
        if not isinstance(item, Mapping) or set(item) != {"path", "size", "sha256"}:
            raise LaPaControlCandidateError("source-hash manifest record malformed")
        path = _relative(item["path"], "manifest path")
        if path in result or not isinstance(item["size"], int) or item["size"] < 0:
            raise LaPaControlCandidateError("source-hash manifest record drift")
        result[path] = _sha(item["sha256"], "manifest record")
    if document.get("file_count") != len(result):
        raise LaPaControlCandidateError("source-hash manifest count drift")
    return result


def _dedup_index(document: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    if document.get("status") != "PASS":
        raise LaPaControlCandidateError("split-dedup gate is not PASS")
    if document.get("seal_sha256") is not None and document["seal_sha256"] != seal_payload(
        document
    ):
        raise LaPaControlCandidateError("split-dedup seal drift")
    records = document.get("records")
    if not isinstance(records, list):
        raise LaPaControlCandidateError("split-dedup records are missing")
    result: dict[str, dict[str, str]] = {}
    groups: dict[str, set[str]] = {}
    for item in records:
        if not isinstance(item, Mapping) or item.get("source") != "lapa":
            continue
        path = _relative(item.get("relative_path"), "split-dedup path")
        group, split = item.get("split_group_id"), item.get("upstream_split")
        if (
            path in result
            or not isinstance(group, str)
            or not group
            or not isinstance(split, str)
            or not split
        ):
            raise LaPaControlCandidateError("split-dedup record drift")
        groups.setdefault(group, set()).add(split)
        result[path] = {
            "source_sha256": _sha(item.get("source_sha256"), "split-dedup source"),
            "split_group_id": group,
            "upstream_split": split,
        }
    for item in result.values():
        item["cross_split_group"] = "true" if len(groups[item["split_group_id"]]) > 1 else "false"
    if not result:
        raise LaPaControlCandidateError("LaPa records absent from split-dedup evidence")
    return result


def _assert_policy(provenance: Mapping[str, Any], remap: Mapping[str, Any]) -> list[str]:
    source = provenance.get("sources", {}).get("lapa", {})
    admission = source.get("training_admission", {}) if isinstance(source, Mapping) else {}
    if (
        provenance.get("policy", {}).get("source_masks_are_gold") is not False
        or not isinstance(admission.get("allowed_label_scope"), list)
        or "head_face" not in admission["allowed_label_scope"]
        or remap.get("source") != "lapa"
    ):
        raise LaPaControlCandidateError("LaPa policy contract drift")
    mappings = remap.get("mappings")
    if not isinstance(mappings, Mapping):
        raise LaPaControlCandidateError("LaPa remap is absent")
    names: list[str] = []
    for value in sorted(HEAD_FACE_VALUES):
        entry = mappings.get(value, mappings.get(str(value)))
        if (
            not isinstance(entry, Mapping)
            or entry.get("action") != "merge"
            or entry.get("part") != ["head_face"]
            or not isinstance(entry.get("source_label"), str)
        ):
            raise LaPaControlCandidateError(f"LaPa head-face remap drift:{value}")
        names.append(entry["source_label"])
    return names


def _candidate(
    root: Path,
    image: Path,
    manifest: Mapping[str, str],
    dedup: Mapping[str, Mapping[str, str]],
    names: list[str],
) -> dict[str, Any] | None:
    image_relative = image.relative_to(root).as_posix()
    parts = Path(image_relative).parts
    if len(parts) != 3 or parts[1] != "images" or image.suffix.casefold() != ".jpg":
        return None
    split = parts[0]
    label_relative = (Path(split) / "labels" / f"{image.stem}.png").as_posix()
    if image_relative not in manifest or label_relative not in manifest:
        raise LaPaControlCandidateError(f"source manifest omits input:{image_relative}")
    lineage = dedup.get(image_relative)
    if lineage is None:
        raise LaPaControlCandidateError(f"split-dedup omits input:{image_relative}")
    if lineage["cross_split_group"] == "true":
        return None
    label = _inside(root, label_relative, image_relative)
    image_sha, label_sha = manifest[image_relative], manifest[label_relative]
    if image_sha != lineage["source_sha256"] or split != lineage["upstream_split"]:
        raise LaPaControlCandidateError(f"source hash or split drift:{image_relative}")
    with Image.open(image) as opened:
        image_size = list(opened.size)
    with Image.open(label) as opened:
        indexed = np.asarray(opened.convert("L"), dtype=np.uint8)
    values = sorted(int(value) for value in np.unique(indexed))
    mask = np.isin(indexed, tuple(HEAD_FACE_VALUES))
    label_size = [int(indexed.shape[1]), int(indexed.shape[0])]
    if image_size != label_size or not set(values).issubset(set(range(11))):
        raise LaPaControlCandidateError(f"source/label geometry or encoding drift:{image_relative}")
    if not int(np.count_nonzero(mask)):
        return None
    source_id = f"lapa_{split}_{image.stem}"
    return {
        "sample_id": f"{source_id}_head_face",
        "source_image_id": source_id,
        "canonical_label": "head_face",
        "raw_label_values": sorted(HEAD_FACE_VALUES),
        "raw_label_names": names,
        "assigned_partition": _partition(split),
        "upstream_split": split,
        "split_group_id": lineage["split_group_id"],
        "source_relative_path": image_relative,
        "source_sha256": image_sha,
        "source_dimensions": image_size,
        "indexed_label_relative_path": label_relative,
        "indexed_label_sha256": label_sha,
        "indexed_label_dimensions": label_size,
        "indexed_label_values": values,
        "mask_pixel_count": int(np.count_nonzero(mask)),
        "alignment_policy": "source_and_indexed_label_geometry_must_match",
        "external_reference_qualification_complete": True,
        "visual_alignment_reviewed": False,
        "critic_control_eligible": False,
        "gold_or_production_authority": False,
    }


def build_lapa_control_candidates(
    *,
    source_root: Path,
    project_root: Path,
    provenance_path: Path,
    inventory_path: Path,
    remap_path: Path,
    qualification_evidence_path: Path,
    source_hash_manifest_path: Path,
    split_dedup_path: Path,
    per_partition: int = 8,
) -> dict[str, Any]:
    """Select exact, split-disjoint controls only after live qualification passes."""
    if per_partition < 1:
        raise LaPaControlCandidateError("per-partition count must be positive")
    root, project = Path(source_root).resolve(strict=True), Path(project_root).resolve(strict=True)
    provenance, inventory, remap = (
        _document(Path(provenance_path), yaml_input=True),
        _document(Path(inventory_path)),
        _document(Path(remap_path), yaml_input=True),
    )
    bundle, manifest_document, dedup_document = (
        _document(Path(qualification_evidence_path)),
        _document(Path(source_hash_manifest_path)),
        _document(Path(split_dedup_path)),
    )
    names = _assert_policy(provenance, remap)
    qualification = verify_external_qualification_evidence(
        provenance, inventory, source="lapa", evidence_bundle=bundle, project_root=project
    )
    if not qualification.admitted:
        raise LaPaControlCandidateError(
            "LaPa external qualification is not admitted:"
            + ",".join(qualification.unmet_gates or qualification.evidence_tokens)
        )
    manifest, dedup = _manifest_index(manifest_document), _dedup_index(dedup_document)
    pools: dict[str, list[dict[str, Any]]] = {item: [] for item in PARTITIONS}
    for image in sorted(root.glob("*/images/*.jpg"), key=lambda item: item.as_posix()):
        row = _candidate(root, image, manifest, dedup, names)
        if row is not None:
            pools[row["assigned_partition"]].append(row)
    selected: list[dict[str, Any]] = []
    used_groups: set[str] = set()
    for partition in PARTITIONS:
        ranked = sorted(
            pools[partition],
            key=lambda row: canonical_sha256(
                {
                    "source_relative_path": row["source_relative_path"],
                    "source_sha256": row["source_sha256"],
                    "indexed_label_sha256": row["indexed_label_sha256"],
                }
            ),
        )
        chosen: list[dict[str, Any]] = []
        for row in ranked:
            if row["split_group_id"] in used_groups:
                continue
            chosen.append(row)
            used_groups.add(row["split_group_id"])
            if len(chosen) == per_partition:
                break
        if len(chosen) != per_partition:
            raise LaPaControlCandidateError(f"insufficient split-disjoint candidates:{partition}")
        selected.extend(chosen)
    selected.sort(key=lambda row: (row["assigned_partition"], row["sample_id"]))
    for row in selected:
        image = _inside(root, row["source_relative_path"], row["sample_id"])
        label = _inside(root, row["indexed_label_relative_path"], row["sample_id"])
        if (
            sha256_file(image) != row["source_sha256"]
            or sha256_file(label) != row["indexed_label_sha256"]
        ):
            raise LaPaControlCandidateError(f"selected source hash drift:{row['sample_id']}")
    by_partition = Counter(row["assigned_partition"] for row in selected)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "lapa_exact_head_face_control_candidates",
        "input_bindings": {
            "provenance_sha256": sha256_file(Path(provenance_path)),
            "inventory_sha256": sha256_file(Path(inventory_path)),
            "remap_sha256": sha256_file(Path(remap_path)),
            "qualification_evidence_sha256": sha256_file(Path(qualification_evidence_path)),
            "qualification_evidence_bundle_sha256": qualification.evidence_bundle_sha256,
            "source_hash_manifest_sha256": sha256_file(Path(source_hash_manifest_path)),
            "source_hash_manifest_seal_sha256": manifest_document["seal_sha256"],
            "split_dedup_sha256": sha256_file(Path(split_dedup_path)),
        },
        "selection_policy": {
            "canonical_label": "head_face",
            "exact_source_values": sorted(HEAD_FACE_VALUES),
            "upstream_partition_mapping": {
                "train": "qualification_train",
                "val": "qualification_test",
                "test": "qualification_test",
            },
            "partitions": list(PARTITIONS),
            "per_partition": per_partition,
            "selection_order": "sha256(source_relative_path,source_sha256,indexed_label_sha256)",
            "split_group_disjoint": True,
        },
        "selected_count": len(selected),
        "selected_by_label": {"head_face": len(selected)},
        "selected_by_partition": dict(sorted(by_partition.items())),
        "selected": selected,
        "authority_claimed": False,
        "critic_control_authority_granted": False,
        "gold_or_production_authority_granted": False,
        "claim_limits": [
            "LaPa remains qualified external weighted pseudo-label supervision, never gold or holdout truth.",
            "Candidates are calibration-only and require per-record panel screening under Amendment 2.",
            "Exact head-face semantics are limited to the governed LaPa 1..9 merge.",
            "No critic role, certificate, production-mask, package, or training-truth authority is granted.",
        ],
        "next_required_stage": "materialize_exact_panels_then_per_record_control_admission_screening",
    }
    result["self_sha256"] = canonical_sha256(result)
    verify_lapa_control_candidates(result)
    return result


def verify_lapa_control_candidates(document: Mapping[str, Any]) -> None:
    """Verify self binding, exact remap fields, partitions, and authority ceiling."""
    if document.get("self_sha256") != canonical_sha256(
        {key: value for key, value in document.items() if key != "self_sha256"}
    ):
        raise LaPaControlCandidateError("candidate self-hash drift")
    if (
        document.get("schema_version") != SCHEMA_VERSION
        or document.get("artifact_type") != "lapa_exact_head_face_control_candidates"
        or document.get("authority_claimed") is not False
        or document.get("critic_control_authority_granted") is not False
        or document.get("gold_or_production_authority_granted") is not False
    ):
        raise LaPaControlCandidateError("candidate authority or schema drift")
    bindings = document.get("input_bindings")
    expected = {
        "provenance_sha256",
        "inventory_sha256",
        "remap_sha256",
        "qualification_evidence_sha256",
        "qualification_evidence_bundle_sha256",
        "source_hash_manifest_sha256",
        "source_hash_manifest_seal_sha256",
        "split_dedup_sha256",
    }
    if not isinstance(bindings, Mapping) or set(bindings) != expected:
        raise LaPaControlCandidateError("candidate input bindings drift")
    for key, value in bindings.items():
        _sha(value, key)
    rows = document.get("selected")
    if not isinstance(rows, list) or document.get("selected_count") != len(rows):
        raise LaPaControlCandidateError("candidate count drift")
    groups: set[str] = set()
    ids: set[str] = set()
    counts: Counter[str] = Counter()
    for row in rows:
        if not isinstance(row, Mapping):
            raise LaPaControlCandidateError("candidate record malformed")
        sample_id, group, partition = (
            row.get("sample_id"),
            row.get("split_group_id"),
            row.get("assigned_partition"),
        )
        if (
            not isinstance(sample_id, str)
            or not sample_id
            or sample_id in ids
            or not isinstance(group, str)
            or not group
            or group in groups
            or partition not in PARTITIONS
            or row.get("canonical_label") != "head_face"
            or row.get("raw_label_values") != sorted(HEAD_FACE_VALUES)
            or row.get("external_reference_qualification_complete") is not True
            or row.get("visual_alignment_reviewed") is not False
            or row.get("critic_control_eligible") is not False
            or row.get("gold_or_production_authority") is not False
            or partition != _partition(str(row.get("upstream_split")))
        ):
            raise LaPaControlCandidateError("candidate identity or authority drift")
        for field in ("source_sha256", "indexed_label_sha256"):
            _sha(row.get(field), field)
        for field in ("source_relative_path", "indexed_label_relative_path"):
            _relative(row.get(field), field)
        dimensions = row.get("source_dimensions")
        if (
            not isinstance(dimensions, list)
            or dimensions != row.get("indexed_label_dimensions")
            or len(dimensions) != 2
            or any(not isinstance(value, int) or value <= 0 for value in dimensions)
            or not isinstance(row.get("mask_pixel_count"), int)
            or row["mask_pixel_count"] <= 0
        ):
            raise LaPaControlCandidateError("candidate geometry drift")
        groups.add(group)
        ids.add(sample_id)
        counts[partition] += 1
    if document.get("selected_by_label") != {"head_face": len(rows)} or document.get(
        "selected_by_partition"
    ) != dict(sorted(counts.items())):
        raise LaPaControlCandidateError("candidate summary count drift")


def materialize_lapa_control_panels(
    *, source_root: Path, candidate_document: Mapping[str, Any], output_root: Path
) -> dict[str, Any]:
    """Render exact source/indexed-map panels; no candidate becomes admitted here."""
    verify_lapa_control_candidates(candidate_document)
    root, output = Path(source_root).resolve(strict=True), Path(output_root)
    if output.exists():
        raise LaPaControlCandidateError("panel output already exists")
    stage = output.with_name(f".{output.name}.tmp-{uuid.uuid4().hex}")
    rows: list[dict[str, Any]] = []
    try:
        stage.mkdir(parents=True)
        for candidate in candidate_document["selected"]:
            sample_id = str(candidate["sample_id"])
            image = _inside(root, candidate["source_relative_path"], sample_id)
            label = _inside(root, candidate["indexed_label_relative_path"], sample_id)
            if (
                sha256_file(image) != candidate["source_sha256"]
                or sha256_file(label) != candidate["indexed_label_sha256"]
            ):
                raise LaPaControlCandidateError(f"source or label hash drift:{sample_id}")
            with Image.open(image) as opened:
                source = np.asarray(opened.convert("RGB"), dtype=np.uint8)
            with Image.open(label) as opened:
                indexed = np.asarray(opened.convert("L"), dtype=np.uint8)
            if (
                list(source.shape[1::-1]) != candidate["source_dimensions"]
                or list(indexed.shape[1::-1]) != candidate["indexed_label_dimensions"]
                or source.shape[:2] != indexed.shape
                or sorted(int(value) for value in np.unique(indexed))
                != candidate["indexed_label_values"]
            ):
                raise LaPaControlCandidateError(f"source or label geometry drift:{sample_id}")
            mask = np.isin(indexed, tuple(HEAD_FACE_VALUES))
            if int(np.count_nonzero(mask)) != candidate["mask_pixel_count"]:
                raise LaPaControlCandidateError(f"head-face remap pixel drift:{sample_id}")
            panels = render_candidate_panels(source, mask, stage / sample_id)
            rows.append(
                {
                    **candidate,
                    "source_path_runpod": image.as_posix(),
                    "indexed_label_path_runpod": label.as_posix(),
                    "source_encoded_sha256_verified": True,
                    "indexed_label_sha256_verified": True,
                    "head_face_remap_pixels_verified": True,
                    **panels,
                    "visual_alignment_reviewed": False,
                    "critic_control_eligible": False,
                    "gold_or_production_authority": False,
                }
            )
        width, height, columns = 720, 260, 4
        contact = Image.new(
            "RGB",
            (width * columns, height * ((len(rows) + columns - 1) // columns)),
            color=(18, 18, 18),
        )
        draw = ImageDraw.Draw(contact)
        for index, row in enumerate(rows):
            with Image.open(stage / row["sample_id"] / row["panel_files"]["target_zoom"]) as opened:
                tile = opened.convert("RGB")
                tile.thumbnail((width, height - 24), Image.Resampling.LANCZOS)
                tile = tile.copy()
            x, y = (index % columns) * width, (index // columns) * height
            contact.paste(tile, (x, y + 24))
            draw.text((x + 4, y + 4), f"{index + 1:02d} {row['sample_id']}", fill=(255, 255, 255))
        contact_path = stage / "contact_sheet.png"
        contact.save(contact_path, format="PNG", optimize=False, compress_level=9)
        report: dict[str, Any] = {
            "schema_version": PANEL_SCHEMA_VERSION,
            "artifact_type": "lapa_exact_head_face_visual_evidence",
            "authority_claimed": False,
            "visual_alignment_qualification_complete": False,
            "critic_control_authority_granted": False,
            "candidate_set_sha256": candidate_document["self_sha256"],
            "record_count": len(rows),
            "panel_count": len(rows) * len(PANEL_NAMES),
            "panels_per_record": list(PANEL_NAMES),
            "contact_sheet": {
                "path": "contact_sheet.png",
                "sha256": sha256_file(contact_path),
                "scheduling_and_navigation_aid_only": True,
                "per_record_evidence_required": True,
            },
            "records": rows,
            "next_required_stage": "per_record_visual_alignment_and_control_admission_screening",
            "claim_limits": [
                "Exact indexed-map rendering does not complete per-record control admission.",
                "Contact sheets are scheduling and navigation aids only.",
                "No critic-control, gold, certificate, package, or production authority.",
            ],
        }
        report["self_sha256"] = canonical_sha256(report)
        (stage / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(stage, output)
        return report
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def verify_lapa_control_panel_report(document: Mapping[str, Any], root: Path) -> None:
    """Verify all rendered panel hashes and reject authority upgrades."""
    if document.get("self_sha256") != canonical_sha256(
        {key: value for key, value in document.items() if key != "self_sha256"}
    ):
        raise LaPaControlCandidateError("panel report self-hash drift")
    if (
        document.get("schema_version") != PANEL_SCHEMA_VERSION
        or document.get("artifact_type") != "lapa_exact_head_face_visual_evidence"
        or document.get("authority_claimed") is not False
        or document.get("visual_alignment_qualification_complete") is not False
        or document.get("critic_control_authority_granted") is not False
    ):
        raise LaPaControlCandidateError("panel report authority or schema drift")
    rows = document.get("records")
    if (
        not isinstance(rows, list)
        or document.get("record_count") != len(rows)
        or document.get("panel_count") != len(rows) * len(PANEL_NAMES)
    ):
        raise LaPaControlCandidateError("panel report count drift")
    output = Path(root).resolve(strict=True)
    for row in rows:
        if (
            row.get("visual_alignment_reviewed") is not False
            or row.get("critic_control_eligible") is not False
            or row.get("gold_or_production_authority") is not False
        ):
            raise LaPaControlCandidateError("panel record authority drift")
        for name in PANEL_NAMES:
            path = (output / str(row["sample_id"]) / row["panel_files"][name]).resolve(strict=True)
            try:
                path.relative_to(output)
            except ValueError as exc:
                raise LaPaControlCandidateError("panel path escapes output root") from exc
            if sha256_file(path) != row["panel_sha256s"][name]:
                raise LaPaControlCandidateError(f"panel hash drift:{row['sample_id']}:{name}")
    contact = document.get("contact_sheet", {})
    path = (output / str(contact.get("path"))).resolve(strict=True)
    if (
        contact.get("scheduling_and_navigation_aid_only") is not True
        or contact.get("per_record_evidence_required") is not True
        or sha256_file(path) != contact.get("sha256")
    ):
        raise LaPaControlCandidateError("contact-sheet binding drift")
