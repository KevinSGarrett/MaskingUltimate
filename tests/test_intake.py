import base64
import io
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
    LocalSourceSafetyScreener,
    SourceSafetyVerdict,
    ingest_one,
    inspect_image,
    perceptual_hash64,
    rescreen_quarantined,
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


class NamedSafetyScreener:
    def screen(self, image: Path) -> SourceSafetyVerdict:
        verdict = "prohibited" if "prohibited" in image.name else "allowed"
        return SourceSafetyVerdict(verdict, 1, "detector+fixture-vlm", "fixture decision")


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
    prohibited = owned / "prohibited_source.png"
    modified = np.asarray(_pattern()).copy()
    modified[20:40, 20:40] = 127
    Image.fromarray(modified).save(prohibited)

    ordered = [*sources, duplicate, undersize, corrupt, root_drop, prohibited]
    results = [
        ingest_one(
            path,
            screener=NamedSafetyScreener(),
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
        "quarantined",
    ]
    assert results[5].duplicate is True
    assert "missing_or_invalid_source_origin" in results[8].reason
    assert results[9].reason == "source_safety_prohibited"
    assert not (images / results[9].image_id).exists()
    accepted_manifest = json.loads(results[0].manifest_path.read_text(encoding="utf-8"))
    assert len(accepted_manifest["source"]["phash64"]) == 16
    assert accepted_manifest["source"]["exif_stripped"] is True
    assert accepted_manifest["source_safety"]["non_configurable"] is True
    with sqlite3.connect(database) as connection:
        counts = dict(connection.execute("SELECT status, count(*) FROM images GROUP BY status"))
    assert counts == {"ingested": 5, "quarantined": 2, "rejected": 2}
    events = [json.loads(line) for line in event_log.read_text(encoding="utf-8").splitlines()]
    assert len(events) == 10
    assert sum(event["outcome"] == "duplicate_skipped" for event in events) == 1


def test_local_source_safety_is_fail_closed_and_parses_allowed(tmp_path: Path) -> None:
    image = tmp_path / "source.png"
    _pattern().save(image)

    def clear_request(_request, _timeout):
        return json.dumps(
            {"message": {"content": json.dumps({"decision": "allowed", "reason": "allowed"})}}
        ).encode()

    clear = LocalSourceSafetyScreener(detector=lambda _path: 2, request=clear_request).screen(image)
    assert clear == SourceSafetyVerdict("allowed", 2, "qwen2.5vl:7b", "allowed")
    failed = LocalSourceSafetyScreener(
        detector=lambda _path: (_ for _ in ()).throw(RuntimeError("detector unavailable"))
    ).screen(image)
    assert failed.verdict == "uncertain"
    assert "detector unavailable" in failed.detail


def test_source_safety_downscales_locally_and_retries_strict_json(tmp_path: Path) -> None:
    image = tmp_path / "large.png"
    _pattern((2400, 1600)).save(image)
    payloads = []
    responses = [
        {"message": {"content": "not json"}},
        {"message": {"content": json.dumps({"decision": "allowed", "reason": "allowed source"})}},
    ]

    def request(request, _timeout):
        payloads.append(json.loads(request.data))
        return json.dumps(responses.pop(0)).encode()

    result = LocalSourceSafetyScreener(detector=lambda _path: 2, request=request).screen(image)
    assert result.verdict == "allowed" and result.person_count == 2
    assert len(payloads) == 2
    for payload in payloads:
        assert payload["options"] == {"temperature": 0, "seed": 1337, "num_predict": 128}
        review_bytes = base64.b64decode(payload["messages"][0]["images"][0])
        assert review_bytes != image.read_bytes()
        with Image.open(io.BytesIO(review_bytes)) as review:
            assert max(review.size) == 1024
            assert review.mode == "RGB"
    assert "prior response was invalid" in payloads[1]["messages"][0]["content"]


def test_source_safety_rejects_extra_or_empty_response_fields(tmp_path: Path) -> None:
    image = tmp_path / "source.png"
    _pattern().save(image)
    invalid = json.dumps(
        {"message": {"content": json.dumps({"decision": "allowed", "reason": ""})}}
    ).encode()
    screener = LocalSourceSafetyScreener(detector=lambda _path: 1, request=lambda *_args: invalid)
    result = screener.screen(image)
    assert result.verdict == "uncertain"
    assert "after one retry" in result.detail


def test_quarantine_rescreen_promotes_only_matching_allowed_source(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    source = incoming / "generated" / "source.png"
    source.parent.mkdir(parents=True)
    _pattern().save(source)
    images = tmp_path / "images"
    database = tmp_path / "state.sqlite"
    events = tmp_path / "intake.jsonl"

    class Uncertain:
        def screen(self, _image):
            return SourceSafetyVerdict("uncertain", 1, "fixture", "first pass unavailable")

    initial = ingest_one(
        source,
        screener=Uncertain(),
        incoming_root=incoming,
        images_root=images,
        database=database,
        event_log=events,
    )
    assert initial.outcome == "quarantined"

    class Allowed:
        def screen(self, _image):
            return SourceSafetyVerdict("allowed", 1, "fixture", "allowed")

    promoted = rescreen_quarantined(
        source,
        screener=Allowed(),
        incoming_root=incoming,
        images_root=images,
        database=database,
        event_log=events,
    )
    assert promoted.outcome == "ingested"
    assert not initial.manifest_path.exists()
    manifest = json.loads(promoted.manifest_path.read_text())
    assert manifest["reason"] == "accepted_after_source_safety_rescreen"
    assert manifest["source_safety"]["verdict"] == "allowed"
    assert manifest["source"]["exif_stripped"] is True
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT status FROM images WHERE image_id = ?", (promoted.image_id,)
        ).fetchone() == ("ingested",)
    assert json.loads(events.read_text().splitlines()[-1])["action"] == "source_safety_rescreen"


def test_quarantine_rescreen_stays_closed_and_refuses_wrong_source(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    source = incoming / "generated" / "subject.png"
    source.parent.mkdir(parents=True)
    _pattern().save(source)
    images = tmp_path / "images"
    database = tmp_path / "state.sqlite"
    events = tmp_path / "intake.jsonl"

    class Uncertain:
        def screen(self, _image):
            return SourceSafetyVerdict("uncertain", 1, "fixture", "uncertain")

    initial = ingest_one(
        source,
        screener=Uncertain(),
        incoming_root=incoming,
        images_root=images,
        database=database,
        event_log=events,
    )
    repeated = rescreen_quarantined(
        source,
        screener=Uncertain(),
        incoming_root=incoming,
        images_root=images,
        database=database,
        event_log=events,
    )
    assert repeated.outcome == "quarantined" and initial.manifest_path.exists()
    changed = np.asarray(_pattern()).copy()
    changed[0, 0] = (1, 2, 3)
    Image.fromarray(changed).save(source)
    with pytest.raises(ValueError, match="not an existing quarantined image"):
        rescreen_quarantined(
            source,
            screener=Uncertain(),
            incoming_root=incoming,
            images_root=images,
            database=database,
            event_log=events,
        )


def test_cli_uses_configured_min_side_but_cannot_disable_source_safety(
    tmp_path: Path, monkeypatch
) -> None:
    incoming = tmp_path / "incoming"
    owned = incoming / "owned"
    owned.mkdir(parents=True)
    source = owned / "prohibited.png"
    _pattern((400, 400)).save(source)
    config = tmp_path / "pipeline.yaml"
    config.write_text(
        "intake:\n  min_side: 256\n  source_safety_enabled: false\nstages: {}\n",
        encoding="utf-8",
    )

    class ProhibitedScreener:
        def screen(self, _image: Path) -> SourceSafetyVerdict:
            return SourceSafetyVerdict("prohibited", 1, "fixture")

    monkeypatch.setattr("maskfactory.intake.LocalSourceSafetyScreener", ProhibitedScreener)
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
    assert json.loads(result.output)["outcome"] == "quarantined"
