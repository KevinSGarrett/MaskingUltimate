"""S00 image intake primitives: identity, decoding, provenance, privacy, and pHash."""

from __future__ import annotations

import io
import json
import os
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

from .fs_atomic import replace_with_retry
from .io.hashing import sha256_file
from .state import DEFAULT_DB_PATH, initialize_database, writer_connection

ALLOWED_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
ORIGIN_FOLDERS = {
    "generated": "generated",
    "owned": "owned_photo",
    "licensed": "licensed",
    "consented": "consented_subject",
}
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INCOMING_ROOT = ROOT / "data" / "incoming"
DEFAULT_IMAGES_ROOT = ROOT / "data" / "images"
DEFAULT_EVENT_LOG = ROOT / "logs" / "intake.jsonl"


class IntakeError(ValueError):
    """Base class for deterministic intake rejection reasons."""


class DecodeRejected(IntakeError):
    """Image is corrupt, unsupported, or below the minimum dimension."""


@dataclass(frozen=True)
class InspectedImage:
    source_sha256: str
    image_id: str
    width: int
    height: int
    format: str
    phash64: str
    source_origin: str | None


@dataclass(frozen=True)
class IntakeResult:
    image_id: str
    outcome: str
    reason: str
    duplicate: bool = False
    manifest_path: Path | None = None


def source_origin(path: Path, incoming_root: Path) -> str | None:
    """Map the first drop subfolder to manifest provenance; root drops quarantine."""
    try:
        relative = Path(path).resolve().relative_to(Path(incoming_root).resolve())
    except ValueError as exc:
        raise IntakeError(f"source is outside incoming root: {path}") from exc
    return ORIGIN_FOLDERS.get(relative.parts[0].lower()) if len(relative.parts) > 1 else None


def inspect_image(path: Path, incoming_root: Path, *, min_side: int = 512) -> InspectedImage:
    path = Path(path)
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise DecodeRejected(f"unsupported image extension: {path.suffix}")
    digest = sha256_file(path)
    try:
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            image_format = str(image.format).upper()
            if min(width, height) < min_side:
                raise DecodeRejected(
                    f"minimum side {min(width, height)} is below required {min_side}"
                )
            phash = perceptual_hash64(image)
    except (OSError, UnidentifiedImageError) as exc:
        raise DecodeRejected(f"cannot decode image: {path}") from exc
    return InspectedImage(
        source_sha256=digest,
        image_id=f"img_{digest[:12]}",
        width=width,
        height=height,
        format=image_format,
        phash64=f"{phash:016x}",
        source_origin=source_origin(path, incoming_root),
    )


def perceptual_hash64(image: Image.Image) -> int:
    """Compute the standard 8x8 low-frequency DCT pHash as an unsigned 64-bit value."""
    sample = np.asarray(image.convert("L").resize((32, 32), Image.Resampling.LANCZOS), dtype=float)
    positions = np.arange(32)
    transform = np.cos(np.pi * (2 * positions[:, None] + 1) * positions[None, :] / 64)
    coefficients = transform.T @ sample @ transform
    low = coefficients[:8, :8]
    median = float(np.median(low.reshape(-1)[1:]))
    bits = (low > median).reshape(-1)
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def write_metadata_stripped(source: Path, destination: Path) -> None:
    """Write a pixel-lossless PNG or scan-lossless metadata-free JPEG."""
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        destination.write_bytes(_strip_jpeg_metadata(source.read_bytes()))
        return
    try:
        with Image.open(source) as image:
            image.load()
            output = io.BytesIO()
            image.save(output, format="PNG")  # png-strict: allow (source privacy rewrite)
            destination.write_bytes(output.getvalue())
    except (OSError, UnidentifiedImageError) as exc:
        raise DecodeRejected(f"cannot strip metadata from image: {source}") from exc


def _strip_jpeg_metadata(data: bytes) -> bytes:
    if not data.startswith(b"\xff\xd8"):
        raise DecodeRejected("invalid JPEG start marker")
    output = bytearray(data[:2])
    cursor = 2
    while cursor < len(data):
        if data[cursor] != 0xFF:
            raise DecodeRejected("invalid JPEG marker stream")
        marker_start = cursor
        while cursor < len(data) and data[cursor] == 0xFF:
            cursor += 1
        if cursor >= len(data):
            raise DecodeRejected("truncated JPEG marker")
        marker = data[cursor]
        cursor += 1
        if marker == 0xDA:  # Start of scan: copy encoded pixels and EOI byte-exact.
            output.extend(data[marker_start:])
            return bytes(output)
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            output.extend(data[marker_start:cursor])
            continue
        if cursor + 2 > len(data):
            raise DecodeRejected("truncated JPEG segment length")
        length = int.from_bytes(data[cursor : cursor + 2], "big")
        segment_end = cursor + length
        if length < 2 or segment_end > len(data):
            raise DecodeRejected("invalid JPEG segment length")
        # APPn and COM are metadata. Preserve all coding/quantization/frame segments.
        if not (0xE0 <= marker <= 0xEF or marker == 0xFE):
            output.extend(data[marker_start:segment_end])
        cursor = segment_end
    raise DecodeRejected("JPEG has no start-of-scan marker")


def ingest_one(
    source: Path,
    *,
    incoming_root: Path = DEFAULT_INCOMING_ROOT,
    images_root: Path = DEFAULT_IMAGES_ROOT,
    database: Path = DEFAULT_DB_PATH,
    event_log: Path = DEFAULT_EVENT_LOG,
    min_side: int = 512,
    now: Callable[[], datetime] | None = None,
) -> IntakeResult:
    """Run governed S00 source registration and intake."""
    source = Path(source)
    incoming_root = Path(incoming_root)
    images_root = Path(images_root)
    database = Path(database)
    event_log = Path(event_log)
    timestamp = (now or (lambda: datetime.now(UTC)))().astimezone(UTC).isoformat()
    digest = sha256_file(source)
    image_id = f"img_{digest[:12]}"
    initialize_database(database)

    duplicate_status = _existing_status(database, digest)
    if duplicate_status is not None:
        _append_event(
            event_log,
            {
                "at": timestamp,
                "image_id": image_id,
                "source_sha256": digest,
                "outcome": "duplicate_skipped",
                "existing_status": duplicate_status,
            },
        )
        return IntakeResult(image_id, "duplicate_skipped", duplicate_status, duplicate=True)

    try:
        inspected = inspect_image(source, incoming_root, min_side=min_side)
    except DecodeRejected as exc:
        _insert_image(database, image_id, digest, "rejected", timestamp)
        _append_event(
            event_log,
            {
                "at": timestamp,
                "image_id": image_id,
                "source_sha256": digest,
                "outcome": "rejected",
                "reason": str(exc),
            },
        )
        return IntakeResult(image_id, "rejected", str(exc))

    quarantine_reasons = []
    if inspected.source_origin is None:
        quarantine_reasons.append("missing_or_invalid_source_origin")
    outcome = "quarantined" if quarantine_reasons else "ingested"
    reason = ",".join(quarantine_reasons) if quarantine_reasons else "accepted"

    manifest = {
        "schema_version": "1.0.0",
        "image_id": image_id,
        "status": outcome,
        "source": {
            "original_name": source.name,
            "source_sha256": inspected.source_sha256,
            "source_width": inspected.width,
            "source_height": inspected.height,
            "source_format": inspected.format,
            "source_origin": inspected.source_origin,
            "ingested_at": timestamp,
            "exif_stripped": outcome == "ingested",
            "phash64": inspected.phash64,
        },
        "reason": reason,
    }
    manifest_path: Path
    if outcome == "ingested":
        image_directory = images_root / image_id
        temporary = images_root / f".{image_id}.tmp-{uuid.uuid4().hex}"
        temporary.mkdir(parents=True, exist_ok=False)
        extension = ".jpg" if source.suffix.lower() in {".jpg", ".jpeg"} else ".png"
        try:
            write_metadata_stripped(source, temporary / f"source{extension}")
            manifest["source"]["source_file"] = f"source{extension}"
            _write_json_atomic(temporary / "manifest.json", manifest)
            replace_with_retry(temporary, image_directory)
        except Exception:
            _remove_tree(temporary)
            raise
        manifest_path = image_directory / "manifest.json"
    else:
        # Quarantine records contain metadata and decisions only; suspect imagery is not copied.
        manifest_path = images_root / "quarantine" / f"{image_id}.json"
        _write_json_atomic(manifest_path, manifest)

    try:
        _insert_image(database, image_id, digest, outcome, timestamp)
    except Exception:
        if outcome == "ingested":
            _remove_tree(manifest_path.parent)
        else:
            manifest_path.unlink(missing_ok=True)
        raise
    _append_event(
        event_log,
        {
            "at": timestamp,
            "image_id": image_id,
            "source_sha256": digest,
            "outcome": outcome,
            "reason": reason,
            "phash64": inspected.phash64,
        },
    )
    return IntakeResult(image_id, outcome, reason, manifest_path=manifest_path)


def _existing_status(database: Path, digest: str) -> str | None:
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT status FROM images WHERE source_sha256 = ?", (digest,)
        ).fetchone()
        return str(row[0]) if row is not None else None
    finally:
        connection.close()


def _insert_image(database: Path, image_id: str, digest: str, status: str, timestamp: str) -> None:
    with writer_connection(database) as connection:
        connection.execute(
            """
            INSERT INTO images(image_id, source_sha256, status, current_stage, created_at, updated_at)
            VALUES (?, ?, ?, 'S00', ?, ?)
            """,
            (image_id, digest, status, timestamp, timestamp),
        )


def _write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_dir():
            _remove_tree(child)
        else:
            child.unlink()
    path.rmdir()
