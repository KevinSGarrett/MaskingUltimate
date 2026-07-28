"""Generate the fixed visualization palette from the canonical ontology."""

from __future__ import annotations

import colorsys
from pathlib import Path

import yaml

from maskfactory.ontology import get_ontology

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "configs" / "viz.yaml"


def _color(index: int) -> str:
    # Golden-angle spacing produces a deterministic, visually separated fixed palette.
    hue = (index * 0.618033988749895) % 1.0
    red, green, blue = colorsys.hsv_to_rgb(hue, 0.72, 0.95)
    return f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"


def build_viz_config() -> dict[str, object]:
    labels = get_ontology().labels
    return {
        "config_version": "1.0.0",
        "overlay": {
            "fill_rgba": [255, 64, 64, 110],
            "contour_width_px": 1,
            "source_opacity": 1.0,
            "output_format": "png",
        },
        "qa_panel": {
            "tile_size_px": 512,
            "zoom_bbox_multiplier": 2.0,
            "layout": [
                "source_crop",
                "mask_only",
                "overlay",
                "contour_on_source",
                "protected_neighbor_overlap_heat",
            ],
            "direction": "horizontal",
        },
        "label_colors": {label.name: _color(index) for index, label in enumerate(labels)},
    }


def main() -> int:
    OUTPUT.write_text(
        yaml.safe_dump(build_viz_config(), sort_keys=False, width=100), encoding="utf-8"
    )
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
