"""Deterministic consumption plan for registered Civitai pose/control fixtures."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = ROOT / "configs" / "civitai_pose_stress_fixtures.yaml"
ELIGIBLE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".json"})


class CivitaiStressError(ValueError):
    """The governed stress-fixture registry or cache is incomplete."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_civitai_stress_plan(
    *,
    output_path: Path,
    registry_path: Path = DEFAULT_REGISTRY,
    verify_archives: bool = True,
    samples_per_fixture: int = 4,
) -> Path:
    """Turn all registered packs into a reproducible QA/acquisition input plan."""
    registry_path = Path(registry_path)
    document = yaml.safe_load(registry_path.read_text(encoding="utf-8-sig"))
    fixtures = document.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise CivitaiStressError("pose stress registry has no fixtures")
    entries: list[dict[str, Any]] = []
    covered: set[str] = set()
    for fixture in sorted(fixtures, key=lambda item: str(item["key"])):
        archive = ROOT / str(fixture["archive_path"])
        extracted = ROOT / str(fixture["extracted_path"])
        if not archive.is_file() or not extracted.is_dir():
            raise CivitaiStressError(f"fixture cache is missing: {fixture['key']}")
        if verify_archives and _sha256(archive) != str(fixture["archive_sha256"]):
            raise CivitaiStressError(f"fixture archive hash mismatch: {fixture['key']}")
        assets = tuple(
            path
            for path in sorted(extracted.rglob("*"), key=lambda value: value.as_posix().lower())
            if path.is_file() and path.suffix.lower() in ELIGIBLE_SUFFIXES
        )
        if not assets:
            raise CivitaiStressError(
                f"fixture has no eligible pose/control assets: {fixture['key']}"
            )
        coverage = tuple(sorted(str(value) for value in fixture["coverage"]))
        covered.update(coverage)
        entries.append(
            {
                "key": str(fixture["key"]),
                "civitai_id": int(fixture["civitai_id"]),
                "archive_sha256": str(fixture["archive_sha256"]),
                "coverage": list(coverage),
                "eligible_asset_count": len(assets),
                "sample_assets": [
                    path.relative_to(ROOT).as_posix() for path in assets[:samples_per_fixture]
                ],
                "use": ["stress_qa", "provider_disagreement", "coverage_acquisition"],
                "gold_authority": False,
                "training_or_gold_requires_intake_annotation_and_qa": True,
            }
        )
    required = set(str(value) for value in document.get("required_coverage", ()))
    missing = sorted(required - covered)
    if missing:
        raise CivitaiStressError(f"stress fixture coverage is incomplete: {missing}")
    plan = {
        "schema_version": "1.0.0",
        "registry_sha256": _sha256(registry_path),
        "authority": "stress_and_acquisition_input_only",
        "fixture_count": len(entries),
        "required_coverage": sorted(required),
        "covered": sorted(covered),
        "fixtures": entries,
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path
