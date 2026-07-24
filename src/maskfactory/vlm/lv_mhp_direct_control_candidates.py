"""Fail-closed LV-MHP direct-label calibration candidate selection."""
from __future__ import annotations
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any
import numpy as np
from PIL import Image
from ..external_supervision_qualification import verify_external_qualification_evidence
from .canonical_polygon_source_candidates import sha256_file
from .critic_catalog import canonical_sha256
from .lv_mhp_hair_control_candidates import PARTITIONS, _content, _dedup, _identity, _inside, _manifest, _read, _sha
SCHEMA = "maskfactory.lv_mhp_v1_direct_control_candidates.v1"

class LvMhpDirectControlCandidateError(ValueError):
    """Exact direct-label control selection cannot be proven."""

def _label(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or not value.replace("_", "").isalnum():
        raise LvMhpDirectControlCandidateError(f"invalid label:{field}")
    return value

def _value(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 255:
        raise LvMhpDirectControlCandidateError("invalid source value")
    return value

def build_lv_mhp_direct_control_candidates(*, source_root: Path, project_root: Path, provenance_path: Path, inventory_path: Path, remap_path: Path, qualification_evidence_path: Path, source_hash_manifest_path: Path, identity_evidence_path: Path, split_dedup_path: Path, source_value: int, source_label: str, canonical_label: str, per_partition: int = 8) -> dict[str, Any]:
    """Select one exact direct-mapped LV-MHP label as calibration-only candidates."""
    source_value, source_label, canonical_label = _value(source_value), _label(source_label, "source"), _label(canonical_label, "canonical")
    if per_partition < 1:
        raise LvMhpDirectControlCandidateError("per-partition must be positive")
    content, provenance, inventory, remap = _content(source_root), _read(provenance_path, True), _read(inventory_path), _read(remap_path, True)
    source = provenance.get("sources", {}).get("lv_mhp_v1", {})
    allowed = source.get("training_admission", {}).get("allowed_label_scope") if isinstance(source, Mapping) else None
    mappings = remap.get("mappings")
    entry = mappings.get(source_value, mappings.get(str(source_value))) if isinstance(mappings, Mapping) else None
    if provenance.get("policy", {}).get("source_masks_are_gold") is not False or not isinstance(allowed, list) or canonical_label not in allowed:
        raise LvMhpDirectControlCandidateError("source admission policy drift")
    if not isinstance(entry, Mapping) or remap.get("source") != "lv_mhp_v1" or entry.get("source_label") != source_label or entry.get("action") != "direct" or entry.get("part") != [canonical_label]:
        raise LvMhpDirectControlCandidateError("direct source remap drift")
    bundle, source_doc, identity_doc, dedup_doc = _read(qualification_evidence_path), _read(source_hash_manifest_path), _read(identity_evidence_path), _read(split_dedup_path)
    qualified = verify_external_qualification_evidence(provenance, inventory, source="lv_mhp_v1", evidence_bundle=bundle, project_root=Path(project_root).resolve(strict=True))
    if not qualified.admitted:
        raise LvMhpDirectControlCandidateError("external qualification not admitted:" + ",".join(qualified.unmet_gates or qualified.evidence_tokens))
    manifest, identities, dedup = _manifest(source_doc), _identity(identity_doc), _dedup(dedup_doc, content)
    pools: dict[str, list[dict[str, Any]]] = {part: [] for part in PARTITIONS.values()}
    for image_id, identity in identities.items():
        image_rel, lineage = f"images/{image_id}.jpg", dedup.get(f"images/{image_id}.jpg")
        if lineage is None or lineage["cross_split"]:
            continue
        for instance in identity["instance_ids"]:
            annotation_rel = identity["annotation_paths"][instance - 1]
            if image_rel not in manifest or annotation_rel not in manifest or manifest[image_rel] != lineage["source_sha256"]:
                raise LvMhpDirectControlCandidateError(f"hash/split drift:{image_id}")
            with Image.open(_inside(content, image_rel)) as opened:
                dimensions = list(opened.size)
            with Image.open(_inside(content, annotation_rel)) as opened:
                indexed = np.asarray(opened.convert("L"), dtype=np.uint8)
            values, mask = sorted(int(item) for item in np.unique(indexed)), indexed == source_value
            if dimensions != [int(indexed.shape[1]), int(indexed.shape[0])] or not set(values).issubset(set(range(19))):
                raise LvMhpDirectControlCandidateError(f"encoding drift:{image_id}:{instance}")
            if not int(np.count_nonzero(mask)):
                continue
            pools[PARTITIONS[lineage["split"]]].append({"sample_id": f"lv_mhp_v1_{image_id}_p{instance:02d}_{canonical_label}", "source_image_id": f"lv_mhp_v1_{image_id}", "source_instance_id": instance, "declared_person_count": identity["person_count"], "canonical_label": canonical_label, "raw_label_values": [source_value], "raw_label_names": [source_label], "assigned_partition": PARTITIONS[lineage["split"]], "upstream_split": lineage["split"], "split_group_id": lineage["split_group_id"], "source_relative_path": image_rel, "source_sha256": manifest[image_rel], "source_dimensions": dimensions, "instance_annotation_relative_path": annotation_rel, "instance_annotation_sha256": manifest[annotation_rel], "instance_annotation_dimensions": dimensions, "indexed_label_values": values, "mask_pixel_count": int(np.count_nonzero(mask)), "instance_identity_verified": True, "external_reference_qualification_complete": True, "visual_alignment_reviewed": False, "critic_control_eligible": False, "gold_or_production_authority": False})
    selected: list[dict[str, Any]] = []
    groups: set[str] = set()
    for partition in PARTITIONS.values():
        chosen = []
        for row in sorted(pools[partition], key=lambda item: canonical_sha256({"image": item["source_relative_path"], "source": item["source_sha256"], "annotation": item["instance_annotation_sha256"]})):
            if row["split_group_id"] not in groups:
                chosen.append(row); groups.add(row["split_group_id"])
            if len(chosen) == per_partition:
                break
        if len(chosen) != per_partition:
            raise LvMhpDirectControlCandidateError(f"insufficient split-disjoint direct candidates:{canonical_label}:{partition}")
        selected.extend(chosen)
    selected.sort(key=lambda row: (row["assigned_partition"], row["sample_id"]))
    for row in selected:
        if sha256_file(_inside(content, row["source_relative_path"])) != row["source_sha256"] or sha256_file(_inside(content, row["instance_annotation_relative_path"])) != row["instance_annotation_sha256"]:
            raise LvMhpDirectControlCandidateError(f"selected byte drift:{row['sample_id']}")
    counts = Counter(row["assigned_partition"] for row in selected)
    result: dict[str, Any] = {"schema_version": SCHEMA, "artifact_type": "lv_mhp_v1_exact_direct_control_candidates", "input_bindings": {"provenance_sha256": sha256_file(provenance_path), "inventory_sha256": sha256_file(inventory_path), "remap_sha256": sha256_file(remap_path), "qualification_evidence_sha256": sha256_file(qualification_evidence_path), "qualification_evidence_bundle_sha256": qualified.evidence_bundle_sha256, "source_hash_manifest_sha256": sha256_file(source_hash_manifest_path), "source_hash_manifest_seal_sha256": source_doc["seal_sha256"], "identity_evidence_sha256": sha256_file(identity_evidence_path), "split_dedup_sha256": sha256_file(split_dedup_path)}, "selection_policy": {"canonical_label": canonical_label, "source_label": source_label, "exact_source_values": [source_value], "partitions": list(PARTITIONS.values()), "per_partition": per_partition, "selection_order": "sha256(image,source,annotation)", "split_group_disjoint": True}, "selected_count": len(selected), "selected_by_label": {canonical_label: len(selected)}, "selected_by_partition": dict(sorted(counts.items())), "selected": selected, "authority_claimed": False, "critic_control_authority_granted": False, "gold_or_production_authority_granted": False, "claim_limits": ["LV-MHP is external weighted pseudo-label supervision, never gold or holdout truth.", "Candidates are calibration-only and require individual Amendment-2 panel screening.", "Only this exact direct remap is eligible; split-required labels are rejected.", "No critic role, certificate, package, production, or training-truth authority is granted."], "next_required_stage": "render_exact_panels_then_per_record_control_admission"}
    result["self_sha256"] = canonical_sha256(result)
    verify_lv_mhp_direct_control_candidates(result)
    return result

def verify_lv_mhp_direct_control_candidates(document: Mapping[str, Any]) -> None:
    """Verify self-binding, direct semantics, split isolation, and authority ceilings."""
    sealed = {key: value for key, value in document.items() if key != "self_sha256"}
    if document.get("self_sha256") != canonical_sha256(sealed):
        raise LvMhpDirectControlCandidateError("candidate hash drift")
    policy, rows = document.get("selection_policy"), document.get("selected")
    if document.get("schema_version") != SCHEMA or document.get("artifact_type") != "lv_mhp_v1_exact_direct_control_candidates" or document.get("authority_claimed") is not False or document.get("critic_control_authority_granted") is not False or document.get("gold_or_production_authority_granted") is not False or not isinstance(policy, Mapping) or not isinstance(rows, list) or document.get("selected_count") != len(rows):
        raise LvMhpDirectControlCandidateError("candidate contract drift")
    values = policy.get("exact_source_values")
    if not isinstance(values, list) or len(values) != 1:
        raise LvMhpDirectControlCandidateError("direct policy values drift")
    source_value, source_label, canonical_label = _value(values[0]), _label(policy.get("source_label"), "policy source"), _label(policy.get("canonical_label"), "policy canonical")
    if policy.get("partitions") != list(PARTITIONS.values()):
        raise LvMhpDirectControlCandidateError("partition policy drift")
    ids: set[str] = set(); groups: set[str] = set(); counts: Counter[str] = Counter()
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("sample_id"), str) or row["sample_id"] in ids or not isinstance(row.get("split_group_id"), str) or row["split_group_id"] in groups or row.get("canonical_label") != canonical_label or row.get("raw_label_values") != [source_value] or row.get("raw_label_names") != [source_label] or row.get("assigned_partition") != PARTITIONS.get(row.get("upstream_split")) or row.get("instance_identity_verified") is not True or row.get("external_reference_qualification_complete") is not True or row.get("visual_alignment_reviewed") is not False or row.get("critic_control_eligible") is not False or row.get("gold_or_production_authority") is not False or not isinstance(row.get("mask_pixel_count"), int) or row["mask_pixel_count"] <= 0 or row.get("source_dimensions") != row.get("instance_annotation_dimensions"):
            raise LvMhpDirectControlCandidateError("candidate identity/authority/geometry drift")
        _sha(row.get("source_sha256"), "source"); _sha(row.get("instance_annotation_sha256"), "annotation")
        ids.add(row["sample_id"]); groups.add(row["split_group_id"]); counts[row["assigned_partition"]] += 1
    if document.get("selected_by_label") != {canonical_label: len(rows)} or document.get("selected_by_partition") != dict(sorted(counts.items())):
        raise LvMhpDirectControlCandidateError("candidate summary drift")
