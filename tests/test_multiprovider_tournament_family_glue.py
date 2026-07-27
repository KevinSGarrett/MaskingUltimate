"""Glue: tournament CLIs must invoke configured local-CUDA families + SAM2."""

from __future__ import annotations

from pathlib import Path

import pytest

from maskfactory.autonomy.tournament_families import (
    REQUIRED_CORE_INVOCATION_KEYS,
    TournamentFamilyMapError,
    assert_cli_invokes_configured_families,
    family_map_as_dict,
    load_tournament_family_map,
    validate_runner_coverage,
)

REPO = Path(__file__).resolve().parents[1]
CLI_TOOLS = (
    REPO / "tools" / "run_multiprovider_gold_tournament.py",
    REPO / "tools" / "run_gold_volume_multiprovider_tournament.py",
)


def test_family_map_requires_three_local_cuda_plus_sam2() -> None:
    document = load_tournament_family_map()
    assert document.required_invocation_keys == REQUIRED_CORE_INVOCATION_KEYS
    assert "sam2_1_large" in document.required_invocation_keys
    assert document.gpu_sequence[-1] == "sam2_1_large"
    sam2 = document.by_invocation_key()["sam2_1_large"]
    assert sam2.runtime == "local_cuda"
    assert sam2.box_prior == "birefnet_general"
    assert sam2.runner == "sam2_local_cuda_runner"


def test_validate_runner_coverage_fails_closed_when_sam2_missing() -> None:
    with pytest.raises(TournamentFamilyMapError, match="sam2_1_large"):
        validate_runner_coverage(
            REQUIRED_CORE_INVOCATION_KEYS,
            {"birefnet_general", "schp_atr", "faceparse_bisenet"},
        )


def test_both_tournament_clis_invoke_configured_families() -> None:
    document = load_tournament_family_map()
    for cli_path in CLI_TOOLS:
        source = cli_path.read_text(encoding="utf-8")
        keys = assert_cli_invokes_configured_families(cli_source=source, family_map=document)
        assert keys == list(REQUIRED_CORE_INVOCATION_KEYS)
        assert "Sam2Runner" in source or "_run_sam2" in source
        assert "load_tournament_family_map" in source
        assert "validate_runner_coverage" in source
        # Must not leave SAM2 as docstring-only / optional nuclio reachability.
        assert "sam2_1_large" in source
        assert "box_prior" in source or "birefnet" in source.lower()


def test_cli_tools_listed_in_map_exist() -> None:
    document = load_tournament_family_map()
    for relative in document.cli_tools:
        assert (REPO / relative).is_file(), relative


def test_family_map_as_dict_is_sealable() -> None:
    payload = family_map_as_dict()
    assert payload["map_id"] == "multiprovider_tournament_families_v1"
    assert payload["required_invocation_keys"] == list(REQUIRED_CORE_INVOCATION_KEYS)
