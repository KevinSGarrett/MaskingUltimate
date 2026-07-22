"""Immutable bounded repair attempts for reference-only generated person masks."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image

from .io.hashing import sha256_file
from .io.png_strict import write_binary_mask
from .nude_box_mask_generation import validate_box_prompt_provider_batch
from .nude_reference_strict_visual_review import (
    validate_reference_person_strict_visual_review,
)
from .providers.contracts import InteractiveSegmenter, MaskProposal, ProviderIdentity
from .providers.disagreement import binary_mask_sha256
from .vlm.target_contract import target_contract_sha256, validate_target_contract


class NudeReferenceMaskRepairError(ValueError):
    """Repair inputs or an attempted authority expansion failed closed."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _provider(identity: ProviderIdentity) -> dict[str, str]:
    return {
        "provider_key": identity.provider_key,
        "role": identity.role,
        "model_family": identity.model_family,
        "source_commit": identity.source_commit,
        "runtime_fingerprint": identity.runtime_fingerprint,
        "contract_version": identity.contract_version,
    }


def _agreed_plan(report: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
    votes = report.get("reviewer_verdicts")
    if not isinstance(votes, list) or len(votes) != 2:
        return None, "qualified_reviewer_pair_missing"
    if any(vote.get("status") != "complete" or vote.get("verdict") != "fail" for vote in votes):
        return None, "repair_requires_two_complete_fail_verdicts"
    plans = [vote.get("repair_plan") for vote in votes]
    if not all(isinstance(plan, Mapping) for plan in plans):
        return None, "repair_plan_missing"
    if _canonical_sha256(plans[0]) != _canonical_sha256(plans[1]):
        return None, "repair_plan_disagreement"
    plan = dict(plans[0])
    if plan.get("tool") == "none":
        return None, "repair_not_requested"
    return plan, "exact_independent_plan_agreement"


def _select(proposals: Sequence[MaskProposal], identity: ProviderIdentity, shape) -> MaskProposal:
    eligible = [
        proposal
        for proposal in proposals
        if proposal.provider == identity
        and proposal.mask.shape == shape
        and proposal.mask.dtype == np.bool_
        and proposal.mask.any()
    ]
    if not eligible:
        raise NudeReferenceMaskRepairError("repair_provider_returned_no_valid_mask")
    return sorted(
        eligible,
        key=lambda proposal: (-float(proposal.confidence), binary_mask_sha256(proposal.mask)),
    )[0]


def _child_contract(
    parent: Mapping[str, Any], *, artifact_sha256: str, mask_sha256: str, hypothesis_id: str
) -> dict[str, Any]:
    child = deepcopy(dict(parent))
    validate_target_contract(child)
    if child["schema_version"] != "2.0.0":
        raise NudeReferenceMaskRepairError("repair_requires_target_contract_v2")
    old_revision = int(child["package"]["revision"])
    child["package"]["parent_revision"] = old_revision
    child["package"]["revision"] = old_revision + 1
    child["contract_id"] = f"{child['contract_id']}@repair-{hypothesis_id}"
    child["candidate"]["encoded_sha256"] = artifact_sha256
    child["candidate"]["decoded_pixel_sha256"] = mask_sha256
    child["contract_sha256"] = target_contract_sha256(child)
    validate_target_contract(child)
    return child


def execute_reference_person_repair_batch(
    *,
    provider_batch: Mapping[str, Any],
    visual_review: Mapping[str, Any],
    evidence_root: Path,
    output_root: Path,
    source_paths: Mapping[str, Path],
    target_contracts: Mapping[str, Mapping[int, Mapping[str, Any]]],
    repair_provider: InteractiveSegmenter,
    attempt_history: Mapping[str, Mapping[int, Sequence[Mapping[str, Any]]]] | None = None,
    maximum_attempts: int = 3,
) -> dict[str, Any]:
    """Execute one hypothesis-distinct repair pass while preserving every parent byte."""

    if (
        not isinstance(maximum_attempts, int)
        or isinstance(maximum_attempts, bool)
        or not 1 <= maximum_attempts <= 5
    ):
        raise NudeReferenceMaskRepairError("repair_attempt_limit_invalid")
    batch = validate_box_prompt_provider_batch(provider_batch, output_root=output_root)
    review = validate_reference_person_strict_visual_review(
        visual_review, evidence_root=evidence_root
    )
    if review["provider_batch_sha256"] != batch["self_sha256"]:
        raise NudeReferenceMaskRepairError("repair_visual_provider_batch_drift")
    if not isinstance(repair_provider, InteractiveSegmenter):
        raise NudeReferenceMaskRepairError("repair_provider_contract_invalid")
    if repair_provider.identity.role != "interactive_segmenter":
        raise NudeReferenceMaskRepairError("repair_provider_role_invalid")
    histories = attempt_history or {}
    batch_records = {record["sample_id"]: record for record in batch["records"]}
    output_records = []
    for review_record in review["records"]:
        sample_id = review_record["sample_id"]
        source_path = Path(source_paths.get(sample_id, ""))
        source_embedding = None
        candidate_outputs = []
        record_reasons = []
        try:
            if review_record["status"] != "fail":
                raise NudeReferenceMaskRepairError(
                    f"repair_record_not_eligible:{review_record['status']}"
                )
            if (
                not source_path.is_file()
                or sha256_file(source_path) != review_record["source_sha256"]
            ):
                raise NudeReferenceMaskRepairError("repair_source_hash_mismatch")
            with Image.open(source_path) as opened:
                source = np.asarray(opened.convert("RGB"))
            source_embedding = repair_provider.embed(source)
            parent_candidates = {
                int(candidate["person_index"]): candidate
                for candidate in batch_records[sample_id]["candidates"]
            }
            parent_masks = {}
            for index, candidate in parent_candidates.items():
                with Image.open(Path(output_root) / candidate["artifact_relative_path"]) as opened:
                    parent_masks[index] = np.asarray(opened.convert("L")) == 255
            for report in review_record["candidate_reports"]:
                person_index = int(report["person_index"])
                plan, plan_reason = _agreed_plan(report)
                prior = list(histories.get(sample_id, {}).get(person_index, ()))
                if plan is None:
                    candidate_outputs.append(
                        {"person_index": person_index, "status": "abstain", "reason": plan_reason}
                    )
                    continue
                if len(prior) >= maximum_attempts:
                    candidate_outputs.append(
                        {
                            "person_index": person_index,
                            "status": "abstain",
                            "reason": "repair_attempt_cap_exhausted",
                        }
                    )
                    continue
                plan_sha = _canonical_sha256(plan)
                if any(
                    item.get("plan_sha256") == plan_sha
                    or item.get("hypothesis_id") == plan["hypothesis_id"]
                    for item in prior
                ):
                    candidate_outputs.append(
                        {
                            "person_index": person_index,
                            "status": "abstain",
                            "reason": "duplicate_repair_hypothesis",
                        }
                    )
                    continue
                parent = parent_candidates[person_index]
                parent_mask = parent_masks[person_index]
                proposals = repair_provider.refine(
                    source_embedding,
                    prompt={
                        "positive_points": plan["positive_points"],
                        "negative_points": plan["negative_points"],
                        "box_xyxy": plan["roi_xyxy"],
                        "mask_prompt": parent_mask,
                    },
                )
                selected = _select(proposals, repair_provider.identity, parent_mask.shape)
                child_mask = np.asarray(selected.mask).astype(bool)
                roi = plan["roi_xyxy"]
                outside = np.ones_like(child_mask, dtype=bool)
                outside[roi[1] : roi[3], roi[0] : roi[2]] = False
                if np.any((child_mask ^ parent_mask) & outside):
                    raise NudeReferenceMaskRepairError("repair_changed_pixels_outside_roi")
                protected = np.zeros_like(child_mask)
                for other_index, other_mask in parent_masks.items():
                    if other_index != person_index:
                        protected |= other_mask
                if np.any(child_mask & protected):
                    raise NudeReferenceMaskRepairError("repair_cross_person_protected_overlap")
                changed = int(np.count_nonzero(child_mask ^ parent_mask))
                changed_fraction = changed / max(1, int(np.count_nonzero(child_mask | parent_mask)))
                if changed == 0:
                    candidate_outputs.append(
                        {
                            "person_index": person_index,
                            "status": "no_progress",
                            "reason": "identical_child_mask",
                            "plan_sha256": plan_sha,
                        }
                    )
                    continue
                if changed_fraction > float(plan["maximum_changed_fraction"]):
                    raise NudeReferenceMaskRepairError("repair_changed_fraction_exceeded")
                relative = (
                    Path(sample_id)
                    / f"person_{person_index:03d}"
                    / "repairs"
                    / f"attempt_{len(prior) + 1:02d}_{plan_sha[:12]}.png"
                )
                path = write_binary_mask(
                    Path(output_root) / relative,
                    child_mask,
                    source_size=(parent_mask.shape[1], parent_mask.shape[0]),
                )
                artifact_sha = sha256_file(path)
                mask_sha = binary_mask_sha256(child_mask)
                parent_contract = target_contracts[sample_id][person_index]
                if parent_contract["contract_sha256"] != report["target_contract_sha256"]:
                    raise NudeReferenceMaskRepairError("repair_target_contract_drift")
                child_contract = _child_contract(
                    parent_contract,
                    artifact_sha256=artifact_sha,
                    mask_sha256=mask_sha,
                    hypothesis_id=plan["hypothesis_id"],
                )
                candidate_outputs.append(
                    {
                        "person_index": person_index,
                        "status": "child_candidate_created",
                        "attempt": len(prior) + 1,
                        "hypothesis_id": plan["hypothesis_id"],
                        "plan_sha256": plan_sha,
                        "parent_artifact_sha256": parent["artifact_sha256"],
                        "parent_mask_sha256": parent["mask_sha256"],
                        "child_relative_path": relative.as_posix(),
                        "child_artifact_sha256": artifact_sha,
                        "child_mask_sha256": mask_sha,
                        "changed_pixels": changed,
                        "changed_fraction": changed_fraction,
                        "repair_provider": _provider(repair_provider.identity),
                        "child_target_contract": child_contract,
                        "authority": "draft_repair_candidate_only",
                        "hard_qc_complete": False,
                        "strict_visual_review_complete": False,
                        "production_mask_authority": False,
                        "operational_certificate_eligible": False,
                    }
                )
        except Exception as exc:  # one record never stalls unrelated records
            record_reasons.append(f"{type(exc).__name__}:{exc}")
        finally:
            close = getattr(repair_provider, "close", None)
            if source_embedding is not None and callable(close):
                close(source_embedding)
        statuses = Counter(item["status"] for item in candidate_outputs)
        output_records.append(
            {
                "sample_id": sample_id,
                "source_sha256": review_record["source_sha256"],
                "status": (
                    "repair_candidates_created"
                    if statuses["child_candidate_created"]
                    else "abstain" if candidate_outputs else "record_error"
                ),
                "reasons": record_reasons,
                "candidate_results": candidate_outputs,
            }
        )
    counts = Counter(record["status"] for record in output_records)
    body = {
        "schema_version": "maskfactory.nude_reference_person_repair_batch.v1",
        "provider_batch_sha256": batch["self_sha256"],
        "visual_review_sha256": review["self_sha256"],
        "repair_provider": _provider(repair_provider.identity),
        "maximum_attempts": maximum_attempts,
        "record_count": len(output_records),
        "status_counts": dict(sorted(counts.items())),
        "records": output_records,
        "immutable_parents_preserved": True,
        "hard_qc_complete": False,
        "strict_visual_review_complete": False,
        "production_mask_authority": False,
        "operational_certificates_issued": False,
        "autonomous_certified_gold_created": False,
    }
    return {**body, "self_sha256": _canonical_sha256(body)}


__all__ = [
    "NudeReferenceMaskRepairError",
    "execute_reference_person_repair_batch",
]
