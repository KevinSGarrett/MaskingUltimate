from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REMAP_ROOT = ROOT / "configs" / "remap"
PART_LABELS = {
    "background",
    "hair",
    "head_face",
    "neck",
    "chest_upper_torso",
    "left_breast",
    "right_breast",
    "abdomen_stomach",
    "pelvic_region",
    "left_shoulder",
    "right_shoulder",
    "left_upper_arm",
    "right_upper_arm",
    "left_elbow",
    "right_elbow",
    "left_forearm",
    "right_forearm",
    "left_wrist",
    "right_wrist",
    "left_hand_base",
    "right_hand_base",
    "left_thigh",
    "right_thigh",
    "left_knee",
    "right_knee",
    "left_calf",
    "right_calf",
    "left_ankle",
    "right_ankle",
    "left_foot_base",
    "right_foot_base",
    "left_toes",
    "right_toes",
    "accessory_or_prop",
}
MATERIAL_LABELS = {
    "none/background",
    "skin",
    "hair_material",
    "clothing_generic",
    "top_garment",
    "bottom_garment",
    "footwear",
    "accessory",
    "waistband",
}


def _plans() -> dict[str, dict]:
    return {
        path.stem: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in REMAP_ROOT.glob("*.yaml")
    }


def test_all_five_sources_have_non_gold_training_disabled_plans() -> None:
    plans = _plans()
    assert set(plans) == {
        "celebamask_hq",
        "lapa",
        "lv_mhp_v1",
        "swimsuit_preview",
        "body_archive",
    }
    for plan in plans.values():
        assert plan["training_allowed"] is False
        assert (
            plan["source_authority"] == "external_source_maps_never_gold"
            or plan["source_authority"] == "external_source_masks_never_gold"
        )


def test_known_source_label_sets_are_complete() -> None:
    plans = _plans()
    assert set(plans["celebamask_hq"]["mappings"]) == {
        "background",
        "skin",
        "nose",
        "l_eye",
        "r_eye",
        "l_brow",
        "r_brow",
        "mouth",
        "u_lip",
        "l_lip",
        "hair",
        "l_ear",
        "r_ear",
        "neck",
        "eye_g",
        "ear_r",
        "neck_l",
        "hat",
        "cloth",
    }
    assert set(plans["lapa"]["mappings"]) == set(range(11))
    assert set(plans["lv_mhp_v1"]["mappings"]) == set(range(19))


def test_known_mappings_only_reference_doc02_labels() -> None:
    for plan in _plans().values():
        for mapping in plan.get("mappings", {}).values():
            assert set(mapping.get("part", [])) <= PART_LABELS
            assert set(mapping.get("material", [])) <= MATERIAL_LABELS
            if mapping["action"] in {"direct", "merge", "split_required"}:
                assert mapping.get("part") or mapping.get("material")


def test_unknown_color_semantics_cannot_emit_labels() -> None:
    plans = _plans()
    swimsuit = plans["swimsuit_preview"]
    archive = plans["body_archive"]
    assert len(swimsuit["observed_colors"]) == 16
    assert swimsuit["mapping_default"] == {
        "action": "ambiguous_do_not_use",
        "part": [],
        "material": [],
    }
    assert archive["mapping_default"]["action"] == "ambiguous_do_not_use"
    assert archive["normalization"]["action"] == "ambiguous_do_not_use"
