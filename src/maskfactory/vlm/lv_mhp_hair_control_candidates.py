"""Fail-closed LV-MHP label-2 per-person hair control materializer."""

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

SCHEMA = "maskfactory.lv_mhp_v1_hair_control_candidates.v1"
PANEL_SCHEMA = "maskfactory.lv_mhp_v1_hair_control_panels.v1"
SOURCE_DIR, HAIR = "LV-MHP-v1", 2
PARTITIONS = {"train": "qualification_train", "test": "qualification_test"}


class LvMhpHairControlCandidateError(ValueError):
    """An exact LV-MHP input, evidence gate, or authority ceiling drifted."""


def _read(path: Path, yaml_input: bool = False) -> Mapping[str, Any]:
    try:
        value = yaml.safe_load(path.read_text()) if yaml_input else json.loads(path.read_text())
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise LvMhpHairControlCandidateError(f"invalid document:{path}") from exc
    if not isinstance(value, Mapping):
        raise LvMhpHairControlCandidateError(f"document not mapping:{path}")
    return value


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise LvMhpHairControlCandidateError(f"invalid sha:{field}")
    try:
        int(value, 16)
    except ValueError as exc:
        raise LvMhpHairControlCandidateError(f"invalid sha:{field}") from exc
    return value


def _rel(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or Path(value).is_absolute()
        or ".." in Path(value).parts
    ):
        raise LvMhpHairControlCandidateError(f"unsafe path:{field}")
    return Path(value).as_posix()


def _content(root: Path) -> Path:
    root = Path(root).resolve(strict=True)
    result = root / SOURCE_DIR if (root / SOURCE_DIR).is_dir() else root
    if (
        result.name != SOURCE_DIR
        or not (result / "images").is_dir()
        or not (result / "annotations").is_dir()
    ):
        raise LvMhpHairControlCandidateError("LV-MHP source-tree drift")
    return result


def _inside(root: Path, relative: str) -> Path:
    result = (root / relative).resolve(strict=True)
    try:
        result.relative_to(root)
    except ValueError as exc:
        raise LvMhpHairControlCandidateError(f"source escape:{relative}") from exc
    return result


def _manifest(document: Mapping[str, Any]) -> dict[str, str]:
    expected = {
        "schema_version": "1.0.0",
        "artifact_type": "external_supervision_source_hash_manifest",
        "source": "lv_mhp_v1",
        "gate": "source_hash_manifested",
        "status": "PASS",
    }
    if any(document.get(key) != value for key, value in expected.items()) or document.get(
        "seal_sha256"
    ) != seal_payload(document):
        raise LvMhpHairControlCandidateError("source-hash gate drift")
    result: dict[str, str] = {}
    for row in document.get("files", []):
        if (
            not isinstance(row, Mapping)
            or set(row) != {"path", "size", "sha256"}
            or not isinstance(row["size"], int)
            or row["size"] < 0
        ):
            raise LvMhpHairControlCandidateError("source-hash row drift")
        path = _rel(row["path"], "manifest")
        if path in result:
            raise LvMhpHairControlCandidateError("duplicate manifest path")
        result[path] = _sha(row["sha256"], "manifest")
    if not result or document.get("file_count") != len(result):
        raise LvMhpHairControlCandidateError("source-hash count drift")
    return result


def _identity(document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    expected = {
        "schema_version": "1.0.0",
        "artifact_type": "external_supervision_identity_evidence",
        "source": "lv_mhp_v1",
        "gate": "instance_identity_validated",
        "status": "PASS",
    }
    if any(document.get(key) != value for key, value in expected.items()) or document.get(
        "seal_sha256"
    ) != seal_payload(document):
        raise LvMhpHairControlCandidateError("identity gate drift")
    result: dict[str, Mapping[str, Any]] = {}
    count = 0
    for row in document.get("records", []):
        if not isinstance(row, Mapping):
            raise LvMhpHairControlCandidateError("identity row malformed")
        image_id, paths, ids, people = (
            row.get("image_id"),
            row.get("annotation_paths"),
            row.get("instance_ids"),
            row.get("person_count"),
        )
        if (
            not isinstance(image_id, str)
            or image_id in result
            or _rel(row.get("image_path"), "identity image") != f"images/{image_id}.jpg"
            or not isinstance(paths, list)
            or not isinstance(ids, list)
            or not isinstance(people, int)
            or people < 1
            or ids != list(range(1, people + 1))
            or len(paths) != people
        ):
            raise LvMhpHairControlCandidateError("identity row drift")
        if [_rel(path, "identity annotation") for path in paths] != [
            f"annotations/{image_id}_{people:02d}_{item:02d}.png" for item in ids
        ]:
            raise LvMhpHairControlCandidateError("identity annotation binding drift")
        result[image_id] = row
        count += people
    if (
        not result
        or document.get("image_count") != len(result)
        or document.get("annotation_count") != count
    ):
        raise LvMhpHairControlCandidateError("identity count drift")
    return result


def _dedup(document: Mapping[str, Any], content: Path) -> dict[str, dict[str, Any]]:
    if document.get("status") != "PASS" or (
        document.get("seal_sha256") is not None
        and document["seal_sha256"] != seal_payload(document)
    ):
        raise LvMhpHairControlCandidateError("dedup gate drift")
    result, groups, prefix = {}, {}, f"{content.name}/"
    for row in document.get("records", []):
        if not isinstance(row, Mapping) or row.get("source") != "lv_mhp_v1":
            continue
        external, group, split = (
            _rel(row.get("relative_path"), "dedup"),
            row.get("split_group_id"),
            row.get("upstream_split"),
        )
        if (
            not external.startswith(prefix)
            or not isinstance(group, str)
            or not group
            or split not in PARTITIONS
        ):
            raise LvMhpHairControlCandidateError("dedup row drift")
        relative = external.removeprefix(prefix)
        if relative in result:
            raise LvMhpHairControlCandidateError("duplicate dedup path")
        result[relative] = {
            "source_sha256": _sha(row.get("source_sha256"), "dedup"),
            "split_group_id": group,
            "split": split,
        }
        groups.setdefault(group, set()).add(split)
    for row in result.values():
        row["cross_split"] = len(groups[row["split_group_id"]]) > 1
    if not result:
        raise LvMhpHairControlCandidateError("LV-MHP absent from dedup gate")
    return result


def build_lv_mhp_hair_control_candidates(
    *,
    source_root: Path,
    project_root: Path,
    provenance_path: Path,
    inventory_path: Path,
    remap_path: Path,
    qualification_evidence_path: Path,
    source_hash_manifest_path: Path,
    identity_evidence_path: Path,
    split_dedup_path: Path,
    per_partition: int = 8,
) -> dict[str, Any]:
    """Return exact direct label-2 hair candidates after every live gate passes."""
    if per_partition < 1:
        raise LvMhpHairControlCandidateError("per-partition must be positive")
    content = _content(source_root)
    provenance, inventory, remap = (
        _read(provenance_path, True),
        _read(inventory_path),
        _read(remap_path, True),
    )
    source = provenance.get("sources", {}).get("lv_mhp_v1", {})
    allowed = (
        source.get("training_admission", {}).get("allowed_label_scope")
        if isinstance(source, Mapping)
        else None
    )
    entry = remap.get("mappings", {}).get(HAIR, remap.get("mappings", {}).get(str(HAIR)))
    if (
        provenance.get("policy", {}).get("source_masks_are_gold") is not False
        or not isinstance(allowed, list)
        or "hair" not in allowed
        or remap.get("source") != "lv_mhp_v1"
        or not isinstance(entry, Mapping)
        or entry.get("source_label") != "hair"
        or entry.get("action") != "direct"
        or entry.get("part") != ["hair"]
    ):
        raise LvMhpHairControlCandidateError("direct hair policy/remap drift")
    bundle, source_doc, identity_doc, dedup_doc = (
        _read(qualification_evidence_path),
        _read(source_hash_manifest_path),
        _read(identity_evidence_path),
        _read(split_dedup_path),
    )
    qualified = verify_external_qualification_evidence(
        provenance,
        inventory,
        source="lv_mhp_v1",
        evidence_bundle=bundle,
        project_root=Path(project_root).resolve(strict=True),
    )
    if not qualified.admitted:
        raise LvMhpHairControlCandidateError(
            "external qualification not admitted:"
            + ",".join(qualified.unmet_gates or qualified.evidence_tokens)
        )
    manifest, identities, dedup = (
        _manifest(source_doc),
        _identity(identity_doc),
        _dedup(dedup_doc, content),
    )
    pools = {part: [] for part in PARTITIONS.values()}
    for image_id, identity in identities.items():
        image_rel, lineage = f"images/{image_id}.jpg", dedup.get(f"images/{image_id}.jpg")
        if lineage is None or lineage["cross_split"]:
            continue
        for instance in identity["instance_ids"]:
            annotation_rel = identity["annotation_paths"][instance - 1]
            if (
                image_rel not in manifest
                or annotation_rel not in manifest
                or manifest[image_rel] != lineage["source_sha256"]
            ):
                raise LvMhpHairControlCandidateError(f"hash/split drift:{image_id}")
            with Image.open(_inside(content, image_rel)) as opened:
                dimensions = list(opened.size)
            with Image.open(_inside(content, annotation_rel)) as opened:
                indexed = np.asarray(opened.convert("L"), dtype=np.uint8)
            annotation_dimensions, values, mask = (
                [int(indexed.shape[1]), int(indexed.shape[0])],
                sorted(int(value) for value in np.unique(indexed)),
                indexed == HAIR,
            )
            if dimensions != annotation_dimensions or not set(values).issubset(set(range(19))):
                raise LvMhpHairControlCandidateError(f"encoding drift:{image_id}:{instance}")
            if not int(np.count_nonzero(mask)):
                continue
            stem = f"lv_mhp_v1_{image_id}_p{instance:02d}"
            pools[PARTITIONS[lineage["split"]]].append(
                {
                    "sample_id": f"{stem}_hair",
                    "source_image_id": f"lv_mhp_v1_{image_id}",
                    "source_instance_id": instance,
                    "declared_person_count": identity["person_count"],
                    "canonical_label": "hair",
                    "raw_label_values": [HAIR],
                    "raw_label_names": ["hair"],
                    "assigned_partition": PARTITIONS[lineage["split"]],
                    "upstream_split": lineage["split"],
                    "split_group_id": lineage["split_group_id"],
                    "source_relative_path": image_rel,
                    "split_dedup_relative_path": f"{content.name}/{image_rel}",
                    "source_sha256": manifest[image_rel],
                    "source_dimensions": dimensions,
                    "instance_annotation_relative_path": annotation_rel,
                    "instance_annotation_sha256": manifest[annotation_rel],
                    "instance_annotation_dimensions": annotation_dimensions,
                    "indexed_label_values": values,
                    "mask_pixel_count": int(np.count_nonzero(mask)),
                    "instance_identity_verified": True,
                    "external_reference_qualification_complete": True,
                    "visual_alignment_reviewed": False,
                    "critic_control_eligible": False,
                    "gold_or_production_authority": False,
                }
            )
    selected, used = [], set()
    for part in PARTITIONS.values():
        chosen = []
        for row in sorted(
            pools[part],
            key=lambda item: canonical_sha256(
                {
                    "image": item["source_relative_path"],
                    "source": item["source_sha256"],
                    "annotation": item["instance_annotation_sha256"],
                }
            ),
        ):
            if row["split_group_id"] not in used:
                chosen.append(row)
                used.add(row["split_group_id"])
            if len(chosen) == per_partition:
                break
        if len(chosen) != per_partition:
            raise LvMhpHairControlCandidateError(
                f"insufficient split-disjoint hair candidates:{part}"
            )
        selected.extend(chosen)
    selected.sort(key=lambda row: (row["assigned_partition"], row["sample_id"]))
    for row in selected:
        if (
            sha256_file(_inside(content, row["source_relative_path"])) != row["source_sha256"]
            or sha256_file(_inside(content, row["instance_annotation_relative_path"]))
            != row["instance_annotation_sha256"]
        ):
            raise LvMhpHairControlCandidateError(f"selected hash drift:{row['sample_id']}")
    counts = Counter(row["assigned_partition"] for row in selected)
    result: dict[str, Any] = {
        "schema_version": SCHEMA,
        "artifact_type": "lv_mhp_v1_exact_hair_control_candidates",
        "input_bindings": {
            "provenance_sha256": sha256_file(provenance_path),
            "inventory_sha256": sha256_file(inventory_path),
            "remap_sha256": sha256_file(remap_path),
            "qualification_evidence_sha256": sha256_file(qualification_evidence_path),
            "qualification_evidence_bundle_sha256": qualified.evidence_bundle_sha256,
            "source_hash_manifest_sha256": sha256_file(source_hash_manifest_path),
            "source_hash_manifest_seal_sha256": source_doc["seal_sha256"],
            "identity_evidence_sha256": sha256_file(identity_evidence_path),
            "split_dedup_sha256": sha256_file(split_dedup_path),
        },
        "selection_policy": {
            "canonical_label": "hair",
            "exact_source_values": [HAIR],
            "source_encoding": "per-person 8-bit indexed PNG",
            "upstream_partition_mapping": PARTITIONS,
            "partitions": list(PARTITIONS.values()),
            "per_partition": per_partition,
            "selection_order": "sha256(image,source,annotation)",
            "split_group_disjoint": True,
            "one_candidate_per_source_identity_group": True,
        },
        "selected_count": len(selected),
        "selected_by_label": {"hair": len(selected)},
        "selected_by_partition": dict(sorted(counts.items())),
        "selected": selected,
        "authority_claimed": False,
        "critic_control_authority_granted": False,
        "gold_or_production_authority_granted": False,
        "claim_limits": [
            "LV-MHP remains qualified external weighted pseudo-label supervision, never gold or holdout truth.",
            "Candidates are calibration-only and require per-record panel screening under Amendment 2.",
            "Exact hair semantics are limited to LV-MHP per-person label 2 direct mapping.",
            "No critic role, certificate, production-mask, package, or training-truth authority is granted.",
        ],
        "next_required_stage": "materialize_exact_panels_then_per_record_control_admission_screening",
    }
    result["self_sha256"] = canonical_sha256(result)
    verify_lv_mhp_hair_control_candidates(result)
    return result


def verify_lv_mhp_hair_control_candidates(document: Mapping[str, Any]) -> None:
    """Verify self-binding, split isolation, exact hair semantics, and authority ceiling."""
    if document.get("self_sha256") != canonical_sha256(
        {key: value for key, value in document.items() if key != "self_sha256"}
    ):
        raise LvMhpHairControlCandidateError("candidate hash drift")
    rows = document.get("selected")
    if (
        document.get("schema_version") != SCHEMA
        or document.get("artifact_type") != "lv_mhp_v1_exact_hair_control_candidates"
        or document.get("authority_claimed") is not False
        or document.get("critic_control_authority_granted") is not False
        or document.get("gold_or_production_authority_granted") is not False
        or not isinstance(rows, list)
        or document.get("selected_count") != len(rows)
    ):
        raise LvMhpHairControlCandidateError("candidate contract drift")
    ids, groups, counts = set(), set(), Counter()
    for row in rows:
        if (
            not isinstance(row, Mapping)
            or not isinstance(row.get("sample_id"), str)
            or row["sample_id"] in ids
            or not isinstance(row.get("split_group_id"), str)
            or row["split_group_id"] in groups
            or row.get("canonical_label") != "hair"
            or row.get("raw_label_values") != [HAIR]
            or row.get("raw_label_names") != ["hair"]
            or row.get("assigned_partition") != PARTITIONS.get(row.get("upstream_split"))
            or row.get("instance_identity_verified") is not True
            or row.get("external_reference_qualification_complete") is not True
            or row.get("visual_alignment_reviewed") is not False
            or row.get("critic_control_eligible") is not False
            or row.get("gold_or_production_authority") is not False
            or not isinstance(row.get("mask_pixel_count"), int)
            or row["mask_pixel_count"] <= 0
            or row.get("source_dimensions") != row.get("instance_annotation_dimensions")
        ):
            raise LvMhpHairControlCandidateError("candidate identity/authority/geometry drift")
        _sha(row.get("source_sha256"), "source")
        _sha(row.get("instance_annotation_sha256"), "annotation")
        ids.add(row["sample_id"])
        groups.add(row["split_group_id"])
        counts[row["assigned_partition"]] += 1
    if document.get("selected_by_label") != {"hair": len(rows)} or document.get(
        "selected_by_partition"
    ) != dict(sorted(counts.items())):
        raise LvMhpHairControlCandidateError("candidate summary drift")


def materialize_lv_mhp_hair_control_panels(
    *, source_root: Path, candidate_document: Mapping[str, Any], output_root: Path
) -> dict[str, Any]:
    """Render exact source/mask panels without admitting any control."""
    verify_lv_mhp_hair_control_candidates(candidate_document)
    content, output = _content(source_root), Path(output_root)
    if output.exists():
        raise LvMhpHairControlCandidateError("panel output exists")
    stage, records = output.with_name(f".{output.name}.tmp-{uuid.uuid4().hex}"), []
    try:
        stage.mkdir(parents=True)
        for row in candidate_document["selected"]:
            image, annotation = _inside(content, row["source_relative_path"]), _inside(
                content, row["instance_annotation_relative_path"]
            )
            if (
                sha256_file(image) != row["source_sha256"]
                or sha256_file(annotation) != row["instance_annotation_sha256"]
            ):
                raise LvMhpHairControlCandidateError(f"source hash drift:{row['sample_id']}")
            with Image.open(image) as opened:
                source = np.asarray(opened.convert("RGB"), dtype=np.uint8)
            with Image.open(annotation) as opened:
                indexed = np.asarray(opened.convert("L"), dtype=np.uint8)
            mask = indexed == HAIR
            if (
                list(source.shape[1::-1]) != row["source_dimensions"]
                or list(indexed.shape[1::-1]) != row["instance_annotation_dimensions"]
                or source.shape[:2] != indexed.shape
                or sorted(int(value) for value in np.unique(indexed)) != row["indexed_label_values"]
                or int(np.count_nonzero(mask)) != row["mask_pixel_count"]
            ):
                raise LvMhpHairControlCandidateError(f"panel geometry drift:{row['sample_id']}")
            panels = render_candidate_panels(source, mask, stage / row["sample_id"])
            records.append(
                {
                    **row,
                    "source_path_runpod": image.as_posix(),
                    "instance_annotation_path_runpod": annotation.as_posix(),
                    "source_encoded_sha256_verified": True,
                    "instance_annotation_sha256_verified": True,
                    "hair_remap_pixels_verified": True,
                    **panels,
                    "visual_alignment_reviewed": False,
                    "critic_control_eligible": False,
                    "gold_or_production_authority": False,
                }
            )
        width, height, columns = 720, 260, 4
        contact = Image.new(
            "RGB",
            (width * columns, height * ((len(records) + columns - 1) // columns)),
            color=(18, 18, 18),
        )
        draw = ImageDraw.Draw(contact)
        for index, row in enumerate(records):
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
            "schema_version": PANEL_SCHEMA,
            "artifact_type": "lv_mhp_v1_exact_hair_visual_evidence",
            "authority_claimed": False,
            "visual_alignment_qualification_complete": False,
            "critic_control_authority_granted": False,
            "candidate_set_sha256": candidate_document["self_sha256"],
            "record_count": len(records),
            "panel_count": len(records) * len(PANEL_NAMES),
            "panels_per_record": list(PANEL_NAMES),
            "contact_sheet": {
                "path": "contact_sheet.png",
                "sha256": sha256_file(contact_path),
                "scheduling_and_navigation_aid_only": True,
                "per_record_evidence_required": True,
            },
            "records": records,
            "next_required_stage": "per_record_visual_alignment_and_control_admission_screening",
            "claim_limits": [
                "Exact rendering does not complete control admission.",
                "Contact sheets are navigation aids only.",
                "No critic-control, gold, certificate, package, or production authority.",
            ],
        }
        report["self_sha256"] = canonical_sha256(report)
        (stage / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        os.replace(stage, output)
        return report
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def verify_lv_mhp_hair_control_panel_report(document: Mapping[str, Any], root: Path) -> None:
    """Verify every panel hash and authority ceiling."""
    if (
        document.get("self_sha256")
        != canonical_sha256({key: value for key, value in document.items() if key != "self_sha256"})
        or document.get("schema_version") != PANEL_SCHEMA
        or document.get("artifact_type") != "lv_mhp_v1_exact_hair_visual_evidence"
        or document.get("authority_claimed") is not False
        or document.get("visual_alignment_qualification_complete") is not False
        or document.get("critic_control_authority_granted") is not False
    ):
        raise LvMhpHairControlCandidateError("panel report contract drift")
    records, output = document.get("records"), Path(root).resolve(strict=True)
    if (
        not isinstance(records, list)
        or document.get("record_count") != len(records)
        or document.get("panel_count") != len(records) * len(PANEL_NAMES)
    ):
        raise LvMhpHairControlCandidateError("panel report count drift")
    for row in records:
        if (
            row.get("visual_alignment_reviewed") is not False
            or row.get("critic_control_eligible") is not False
            or row.get("gold_or_production_authority") is not False
        ):
            raise LvMhpHairControlCandidateError("panel authority drift")
        for name in PANEL_NAMES:
            path = (output / row["sample_id"] / row["panel_files"][name]).resolve(strict=True)
            try:
                path.relative_to(output)
            except ValueError as exc:
                raise LvMhpHairControlCandidateError("panel path escapes output") from exc
            if sha256_file(path) != row["panel_sha256s"][name]:
                raise LvMhpHairControlCandidateError(f"panel hash drift:{row['sample_id']}:{name}")
    contact = document.get("contact_sheet", {})
    path = (output / str(contact.get("path"))).resolve(strict=True)
    if (
        contact.get("scheduling_and_navigation_aid_only") is not True
        or contact.get("per_record_evidence_required") is not True
        or sha256_file(path) != contact.get("sha256")
    ):
        raise LvMhpHairControlCandidateError("contact-sheet drift")
