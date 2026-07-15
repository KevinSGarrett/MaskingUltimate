"""Human-auditable generator source for every ontology registry in doc 02."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ONTOLOGY_VERSION = "body_parts_v1"
LEFT_RIGHT_CONVENTION = "character_perspective"
VISIBILITY_STATES = (
    "visible",
    "partially_visible",
    "occluded",
    "cropped_out",
    "not_visible",
    "ambiguous_do_not_use",
)


@dataclass(frozen=True)
class LabelSource:
    id: int | None
    name: str
    mask_type: str
    map: str
    side: str
    parent_union: str | None
    enabled: bool
    expected_area_pct_range: tuple[float, float] | None
    max_components: int | None
    exclusivity_group: str | None
    swap_partner: str | None
    visibility_default: str
    boundary_rule: str


BOUNDARY_RULES: dict[str, dict[str, Any]] = {
    "frame_remainder": {"rule": "all pixels not owned by any foreground PART label"},
    "visible_contour": {"rule": "visible pixel contour; never infer hidden extent"},
    "hair_50pct": {
        "rule": "hair owns occluded face/body pixels; wisps use 50 percent opacity boundary"
    },
    "head_face": {"rule": "face plus ears by default and scalp skin visible through partings"},
    "neck_clavicle": {"rule": "jawline or hair boundary down to clavicle line"},
    "torso_front": {"rule": "front torso anatomical lines and visible fabric-defined contours"},
    "belly_carveout": {"rule": "navel depression carved out of abdomen_stomach"},
    "joint_0_6": {"rule": "perpendicular keypoint band height 0.6 times local limb width"},
    "wrist_0_5": {"rule": "perpendicular wrist band height 0.5 times local limb width"},
    "hand_mcp": {"rule": "hand base begins after wrist; fingers begin at MCP knuckle line"},
    "foot_mtp": {"rule": "foot base excludes toes beginning at metatarsophalangeal line"},
    "glute_back": {"rule": "gluteal fold to iliac crest, split at body midline"},
    "densepose_surface": {"rule": "front/back ownership by DensePose surface majority"},
    "protected_visible": {"rule": "visible protected object/person contour in this instance crop"},
    "script_formula": {"rule": "exact script-generated result of the registered formula"},
    "geometry_projected": {"rule": "geometry estimate kept separate from visible truth"},
}


def _side(name: str) -> str:
    if name.startswith("left_"):
        return "left"
    if name.startswith("right_"):
        return "right"
    return "center" if name not in {"background"} else "na"


def _swap(name: str) -> str | None:
    if name.startswith("left_"):
        return "right_" + name.removeprefix("left_")
    if name.startswith("right_"):
        return "left_" + name.removeprefix("right_")
    return None


def _part(
    id_: int,
    name: str,
    area: tuple[float, float],
    *,
    parent: str | None = None,
    components: int = 1,
    boundary: str = "visible_contour",
    enabled: bool = True,
    mask_type: str = "atomic_exclusive",
) -> LabelSource:
    return LabelSource(
        id=id_,
        name=name,
        mask_type=mask_type,
        map="part",
        side=_side(name),
        parent_union=parent,
        enabled=enabled,
        expected_area_pct_range=area,
        max_components=components,
        exclusivity_group="part_map",
        swap_partner=_swap(name),
        visibility_default="visible" if name != "background" else "n/a",
        boundary_rule=boundary,
    )


PART_LABELS: tuple[LabelSource, ...] = (
    _part(0, "background", (0.0, 100.0), boundary="frame_remainder"),
    _part(1, "hair", (0.1, 35.0), components=4, boundary="hair_50pct"),
    _part(2, "head_face", (1.0, 20.0), components=2, boundary="head_face"),
    _part(3, "neck", (0.2, 8.0), boundary="neck_clavicle"),
    _part(
        4,
        "chest_upper_torso",
        (1.0, 25.0),
        parent="full_torso",
        components=2,
        boundary="torso_front",
    ),
    _part(5, "left_breast", (0.1, 12.0), parent="both_breasts", boundary="torso_front"),
    _part(6, "right_breast", (0.1, 12.0), parent="both_breasts", boundary="torso_front"),
    _part(
        7,
        "abdomen_stomach",
        (1.0, 25.0),
        parent="abdomen_full",
        components=2,
        boundary="torso_front",
    ),
    _part(8, "belly_button", (0.001, 1.0), parent="abdomen_full", boundary="belly_carveout"),
    _part(9, "pelvic_region", (0.5, 15.0), parent="full_torso", boundary="torso_front"),
    _part(10, "left_hip", (0.2, 8.0), parent="full_torso", boundary="torso_front"),
    _part(11, "right_hip", (0.2, 8.0), parent="full_torso", boundary="torso_front"),
    _part(12, "left_shoulder", (0.2, 6.0), parent="both_arms"),
    _part(13, "right_shoulder", (0.2, 6.0), parent="both_arms"),
    _part(14, "left_upper_arm", (0.8, 5.0), parent="both_upper_arms"),
    _part(15, "right_upper_arm", (0.8, 5.0), parent="both_upper_arms"),
    _part(16, "left_elbow", (0.05, 2.0), parent="both_arms", boundary="joint_0_6"),
    _part(17, "right_elbow", (0.05, 2.0), parent="both_arms", boundary="joint_0_6"),
    _part(18, "left_forearm", (0.8, 4.0), parent="both_forearms"),
    _part(19, "right_forearm", (0.8, 4.0), parent="both_forearms"),
    _part(20, "left_wrist", (0.02, 1.0), parent="left_hand", boundary="wrist_0_5"),
    _part(21, "right_wrist", (0.02, 1.0), parent="right_hand", boundary="wrist_0_5"),
    _part(22, "left_hand_base", (0.1, 3.0), parent="left_hand", boundary="hand_mcp"),
    _part(23, "right_hand_base", (0.1, 3.0), parent="right_hand", boundary="hand_mcp"),
    _part(24, "left_thumb", (0.02, 0.5), parent="all_thumbs", boundary="hand_mcp"),
    _part(25, "right_thumb", (0.02, 0.5), parent="all_thumbs", boundary="hand_mcp"),
    _part(26, "left_index_finger", (0.02, 0.5), parent="all_index_fingers", boundary="hand_mcp"),
    _part(27, "right_index_finger", (0.02, 0.5), parent="all_index_fingers", boundary="hand_mcp"),
    _part(28, "left_middle_finger", (0.02, 0.5), parent="all_middle_fingers", boundary="hand_mcp"),
    _part(29, "right_middle_finger", (0.02, 0.5), parent="all_middle_fingers", boundary="hand_mcp"),
    _part(30, "left_ring_finger", (0.02, 0.5), parent="all_ring_fingers", boundary="hand_mcp"),
    _part(31, "right_ring_finger", (0.02, 0.5), parent="all_ring_fingers", boundary="hand_mcp"),
    _part(32, "left_pinky", (0.02, 0.5), parent="all_pinkies", boundary="hand_mcp"),
    _part(33, "right_pinky", (0.02, 0.5), parent="all_pinkies", boundary="hand_mcp"),
    _part(34, "left_glute", (0.5, 10.0), parent="both_glutes", boundary="glute_back"),
    _part(35, "right_glute", (0.5, 10.0), parent="both_glutes", boundary="glute_back"),
    _part(36, "left_thigh", (3.0, 12.0), parent="both_thighs"),
    _part(37, "right_thigh", (3.0, 12.0), parent="both_thighs"),
    _part(38, "left_knee", (0.1, 3.0), parent="both_knees", boundary="joint_0_6"),
    _part(39, "right_knee", (0.1, 3.0), parent="both_knees", boundary="joint_0_6"),
    _part(40, "left_calf", (1.0, 7.0), parent="both_calves"),
    _part(41, "right_calf", (1.0, 7.0), parent="both_calves"),
    _part(42, "left_ankle", (0.03, 1.5), parent="left_foot", boundary="joint_0_6"),
    _part(43, "right_ankle", (0.03, 1.5), parent="right_foot", boundary="joint_0_6"),
    _part(44, "left_foot_base", (0.2, 4.0), parent="left_foot", boundary="foot_mtp"),
    _part(45, "right_foot_base", (0.2, 4.0), parent="right_foot", boundary="foot_mtp"),
    _part(46, "left_toes", (0.05, 1.5), parent="all_toes", boundary="foot_mtp"),
    _part(47, "right_toes", (0.05, 1.5), parent="all_toes", boundary="foot_mtp"),
    _part(
        48,
        "back_upper_torso",
        (1.0, 30.0),
        parent="full_torso",
        components=2,
        boundary="densepose_surface",
    ),
    _part(
        49,
        "back_lower_torso",
        (1.0, 30.0),
        parent="full_torso",
        components=2,
        boundary="densepose_surface",
    ),
    _part(
        50,
        "other_person",
        (0.0, 100.0),
        components=8,
        boundary="protected_visible",
        mask_type="protected_qa",
    ),
    _part(
        51,
        "occluding_object",
        (0.0, 100.0),
        components=8,
        boundary="protected_visible",
        mask_type="protected_qa",
    ),
    _part(
        52,
        "support_surface",
        (0.0, 100.0),
        components=8,
        boundary="protected_visible",
        mask_type="protected_qa",
    ),
    _part(
        53,
        "accessory_or_prop",
        (0.0, 100.0),
        components=8,
        boundary="protected_visible",
        mask_type="protected_qa",
    ),
    _part(54, "left_ear", (0.01, 1.5), boundary="head_face", enabled=False),
    _part(55, "right_ear", (0.01, 1.5), boundary="head_face", enabled=False),
)


MATERIAL_NAMES = (
    "none_background",
    "skin",
    "hair_material",
    "clothing_generic",
    "bra",
    "underwear_bottom",
    "top_garment",
    "bottom_garment",
    "footwear",
    "accessory",
    "strap",
    "waistband",
    "lace_or_sheer",
    "other_person_material",
    "object_material",
    "glove_or_sock",
)
MATERIAL_LABELS: tuple[LabelSource, ...] = tuple(
    LabelSource(
        id=index,
        name=name,
        mask_type="material",
        map="material",
        side="na",
        parent_union=None,
        enabled=True,
        expected_area_pct_range=(0.0, 100.0),
        max_components=16,
        exclusivity_group="material_map",
        swap_partner=None,
        visibility_default="visible" if index else "n/a",
        boundary_rule="visible_contour",
    )
    for index, name in enumerate(MATERIAL_NAMES)
)


REGION_BANDS: tuple[dict[str, Any], ...] = (
    {
        "name": "waist",
        "definition": "lowest-rib to iliac-crest band; height 12% shoulder-to-hip distance",
    },
    {"name": "spine_back_center", "definition": "back spine-line band; width 10% shoulder width"},
    {"name": "left_scapula_back", "definition": "left DensePose back-surface shoulder-blade patch"},
    {
        "name": "right_scapula_back",
        "definition": "right DensePose back-surface shoulder-blade patch",
    },
    {
        "name": "body_contact_region",
        "definition": "body-surface contact boundary; 8 px at 1024 ref",
    },
    {"name": "left_body_contact_region", "definition": "left owning-limb subset of body contact"},
    {"name": "right_body_contact_region", "definition": "right owning-limb subset of body contact"},
    {"name": "overlap_occlusion_boundary", "definition": "atomic occlusion edge; 6 px scaled"},
    {"name": "left_underarm", "definition": "optional left axilla band"},
    {"name": "right_underarm", "definition": "optional right axilla band"},
    {"name": "left_side_torso", "definition": "optional left lateral torso strip"},
    {"name": "right_side_torso", "definition": "optional right lateral torso strip"},
    {"name": "left_inner_thigh", "definition": "optional left inner-thigh detail band"},
    {"name": "right_inner_thigh", "definition": "optional right inner-thigh detail band"},
    {"name": "left_outer_thigh", "definition": "optional left outer-thigh detail band"},
    {"name": "right_outer_thigh", "definition": "optional right outer-thigh detail band"},
    {"name": "left_shin_front", "definition": "optional left anterior-shin detail band"},
    {"name": "right_shin_front", "definition": "optional right anterior-shin detail band"},
    {
        "name": "interperson_contact_boundary",
        "definition": "different promoted instances contact/occlusion; 8 px at 1024 ref",
    },
)


DERIVED_UNIONS = (
    "both_breasts",
    "breast_skin",
    "left_breast_skin",
    "right_breast_skin",
    "left_hand",
    "right_hand",
    "both_hands",
    "all_fingers",
    "all_thumbs",
    "all_index_fingers",
    "all_middle_fingers",
    "all_ring_fingers",
    "all_pinkies",
    "left_foot",
    "right_foot",
    "both_feet",
    "all_toes",
    "both_arms",
    "both_upper_arms",
    "both_forearms",
    "both_glutes",
    "both_thighs",
    "both_knees",
    "both_calves",
    "full_torso",
    "full_arms",
    "full_legs",
    "abdomen_full",
    "full_body_parts_visible",
    "person_full_visible",
    "visible_body_skin",
    "clothing_visible",
    "bra_visible",
    "panty_visible",
    "bra_left_cup",
    "bra_right_cup",
    "bra_straps",
    "clothing_boundary_chest",
    "clothing_skin_boundary",
    "clothing_bodypart_occlusion",
)

DERIVED_FORMULAS: dict[str, str] = {
    "both_breasts": "part:left_breast | part:right_breast",
    "breast_skin": "(part:left_breast | part:right_breast) & material:skin",
    "left_breast_skin": "part:left_breast & material:skin",
    "right_breast_skin": "part:right_breast & material:skin",
    "left_hand": "part:left_hand_base | part:left_thumb | part:left_index_finger | part:left_middle_finger | part:left_ring_finger | part:left_pinky",
    "right_hand": "part:right_hand_base | part:right_thumb | part:right_index_finger | part:right_middle_finger | part:right_ring_finger | part:right_pinky",
    "both_hands": "derived:left_hand | derived:right_hand",
    "all_fingers": "part_ids:24-33",
    "all_thumbs": "part:left_thumb | part:right_thumb",
    "all_index_fingers": "part:left_index_finger | part:right_index_finger",
    "all_middle_fingers": "part:left_middle_finger | part:right_middle_finger",
    "all_ring_fingers": "part:left_ring_finger | part:right_ring_finger",
    "all_pinkies": "part:left_pinky | part:right_pinky",
    "left_foot": "part:left_foot_base | part:left_toes",
    "right_foot": "part:right_foot_base | part:right_toes",
    "both_feet": "derived:left_foot | derived:right_foot",
    "all_toes": "part:left_toes | part:right_toes",
    "both_arms": "part_ids:12-33",
    "both_upper_arms": "part:left_upper_arm | part:right_upper_arm",
    "both_forearms": "part:left_forearm | part:right_forearm",
    "both_glutes": "part:left_glute | part:right_glute",
    "both_thighs": "part:left_thigh | part:right_thigh",
    "both_knees": "part:left_knee | part:right_knee",
    "both_calves": "part:left_calf | part:right_calf",
    "full_torso": "part_ids:4-11 | part_ids:48-49",
    "full_arms": "part_ids:12-33",
    "full_legs": "part_ids:34-47",
    "abdomen_full": "part:abdomen_stomach | part:belly_button",
    "full_body_parts_visible": "part_ids:1-49",
    "person_full_visible": "silhouette:person_full_visible",
    "visible_body_skin": "(part_ids:1-49 & material:skin) - part:hair",
    "clothing_visible": "material_ids:3-8,10-12,15",
    "bra_visible": "material:bra",
    "panty_visible": "material:underwear_bottom",
    "bra_left_cup": "material:bra & part:left_breast",
    "bra_right_cup": "material:bra & part:right_breast",
    "bra_straps": "material:strap & (part:chest_upper_torso | part:left_shoulder | part:right_shoulder)",
    "clothing_boundary_chest": "edge(material_ids:3,4,6 within part_ids:4-6)",
    "clothing_skin_boundary": "edge(material:skin, material_ids:3-8,10-12,15, width=4px@1024)",
    "clothing_bodypart_occlusion": "clothing_visible & projected:amodal_body_estimates",
}


PROJECTED_REGISTRY: tuple[dict[str, Any], ...] = (
    {"name": "left_breast_projected_region", "kind": "projected_amodal"},
    {"name": "right_breast_projected_region", "kind": "projected_amodal"},
    {"name": "left_chest_clothing_over_breast", "kind": "projected_amodal"},
    {"name": "right_chest_clothing_over_breast", "kind": "projected_amodal"},
    {"name": "amodal_<part>", "kind": "template"},
    {"name": "inpaint_<part>_d<k>f<f>", "kind": "template"},
)


PROTECTED_CLASSES = tuple(label.name for label in PART_LABELS if label.mask_type == "protected_qa")
