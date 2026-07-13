"""Build a reversible machine-improved draft for the human review handoff."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from ..io.hashing import sha256_file
from ..io.png_strict import write_label_map
from ..ontology import get_ontology


@dataclass(frozen=True)
class CandidateQaOutcome:
    """Result of rerunning hard QA against one complete candidate label map."""

    block_qc_ids: tuple[str, ...]
    report_path: str | None
    overall: str

    @property
    def passed(self) -> bool:
        return not self.block_qc_ids and self.overall != "fail"


@dataclass(frozen=True)
class ReviewDraftSelection:
    label: str
    candidate_id: str
    mask_path: str
    mask_sha256: str
    status: str
    score: float


MapQaValidator = Callable[[Path, str], CandidateQaOutcome]


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


def build_autonomous_review_draft(
    base_part_map_path: Path,
    selections: tuple[ReviewDraftSelection, ...],
    output_dir: Path,
    *,
    map_validator: MapQaValidator | None = None,
) -> dict:
    """Compose selected masks, rerun full-map QA, and fall back atomically on failure.

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
    skipped: list[dict] = []
    for selection in ordered:
        path = Path(selection.mask_path)
        reason = None
        if selection.status not in {"machine_verified_candidate", "calibrated_auto_accepted"}:
            reason = "selection_status_not_review_draft_eligible"
        elif not path.is_file() or sha256_file(path) != selection.mask_sha256:
            reason = "candidate_hash_or_path_invalid"
        if reason is None:
            candidate_map, vetoes = compose_candidate_map(
                proposed,
                label=selection.label,
                candidate_mask_path=path,
            )
            if vetoes:
                reason = ",".join(vetoes)
            else:
                proposed = candidate_map
                applied.append(asdict(selection))
        if reason is not None:
            skipped.append(asdict(selection) | {"reason": reason})

    proposed_path = write_label_map(output_dir / "proposed_label_map_part.png", proposed, bits=16)
    qa = (
        map_validator(proposed_path, "autonomy_review_draft")
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
        "rolled_back": applied if applied and not promoted else [],
        "skipped": skipped,
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


__all__ = [
    "CandidateQaOutcome",
    "MapQaValidator",
    "ReviewDraftSelection",
    "build_autonomous_review_draft",
    "compose_candidate_map",
]
