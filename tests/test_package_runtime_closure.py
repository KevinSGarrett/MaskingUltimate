from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_declares_the_live_maskfactory_entrypoint() -> None:
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)

    entrypoint = project["project"]["scripts"]["maskfactory"]
    module_name, callable_name = entrypoint.split(":", maxsplit=1)
    module = importlib.import_module(module_name)

    assert callable(getattr(module, callable_name))


def test_declared_entrypoint_builds_a_nonempty_command_surface() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0, result.output
    assert "MaskFactory pipeline" in result.output
    assert "doctor" in result.output
    assert "models" in result.output


@pytest.mark.parametrize("command_name", sorted(main.commands))
def test_every_top_level_command_renders_help(command_name: str) -> None:
    result = CliRunner().invoke(main, [command_name, "--help"])

    assert result.exit_code == 0, result.output
