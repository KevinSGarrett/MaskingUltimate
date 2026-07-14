"""Rebuild and diff the SQLite image index from authoritative package manifests."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .ontology_v2_manifest import require_valid_v2_manifest
from .state import DEFAULT_DB_PATH, initialize_database, reader_connection, writer_connection
from .validation import require_valid_document

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACKAGES_ROOT = ROOT / "data" / "packages"

STATUS_RANK = {
    "n/a": 0,
    "draft_model_generated": 1,
    "rejected_needs_fix": 2,
    "human_corrected": 3,
    "human_approved_gold": 4,
    "deprecated": 5,
}
PART_TO_IMAGE_STATUS = {
    "n/a": "ingested",
    "draft_model_generated": "drafted",
    "rejected_needs_fix": "in_review",
    "human_corrected": "corrected",
    "human_approved_gold": "approved_gold",
    "deprecated": "deprecated",
}
STATUS_STAGE = {
    "ingested": "S00",
    "drafted": "S09",
    "auto_qa": "S10",
    "vlm_qa": "S11",
    "in_review": "S12",
    "corrected": "S12",
    "approved_gold": "S13",
    "exported": "S14",
    "deprecated": "S13",
}
PACKAGE_REQUIRED_STATUSES = frozenset(
    {"in_review", "corrected", "approved_gold", "exported", "deprecated"}
)


class ReindexError(RuntimeError):
    """Package manifests cannot form one consistent image-index row."""


@dataclass(frozen=True)
class ImageIndexRow:
    image_id: str
    source_sha256: str
    status: str
    current_stage: str
    package_version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ReindexDiff:
    missing_in_db: tuple[str, ...]
    stale_rows: Mapping[str, Mapping[str, tuple[Any, Any]]]
    extra_in_db: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.missing_in_db and not self.stale_rows and not self.extra_in_db

    def as_dict(self) -> dict[str, Any]:
        return {
            "clean": self.clean,
            "missing_in_db": list(self.missing_in_db),
            "stale_rows": {
                image_id: {
                    field: {"database": values[0], "manifest": values[1]}
                    for field, values in fields.items()
                }
                for image_id, fields in self.stale_rows.items()
            },
            "extra_in_db": list(self.extra_in_db),
        }


def _manifest_status(manifest: Mapping[str, Any]) -> str:
    workflow_status = manifest.get("workflow_status")
    if workflow_status is not None:
        workflow_status = str(workflow_status)
        if workflow_status not in STATUS_STAGE:
            raise ReindexError(f"unsupported package workflow_status: {workflow_status}")
        return workflow_status
    parts = manifest["parts"]
    statuses = [entry["status"] for entry in parts.values()]
    highest = max(statuses, key=lambda status: STATUS_RANK[status], default="n/a")
    return PART_TO_IMAGE_STATUS[highest]


def _manifest_updated_at(manifest: Mapping[str, Any]) -> str:
    if manifest.get("workflow_updated_at"):
        return str(manifest["workflow_updated_at"])
    review = manifest["review"]
    return review.get("approved_at") or manifest["source"]["ingested_at"]


def _package_version(path: Path) -> int:
    versions = []
    for part in path.parts:
        if "@v" in part:
            _, _, suffix = part.rpartition("@v")
            if suffix.isdigit():
                versions.append(int(suffix))
    return max(versions, default=1)


def expected_image_rows(packages_root: Path = DEFAULT_PACKAGES_ROOT) -> dict[str, ImageIndexRow]:
    """Validate every per-instance manifest and collapse them to one row per image."""
    packages_root = Path(packages_root)
    if not packages_root.exists():
        return {}
    grouped: dict[str, list[tuple[dict[str, Any], Path]]] = {}
    for path in sorted(packages_root.rglob("manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not all(key in manifest for key in ("image_id", "source", "parts", "files")):
            continue
        if manifest.get("mask_ontology_version") == "body_parts_v2":
            require_valid_document(manifest, "manifest_v2")
            require_valid_v2_manifest(manifest)
        else:
            require_valid_document(manifest, "manifest")
        image_id = manifest["image_id"]
        relative = path.relative_to(packages_root)
        if not relative.parts or relative.parts[0] != image_id:
            raise ReindexError(
                f"manifest image_id {image_id} does not match package directory {relative.parts[0]}"
            )
        grouped.setdefault(image_id, []).append((manifest, path))

    rows: dict[str, ImageIndexRow] = {}
    for image_id, manifests in grouped.items():
        source_hashes = {manifest["source"]["parent_source_sha256"] for manifest, _ in manifests}
        if len(source_hashes) != 1:
            raise ReindexError(f"instances for {image_id} disagree on parent_source_sha256")
        statuses = [_manifest_status(manifest) for manifest, _ in manifests]
        status = max(statuses, key=lambda value: list(STATUS_STAGE).index(value))
        created = min(manifest["source"]["ingested_at"] for manifest, _ in manifests)
        updated = max(_manifest_updated_at(manifest) for manifest, _ in manifests)
        version = max(_package_version(path) for _, path in manifests)
        rows[image_id] = ImageIndexRow(
            image_id=image_id,
            source_sha256=next(iter(source_hashes)),
            status=status,
            current_stage=STATUS_STAGE[status],
            package_version=version,
            created_at=created,
            updated_at=updated,
        )
    return rows


def _database_rows(database: Path) -> dict[str, ImageIndexRow]:
    database = Path(database)
    if not database.is_file():
        return {}
    try:
        with reader_connection(database) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='images'"
            ).fetchone()
            if exists is None:
                return {}
            values = connection.execute(
                "SELECT image_id, source_sha256, status, current_stage, package_version, "
                "created_at, updated_at FROM images"
            ).fetchall()
    except Exception as exc:
        raise ReindexError(f"cannot read current image index: {exc}") from exc
    return {row[0]: ImageIndexRow(*tuple(row)) for row in values}


def diff_rows(
    expected: Mapping[str, ImageIndexRow], current: Mapping[str, ImageIndexRow]
) -> ReindexDiff:
    missing = tuple(sorted(set(expected).difference(current)))
    extra = tuple(
        sorted(
            image_id
            for image_id in set(current).difference(expected)
            if current[image_id].status in PACKAGE_REQUIRED_STATUSES
        )
    )
    stale: dict[str, dict[str, tuple[Any, Any]]] = {}
    for image_id in sorted(set(expected).intersection(current)):
        expected_values = asdict(expected[image_id])
        current_values = asdict(current[image_id])
        fields = {
            field: (current_values[field], expected_values[field])
            for field in expected_values
            if current_values[field] != expected_values[field]
        }
        if fields:
            stale[image_id] = fields
    return ReindexDiff(missing, stale, extra)


def reindex_packages(
    *,
    packages_root: Path = DEFAULT_PACKAGES_ROOT,
    database: Path = DEFAULT_DB_PATH,
    dry_run: bool,
) -> ReindexDiff:
    """Diff or transactionally rebuild images from validated package manifests."""
    expected = expected_image_rows(packages_root)
    current = _database_rows(database)
    difference = diff_rows(expected, current)
    if dry_run:
        return difference
    initialize_database(database)
    with writer_connection(database) as connection:
        touched = tuple(sorted(set(expected).union(difference.extra_in_db)))
        if touched:
            placeholders = ",".join("?" for _ in touched)
            connection.execute(
                f"DELETE FROM stage_runs WHERE image_id IN ({placeholders})", touched
            )
            connection.execute(
                f"DELETE FROM review_tasks WHERE image_id IN ({placeholders})", touched
            )
            connection.execute(f"DELETE FROM images WHERE image_id IN ({placeholders})", touched)
        connection.executemany(
            "INSERT INTO images (image_id, source_sha256, status, current_stage, package_version, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [tuple(asdict(row).values()) for row in expected.values()],
        )
    return difference


def run_reindex_incident_drill(
    *,
    source_database: Path,
    packages_root: Path,
    output_dir: Path,
    now: datetime | None = None,
) -> Path:
    """Copy state.db, rebuild only the copy from manifests, and prove a clean post-diff."""
    source_database = Path(source_database).resolve()
    if not source_database.is_file():
        raise FileNotFoundError(f"source state database is missing: {source_database}")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    token = timestamp.strftime("%Y%m%dT%H%M%SZ")
    copy_path = output_dir / f"maskfactory_ip3_copy_{token}.sqlite"
    if copy_path.exists():
        raise FileExistsError(f"incident drill copy already exists: {copy_path}")
    source_hash_before = _file_sha256(source_database)
    shutil.copy2(source_database, copy_path)
    before = reindex_packages(packages_root=packages_root, database=copy_path, dry_run=True)
    reindex_packages(packages_root=packages_root, database=copy_path, dry_run=False)
    after = reindex_packages(packages_root=packages_root, database=copy_path, dry_run=True)
    source_hash_after = _file_sha256(source_database)
    if source_hash_after != source_hash_before:
        raise ReindexError("source database changed during copy-only incident drill")
    if not after.clean:
        raise ReindexError(f"rebuilt incident copy still differs: {after.as_dict()}")
    report = {
        "schema_version": "1.0.0",
        "drill": "IP-3 state DB reindex on copy",
        "executed_at": timestamp.isoformat(),
        "source_database": str(source_database),
        "source_sha256_before": source_hash_before,
        "source_sha256_after": source_hash_after,
        "source_untouched": True,
        "copy_database": str(copy_path),
        "packages_root": str(Path(packages_root).resolve()),
        "before_rebuild": before.as_dict(),
        "after_rebuild": after.as_dict(),
    }
    report_path = output_dir / f"ip3_reindex_drill_{token}.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report_path


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
