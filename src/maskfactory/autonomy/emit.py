"""Canonical production emit path for autonomy lifecycle + corpus envelopes.

Tournament / S11 writers must land ``machine_verified_candidate`` sidecars under
``runs/**/autonomy/`` and write companion ``*.corpus_record.json`` envelopes whose
paths are relative to the **production** machine root (``runs/``) that
``build_autonomous_gold_admission`` and corpus assembly scan.

A common glue bug is writing envelopes with ``machine_root`` set to a tournament
subdirectory (e.g. ``runs/autonomous_gold_tournament_*/``), which makes
``machine_lifecycle_path`` look like ``img_xxx/autonomy/torso.json`` and fail to
resolve under ``runs/``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .corpus import (
    CORPUS_RECORD_SUFFIX,
    AutonomousCorpusError,
    build_corpus_record,
    corpus_record_from_decision,
    corpus_record_path_for_lifecycle,
    write_corpus_record_envelope,
)
from .lifecycle import write_lifecycle_sidecar
from .tournament import TournamentDecision

DEFAULT_MACHINE_ROOT_ENV = "MASKFACTORY_MACHINE_ROOT"
DEFAULT_MACHINE_ROOT_NAME = "runs"


class AutonomyEmitError(RuntimeError):
    """Lifecycle / corpus emit path cannot proceed honestly."""


def resolve_production_machine_root(
    machine_root: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> Path:
    """Resolve the production root admission scans (default: ``runs/``)."""
    if machine_root is not None:
        return Path(machine_root).resolve()
    env = os.environ.get(DEFAULT_MACHINE_ROOT_ENV)
    if env:
        return Path(env).resolve()
    if repo_root is not None:
        return (Path(repo_root) / DEFAULT_MACHINE_ROOT_NAME).resolve()
    return Path(DEFAULT_MACHINE_ROOT_NAME).resolve()


def ensure_lifecycle_under_machine_root(lifecycle_path: Path, machine_root: Path) -> Path:
    """Require the lifecycle sidecar to live under the production machine root."""
    root = Path(machine_root).resolve()
    path = Path(lifecycle_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise AutonomyEmitError(
            f"lifecycle sidecar escapes production machine_root: {path} not under {root}"
        ) from exc
    if "autonomy" not in path.parts:
        raise AutonomyEmitError(f"lifecycle sidecar must live under an autonomy/ directory: {path}")
    return path


def emit_lifecycle_and_corpus_record(
    lifecycle_path: Path,
    *,
    image_id: str,
    instance_id: str,
    pipeline_fingerprint: str,
    decision: TournamentDecision,
    machine_root: Path | str | None = None,
    risk_bucket: str | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Write lifecycle sidecar + corpus envelope rooted at production ``runs/``.

    Returns write-path metadata for evidence seals / tests.
    """
    root = resolve_production_machine_root(machine_root, repo_root=repo_root)
    lifecycle_path = Path(lifecycle_path)
    if not lifecycle_path.is_absolute():
        lifecycle_path = (root / lifecycle_path).resolve()
    else:
        lifecycle_path = lifecycle_path.resolve()
    ensure_lifecycle_under_machine_root(lifecycle_path, root)

    lifecycle = write_lifecycle_sidecar(
        lifecycle_path,
        image_id=image_id,
        instance_id=instance_id,
        pipeline_fingerprint=pipeline_fingerprint,
        decision=decision,
    )
    envelope = corpus_record_from_decision(
        lifecycle_path,
        machine_root=root,
        image_id=image_id,
        decision=decision,
        pipeline_fingerprint=pipeline_fingerprint,
        risk_bucket=risk_bucket,
    )
    envelope_path = (
        corpus_record_path_for_lifecycle(lifecycle_path) if envelope is not None else None
    )
    return {
        "machine_root": str(root),
        "lifecycle_path": str(lifecycle_path),
        "lifecycle_relpath": lifecycle_path.relative_to(root).as_posix(),
        "lifecycle_status": lifecycle.get("status"),
        "corpus_envelope_written": envelope is not None,
        "corpus_envelope_path": str(envelope_path) if envelope_path is not None else None,
        "corpus_envelope_relpath": (
            envelope_path.relative_to(root).as_posix() if envelope_path is not None else None
        ),
        "corpus_record": envelope,
    }


def repair_corpus_envelopes(
    machine_root: Path | str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Rewrite corpus envelopes so artifact paths resolve under ``machine_root``.

    Preserves independence / stability fields from the existing envelope when
    present; recomputes path/hash bindings from the sibling lifecycle sidecar.
    """
    root = Path(machine_root).resolve()
    repaired: list[str] = []
    already_ok: list[str] = []
    failed: list[dict[str, str]] = []
    if not root.is_dir():
        return {
            "machine_root": str(root),
            "repaired": 0,
            "already_ok": 0,
            "failed": 0,
            "dry_run": dry_run,
            "rows": [],
        }

    for envelope_path in sorted(root.rglob(f"*{CORPUS_RECORD_SUFFIX}")):
        try:
            old = json.loads(envelope_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failed.append({"path": str(envelope_path), "error": f"unreadable: {exc}"})
            continue
        lifecycle_name = envelope_path.name[: -len(CORPUS_RECORD_SUFFIX)] + ".json"
        lifecycle_path = envelope_path.with_name(lifecycle_name)
        if not lifecycle_path.is_file():
            failed.append(
                {
                    "path": str(envelope_path),
                    "error": f"missing sibling lifecycle {lifecycle_name}",
                }
            )
            continue
        try:
            ensure_lifecycle_under_machine_root(lifecycle_path, root)
            old_life = root / str(old.get("machine_lifecycle_path", ""))
            old_mask = root / str(old.get("machine_mask_path", ""))
            if old_life.is_file() and old_mask.is_file():
                already_ok.append(lifecycle_path.relative_to(root).as_posix())
                continue
            record = build_corpus_record(
                lifecycle_path=lifecycle_path,
                machine_root=root,
                image_id=str(old["image_id"]),
                label=str(old["label"]),
                context=str(old["context"]),
                pipeline_fingerprint=str(old["pipeline_fingerprint"]),
                risk_bucket=old.get("risk_bucket"),
                independent_family_count=int(old["independent_family_count"]),
                cross_family_disagreement=bool(old["cross_family_disagreement"]),
                serious_cross_family_disagreement=bool(old["serious_cross_family_disagreement"]),
                candidate_stability_pass=bool(old["candidate_stability_pass"]),
                perturbation_stability_pass=bool(old["perturbation_stability_pass"]),
                complete_map_hard_veto_pass=bool(old["complete_map_hard_veto_pass"]),
                machine_accepted=bool(old.get("machine_accepted", True)),
            )
        except (AutonomousCorpusError, AutonomyEmitError, KeyError, TypeError, ValueError) as exc:
            failed.append({"path": str(envelope_path), "error": str(exc)})
            continue
        if not dry_run:
            write_corpus_record_envelope(
                lifecycle_path,
                machine_root=root,
                image_id=str(record["image_id"]),
                label=str(record["label"]),
                context=str(record["context"]),
                pipeline_fingerprint=str(record["pipeline_fingerprint"]),
                risk_bucket=record.get("risk_bucket"),
                independent_family_count=int(record["independent_family_count"]),
                cross_family_disagreement=bool(record["cross_family_disagreement"]),
                serious_cross_family_disagreement=bool(record["serious_cross_family_disagreement"]),
                candidate_stability_pass=bool(record["candidate_stability_pass"]),
                perturbation_stability_pass=bool(record["perturbation_stability_pass"]),
                complete_map_hard_veto_pass=bool(record["complete_map_hard_veto_pass"]),
                machine_accepted=bool(record.get("machine_accepted", True)),
            )
        repaired.append(record["machine_lifecycle_path"])

    return {
        "machine_root": str(root),
        "repaired": len(repaired),
        "already_ok": len(already_ok),
        "failed": len(failed),
        "dry_run": dry_run,
        "repaired_lifecycle_paths": repaired,
        "already_ok_lifecycle_paths": already_ok,
        "failures": failed,
    }


__all__ = [
    "AutonomyEmitError",
    "DEFAULT_MACHINE_ROOT_ENV",
    "DEFAULT_MACHINE_ROOT_NAME",
    "emit_lifecycle_and_corpus_record",
    "ensure_lifecycle_under_machine_root",
    "repair_corpus_envelopes",
    "resolve_production_machine_root",
]
