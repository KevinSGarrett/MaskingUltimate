from __future__ import annotations
import copy
import pytest
from maskfactory.vlm.critic_catalog import canonical_sha256
from maskfactory.vlm.lv_mhp_direct_control_candidates import LvMhpDirectControlCandidateError, verify_lv_mhp_direct_control_candidates

def _document() -> dict[str, object]:
    row = {"sample_id": "lv_mhp_v1_0001_p01_accessory_or_prop", "split_group_id": "g1", "canonical_label": "accessory_or_prop", "raw_label_values": [1], "raw_label_names": ["hat"], "assigned_partition": "qualification_train", "upstream_split": "train", "instance_identity_verified": True, "external_reference_qualification_complete": True, "visual_alignment_reviewed": False, "critic_control_eligible": False, "gold_or_production_authority": False, "mask_pixel_count": 4, "source_dimensions": [8, 8], "instance_annotation_dimensions": [8, 8], "source_sha256": "a" * 64, "instance_annotation_sha256": "b" * 64}
    document: dict[str, object] = {"schema_version": "maskfactory.lv_mhp_v1_direct_control_candidates.v1", "artifact_type": "lv_mhp_v1_exact_direct_control_candidates", "input_bindings": {}, "selection_policy": {"canonical_label": "accessory_or_prop", "source_label": "hat", "exact_source_values": [1], "partitions": ["qualification_train", "qualification_test"]}, "selected_count": 1, "selected_by_label": {"accessory_or_prop": 1}, "selected_by_partition": {"qualification_train": 1}, "selected": [row], "authority_claimed": False, "critic_control_authority_granted": False, "gold_or_production_authority_granted": False}
    document["self_sha256"] = canonical_sha256(document)
    return document

def test_verify_exact_direct_candidate() -> None:
    verify_lv_mhp_direct_control_candidates(_document())

def test_reject_direct_label_drift() -> None:
    document = copy.deepcopy(_document())
    document["selected"][0]["raw_label_values"] = [2]
    document["self_sha256"] = canonical_sha256({key: value for key, value in document.items() if key != "self_sha256"})
    with pytest.raises(LvMhpDirectControlCandidateError, match="identity/authority/geometry"):
        verify_lv_mhp_direct_control_candidates(document)
