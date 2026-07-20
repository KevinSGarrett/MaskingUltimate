"""Read-only gold-volume tournament input path map.

Resolves MaskedWarehouse / reference / DAZ roots from
``configs/gold_volume_tournament_inputs.yaml`` and probes presence without
writing into those corpora. Container consumers prefer the ``/gold/*`` mounts
wired by ``docker/compose.gpu.yml``; host consumers use the absolute Windows
roots.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MAP_PATH = REPO_ROOT / "configs" / "gold_volume_tournament_inputs.yaml"

VOLUME_KEYS = ("maskedwarehouse", "reference", "daz")


class GoldVolumePathError(ValueError):
    """Gold-volume path map is missing, incoherent, or not read-only."""


@dataclass(frozen=True)
class GoldVolumeRoots:
    maskedwarehouse: Path
    reference: Path
    daz: Path
    map_path: Path
    access_mode: str
    using_container_roots: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "maskedwarehouse": str(self.maskedwarehouse),
            "reference": str(self.reference),
            "daz": str(self.daz),
            "map_path": str(self.map_path),
            "access_mode": self.access_mode,
            "using_container_roots": self.using_container_roots,
        }


def load_gold_volume_map(path: Path | None = None) -> dict[str, Any]:
    map_path = Path(path) if path is not None else DEFAULT_MAP_PATH
    raw = yaml.safe_load(map_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise GoldVolumePathError("gold volume map must be a mapping")
    if str(raw.get("access_mode")) != "read_only":
        raise GoldVolumePathError("gold volume map access_mode must be read_only")
    volumes = raw.get("volumes")
    if not isinstance(volumes, Mapping) or set(VOLUME_KEYS) - set(volumes):
        raise GoldVolumePathError(
            "gold volume map must declare maskedwarehouse, reference, and daz volumes"
        )
    for key in VOLUME_KEYS:
        entry = volumes[key]
        if not isinstance(entry, Mapping):
            raise GoldVolumePathError(f"volume {key} must be a mapping")
        if str(entry.get("mount_mode")) != "ro":
            raise GoldVolumePathError(f"volume {key} mount_mode must be ro")
        if not entry.get("host_root") or not entry.get("container_root"):
            raise GoldVolumePathError(f"volume {key} requires host_root and container_root")
    return dict(raw)


def _prefer_container() -> bool:
    runtime = os.environ.get("MASKFACTORY_CONTAINER_RUNTIME", "").strip()
    if runtime:
        return True
    return Path("/gold/maskedwarehouse").is_dir() and Path("/gold/reference").is_dir()


def resolve_gold_volume_roots(path: Path | None = None) -> GoldVolumeRoots:
    document = load_gold_volume_map(path)
    volumes = document["volumes"]
    map_path = Path(path) if path is not None else DEFAULT_MAP_PATH
    use_container = _prefer_container()
    if use_container:
        mw = Path(
            os.environ.get(
                "MASKFACTORY_GOLD_MASKEDWAREHOUSE",
                str(volumes["maskedwarehouse"]["container_root"]),
            )
        )
        ref = Path(
            os.environ.get(
                "MASKFACTORY_GOLD_REFERENCE",
                str(volumes["reference"]["container_root"]),
            )
        )
        daz = Path(
            os.environ.get(
                "MASKFACTORY_GOLD_DAZ",
                str(volumes["daz"]["container_root"]),
            )
        )
    else:
        mw = Path(str(volumes["maskedwarehouse"]["host_root"]))
        ref = Path(str(volumes["reference"]["host_root"]))
        daz = Path(str(volumes["daz"]["host_root"]))
    return GoldVolumeRoots(
        maskedwarehouse=mw,
        reference=ref,
        daz=daz,
        map_path=map_path.resolve(),
        access_mode=str(document["access_mode"]),
        using_container_roots=use_container,
    )


def probe_gold_volume_paths(path: Path | None = None) -> dict[str, Any]:
    """Read-only presence probe of the configured gold-volume roots."""
    document = load_gold_volume_map(path)
    roots = resolve_gold_volume_roots(path)
    volumes = document["volumes"]

    def _probe_path(label: str, candidate: Path) -> dict[str, Any]:
        exists = candidate.exists()
        is_dir = candidate.is_dir() if exists else False
        readable = False
        child_count: int | None = None
        if is_dir:
            try:
                children = list(candidate.iterdir())
                child_count = len(children)
                readable = True
            except OSError as exc:
                readable = False
                child_count = None
                return {
                    "label": label,
                    "path": str(candidate),
                    "exists": exists,
                    "is_dir": is_dir,
                    "readable": readable,
                    "child_count": child_count,
                    "error": str(exc),
                }
        return {
            "label": label,
            "path": str(candidate),
            "exists": exists,
            "is_dir": is_dir,
            "readable": readable,
            "child_count": child_count,
        }

    dataset_probes = []
    for name, dataset_path in sorted(volumes["maskedwarehouse"].get("datasets", {}).items()):
        dataset_probes.append(
            _probe_path(f"maskedwarehouse.datasets.{name}", Path(str(dataset_path)))
        )

    daz_sub = []
    for name, sub_path in sorted(volumes["daz"].get("tournament_subroots", {}).items()):
        daz_sub.append(_probe_path(f"daz.tournament_subroots.{name}", Path(str(sub_path))))

    identity_path = Path(str(volumes["daz"].get("root_identity", "")))
    registry_path = Path(str(volumes["daz"].get("path_registry", "")))
    ref_db = Path(str(volumes["reference"].get("database", "")))

    probes = {
        "maskedwarehouse_root": _probe_path("maskedwarehouse", roots.maskedwarehouse),
        "reference_root": _probe_path("reference", roots.reference),
        "daz_root": _probe_path("daz", roots.daz),
        "reference_database": {
            "path": str(ref_db),
            "exists": ref_db.is_file(),
            "readable": ref_db.is_file(),
        },
        "daz_root_identity": {
            "path": str(identity_path),
            "exists": identity_path.is_file(),
            "readable": identity_path.is_file(),
        },
        "daz_path_registry": {
            "path": str(registry_path),
            "exists": registry_path.is_file(),
            "readable": registry_path.is_file(),
        },
        "maskedwarehouse_datasets": dataset_probes,
        "daz_tournament_subroots": daz_sub,
    }

    required_ok = all(
        probes[key]["exists"] and probes[key].get("is_dir", probes[key].get("readable"))
        for key in ("maskedwarehouse_root", "reference_root", "daz_root")
    )
    return {
        "map_id": document.get("map_id"),
        "access_mode": document.get("access_mode"),
        "roots": roots.as_dict(),
        "f_drive_present": Path("F:/").exists(),
        "required_roots_present": required_ok,
        "probes": probes,
        "compose_bind_mounts": document.get("compose_bind_mounts", []),
        "container_env": document.get("container_env", {}),
        "claim_boundary": document.get("claim_boundary", {}),
    }


__all__ = [
    "DEFAULT_MAP_PATH",
    "GoldVolumePathError",
    "GoldVolumeRoots",
    "load_gold_volume_map",
    "probe_gold_volume_paths",
    "resolve_gold_volume_roots",
]
