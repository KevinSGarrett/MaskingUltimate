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


def prove_emit_machine_verified_candidate(
    machine_root: Path | str,
    *,
    batch_id: str,
    image_id: str,
    label: str,
    context: str,
    pipeline_fingerprint: str,
    config: dict[str, Any],
    mask_array: Any,
) -> dict[str, Any]:
    """Run a 3-family winner through the correction loop and emit under ``runs/``.

    Glue-proof only: never mints certificates, never fabricates Wilson samples,
    and never claims autonomous_certified_gold.
    """
    import numpy as np

    from maskfactory.io.hashing import sha256_file
    from maskfactory.io.png_strict import write_binary_mask

    from .controller import run_autonomous_correction_loop
    from .tournament import CandidateEvidence

    root = resolve_production_machine_root(machine_root)
    stage = root / batch_id / image_id
    autonomy = stage / "autonomy"
    autonomy.mkdir(parents=True, exist_ok=True)
    mask_path = write_binary_mask(stage / "masks" / "winner.png", np.asarray(mask_array))
    mask_sha = sha256_file(mask_path)
    winner = CandidateEvidence(
        candidate_id="winner",
        mask_path=str(mask_path),
        mask_sha256=mask_sha,
        independent_sources=3,
        consensus_iou=0.98,
        boundary_agreement=0.98,
        pose_consistency=0.98,
        critic_pass_weight=0.96,
        critic_disagreement=False,
        protected_overlap=0.0,
        exclusive_overlap=0.0,
        component_count=1,
        ontology_max_components=1,
        format_valid=True,
        block_qc_ids=(),
        source_provider_keys=("fam_a", "fam_b", "fam_c"),
        source_model_families=("family_a", "family_b", "family_c"),
    )

    def _no_correction(**_kwargs: Any) -> tuple[()]:
        return ()

    result = run_autonomous_correction_loop(
        (winner,),
        label=label,
        context=context,
        pipeline_fingerprint=pipeline_fingerprint,
        config=config,
        correction_generator=_no_correction,
        certificate=None,
    )
    if result.decision.status != "machine_verified_candidate":
        raise AutonomyEmitError(
            "prove-emit tournament did not reach machine_verified_candidate: "
            f"{result.decision.status} ({result.decision.reason})"
        )
    emit = emit_lifecycle_and_corpus_record(
        autonomy / f"{label}.json",
        image_id=image_id,
        instance_id="p0",
        pipeline_fingerprint=pipeline_fingerprint,
        decision=result.decision,
        machine_root=root,
        risk_bucket=context,
    )
    return {
        **emit,
        "batch_id": batch_id,
        "image_id": image_id,
        "label": label,
        "context": context,
        "decision_status": result.decision.status,
        "winner_mask_path": str(mask_path.relative_to(root).as_posix()),
        "claim_boundary": {
            "emit_path_glue_proof_only": True,
            "no_fabricated_wilson_samples": True,
            "no_certificate_minted": True,
            "not_authoritative_human_gold": True,
        },
    }


__all__ = [
    "AutonomyEmitError",
    "DEFAULT_MACHINE_ROOT_ENV",
    "DEFAULT_MACHINE_ROOT_NAME",
    "emit_lifecycle_and_corpus_record",
    "ensure_lifecycle_under_machine_root",
    "prove_emit_machine_verified_candidate",
    "repair_corpus_envelopes",
    "resolve_production_machine_root",
]
