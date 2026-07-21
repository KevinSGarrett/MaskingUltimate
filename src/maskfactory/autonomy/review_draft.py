"""Build a reversible machine-improved draft for the human review handoff."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image

from ..io.hashing import sha256_file
from ..io.png_strict import write_label_map
from ..ontology import get_ontology
from .tournament import TournamentDecision


@dataclass(frozen=True)
class CandidateQaOutcome:
    """Result of rerunning hard QA against one complete candidate label map."""

    block_qc_ids: tuple[str, ...]
    report_path: str | None
    overall: str
    score: float | None = None
    baseline_score: float | None = None
    non_regressing: bool = False
    all_block_qc_ids: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.block_qc_ids and (
            self.overall in {"pass", "needs_human"} or self.non_regressing
        )


@dataclass(frozen=True)
class ReviewDraftSelection:
    label: str
    candidate_id: str
    mask_path: str
    mask_sha256: str
    status: str
    score: float
    selection_reason: str = "tournament_winner"
    baseline_score: float | None = None
    score_delta: float | None = None
    provider_votes: tuple[dict[str, Any], ...] = ()
    remaining_uncertainties: tuple[str, ...] = ()
    before_metrics: dict[str, Any] | None = None
    after_metrics: dict[str, Any] | None = None
    repair_roi_xyxy: tuple[int, int, int, int] | None = None
    allow_label_reassignment: bool = False
    immutable_label_ids: tuple[int, ...] = ()
    maximum_displaced_labels: int = 0


MapQaValidator = Callable[[Path, str], CandidateQaOutcome]


def select_pre_review_candidate(
    decision: TournamentDecision,
    *,
    policy: dict[str, Any],
    provider_votes: tuple[dict[str, Any], ...] = (),
    remaining_uncertainties: tuple[str, ...] = (),
) -> ReviewDraftSelection | None:
    """Select a reversible non-gold improvement independently of autoaccept eligibility.

    A calibration certificate controls whether human review may be skipped. It does not
    prevent a demonstrably safer candidate from becoming the starting point for that
    human review.
    """
    draft_policy = policy.get("review_draft", {})
    if draft_policy.get("enabled") is not True or decision.winner_id in {
        None,
        "s09_baseline",
    }:
        return None
    winner = next(
        (item for item in decision.ranking if item.candidate_id == decision.winner_id),
        None,
    )
    baseline = next(
        (item for item in decision.ranking if item.candidate_id == "s09_baseline"),
        None,
    )
    if winner is None or baseline is None or not winner.eligible:
        return None
    if float(winner.score) < float(draft_policy["minimum_score"]):
        return None

    score_delta = float(winner.score - baseline.score)
    baseline_hard_vetoed = not baseline.eligible
    verified_better = winner.evidence.critic_pass_weight >= float(
        draft_policy["minimum_verified_better_confidence"]
    ) and score_delta >= float(draft_policy["minimum_score_delta"])
    established_autonomy_winner = decision.status in {
        "machine_verified_candidate",
        "calibrated_auto_accepted",
    }
    clears_hard_veto = (
        baseline_hard_vetoed
        and draft_policy["apply_if_baseline_hard_vetoed"] is True
        and not winner.vetoes
    )
    if not (established_autonomy_winner or clears_hard_veto or verified_better):
        return None

    if established_autonomy_winner:
        reason = "winner_passed_autonomy_tournament"
        status = decision.status
    elif clears_hard_veto:
        reason = "candidate_clears_baseline_hard_veto"
        status = draft_policy["status"]
    else:
        reason = "candidate_verified_better_for_human_review"
        status = draft_policy["status"]
    uncertainties = list(remaining_uncertainties)
    if decision.status == "residual_human_queue":
        uncertainties.append(decision.reason)
    if winner.evidence.critic_disagreement:
        uncertainties.append("independent_critics_disagree")
    return ReviewDraftSelection(
        label=decision.label,
        candidate_id=winner.candidate_id,
        mask_path=winner.evidence.mask_path,
        mask_sha256=winner.evidence.mask_sha256,
        status=status,
        score=float(winner.score),
        selection_reason=reason,
        baseline_score=float(baseline.score),
        score_delta=score_delta,
        provider_votes=provider_votes,
        remaining_uncertainties=tuple(dict.fromkeys(uncertainties)),
        before_metrics={
            "score": float(baseline.score),
            "eligible": baseline.eligible,
            "vetoes": list(baseline.vetoes),
            "evidence": asdict(baseline.evidence),
        },
        after_metrics={
            "score": float(winner.score),
            "eligible": winner.eligible,
            "vetoes": list(winner.vetoes),
            "evidence": asdict(winner.evidence),
        },
    )


def compose_candidate_map(
    base_part_map: np.ndarray,
    *,
    label: str,
    candidate_mask_path: Path,
) -> tuple[np.ndarray, tuple[str, ...]]:
    """Replace one label in a copy of the map while refusing cross-label overwrite."""
    authority = get_ontology()
    label_id = int(authority.label(label).id)
    if label_id <= 0:
        raise ValueError(f"autonomy candidate label is not an indexed PART label: {label}")
    base = np.asarray(base_part_map)
    with Image.open(candidate_mask_path) as image:
        candidate = np.asarray(image)
        format_valid = image.mode == "L" and set(np.unique(candidate).tolist()) <= {0, 255}
    if candidate.shape != base.shape:
        return base.copy(), ("candidate_dimensions",)
    if not format_valid:
        return base.copy(), ("candidate_format",)
    candidate_bool = candidate != 0
    if not candidate_bool.any():
        return base.copy(), ("candidate_empty",)
    cross_label = candidate_bool & (base != 0) & (base != label_id)
    if np.any(cross_label):
        return base.copy(), ("candidate_cross_label_overwrite",)
    output = base.copy()
    output[output == label_id] = 0
    output[candidate_bool] = label_id
    return output, ()


def compose_candidate_map_transactional(
    base_part_map: np.ndarray,
    *,
    label: str,
    candidate_mask_path: Path,
    repair_roi_xyxy: tuple[int, int, int, int],
    immutable_label_ids: tuple[int, ...] = (),
    maximum_displaced_labels: int = 8,
) -> tuple[np.ndarray, tuple[str, ...], dict[int, int]]:
    """Atomically reassign a target inside an ROI while preserving immutable labels.

    Ordinary draft labels are hypotheses, not protected truth.  A candidate may displace
    them only inside its anatomy ROI.  The complete resulting map is returned for QA;
    callers never mutate the input map in place.
    """
    authority = get_ontology()
    label_id = int(authority.label(label).id)
    base = np.asarray(base_part_map)
    with Image.open(candidate_mask_path) as image:
        candidate = np.asarray(image)
        format_valid = image.mode == "L" and set(np.unique(candidate).tolist()) <= {0, 255}
    if candidate.shape != base.shape:
        return base.copy(), ("candidate_dimensions",), {}
    if not format_valid:
        return base.copy(), ("candidate_format",), {}
    target = candidate != 0
    if not target.any():
        return base.copy(), ("candidate_empty",), {}
    left, top, right, bottom = repair_roi_xyxy
    height, width = base.shape
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        return base.copy(), ("candidate_repair_roi",), {}
    roi = np.zeros(base.shape, dtype=bool)
    roi[top:bottom, left:right] = True
    if np.any(target & ~roi):
        return base.copy(), ("candidate_outside_repair_roi",), {}
    incumbent = base[target]
    immutable = set(int(value) for value in immutable_label_ids)
    if any(int(value) in immutable for value in np.unique(incumbent)):
        return base.copy(), ("candidate_immutable_label_overwrite",), {}
    displaced = {
        int(value): int(np.count_nonzero(incumbent == value))
        for value in np.unique(incumbent)
        if int(value) not in {0, label_id}
    }
    if len(displaced) > maximum_displaced_labels:
        return base.copy(), ("candidate_displaced_label_limit",), displaced
    output = base.copy()
    output[output == label_id] = 0
    output[target] = label_id
    return output, (), displaced


def build_autonomous_review_draft(
    base_part_map_path: Path,
    selections: tuple[ReviewDraftSelection, ...],
    output_dir: Path,
    *,
    map_validator: MapQaValidator | None = None,
) -> dict:
    """Compose selected masks with per-label QA and reversible per-label rollback.

    The resulting map is only the starting draft sent to CVAT. It is never human gold.
    """
    base_path = Path(base_part_map_path)
    with Image.open(base_path) as base_image:
        base = np.asarray(base_image)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ordered = sorted(selections, key=lambda item: (-item.score, item.label, item.candidate_id))
    proposed = base.copy()
    applied: list[dict] = []
    rolled_back: list[dict] = []
    skipped: list[dict] = []
    candidate_maps_dir = output_dir / "candidate_maps"
    for index, selection in enumerate(ordered, start=1):
        path = Path(selection.mask_path)
        reason = None
        if selection.status not in {
            "pre_review_improvement",
            "repair_progress",
            "machine_verified_candidate",
            "calibrated_auto_accepted",
        }:
            reason = "selection_status_not_review_draft_eligible"
        elif not path.is_file() or sha256_file(path) != selection.mask_sha256:
            reason = "candidate_hash_or_path_invalid"
        if reason is None:
            displaced: dict[int, int] = {}
            if selection.allow_label_reassignment and selection.repair_roi_xyxy is not None:
                candidate_map, vetoes, displaced = compose_candidate_map_transactional(
                    proposed,
                    label=selection.label,
                    candidate_mask_path=path,
                    repair_roi_xyxy=selection.repair_roi_xyxy,
                    immutable_label_ids=selection.immutable_label_ids,
                    maximum_displaced_labels=selection.maximum_displaced_labels,
                )
            else:
                candidate_map, vetoes = compose_candidate_map(
                    proposed,
                    label=selection.label,
                    candidate_mask_path=path,
                )
            if vetoes:
                reason = ",".join(vetoes)
            else:
                changed_pixel_count = int(np.count_nonzero(candidate_map != proposed))
                candidate_maps_dir.mkdir(parents=True, exist_ok=True)
                candidate_map_path = write_label_map(
                    candidate_maps_dir
                    / f"{index:03d}_{selection.label}_{selection.candidate_id}.png",
                    candidate_map,
                    bits=16,
                )
                incremental_qa = (
                    map_validator(
                        candidate_map_path,
                        f"autonomy_review_draft_{selection.label}_{selection.candidate_id}",
                    )
                    if map_validator is not None
                    else CandidateQaOutcome((), None, "not_run")
                )
                record = asdict(selection) | {
                    "candidate_complete_map": str(candidate_map_path),
                    "candidate_complete_map_sha256": sha256_file(candidate_map_path),
                    "changed_pixel_count": changed_pixel_count,
                    "changed_pixel_fraction": changed_pixel_count / int(proposed.size),
                    "displaced_label_pixel_counts": {
                        str(key): value for key, value in sorted(displaced.items())
                    },
                    "incremental_qa": _qa_document(incremental_qa),
                }
                if incremental_qa.passed:
                    proposed = candidate_map
                    applied.append(record)
                else:
                    rolled_back.append(record | {"reason": "incremental_full_map_hard_qa_failed"})
        if reason is not None:
            skipped.append(asdict(selection) | {"reason": reason})

    proposed_path = write_label_map(output_dir / "proposed_label_map_part.png", proposed, bits=16)
    qa = (
        map_validator(proposed_path, "autonomy_review_draft_final")
        if map_validator is not None and applied
        else CandidateQaOutcome((), None, "pass" if applied else "no_selection")
    )
    promoted = bool(applied) and qa.passed
    final_path = write_label_map(
        output_dir / "label_map_part.png", proposed if promoted else base, bits=16
    )
    document = {
        "schema_version": "1.0.0",
        "authority": "machine_generated_review_draft_non_gold",
        "base_part_map": str(base_path),
        "base_part_map_sha256": sha256_file(base_path),
        "proposed_part_map": str(proposed_path),
        "proposed_part_map_sha256": sha256_file(proposed_path),
        "review_part_map": str(final_path),
        "review_part_map_sha256": sha256_file(final_path),
        "promoted_for_human_review": promoted,
        "authoritative_human_gold": False,
        "applied": applied if promoted else [],
        "rolled_back": (
            rolled_back
            if promoted
            else rolled_back
            + [item | {"reason": "final_full_map_hard_qa_failed"} for item in applied]
        ),
        "skipped": skipped,
        "changed_labels": [item["label"] for item in applied] if promoted else [],
        "changed_pixel_count": int(np.count_nonzero(proposed != base)) if promoted else 0,
        "changed_pixel_fraction": (
            int(np.count_nonzero(proposed != base)) / int(base.size) if promoted else 0.0
        ),
        "human_gold_approval_required": True,
        "qa": {
            "overall": qa.overall,
            "block_qc_ids": list(qa.block_qc_ids),
            "report_path": str(qa.report_path) if qa.report_path is not None else None,
        },
    }
    persisted_qa = dict(document["qa"])
    if persisted_qa.get("report_path"):
        persisted_qa["report_path"] = Path(
            os.path.relpath(str(persisted_qa["report_path"]), str(output_dir))
        ).as_posix()
    persisted = document | {
        "proposed_part_map": proposed_path.name,
        "review_part_map": final_path.name,
        "qa": persisted_qa,
    }
    (output_dir / "report.json").write_text(
        json.dumps(persisted, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return document


def _qa_document(outcome: CandidateQaOutcome) -> dict[str, Any]:
    return {
        "overall": outcome.overall,
        "block_qc_ids": list(outcome.block_qc_ids),
        "report_path": str(outcome.report_path) if outcome.report_path is not None else None,
        "score": outcome.score,
        "baseline_score": outcome.baseline_score,
        "non_regressing": outcome.non_regressing,
        "all_block_qc_ids": list(outcome.all_block_qc_ids),
    }


__all__ = [
    "CandidateQaOutcome",
    "MapQaValidator",
    "ReviewDraftSelection",
    "build_autonomous_review_draft",
    "compose_candidate_map",
    "compose_candidate_map_transactional",
    "select_pre_review_candidate",
]
