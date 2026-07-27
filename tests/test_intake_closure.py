"""Hermetic S00 intake closure tests for the integrated runtime."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, PngImagePlugin

from maskfactory.intake import SafetyVerdict, ingest_one

NOW = datetime(2026, 7, 27, tzinfo=UTC)


class _AllowedFixtureScreener:
    """Hermetic source-policy fixture; production always supplies the local screener."""

    def screen(self, image: Path) -> SafetyVerdict:
        del image
        return SafetyVerdict("clear_adult", 1, "fixture-source-safety")


def _write_image(path: Path, color: tuple[int, int, int], *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = PngImagePlugin.PngInfo()
    if private:
        metadata.add_text("private", "synthetic-test-only")
    Image.new("RGB", (640, 512), color).save(path, pnginfo=metadata)


def test_intake_records_governed_outcomes_without_promoting_quarantine(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    images = tmp_path / "images"
    database = tmp_path / "state.sqlite"
    event_log = tmp_path / "intake.jsonl"
    accepted_source = incoming / "owned" / "accepted.png"
    root_drop = incoming / "root_drop.png"
    corrupt = incoming / "licensed" / "corrupt.png"
    _write_image(accepted_source, (11, 22, 33), private=True)
    _write_image(root_drop, (44, 55, 66))
    corrupt.parent.mkdir(parents=True, exist_ok=True)
    corrupt.write_bytes(b"not a PNG")
    screener = _AllowedFixtureScreener()

    accepted = ingest_one(
        accepted_source,
        screener=screener,
        incoming_root=incoming,
        images_root=images,
        database=database,
        event_log=event_log,
        now=lambda: NOW,
    )
    duplicate = ingest_one(
        accepted_source,
        screener=screener,
        incoming_root=incoming,
        images_root=images,
        database=database,
        event_log=event_log,
        now=lambda: NOW,
    )
    quarantined = ingest_one(
        root_drop,
        screener=screener,
        incoming_root=incoming,
        images_root=images,
        database=database,
        event_log=event_log,
        now=lambda: NOW,
    )
    rejected = ingest_one(
        corrupt,
        screener=screener,
        incoming_root=incoming,
        images_root=images,
        database=database,
        event_log=event_log,
        now=lambda: NOW,
    )

    assert (accepted.outcome, duplicate.outcome, quarantined.outcome, rejected.outcome) == (
        "ingested",
        "duplicate_skipped",
        "quarantined",
        "rejected",
    )
    assert duplicate.duplicate is True
    assert accepted.manifest_path is not None
    manifest = json.loads(accepted.manifest_path.read_text(encoding="utf-8"))
    assert manifest["source"]["source_origin"] == "owned_photo"
    assert manifest["source"]["exif_stripped"] is True
    cleaned_source = accepted.manifest_path.parent / manifest["source"]["source_file"]
    assert b"synthetic-test-only" not in cleaned_source.read_bytes()
    assert quarantined.manifest_path is not None
    assert quarantined.manifest_path.parent.name == "quarantine"
    assert "missing_or_invalid_source_origin" in quarantined.reason

    with sqlite3.connect(database) as connection:
        statuses = dict(connection.execute("SELECT status, count(*) FROM images GROUP BY status"))
    assert statuses == {"ingested": 1, "quarantined": 1, "rejected": 1}
    events = [json.loads(line) for line in event_log.read_text(encoding="utf-8").splitlines()]
    assert [event["outcome"] for event in events] == [
        "ingested",
        "duplicate_skipped",
        "quarantined",
        "rejected",
    ]
