"""Render and verify exact panels for LV-MHP direct-label control candidates."""
from __future__ import annotations
import json
import os
import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any
import numpy as np
from PIL import Image, ImageDraw
from .canonical_polygon_panels import PANEL_NAMES, render_candidate_panels
from .canonical_polygon_source_candidates import sha256_file
from .critic_catalog import canonical_sha256
from .lv_mhp_direct_control_candidates import verify_lv_mhp_direct_control_candidates
from .lv_mhp_hair_control_candidates import _content, _inside
SCHEMA = "maskfactory.lv_mhp_v1_direct_control_panels.v1"

class LvMhpDirectControlPanelError(ValueError):
    """A direct-label panel artifact has drifted or overclaimed authority."""

def materialize_lv_mhp_direct_control_panels(*, source_root: Path, candidate_document: Mapping[str, Any], output_root: Path) -> dict[str, Any]:
    """Render immutable per-record panels for a verified calibration-only candidate set."""
    verify_lv_mhp_direct_control_candidates(candidate_document)
    content, output = _content(source_root), Path(output_root)
    if output.exists():
        raise LvMhpDirectControlPanelError("panel output exists")
    policy = candidate_document["selection_policy"]
    source_value, canonical_label = int(policy["exact_source_values"][0]), str(policy["canonical_label"])
    stage, records = output.with_name(f".{output.name}.tmp-{uuid.uuid4().hex}"), []
    try:
        stage.mkdir(parents=True)
        for row in candidate_document["selected"]:
            image, annotation = _inside(content, row["source_relative_path"]), _inside(content, row["instance_annotation_relative_path"])
            if sha256_file(image) != row["source_sha256"] or sha256_file(annotation) != row["instance_annotation_sha256"]:
                raise LvMhpDirectControlPanelError(f"source byte drift:{row['sample_id']}")
            with Image.open(image) as opened:
                source = np.asarray(opened.convert("RGB"), dtype=np.uint8)
            with Image.open(annotation) as opened:
                indexed = np.asarray(opened.convert("L"), dtype=np.uint8)
            mask = indexed == source_value
            if list(source.shape[1::-1]) != row["source_dimensions"] or list(indexed.shape[1::-1]) != row["instance_annotation_dimensions"] or source.shape[:2] != indexed.shape or sorted(int(value) for value in np.unique(indexed)) != row["indexed_label_values"] or int(np.count_nonzero(mask)) != row["mask_pixel_count"]:
                raise LvMhpDirectControlPanelError(f"geometry drift:{row['sample_id']}")
            panels = render_candidate_panels(source, mask, stage / row["sample_id"])
            records.append({**row, "source_path_runpod": image.as_posix(), "instance_annotation_path_runpod": annotation.as_posix(), "source_encoded_sha256_verified": True, "instance_annotation_sha256_verified": True, "direct_remap_pixels_verified": True, **panels, "visual_alignment_reviewed": False, "critic_control_eligible": False, "gold_or_production_authority": False})
        width, height, columns = 720, 260, 4
        contact = Image.new("RGB", (width * columns, height * ((len(records) + columns - 1) // columns)), color=(18, 18, 18))
        draw = ImageDraw.Draw(contact)
        for index, row in enumerate(records):
            with Image.open(stage / row["sample_id"] / row["panel_files"]["target_zoom"]) as opened:
                tile = opened.convert("RGB"); tile.thumbnail((width, height - 24), Image.Resampling.LANCZOS); tile = tile.copy()
            x, y = (index % columns) * width, (index // columns) * height
            contact.paste(tile, (x, y + 24)); draw.text((x + 4, y + 4), f"{index + 1:02d} {row['sample_id']}", fill=(255, 255, 255))
        contact_path = stage / "contact_sheet.png"
        contact.save(contact_path, format="PNG", optimize=False, compress_level=9)
        report: dict[str, Any] = {"schema_version": SCHEMA, "artifact_type": "lv_mhp_v1_exact_direct_visual_evidence", "authority_claimed": False, "visual_alignment_qualification_complete": False, "critic_control_authority_granted": False, "candidate_set_sha256": candidate_document["self_sha256"], "canonical_label": canonical_label, "record_count": len(records), "panel_count": len(records) * len(PANEL_NAMES), "panels_per_record": list(PANEL_NAMES), "contact_sheet": {"path": "contact_sheet.png", "sha256": sha256_file(contact_path), "scheduling_and_navigation_aid_only": True, "per_record_evidence_required": True}, "records": records, "next_required_stage": "per_record_visual_alignment_and_control_admission_screening", "claim_limits": ["Exact rendering does not complete control admission.", "Contact sheets are scheduling/navigation aids only.", "No critic-control, gold, certificate, package, or production authority is granted."]}
        report["self_sha256"] = canonical_sha256(report)
        (stage / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(stage, output)
        return report
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

def verify_lv_mhp_direct_control_panel_report(document: Mapping[str, Any], root: Path) -> None:
    """Verify all panel bytes, report binding, and the calibration-only ceiling."""
    sealed = {key: value for key, value in document.items() if key != "self_sha256"}
    if document.get("self_sha256") != canonical_sha256(sealed) or document.get("schema_version") != SCHEMA or document.get("artifact_type") != "lv_mhp_v1_exact_direct_visual_evidence" or document.get("authority_claimed") is not False or document.get("visual_alignment_qualification_complete") is not False or document.get("critic_control_authority_granted") is not False:
        raise LvMhpDirectControlPanelError("panel report contract drift")
    output, rows = Path(root).resolve(strict=True), document.get("records")
    if not isinstance(rows, list) or document.get("record_count") != len(rows) or document.get("panel_count") != len(rows) * len(PANEL_NAMES):
        raise LvMhpDirectControlPanelError("panel report count drift")
    for row in rows:
        if row.get("visual_alignment_reviewed") is not False or row.get("critic_control_eligible") is not False or row.get("gold_or_production_authority") is not False or row.get("direct_remap_pixels_verified") is not True:
            raise LvMhpDirectControlPanelError("panel authority drift")
        for name in PANEL_NAMES:
            path = (output / row["sample_id"] / row["panel_files"][name]).resolve(strict=True)
            try: path.relative_to(output)
            except ValueError as exc: raise LvMhpDirectControlPanelError("panel path escape") from exc
            if sha256_file(path) != row["panel_sha256s"][name]:
                raise LvMhpDirectControlPanelError(f"panel hash drift:{row['sample_id']}:{name}")
    contact = document.get("contact_sheet", {})
    path = (output / str(contact.get("path"))).resolve(strict=True)
    if contact.get("scheduling_and_navigation_aid_only") is not True or contact.get("per_record_evidence_required") is not True or sha256_file(path) != contact.get("sha256"):
        raise LvMhpDirectControlPanelError("contact-sheet drift")
