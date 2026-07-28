from __future__ import annotations

import json
from pathlib import Path

import pytest

from maskfactory.nude_provider_canary import (
    NudeProviderCanaryError,
    _reference_context,
    _runtime_bindings,
    _validated_box,
)


def test_bbox_validation_preserves_prompt_geometry_not_pixels() -> None:
    assert _validated_box({"bbox": [2, 3, 10, 12]}, width=32, height=24) == [2, 3, 12, 15]
    with pytest.raises(NudeProviderCanaryError, match="out_of_bounds"):
        _validated_box({"bbox": [30, 3, 10, 12]}, width=32, height=24)


def test_runtime_bindings_require_installed_no_gold_providers(tmp_path: Path) -> None:
    providers = [
        "sam3_1",
        "maskfactory_core",
        "sam2matting_base_plus",
        "sam3_litetext_s0",
    ]
    path = tmp_path / "matrix.json"
    path.write_text(
        json.dumps(
            {
                "runtimes": [
                    {
                        "provider": provider,
                        "status": "live_smoke_passed",
                        "isolation_boundary": provider + "_env",
                        "checkpoint_status": "installed",
                        "may_author_gold": False,
                        "artifacts": [],
                    }
                    for provider in providers
                ]
            }
        ),
        encoding="utf-8",
    )
    assert set(_runtime_bindings(path)) == set(providers)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["runtimes"][0]["may_author_gold"] = True
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(NudeProviderCanaryError, match="authority_invalid"):
        _runtime_bindings(path)


def _reference_record() -> dict[str, object]:
    return {
        "dataset_id": "civitai_top_nsfw_images_2025",
        "source_role": "reference_and_tournament_input",
        "authority": "reference_only_no_mask_truth",
        "media_domain": "synthetic_or_generated",
        "annotation_count": 0,
        "has_bbox": False,
        "has_polygon_segmentation": False,
        "source_labels": [],
        "metadata_ref": "CivitAI_Top_NSFW_Images/prompts.json",
        "metadata_nsfw_level": "X",
        "source_split": "unsplit_reference",
        "source_relative_path": "CivitAI_Top_NSFW_Images/images/1.jpeg",
        "source_sha256": "a" * 64,
    }


def test_reference_prompt_join_is_weak_context_not_pixel_truth(tmp_path: Path) -> None:
    metadata = tmp_path / "CivitAI_Top_NSFW_Images" / "prompts.json"
    metadata.parent.mkdir()
    metadata.write_text(
        json.dumps({"1.jpeg": {"prompt": "two people, standing", "nsfwLevel": "X"}}),
        encoding="utf-8",
    )
    context = _reference_context(tmp_path, _reference_record(), {})
    assert context["image_filename"] == "1.jpeg"
    assert context["prompt"] == "two people, standing"
    assert context["authority"] == "weak_scene_action_retrieval_context_only"
    assert context["may_supply_pixel_truth"] is False
    assert context["may_infer_anatomy_labels"] is False
    assert context["may_infer_fine_masks"] is False


def test_reference_prompt_join_rejects_metadata_drift(tmp_path: Path) -> None:
    metadata = tmp_path / "CivitAI_Top_NSFW_Images" / "prompts.json"
    metadata.parent.mkdir()
    metadata.write_text(
        json.dumps({"1.jpeg": {"prompt": "person", "nsfwLevel": "Mature"}}),
        encoding="utf-8",
    )
    with pytest.raises(NudeProviderCanaryError, match="nsfw_level_drift"):
        _reference_context(tmp_path, _reference_record(), {})
