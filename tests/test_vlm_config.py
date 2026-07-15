from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_vlm_config_is_local_private_and_non_authoritative() -> None:
    config = yaml.safe_load((ROOT / "configs" / "vlm.yaml").read_text(encoding="utf-8"))

    assert config["runtime"]["provider"] == "ollama"
    assert config["runtime"]["base_url"] == "http://127.0.0.1:11434"
    assert config["runtime"]["cloud_enabled"] is True
    assert config["runtime"]["gpu_slot"] == "exclusive"
    assert config["models"]["primary_vlm"] == "qwen2.5vl:7b"
    assert config["models"]["fallback_vlm"] == "llava:13b"
    assert config["models"]["text_llm"] == "qwen2.5:7b-instruct"
    assert config["governance"]["may_author_masks"] is False
    assert config["governance"]["may_approve_gold"] is False
    assert config["governance"]["may_clear_blocks"] is False
    assert config["governance"]["source_images_leave_machine"] == "exact_hash_opt_in_only"
    assert config["workhorse"]["specialist_disagreement_fraction"] == 0.03


def test_p_part_contract_matches_doc10_shape() -> None:
    config = yaml.safe_load((ROOT / "configs" / "vlm.yaml").read_text(encoding="utf-8"))
    p_part = config["prompts"]["p_part"]

    assert p_part["version"] == "p-part-v1-doc10"
    assert p_part["max_image_long_side"] == 1024
    assert p_part["retry_on_invalid_json"] == 1
    assert p_part["allowed_verdicts"] == ["pass", "fail", "uncertain"]
    assert p_part["required_keys"] == [
        "verdict",
        "confidence",
        "problems",
        "evidence",
        "correction_instruction",
    ]
    assert set(p_part["allowed_problems"]) == {
        "wrong_part",
        "wrong_side",
        "boundary_too_loose",
        "boundary_too_tight",
        "includes_clothing_as_skin",
        "includes_background",
        "includes_neighbor_part",
        "missing_visible_area",
        "mask_on_hidden_area",
        "finger_merge",
        "hair_edge_bad",
        "occlusion_error",
        "other",
    }


def test_ollama_smoke_uses_primary_vlm_json_mode_and_synthetic_image() -> None:
    text = (ROOT / "tools" / "smoke_ollama_vlm.py").read_text(encoding="utf-8")

    assert '"format": "json"' in text
    assert 'config["models"]["primary_vlm"]' in text
    assert "Image.new" in text
    assert "base64.b64encode" in text
    assert 'REPORT_PATH = ROOT / "qa" / "reports" / "ollama_vlm_smoke.json"' in text
    assert "may_author_masks" in text


def test_autonomous_complete_map_score_tolerance_is_small_and_bounded() -> None:
    config = yaml.safe_load(
        (ROOT / "configs" / "autonomous_masks.yaml").read_text(encoding="utf-8")
    )
    assert config["repair"]["complete_map_score_tolerance"] == 0.001
    assert config["repair"]["minimum_advisory_pass_confidence"] == 0.80
    assert config["repair"]["minimum_independent_pass_reviewers"] == 3
