from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from PIL import Image
from maskfactory.vlm.canonical_polygon_source_candidates import sha256_file
from maskfactory.vlm.critic_catalog import canonical_sha256
from maskfactory.vlm.lv_mhp_direct_control_panels import materialize_lv_mhp_direct_control_panels, verify_lv_mhp_direct_control_panel_report

def test_materializes_hash_bound_direct_panels(tmp_path: Path) -> None:
    content = tmp_path / "source" / "LV-MHP-v1"
    (content / "images").mkdir(parents=True); (content / "annotations").mkdir()
    image = content / "images" / "0001.jpg"; annotation = content / "annotations" / "0001_01_01.png"
    Image.fromarray(np.zeros((16, 16, 3), dtype=np.uint8), mode="RGB").save(image)
    indexed = np.zeros((16, 16), dtype=np.uint8); indexed[2:8, 4:10] = 1; Image.fromarray(indexed, mode="L").save(annotation)
    row = {"sample_id": "lv_mhp_v1_0001_p01_accessory_or_prop", "split_group_id": "g1", "canonical_label": "accessory_or_prop", "raw_label_values": [1], "raw_label_names": ["hat"], "assigned_partition": "qualification_train", "upstream_split": "train", "instance_identity_verified": True, "external_reference_qualification_complete": True, "visual_alignment_reviewed": False, "critic_control_eligible": False, "gold_or_production_authority": False, "mask_pixel_count": 36, "source_relative_path": "images/0001.jpg", "source_sha256": sha256_file(image), "source_dimensions": [16, 16], "instance_annotation_relative_path": "annotations/0001_01_01.png", "instance_annotation_sha256": sha256_file(annotation), "instance_annotation_dimensions": [16, 16], "indexed_label_values": [0, 1]}
    candidate = {"schema_version": "maskfactory.lv_mhp_v1_direct_control_candidates.v1", "artifact_type": "lv_mhp_v1_exact_direct_control_candidates", "input_bindings": {}, "selection_policy": {"canonical_label": "accessory_or_prop", "source_label": "hat", "exact_source_values": [1], "partitions": ["qualification_train", "qualification_test"]}, "selected_count": 1, "selected_by_label": {"accessory_or_prop": 1}, "selected_by_partition": {"qualification_train": 1}, "selected": [row], "authority_claimed": False, "critic_control_authority_granted": False, "gold_or_production_authority_granted": False}
    candidate["self_sha256"] = canonical_sha256(candidate)
    output = tmp_path / "output"
    report = materialize_lv_mhp_direct_control_panels(source_root=content.parent, candidate_document=candidate, output_root=output)
    verify_lv_mhp_direct_control_panel_report(report, output)
    assert json.loads((output / "report.json").read_text())["self_sha256"] == report["self_sha256"]
