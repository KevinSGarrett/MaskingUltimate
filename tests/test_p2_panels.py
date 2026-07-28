from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from maskfactory.qa.panels import render_boundary_panel, render_part_overlays


def test_per_label_and_all_parts_overlays_follow_viz_config(tmp_path: Path) -> None:
    source = Image.new("RGB", (80, 60), (20, 30, 40))
    part = np.zeros((60, 80), dtype=np.uint16)
    part[10:30, 10:35] = 18
    part[25:50, 45:70] = 19
    config = yaml.safe_load(Path("configs/viz.yaml").read_text())
    outputs = render_part_overlays(
        source,
        part,
        tmp_path,
        label_colors=config["label_colors"],
        alpha=config["overlay"]["fill_rgba"][3],
        contour_width=config["overlay"]["contour_width_px"],
    )
    assert {path.name for path in outputs} == {
        "left_forearm.png",
        "right_forearm.png",
        "all_parts.png",
    }
    assert all(Image.open(path).mode == "RGB" for path in outputs)
    assert all(Image.open(path).size == source.size for path in outputs)
    assert np.array(Image.open(tmp_path / "all_parts.png"))[20, 20].tolist() != [20, 30, 40]


def test_boundary_panel_has_exact_five_tile_layout_and_overlap_heat(tmp_path: Path) -> None:
    source = Image.new("RGB", (100, 100), (30, 30, 30))
    mask = np.zeros((100, 100), dtype=bool)
    protected = np.zeros_like(mask)
    mask[30:70, 35:65] = True
    protected[45:60, 50:75] = True
    path = render_boundary_panel(source, mask, protected, tmp_path / "left_forearm.png")
    panel = Image.open(path)
    assert panel.mode == "RGB"
    assert panel.size == (512 * 5, 512)
    pixels = np.asarray(panel)
    assert pixels[:, 512:1024].max() == 255  # mask-only tile
    heat = pixels[:, 2048:2560].astype(int)
    assert np.any((heat[:, :, 0] > heat[:, :, 1] + 50) & (heat[:, :, 2] > heat[:, :, 1] + 50))
