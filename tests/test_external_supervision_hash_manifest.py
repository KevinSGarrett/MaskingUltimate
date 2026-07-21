import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from maskfactory.external_supervision_evidence import seal_payload
from maskfactory.external_supervision_hash_manifest import (
    SourceHashManifestError,
    build_source_hash_manifest,
    main,
    publish_source_hash_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (
    ROOT
    / "src"
    / "maskfactory"
    / "schemas"
    / "external_supervision_source_hash_manifest.schema.json"
)


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    (root / "images").mkdir(parents=True)
    (root / "masks").mkdir()
    (root / "images" / "b.jpg").write_bytes(b"image-b")
    (root / "images" / "a.jpg").write_bytes(b"image-a")
    (root / "masks" / "a.png").write_bytes(b"mask-a")
    return root


def test_full_manifest_is_deterministic_sealed_and_schema_valid(tmp_path: Path):
    source = _source(tmp_path)
    first = build_source_hash_manifest(source="fixture", source_root=source)
    second = build_source_hash_manifest(source="fixture", source_root=source)

    assert first == second
    assert first["file_count"] == 3
    assert first["total_bytes"] == 20
    assert [record["path"] for record in first["files"]] == [
        "images/a.jpg",
        "images/b.jpg",
        "masks/a.png",
    ]
    assert first["seal_sha256"] == seal_payload(first)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(first)


def test_published_manifest_is_atomic_and_hash_bound(tmp_path: Path):
    manifest = build_source_hash_manifest(source="fixture", source_root=_source(tmp_path))
    output = tmp_path / "evidence" / "manifest.json"
    file_hash = publish_source_hash_manifest(manifest, output)

    assert file_hash == hashlib.sha256(output.read_bytes()).hexdigest()
    assert json.loads(output.read_text(encoding="utf-8")) == manifest
    assert not list(output.parent.glob("*.partial"))
    assert publish_source_hash_manifest(manifest, output) == file_hash

    changed = dict(manifest)
    changed["source"] = "different"
    with pytest.raises(SourceHashManifestError, match="immutable .* path"):
        publish_source_hash_manifest(changed, output)


def test_missing_and_outside_paths_fail_closed(tmp_path: Path):
    source = _source(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    with pytest.raises(SourceHashManifestError, match="escaped or is unreadable"):
        build_source_hash_manifest(source="fixture", source_root=source, paths=[outside])
    with pytest.raises(SourceHashManifestError, match="escaped or is unreadable"):
        build_source_hash_manifest(
            source="fixture", source_root=source, paths=[source / "missing.jpg"]
        )


def test_empty_and_duplicate_path_sets_fail_closed(tmp_path: Path):
    source = _source(tmp_path)
    with pytest.raises(SourceHashManifestError, match="cannot be empty"):
        build_source_hash_manifest(source="fixture", source_root=source, paths=[])
    same = source / "images" / "a.jpg"
    with pytest.raises(SourceHashManifestError, match="path collision"):
        build_source_hash_manifest(source="fixture", source_root=source, paths=[same, same])


def test_cli_publishes_machine_readable_result(tmp_path: Path, capsys):
    source = _source(tmp_path)
    output = tmp_path / "manifest.json"
    assert (
        main(
            [
                "--source",
                "fixture",
                "--source-root",
                str(source),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "PASS"
    assert result["file_count"] == 3
    assert result["manifest_file_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
