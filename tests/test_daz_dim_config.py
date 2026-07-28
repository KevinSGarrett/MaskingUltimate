from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import maskfactory.daz.assets.dim_config as dim_config
from maskfactory.cli import main
from maskfactory.daz.assets import DimManifestError, configure_dim_paths, inspect_dim_paths


def _settings(secret: str = "encrypted-private-value") -> str:
    return f"""[General]
AccountTitle=Account
Account=private@example.invalid
Password={secret}
RememberPassword=true
DownloadPath=C:/Users/Public/Documents/DAZ 3D/InstallManager/Downloads
CurInstallPath=C:/Users/Public/Documents/My DAZ 3D Library
AutoInstall=true
AutoDelete=false

[InstallPaths]
size=2
1\\InstallPathTitle=Legacy Library
1\\InstallPath=C:/Users/Public/Documents/My DAZ 3D Library
2\\InstallPathTitle=Other Library
2\\InstallPath=D:/Other

[ApplicationPaths]
size=1
1\\AppName=DAZ Studio
"""


def test_dim_configuration_dry_run_redacts_and_does_not_modify(tmp_path: Path):
    path = tmp_path / "Account.ini"
    original = _settings().encode("utf-8")
    path.write_bytes(original)
    report = configure_dim_paths(path, apply=False)
    assert path.read_bytes() == original
    assert report["changed"] is True and report["applied"] is False
    assert report["before"] == {
        "download_root": "legacy_non_f",
        "install_root": "legacy_non_f",
        "install_path_count": 2,
        "automatic_install": True,
    }
    assert report["credential_values_extracted"] is False
    assert "private@example" not in json.dumps(report)
    assert "encrypted-private" not in json.dumps(report)


def test_dim_configuration_is_atomic_preserves_credentials_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "Account.ini"
    secret = "encrypted-private-value"
    path.write_text(_settings(secret), encoding="utf-8")
    monkeypatch.setattr(dim_config, "dim_processes_running", lambda: ())
    first = configure_dim_paths(path, apply=True)
    changed = path.read_text(encoding="utf-8")
    assert first["applied"] is True
    assert f"Password={secret}" in changed
    assert "Account=private@example.invalid" in changed
    assert "DownloadPath=F:/DAZ/02_installers/dim_downloads" in changed
    assert "CurInstallPath=F:/DAZ/03_content/libraries/MaskFactory_DAZ_Library" in changed
    assert "AutoInstall=false" in changed
    assert "size=1" in changed
    assert "2\\InstallPath" not in changed
    second = configure_dim_paths(path, apply=True)
    assert second["changed"] is False and second["applied"] is False
    inspection = inspect_dim_paths(path)
    assert inspection["already_compliant"] is True


def test_dim_configuration_refuses_live_dim_or_ambiguous_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "Account.ini"
    path.write_text(_settings(), encoding="utf-8")
    monkeypatch.setattr(dim_config, "dim_processes_running", lambda: (1234,))
    with pytest.raises(DimManifestError) as running:
        configure_dim_paths(path, apply=True)
    assert running.value.reason_code == "dim_process_running"

    monkeypatch.setattr(dim_config, "dim_processes_running", lambda: ())
    duplicate_text = _settings().replace(
        "DownloadPath=C:/Users/Public/Documents/DAZ 3D/InstallManager/Downloads",
        "DownloadPath=C:/Users/Public/Documents/DAZ 3D/InstallManager/Downloads\n"
        "DownloadPath=D:/duplicate",
    )
    path.write_text(duplicate_text, encoding="utf-8")
    with pytest.raises(DimManifestError) as duplicate:
        configure_dim_paths(path, apply=False)
    assert duplicate.value.reason_code == "dim_settings_duplicate_key"


def test_dim_configuration_cli_is_dry_run_by_default_and_uses_error_code_82(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "Account.ini"
    original = _settings()
    path.write_text(original, encoding="utf-8")
    original_bytes = path.read_bytes()
    runner = CliRunner()
    planned = runner.invoke(main, ["daz", "assets", "dim-config", "--account-settings", str(path)])
    assert planned.exit_code == 0
    assert json.loads(planned.output)["reason"] == "dim_configuration_plan"
    assert path.read_text(encoding="utf-8") == original

    monkeypatch.setattr(dim_config, "dim_processes_running", lambda: (1234,))
    refused = runner.invoke(
        main,
        ["daz", "assets", "dim-config", "--account-settings", str(path), "--apply"],
    )
    assert refused.exit_code == 82
    assert json.loads(refused.output)["code"] == 82
    assert (
        hashlib.sha256(path.read_bytes()).hexdigest() == hashlib.sha256(original_bytes).hexdigest()
    )
