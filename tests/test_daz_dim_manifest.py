from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from jsonschema import Draft202012Validator

from maskfactory.cli import main
from maskfactory.daz.assets import (
    DimManifestError,
    parse_dim_install_manifest,
    publish_dim_snapshot,
    scan_dim_manifest_archive,
)
from maskfactory.validation import validate_document

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "src" / "maskfactory" / "schemas"


def _manifest(
    *,
    global_id: str = "355f26dd-8387-4dd1-9a5c-84e0cc7dfa69",
    extra: str = "",
    files: str | None = None,
) -> str:
    file_elements = files or (
        '<File TARGET="Content" ACTION="Install" '
        'VALUE="Content/People/Genesis 9/Test Asset.duf"/>'
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<DAZInstallManifest VERSION="0.1">
 <GlobalID VALUE="{global_id}"/>
 <MetadataGlobalID VALUE="{global_id}"/>
 <SmartContent VALUE="True"/>
 <ProductName VALUE="Fixture Product"/>
 <ProductStoreIDX VALUE="86958-1"/>
 <ProductFileGuid VALUE="5013946f-d753-3895-c1cb-eeaaaad977d5"/>
 <InstallTypes VALUE="Content"/>
 <ProductTags VALUE="CloudAvailable,DAZStudio4_5"/>
 <UserInstallAccount VALUE="private-account@example.invalid"/>
 <UserInstallPath VALUE="F:/DAZ/03_content/libraries/MaskFactory_DAZ_Library"/>
 <InstalledSize VALUE="1234"/>
 {extra}
 {file_elements}
</DAZInstallManifest>
"""


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_dim_parser_builds_stable_ids_and_never_serializes_account_or_absolute_path(tmp_path: Path):
    path = _write(tmp_path / "IM00086958-01_Fixture.dsx", _manifest())
    first = parse_dim_install_manifest(path)
    second = parse_dim_install_manifest(path)
    assert first == second
    assert first.product_id.startswith("prd_") and len(first.product_id) == 28
    assert first.package_id.startswith("pkg_") and len(first.package_id) == 28
    assert first.store_sku == "86958" and first.store_download_id == "1"
    assert first.install_root_state == "expected_f"
    assert first.account_field_present is True
    serialized = json.dumps(first.summary(), sort_keys=True)
    assert "private-account" not in serialized
    assert "F:/DAZ" not in serialized
    assert first.entries[0].canonical_value == "content/people/genesis 9/test asset.duf"

    reinstalled = _write(
        tmp_path / "IM00086958-01_Reinstalled.dsx",
        _manifest(extra='<UserInstallDate VALUE="2026-07-16T00:00:00Z"/>'),
    )
    assert parse_dim_install_manifest(reinstalled).package_id == first.package_id


def test_dim_parser_records_execution_elevation_and_traversal_without_executing(tmp_path: Path):
    files = """
 <File TARGET="Content" ACTION="Install" VALUE="Content/../escape.exe"/>
 <File TARGET="Application" ACTION="Execute" VALUE="Tools/setup.exe"
       EXECUTEONINSTALL="True" EXECUTEELEVATED="True"/>
"""
    manifest = parse_dim_install_manifest(_write(tmp_path / "unsafe.dsx", _manifest(files=files)))
    assert [entry.safe_relative_path for entry in manifest.entries] == [False, True]
    assert sum(entry.executes for entry in manifest.entries) == 1
    assert sum(entry.elevated for entry in manifest.entries) == 1
    assert "unsafe_entry_path_present" in manifest.warnings
    assert "executable_action_present" in manifest.warnings
    assert "elevated_action_present" in manifest.warnings


@pytest.mark.parametrize(
    "text,reason_code",
    [
        ("<not-xml", "xml_malformed"),
        (_manifest(global_id="not-a-guid"), "global_id_invalid"),
        (
            _manifest(extra='<GlobalID VALUE="355f26dd-8387-4dd1-9a5c-84e0cc7dfa69"/>'),
            "duplicate_scalar",
        ),
        (
            '<!DOCTYPE x [<!ENTITY boom "boom">]>' + _manifest(),
            "xml_declaration_unsafe",
        ),
    ],
)
def test_dim_parser_rejects_malformed_ambiguous_or_entity_input(
    tmp_path: Path, text: str, reason_code: str
):
    path = _write(tmp_path / f"{reason_code}.dsx", text)
    with pytest.raises(DimManifestError) as caught:
        parse_dim_install_manifest(path)
    assert caught.value.reason_code == reason_code


def test_dim_parser_redacts_unknown_values_but_reports_unknown_element(tmp_path: Path):
    manifest = parse_dim_install_manifest(
        _write(
            tmp_path / "unknown.dsx",
            _manifest(extra='<FutureSecret VALUE="do-not-serialize-this" TOKEN="secret"/>'),
        )
    )
    assert manifest.unknown_elements == {"FutureSecret": 1}
    assert manifest.warnings == ("unknown_element:FutureSecret",)
    assert "do-not-serialize-this" not in json.dumps(manifest.summary())
    assert "secret" not in json.dumps(manifest.summary())


def test_dim_archive_scan_is_deterministic_closed_and_privacy_safe(tmp_path: Path):
    _write(tmp_path / "b.dsx", _manifest(global_id="255f26dd-8387-4dd1-9a5c-84e0cc7dfa69"))
    _write(tmp_path / "A.dsx", _manifest())
    _write(tmp_path / "broken.dsx", "<broken")
    first = scan_dim_manifest_archive(tmp_path)
    second = scan_dim_manifest_archive(tmp_path)
    assert first == second
    assert first["manifest_count"] == 3
    assert first["valid_count"] == 2 and first["invalid_count"] == 1
    assert first["entry_count"] == 2
    assert first["safety"]["account_values_stored"] == 0
    assert first["failures"][0]["reason_code"] == "xml_malformed"
    encoded = json.dumps(first, sort_keys=True)
    assert "private-account" not in encoded
    schema = json.loads(
        (SCHEMAS / "daz_dim_manifest_snapshot.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    assert validate_document(first, "daz_dim_manifest_snapshot") == ()


def test_dim_archive_scan_refuses_duplicate_package_identity(tmp_path: Path):
    document = _manifest()
    _write(tmp_path / "first.dsx", document)
    _write(tmp_path / "second.dsx", document)
    with pytest.raises(DimManifestError) as caught:
        scan_dim_manifest_archive(tmp_path)
    assert caught.value.reason_code == "duplicate_package_identity"


def test_dim_snapshot_publication_is_atomic_idempotent_and_immutable(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _write(source / "fixture.dsx", _manifest())
    report = scan_dim_manifest_archive(source)
    output = tmp_path / "snapshots"
    first = publish_dim_snapshot(report, output)
    second = publish_dim_snapshot(report, output)
    assert first["published"] is True and second["published"] is False
    target = Path(first["path"])
    assert json.loads(target.read_text(encoding="utf-8")) == report
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(DimManifestError) as caught:
        publish_dim_snapshot(report, output)
    assert caught.value.reason_code == "snapshot_immutable_drift"


def test_dim_scan_cli_returns_closed_json_and_stable_failure_code(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _write(source / "fixture.dsx", _manifest())
    output = tmp_path / "output"
    runner = CliRunner()
    successful = runner.invoke(
        main,
        ["daz", "assets", "dim-scan", "--source", str(source), "--output", str(output)],
    )
    assert successful.exit_code == 0
    document = json.loads(successful.output)
    assert document["reason"] == "dim_manifest_scan_complete"
    assert document["data"]["snapshot"]["valid_count"] == 1
    assert document["data"]["publication"]["published"] is True
    assert "private-account" not in successful.output

    _write(source / "broken.dsx", "<broken")
    partial = runner.invoke(main, ["daz", "assets", "dim-scan", "--source", str(source)])
    assert partial.exit_code == 0
    assert json.loads(partial.output)["data"]["snapshot"]["invalid_count"] == 1

    duplicate = tmp_path / "duplicate"
    duplicate.mkdir()
    _write(duplicate / "one.dsx", _manifest())
    _write(duplicate / "two.dsx", _manifest())
    refused = runner.invoke(main, ["daz", "assets", "dim-scan", "--source", str(duplicate)])
    assert refused.exit_code == 81
    assert json.loads(refused.output)["code"] == 81
