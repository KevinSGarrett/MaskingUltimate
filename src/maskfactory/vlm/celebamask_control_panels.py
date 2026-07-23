"""Materialize exact CelebAMask-HQ direct-label critic-control evidence."""

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
from .celebamask_control_candidates import verify_celebamask_control_candidates
from .critic_catalog import canonical_sha256

SCHEMA_VERSION = "maskfactory.celebamask_control_panels.v1"


class CelebAMaskControlPanelError(ValueError):
    """CelebAMask evidence cannot be rendered or verified exactly."""


def materialize_celebamask_control_panels(
    *,
    source_root: Path,
    candidate_document: Mapping[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    """Render complete per-record evidence from exact source/component bytes."""

    verify_celebamask_control_candidates(candidate_document)
    source_root = Path(source_root).resolve(strict=True)
    output_root = Path(output_root)
    if output_root.exists():
        raise CelebAMaskControlPanelError("panel output already exists")
    stage = output_root.with_name(f".{output_root.name}.tmp-{uuid.uuid4().hex}")
    rows: list[dict[str, Any]] = []
    try:
        stage.mkdir(parents=True)
        for candidate in candidate_document["selected"]:
            sample_id = candidate["sample_id"]
            source_path = (source_root / candidate["source_relative_path"]).resolve(strict=True)
            mask_path = (source_root / candidate["mask_relative_path"]).resolve(strict=True)
            for path in (source_path, mask_path):
                try:
                    path.relative_to(source_root)
                except ValueError as exc:
                    raise CelebAMaskControlPanelError(
                        f"source path escapes root:{sample_id}"
                    ) from exc
            if (
                sha256_file(source_path) != candidate["source_sha256"]
                or sha256_file(mask_path) != candidate["mask_sha256"]
            ):
                raise CelebAMaskControlPanelError(f"source or mask hash drift:{sample_id}")
            with Image.open(mask_path) as opened:
                mask = np.asarray(opened.convert("L")) == 255
            with Image.open(source_path) as opened:
                source = np.asarray(
                    opened.convert("RGB").resize(
                        (mask.shape[1], mask.shape[0]), Image.Resampling.BILINEAR
                    ),
                    dtype=np.uint8,
                )
            panels = render_candidate_panels(source, mask, stage / sample_id)
            rows.append(
                {
                    **candidate,
                    "source_path_runpod": source_path.as_posix(),
                    "mask_path_runpod": mask_path.as_posix(),
                    "source_encoded_sha256_verified": True,
                    "component_mask_sha256_verified": True,
                    **panels,
                    "visual_alignment_reviewed": False,
                    "critic_control_eligible": False,
                    "gold_or_production_authority": False,
                }
            )
        tile_width, tile_height, columns = 720, 260, 4
        contact = Image.new(
            "RGB",
            (tile_width * columns, tile_height * ((len(rows) + columns - 1) // columns)),
            color=(18, 18, 18),
        )
        draw = ImageDraw.Draw(contact)
        for index, row in enumerate(rows):
            path = stage / row["sample_id"] / row["panel_files"]["target_zoom"]
            with Image.open(path) as opened:
                tile = opened.convert("RGB")
                tile.thumbnail((tile_width, tile_height - 24), Image.Resampling.LANCZOS)
                tile = tile.copy()
            x = (index % columns) * tile_width
            y = (index // columns) * tile_height
            contact.paste(tile, (x, y + 24))
            draw.text(
                (x + 4, y + 4),
                f"{index + 1:02d} {row['sample_id']}",
                fill=(255, 255, 255),
            )
        contact_path = stage / "contact_sheet.png"
        contact.save(contact_path, format="PNG", optimize=False, compress_level=9)
        report: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": "celebamask_exact_direct_label_visual_evidence",
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
            "next_required_stage": (
                "per_record_visual_alignment_and_external_reference_qualification"
            ),
            "claim_limits": [
                "Exact source/component rendering does not qualify semantics.",
                "Contact sheets are scheduling/navigation aids only.",
                "No critic-control, gold, certificate, or production authority.",
            ],
        }
        report["self_sha256"] = canonical_sha256(report)
        (stage / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(stage, output_root)
        return report
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def verify_celebamask_control_panel_report(document: Mapping[str, Any], root: Path) -> None:
    """Verify every exact panel byte and reject authority drift."""

    payload = {key: value for key, value in document.items() if key != "self_sha256"}
    if document.get("self_sha256") != canonical_sha256(payload):
        raise CelebAMaskControlPanelError("panel report self hash mismatch")
    if (
        document.get("schema_version") != SCHEMA_VERSION
        or document.get("authority_claimed") is not False
        or document.get("visual_alignment_qualification_complete") is not False
        or document.get("critic_control_authority_granted") is not False
    ):
        raise CelebAMaskControlPanelError("panel report authority drift")
    records = document.get("records")
    if (
        not isinstance(records, list)
        or document.get("record_count") != len(records)
        or document.get("panel_count") != len(records) * len(PANEL_NAMES)
    ):
        raise CelebAMaskControlPanelError("panel report counts drift")
    root = Path(root).resolve(strict=True)
    for record in records:
        if (
            record.get("visual_alignment_reviewed") is not False
            or record.get("critic_control_eligible") is not False
            or record.get("gold_or_production_authority") is not False
        ):
            raise CelebAMaskControlPanelError("panel record authority drift")
        for panel_name in PANEL_NAMES:
            path = (root / record["sample_id"] / record["panel_files"][panel_name]).resolve(
                strict=True
            )
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise CelebAMaskControlPanelError("panel path escapes root") from exc
            if sha256_file(path) != record["panel_sha256s"][panel_name]:
                raise CelebAMaskControlPanelError(
                    f"panel hash drift:{record['sample_id']}:{panel_name}"
                )
    contact = document.get("contact_sheet", {})
    contact_path = (root / str(contact.get("path"))).resolve(strict=True)
    if (
        contact.get("scheduling_and_navigation_aid_only") is not True
        or contact.get("per_record_evidence_required") is not True
        or sha256_file(contact_path) != contact.get("sha256")
    ):
        raise CelebAMaskControlPanelError("contact sheet binding drift")
