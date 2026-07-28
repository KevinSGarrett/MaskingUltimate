from pathlib import Path

import yaml

from maskfactory.ontology import get_ontology


def test_viz_config_covers_every_label_and_exact_evidence_style() -> None:
    document = yaml.safe_load(Path("configs/viz.yaml").read_text(encoding="utf-8"))
    assert document["overlay"] == {
        "fill_rgba": [255, 64, 64, 110],
        "contour_width_px": 1,
        "source_opacity": 1.0,
        "output_format": "png",
    }
    assert document["qa_panel"]["tile_size_px"] == 512
    assert document["qa_panel"]["zoom_bbox_multiplier"] == 2.0
    assert document["qa_panel"]["layout"] == [
        "source_crop",
        "mask_only",
        "overlay",
        "contour_on_source",
        "protected_neighbor_overlap_heat",
    ]
    expected = {label.name for label in get_ontology().labels}
    colors = document["label_colors"]
    assert set(colors) == expected
    assert len(set(colors.values())) == len(colors)
    assert all(len(color) == 7 and color.startswith("#") for color in colors.values())
