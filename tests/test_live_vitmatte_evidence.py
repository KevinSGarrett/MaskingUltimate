import hashlib
import json
from pathlib import Path

from PIL import Image


def test_live_vitmatte_evidence_proves_mf_p3_03_03_contract() -> None:
    root = Path("qa/live_verification/mf_p3_03_03_vitmatte_live/img_dd4151e9a815/p0")
    audit = json.loads((root / "audit.json").read_text(encoding="utf-8"))
    matting = root / "matting"
    assert audit["item"] == "MF-P3-03.03"
    assert audit["triggered"] is True
    assert audit["hair_fraction_of_person_bbox"] >= audit["trigger_threshold"] == 0.02
    assert audit["trimap_values"] == [0, 128, 255]
    assert audit["trimap_radius_px"] == 3
    assert audit["known_background_exact_zero"] is True
    assert audit["known_foreground_exact_255"] is True
    assert audit["unknown_pixel_count"] > 0 and audit["unknown_std"] > 0
    assert audit["runtime"]["device"] == "NVIDIA GeForce RTX 5060 Laptop GPU"
    assert audit["checkpoint_sha256"] == (
        "6ec6aed44bc8d8ab7f4d0ff46da3520a534cf5a97a8262404ff6efa9ae33b1e5"
    )
    for name, expected in audit["artifacts"].items():
        path = matting / name
        assert Image.open(path).size == (429, 1600)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
