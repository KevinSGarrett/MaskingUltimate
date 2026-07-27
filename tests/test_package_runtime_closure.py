from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

from click.testing import CliRunner

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_declares_the_live_maskfactory_entrypoint() -> None:
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)

    entrypoint = project["project"]["scripts"]["maskfactory"]
    module_name, callable_name = entrypoint.split(":", maxsplit=1)
    module = importlib.import_module(module_name)

    assert callable(getattr(module, callable_name))


def test_declared_entrypoint_builds_a_nonempty_command_surface() -> None:
    from maskfactory.cli import main

    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0, result.output
    assert "MaskFactory pipeline" in result.output
    assert "doctor" in result.output
    assert "models" in result.output
