import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "src" / "maskfactory" / "schemas" / "manifest.schema.json"
SHA = "a" * 64


def valid_manifest() -> dict:
    return {
        "schema_version": "1.0.0",
        "image_id": "img_a3f9c2e17b04",
        "mask_ontology_version": "body_parts_v1",
        "left_right_convention": "character_perspective",
        "workflow_status": "approved_gold",
        "workflow_updated_at": "2026-07-09T15:03:22Z",
        "source": {
            "source_file": "source.png",
            "source_sha256": SHA,
            "parent_source_sha256": SHA,
            "source_width": 1664,
            "source_height": 2432,
            "source_origin": "generated",
            "origin_note": "fixture",
            "ingested_at": "2026-07-09T14:03:22Z",
            "exif_stripped": True,
        },
        "person": {
            "primary_person_bbox": [10, 20, 1000, 2200],
            "person_count": 2,
            "view": "front",
            "pose_tags": ["arms_down", "standing"],
            "estimated_person_height_px": 2210,
        },
        "interperson": [
            {
                "other_instance_id": "img_a3f9c2e17b04_p1",
                "relationship": "contact",
                "contact_band_file": "masks_regions/interperson_contact_boundary.png",
            }
        ],
        "parts": {
            "left_forearm": {
                "mask_type": "atomic_exclusive",
                "visibility": "visible",
                "mask_file": "masks/left_forearm.png",
                "mask_sha256": SHA,
                "mask_area_px": 48211,
                "mask_bbox": [100, 200, 150, 400],
                "components": 1,
                "status": "human_corrected",
                "annotated_on": "full",
                "occlusion": {
                    "occluded_by": ["right_hand_base"],
                    "occludes": [],
                    "layer": "back_layer",
                },
                "provenance": {
                    "draft_source": "fusion_v1",
                    "sam2_prompt_id": "p_0142",
                    "human_edit": True,
                },
                "notes": "",
            },
            "left_breast_projected_region": {
                "mask_type": "projected_amodal",
                "visibility": "n/a",
                "basis": "torso_landmarks+clothing_surface",
                "mask_file": "projected/left_breast_projected_region.png",
                "mask_sha256": SHA,
                "status": "human_approved_gold",
            },
            "left_toes": {
                "mask_type": "atomic_exclusive",
                "visibility": "cropped_out",
                "mask_file": None,
                "status": "n/a",
            },
        },
        "inpaint_derivatives": [
            {
                "label": "left_hand",
                "file": "inpaint/inpaint_left_hand_d8f4.png",
                "dilate_px": 8,
                "feather_px": 4,
                "ref_scale": 1024,
                "source_gold_sha256": SHA,
            }
        ],
        "tooling": {
            "annotation_tool": "cvat",
            "annotation_tool_version": "2.24.0",
            "pipeline_version": "maskfactory 0.4.1+g8f21ac",
            "model_versions_used": {"sam2": "2.1"},
            "config_hashes": {"ontology.yaml": SHA, "pipeline.yaml": SHA},
        },
        "review": {
            "reviewer": "kevin",
            "approved_at": "2026-07-11T02:11:09Z",
            "second_review": {
                "required": True,
                "reviewer": "kevin_day2",
                "result": "pass",
                "at": "2026-07-12T02:11:09Z",
            },
            "review_time_sec": 940,
        },
        "qa": {"qa_report_file": "qa_report.json", "qa_overall": "pass", "qa_score": 0.96},
        "files": {"source.png": SHA, "masks/left_forearm.png": SHA},
    }


def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_manifest_schema_accepts_full_single_instance_contract_and_doc17_amendment() -> None:
    assert list(validator().iter_errors(valid_manifest())) == []


def test_manifest_schema_requires_every_authoritative_top_level_block() -> None:
    manifest = copy.deepcopy(valid_manifest())
    del manifest["files"]
    errors = list(validator().iter_errors(manifest))
    assert len(errors) == 1
    assert errors[0].validator == "required"


def test_manifest_schema_rejects_unsafe_paths_and_unverified_hashes() -> None:
    manifest = copy.deepcopy(valid_manifest())
    manifest["source"]["source_file"] = "../outside.png"
    manifest["source"]["source_sha256"] = "not-a-hash"
    errors = list(validator().iter_errors(manifest))
    assert {tuple(error.absolute_path) for error in errors} == {
        ("source", "source_file"),
        ("source", "source_sha256"),
    }
