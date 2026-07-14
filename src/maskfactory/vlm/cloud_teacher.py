"""Governed multi-provider teacher judgments, candidate proposals, and gold-only learning."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import yaml
from PIL import Image, ImageDraw

from ..io.hashing import sha256_file
from ..io.png_strict import read_mask, write_binary_mask
from ..qa.metrics import boundary_f, iou
from ..qa.panels import WorkhorseEvidence
from .client import ALLOWED_PROBLEMS
from .cloud_budget import DailyBudgetLedger
from .workhorse import CorrectionRefiner, WorkhorseAudit


class CloudTeacherError(RuntimeError):
    """Cloud-teacher evidence, authority, or provider output is unsafe or invalid."""


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
        "age_safety",
        "rights_evidence",
        "approved_by",
        "approved_at",
        "providers",
    }
    if not isinstance(record, dict) or set(record) != required:
        raise CloudTeacherError(f"image is not explicitly cloud eligible: {image_id}")
    if record["age_safety"] != "clear_adult":
        raise CloudTeacherError("cloud transmission requires clear_adult authority")
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
            # Once dispatch begins we cannot prove a failed/malformed response was
            # unbilled. Charge the full reservation so spend can never be understated.
            budget.commit(
                request_id,
                actual_cost_usd=provider.maximum_reserved_cost_usd,
                input_tokens=0,
                output_tokens=0,
                error=f"unknown_usage_after_dispatch:{type(exc).__name__}:{exc}",
            )
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
    if correction.tool == "polygon":
        if len(correction.polygon) < 3:
            return _teacher_rejection(
                judgment, request.label, "teacher polygon has fewer than three points"
            )
        candidate = _rasterize_normalized_polygon(correction.polygon, before.shape)
    elif correction.tool == "points":
        if refiner is None or not correction.positive_points:
            return _teacher_rejection(
                judgment, request.label, "point correction requires SAM and positive points"
            )
        clicks = tuple(
            {"x": x, "y": y, "positive": polarity}
            for polarity, points in (
                (True, correction.positive_points),
                (False, correction.negative_points),
            )
            for x, y in _normalized_to_pixels(points, request.evidence.source_size)
        )
        source = np.asarray(Image.open(request.source_path).convert("RGB"))
        candidate = np.asarray(refiner(source, request.label, clicks)).astype(bool)
    else:
        return _teacher_rejection(
            judgment, request.label, "teacher selected no executable correction"
        )
    if candidate.shape != before.shape or not candidate.any():
        return _teacher_rejection(
            judgment, request.label, "teacher candidate is empty or wrong-sized"
        )
    changed = float(np.count_nonzero(candidate ^ before) / max(1, int(before.sum())))
    overlap = float(np.count_nonzero(candidate & protected) / max(1, int(candidate.sum())))
    if changed > max_changed_fraction:
        return _teacher_rejection(
            judgment, request.label, f"candidate changes too much ({changed:.6f})"
        )
    if overlap > max_protected_overlap_fraction:
        return _teacher_rejection(
            judgment, request.label, f"candidate overlaps protected anatomy ({overlap:.6f})"
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
        changed,
        overlap,
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
    return (
        template.replace("<label>", request.label)
        + f"\nIMAGE_ID: {request.image_id}; INSTANCE: {request.instance_id}."
        + f"\nFULL SOURCE SIZE: {list(request.evidence.source_size)}."
        + f"\nTARGET CROP XYXY: {list(request.evidence.crop_xyxy)}."
        + "\nLOCAL AUDIT (not authoritative): "
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
        )
        + "\nAUTO-QA NON-PASS FINDINGS: "
        + json.dumps(request.qa_findings[:20], sort_keys=True, separators=(",", ":"))
    )


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


def _rasterize_normalized_polygon(points, shape: tuple[int, int]) -> np.ndarray:
    height, width = shape
    pixels = [
        (
            min(width - 1, round(x * (width - 1) / 1000)),
            min(height - 1, round(y * (height - 1) / 1000)),
        )
        for x, y in points
    ]
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
    "should_escalate_to_cloud",
    "verify_cloud_eligibility",
]
