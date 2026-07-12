"""Durable count authority for real multi-instance orchestration fixtures."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

ALLOWED_ORIGINS = {"generated", "owned_photo", "licensed", "consented_subject", "qa_asset"}


class MultiInstanceFixtureError(ValueError):
    """A fixture set cannot prove its visible/promoted instance counts."""


def seal_multi_instance_fixture_set(
    registry_path: Path,
    output_path: Path,
    *,
    project_root: Path,
    max_instances_per_image: int = 4,
    work_root: Path | None = None,
) -> dict[str, Any]:
    """Validate 2-3 manually reviewed rasters against immutable S01 count evidence."""
    root = Path(project_root).resolve()
    if isinstance(max_instances_per_image, bool) or not 2 <= max_instances_per_image <= 16:
        raise MultiInstanceFixtureError("max_instances_per_image must be an integer in [2,16]")
    try:
        registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
        fixtures = registry["fixtures"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise MultiInstanceFixtureError(f"fixture source registry is unreadable: {exc}") from exc
    if not isinstance(fixtures, list) or not 2 <= len(fixtures) <= 3:
        raise MultiInstanceFixtureError("fixture set requires exactly 2-3 source records")
    required = {
        "key",
        "source_path",
        "source_sha256",
        "source_origin",
        "rights_evidence",
        "age_safety",
        "age_evidence",
        "manual_visible_instance_count",
        "reviewer",
        "reviewed_at",
        "s01_evidence_path",
        "s01_evidence_sha256",
        "s01_config_hash",
        "model_key",
    }
    records = []
    source_hashes = set()
    keys = set()
    for fixture in fixtures:
        if not isinstance(fixture, dict) or set(fixture) != required:
            raise MultiInstanceFixtureError(f"fixture requires exactly {sorted(required)}")
        key = fixture["key"]
        if not isinstance(key, str) or not key or key in keys:
            raise MultiInstanceFixtureError("fixture keys must be nonempty and unique")
        keys.add(key)
        if fixture["source_origin"] not in ALLOWED_ORIGINS:
            raise MultiInstanceFixtureError(f"fixture source origin is not governed: {key}")
        if fixture["age_safety"] != "clear_adult":
            raise MultiInstanceFixtureError(f"fixture is not age-cleared adult: {key}")
        for field in ("rights_evidence", "age_evidence", "reviewer", "reviewed_at"):
            if not isinstance(fixture[field], str) or not fixture[field].strip():
                raise MultiInstanceFixtureError(f"fixture {field} is missing: {key}")
        source = _safe_file(root, fixture["source_path"])
        evidence = _safe_file(root, fixture["s01_evidence_path"])
        source_digest = _sha256(source)
        evidence_digest = _sha256(evidence)
        if source_digest != fixture["source_sha256"]:
            raise MultiInstanceFixtureError(f"fixture source hash mismatch: {key}")
        if evidence_digest != fixture["s01_evidence_sha256"]:
            raise MultiInstanceFixtureError(f"fixture S01 evidence hash mismatch: {key}")
        if source_digest in source_hashes:
            raise MultiInstanceFixtureError("multi-instance fixtures must use distinct rasters")
        source_hashes.add(source_digest)
        try:
            s01 = json.loads(evidence.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MultiInstanceFixtureError(f"fixture S01 evidence is invalid: {key}") from exc
        manual_count = fixture["manual_visible_instance_count"]
        if isinstance(manual_count, bool) or not isinstance(manual_count, int) or manual_count < 2:
            raise MultiInstanceFixtureError(f"fixture manual count must be >=2: {key}")
        if s01.get("outcome") != "promoted" or s01.get("raw_detection_count") != manual_count:
            raise MultiInstanceFixtureError(f"manual and S01 visible counts differ: {key}")
        persons = s01.get("persons")
        if not isinstance(persons, list):
            raise MultiInstanceFixtureError(f"fixture persons list is missing: {key}")
        promoted = [person for person in persons if person.get("promoted") is True]
        expected_promoted = min(manual_count, max_instances_per_image)
        if len(promoted) != expected_promoted or [p.get("person_index") for p in promoted] != list(
            range(expected_promoted)
        ):
            raise MultiInstanceFixtureError(f"fixture promoted count/indexes differ: {key}")
        with Image.open(source) as opened:
            width, height = opened.size
        for person in promoted:
            _validate_box(person.get("bbox_xyxy"), width, height, key)
            _validate_box(person.get("context_bbox_xyxy"), width, height, key)
        promoted_names = [f"p{person['person_index']}" for person in promoted]
        # Canonical data/images paths carry the image id in their parent directory.
        image_id = source.parent.name if source.parent.parent.name == "images" else None
        downstream_verified = _downstream_verified(root, work_root, image_id, promoted_names)
        records.append(
            {
                "key": key,
                "source_path": fixture["source_path"],
                "source_sha256": source_digest,
                "source_size": [width, height],
                "source_origin": fixture["source_origin"],
                "rights_evidence": fixture["rights_evidence"],
                "age_safety": fixture["age_safety"],
                "age_evidence": fixture["age_evidence"],
                "manual_visible_instance_count": manual_count,
                "reviewer": fixture["reviewer"],
                "reviewed_at": fixture["reviewed_at"],
                "s01_evidence_path": fixture["s01_evidence_path"],
                "s01_evidence_sha256": evidence_digest,
                "s01_config_hash": fixture["s01_config_hash"],
                "model_key": fixture["model_key"],
                "raw_detection_count": s01["raw_detection_count"],
                "promoted_instance_count": len(promoted),
                "promoted_instances": promoted_names,
                "persons": promoted,
                "downstream_package_count_verified": downstream_verified,
            }
        )
    document = {
        "schema_version": "1.0.0",
        "fixture_count": len(records),
        "count_authority": "manual_visual_review_plus_s01_exact_match",
        "max_instances_per_image": max_instances_per_image,
        "fixtures": records,
        "downstream_status": (
            "verified_exact_promoted_draft_packages"
            if all(record["downstream_package_count_verified"] for record in records)
            else "not_all_fixture_package_counts_verified"
        ),
    }
    _atomic_json(Path(output_path), document)
    return document


def _downstream_verified(
    root: Path,
    work_root: Path | None,
    image_id: str | None,
    promoted: list[str],
) -> bool:
    if work_root is None or image_id is None or not image_id.startswith("img_"):
        return False
    work = (root / work_root).resolve() if not Path(work_root).is_absolute() else Path(work_root)
    if root not in work.parents and work != root:
        raise MultiInstanceFixtureError("fixture work root is outside project root")
    draft_instances = work / "drafts" / image_id / "instances"
    if not draft_instances.is_dir():
        return False
    actual = sorted(path.name for path in draft_instances.iterdir() if path.is_dir())
    if actual != promoted:
        return False
    for name in promoted:
        if not (draft_instances / name / "draft_contract.json").is_file():
            return False
        for stage in ("s02", "s03", "s04", "s05", "s06", "s07", "s08", "s08_5", "s09"):
            receipt = work / "instances" / name / stage / image_id / "stage_run.json"
            if not receipt.is_file():
                return False
            try:
                if json.loads(receipt.read_text(encoding="utf-8")).get("status") != "complete":
                    return False
            except (OSError, json.JSONDecodeError):
                return False
    manifest_path = work / "s09_5" / image_id / "image_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return manifest.get("promoted_instances") == promoted


def _safe_file(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise MultiInstanceFixtureError("fixture path must be project-relative")
    path = (root / Path(value.replace("\\", "/"))).resolve()
    if root not in path.parents or not path.is_file():
        raise MultiInstanceFixtureError(f"fixture path is missing or unsafe: {value}")
    return path


def _validate_box(value: Any, width: int, height: int, key: str) -> None:
    if not isinstance(value, list) or len(value) != 4 or not all(isinstance(v, int) for v in value):
        raise MultiInstanceFixtureError(f"fixture bbox is invalid: {key}")
    left, top, right, bottom = value
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise MultiInstanceFixtureError(f"fixture bbox is outside source geometry: {key}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
