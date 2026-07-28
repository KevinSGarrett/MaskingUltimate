"""Fail-closed contract for the local multi-provider tournament family map."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FAMILY_MAP_PATH = REPOSITORY_ROOT / "configs/multiprovider_tournament_families.yaml"
REQUIRED_CORE_INVOCATION_KEYS = (
    "birefnet_general",
    "schp_atr",
    "faceparse_bisenet",
    "sam2_1_large",
)
_ROOT_KEYS = {
    "schema_version",
    "map_id",
    "authority",
    "required_minimum_independent_families",
    "local_cuda_python",
    "families",
    "cli_tools",
    "gpu_sequence",
    "claim_boundary",
}
_FAMILY_REQUIRED_KEYS = {
    "provider_key",
    "model_family",
    "role",
    "runtime",
    "required",
    "invocation_key",
    "runner",
}
_FAMILY_OPTIONAL_KEYS = {
    "box_prior",
    "checkpoint",
    "oom_fallback_checkpoint",
    "source_path",
    "dependency_site",
}


class TournamentFamilyMapError(ValueError):
    """Raised when a tournament map cannot prove its required local families."""


@dataclass(frozen=True)
class TournamentFamily:
    provider_key: str
    model_family: str
    role: str
    runtime: str
    required: bool
    invocation_key: str
    runner: str
    box_prior: str | None = None


@dataclass(frozen=True)
class TournamentFamilyMap:
    schema_version: str
    map_id: str
    authority: str
    required_minimum_independent_families: int
    local_cuda_python: str
    families: tuple[TournamentFamily, ...]
    cli_tools: tuple[str, ...]
    gpu_sequence: tuple[str, ...]

    @property
    def required_invocation_keys(self) -> tuple[str, ...]:
        return tuple(family.invocation_key for family in self.families if family.required)

    def by_invocation_key(self) -> dict[str, TournamentFamily]:
        return {family.invocation_key: family for family in self.families}


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise TournamentFamilyMapError(f"{field} must be a non-empty string")
    return value


def _relative_tool_path(value: object) -> str:
    path = _required_text(value, field="CLI tool path")
    if "\\" in path:
        raise TournamentFamilyMapError("CLI tool path must use POSIX separators")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or parsed.as_posix() != path:
        raise TournamentFamilyMapError("CLI tool path escapes the repository")
    return path


def _parse_family(raw: object) -> TournamentFamily:
    if not isinstance(raw, Mapping):
        raise TournamentFamilyMapError("family entry must be an object")
    keys = set(raw)
    if not _FAMILY_REQUIRED_KEYS.issubset(keys) or not keys <= (
        _FAMILY_REQUIRED_KEYS | _FAMILY_OPTIONAL_KEYS
    ):
        raise TournamentFamilyMapError("family entry has an invalid field set")
    required = raw["required"]
    if not isinstance(required, bool):
        raise TournamentFamilyMapError("family required flag must be boolean")
    box_prior = raw.get("box_prior")
    if box_prior is not None and not isinstance(box_prior, str):
        raise TournamentFamilyMapError("family box_prior must be a string when present")
    return TournamentFamily(
        provider_key=_required_text(raw["provider_key"], field="family provider_key"),
        model_family=_required_text(raw["model_family"], field="family model_family"),
        role=_required_text(raw["role"], field="family role"),
        runtime=_required_text(raw["runtime"], field="family runtime"),
        required=required,
        invocation_key=_required_text(raw["invocation_key"], field="family invocation_key"),
        runner=_required_text(raw["runner"], field="family runner"),
        box_prior=box_prior,
    )


def _validate_map(document: Mapping[str, Any]) -> TournamentFamilyMap:
    if set(document) != _ROOT_KEYS:
        raise TournamentFamilyMapError("family map has an invalid field set")
    families_raw = document["families"]
    if not isinstance(families_raw, list) or not families_raw:
        raise TournamentFamilyMapError("family map must contain families")
    families = tuple(_parse_family(raw) for raw in families_raw)
    keys = tuple(family.invocation_key for family in families)
    if len(keys) != len(set(keys)):
        raise TournamentFamilyMapError("family invocation keys must be unique")
    required_keys = tuple(family.invocation_key for family in families if family.required)
    if required_keys != REQUIRED_CORE_INVOCATION_KEYS:
        raise TournamentFamilyMapError(
            "required tournament family sequence must be "
            + ", ".join(REQUIRED_CORE_INVOCATION_KEYS)
        )
    sequence_raw = document["gpu_sequence"]
    if not isinstance(sequence_raw, list) or tuple(sequence_raw) != REQUIRED_CORE_INVOCATION_KEYS:
        raise TournamentFamilyMapError("GPU sequence must exactly match required family sequence")
    by_key = {family.invocation_key: family for family in families}
    if any(by_key[key].runtime != "local_cuda" for key in REQUIRED_CORE_INVOCATION_KEYS):
        raise TournamentFamilyMapError("required tournament families must use local_cuda")
    sam2 = by_key["sam2_1_large"]
    if sam2.runner != "sam2_local_cuda_runner" or sam2.box_prior != "birefnet_general":
        raise TournamentFamilyMapError("sam2_1_large must bind its local runner and BiRefNet prior")
    minimum = document["required_minimum_independent_families"]
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum != 3:
        raise TournamentFamilyMapError(
            "required minimum independent families must be exactly three"
        )
    cli_tools_raw = document["cli_tools"]
    if not isinstance(cli_tools_raw, list) or not cli_tools_raw:
        raise TournamentFamilyMapError("family map must bind CLI tools")
    cli_tools = tuple(_relative_tool_path(path) for path in cli_tools_raw)
    if len(cli_tools) != len(set(cli_tools)):
        raise TournamentFamilyMapError("CLI tool bindings must be unique")
    return TournamentFamilyMap(
        schema_version=_required_text(document["schema_version"], field="schema_version"),
        map_id=_required_text(document["map_id"], field="map_id"),
        authority=_required_text(document["authority"], field="authority"),
        required_minimum_independent_families=minimum,
        local_cuda_python=_required_text(document["local_cuda_python"], field="local_cuda_python"),
        families=families,
        cli_tools=cli_tools,
        gpu_sequence=tuple(sequence_raw),
    )


def load_tournament_family_map(path: Path = DEFAULT_FAMILY_MAP_PATH) -> TournamentFamilyMap:
    """Load the exact YAML family map without accepting malformed or partial policy."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise TournamentFamilyMapError("tournament family map is absent or not a regular file")
    try:
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise TournamentFamilyMapError("tournament family map is unreadable") from error
    if not isinstance(document, Mapping):
        raise TournamentFamilyMapError("tournament family map root must be an object")
    return _validate_map(document)


def validate_runner_coverage(
    required_invocation_keys: Iterable[str], available_runner_keys: Iterable[str]
) -> None:
    """Require a concrete runner for every map-required invocation key."""

    required = tuple(required_invocation_keys)
    if required != REQUIRED_CORE_INVOCATION_KEYS:
        raise TournamentFamilyMapError(
            "runner coverage must use the exact required family sequence"
        )
    available = set(available_runner_keys)
    missing = [key for key in required if key not in available]
    if missing:
        raise TournamentFamilyMapError(
            "required tournament runners are missing: " + ", ".join(missing)
        )


def assert_cli_invokes_configured_families(
    *, cli_source: str, family_map: TournamentFamilyMap
) -> list[str]:
    """Reject a CLI which omits any required family from its executable source."""

    if not isinstance(cli_source, str) or not cli_source:
        raise TournamentFamilyMapError("CLI source is absent")
    required = family_map.required_invocation_keys
    validate_runner_coverage(required, required)
    missing = [key for key in required if key not in cli_source]
    if missing:
        raise TournamentFamilyMapError(
            "CLI omits required tournament families: " + ", ".join(missing)
        )
    if (
        "load_tournament_family_map" not in cli_source
        or "validate_runner_coverage" not in cli_source
    ):
        raise TournamentFamilyMapError("CLI does not bind the governed tournament family map")
    return list(required)


def family_map_as_dict(path: Path = DEFAULT_FAMILY_MAP_PATH) -> dict[str, Any]:
    """Return only the serializable, policy-relevant map fields for receipts."""

    document = load_tournament_family_map(path)
    return {
        "schema_version": document.schema_version,
        "map_id": document.map_id,
        "authority": document.authority,
        "required_minimum_independent_families": document.required_minimum_independent_families,
        "required_invocation_keys": list(document.required_invocation_keys),
        "gpu_sequence": list(document.gpu_sequence),
        "cli_tools": list(document.cli_tools),
        "families": [
            {
                "provider_key": family.provider_key,
                "model_family": family.model_family,
                "role": family.role,
                "runtime": family.runtime,
                "required": family.required,
                "invocation_key": family.invocation_key,
                "runner": family.runner,
                "box_prior": family.box_prior,
            }
            for family in document.families
        ],
    }


__all__ = [
    "DEFAULT_FAMILY_MAP_PATH",
    "REQUIRED_CORE_INVOCATION_KEYS",
    "TournamentFamily",
    "TournamentFamilyMap",
    "TournamentFamilyMapError",
    "assert_cli_invokes_configured_families",
    "family_map_as_dict",
    "load_tournament_family_map",
    "validate_runner_coverage",
]
