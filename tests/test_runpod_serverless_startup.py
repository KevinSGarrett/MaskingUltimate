from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("deploy/runpod_serverless/maskfactory/start.sh")
pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="startup link semantics require a native Linux filesystem",
)


def bash_path(path: Path) -> str:
    resolved = path.resolve()
    if os.name != "nt":
        return str(resolved)
    windows_path = str(resolved).replace("\\", "/")
    return f"/mnt/{windows_path[0].lower()}{windows_path[2:]}"


def run_prepare(volume: Path, workspace: Path) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment.update(
        {
            "RUNPOD_VOLUME_PATH": bash_path(volume),
            "MASKFACTORY_WORKSPACE_PATH": bash_path(workspace),
        }
    )
    return subprocess.run(
        ["bash", bash_path(SCRIPT), "--prepare-only"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_startup_replaces_only_empty_base_image_workspace(tmp_path: Path) -> None:
    volume = tmp_path / "runpod-volume"
    workspace = tmp_path / "workspace"
    volume.mkdir()
    workspace.mkdir()

    result = run_prepare(volume, workspace)

    assert result.returncode == 0, result.stderr
    assert workspace.is_symlink()
    assert workspace.resolve() == volume.resolve()


def test_startup_refuses_to_replace_nonempty_workspace(tmp_path: Path) -> None:
    volume = tmp_path / "runpod-volume"
    workspace = tmp_path / "workspace"
    volume.mkdir()
    workspace.mkdir()
    marker = workspace / "do-not-delete"
    marker.write_text("preserve", encoding="utf-8")

    result = run_prepare(volume, workspace)

    assert result.returncode == 64
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert not workspace.is_symlink()
