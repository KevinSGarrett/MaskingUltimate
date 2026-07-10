"""Build the tracked MaskFactory classification view of the local Civitai manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Plan" / "Civitai" / "civitai_bootstrap_manifest.json"
OUTPUT = ROOT / "configs" / "civitai_classifications.json"

CATEGORIES = {
    "provider_inference",
    "comfyui_graph_reference",
    "annotation_aid",
    "qa_visualization",
    "reject",
}

# Workflow records default to graph references. These records have a more specific
# primary use, or are outside the v1 masking scope.
WORKFLOW_OVERRIDES = {
    "yoloDatasetAuto_v20.zip": "annotation_aid",
    "yoloDatasetAuto_v10.zip": "annotation_aid",
    "SegmentMaskMaskAddRemove_v10.zip": "annotation_aid",
    "inpaintingWithFluxControlnet_v10.zip": "annotation_aid",
    "automaticHandFixerAutoMasking_v10.zip": "annotation_aid",
    "AnimaHandFootDetailFixer_animaRetouchFaces.zip": "annotation_aid",
    "rotomakerWith_v3.zip": "reject",
    "breastExpansion_v10.zip": "reject",
    "maskAdetailerFaceDetailer_v1V8Seg.zip": "provider_inference",
}

RATIONALE = {
    "provider_inference": (
        "Candidate detector, parser, ControlNet, or segmentation vote; output must be "
        "preserved raw and fused with MaskFactory providers, never promoted directly to gold."
    ),
    "comfyui_graph_reference": (
        "Reference wiring for a controlled ComfyUI adapter or debug graph; it is not a "
        "MaskFactory stage or mask authority as supplied."
    ),
    "annotation_aid": (
        "May accelerate candidate-label creation or human mask correction; every result "
        "still requires ontology remap, QA, and human review."
    ),
    "qa_visualization": (
        "Pose, depth, contact, occlusion, or perspective stress fixture for QA panels; "
        "not training data or gold truth without separate provenance approval."
    ),
    "reject": (
        "Rejected from MaskFactory v1 intake because its primary purpose is out-of-scope "
        "generative editing rather than controlled mask production or QA."
    ),
}


def _classification(record: dict[str, Any]) -> str:
    file_name = record.get("file_name") or record.get("manual_file_name")
    if file_name in WORKFLOW_OVERRIDES:
        return WORKFLOW_OVERRIDES[file_name]
    record_type = record.get("type")
    if record_type in {"Detection", "Controlnet"}:
        return "provider_inference"
    if record_type == "Pose/Control Fixtures":
        return "qa_visualization"
    if record_type == "Workflows":
        return "comfyui_graph_reference"
    raise ValueError(f"Unclassified Civitai record type: {record_type!r} ({file_name})")


def build() -> dict[str, Any]:
    source_bytes = SOURCE.read_bytes()
    manifest = json.loads(source_bytes)
    records = manifest["records"]
    downloaded_by_id: dict[int, list[str]] = {}
    for record in records:
        if record.get("downloaded"):
            downloaded_by_id.setdefault(record["id"], []).append(record["file_name"])

    classified = []
    seen: set[tuple[int, str]] = set()
    for record in records:
        key = (record["id"], record["file_name"])
        if key in seen:
            raise ValueError(f"Duplicate manifest identity: {key}")
        seen.add(key)

        category = _classification(record)
        if category not in CATEGORIES:
            raise ValueError(f"Invalid classification {category!r} for {key}")

        downloaded = bool(record.get("downloaded"))
        newer_files = [
            name for name in downloaded_by_id.get(record["id"], []) if name != record["file_name"]
        ]
        if downloaded:
            disposition = "available"
            download_action = "none"
            superseded_by = None
        elif newer_files:
            disposition = "superseded_by_downloaded_variant"
            download_action = "unnecessary"
            superseded_by = sorted(newer_files)
        else:
            disposition = "manual_browser_required"
            download_action = "manual_browser_download_needed"
            superseded_by = None

        classified.append(
            {
                "id": record["id"],
                "name": record["name"],
                "type": record["type"],
                "version": record.get("version"),
                "file_name": record["file_name"],
                "classification": category,
                "rationale": RATIONALE[category],
                "authority": "proposal_or_reference_only",
                "downloaded": downloaded,
                "download_status": (
                    "manual_registered"
                    if record.get("status") == "ManualRegistered"
                    else "downloaded" if downloaded else "metadata_only"
                ),
                "metadata_only_disposition": disposition,
                "download_action": download_action,
                "superseded_by": superseded_by,
                "source_url": record.get("model_url"),
                "sha256": record.get("sha256"),
            }
        )

    return {
        "schema_version": "1.0.0",
        "source_manifest": str(SOURCE),
        "source_manifest_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_updated_at": manifest.get("updated_at"),
        "policy": {
            "allowed_classifications": sorted(CATEGORIES),
            "mask_authority": "none",
            "training_or_gold_requires_separate_license_provenance_consent_review": True,
        },
        "record_count": len(classified),
        "records": classified,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail if the tracked output is stale")
    args = parser.parse_args()
    rendered = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"stale classification output: run {Path(__file__).name}")
        print(f"PASS: {OUTPUT} is current")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT} ({len(build()['records'])} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
