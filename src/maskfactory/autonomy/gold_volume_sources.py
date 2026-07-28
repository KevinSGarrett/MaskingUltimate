"""Read-when-present gold-volume source path map for tournament input selection.

Probes configured candidate roots for MaskedWarehouse, the reference library, and
DAZ — including optional removable F: USB paths when the drive is present —
and selects the first readable candidate per role.

Honesty / safety boundaries (fail-closed):
  * Read-when-present only. Never creates junctions, never relocates trees.
  * Never junctions critical runtime (data/, models/, Docker VHDX, live WSL) onto
    removable USB media.
  * External / reference / DAZ corpora remain tournament *inputs*; this module
    never marks them MaskFactory gold and never force-registers a champion.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

GOLD_VOLUME_SOURCES_SCHEMA = "1.0.0"
GOLD_VOLUME_SOURCES_MAP_ID = "maskfactory-gold-volume-sources-read-when-present-v1"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "gold_volume_sources.yaml"

REQUIRED_CLAIM_BOUNDARY = {
    "read_when_present_only": True,
    "never_junction_critical_runtime_to_usb": True,
    "never_relocate_data_models_docker_to_removable": True,
    "never_treat_external_labels_as_gold": True,
    "never_force_register_champion": True,
    "inputs_only": True,
}


class GoldVolumeSourcesError(RuntimeError):
    """The gold-volume source map config is invalid or unusable."""


@dataclass(frozen=True)
class CandidateProbe:
    path: Path
    media: str
    priority: int
    present: bool
    readable: bool
    markers_ok: bool
    missing_markers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "media": self.media,
            "priority": self.priority,
            "present": self.present,
            "readable": self.readable,
            "markers_ok": self.markers_ok,
            "missing_markers": list(self.missing_markers),
        }


@dataclass(frozen=True)
class SourceSelection:
    role: str
    description: str
    selected_root: Path | None
    selected_media: str | None
    present: bool
    candidates: tuple[CandidateProbe, ...]
    dataset_hints_present: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "description": self.description,
            "selected_root": str(self.selected_root) if self.selected_root else None,
            "selected_media": self.selected_media,
            "present": self.present,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "dataset_hints_present": list(self.dataset_hints_present),
        }


@dataclass(frozen=True)
class GoldVolumeProbeResult:
    """Immutable probe of the gold-volume path map."""

    schema_version: str
    map_id: str
    claim_boundary: Mapping[str, Any]
    removable_drive_letters_present: tuple[str, ...]
    sources: Mapping[str, SourceSelection]
    any_source_present: bool
    all_primary_sources_present: bool
    junction_critical_runtime_to_usb: bool

    def selected_roots(self) -> dict[str, Path]:
        return {
            name: selection.selected_root
            for name, selection in self.sources.items()
            if selection.selected_root is not None
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "map_id": self.map_id,
            "claim_boundary": dict(self.claim_boundary),
            "removable_drive_letters_present": list(self.removable_drive_letters_present),
            "sources": {name: selection.to_dict() for name, selection in self.sources.items()},
            "any_source_present": self.any_source_present,
            "all_primary_sources_present": self.all_primary_sources_present,
            "junction_critical_runtime_to_usb": self.junction_critical_runtime_to_usb,
            "selected_roots": {
                name: str(path) for name, path in sorted(self.selected_roots().items())
            },
        }


def load_gold_volume_source_map(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try:
        document = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GoldVolumeSourcesError(f"gold volume source map unreadable: {config_path}") from exc
    if not isinstance(document, dict):
        raise GoldVolumeSourcesError("gold volume source map must be a mapping")
    if document.get("schema_version") != GOLD_VOLUME_SOURCES_SCHEMA:
        raise GoldVolumeSourcesError("gold volume source map schema is invalid")
    if document.get("map_id") != GOLD_VOLUME_SOURCES_MAP_ID:
        raise GoldVolumeSourcesError("gold volume source map id is invalid")
    boundary = document.get("claim_boundary")
    if not isinstance(boundary, dict) or any(
        boundary.get(flag) is not expected for flag, expected in REQUIRED_CLAIM_BOUNDARY.items()
    ):
        raise GoldVolumeSourcesError("gold volume source map claim_boundary is not honest")
    sources = document.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise GoldVolumeSourcesError("gold volume source map sources are missing")
    for name, entry in sources.items():
        if not isinstance(entry, dict):
            raise GoldVolumeSourcesError(f"source {name!r} must be a mapping")
        candidates = entry.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise GoldVolumeSourcesError(f"source {name!r} has no candidates")
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise GoldVolumeSourcesError(f"source {name!r} candidate must be a mapping")
            if not isinstance(candidate.get("path"), str) or not candidate["path"].strip():
                raise GoldVolumeSourcesError(f"source {name!r} candidate path is empty")
            if candidate.get("media") not in {"fixed_local", "removable_usb"}:
                raise GoldVolumeSourcesError(f"source {name!r} candidate media is invalid")
            if not isinstance(candidate.get("priority"), int):
                raise GoldVolumeSourcesError(f"source {name!r} candidate priority must be int")
    return document


def _drive_letter_present(letter: str) -> bool:
    root = Path(f"{letter}:/")
    try:
        return root.exists()
    except OSError:
        return False


def _probe_candidate(
    candidate: Mapping[str, Any],
    *,
    required_child_any: tuple[str, ...],
) -> CandidateProbe:
    path = Path(candidate["path"])
    present = False
    readable = False
    markers_ok = False
    missing: list[str] = []
    try:
        present = path.exists() and path.is_dir()
        if present:
            # Directory listing is a cheap readability check without deep walks.
            found = {child.name for child in path.iterdir()}
            readable = True
            if required_child_any:
                missing = [name for name in required_child_any if name not in found]
                # required_child_any: succeed when at least one marker child exists.
                markers_ok = len(missing) < len(required_child_any)
            else:
                markers_ok = True
    except OSError:
        present = False
        readable = False
        markers_ok = False
        missing = list(required_child_any)
    return CandidateProbe(
        path=path,
        media=str(candidate["media"]),
        priority=int(candidate["priority"]),
        present=bool(present),
        readable=bool(readable),
        markers_ok=bool(markers_ok),
        missing_markers=tuple(missing),
    )


def _hint_presence(root: Path | None, hints: list[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    if root is None:
        return ()
    present_hints: list[dict[str, Any]] = []
    for hint in hints:
        relative = hint.get("relative")
        if not isinstance(relative, str) or not relative:
            continue
        target = root.joinpath(*Path(relative).parts)
        try:
            exists = target.exists()
        except OSError:
            exists = False
        present_hints.append(
            {
                "relative": relative,
                "use": hint.get("use"),
                "path": str(target),
                "present": exists,
            }
        )
    return tuple(present_hints)


def probe_gold_volume_sources(
    config_path: str | Path | None = None,
    *,
    config: Mapping[str, Any] | None = None,
) -> GoldVolumeProbeResult:
    """Probe configured candidates and select present roots (read-only)."""
    document = dict(config) if config is not None else load_gold_volume_source_map(config_path)
    removable_letters = tuple(letter for letter in ("F",) if _drive_letter_present(letter))
    dataset_hints = document.get("dataset_hints") or {}
    if not isinstance(dataset_hints, dict):
        raise GoldVolumeSourcesError("dataset_hints must be a mapping")

    sources: dict[str, SourceSelection] = {}
    for name, entry in document["sources"].items():
        required = entry.get("required_child_any") or []
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            raise GoldVolumeSourcesError(f"source {name!r} required_child_any is invalid")
        required_tuple = tuple(required)
        probes = tuple(
            _probe_candidate(candidate, required_child_any=required_tuple)
            for candidate in sorted(entry["candidates"], key=lambda item: int(item["priority"]))
        )
        selected: CandidateProbe | None = None
        for probe in probes:
            if probe.present and probe.readable and probe.markers_ok:
                selected = probe
                break
        hints = dataset_hints.get(name) or []
        if not isinstance(hints, list):
            raise GoldVolumeSourcesError(f"dataset_hints[{name!r}] must be a list")
        sources[name] = SourceSelection(
            role=str(entry.get("role") or name),
            description=str(entry.get("description") or ""),
            selected_root=selected.path if selected else None,
            selected_media=selected.media if selected else None,
            present=selected is not None,
            candidates=probes,
            dataset_hints_present=_hint_presence(selected.path if selected else None, hints),
        )

    return GoldVolumeProbeResult(
        schema_version=str(document["schema_version"]),
        map_id=str(document["map_id"]),
        claim_boundary=dict(document["claim_boundary"]),
        removable_drive_letters_present=removable_letters,
        sources=sources,
        any_source_present=any(selection.present for selection in sources.values()),
        all_primary_sources_present=all(
            sources[name].present
            for name in ("maskedwarehouse", "reference_library", "daz")
            if name in sources
        ),
        junction_critical_runtime_to_usb=False,
    )


def select_tournament_input_roots(
    config_path: str | Path | None = None,
    *,
    config: Mapping[str, Any] | None = None,
    require_all: bool = False,
) -> dict[str, Path]:
    """Return present gold-volume roots for tournament input selection.

    Missing removable roots are omitted (read-when-present). When
    ``require_all`` is True and any primary source is absent, raise.
    """
    probe = probe_gold_volume_sources(config_path, config=config)
    if require_all and not probe.all_primary_sources_present:
        missing = [name for name, selection in probe.sources.items() if not selection.present]
        raise GoldVolumeSourcesError(
            "required gold-volume tournament inputs missing: " + ", ".join(missing)
        )
    return probe.selected_roots()


def resolve_tournament_source_root(
    source_name: str,
    *,
    relative: str | None = None,
    config_path: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
) -> Path | None:
    """Resolve a present source root (optionally with a relative child)."""
    roots = select_tournament_input_roots(config_path, config=config)
    root = roots.get(source_name)
    if root is None:
        return None
    if relative is None:
        return root
    target = root.joinpath(*Path(relative).parts)
    try:
        return target if target.exists() else None
    except OSError:
        return None


def default_maskedwarehouse_lv_mhp_root(
    config_path: str | Path | None = None,
) -> Path:
    """Preferred LV-MHP root for multi-person tournament slices (read-when-present)."""
    resolved = resolve_tournament_source_root(
        "maskedwarehouse",
        relative="Body/LV-MHP-v1",
        config_path=config_path,
    )
    if resolved is not None:
        return resolved
    return Path(r"C:\Comfy_UI_Main\MaskedWarehouse\Body\LV-MHP-v1")


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "GOLD_VOLUME_SOURCES_MAP_ID",
    "GOLD_VOLUME_SOURCES_SCHEMA",
    "CandidateProbe",
    "GoldVolumeProbeResult",
    "GoldVolumeSourcesError",
    "SourceSelection",
    "default_maskedwarehouse_lv_mhp_root",
    "load_gold_volume_source_map",
    "probe_gold_volume_sources",
    "resolve_tournament_source_root",
    "select_tournament_input_roots",
]
