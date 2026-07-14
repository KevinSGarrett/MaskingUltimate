"""Tool-using VLM mask audit and bounded SAM2 correction-candidate orchestration."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image
from scipy import ndimage

from ..gpu import GpuLock
from ..io.png_strict import write_binary_mask
from ..ontology import get_ontology
from ..qa.panels import WorkhorseEvidence
from .client import ALLOWED_PROBLEMS, OllamaClient


class WorkhorseError(ValueError):
    """A VLM audit or correction proposal violated a bounded contract."""


class CorrectionRefiner(Protocol):
    def __call__(
        self, image: np.ndarray, label: str, clicks: tuple[dict[str, Any], ...]
    ) -> np.ndarray: ...


@dataclass(frozen=True)
class CorrectionPlan:
    tool: str
    positive_points: tuple[tuple[int, int], ...]
    negative_points: tuple[tuple[int, int], ...]
    rationale: str


@dataclass(frozen=True)
class WorkhorseAudit:
    label: str
    model_verdict: str
    model_confidence: float
    verdict: str
    confidence: float
    problems: tuple[str, ...]
    observations: dict[str, str]
    evidence: str
    correction_instruction: str
    correction_plan: CorrectionPlan
    model: str
    prompt_version: str
    latency_ms: int
    deterministic_overrides: tuple[str, ...]


@dataclass(frozen=True)
class CandidateResult:
    status: str
    label: str
    candidate_path: str | None
    before_area_px: int
    after_area_px: int | None
    changed_fraction: float | None
    positive_points_satisfied: bool
    negative_points_satisfied: bool
    protected_overlap_fraction: float | None
    reason: str


@dataclass(frozen=True)
class CandidateVerification:
    label: str
    decision: str
    confidence: float
    fixed_problems: tuple[str, ...]
    remaining_problems: tuple[str, ...]
    before_observation: str
    after_observation: str
    evidence: str
    latency_ms: int


def review_part_workhorse(
    client: OllamaClient,
    *,
    label: str,
    evidence: WorkhorseEvidence,
    model: str,
    prompt_template: str,
    prompt_version: str,
    gpu_lock_path: Path,
    generation_options: dict[str, Any],
    qa_findings: tuple[dict[str, Any], ...] = (),
) -> WorkhorseAudit:
    """Force observation of each independent image before accepting a verdict or tool plan."""
    crop = evidence.crop_xyxy
    width, height = evidence.source_size
    definition = get_ontology().label(label)
    prompt = (
        prompt_template.replace("<label>", label)
        + f"\nFULL SOURCE SIZE: {width}x{height}."
        + f"\nCROP XYXY IN FULL SOURCE: {list(crop)}."
        + "\nCorrection points MUST be integer coordinates in the full source image."
        + "\nDETERMINISTIC MASK METRICS: "
        + json.dumps(_evidence_metrics(evidence), sort_keys=True, separators=(",", ":"))
        + ". Treat component_count above the ontology maximum as a definite defect."
        + "\nONTOLOGY CONTRACT: "
        + json.dumps(
            {
                "side": definition.side,
                "parent_union": definition.parent_union,
                "expected_area_pct_range": definition.expected_area_pct_range,
                "max_components": definition.max_components,
                "boundary_rule": definition.boundary_rule,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\nDETERMINISTIC AUTO-QA NON-PASS FINDINGS: "
        + json.dumps(list(qa_findings[:20]), sort_keys=True, separators=(",", ":"))
        + ". Auto-QA findings are evidence to investigate and may not be silently dismissed."
    )
    started = time.perf_counter()
    raw = ""
    parsed = None
    with GpuLock(path=gpu_lock_path, purpose="S11_vlm_workhorse_audit"):
        for attempt in range(2):
            raw = client.generate(
                model=model,
                prompt=(
                    prompt if attempt == 0 else prompt + "\nPrior output invalid. Exact JSON only."
                ),
                images=evidence.images,
                options=generation_options,
                think=False,
            )
            parsed = _parse_audit(raw, evidence.source_size)
            if parsed is not None:
                break
    latency = round((time.perf_counter() - started) * 1000)
    if parsed is None:
        parsed = {
            "verdict": "uncertain",
            "confidence": 0.0,
            "problems": [],
            "observations": {name: "invalid response" for name in _OBSERVATION_KEYS},
            "evidence": "Response violated the workhorse audit contract.",
            "correction_instruction": "",
            "correction_plan": {
                "tool": "human_review",
                "positive_points": [],
                "negative_points": [],
                "rationale": "Invalid model response; do not automate correction.",
            },
        }
    model_verdict = parsed["verdict"]
    model_confidence = float(parsed["confidence"])
    parsed = _apply_deterministic_findings(parsed, label, evidence, qa_findings)
    plan = parsed["correction_plan"]
    return WorkhorseAudit(
        label=label,
        model_verdict=model_verdict,
        model_confidence=model_confidence,
        verdict=parsed["verdict"],
        confidence=float(parsed["confidence"]),
        problems=tuple(parsed["problems"]),
        observations=dict(parsed["observations"]),
        evidence=parsed["evidence"],
        correction_instruction=parsed["correction_instruction"],
        correction_plan=CorrectionPlan(
            plan["tool"],
            tuple(tuple(point) for point in plan["positive_points"]),
            tuple(tuple(point) for point in plan["negative_points"]),
            plan["rationale"],
        ),
        model=model,
        prompt_version=prompt_version,
        latency_ms=latency,
        deterministic_overrides=tuple(parsed.pop("_deterministic_overrides", ())),
    )


def generate_correction_candidate(
    audit: WorkhorseAudit,
    *,
    source: np.ndarray,
    current_mask: np.ndarray,
    protected_neighbor: np.ndarray,
    refiner: CorrectionRefiner | None,
    output_path: Path,
    max_changed_fraction: float = 0.75,
    max_protected_overlap_fraction: float = 0.02,
) -> CandidateResult:
    """Execute a bounded SAM2 plan and persist a proposal, never an authoritative map edit."""
    before = np.asarray(current_mask).astype(bool)
    protected = np.asarray(protected_neighbor).astype(bool)
    if before.shape != source.shape[:2] or protected.shape != before.shape or not before.any():
        raise WorkhorseError("candidate inputs have invalid geometry or empty current mask")
    plan = audit.correction_plan
    if audit.verdict != "fail" or audit.confidence < 0.7:
        return _rejected(audit, before, "audit does not authorize a correction candidate")
    if plan.tool == "remove_small_components":
        labels, count = ndimage.label(before)
        ranked = sorted(
            range(1, count + 1),
            key=lambda index: int(np.count_nonzero(labels == index)),
            reverse=True,
        )
        allowed = max(1, int(get_ontology().label(audit.label).max_components))
        candidate = np.isin(labels, ranked[:allowed])
    elif plan.tool == "sam2_refine":
        if refiner is None:
            return _rejected(audit, before, "SAM2 correction refiner is unavailable")
        clicks = tuple(
            {"x": x, "y": y, "positive": positive}
            for positive, points in ((True, plan.positive_points), (False, plan.negative_points))
            for x, y in points
        )
        try:
            candidate = np.asarray(refiner(source, audit.label, clicks)).astype(bool)
        except Exception as exc:  # noqa: BLE001 - tool failures become reviewable evidence
            return _rejected(audit, before, f"SAM2 correction failed: {type(exc).__name__}: {exc}")
    else:
        return _rejected(audit, before, "audit selected no executable correction tool")
    if candidate.shape != before.shape or not candidate.any():
        return _rejected(audit, before, "SAM2 candidate is empty or has wrong dimensions")
    positive_ok = all(candidate[y, x] for x, y in plan.positive_points)
    negative_ok = all(not candidate[y, x] for x, y in plan.negative_points)
    changed = float(np.count_nonzero(candidate ^ before) / max(1, np.count_nonzero(before)))
    overlap = float(np.count_nonzero(candidate & protected) / max(1, np.count_nonzero(candidate)))
    if not positive_ok or not negative_ok:
        reason = "candidate violates VLM prompt polarity"
    elif changed > max_changed_fraction:
        reason = f"candidate changes too much of the prior ({changed:.4f})"
    elif overlap > max_protected_overlap_fraction:
        reason = f"candidate overlaps protected neighbors ({overlap:.4f})"
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_binary_mask(output_path, candidate.astype(np.uint8) * 255)
        return CandidateResult(
            "candidate_created",
            audit.label,
            str(output_path),
            int(before.sum()),
            int(candidate.sum()),
            changed,
            positive_ok,
            negative_ok,
            overlap,
            "bounded SAM2 proposal created; human review still required",
        )
    return CandidateResult(
        "candidate_rejected",
        audit.label,
        None,
        int(before.sum()),
        int(candidate.sum()),
        changed,
        positive_ok,
        negative_ok,
        overlap,
        reason,
    )


def verify_correction_candidate(
    client: OllamaClient,
    *,
    label: str,
    before: WorkhorseEvidence,
    after: WorkhorseEvidence,
    model: str,
    prompt_template: str,
    gpu_lock_path: Path,
    generation_options: dict[str, Any],
) -> CandidateVerification:
    """Blindly compare complete before/after evidence; uncertainty never promotes a candidate."""
    prompt = prompt_template.replace("<label>", label)
    started = time.perf_counter()
    parsed = None
    with GpuLock(path=gpu_lock_path, purpose="S11_vlm_workhorse_compare"):
        for attempt in range(2):
            raw = client.generate(
                model=model,
                prompt=(
                    prompt if attempt == 0 else prompt + "\nPrior output invalid. Exact JSON only."
                ),
                images=(*before.images, *after.images),
                options=generation_options,
                think=False,
            )
            parsed = _parse_verification(raw)
            if parsed is not None:
                break
    if parsed is None:
        parsed = {
            "decision": "uncertain",
            "confidence": 0.0,
            "fixed_problems": [],
            "remaining_problems": [],
            "before_observation": "Invalid comparison response.",
            "after_observation": "Invalid comparison response.",
            "evidence": "Candidate cannot be promoted for review preference.",
        }
    return CandidateVerification(
        label,
        parsed["decision"],
        float(parsed["confidence"]),
        tuple(parsed["fixed_problems"]),
        tuple(parsed["remaining_problems"]),
        parsed["before_observation"],
        parsed["after_observation"],
        parsed["evidence"],
        round((time.perf_counter() - started) * 1000),
    )


def write_workhorse_report(
    path: Path,
    *,
    audits: list[WorkhorseAudit],
    candidates: list[CandidateResult],
    verifications: list[CandidateVerification] | None = None,
) -> Path:
    verifications = verifications or []
    path = Path(path)
    report_root = path.parent
    candidate_documents = []
    for candidate in candidates:
        candidate_document = asdict(candidate)
        candidate_path = candidate_document.get("candidate_path")
        if candidate_path:
            try:
                candidate_document["candidate_path"] = (
                    Path(candidate_path).resolve().relative_to(report_root.resolve()).as_posix()
                )
            except ValueError:
                pass
        candidate_documents.append(candidate_document)
    document = {
        "schema_version": "1.0.0",
        "authority": "candidate_proposals_only_human_approval_required",
        "audit_count": len(audits),
        "candidate_created_count": sum(item.status == "candidate_created" for item in candidates),
        "audits": [_audit_document(item) for item in audits],
        "candidates": candidate_documents,
        "verifications": [
            asdict(item)
            | {
                "fixed_problems": list(item.fixed_problems),
                "remaining_problems": list(item.remaining_problems),
            }
            for item in verifications
        ],
    }
    document["sha256"] = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


_OBSERVATION_KEYS = {
    "full_context",
    "source_crop",
    "mask",
    "overlay",
    "contour",
    "neighbor_overlap",
}


def _parse_audit(raw: str, source_size: tuple[int, int]) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    required = {
        "verdict",
        "confidence",
        "problems",
        "observations",
        "evidence",
        "correction_instruction",
        "correction_plan",
    }
    if not isinstance(value, dict) or set(value) != required:
        return None
    if value["verdict"] not in {"pass", "fail", "uncertain"}:
        return None
    if isinstance(value["confidence"], bool) or not isinstance(value["confidence"], (int, float)):
        return None
    if not 0 <= value["confidence"] <= 1:
        return None
    problems = value["problems"]
    if (
        not isinstance(problems, list)
        or len(set(problems)) != len(problems)
        or not set(problems) <= ALLOWED_PROBLEMS
    ):
        return None
    observations = value["observations"]
    if not isinstance(observations, dict) or set(observations) != _OBSERVATION_KEYS:
        return None
    if any(not isinstance(text, str) or not text.strip() for text in observations.values()):
        return None
    if not isinstance(value["evidence"], str) or not isinstance(
        value["correction_instruction"], str
    ):
        return None
    plan = value["correction_plan"]
    if not isinstance(plan, dict) or set(plan) != {
        "tool",
        "positive_points",
        "negative_points",
        "rationale",
    }:
        return None
    if plan["tool"] not in {
        "none",
        "sam2_refine",
        "remove_small_components",
        "human_review",
    } or not isinstance(plan["rationale"], str):
        return None
    width, height = source_size
    for key in ("positive_points", "negative_points"):
        points = plan[key]
        if not isinstance(points, list) or len(points) > 12:
            return None
        for point in points:
            if (
                not isinstance(point, list)
                or len(point) != 2
                or any(isinstance(v, bool) or not isinstance(v, int) for v in point)
                or not 0 <= point[0] < width
                or not 0 <= point[1] < height
            ):
                return None
    if plan["tool"] == "sam2_refine" and not plan["positive_points"]:
        return None
    if value["verdict"] == "pass" and (problems or plan["tool"] != "none"):
        return None
    return value


def _parse_verification(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    required = {
        "decision",
        "confidence",
        "fixed_problems",
        "remaining_problems",
        "before_observation",
        "after_observation",
        "evidence",
    }
    if not isinstance(value, dict) or set(value) != required:
        return None
    if value["decision"] not in {"better", "worse", "no_material_change", "uncertain"}:
        return None
    if (
        isinstance(value["confidence"], bool)
        or not isinstance(value["confidence"], (int, float))
        or not 0 <= value["confidence"] <= 1
    ):
        return None
    for key in ("fixed_problems", "remaining_problems"):
        if not isinstance(value[key], list) or not set(value[key]) <= ALLOWED_PROBLEMS:
            return None
    if any(
        not isinstance(value[key], str) or not value[key].strip()
        for key in ("before_observation", "after_observation", "evidence")
    ):
        return None
    return value


def _rejected(audit: WorkhorseAudit, before: np.ndarray, reason: str) -> CandidateResult:
    return CandidateResult(
        "not_created", audit.label, None, int(before.sum()), None, None, False, False, None, reason
    )


def _evidence_metrics(evidence: WorkhorseEvidence) -> dict[str, float]:
    if evidence.metrics:
        return dict(evidence.metrics)
    with Image.open(evidence.images[2]) as opened:
        mask = np.asarray(opened.convert("L")) != 0
    labels, count = ndimage.label(mask)
    areas = sorted(
        (int(np.count_nonzero(labels == index)) for index in range(1, count + 1)), reverse=True
    )
    return {
        "mask_area_px": float(mask.sum()),
        "component_count": float(count),
        "largest_component_fraction": float(areas[0] / max(1, int(mask.sum()))) if areas else 0.0,
        "protected_overlap_px": 0.0,
    }


def _apply_deterministic_findings(
    parsed: dict[str, Any],
    label: str,
    evidence: WorkhorseEvidence,
    qa_findings: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    metrics = _evidence_metrics(evidence)
    maximum = int(get_ontology().label(label).max_components)
    components = int(metrics["component_count"])
    if components > maximum:
        updated = dict(parsed)
        updated["verdict"] = "fail"
        updated["confidence"] = max(float(parsed["confidence"]), 0.99)
        updated["problems"] = list(dict.fromkeys((*parsed["problems"], "other")))
        updated["evidence"] = (
            f"Deterministic topology found {components} components; ontology allows {maximum}."
        )
        updated["correction_instruction"] = (
            "Remove disconnected fragments outside the main anatomy."
        )
        updated["correction_plan"] = {
            "tool": "remove_small_components",
            "positive_points": [],
            "negative_points": [],
            "rationale": "Deterministic component count exceeds the ontology maximum.",
        }
        updated["_deterministic_overrides"] = ("component_count_exceeds_ontology",)
        return updated

    relevant = tuple(item for item in qa_findings if _finding_mentions_label(item, label))
    if not relevant:
        return parsed
    blockers = tuple(item for item in relevant if item.get("severity") == "BLOCK")
    updated = dict(parsed)
    updated["verdict"] = "fail" if blockers else "uncertain"
    updated["confidence"] = max(float(parsed["confidence"]), 0.99 if blockers else 0.0)
    updated["problems"] = list(dict.fromkeys((*parsed["problems"], "other")))
    summary = "; ".join(
        f'{item.get("id", "QA")}:{item.get("name", "finding")}:'
        f'{_bounded_text(str(item.get("message", "")), 80)}'
        for item in relevant
    )
    updated["evidence"] = _bounded_text(
        f"Independent auto-QA contradicts a clean pass for {label}: {summary}", 240
    )
    updated["correction_instruction"] = (
        "Resolve the cited independent QA finding and rerun all checks before approval."
    )
    updated["correction_plan"] = {
        "tool": "human_review",
        "positive_points": [],
        "negative_points": [],
        "rationale": "A semantic or geometric QA finding cannot be cleared by VLM confidence.",
    }
    updated["_deterministic_overrides"] = tuple(
        f'autoqa_{str(item.get("id", "unknown")).lower().replace("-", "_")}' for item in relevant
    )
    return updated


def _bounded_text(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    return value[: maximum - 3].rstrip() + "..."


def _finding_mentions_label(finding: dict[str, Any], label: str) -> bool:
    """Match a QA finding to one label without turning package-wide failures into part claims."""
    if finding.get("result") not in {"fail", "warn", "route"}:
        return False
    haystack = " ".join(
        str(finding.get(key, "")) for key in ("name", "message", "body_part", "label")
    )
    return (
        re.search(rf"(?<![a-z0-9_]){re.escape(label)}(?![a-z0-9_])", haystack.lower()) is not None
    )


def _audit_document(audit: WorkhorseAudit) -> dict[str, Any]:
    document = asdict(audit)
    document["problems"] = list(audit.problems)
    document["correction_plan"]["positive_points"] = [
        list(p) for p in audit.correction_plan.positive_points
    ]
    document["correction_plan"]["negative_points"] = [
        list(p) for p in audit.correction_plan.negative_points
    ]
    return document
