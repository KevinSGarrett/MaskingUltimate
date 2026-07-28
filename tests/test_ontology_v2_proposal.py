from pathlib import Path

import yaml

from maskfactory.ontology_source import PART_LABELS

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = ROOT / "Plan" / "OntologyV2" / "ontology_v2_additions.yaml"
SPEC = ROOT / "Plan" / "18_ADULT_ANATOMY_ONTOLOGY_V2_SPEC.md"


def test_adult_anatomy_v2_proposal_is_append_only_complete_and_not_active() -> None:
    document = yaml.safe_load(PROPOSAL.read_text(encoding="utf-8"))
    assert document["status"] == "approved_design_not_active"
    assert document["base_ontology"] == "body_parts_v1"
    assert document["target_ontology"] == "body_parts_v2"
    assert document["part_id_range"] == [0, 65]
    assert document["num_part_classes_including_background"] == 66
    assert [label.id for label in PART_LABELS] == list(range(56))

    additions = document["labels"]
    assert [label["id"] for label in additions] == list(range(56, 66))
    names = {label["name"] for label in additions}
    assert names == {
        "left_areola",
        "right_areola",
        "left_nipple",
        "right_nipple",
        "vulva",
        "penis_shaft",
        "glans_penis",
        "left_scrotal_region",
        "right_scrotal_region",
        "anus",
    }
    assert names.isdisjoint({label.name for label in PART_LABELS})
    by_name = {label["name"]: label for label in additions}
    for name, label in by_name.items():
        partner = label["swap_partner"]
        if partner is not None:
            assert partner in by_name
            assert by_name[partner]["swap_partner"] == name

    formulas = document["derived_formulas"]
    aliases = document["aliases"]
    canonical = names | set(formulas) | {label.name for label in PART_LABELS} | {"both_glutes"}
    assert {entry["canonical"] for entry in aliases.values()} <= canonical
    assert document["visibility_states_added"] == [
        "occluded_by_clothing",
        "not_applicable",
        "unreviewed_for_v2",
    ]
    assert document["governance"] == {
        "permitted_origins": ["generated", "owned_photo", "licensed", "consented_subject"],
        "hidden_anatomy_may_be_visible_gold": False,
        "clothing_contour_is_anatomy_evidence": False,
        "projected_amodal_is_training_or_gold_authority": False,
        "unreviewed_is_negative": False,
    }


def test_adult_anatomy_v2_spec_covers_annotation_migration_and_system_consumers() -> None:
    text = SPEC.read_text(encoding="utf-8")
    for required in (
        "unreviewed_for_v2",
        "occluded_by_clothing",
        "ambiguous_do_not_use",
        "num_classes: 66",
        "`anus`",
        "`left butt cheek`",
        "CVAT annotation SOP",
        "QC-V2-012",
        "Migration from v1",
        "ComfyUI",
        "false-positive rate on clothed images",
    ):
        assert required in text
