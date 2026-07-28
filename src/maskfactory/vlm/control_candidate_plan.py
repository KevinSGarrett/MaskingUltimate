"""Hash-bound 66-label calibration-control candidate batch planning.

The planner turns a sealed source-deficit report into reviewable batches.  It
does not admit a control: every emitted candidate still requires exact panels,
identity/split checks, and the bounded non-certifying screening mandated by
Amendment 2.  Draft-machine candidates receive the narrower Amendment-3
calibration-only ceiling and are rejected unless hard-QC and independent pixel
consensus are already bound.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .corpus_source_deficits import verify_visual_corpus_source_deficits
from .critic_catalog import canonical_sha256

SCHEMA_VERSION = "maskfactory.visual_control_candidate_plan.v1"
SOURCE_KINDS = (
    "qualified_polygon_or_rle",
    "parsing_dataset_exact_semantics",
    "shard0001_draft_machine",
)
SOURCE_PRIORITY = {source_kind: index for index, source_kind in enumerate(SOURCE_KINDS)}
EXTERNAL_REFERENCE = "external_labeled_reference"
DRAFT_CANDIDATE = "draft_machine_candidate"
SHA256_LENGTH = 64

CANDIDATE_KEYS = frozenset(
    {
        "candidate_id",
        "canonical_label",
        "source_kind",
        "source_authority_tier",
        "source_sha256",
        "panel_set_sha256",
        "identity_group_id",
        "partition",
        "exact_canonical_semantics",
        "deterministic_hard_qc_pass",
        "multi_provider_pixel_consensus",
    }
)
BATCH_CANDIDATE_KEYS = frozenset(
    {
        "candidate_id",
        "source_kind",
        "source_authority_tier",
        "source_sha256",
        "panel_set_sha256",
        "identity_group_id",
        "partition",
        "admission_ceiling",
        "requires_session_agent_screening",
        "requires_identity_and_split_disjointness",
        "requires_seeded_negative_generation",
    }
)
BATCH_KEYS = frozenset(
    {
        "canonical_label",
        "candidate_count",
        "candidates",
        "next_action",
    }
)
PLAN_KEYS = frozenset(
    {
        "schema_version",
        "artifact_type",
        "authority_claimed",
        "promotion_allowed",
        "qualification_corpus_ready",
        "calibration_controls_only",
        "source_deficit_sha256",
        "candidate_catalog_sha256",
        "planned_deficit_label_count",
        "unfilled_deficit_label_count",
        "batches",
        "claim_limits",
        "self_sha256",
    }
)


class ControlCandidatePlanError(ValueError):
    """Candidate catalog or emitted control-batch plan is invalid."""


def _self_sha256(document: Mapping[str, Any]) -> str:
    return canonical_sha256({key: value for key, value in document.items() if key != "self_sha256"})


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != SHA256_LENGTH:
        raise ControlCandidatePlanError(f"{field} must be a SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ControlCandidatePlanError(f"{field} must be a SHA-256") from exc
    return value


def _validate_candidate(candidate: Mapping[str, Any], missing_labels: set[str]) -> None:
    if not isinstance(candidate, Mapping) or set(candidate) != CANDIDATE_KEYS:
        raise ControlCandidatePlanError("candidate fields are incomplete or unknown")
    candidate_id = candidate["candidate_id"]
    label = candidate["canonical_label"]
    source_kind = candidate["source_kind"]
    if not isinstance(candidate_id, str) or not candidate_id:
        raise ControlCandidatePlanError("candidate id is invalid")
    if label not in missing_labels:
        raise ControlCandidatePlanError("candidate does not target a current deficit label")
    if source_kind not in SOURCE_PRIORITY:
        raise ControlCandidatePlanError("candidate source kind is invalid")
    for field in ("source_sha256", "panel_set_sha256"):
        _require_sha256(candidate[field], field)
    for field in ("identity_group_id", "partition"):
        if not isinstance(candidate[field], str) or not candidate[field]:
            raise ControlCandidatePlanError(f"candidate {field} is invalid")
    if candidate["exact_canonical_semantics"] is not True:
        raise ControlCandidatePlanError("candidate canonical semantics are not exact")
    if source_kind == "shard0001_draft_machine":
        if (
            candidate["source_authority_tier"] != DRAFT_CANDIDATE
            or candidate["deterministic_hard_qc_pass"] is not True
            or candidate["multi_provider_pixel_consensus"] is not True
        ):
            raise ControlCandidatePlanError("draft candidate lacks Amendment-3 prerequisites")
    elif (
        candidate["source_authority_tier"] != EXTERNAL_REFERENCE
        or candidate["deterministic_hard_qc_pass"] is not False
        or candidate["multi_provider_pixel_consensus"] is not False
    ):
        raise ControlCandidatePlanError("external candidate authority or prerequisites are invalid")


def build_visual_control_candidate_plan(
    *,
    source_deficit_report: Mapping[str, Any],
    candidate_catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build one closed batch plan for every currently missing canonical label."""

    verify_visual_corpus_source_deficits(source_deficit_report)
    if not isinstance(candidate_catalog, Sequence) or isinstance(candidate_catalog, (str, bytes)):
        raise ControlCandidatePlanError("candidate catalog must be an array")
    missing_labels = list(source_deficit_report["missing_canonical_labels"])
    missing_label_set = set(missing_labels)
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    seen_candidate_ids: set[str] = set()
    seen_identity_partition: set[tuple[str, str]] = set()
    for candidate in candidate_catalog:
        _validate_candidate(candidate, missing_label_set)
        candidate_id = str(candidate["candidate_id"])
        identity_partition = (str(candidate["identity_group_id"]), str(candidate["partition"]))
        if candidate_id in seen_candidate_ids or identity_partition in seen_identity_partition:
            raise ControlCandidatePlanError("candidate identity or split group is duplicated")
        seen_candidate_ids.add(candidate_id)
        seen_identity_partition.add(identity_partition)
        grouped[str(candidate["canonical_label"])].append(candidate)

    batches: list[dict[str, Any]] = []
    for label in missing_labels:
        selected = sorted(
            grouped[label],
            key=lambda candidate: (
                SOURCE_PRIORITY[str(candidate["source_kind"])],
                str(candidate["candidate_id"]),
            ),
        )
        batch_candidates = [
            {
                "candidate_id": candidate["candidate_id"],
                "source_kind": candidate["source_kind"],
                "source_authority_tier": candidate["source_authority_tier"],
                "source_sha256": candidate["source_sha256"],
                "panel_set_sha256": candidate["panel_set_sha256"],
                "identity_group_id": candidate["identity_group_id"],
                "partition": candidate["partition"],
                "admission_ceiling": "calibration_only",
                "requires_session_agent_screening": True,
                "requires_identity_and_split_disjointness": True,
                "requires_seeded_negative_generation": True,
            }
            for candidate in selected
        ]
        batches.append(
            {
                "canonical_label": label,
                "candidate_count": len(batch_candidates),
                "candidates": batch_candidates,
                "next_action": (
                    "render_exact_panels_then_session_agent_screening"
                    if batch_candidates
                    else "source_deficit_unfilled_acquire_exact_real_pixel_annotation"
                ),
            }
        )

    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "visual_critic_66_label_control_candidate_batch_plan",
        "authority_claimed": False,
        "promotion_allowed": False,
        "qualification_corpus_ready": False,
        "calibration_controls_only": True,
        "source_deficit_sha256": source_deficit_report["self_sha256"],
        "candidate_catalog_sha256": canonical_sha256(list(candidate_catalog)),
        "planned_deficit_label_count": len(batches),
        "unfilled_deficit_label_count": sum(not batch["candidates"] for batch in batches),
        "batches": batches,
        "claim_limits": [
            "Every candidate remains subject to per-record panel screening under Amendment 2.",
            "The plan may produce calibration controls only, never gold, training truth, package authority, or certificates.",
            "Shard-0001 drafts are eligible only as Amendment-3 calibration candidates after hard QC and multi-provider consensus; screening remains mandatory.",
            "An empty batch is a typed source deficit, never an invitation to infer pixels or substitute an alias.",
        ],
    }
    document["self_sha256"] = _self_sha256(document)
    verify_visual_control_candidate_plan(document, source_deficit_report=source_deficit_report)
    return document


def verify_visual_control_candidate_plan(
    document: Mapping[str, Any],
    *,
    source_deficit_report: Mapping[str, Any],
) -> None:
    """Verify batch order, authority ceiling, and all Amendment-2/3 restrictions."""

    verify_visual_corpus_source_deficits(source_deficit_report)
    if not isinstance(document, Mapping) or set(document) != PLAN_KEYS:
        raise ControlCandidatePlanError("control candidate plan fields are incomplete or unknown")
    if (
        document["schema_version"] != SCHEMA_VERSION
        or document["authority_claimed"] is not False
        or document["promotion_allowed"] is not False
        or document["qualification_corpus_ready"] is not False
        or document["calibration_controls_only"] is not True
        or document["source_deficit_sha256"] != source_deficit_report["self_sha256"]
        or _self_sha256(document) != document["self_sha256"]
    ):
        raise ControlCandidatePlanError("control candidate plan authority or hash drift")
    _require_sha256(document["candidate_catalog_sha256"], "candidate_catalog_sha256")
    batches = document["batches"]
    if (
        not isinstance(batches, list)
        or [batch.get("canonical_label") for batch in batches]
        != source_deficit_report["missing_canonical_labels"]
        or document["planned_deficit_label_count"] != len(batches)
    ):
        raise ControlCandidatePlanError("control candidate plan labels are not exact")
    unfilled = 0
    seen_candidate_ids: set[str] = set()
    seen_identity_partition: set[tuple[str, str]] = set()
    for batch in batches:
        if not isinstance(batch, Mapping) or set(batch) != BATCH_KEYS:
            raise ControlCandidatePlanError("control candidate batch fields are invalid")
        candidates = batch["candidates"]
        if not isinstance(candidates, list) or batch["candidate_count"] != len(candidates):
            raise ControlCandidatePlanError("control candidate batch count drifted")
        if not candidates:
            unfilled += 1
            if (
                batch["next_action"]
                != "source_deficit_unfilled_acquire_exact_real_pixel_annotation"
            ):
                raise ControlCandidatePlanError("empty control candidate batch action is invalid")
        else:
            if batch["next_action"] != "render_exact_panels_then_session_agent_screening":
                raise ControlCandidatePlanError(
                    "populated control candidate batch action is invalid"
                )
        previous_priority = -1
        for candidate in candidates:
            if not isinstance(candidate, Mapping) or set(candidate) != BATCH_CANDIDATE_KEYS:
                raise ControlCandidatePlanError("batch candidate fields are invalid")
            if (
                candidate["admission_ceiling"] != "calibration_only"
                or candidate["requires_session_agent_screening"] is not True
                or candidate["requires_identity_and_split_disjointness"] is not True
                or candidate["requires_seeded_negative_generation"] is not True
            ):
                raise ControlCandidatePlanError("batch candidate authority ceiling drifted")
            source_kind = candidate["source_kind"]
            if (
                source_kind not in SOURCE_PRIORITY
                or SOURCE_PRIORITY[source_kind] < previous_priority
            ):
                raise ControlCandidatePlanError("batch candidate source priority drifted")
            previous_priority = SOURCE_PRIORITY[source_kind]
            for field in ("source_sha256", "panel_set_sha256"):
                _require_sha256(candidate[field], field)
            candidate_id = candidate["candidate_id"]
            identity_partition = (candidate["identity_group_id"], candidate["partition"])
            if candidate_id in seen_candidate_ids or identity_partition in seen_identity_partition:
                raise ControlCandidatePlanError(
                    "batch candidate identity or split group duplicated"
                )
            seen_candidate_ids.add(candidate_id)
            seen_identity_partition.add(identity_partition)
    if document["unfilled_deficit_label_count"] != unfilled:
        raise ControlCandidatePlanError("control candidate unfilled summary drifted")


__all__ = [
    "ControlCandidatePlanError",
    "build_visual_control_candidate_plan",
    "verify_visual_control_candidate_plan",
]
