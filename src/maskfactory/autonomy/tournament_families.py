"""Governed multi-provider tournament family invocation map.

Smokes that prove families are online do not mint gold. Tournament CLIs must
load this map and actually invoke every required family (including SAM2).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MAP_PATH = REPO_ROOT / "configs" / "multiprovider_tournament_families.yaml"

# Canonical 3 local-CUDA families + SAM2 that tournament CLIs must invoke.
REQUIRED_CORE_INVOCATION_KEYS = (
    "birefnet_general",
    "schp_atr",
    "faceparse_bisenet",
    "sam2_1_large",
)


class TournamentFamilyMapError(ValueError):
    """Tournament family invocation map is invalid or incomplete."""


@dataclass(frozen=True)
class TournamentFamilySpec:
    provider_key: str
    model_family: str
    role: str
    runtime: str
    required: bool
    invocation_key: str
    runner: str
    box_prior: str | None = None
    checkpoint: str | None = None
    oom_fallback_checkpoint: str | None = None
    source_path: str | None = None
    dependency_site: str | None = None


@dataclass(frozen=True)
class TournamentFamilyMap:
    path: Path
    schema_version: str
    map_id: str
    authority: str
    required_minimum_independent_families: int
    local_cuda_python: str
    families: tuple[TournamentFamilySpec, ...]
    cli_tools: tuple[str, ...]
    gpu_sequence: tuple[str, ...]

    @property
    def required_invocation_keys(self) -> tuple[str, ...]:
        return tuple(row.invocation_key for row in self.families if row.required)

    @property
    def all_invocation_keys(self) -> tuple[str, ...]:
        return tuple(row.invocation_key for row in self.families)

    def by_invocation_key(self) -> dict[str, TournamentFamilySpec]:
        return {row.invocation_key: row for row in self.families}


def load_tournament_family_map(
    path: Path | None = None,
) -> TournamentFamilyMap:
    """Load and validate the governed tournament family invocation map."""
    map_path = Path(path) if path is not None else DEFAULT_MAP_PATH
    try:
        document = yaml.safe_load(map_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TournamentFamilyMapError(f"cannot read family map: {map_path}") from exc
    if not isinstance(document, dict):
        raise TournamentFamilyMapError("family map root must be a mapping")
    families_raw = document.get("families")
    if not isinstance(families_raw, list) or not families_raw:
        raise TournamentFamilyMapError("families must be a non-empty list")
    families: list[TournamentFamilySpec] = []
    seen: set[str] = set()
    for index, row in enumerate(families_raw):
        if not isinstance(row, dict):
            raise TournamentFamilyMapError(f"families[{index}] must be a mapping")
        key = str(row.get("invocation_key") or row.get("provider_key") or "")
        if not key:
            raise TournamentFamilyMapError(f"families[{index}] missing invocation_key")
        if key in seen:
            raise TournamentFamilyMapError(f"duplicate invocation_key: {key}")
        seen.add(key)
        families.append(
            TournamentFamilySpec(
                provider_key=str(row["provider_key"]),
                model_family=str(row["model_family"]),
                role=str(row["role"]),
                runtime=str(row.get("runtime") or "local_cuda"),
                required=bool(row.get("required", True)),
                invocation_key=key,
                runner=str(row["runner"]),
                box_prior=(str(row["box_prior"]) if row.get("box_prior") else None),
                checkpoint=(str(row["checkpoint"]) if row.get("checkpoint") else None),
                oom_fallback_checkpoint=(
                    str(row["oom_fallback_checkpoint"])
                    if row.get("oom_fallback_checkpoint")
                    else None
                ),
                source_path=(str(row["source_path"]) if row.get("source_path") else None),
                dependency_site=(
                    str(row["dependency_site"]) if row.get("dependency_site") else None
                ),
            )
        )
    required = tuple(row.invocation_key for row in families if row.required)
    missing_core = [key for key in REQUIRED_CORE_INVOCATION_KEYS if key not in required]
    if missing_core:
        raise TournamentFamilyMapError(f"required core families missing from map: {missing_core}")
    cli_tools = document.get("cli_tools") or []
    gpu_sequence = document.get("gpu_sequence") or required
    if not isinstance(cli_tools, list) or not cli_tools:
        raise TournamentFamilyMapError("cli_tools must be a non-empty list")
    if not isinstance(gpu_sequence, list) or not gpu_sequence:
        raise TournamentFamilyMapError("gpu_sequence must be a non-empty list")
    for key in required:
        if key not in gpu_sequence:
            raise TournamentFamilyMapError(f"gpu_sequence missing required family: {key}")
    minimum = int(document.get("required_minimum_independent_families") or 3)
    if minimum < 3:
        raise TournamentFamilyMapError("required_minimum_independent_families must be >= 3")
    return TournamentFamilyMap(
        path=map_path.resolve(),
        schema_version=str(document.get("schema_version") or ""),
        map_id=str(document.get("map_id") or ""),
        authority=str(document.get("authority") or ""),
        required_minimum_independent_families=minimum,
        local_cuda_python=str(document.get("local_cuda_python") or ""),
        families=tuple(families),
        cli_tools=tuple(str(item) for item in cli_tools),
        gpu_sequence=tuple(str(item) for item in gpu_sequence),
    )


def validate_runner_coverage(
    configured_keys: tuple[str, ...] | list[str],
    implemented_keys: set[str] | frozenset[str] | tuple[str, ...] | list[str],
) -> None:
    """Fail closed when a configured required family has no tournament runner."""
    configured = tuple(configured_keys)
    implemented = set(implemented_keys)
    missing = [key for key in configured if key not in implemented]
    if missing:
        raise TournamentFamilyMapError(
            "tournament CLI does not invoke configured families: " + ", ".join(missing)
        )


def extract_string_keys_from_source(source: str) -> set[str]:
    """Extract string literals that look like family invocation keys (AST-safe)."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise TournamentFamilyMapError(f"CLI source is not valid Python: {exc}") from exc
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.add(node.value)
    # Also catch FAMILIES = (...) style without requiring runtime import.
    for match in re.finditer(
        r'["\'](birefnet_general|schp_atr|faceparse_bisenet|sam2_1_large|nuclio_pth_sam2)["\']',
        source,
    ):
        found.add(match.group(1))
    return found


def assert_cli_invokes_configured_families(
    *,
    cli_source: str,
    family_map: TournamentFamilyMap | None = None,
) -> list[str]:
    """Return required keys present in CLI source; raise if any required key is absent."""
    document = family_map or load_tournament_family_map()
    present = extract_string_keys_from_source(cli_source)
    validate_runner_coverage(document.required_invocation_keys, present)
    # SAM2 must be wired as a real runner, not only mentioned in a comment/docstring.
    if "sam2_1_large" in document.required_invocation_keys:
        if not re.search(
            r"(Sam2Runner|_run_sam2|sam2_local_cuda_runner|sam2_1_large)",
            cli_source,
        ):
            raise TournamentFamilyMapError(
                "CLI mentions sam2_1_large but lacks a SAM2 runner invocation symbol"
            )
        if "Sam2Runner" not in cli_source and "_run_sam2" not in cli_source:
            raise TournamentFamilyMapError(
                "CLI must define Sam2Runner or _run_sam2 to invoke local-CUDA SAM2"
            )
    return list(document.required_invocation_keys)


def family_map_as_dict(document: TournamentFamilyMap | None = None) -> dict[str, Any]:
    """Serialize the family map for seals / evidence."""
    loaded = document or load_tournament_family_map()
    return {
        "schema_version": loaded.schema_version,
        "map_id": loaded.map_id,
        "authority": loaded.authority,
        "path": str(loaded.path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "required_minimum_independent_families": loaded.required_minimum_independent_families,
        "required_invocation_keys": list(loaded.required_invocation_keys),
        "gpu_sequence": list(loaded.gpu_sequence),
        "cli_tools": list(loaded.cli_tools),
        "families": [
            {
                "provider_key": row.provider_key,
                "model_family": row.model_family,
                "role": row.role,
                "runtime": row.runtime,
                "required": row.required,
                "invocation_key": row.invocation_key,
                "runner": row.runner,
                "box_prior": row.box_prior,
            }
            for row in loaded.families
        ],
    }
