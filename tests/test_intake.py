import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image, PngImagePlugin

from maskfactory.cli import main
from maskfactory.intake import (
    DecodeRejected,
    ingest_one,
    inspect_image,
    perceptual_hash64,
    source_origin,
    write_metadata_stripped,
)


def _pattern(size: tuple[int, int] = (640, 768)) -> Image.Image:
    array = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    array[:, : size[0] // 2] = (240, 40, 20)
    array[size[1] // 3 :, size[0] // 2 :] = (20, 180, 230)
    return Image.fromarray(array)


def test_inspect_hash_identity_dimensions_origin_and_phash(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    source = incoming / "owned" / "sample.png"
    source.parent.mkdir(parents=True)
    _pattern().save(source)
    result = inspect_image(source, incoming)
    assert result.image_id == f"img_{result.source_sha256[:12]}"
    assert (result.width, result.height) == (640, 768)
    assert result.source_origin == "owned_photo"
    assert len(result.phash64) == 16
    assert int(result.phash64, 16) == perceptual_hash64(_pattern())


def test_origin_root_drop_quarantines_and_outside_path_rejected(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    assert source_origin(incoming / "root.png", incoming) is None
    with pytest.raises(ValueError, match="outside incoming root"):
        source_origin(tmp_path / "elsewhere" / "x.png", incoming)


@pytest.mark.parametrize(
    ("folder", "expected"),
    [
        ("generated", "generated"),
        ("owned", "owned_photo"),
        ("licensed", "licensed"),
        ("consented", "consented_subject"),
    ],
)
def test_every_governed_drop_folder_maps_to_manifest_origin(
    tmp_path: Path, folder: str, expected: str
) -> None:
    incoming = tmp_path / "incoming"
    assert source_origin(incoming / folder / "image.png", incoming) == expected


def test_corrupt_unsupported_and_undersize_rejected(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    corrupt = incoming / "bad.png"
    corrupt.write_bytes(b"not an image")
    with pytest.raises(DecodeRejected, match="cannot decode"):
        inspect_image(corrupt, incoming)
    unsupported = incoming / "image.bmp"
    _pattern().save(unsupported)
    with pytest.raises(DecodeRejected, match="unsupported"):
        inspect_image(unsupported, incoming)
    small = incoming / "small.png"
    _pattern((511, 700)).save(small)
    with pytest.raises(DecodeRejected, match="below required 512"):
        inspect_image(small, incoming)


def test_png_metadata_removed_without_pixel_change(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    destination = tmp_path / "clean.png"
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("private", "secret")
    _pattern().save(source, pnginfo=metadata)
    write_metadata_stripped(source, destination)
    with Image.open(source) as before, Image.open(destination) as after:
        assert np.array_equal(np.asarray(before), np.asarray(after))
        assert "private" not in after.info


def test_jpeg_metadata_removed_while_scan_data_remains_identical(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    destination = tmp_path / "clean.jpg"
    _pattern().save(source, quality=92, exif=b"Exif\x00\x00private")
    write_metadata_stripped(source, destination)
    clean = destination.read_bytes()
    assert b"private" not in clean
    original_scan = source.read_bytes()[source.read_bytes().index(b"\xff\xda") :]
    assert clean[clean.index(b"\xff\xda") :] == original_scan
    with Image.open(source) as before, Image.open(destination) as after:
        assert np.array_equal(np.asarray(before), np.asarray(after))


def test_required_ten_image_mixed_batch_routes_every_outcome(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    images = tmp_path / "images"
    database = tmp_path / "state.sqlite"
    event_log = tmp_path / "intake.jsonl"
    owned = incoming / "owned"
    owned.mkdir(parents=True)
    sources: list[Path] = []
    for index in range(5):
        source = owned / f"clear_{index}.png"
        array = np.asarray(_pattern()).copy()
        array[index, index] = (index * 20, 255 - index * 20, 100)
        Image.fromarray(array).save(source)
        sources.append(source)
    duplicate = owned / "duplicate.png"
    duplicate.write_bytes(sources[0].read_bytes())
    undersize = owned / "undersize.png"
    _pattern((511, 700)).save(undersize)
    corrupt = owned / "corrupt.png"
    corrupt.write_bytes(b"broken")
    root_drop = incoming / "root_drop.png"
    _pattern().save(root_drop)
    sixth_valid = owned / "sixth_valid.png"
    modified = np.asarray(_pattern()).copy()
    modified[20:40, 20:40] = 127
    Image.fromarray(modified).save(sixth_valid)

    ordered = [*sources, duplicate, undersize, corrupt, root_drop, sixth_valid]
    results = [
        ingest_one(
            path,
            incoming_root=incoming,
            images_root=images,
            database=database,
            event_log=event_log,
        )
        for path in ordered
    ]
    assert [result.outcome for result in results] == [
        "ingested",
        "ingested",
        "ingested",
        "ingested",
        "ingested",
        "duplicate_skipped",
        "rejected",
        "rejected",
        "quarantined",
        "ingested",
    ]
    assert results[5].duplicate is True
    assert "missing_or_invalid_source_origin" in results[8].reason
    assert results[9].reason == "accepted"
    assert (images / results[9].image_id).is_dir()
    accepted_manifest = json.loads(results[0].manifest_path.read_text(encoding="utf-8"))
    assert len(accepted_manifest["source"]["phash64"]) == 16
    assert accepted_manifest["source"]["exif_stripped"] is True
    with sqlite3.connect(database) as connection:
        counts = dict(connection.execute("SELECT status, count(*) FROM images GROUP BY status"))
    assert counts == {"ingested": 6, "quarantined": 1, "rejected": 2}
    events = [json.loads(line) for line in event_log.read_text(encoding="utf-8").splitlines()]
    assert len(events) == 10
    assert sum(event["outcome"] == "duplicate_skipped" for event in events) == 1


def test_cli_uses_configured_min_side_for_uniform_admission(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    owned = incoming / "owned"
    owned.mkdir(parents=True)
    source = owned / "source.png"
    _pattern((400, 400)).save(source)
    config = tmp_path / "pipeline.yaml"
    config.write_text(
        "intake:\n  min_side: 256\nstages: {}\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        main,
        [
            "ingest",
            str(source),
            "--incoming-root",
            str(incoming),
            "--images-root",
            str(tmp_path / "images"),
            "--database",
            str(tmp_path / "state.sqlite"),
            "--event-log",
            str(tmp_path / "events.jsonl"),
            "--config",
            str(config),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["outcome"] == "ingested"
