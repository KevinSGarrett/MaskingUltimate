import hashlib
import json
from pathlib import Path

import numpy as np

from maskfactory.inpaint import derive_inpaint, feathered_dilation
from maskfactory.io.png_strict import read_mask, write_binary_mask


def test_feathered_dilation_has_hard_core_and_monotonic_ramp() -> None:
    mask = np.zeros((25, 25), dtype=bool)
    mask[12, 12] = True
    result = feathered_dilation(mask, dilate_px=2, feather_px=3)
    assert result[12, 12] == 255
    assert result[12, 14] == 255
    assert 0 < result[12, 17] < result[12, 16] < result[12, 15] < 255
    assert result[12, 18] == 0


def test_derive_inpaint_scales_settings_writes_ramp_and_updates_manifest(tmp_path: Path) -> None:
    package = tmp_path / "package"
    source = package / "masks_derived" / "left_hand.png"
    mask = np.zeros((512, 768), dtype=np.uint8)
    mask[200:300, 300:400] = 255
    write_binary_mask(source, mask)
    manifest = {"inpaint_derivatives": []}
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    config = tmp_path / "inpaint.yaml"
    config.write_text(
        "defaults:\n  dilate_px: 8\n  feather_px: 4\n  ref_scale: 1024\n"
        "targets: [left_hand]\noverrides: {}\n",
        encoding="utf-8",
    )

    outputs = derive_inpaint(package, config_path=config)
    assert outputs == (package / "inpaint" / "inpaint_left_hand_d6f3.png",)
    ramp = read_mask(outputs[0])
    assert ramp.dtype == np.uint8
    assert set(np.unique(ramp)) > {0, 255}
    updated = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    record = updated["inpaint_derivatives"][0]
    assert record == {
        "label": "left_hand",
        "file": "inpaint/inpaint_left_hand_d6f3.png",
        "dilate_px": 6,
        "feather_px": 3,
        "ref_scale": 1024,
        "source_gold_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
