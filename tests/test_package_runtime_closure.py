from __future__ import annotations

import importlib
import re
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _require_build_backend_contract(
    project: dict, requirements_lock: str, environment_lock: str
) -> None:
    """Keep every clean-build backend pin aligned with the runtime contracts."""

    expected = {"setuptools": "78.1.0", "wheel": "0.47.0"}
    build_requires = project["build-system"]["requires"]
    assert build_requires == [f"{name}=={version}" for name, version in expected.items()]
    matches = list(
        re.finditer(
            r"^(?P<name>setuptools|wheel)==(?P<version>[^\r\n]+)$",
            requirements_lock,
            flags=re.MULTILINE,
        )
    )
    assert len(matches) == len(expected)
    locked = {match.group("name"): match.group("version") for match in matches}
    assert locked == expected
    assert re.search(r"^  - wheel=0\.47\.0=", environment_lock, flags=re.MULTILINE)
    assert re.search(r"^      - setuptools==78\.1\.0$", environment_lock, flags=re.MULTILINE)


def test_pyproject_declares_the_live_maskfactory_entrypoint() -> None:
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)

    entrypoint = project["project"]["scripts"]["maskfactory"]
    module_name, callable_name = entrypoint.split(":", maxsplit=1)
    module = importlib.import_module(module_name)

    assert callable(getattr(module, callable_name))


def test_clean_build_backend_pins_match_both_runtime_locks() -> None:
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)
    _require_build_backend_contract(
        project,
        (REPOSITORY_ROOT / "env/requirements.lock.txt").read_text(encoding="utf-8"),
        (REPOSITORY_ROOT / "env/maskfactory_env.yml").read_text(encoding="utf-8"),
    )


def test_clean_build_backend_contract_rejects_open_or_drifted_pins() -> None:
    project = {"build-system": {"requires": ["setuptools>=68", "wheel==0.47.0"]}}
    requirements_lock = "setuptools==78.1.0\nwheel==0.47.0\n"
    environment_lock = "  - wheel=0.47.0=build\n      - setuptools==78.1.0\n"

    with pytest.raises(AssertionError):
        _require_build_backend_contract(project, requirements_lock, environment_lock)


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
