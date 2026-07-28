#!/usr/bin/env python3
"""Validate one MaskFactory DAZ asset manifest without modifying it."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import jsonschema
import yaml

PACKAGE = Path(__file__).resolve().parents[1]
SCHEMA = PACKAGE / "schemas" / "asset_manifest.schema.json"
VOCAB = PACKAGE / "vocabularies" / "controlled_vocabularies.yaml"
TAXONOMY = PACKAGE / "vocabularies" / "body_taxonomy.yaml"


def load(path: Path):
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate(path: Path, check_files: bool) -> tuple[list[str], list[str]]:
    record, schema, vocab, taxonomy = load(path), load(SCHEMA), load(VOCAB), load(TAXONOMY)
    errors: list[str] = []
    warnings: list[str] = []
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    for error in sorted(validator.iter_errors(record), key=lambda item: list(item.path)):
        location = ".".join(map(str, error.path)) or "$"
        errors.append(f"schema:{location}: {error.message}")

    classes = set(vocab["primary_asset_classes"])
    roles = set(vocab["file_roles"])
    generations = set(vocab["generations"])
    taxon_by_id = {item["id"]: item for item in taxonomy["taxa"]}
    classification = record.get("classifications", {})
    if classification.get("primary_asset_class") not in classes:
        errors.append("vocabulary: invalid primary_asset_class")
    if classification.get("dropzone_generation") not in generations:
        errors.append("vocabulary: invalid dropzone_generation")
    for item in record.get("files", []):
        if item.get("role") not in roles:
            errors.append(f"vocabulary:{item.get('file_id')}: invalid file role")
    for link in record.get("body_associations", []):
        taxon = taxon_by_id.get(link.get("taxon_id"))
        if not taxon:
            errors.append(f"taxonomy:{link.get('taxon_id')}: unknown taxon")
        elif taxon["level"] != link.get("level"):
            errors.append(f"taxonomy:{link.get('taxon_id')}: level mismatch")

    groups = ("packages", "files", "assets", "components", "properties", "dependencies", "inspections")
    id_keys = ("package_id", "file_id", "asset_id", "component_id", "property_id", "dependency_id", "inspection_id")
    seen = {record.get("product", {}).get("product_id")}
    for group, key in zip(groups, id_keys):
        for item in record.get(group, []):
            value = item.get(key)
            if value in seen:
                errors.append(f"identity:{value}: duplicate stable ID")
            seen.add(value)
    file_ids = {item.get("file_id") for item in record.get("files", [])}
    asset_ids = {item.get("asset_id") for item in record.get("assets", [])}
    component_ids = {item.get("component_id") for item in record.get("components", [])}
    for item in record.get("assets", []):
        if item.get("source_file_id") not in file_ids:
            errors.append(f"reference:{item.get('asset_id')}: source file is unresolved")
    for item in record.get("components", []):
        if item.get("asset_id") not in asset_ids:
            errors.append(f"reference:{item.get('component_id')}: asset is unresolved")
    for item in record.get("properties", []):
        if item.get("owner_component_id") not in component_ids:
            errors.append(f"reference:{item.get('property_id')}: owner component is unresolved")

    if check_files:
        for item in record.get("files", []):
            if item.get("existence") != "present":
                continue
            candidate = Path(item.get("installed_absolute_path", ""))
            if not candidate.is_file():
                errors.append(f"path:{item.get('file_id')}: present file does not exist")
                continue
            if candidate.stat().st_size != item.get("size_bytes"):
                errors.append(f"size:{item.get('file_id')}: byte count differs")
            if sha256(candidate) != item.get("sha256"):
                errors.append(f"hash:{item.get('file_id')}: SHA-256 differs")
    else:
        warnings.append("filesystem hash checks skipped; pass --check-files for installed records")
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--check-files", action="store_true")
    args = parser.parse_args()
    errors, warnings = validate(args.manifest.resolve(), args.check_files)
    result = {"valid": not errors, "errors": errors, "warnings": warnings}
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
