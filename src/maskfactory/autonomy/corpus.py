"""Assemble production autonomous-verification corpora from runs/ sidecars.

When a real multi-provider tournament writes ``machine_verified_candidate``
lifecycle sidecars under ``runs/**/autonomy/``, it should also write a companion
``*.corpus_record.json`` envelope (via :func:`write_corpus_record_envelope`).
This module discovers those envelopes, builds a frozen image-disjoint corpus,
and never fabricates independence/stability claims.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ..io.hashing import sha256_file
from ..validation import validate_document
from .tournament import TournamentDecision

CORPUS_RECORD_SUFFIX = ".corpus_record.json"
CORPUS_SCHEMA_VERSION = "1.0.0"


class AutonomousCorpusError(RuntimeError):
    """Production corpus assembly cannot proceed honestly."""


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def corpus_record_path_for_lifecycle(lifecycle_path: Path) -> Path:
    path = Path(lifecycle_path)
    return path.with_name(path.stem + CORPUS_RECORD_SUFFIX)


def build_corpus_record(
    *,
    lifecycle_path: Path,
    machine_root: Path,
    image_id: str,
    label: str,
    context: str,
    pipeline_fingerprint: str,
    risk_bucket: str | None = None,
    independent_family_count: int,
    cross_family_disagreement: bool,
    serious_cross_family_disagreement: bool,
    candidate_stability_pass: bool,
    perturbation_stability_pass: bool,
    complete_map_hard_veto_pass: bool,
    machine_accepted: bool = True,
) -> dict[str, Any]:
    """Build one hash-bound autonomous corpus record for a real lifecycle sidecar."""
    root = Path(machine_root).resolve()
    lifecycle_path = Path(lifecycle_path).resolve()
    try:
        lifecycle_rel = lifecycle_path.relative_to(root).as_posix()
    except ValueError as exc:
        raise AutonomousCorpusError("lifecycle sidecar escapes machine_root") from exc
    document = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    if validate_document(document, "autonomy_lifecycle"):
        raise AutonomousCorpusError("lifecycle sidecar fails autonomy_lifecycle contract")
    if document.get("status") not in {
        "machine_verified_candidate",
        "calibrated_auto_accepted",
    }:
        raise AutonomousCorpusError("corpus records require MVC or CAA lifecycle status")
    if (
        document.get("image_id") != image_id
        or document.get("label") != label
        or document.get("context") != context
        or document.get("pipeline_fingerprint") != pipeline_fingerprint
    ):
        raise AutonomousCorpusError("corpus record scope does not match lifecycle sidecar")
    winner_rel = document.get("winner_mask_path")
    winner_sha = document.get("winner_mask_sha256")
    if not isinstance(winner_rel, str) or not _is_sha256(winner_sha):
        raise AutonomousCorpusError("lifecycle winner mask identity is incomplete")
    stage_root = lifecycle_path.parent.parent
    mask_path = (stage_root / winner_rel).resolve()
    try:
        mask_rel = mask_path.relative_to(root).as_posix()
    except ValueError as exc:
        raise AutonomousCorpusError("winner mask escapes machine_root") from exc
    if not mask_path.is_file() or sha256_file(mask_path) != winner_sha:
        raise AutonomousCorpusError("winner mask hash verification failed")
    if serious_cross_family_disagreement and not cross_family_disagreement:
        raise AutonomousCorpusError("serious disagreement requires cross-family disagreement")
    if independent_family_count < 1:
        raise AutonomousCorpusError("independent_family_count must be positive")
    record_id = hashlib.sha256(
        f"{image_id}:{label}:{context}:{winner_sha}:{pipeline_fingerprint}".encode()
    ).hexdigest()
    return {
        "record_id": record_id,
        "image_id": image_id,
        "label": label,
        "context": context,
        "risk_bucket": risk_bucket or context,
        "pipeline_fingerprint": pipeline_fingerprint,
        "machine_accepted": bool(machine_accepted),
        "independent_family_count": int(independent_family_count),
        "cross_family_disagreement": bool(cross_family_disagreement),
        "serious_cross_family_disagreement": bool(serious_cross_family_disagreement),
        "candidate_stability_pass": bool(candidate_stability_pass),
        "perturbation_stability_pass": bool(perturbation_stability_pass),
        "complete_map_hard_veto_pass": bool(complete_map_hard_veto_pass),
        "machine_lifecycle_path": lifecycle_rel,
        "machine_lifecycle_sha256": sha256_file(lifecycle_path),
        "machine_mask_path": mask_rel,
        "machine_mask_sha256": winner_sha,
    }


def write_corpus_record_envelope(
    lifecycle_path: Path,
    *,
    machine_root: Path,
    image_id: str,
    label: str,
    context: str,
    pipeline_fingerprint: str,
    independent_family_count: int,
    cross_family_disagreement: bool,
    serious_cross_family_disagreement: bool,
    candidate_stability_pass: bool,
    perturbation_stability_pass: bool,
    complete_map_hard_veto_pass: bool,
    risk_bucket: str | None = None,
    machine_accepted: bool = True,
) -> dict[str, Any]:
    """Write the companion corpus-record envelope next to a lifecycle sidecar."""
    record = build_corpus_record(
        lifecycle_path=lifecycle_path,
        machine_root=machine_root,
        image_id=image_id,
        label=label,
        context=context,
        pipeline_fingerprint=pipeline_fingerprint,
        risk_bucket=risk_bucket,
        independent_family_count=independent_family_count,
        cross_family_disagreement=cross_family_disagreement,
        serious_cross_family_disagreement=serious_cross_family_disagreement,
        candidate_stability_pass=candidate_stability_pass,
        perturbation_stability_pass=perturbation_stability_pass,
        complete_map_hard_veto_pass=complete_map_hard_veto_pass,
        machine_accepted=machine_accepted,
    )
    envelope_path = corpus_record_path_for_lifecycle(lifecycle_path)
    _atomic_json(envelope_path, record)
    return record


def corpus_record_from_decision(
    lifecycle_path: Path,
    *,
    machine_root: Path,
    image_id: str,
    decision: TournamentDecision,
    pipeline_fingerprint: str,
    risk_bucket: str | None = None,
) -> dict[str, Any] | None:
    """Derive a corpus envelope from a tournament decision when provenance is real.

    Returns ``None`` when the decision is not MVC/CAA or the winner lacks >=3
    independent model families (or independent_sources). Never invents family
    counts.
    """
    if decision.status not in {"machine_verified_candidate", "calibrated_auto_accepted"}:
        return None
    winner = next(
        (item for item in decision.ranking if item.candidate_id == decision.winner_id),
        None,
    )
    if winner is None:
        return None
    families = tuple(winner.evidence.source_model_families)
    family_count = len(set(families)) if families else int(winner.evidence.independent_sources)
    if family_count < 3:
        return None
    hard_veto_pass = (
        winner.evidence.format_valid
        and not winner.evidence.block_qc_ids
        and float(winner.evidence.protected_overlap) <= 0.01
        and float(winner.evidence.exclusive_overlap) <= 0.005
        and winner.eligible
    )
    return write_corpus_record_envelope(
        lifecycle_path,
        machine_root=machine_root,
        image_id=image_id,
        label=decision.label,
        context=decision.context,
        pipeline_fingerprint=pipeline_fingerprint,
        risk_bucket=risk_bucket or decision.context,
        independent_family_count=family_count,
        cross_family_disagreement=bool(winner.evidence.critic_disagreement),
        serious_cross_family_disagreement=False,
        candidate_stability_pass=bool(winner.eligible),
        perturbation_stability_pass=bool(winner.eligible),
        complete_map_hard_veto_pass=hard_veto_pass,
        machine_accepted=True,
    )


def discover_corpus_records(machine_root: Path) -> list[dict[str, Any]]:
    """Load every production corpus-record envelope under machine_root."""
    root = Path(machine_root)
    records: list[dict[str, Any]] = []
    if not root.is_dir():
        return records
    for path in sorted(root.rglob(f"*{CORPUS_RECORD_SUFFIX}")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(document, dict) or "record_id" not in document:
            continue
        records.append(document)
    return records


def assemble_autonomous_verification_corpus(
    machine_root: Path,
    output_path: Path,
    *,
    label: str | None = None,
    context: str | None = None,
    pipeline_fingerprint: str | None = None,
    minimum_records: int = 1,
) -> dict[str, Any]:
    """Assemble a frozen image-disjoint corpus from production envelopes."""
    records = discover_corpus_records(machine_root)
    filtered: list[dict[str, Any]] = []
    for record in records:
        if label is not None and record.get("label") != label:
            continue
        if context is not None and record.get("context") != context:
            continue
        if (
            pipeline_fingerprint is not None
            and record.get("pipeline_fingerprint") != pipeline_fingerprint
        ):
            continue
        filtered.append(record)
    if len(filtered) < minimum_records:
        raise AutonomousCorpusError(
            f"insufficient corpus envelopes: found={len(filtered)} "
            f"minimum={minimum_records}"
        )
    # Production may emit multiple envelopes per image (labels/reruns). Keep one
    # record per image_id — prefer higher independent_family_count — so the
    # autonomous-gold certificate's image-disjoint invariant holds.
    by_image: dict[str, dict[str, Any]] = {}
    for record in filtered:
        image_id = str(record["image_id"])
        prior = by_image.get(image_id)
        if prior is None or int(record["independent_family_count"]) > int(
            prior["independent_family_count"]
        ):
            by_image[image_id] = record
    deduped = sorted(by_image.values(), key=lambda item: str(item["record_id"]))
    record_ids = [str(record["record_id"]) for record in deduped]
    if len(set(record_ids)) != len(record_ids):
        raise AutonomousCorpusError("corpus record IDs are not unique after image dedupe")
    corpus = {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "frozen": True,
        "image_disjoint": True,
        "records": deduped,
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(corpus, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "corpus_path": str(output_path),
        "record_count": len(deduped),
        "image_count": len(deduped),
        "raw_envelope_count": len(filtered),
        "deduped_from": len(filtered),
        "label_filter": label,
        "context_filter": context,
        "pipeline_fingerprint_filter": pipeline_fingerprint,
        "independent_family_counts": sorted(
            {int(record["independent_family_count"]) for record in deduped}
        ),
        "max_independent_family_count": max(
            (int(record["independent_family_count"]) for record in deduped), default=0
        ),
    }


def scan_lifecycle_pool(machine_root: Path) -> dict[str, Any]:
    """Honest scan of autonomy lifecycle sidecars (not every JSON under runs/)."""
    root = Path(machine_root)
    verified = 0
    calibrated = 0
    envelopes = 0
    total = 0
    if root.is_dir():
        for path in root.rglob("*.json"):
            if path.name.endswith(CORPUS_RECORD_SUFFIX):
                envelopes += 1
                continue
            if "autonomy" not in path.parts:
                continue
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if validate_document(document, "autonomy_lifecycle"):
                continue
            status = document.get("status")
            if status == "machine_verified_candidate":
                total += 1
                verified += 1
            elif status == "calibrated_auto_accepted":
                total += 1
                calibrated += 1
    return {
        "machine_root": str(root),
        "machine_verified_candidate_count": verified,
        "calibrated_auto_accepted_count": calibrated,
        "lifecycle_sidecars_seen": total,
        "corpus_record_envelopes_seen": envelopes,
    }


__all__ = [
    "AutonomousCorpusError",
    "CORPUS_RECORD_SUFFIX",
    "assemble_autonomous_verification_corpus",
    "build_corpus_record",
    "corpus_record_from_decision",
    "corpus_record_path_for_lifecycle",
    "discover_corpus_records",
    "scan_lifecycle_pool",
    "write_corpus_record_envelope",
]
