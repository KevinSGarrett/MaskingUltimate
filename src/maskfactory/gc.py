"""Conservative garbage collection for explicitly deprecated mask versions."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


class GarbageCollectionError(RuntimeError):
    """A GC plan cannot be proven safe or changed after review."""


@dataclass(frozen=True)
class GcCandidate:
    package_root: str
    relative_path: str
    version: int
    retain_until: str
    bytes: int


@dataclass(frozen=True)
class GcPlan:
    generated_at: str
    candidates: tuple[GcCandidate, ...]
    protected_count: int
    plan_hash: str


def build_gc_plan(packages_root: Path, *, now: datetime | None = None) -> GcPlan:
    """List expired deprecated versions with a gold successor and no manifest reference."""
    reference_time = (now or datetime.now(UTC)).astimezone(UTC)
    candidates = []
    protected = 0
    for registry_path in sorted(Path(packages_root).rglob("mask_versions.json")):
        package = registry_path.parent
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        active = str(registry.get("active_version"))
        active_entry = registry.get("versions", {}).get(active, {})
        if (
            active_entry.get("status") != "human_approved_gold"
            or active_entry.get("directory") != "masks"
        ):
            protected += 1
            continue
        manifest_refs = _manifest_references(package)
        for raw_version, entry in sorted(
            registry.get("versions", {}).items(), key=lambda item: int(item[0])
        ):
            if entry.get("status") != "deprecated":
                continue
            directory = str(entry.get("directory", ""))
            target = package / directory
            try:
                version = int(raw_version)
                retain_until = datetime.fromisoformat(
                    str(entry["retain_until"]).replace("Z", "+00:00")
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise GarbageCollectionError(
                    f"invalid deprecated version metadata: {registry_path}"
                ) from exc
            safe_name = (
                directory == f"masks@v{version}" and target.parent.resolve() == package.resolve()
            )
            referenced = any(
                ref == directory or ref.startswith(directory + "/") for ref in manifest_refs
            )
            if (
                not safe_name
                or not target.is_dir()
                or version == int(active)
                or retain_until.astimezone(UTC) > reference_time
                or referenced
            ):
                protected += 1
                continue
            candidates.append(
                GcCandidate(
                    str(package.resolve()),
                    directory,
                    version,
                    retain_until.astimezone(UTC).isoformat(),
                    _tree_bytes(target),
                )
            )
    payload = [asdict(candidate) for candidate in candidates]
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return GcPlan(reference_time.isoformat(), tuple(candidates), protected, digest)


def apply_gc_plan(plan: GcPlan, *, packages_root: Path) -> tuple[Path, ...]:
    """Delete exactly reviewed candidates after recomputing and matching the plan hash."""
    recomputed = build_gc_plan(packages_root, now=datetime.fromisoformat(plan.generated_at))
    if recomputed.plan_hash != plan.plan_hash or recomputed.candidates != plan.candidates:
        raise GarbageCollectionError("GC candidates changed after plan review; rerun dry-run")
    removed = []
    root = Path(packages_root).resolve()
    for candidate in plan.candidates:
        package = Path(candidate.package_root).resolve()
        target = (package / candidate.relative_path).resolve()
        if root not in target.parents or target.parent != package or not target.is_dir():
            raise GarbageCollectionError(f"GC target escaped or changed: {target}")
        shutil.rmtree(target)
        removed.append(target)
    return tuple(removed)


def write_gc_log(
    path: Path, plan: GcPlan, *, applied: bool, removed: tuple[Path, ...] = ()
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"generated_at={plan.generated_at}",
        f"plan_hash={plan.plan_hash}",
        f"mode={'apply' if applied else 'dry-run'}",
        f"candidates={len(plan.candidates)}",
        f"protected={plan.protected_count}",
    ]
    for candidate in plan.candidates:
        target = Path(candidate.package_root) / candidate.relative_path
        action = "REMOVED" if target in removed else "WOULD_REMOVE"
        lines.append(
            f"{action} {target} version={candidate.version} bytes={candidate.bytes} "
            f"retain_until={candidate.retain_until}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _manifest_references(package: Path) -> frozenset[str]:
    path = package / "manifest.json"
    if not path.is_file():
        return frozenset()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    files = manifest.get("files", {})
    return frozenset(str(value).replace("\\", "/") for value in files if isinstance(value, str))


def _tree_bytes(path: Path) -> int:
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())
