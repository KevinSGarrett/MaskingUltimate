from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.providers.sam31_exemplars import (
    AUTHORITY,
    Sam31VisualExemplarError,
    load_sam31_visual_exemplar,
    write_sam31_visual_exemplar,
)
from maskfactory.validation import validate_document


def _image(path: Path, *, value: int = 80) -> Path:
    pixels = np.full((10, 14, 3), value, dtype=np.uint8)
    pixels[2:8, 3:11] = (120, 70, 30)
    Image.fromarray(pixels, "RGB").save(path)
    return path


def test_visual_exemplar_is_closed_self_hashed_and_source_bound(tmp_path: Path) -> None:
    source = _image(tmp_path / "source.png")
    manifest = write_sam31_visual_exemplar(
        tmp_path / "prompts/hand.json",
        source_image=source,
        bbox_xyxy=(3, 2, 11, 8),
        polarity="negative",
    )
    document = json.loads(manifest.read_text(encoding="utf-8"))
    assert not validate_document(document, "sam31_visual_exemplar")
    assert document["authority"] == AUTHORITY
    assert document["kind"] == "same_image_visual_box"
    assert document["polarity"] == "negative"
    loaded = load_sam31_visual_exemplar(manifest, source_image=source)
    assert loaded["bbox_xyxy"] == [3.0, 2.0, 11.0, 8.0]
    assert loaded["polarity"] == "negative"
    assert len(loaded["manifest_sha256"]) == 64
    assert len(loaded["manifest_file_sha256"]) == 64


def test_visual_exemplar_rejects_tamper_cross_image_and_out_of_bounds(
    tmp_path: Path,
) -> None:
    source = _image(tmp_path / "source.png")
    other = _image(tmp_path / "other.png", value=20)
    manifest = write_sam31_visual_exemplar(
        tmp_path / "hand.json", source_image=source, bbox_xyxy=(3, 2, 11, 8)
    )
    with pytest.raises(Sam31VisualExemplarError, match="different source image"):
        load_sam31_visual_exemplar(manifest, source_image=other)

    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["bbox_xyxy"] = [1, 1, 5, 5]
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(Sam31VisualExemplarError, match="document hash is stale"):
        load_sam31_visual_exemplar(manifest, source_image=source)

    with pytest.raises(Sam31VisualExemplarError, match="outside its source image"):
        write_sam31_visual_exemplar(
            tmp_path / "outside.json",
            source_image=source,
            bbox_xyxy=(0, 0, 15, 5),
        )


def test_visual_exemplar_rejects_raw_images_and_invalid_polarity(tmp_path: Path) -> None:
    source = _image(tmp_path / "source.png")
    with pytest.raises(Sam31VisualExemplarError, match="governed same-image"):
        load_sam31_visual_exemplar(source, source_image=source)
    with pytest.raises(Sam31VisualExemplarError, match="polarity"):
        write_sam31_visual_exemplar(
            tmp_path / "invalid.json",
            source_image=source,
            bbox_xyxy=(1, 1, 5, 5),
            polarity="maybe",
        )
