"""Governed multi-provider teacher judgments, candidate proposals, and gold-only learning."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import yaml
from PIL import Image, ImageDraw

from ..autonomy.repair import (
    evaluate_repair_candidate,
    normalized_roi_points_to_source,
)
from ..io.hashing import sha256_file
from ..io.png_strict import read_mask, write_binary_mask
from ..ontology import get_ontology
from ..qa.metrics import boundary_f, iou
from ..qa.panels import WorkhorseEvidence
from .client import ALLOWED_PROBLEMS
from .cloud_budget import DailyBudgetLedger
from .workhorse import CorrectionRefiner, WorkhorseAudit


class CloudTeacherError(RuntimeError):
    """Cloud-teacher evidence, authority, or provider output is unsafe or invalid."""


class CloudProviderRequestError(CloudTeacherError):
    """Provider transport failure with explicit billing certainty."""

    def __init__(self, message: str, *, definitely_unbilled: bool = False) -> None:
        super().__init__(message)
        self.definitely_unbilled = bool(definitely_unbilled)


@dataclass
class CloudJobQuota:
    """In-memory cap shared by every cloud cascade in one S11 image job."""

    maximum_calls_per_job: int
    maximum_calls_per_label: int
    calls: int = 0
    calls_by_label: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.maximum_calls_per_job <= 0 or self.maximum_calls_per_label <= 0:
            raise CloudTeacherError("cloud job call quotas must be positive")

    def claim(self, label: str) -> None:
        label_calls = self.calls_by_label.get(label, 0)
        if self.calls >= self.maximum_calls_per_job:
            raise CloudTeacherError("cloud maximum calls per S11 job reached")
        if label_calls >= self.maximum_calls_per_label:
            raise CloudTeacherError(f"cloud maximum calls per label reached: {label}")
        self.calls += 1
        self.calls_by_label[label] = label_calls + 1


@dataclass(frozen=True)
class TeacherCorrection:
    tool: str
    polygon: tuple[tuple[int, int], ...]
    positive_points: tuple[tuple[int, int], ...]
    negative_points: tuple[tuple[int, int], ...]
    rationale: str


@dataclass(frozen=True)
class TeacherUsage:
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass(frozen=True)
class TeacherJudgment:
    provider: str
    model: str
    verdict: str
    confidence: float
    defects: tuple[str, ...]
    observations: dict[str, str]
    evidence: str
    correction: TeacherCorrection
    usage: TeacherUsage
    latency_ms: int
    response_sha256: str


@dataclass(frozen=True)
class TeacherRequest:
    image_id: str
    instance_id: str
    label: str
    source_path: Path
    evidence: WorkhorseEvidence
    local_audit: WorkhorseAudit
    qa_findings: tuple[dict[str, Any], ...]
    correction_roi_xyxy: tuple[int, int, int, int] | None = None
    side_evidence: dict[str, Any] | None = None
    iteration_feedback: tuple[str, ...] = ()


@dataclass(frozen=True)
class TeacherCandidate:
    provider: str
    label: str
    status: str
    path: str | None
    before_iou: float | None
    changed_fraction: float | None
    protected_overlap_fraction: float | None
    reason: str


class TeacherProvider(Protocol):
    name: str
    model: str
    maximum_reserved_cost_usd: float

    def review(self, request: TeacherRequest, prompt: str) -> TeacherJudgment: ...


def load_cloud_teacher_config(path: Path = Path("configs/cloud_teacher.yaml")) -> dict:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    required = {
        "config_version",
        "enabled",
        "mode",
        "budget",
        "selection",
        "governance",
        "providers",
        "learning",
        "evaluation",
    }
    if not isinstance(document, dict) or set(document) != required:
        raise CloudTeacherError(f"cloud-teacher config requires exactly {sorted(required)}")
    if document["mode"] != "shadow_only":
        raise CloudTeacherError("cloud teachers may run only in shadow mode")
    governance = document["governance"]
    if any(
        governance[key] is not False
        for key in ("may_approve_gold", "may_clear_blocks", "may_write_authoritative_masks")
    ):
        raise CloudTeacherError("cloud-teacher authority boundary is invalid")
    budget = document["budget"]
    if not 0 < float(budget["operational_limit_usd"]) < float(budget["hard_limit_usd"]) < 20:
        raise CloudTeacherError("cloud hard limit must remain below $20/day")
    if float(budget["hard_limit_usd"]) + float(budget["emergency_reserve_usd"]) > 20:
        raise CloudTeacherError("cloud hard limit plus reserve exceeds $20/day")
    if not 1 <= int(budget["maximum_calls_per_job"]) <= 12:
        raise CloudTeacherError("cloud maximum_calls_per_job must be within 1..12")
    if not 1 <= int(budget["maximum_calls_per_label"]) <= int(budget["maximum_calls_per_job"]):
        raise CloudTeacherError("cloud maximum_calls_per_label is invalid")
    providers = document["providers"]
    expected_providers = {"gemini", "openai", "anthropic"}
    if not isinstance(providers, dict) or set(providers) != expected_providers:
        raise CloudTeacherError("cloud teacher requires the three governed provider slots")
    for name, settings in providers.items():
        if float(settings["maximum_reserved_cost_usd"]) <= 0:
            raise CloudTeacherError(f"{name} reservation must be positive")
        if float(settings["maximum_reserved_cost_usd"]) > float(budget["hard_limit_usd"]):
            raise CloudTeacherError(f"{name} reservation exceeds the daily hard limit")
        if (
            float(settings["input_usd_per_million"]) < 0
            or float(settings["output_usd_per_million"]) < 0
        ):
            raise CloudTeacherError(f"{name} token rates cannot be negative")
    selection = document["selection"]
    if not isinstance(selection.get("diagnosis_cascade_before_autonomous_convergence"), bool):
        raise CloudTeacherError("cloud diagnostic-cascade policy must be boolean")
    selected = {
        selection["primary_provider"],
        selection["disagreement_critic"],
        selection["tie_breaker"],
    }
    if selected != expected_providers:
        raise CloudTeacherError("provider cascade must name each governed provider exactly once")
    learning = document["learning"]
    if (
        learning["require_human_approved_gold"] is not True
        or learning["require_frozen_package"] is not True
        or learning["cloud_outputs_are_training_authority"] is not False
    ):
        raise CloudTeacherError("cloud learning authority boundary is invalid")
    evaluation = document["evaluation"]
    for key in (
        "minimum_serious_defect_recall",
        "minimum_overall_defect_recall",
        "minimum_precision",
        "maximum_false_pass_rate",
        "minimum_incremental_recall_over_local",
        "minimum_correction_usefulness",
    ):
        if not 0 <= float(evaluation[key]) <= 1:
            raise CloudTeacherError(f"cloud evaluation threshold must be 0..1: {key}")
    if int(evaluation["minimum_cases"]) < 200:
        raise CloudTeacherError("cloud incremental-value evaluation requires at least 200 cases")
    if (
        evaluation["require_frozen_human_truth"] is not True
        or evaluation["promotion_grants_mask_authority"] is not False
    ):
        raise CloudTeacherError("cloud evaluation authority boundary is invalid")
    return document


def verify_cloud_eligibility(
    *,
    registry_path: Path,
    image_id: str,
    provider: str,
    source_path: Path,
) -> dict:
    """Require explicit admission of one exact source hash for one named provider."""
    registry = yaml.safe_load(Path(registry_path).read_text(encoding="utf-8"))
    if registry.get("schema_version") != "1.0.0" or registry.get("default") != "deny":
        raise CloudTeacherError("cloud eligibility registry must be schema 1.0.0 and default deny")
    record = registry.get("images", {}).get(image_id)
    required = {
        "source_sha256",
        "content_lane",
        "content_compatibility",
        "rights_evidence",
        "approved_by",
        "approved_at",
        "providers",
    }
    if not isinstance(record, dict) or set(record) != required:
        raise CloudTeacherError(f"image is not explicitly cloud eligible: {image_id}")
    if (
        record["content_lane"]
        not in {
            "general",
            "adult_nonexplicit",
            "consensual_explicit_adult",
        }
        or record["content_compatibility"] != "allowed"
    ):
        raise CloudTeacherError("cloud transmission lacks an allowed content-lane decision")
    if not all(
        str(record[key]).strip() for key in ("rights_evidence", "approved_by", "approved_at")
    ):
        raise CloudTeacherError("cloud eligibility lacks rights or approval evidence")
    if provider not in record["providers"]:
        raise CloudTeacherError(f"provider is not approved for image {image_id}: {provider}")
    if sha256_file(source_path) != record["source_sha256"]:
        raise CloudTeacherError(f"cloud eligibility source hash mismatch: {image_id}")
    return record


def should_escalate_to_cloud(
    request: TeacherRequest,
    *,
    selection: dict,
    disagreement_fraction: float = 0,
) -> bool:
    if request.label in selection["always_escalate_labels"]:
        return True
    if request.local_audit.verdict in selection["escalate_local_verdicts"]:
        return True
    if selection["escalate_on_autoqa_nonpass"] and request.qa_findings:
        return True
    if selection["escalate_on_component_override"] and request.local_audit.deterministic_overrides:
        return True
    return disagreement_fraction >= float(selection["minimum_disagreement_fraction"])


def run_teacher_cascade(
    request: TeacherRequest,
    *,
    providers: dict[str, TeacherProvider],
    config: dict,
    budget: DailyBudgetLedger,
    prompt_template: str,
    report_path: Path,
    call_quota: CloudJobQuota | None = None,
) -> tuple[TeacherJudgment, ...]:
    """Run primary, disagreement critic, then tie-breaker without granting authority."""
    if config["enabled"] is not True:
        return ()
    if not should_escalate_to_cloud(request, selection=config["selection"]):
        return ()
    sequence = [
        config["selection"]["primary_provider"],
        config["selection"]["disagreement_critic"],
        config["selection"]["tie_breaker"],
    ]
    maximum = int(config["budget"]["maximum_calls_per_image"])
    judgments = []
    for provider_name in sequence[:maximum]:
        provider = providers.get(provider_name)
        settings = config["providers"].get(provider_name, {})
        if provider is None or settings.get("enabled") is not True:
            continue
        try:
            if call_quota is not None:
                call_quota.claim(request.label)
        except CloudTeacherError:
            break
        verify_cloud_eligibility(
            registry_path=Path(config["governance"]["eligibility_registry"]),
            image_id=request.image_id,
            provider=provider_name,
            source_path=request.source_path,
        )
        request_id = f"teach_{uuid.uuid4().hex}"
        budget.reserve(
            request_id=request_id,
            provider=provider.name,
            model=provider.model,
            image_id=request.image_id,
            label=request.label,
            maximum_cost_usd=provider.maximum_reserved_cost_usd,
        )
        try:
            judgment = provider.review(request, _teacher_prompt(request, prompt_template))
            budget.commit(
                request_id,
                actual_cost_usd=judgment.usage.cost_usd,
                input_tokens=judgment.usage.input_tokens,
                output_tokens=judgment.usage.output_tokens,
            )
        except Exception as exc:
            _reconcile_failed_dispatch(budget, request_id, provider, exc)
            continue
        judgments.append(judgment)
        if len(judgments) == 1 and _agrees_with_local(judgment, request.local_audit):
            break
        if (
            len(judgments) >= 2
            and _provider_consensus(judgments)
            and not any(_has_serious_defect(item) for item in judgments)
        ):
            break
    _write_teacher_report(report_path, request=request, judgments=judgments)
    return tuple(judgments)


def run_teacher_committee(
    request: TeacherRequest,
    *,
    providers: dict[str, TeacherProvider],
    config: dict,
    budget: DailyBudgetLedger,
    prompt_template: str,
    report_path: Path,
    call_quota: CloudJobQuota | None = None,
) -> tuple[TeacherJudgment, ...]:
    """Run every enabled provider for a final-candidate convergence decision.

    Unlike the cost-saving diagnosis cascade, this function never stops after the
    first agreement. It is reserved for a deterministic-QA-surviving candidate and
    remains bounded by the provider count, exact-image eligibility, and spend ledger.
    """
    if config["enabled"] is not True:
        return ()
    sequence = (
        config["selection"]["primary_provider"],
        config["selection"]["disagreement_critic"],
        config["selection"]["tie_breaker"],
    )
    judgments = []
    for provider_name in sequence:
        provider = providers.get(provider_name)
        settings = config["providers"].get(provider_name, {})
        if provider is None or settings.get("enabled") is not True:
            continue
        try:
            if call_quota is not None:
                call_quota.claim(request.label)
        except CloudTeacherError:
            break
        verify_cloud_eligibility(
            registry_path=Path(config["governance"]["eligibility_registry"]),
            image_id=request.image_id,
            provider=provider_name,
            source_path=request.source_path,
        )
        request_id = f"committee_{uuid.uuid4().hex}"
        budget.reserve(
            request_id=request_id,
            provider=provider.name,
            model=provider.model,
            image_id=request.image_id,
            label=request.label,
            maximum_cost_usd=provider.maximum_reserved_cost_usd,
        )
        try:
            judgment = provider.review(request, _teacher_prompt(request, prompt_template))
            budget.commit(
                request_id,
                actual_cost_usd=judgment.usage.cost_usd,
                input_tokens=judgment.usage.input_tokens,
                output_tokens=judgment.usage.output_tokens,
            )
        except Exception as exc:
            _reconcile_failed_dispatch(budget, request_id, provider, exc)
            continue
        judgments.append(judgment)
    _write_teacher_report(report_path, request=request, judgments=judgments)
    return tuple(judgments)


def _reconcile_failed_dispatch(
    budget: DailyBudgetLedger,
    request_id: str,
    provider: TeacherProvider,
    exc: Exception,
) -> None:
    if isinstance(exc, CloudProviderRequestError) and exc.definitely_unbilled:
        budget.release(
            request_id,
            error=f"definitely_unbilled_transport_failure:{type(exc).__name__}:{exc}",
        )
        return
    # Once a provider accepted a request or returned malformed content, usage cannot
    # be proven absent. Charge the full reservation so the ledger never understates it.
    budget.commit(
        request_id,
        actual_cost_usd=provider.maximum_reserved_cost_usd,
        input_tokens=0,
        output_tokens=0,
        error=f"unknown_usage_after_dispatch:{type(exc).__name__}:{exc}",
    )


def materialize_teacher_candidate(
    judgment: TeacherJudgment,
    *,
    request: TeacherRequest,
    current_mask: np.ndarray,
    protected_neighbor: np.ndarray,
    refiner: CorrectionRefiner | None,
    output_path: Path,
    max_changed_fraction: float = 0.75,
    max_protected_overlap_fraction: float = 0.02,
    reconstruction_max_changed_fraction: float = 2.0,
    maximum_outside_roi_fraction: float = 0.005,
    expected_area_slack: float = 0.5,
    person_bbox_xyxy: tuple[int, int, int, int] | None = None,
) -> TeacherCandidate:
    """Turn a cloud polygon/point plan into an isolated proposal under local safeguards."""
    before = np.asarray(current_mask).astype(bool)
    protected = np.asarray(protected_neighbor).astype(bool)
    if before.shape != protected.shape or before.shape != request.evidence.source_size[::-1]:
        raise CloudTeacherError("teacher candidate geometry differs from full source")
    if judgment.verdict != "fail" or judgment.confidence < 0.7:
        return _teacher_rejection(
            judgment, request.label, "teacher judgment does not authorize a proposal"
        )
    correction = judgment.correction
    roi = request.correction_roi_xyxy or (0, 0, before.shape[1], before.shape[0])
    if correction.tool == "polygon":
        if len(correction.polygon) < 3:
            return _teacher_rejection(
                judgment, request.label, "teacher polygon has fewer than three points"
            )
        candidate = _rasterize_normalized_polygon(correction.polygon, before.shape, roi_xyxy=roi)
    elif correction.tool == "points":
        if refiner is None or not correction.positive_points:
            return _teacher_rejection(
                judgment, request.label, "point correction requires SAM and positive points"
            )
        source_points = tuple(
            {"x": x, "y": y, "positive": polarity}
            for polarity, points in (
                (True, correction.positive_points),
                (False, correction.negative_points),
            )
            for x, y in normalized_roi_points_to_source(points, roi, before.shape)
        )
        source = np.asarray(Image.open(request.source_path).convert("RGB"))
        refine_roi = getattr(refiner, "refine_roi", None)

        def execute(points: tuple[dict[str, Any], ...]) -> np.ndarray:
            return np.asarray(
                refine_roi(source, request.label, points, roi_xyxy=roi)
                if callable(refine_roi)
                else refiner(source, request.label, points)
            ).astype(bool)

        try:
            predicted = execute(source_points)
        except Exception as exc:  # noqa: BLE001 - an unsafe tool result is a rejected proposal
            return _teacher_rejection(
                judgment,
                request.label,
                f"SAM correction failed: {type(exc).__name__}: {str(exc)[:200]}",
            )
        additive_defects = {"boundary_too_tight", "missing_visible_area"}
        additive = bool(judgment.defects) and set(judgment.defects) <= additive_defects
        fallback_errors = []
        if additive:
            # A reviewer asking to add missing boundary pixels is defining a delta,
            # not authorizing replacement of the already-good interior. If a joint
            # multi-point prompt misses one requested location, retry only that point
            # against the cached embedding and union its anchored component.
            for point in (item for item in source_points if item["positive"]):
                if not predicted[int(point["y"]), int(point["x"])]:
                    try:
                        predicted |= execute((point,))
                    except Exception as exc:  # noqa: BLE001 - preserve the original safe mask
                        fallback_errors.append(f"{type(exc).__name__}:{str(exc)[:120]}")
            candidate = before | predicted
        else:
            candidate = predicted
        if any(
            bool(candidate[int(point["y"]), int(point["x"])]) != bool(point["positive"])
            for point in source_points
        ):
            return _teacher_rejection(
                judgment,
                request.label,
                "SAM candidate violates a teacher correction point"
                + (f"; fallback_errors={fallback_errors}" if fallback_errors else ""),
            )
    else:
        return _teacher_rejection(
            judgment, request.label, "teacher selected no executable correction"
        )
    if candidate.shape != before.shape or not candidate.any():
        return _teacher_rejection(
            judgment, request.label, "teacher candidate is empty or wrong-sized"
        )
    guard = evaluate_repair_candidate(
        candidate,
        current_mask=before,
        protected_mask=protected,
        label=request.label,
        roi_xyxy=roi,
        person_bbox_xyxy=person_bbox_xyxy,
        ordinary_max_changed_fraction=max_changed_fraction,
        reconstruction_max_changed_fraction=reconstruction_max_changed_fraction,
        maximum_protected_overlap_fraction=max_protected_overlap_fraction,
        maximum_outside_roi_fraction=maximum_outside_roi_fraction,
        expected_area_slack=expected_area_slack,
    )
    if not guard.eligible:
        return _teacher_rejection(
            judgment,
            request.label,
            "repair candidate vetoed: " + ",".join(guard.vetoes),
        )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_binary_mask(output_path, candidate.astype(np.uint8) * 255)
    return TeacherCandidate(
        judgment.provider,
        request.label,
        "candidate_created",
        str(output_path),
        None,
        guard.changed_fraction,
        guard.protected_overlap_fraction,
        "isolated cloud-teacher proposal; human approval required",
    )


def harvest_human_teacher_resolution(
    *,
    package_root: Path,
    teacher_report_path: Path,
    output_path: Path,
) -> dict:
    """Create a distillation record only from a frozen, fully human-approved gold package."""
    package = Path(package_root)
    if not (package / ".maskfactory_frozen.json").is_file():
        raise CloudTeacherError("teacher learning requires a frozen package")
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    review = manifest.get("review", {})
    if not review.get("reviewer") or manifest.get("qa", {}).get("qa_overall") != "pass":
        raise CloudTeacherError("teacher learning requires human review and passing gold QA")
    report = json.loads(Path(teacher_report_path).read_text(encoding="utf-8"))
    label = str(report["label"])
    part = manifest.get("parts", {}).get(label, {})
    if part.get("status") != "human_approved_gold":
        raise CloudTeacherError(f"teacher learning label is not human-approved gold: {label}")
    gold_path = package / "masks" / f"{label}.png"
    if not gold_path.is_file():
        raise CloudTeacherError(f"human-approved teacher target mask is missing: {gold_path}")
    baseline_path = package / "annotations" / "draft_baseline" / "masks" / f"{label}.png"
    gold = read_mask(gold_path) > 0
    baseline = read_mask(baseline_path) > 0 if baseline_path.is_file() else None
    review_draft_path = (
        package / "annotations" / "autonomy" / "autonomy_review_draft" / "label_map_part.png"
    )
    review_draft = None
    if review_draft_path.is_file():
        label_id = int(get_ontology().label(label).id)
        review_draft = np.asarray(Image.open(review_draft_path)) == label_id
        if review_draft.shape != gold.shape:
            raise CloudTeacherError("autonomy review draft dimensions differ from human gold")
    baseline_changed_pixels = (
        int(np.count_nonzero(baseline != gold)) if baseline is not None else None
    )
    review_draft_changed_pixels = (
        int(np.count_nonzero(review_draft != gold)) if review_draft is not None else None
    )
    record = {
        "schema_version": "1.0.0",
        "record_id": hashlib.sha256(
            f'{manifest["image_id"]}:{package.name}:{label}:{sha256_file(gold_path)}'.encode()
        ).hexdigest(),
        "image_id": manifest["image_id"],
        "instance_id": package.name if package.name.startswith("p") else "p0",
        "label": label,
        "reviewer": review["reviewer"],
        "approved_at": review["approved_at"],
        "gold_mask": str(gold_path),
        "gold_sha256": sha256_file(gold_path),
        "baseline_sha256": sha256_file(baseline_path) if baseline_path.is_file() else None,
        "baseline_iou": iou(baseline, gold) if baseline is not None else None,
        "baseline_boundary_f1": boundary_f(baseline, gold) if baseline is not None else None,
        "baseline_changed_pixels_to_gold": baseline_changed_pixels,
        "review_draft_sha256": (
            sha256_file(review_draft_path) if review_draft is not None else None
        ),
        "review_draft_iou": (iou(review_draft, gold) if review_draft is not None else None),
        "review_draft_boundary_f1": (
            boundary_f(review_draft, gold) if review_draft is not None else None
        ),
        "review_draft_changed_pixels_to_gold": review_draft_changed_pixels,
        "machine_changed_pixels_from_baseline": (
            int(np.count_nonzero(review_draft != baseline))
            if review_draft is not None and baseline is not None
            else None
        ),
        "human_correction_pixels_avoided": (
            baseline_changed_pixels - review_draft_changed_pixels
            if baseline_changed_pixels is not None and review_draft_changed_pixels is not None
            else None
        ),
        "review_time_sec": review.get("review_time_sec"),
        "human_truth_verdict": (
            "pass"
            if baseline is not None
            and iou(baseline, gold) >= 0.995
            and boundary_f(baseline, gold) >= 0.99
            else "fail"
        ),
        "teacher_report": str(teacher_report_path),
        "teacher_report_sha256": sha256_file(teacher_report_path),
        "teacher_judgments": report["judgments"],
        "authority": "human_approved_gold_only",
    }
    _append_unique_jsonl(Path(output_path), record, identity=record["record_id"])
    return record


def build_teacher_distillation_manifest(
    *,
    records_path: Path,
    output_path: Path,
    minimum_prompt_records: int,
    minimum_lora_records: int,
    holdout_fraction: float = 0.20,
) -> dict:
    """Create an image-disjoint, balanced readiness manifest from human-gold resolutions."""
    if not 0.1 <= holdout_fraction <= 0.5:
        raise CloudTeacherError("teacher holdout fraction must be 0.1..0.5")
    records = []
    if Path(records_path).is_file():
        for number, line in enumerate(
            Path(records_path).read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CloudTeacherError(f"invalid teacher learning row {number}: {exc}") from exc
            if (
                record.get("authority") != "human_approved_gold_only"
                or record.get("human_truth_verdict") not in {"pass", "fail"}
                or not record.get("record_id")
                or not record.get("image_id")
            ):
                raise CloudTeacherError(f"teacher learning row {number} lacks gold authority")
            records.append(record)
    by_image: dict[str, list[dict]] = {}
    for record in records:
        by_image.setdefault(str(record["image_id"]), []).append(record)
    holdout_images = {
        image_id
        for image_id in by_image
        if int(hashlib.sha256(image_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        < holdout_fraction
    }
    if by_image and not holdout_images:
        holdout_images.add(sorted(by_image)[-1])
    if len(by_image) > 1 and holdout_images == set(by_image):
        holdout_images.remove(sorted(holdout_images)[0])
    train = [record for record in records if record["image_id"] not in holdout_images]
    holdout = [record for record in records if record["image_id"] in holdout_images]
    truth_counts = {
        verdict: sum(record["human_truth_verdict"] == verdict for record in train)
        for verdict in ("pass", "fail")
    }

    def balanced_ready(minimum: int) -> bool:
        per_class = max(1, minimum // 4)
        return len(train) >= minimum and all(count >= per_class for count in truth_counts.values())

    providers = sorted(
        {
            str(judgment.get("provider"))
            for record in records
            for judgment in record.get("teacher_judgments", ())
            if judgment.get("provider")
        }
    )
    document = {
        "schema_version": "1.0.0",
        "authority": "human_approved_gold_only",
        "source_records": str(records_path),
        "record_count": len(records),
        "image_count": len(by_image),
        "training_record_ids": sorted(record["record_id"] for record in train),
        "holdout_record_ids": sorted(record["record_id"] for record in holdout),
        "holdout_image_ids": sorted(holdout_images),
        "training_truth_counts": truth_counts,
        "providers_observed": providers,
        "prompt_exemplars_ready": balanced_ready(minimum_prompt_records),
        "lora_candidate_ready": balanced_ready(minimum_lora_records),
        "lora_authority": "candidate_only_requires_frozen_eval_and_explicit_promotion",
    }
    document["sha256"] = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return document


def parse_teacher_judgment(
    raw: str,
    *,
    provider: str,
    model: str,
    usage: TeacherUsage,
    latency_ms: int,
) -> TeacherJudgment:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CloudTeacherError(f"{provider} returned invalid JSON") from exc
    required = {"verdict", "confidence", "defects", "observations", "evidence", "correction"}
    observation_keys = {
        "full_context",
        "source_crop",
        "mask",
        "overlay",
        "contour",
        "neighbor_overlap",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise CloudTeacherError("teacher judgment has the wrong top-level shape")
    if value["verdict"] not in {"pass", "fail", "uncertain"}:
        raise CloudTeacherError("teacher verdict is invalid")
    confidence = value["confidence"]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        raise CloudTeacherError("teacher confidence is invalid")
    defects = value["defects"]
    if (
        not isinstance(defects, list)
        or len(set(defects)) != len(defects)
        or not set(defects) <= ALLOWED_PROBLEMS
    ):
        raise CloudTeacherError("teacher defects violate the closed taxonomy")
    observations = value["observations"]
    if (
        not isinstance(observations, dict)
        or set(observations) != observation_keys
        or any(not isinstance(text, str) or not text.strip() for text in observations.values())
    ):
        raise CloudTeacherError("teacher must make six nonempty observations")
    correction = _parse_correction(value["correction"])
    if value["verdict"] == "pass" and (defects or correction.tool != "none"):
        raise CloudTeacherError("teacher pass cannot include defects or correction")
    return TeacherJudgment(
        provider,
        model,
        value["verdict"],
        float(confidence),
        tuple(defects),
        observations,
        str(value["evidence"]),
        correction,
        usage,
        int(latency_ms),
        hashlib.sha256(raw.encode()).hexdigest(),
    )


def _parse_correction(value: Any) -> TeacherCorrection:
    required = {"tool", "polygon", "positive_points", "negative_points", "rationale"}
    if not isinstance(value, dict) or set(value) != required:
        raise CloudTeacherError("teacher correction has the wrong shape")
    if value["tool"] not in {"none", "polygon", "points", "human_review"}:
        raise CloudTeacherError("teacher correction tool is invalid")
    parsed = []
    for key, limit in (("polygon", 256), ("positive_points", 12), ("negative_points", 12)):
        points = value[key]
        if not isinstance(points, list) or len(points) > limit:
            raise CloudTeacherError(f"teacher {key} exceeds its point limit")
        output = []
        for point in points:
            if (
                not isinstance(point, list)
                or len(point) != 2
                or any(isinstance(item, bool) or not isinstance(item, int) for item in point)
                or any(not 0 <= item <= 1000 for item in point)
            ):
                raise CloudTeacherError(f"teacher {key} contains an invalid normalized point")
            output.append(tuple(point))
        parsed.append(tuple(output))
    polygon, positive, negative = parsed
    if value["tool"] == "polygon" and len(polygon) < 3:
        raise CloudTeacherError("polygon correction requires three or more points")
    if value["tool"] == "points" and not positive:
        raise CloudTeacherError("point correction requires a positive point")
    return TeacherCorrection(value["tool"], polygon, positive, negative, str(value["rationale"]))


def _teacher_prompt(request: TeacherRequest, template: str) -> str:
    roi = request.correction_roi_xyxy or (
        0,
        0,
        request.evidence.source_size[0],
        request.evidence.source_size[1],
    )
    ontology = get_ontology()
    definition = ontology.label(request.label)
    ontology_contract = {
        "side": definition.side,
        "parent_union": definition.parent_union,
        "expected_area_pct_range": definition.expected_area_pct_range,
        "max_components": definition.max_components,
        "boundary_rule": definition.boundary_rule,
        "boundary_rule_text": ontology.boundary_rule_text(definition.boundary_rule),
    }
    fields = (
        template.replace("<label>", request.label),
        f"IMAGE_ID: {request.image_id}; INSTANCE: {request.instance_id}.",
        f"FULL SOURCE SIZE: {list(request.evidence.source_size)}.",
        f"TARGET CROP XYXY: {list(request.evidence.crop_xyxy)}.",
        (
            f"CORRECTION ROI XYXY: {list(roi)}. Correction coordinates are normalized "
            "0..1000 inside this ROI, not inside the full image or diagnostic thumbnail."
        ),
        "POSE-CHAIN CHARACTER-SIDE EVIDENCE: "
        + json.dumps(
            request.side_evidence or {"status": "unavailable"},
            sort_keys=True,
            separators=(",", ":"),
        ),
        (
            "SIDE CONTRACT: When pose-chain evidence is available, COCO semantic joint "
            "identity controls character left/right. Never reverse it from viewer position."
        ),
        "ONTOLOGY CONTRACT: "
        + json.dumps(ontology_contract, sort_keys=True, separators=(",", ":")),
        (
            "BOUNDARY CONTRACT IS LITERAL: reject a parent-union silhouette that crosses the "
            "named anatomical split. hand_mcp means hand_base excludes every finger beginning "
            "at the MCP line. foot_mtp means foot_base excludes visible toes beginning at the "
            "MTP line; toes are a separate atomic mask. Never pass a whole hand as hand_base or "
            "a whole bare foot as foot_base."
        ),
        "SPECIALIST PROPOSAL EVIDENCE (proposal only, never truth): "
        + json.dumps(
            dict(request.evidence.specialist_metadata),
            sort_keys=True,
            separators=(",", ":"),
        ),
        "PRIOR REPAIR EXECUTION FEEDBACK: "
        + json.dumps(request.iteration_feedback, sort_keys=True, separators=(",", ":")),
        (
            "If a prior plan was rejected, do not repeat it unchanged. Choose a safer alternate "
            "point/polygon plan, or pass/uncertain if no executable correction is justified."
        ),
        "LOCAL AUDIT (not authoritative): "
        + json.dumps(
            {
                "model_verdict": request.local_audit.model_verdict,
                "final_verdict": request.local_audit.verdict,
                "confidence": request.local_audit.confidence,
                "problems": request.local_audit.problems,
                "deterministic_overrides": request.local_audit.deterministic_overrides,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        "AUTO-QA NON-PASS FINDINGS: "
        + json.dumps(request.qa_findings[:20], sort_keys=True, separators=(",", ":")),
    )
    return "\n".join(fields)


def _agrees_with_local(judgment: TeacherJudgment, local: WorkhorseAudit) -> bool:
    return judgment.verdict == local.verdict and (
        judgment.verdict != "pass" or not local.deterministic_overrides
    )


def _provider_consensus(judgments: list[TeacherJudgment]) -> bool:
    return len({item.verdict for item in judgments}) == 1


def _has_serious_defect(judgment: TeacherJudgment) -> bool:
    serious = {
        "wrong_part",
        "wrong_side",
        "includes_clothing_as_skin",
        "includes_neighbor_part",
        "missing_visible_area",
        "mask_on_hidden_area",
        "finger_merge",
        "occlusion_error",
    }
    return judgment.verdict == "fail" and bool(set(judgment.defects) & serious)


def _rasterize_normalized_polygon(
    points,
    shape: tuple[int, int],
    *,
    roi_xyxy: tuple[int, int, int, int] | None = None,
) -> np.ndarray:
    height, width = shape
    roi = roi_xyxy or (0, 0, width, height)
    pixels = list(normalized_roi_points_to_source(tuple(points), roi, shape))
    image = Image.new("L", (width, height), 0)
    ImageDraw.Draw(image).polygon(pixels, fill=255)
    return np.asarray(image) != 0


def _normalized_to_pixels(points, size: tuple[int, int]) -> tuple[tuple[int, int], ...]:
    width, height = size
    return tuple(
        (
            min(width - 1, round(x * (width - 1) / 1000)),
            min(height - 1, round(y * (height - 1) / 1000)),
        )
        for x, y in points
    )


def _teacher_rejection(judgment: TeacherJudgment, label: str, reason: str) -> TeacherCandidate:
    return TeacherCandidate(judgment.provider, label, "not_created", None, None, None, None, reason)


def _write_teacher_report(path: Path, *, request: TeacherRequest, judgments) -> Path:
    document = {
        "schema_version": "1.0.0",
        "authority": "shadow_advisory_human_approval_required",
        "image_id": request.image_id,
        "instance_id": request.instance_id,
        "label": request.label,
        "source_sha256": sha256_file(request.source_path),
        "local_audit": {
            "model": request.local_audit.model,
            "model_verdict": request.local_audit.model_verdict,
            "final_verdict": request.local_audit.verdict,
            "deterministic_overrides": list(request.local_audit.deterministic_overrides),
        },
        "judgments": [_judgment_document(item) for item in judgments],
    }
    document["sha256"] = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _judgment_document(judgment: TeacherJudgment) -> dict:
    value = asdict(judgment)
    value["defects"] = list(judgment.defects)
    for key in ("polygon", "positive_points", "negative_points"):
        value["correction"][key] = [list(point) for point in getattr(judgment.correction, key)]
    return value


def _append_unique_jsonl(path: Path, document: dict, *, identity: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + 5
    fd = None
    while fd is None:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise CloudTeacherError(f"teacher learning lock remained busy: {lock}")
            time.sleep(0.05)
    try:
        os.close(fd)
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip() and json.loads(line).get("record_id") == identity:
                    return
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        lock.unlink(missing_ok=True)


__all__ = [
    "CloudJobQuota",
    "CloudProviderRequestError",
    "CloudTeacherError",
    "TeacherCandidate",
    "TeacherCorrection",
    "TeacherJudgment",
    "TeacherProvider",
    "TeacherRequest",
    "TeacherUsage",
    "harvest_human_teacher_resolution",
    "build_teacher_distillation_manifest",
    "load_cloud_teacher_config",
    "materialize_teacher_candidate",
    "parse_teacher_judgment",
    "run_teacher_cascade",
    "run_teacher_committee",
    "should_escalate_to_cloud",
    "verify_cloud_eligibility",
]
