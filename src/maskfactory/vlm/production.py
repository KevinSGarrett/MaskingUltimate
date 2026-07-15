"""Production S11 panel generation, calibration gating, local review, and routing."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np
import yaml
from PIL import Image

from ..autonomy.adapters import MaskCandidateInput, build_mask_candidate_evidence
from ..autonomy.calibration import (
    build_autonomy_pipeline_fingerprint,
    load_autonomy_config,
)
from ..autonomy.lifecycle import (
    certificate_is_revoked,
    load_scoped_certificate,
    write_lifecycle_sidecar,
)
from ..autonomy.repair import (
    atomic_boundary_vetoes,
    build_pose_side_evidence,
    immutable_protected_union,
    load_repair_regions,
    merge_specialist_repair_regions,
)
from ..autonomy.review_draft import (
    CandidateQaOutcome,
    MapQaValidator,
    ReviewDraftSelection,
    build_autonomous_review_draft,
    compose_candidate_map,
    compose_candidate_map_transactional,
    select_pre_review_candidate,
)
from ..autonomy.tournament import run_candidate_tournament
from ..gpu import GpuLock
from ..io.png_strict import write_binary_mask, write_label_map
from ..ontology import get_ontology
from ..providers.civitai_auxiliary import load_auxiliary_s11_evidence
from ..qa.failure_mining import append_failure_once, make_failure_record
from ..qa.panels import render_boundary_panel, render_part_overlays, render_workhorse_evidence
from ..validation import ArtifactValidationError, validate_document
from .client import OllamaClient, VlmVerdict, append_verdict, prepare_panel_input, review_part
from .cloud_budget import DailyBudgetLedger
from .cloud_providers import build_teacher_providers
from .cloud_teacher import (
    CloudJobQuota,
    TeacherProvider,
    TeacherRequest,
    load_cloud_teacher_config,
    materialize_teacher_candidate,
    run_teacher_cascade,
    run_teacher_committee,
)
from .eval import VlmEvalError, require_current_gate
from .router import route
from .workhorse import (
    CorrectionRefiner,
    generate_correction_candidate,
    review_part_workhorse,
    verify_correction_candidate,
    write_workhorse_report,
)

GateChecker = Callable[..., dict]


def run_s11_production(
    *,
    source_crop_path: Path,
    part_map_path: Path,
    s10_report_path: Path,
    output_dir: Path,
    gate_path: Path,
    client: OllamaClient | None = None,
    config_path: Path = Path("configs/vlm.yaml"),
    prompt_path: Path = Path("src/maskfactory/vlm/prompts/p_part.txt"),
    gate_checker: GateChecker = require_current_gate,
    failure_queue_path: Path | None = None,
    pose_angle: str | None = None,
    failure_instance_id: str = "p0",
    workhorse_enabled: bool = False,
    correction_refiner: CorrectionRefiner | None = None,
    auto_load_correction_refiner: bool = False,
    cloud_teacher_config_path: Path = Path("configs/cloud_teacher.yaml"),
    teacher_providers: dict[str, TeacherProvider] | None = None,
    teacher_budget: DailyBudgetLedger | None = None,
    autonomy_config_path: Path = Path("configs/autonomous_masks.yaml"),
    autonomy_context: str = "solo",
    autonomy_certificate_root: Path = Path("qa/autonomy/certificates"),
    autonomy_revocations_root: Path = Path("qa/autonomy/revocations"),
    map_qa_validator: MapQaValidator | None = None,
    auxiliary_dir: Path | None = None,
    repair_hints_path: Path | None = None,
    person_bbox_xyxy: tuple[int, int, int, int] | None = None,
    labels_to_review: tuple[str, ...] | None = None,
    pose_path: Path | None = None,
    context_origin_xy: tuple[int, int] = (0, 0),
) -> dict:
    """Run gated local VLM review, or safely route every part when the gate is unavailable."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    qa_report_path = output_dir / "qa_report.json"
    shutil.copy2(s10_report_path, qa_report_path)
    report = json.loads(qa_report_path.read_text(encoding="utf-8"))
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    cloud_config = load_cloud_teacher_config(cloud_teacher_config_path)
    if Path(cloud_teacher_config_path) == Path("configs/cloud_teacher.yaml") and bool(
        config["runtime"].get("cloud_enabled", False)
    ) != bool(cloud_config["enabled"]):
        raise ValueError("vlm/cloud-teacher enable controls disagree")
    autonomy_config = load_autonomy_config(autonomy_config_path)
    autonomy_status = {
        "enabled": autonomy_config["enabled"],
        "mode": autonomy_config["mode"],
        "status": "residual_human_queue",
        "reason": "no_valid_label_context_calibration_certificate",
        "uncalibrated_status": autonomy_config["operations"]["uncalibrated_status"],
        "calibrated_status": autonomy_config["operations"]["calibrated_status"],
        "authoritative_gold": False,
    }
    model = config["models"]["primary_vlm"]
    prompt_version = config["prompts"]["p_part"]["version"]
    generation_options = config["runtime"]["generation_options"]
    prompt_template = Path(prompt_path).read_text(encoding="utf-8")
    if workhorse_enabled and config.get("workhorse", {}).get("enabled") is True:
        prompt_path = Path(config["prompts"]["p_workhorse"]["path"])
        prompt_version = config["prompts"]["p_workhorse"]["version"]
        generation_options = config["workhorse"]["generation_options"]
    report["vlm_review"] = {"model": model, "verdicts": []}
    qa_report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    part_map = np.asarray(Image.open(part_map_path))
    source = Image.open(source_crop_path).convert("RGB")
    authority = get_ontology()
    masks = {
        label.name: part_map == int(label.id)
        for label in authority.labels_for_map("part", enabled_only=True)
        if label.id and np.any(part_map == int(label.id))
    }
    auxiliary = (
        load_auxiliary_s11_evidence(Path(auxiliary_dir), part_map.shape)
        if auxiliary_dir is not None and Path(auxiliary_dir).is_dir()
        else None
    )
    auxiliary_protected = (
        auxiliary.protected_union if auxiliary is not None else np.zeros(part_map.shape, dtype=bool)
    )
    pose_document = (
        json.loads(Path(pose_path).read_text(encoding="utf-8"))
        if pose_path is not None and Path(pose_path).is_file()
        else None
    )
    repair_policy = autonomy_config["repair"]
    repair_regions = load_repair_regions(
        repair_hints_path,
        image_shape=part_map.shape,
        padding_fraction=float(repair_policy["roi_padding_fraction"]),
    )
    if auxiliary is not None:
        combined_region_metadata = {
            label: tuple(
                (
                    *auxiliary.label_metadata.get(label, ()),
                    *auxiliary.support_metadata.get(label, ()),
                )
            )
            for label in set(auxiliary.label_metadata) | set(auxiliary.support_metadata)
        }
        repair_regions = merge_specialist_repair_regions(
            repair_regions,
            label_metadata=combined_region_metadata,
            image_shape=part_map.shape,
            padding_fraction=float(repair_policy["roi_padding_fraction"]),
        )
    immutable_protected = immutable_protected_union(
        part_map, auxiliary_protected=auxiliary_protected
    )
    immutable_label_ids = tuple(
        int(authority.label(name).id)
        for name in repair_policy["immutable_labels"]
        if authority.label(name).id is not None
    )
    full_repair_roi = (0, 0, part_map.shape[1], part_map.shape[0])
    # Area sanity is meaningful only when the caller supplies the promoted-person
    # bbox. Test/ad-hoc callers without it retain the legacy geometry-only behavior.
    effective_person_bbox = person_bbox_xyxy
    if (
        workhorse_enabled
        and config.get("workhorse", {}).get("enabled") is True
        and auxiliary is not None
    ):
        for label, specialist_mask in auxiliary.part_candidates.items():
            if label not in masks and specialist_mask.any():
                # Preserve the actual empty S09 baseline while allowing a specialist to expose a
                # potentially missing label to S11, the tournament, and the human review route.
                masks[label] = np.zeros(part_map.shape, dtype=bool)
    if labels_to_review is not None:
        requested = set(labels_to_review)
        if not requested:
            raise ValueError("S11 label filter cannot be empty")
        for label in requested:
            authority.label(label, require_enabled=True)
        masks = {label: mask for label, mask in masks.items() if label in requested}
        if set(masks) != requested:
            missing = sorted(requested - set(masks))
            raise ValueError(
                f"S11 requested labels have no baseline or specialist proposal: {missing}"
            )
    specialist_disagreement_threshold = float(
        config.get("workhorse", {}).get("specialist_disagreement_fraction", 0.03)
    )
    viz = yaml.safe_load(Path("configs/viz.yaml").read_text(encoding="utf-8"))
    render_part_overlays(
        source,
        part_map,
        output_dir / "qa_panels",
        label_colors=viz["label_colors"],
    )
    panels: dict[str, Path] = {}
    for label, mask in sorted(masks.items()):
        panel_target = mask
        if not panel_target.any() and auxiliary is not None:
            panel_target = auxiliary.part_candidates.get(label, panel_target)
        protected = np.zeros(mask.shape, dtype=bool)
        for other, other_mask in masks.items():
            if other != label:
                protected |= other_mask
        protected |= auxiliary_protected
        panels[label] = render_boundary_panel(
            source, panel_target, protected, output_dir / "qa_panels" / f"{label}.png"
        )

    try:
        gate = gate_checker(
            gate_path,
            model=model,
            prompt_version=prompt_version,
            prompt_path=prompt_path,
            generation_options=generation_options,
        )
    except VlmEvalError as exc:
        routes = {
            label: {
                "queue": "careful",
                "priority": "highest" if report["overall"] == "fail" else "high",
                "reason": "vlm_calibration_gate_unavailable",
                "may_approve_gold": False,
                "may_clear_block": False,
                "may_edit_mask": False,
            }
            for label in panels
        }
        status = {
            "enabled": False,
            "reason": str(exc),
            "model": model,
            "routes": routes,
            "whole_image_review": {"status": "skipped_gate_unavailable"},
            "manifest_review": {"status": "skipped_until_draft_manifest"},
            "workhorse": {"enabled": False, "reason": "calibration_gate_unavailable"},
            "cloud_teacher": {
                "enabled": False,
                "reason": "cloud_teacher_disabled_or_calibration_gate_unavailable",
            },
            "autonomy": autonomy_status,
        }
        if workhorse_enabled and config.get("workhorse", {}).get("enabled") is True:
            try:
                shadow = run_s11_production(
                    source_crop_path=source_crop_path,
                    part_map_path=part_map_path,
                    s10_report_path=s10_report_path,
                    output_dir=output_dir,
                    gate_path=gate_path,
                    client=client,
                    config_path=config_path,
                    prompt_path=prompt_path,
                    gate_checker=lambda *args, **kwargs: {"fingerprint": "shadow-uncalibrated"},
                    failure_queue_path=None,
                    pose_angle=pose_angle,
                    failure_instance_id=failure_instance_id,
                    workhorse_enabled=True,
                    correction_refiner=correction_refiner,
                    auto_load_correction_refiner=auto_load_correction_refiner,
                    cloud_teacher_config_path=cloud_teacher_config_path,
                    teacher_providers=teacher_providers,
                    teacher_budget=teacher_budget,
                    autonomy_config_path=autonomy_config_path,
                    autonomy_context=autonomy_context,
                    autonomy_certificate_root=autonomy_certificate_root,
                    autonomy_revocations_root=autonomy_revocations_root,
                    map_qa_validator=map_qa_validator,
                    auxiliary_dir=auxiliary_dir,
                    repair_hints_path=repair_hints_path,
                    person_bbox_xyxy=person_bbox_xyxy,
                    labels_to_review=labels_to_review,
                    pose_path=pose_path,
                    context_origin_xy=context_origin_xy,
                )
                status["shadow_enabled"] = True
                status["workhorse"] = shadow.get("workhorse", {}) | {
                    "enabled": True,
                    "authority": "uncalibrated_shadow_candidate_proposals_only",
                }
                status["whole_image_review"] = shadow["whole_image_review"] | {
                    "authority": "uncalibrated_shadow_only"
                }
                status["cloud_teacher"] = shadow.get(
                    "cloud_teacher", {"enabled": False, "reason": "not_run"}
                )
                status["autonomy"] = shadow.get("autonomy", autonomy_status) | {
                    "authority": "uncalibrated_shadow_candidate_proposals_only",
                    "authoritative_gold": False,
                }
                report = json.loads(qa_report_path.read_text(encoding="utf-8"))
                report["vlm_review"] = {"model": model, "verdicts": []}
            except Exception as shadow_exc:  # noqa: BLE001 - shadow work may never break S11
                status["shadow_enabled"] = False
                status["workhorse"] = {
                    "enabled": False,
                    "reason": f"shadow_failed:{type(shadow_exc).__name__}:{shadow_exc}",
                }
                report = json.loads(qa_report_path.read_text(encoding="utf-8"))
                report["vlm_review"] = {"model": model, "verdicts": []}
        report["overall"] = "fail" if report["overall"] == "fail" else "needs_human"
        qa_report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    else:
        project_root = Path(__file__).resolve().parents[3]
        autonomy_pipeline_fingerprint = build_autonomy_pipeline_fingerprint(
            gate["fingerprint"],
            components={
                "maskfactory_source": project_root / "src/maskfactory",
                "autonomy_config": Path(autonomy_config_path),
                "vlm_config": Path(config_path),
                "cloud_teacher_config": Path(cloud_teacher_config_path),
                "pipeline_config": project_root / "configs/pipeline.yaml",
                "ontology_config": project_root / "configs/ontology.yaml",
                "model_registry": project_root / "models/model_registry.json",
                "requirements_lock": project_root / "env/requirements.lock.txt",
                "project_manifest": project_root / "pyproject.toml",
            },
        )
        autonomy_status["pipeline_fingerprint"] = autonomy_pipeline_fingerprint
        active_client = client or OllamaClient(config["runtime"]["base_url"])
        auto_qa = (
            "block"
            if report["overall"] == "fail"
            else "all_pass" if report["overall"] == "pass" else "route"
        )
        routes = {}
        workhorse_audits = []
        workhorse_candidates = []
        workhorse_verifications = []
        cloud_judgments = []
        cloud_candidates = []
        cloud_errors = []
        cloud_candidate_support: dict[tuple[str, str], float] = {}
        autonomy_inputs: dict[str, list[MaskCandidateInput]] = {}
        autonomy_provider_votes: dict[str, tuple[dict[str, Any], ...]] = {}
        autonomy_uncertainties: dict[str, tuple[str, ...]] = {}
        owned_refiner = None
        active_teacher_providers = teacher_providers or build_teacher_providers(cloud_config)
        budget_settings = cloud_config["budget"]
        active_teacher_budget = teacher_budget or DailyBudgetLedger(
            Path(budget_settings["ledger_path"]),
            timezone_name=budget_settings["timezone"],
            hard_limit_usd=budget_settings["hard_limit_usd"],
            lock_timeout_sec=float(budget_settings["lock_timeout_sec"]),
        )
        active_teacher_quota = CloudJobQuota(
            int(budget_settings["maximum_calls_per_job"]),
            int(budget_settings["maximum_calls_per_label"]),
        )
        for label, panel in panels.items():
            specialist_disagreement = 0.0
            specialist_high_disagreement = False
            if workhorse_enabled and config.get("workhorse", {}).get("enabled") is True:
                neighbor_protected = np.zeros(masks[label].shape, dtype=bool)
                for other, other_mask in masks.items():
                    if other != label:
                        neighbor_protected |= other_mask
                neighbor_protected |= auxiliary_protected
                repair_region = repair_regions.get(label)
                repair_roi_xyxy = (
                    repair_region.bbox_xyxy if repair_region is not None else full_repair_roi
                )
                specialist_mask = (
                    auxiliary.part_candidates.get(label) if auxiliary is not None else None
                )
                specialist_visual = (
                    specialist_mask
                    if specialist_mask is not None
                    else (
                        auxiliary.support_candidates.get(label) if auxiliary is not None else None
                    )
                )
                final_mask_present = bool(masks[label].any())
                review_mask = (
                    masks[label]
                    if final_mask_present or specialist_mask is None
                    else specialist_mask
                )
                specialist_records = (
                    tuple(
                        (
                            *auxiliary.label_metadata.get(label, ()),
                            *auxiliary.support_metadata.get(label, ()),
                        )
                    )
                    if auxiliary is not None
                    else ()
                )
                specialist_metadata = {
                    "detectors": ",".join(
                        sorted({str(item["detector_key"]) for item in specialist_records})
                    ),
                    "maximum_confidence": (
                        f"{max(float(item['confidence']) for item in specialist_records):.6f}"
                        if specialist_records
                        else ""
                    ),
                    "authority": "proposal_only",
                    "evidence_scope": (
                        "atomic_candidate"
                        if specialist_mask is not None
                        else "parent_union_support_only_not_atomic_candidate"
                    ),
                    "final_mask_state": "present" if final_mask_present else "absent",
                    "evidence_target": (
                        "s09_final_mask"
                        if final_mask_present
                        else "raw_specialist_missing-label_proposal"
                    ),
                }
                evidence = render_workhorse_evidence(
                    source,
                    review_mask,
                    neighbor_protected,
                    output_dir / "workhorse_evidence" / label,
                    tile_size=int(config["prompts"]["p_workhorse"]["independent_image_long_side"]),
                    specialist_candidate=specialist_visual,
                    specialist_metadata=(
                        specialist_metadata if specialist_visual is not None else None
                    ),
                    focus_bbox_xyxy=(repair_roi_xyxy if repair_region is not None else None),
                )
                specialist_disagreement = (
                    float(
                        np.count_nonzero(masks[label] ^ specialist_mask)
                        / max(1, np.count_nonzero(masks[label] | specialist_mask))
                    )
                    if specialist_mask is not None
                    else 0.0
                )
                specialist_high_disagreement = (
                    specialist_mask is not None
                    and specialist_disagreement >= specialist_disagreement_threshold
                )
                specialist_finding = (
                    (
                        {
                            "id": "AUX-S11-001",
                            "name": "specialist_final_disagreement",
                            "result": "route",
                            "severity": "ROUTE",
                            "label": label,
                            "message": (
                                f"raw specialist/final disagreement={specialist_disagreement:.6f} "
                                f">= {specialist_disagreement_threshold:.6f}"
                            ),
                        },
                    )
                    if specialist_high_disagreement
                    else ()
                )
                workhorse_prompt_path = Path(config["prompts"]["p_workhorse"]["path"])
                audit = review_part_workhorse(
                    active_client,
                    label=label,
                    evidence=evidence,
                    model=model,
                    prompt_template=workhorse_prompt_path.read_text(encoding="utf-8"),
                    prompt_version=config["prompts"]["p_workhorse"]["version"],
                    gpu_lock_path=output_dir / ".vlm_gpu.lock",
                    generation_options=generation_options,
                    qa_findings=tuple(
                        check
                        for check in report.get("checks", ())
                        if isinstance(check, dict)
                        and check.get("result") in {"fail", "warn", "route"}
                    )
                    + specialist_finding,
                )
                workhorse_audits.append(audit)
                block_ids = tuple(
                    str(check.get("qc_id", check.get("check_id", "unknown_block")))
                    for check in report.get("checks", ())
                    if isinstance(check, dict)
                    and check.get("result") == "fail"
                    and check.get("severity") == "BLOCK"
                    and (check.get("label") in {None, label})
                )
                baseline_path = write_binary_mask(
                    output_dir / "autonomy_candidates" / label / "s09_baseline.png",
                    masks[label],
                )
                verdict = VlmVerdict(
                    audit.label,
                    f"workhorse_evidence/{label}",
                    audit.model,
                    audit.prompt_version,
                    audit.verdict,
                    audit.confidence,
                    audit.problems,
                    audit.evidence,
                    audit.correction_instruction,
                    audit.latency_ms,
                )
                active_refiner = correction_refiner
                if (
                    active_refiner is None
                    and auto_load_correction_refiner
                    and audit.verdict == "fail"
                    and audit.correction_plan.tool == "sam2_refine"
                ):
                    from ..serve.providers import load_production_sam2_refiner

                    owned_refiner = owned_refiner or load_production_sam2_refiner(
                        work_dir=output_dir / "sam2_workhorse"
                    )
                    active_refiner = owned_refiner
                settings = config["workhorse"]
                candidate = generate_correction_candidate(
                    audit,
                    source=np.asarray(source),
                    current_mask=review_mask,
                    protected_neighbor=immutable_protected,
                    refiner=active_refiner,
                    output_path=output_dir / "correction_candidates" / f"{label}.png",
                    max_changed_fraction=float(settings["max_changed_fraction"]),
                    max_protected_overlap_fraction=float(
                        repair_policy["maximum_protected_overlap_fraction"]
                    ),
                    repair_roi_xyxy=repair_roi_xyxy,
                    person_bbox_xyxy=effective_person_bbox,
                    reconstruction_max_changed_fraction=float(
                        repair_policy["reconstruction_max_changed_fraction"]
                    ),
                    maximum_outside_roi_fraction=float(
                        repair_policy["maximum_outside_roi_fraction"]
                    ),
                    expected_area_slack=float(repair_policy["expected_area_slack"]),
                )
                workhorse_candidates.append(candidate)
                local_verification = None
                if candidate.status == "candidate_created" and candidate.candidate_path:
                    candidate_mask = (
                        np.asarray(Image.open(candidate.candidate_path).convert("L")) != 0
                    )
                    after_evidence = render_workhorse_evidence(
                        source,
                        candidate_mask,
                        neighbor_protected,
                        output_dir / "workhorse_evidence_after" / label,
                        tile_size=int(
                            config["prompts"]["p_workhorse"]["independent_image_long_side"]
                        ),
                        focus_bbox_xyxy=(repair_roi_xyxy if repair_region is not None else None),
                    )
                    compare_prompt = Path(config["prompts"]["p_compare"]["path"]).read_text(
                        encoding="utf-8"
                    )
                    local_verification = verify_correction_candidate(
                        active_client,
                        label=label,
                        before=evidence,
                        after=after_evidence,
                        model=model,
                        prompt_template=compare_prompt,
                        gpu_lock_path=output_dir / ".vlm_gpu.lock",
                        generation_options=generation_options,
                    )
                    workhorse_verifications.append(local_verification)
                label_cloud_judgments = ()
                label_cloud_candidates = []
                if cloud_config["enabled"] is True and (
                    repair_policy["enabled"] is not True
                    or cloud_config["selection"]["diagnosis_cascade_before_autonomous_convergence"]
                    is True
                ):
                    nonpass_findings = tuple(
                        check
                        for check in report.get("checks", ())
                        if isinstance(check, dict)
                        and check.get("result") in {"fail", "warn", "route"}
                    )
                    teacher_request = TeacherRequest(
                        str(report["image_id"]),
                        failure_instance_id,
                        label,
                        Path(source_crop_path),
                        evidence,
                        audit,
                        nonpass_findings,
                        repair_roi_xyxy,
                        build_pose_side_evidence(
                            label,
                            pose_document,
                            context_origin_xy=context_origin_xy,
                            candidate_mask=review_mask,
                        ),
                    )
                    try:
                        judgments = run_teacher_cascade(
                            teacher_request,
                            providers=active_teacher_providers,
                            config=cloud_config,
                            budget=active_teacher_budget,
                            prompt_template=Path(
                                "src/maskfactory/vlm/prompts/p_cloud_teacher.txt"
                            ).read_text(encoding="utf-8"),
                            report_path=output_dir / "cloud_teacher_reports" / f"{label}.json",
                            call_quota=active_teacher_quota,
                        )
                        cloud_judgments.extend(judgments)
                        label_cloud_judgments = judgments
                        for teacher_judgment in judgments:
                            teacher_refiner = correction_refiner
                            if (
                                teacher_refiner is None
                                and auto_load_correction_refiner
                                and teacher_judgment.correction.tool == "points"
                            ):
                                from ..serve.providers import load_production_sam2_refiner

                                owned_refiner = owned_refiner or load_production_sam2_refiner(
                                    work_dir=output_dir / "sam2_workhorse"
                                )
                                teacher_refiner = owned_refiner
                            teacher_candidate = materialize_teacher_candidate(
                                teacher_judgment,
                                request=teacher_request,
                                current_mask=masks[label],
                                protected_neighbor=immutable_protected,
                                refiner=teacher_refiner,
                                output_path=output_dir
                                / "cloud_teacher_candidates"
                                / f"{teacher_judgment.provider}_{label}.png",
                                max_changed_fraction=float(
                                    config["workhorse"]["max_changed_fraction"]
                                ),
                                max_protected_overlap_fraction=float(
                                    repair_policy["maximum_protected_overlap_fraction"]
                                ),
                                reconstruction_max_changed_fraction=float(
                                    repair_policy["reconstruction_max_changed_fraction"]
                                ),
                                maximum_outside_roi_fraction=float(
                                    repair_policy["maximum_outside_roi_fraction"]
                                ),
                                expected_area_slack=float(repair_policy["expected_area_slack"]),
                                person_bbox_xyxy=effective_person_bbox,
                            )
                            cloud_candidates.append(teacher_candidate)
                            label_cloud_candidates.append(teacher_candidate)
                            if (
                                teacher_candidate.status == "candidate_created"
                                and teacher_candidate.path
                            ):
                                cloud_mask = (
                                    np.asarray(Image.open(teacher_candidate.path).convert("L")) != 0
                                )
                                cloud_after = render_workhorse_evidence(
                                    source,
                                    cloud_mask,
                                    neighbor_protected,
                                    output_dir
                                    / "cloud_teacher_evidence_after"
                                    / label
                                    / teacher_judgment.provider,
                                    tile_size=int(
                                        config["prompts"]["p_workhorse"][
                                            "independent_image_long_side"
                                        ]
                                    ),
                                    focus_bbox_xyxy=(
                                        repair_roi_xyxy if repair_region is not None else None
                                    ),
                                )
                                cloud_verification = verify_correction_candidate(
                                    active_client,
                                    label=label,
                                    before=evidence,
                                    after=cloud_after,
                                    model=model,
                                    prompt_template=Path(
                                        config["prompts"]["p_compare"]["path"]
                                    ).read_text(encoding="utf-8"),
                                    gpu_lock_path=output_dir / ".vlm_gpu.lock",
                                    generation_options=generation_options,
                                )
                                workhorse_verifications.append(cloud_verification)
                                cloud_candidate_support[(label, teacher_judgment.provider)] = (
                                    1.0
                                    if cloud_verification.decision == "better"
                                    and cloud_verification.confidence >= 0.7
                                    else (
                                        0.0
                                        if cloud_verification.decision == "worse"
                                        and cloud_verification.confidence >= 0.7
                                        else 0.5
                                    )
                                )
                    except Exception as exc:  # noqa: BLE001 - cloud shadow never breaks S11
                        cloud_errors.append(f"{label}:{type(exc).__name__}:{exc}")
                critic_verdicts = [audit.verdict, *(item.verdict for item in label_cloud_judgments)]
                critic_support = sum(
                    1.0 if verdict == "pass" else 0.5 if verdict == "uncertain" else 0.0
                    for verdict in critic_verdicts
                ) / max(1, len(critic_verdicts))
                critic_disagreement = len(set(critic_verdicts)) > 1
                combined_disagreement = critic_disagreement or specialist_high_disagreement
                observed_cloud = {item.provider for item in label_cloud_judgments}
                provider_votes = [
                    {
                        "provider": "self_hosted_qwen",
                        "model": audit.model,
                        "participated": True,
                        "verdict": audit.verdict,
                        "confidence": audit.confidence,
                        "defects": list(audit.problems),
                    },
                    *(
                        {
                            "provider": item.provider,
                            "model": item.model,
                            "participated": True,
                            "verdict": item.verdict,
                            "confidence": item.confidence,
                            "defects": list(item.defects),
                        }
                        for item in label_cloud_judgments
                    ),
                    *(
                        {
                            "provider": f"civitai_{item['detector_key']}",
                            "model": item["checkpoint_sha256"],
                            "participated": True,
                            "verdict": ("disagrees" if specialist_high_disagreement else "aligns"),
                            "confidence": item["confidence"],
                            "defects": (
                                ["specialist_final_disagreement"]
                                if specialist_high_disagreement
                                else []
                            ),
                            "authority": "proposal_only",
                        }
                        for item in specialist_records
                    ),
                    *(
                        {
                            "provider": provider_name,
                            "model": cloud_config["providers"][provider_name]["model"],
                            "participated": False,
                            "verdict": "not_run",
                            "confidence": None,
                            "defects": [],
                            "reason": "not_applicable_not_eligible_or_cascade_stopped",
                        }
                        for provider_name in ("gemini", "openai", "anthropic")
                        if provider_name not in observed_cloud
                    ),
                ]
                autonomy_provider_votes[label] = tuple(provider_votes)
                uncertainties = []
                if critic_disagreement:
                    uncertainties.append("independent_critics_disagree")
                if specialist_high_disagreement:
                    uncertainties.append("specialist_final_mask_disagreement")
                if audit.verdict == "uncertain":
                    uncertainties.append("self_hosted_workhorse_uncertain")
                if not label_cloud_judgments:
                    uncertainties.append("cloud_committee_not_observed")
                autonomy_uncertainties[label] = tuple(uncertainties)
                consensus_sources = tuple(
                    str(source_name)
                    for source_name in report.get("consensus", {}).get("sources", ())
                ) or ("s09_consensus",)
                label_inputs = [
                    MaskCandidateInput(
                        "s09_baseline",
                        baseline_path,
                        consensus_sources,
                        critic_support,
                        combined_disagreement,
                        1.0,
                        block_ids,
                    )
                ]
                if specialist_mask is not None and specialist_mask.any():
                    specialist_path = write_binary_mask(
                        output_dir / "autonomy_candidates" / label / "civitai_specialist_raw.png",
                        specialist_mask,
                    )
                    specialist_qa = _validate_candidate_map(
                        part_map,
                        label=label,
                        candidate_mask_path=specialist_path,
                        output_dir=output_dir / "candidate_qa" / label / "civitai_specialist",
                        tag=f"{label}_civitai_specialist",
                        validator=map_qa_validator,
                        repair_roi_xyxy=repair_roi_xyxy,
                        immutable_label_ids=immutable_label_ids,
                        maximum_displaced_labels=int(
                            repair_policy["maximum_displaced_labels_per_transaction"]
                        ),
                    )
                    specialist_sources = tuple(
                        sorted({f"civitai:{item['detector_key']}" for item in specialist_records})
                    ) or ("civitai:unknown_specialist",)
                    label_inputs.append(
                        MaskCandidateInput(
                            "civitai_specialist_raw",
                            specialist_path,
                            specialist_sources,
                            0.5,
                            combined_disagreement,
                            1.0,
                            specialist_qa.block_qc_ids,
                        )
                    )
                if candidate.status == "candidate_created" and candidate.candidate_path:
                    local_qa = _validate_candidate_map(
                        part_map,
                        label=label,
                        candidate_mask_path=Path(candidate.candidate_path),
                        output_dir=output_dir / "candidate_qa" / label / "local_r1",
                        tag=f"{label}_local_r1",
                        validator=map_qa_validator,
                        repair_roi_xyxy=repair_roi_xyxy,
                        immutable_label_ids=immutable_label_ids,
                        maximum_displaced_labels=int(
                            repair_policy["maximum_displaced_labels_per_transaction"]
                        ),
                    )
                    support = (
                        1.0
                        if local_verification is not None
                        and local_verification.decision == "better"
                        and local_verification.confidence >= 0.7
                        else 0.5
                    )
                    label_inputs.append(
                        MaskCandidateInput(
                            "local_correction_r1",
                            Path(candidate.candidate_path),
                            ("s09_baseline", "local_qwen", "local_correction_tool"),
                            support,
                            combined_disagreement,
                            1.0,
                            local_qa.block_qc_ids,
                        )
                    )
                    current_mask = candidate_mask
                    current_evidence = after_evidence
                    current_verification = local_verification
                    maximum_rounds = min(
                        int(autonomy_config["tournament"]["maximum_rounds"]),
                        int(config["workhorse"].get("max_iterations_per_part", 1)),
                    )
                    for round_number in range(2, maximum_rounds + 1):
                        if (
                            not local_qa.passed
                            or current_verification is None
                            or current_verification.decision != "better"
                            or current_verification.confidence < 0.7
                        ):
                            break
                        round_audit = review_part_workhorse(
                            active_client,
                            label=label,
                            evidence=current_evidence,
                            model=model,
                            prompt_template=workhorse_prompt_path.read_text(encoding="utf-8"),
                            prompt_version=config["prompts"]["p_workhorse"]["version"],
                            gpu_lock_path=output_dir / ".vlm_gpu.lock",
                            generation_options=generation_options,
                            qa_findings=_qa_findings(local_qa),
                        )
                        workhorse_audits.append(round_audit)
                        if round_audit.verdict != "fail":
                            break
                        if (
                            active_refiner is None
                            and auto_load_correction_refiner
                            and round_audit.correction_plan.tool == "sam2_refine"
                        ):
                            from ..serve.providers import load_production_sam2_refiner

                            owned_refiner = owned_refiner or load_production_sam2_refiner(
                                work_dir=output_dir / "sam2_workhorse"
                            )
                            active_refiner = owned_refiner
                        round_candidate = generate_correction_candidate(
                            round_audit,
                            source=np.asarray(source),
                            current_mask=current_mask,
                            protected_neighbor=immutable_protected,
                            refiner=active_refiner,
                            output_path=(
                                output_dir
                                / "correction_candidates"
                                / f"{label}_r{round_number}.png"
                            ),
                            max_changed_fraction=float(settings["max_changed_fraction"]),
                            max_protected_overlap_fraction=float(
                                repair_policy["maximum_protected_overlap_fraction"]
                            ),
                            repair_roi_xyxy=repair_roi_xyxy,
                            person_bbox_xyxy=effective_person_bbox,
                            reconstruction_max_changed_fraction=float(
                                repair_policy["reconstruction_max_changed_fraction"]
                            ),
                            maximum_outside_roi_fraction=float(
                                repair_policy["maximum_outside_roi_fraction"]
                            ),
                            expected_area_slack=float(repair_policy["expected_area_slack"]),
                        )
                        workhorse_candidates.append(round_candidate)
                        if (
                            round_candidate.status != "candidate_created"
                            or not round_candidate.candidate_path
                        ):
                            break
                        round_mask = (
                            np.asarray(Image.open(round_candidate.candidate_path).convert("L")) != 0
                        )
                        round_evidence = render_workhorse_evidence(
                            source,
                            round_mask,
                            neighbor_protected,
                            output_dir
                            / "workhorse_evidence_after"
                            / label
                            / f"round_{round_number}",
                            tile_size=int(
                                config["prompts"]["p_workhorse"]["independent_image_long_side"]
                            ),
                            focus_bbox_xyxy=(
                                repair_roi_xyxy if repair_region is not None else None
                            ),
                        )
                        round_verification = verify_correction_candidate(
                            active_client,
                            label=label,
                            before=current_evidence,
                            after=round_evidence,
                            model=model,
                            prompt_template=compare_prompt,
                            gpu_lock_path=output_dir / ".vlm_gpu.lock",
                            generation_options=generation_options,
                        )
                        workhorse_verifications.append(round_verification)
                        local_qa = _validate_candidate_map(
                            part_map,
                            label=label,
                            candidate_mask_path=Path(round_candidate.candidate_path),
                            output_dir=(
                                output_dir / "candidate_qa" / label / f"local_r{round_number}"
                            ),
                            tag=f"{label}_local_r{round_number}",
                            validator=map_qa_validator,
                            repair_roi_xyxy=repair_roi_xyxy,
                            immutable_label_ids=immutable_label_ids,
                            maximum_displaced_labels=int(
                                repair_policy["maximum_displaced_labels_per_transaction"]
                            ),
                        )
                        round_support = (
                            1.0
                            if round_verification.decision == "better"
                            and round_verification.confidence >= 0.7
                            else (
                                0.0
                                if round_verification.decision == "worse"
                                and round_verification.confidence >= 0.7
                                else 0.5
                            )
                        )
                        label_inputs.append(
                            MaskCandidateInput(
                                f"local_correction_r{round_number}",
                                Path(round_candidate.candidate_path),
                                (
                                    "s09_baseline",
                                    "local_qwen",
                                    "sam2_refiner",
                                    f"local_round_{round_number}",
                                ),
                                round_support,
                                combined_disagreement,
                                1.0,
                                local_qa.block_qc_ids,
                            )
                        )
                        current_mask = round_mask
                        current_evidence = round_evidence
                        current_verification = round_verification
                for teacher_candidate in label_cloud_candidates:
                    if teacher_candidate.status == "candidate_created" and teacher_candidate.path:
                        cloud_qa = _validate_candidate_map(
                            part_map,
                            label=label,
                            candidate_mask_path=Path(teacher_candidate.path),
                            output_dir=(
                                output_dir
                                / "candidate_qa"
                                / label
                                / f"cloud_{teacher_candidate.provider}"
                            ),
                            tag=f"{label}_cloud_{teacher_candidate.provider}",
                            validator=map_qa_validator,
                            repair_roi_xyxy=repair_roi_xyxy,
                            immutable_label_ids=immutable_label_ids,
                            maximum_displaced_labels=int(
                                repair_policy["maximum_displaced_labels_per_transaction"]
                            ),
                        )
                        label_inputs.append(
                            MaskCandidateInput(
                                f"cloud_{teacher_candidate.provider}",
                                Path(teacher_candidate.path),
                                (
                                    "s09_baseline",
                                    f"cloud_{teacher_candidate.provider}",
                                    "cloud_correction_tool",
                                ),
                                cloud_candidate_support.get(
                                    (label, teacher_candidate.provider), 0.5
                                ),
                                combined_disagreement,
                                1.0,
                                cloud_qa.block_qc_ids,
                            )
                        )
                autonomy_inputs[label] = label_inputs
            else:
                prepared = prepare_panel_input(panel, output_dir / "prepared" / f"{label}.png")
                verdict = review_part(
                    active_client,
                    label=label,
                    panel_path=prepared,
                    panel_file=f"qa_panels/{label}.png",
                    model=model,
                    prompt_template=prompt_template,
                    prompt_version=prompt_version,
                    gpu_lock_path=output_dir / ".vlm_gpu.lock",
                    generation_options=generation_options,
                )
            append_verdict(qa_report_path, verdict)
            decision = route(
                "route" if workhorse_enabled and auto_qa == "all_pass" else auto_qa, verdict
            )
            routes[label] = asdict(decision)
            if workhorse_enabled and specialist_high_disagreement:
                routes[label].update(
                    {
                        "queue": "careful",
                        "priority": "high",
                        "pin_disagreement_heatmap": True,
                        "specialist_disagreement_fraction": specialist_disagreement,
                        "specialist_disagreement_reason": "raw_specialist_vs_final_mask",
                    }
                )
            if failure_queue_path is not None and _is_disagreement(auto_qa, verdict):
                if pose_angle is None:
                    raise ValueError("S11 failure-queue emission requires pose_angle")
                if not failure_instance_id.startswith("p") or not failure_instance_id[1:].isdigit():
                    raise ValueError("S11 failure instance must be pN")
                occurred = datetime.now(UTC)
                record = make_failure_record(
                    image_id=str(report["image_id"]),
                    body_part=label,
                    reason="vlm_autoqa_disagreement",
                    pose=pose_angle,
                    model=f"{model}:{prompt_version}:{failure_instance_id}:{report['run_id']}",
                    correction=f"review_{label}",
                    class_error_rate=float(verdict.confidence),
                    coverage_deficit=1.0,
                    use_weight=_label_use_weight(label),
                    event_time=occurred,
                    now=occurred,
                )
                append_failure_once(Path(failure_queue_path), record)
        autonomy_lifecycle = []
        autonomy_convergence: dict[str, dict[str, Any]] = {}
        review_draft_selections: list[ReviewDraftSelection] = []
        for label, candidate_inputs in sorted(autonomy_inputs.items()):
            convergence_enabled = bool(
                repair_policy["enabled"]
                and workhorse_enabled
                and config.get("workhorse", {}).get("enabled") is True
                and repair_hints_path is not None
                and effective_person_bbox is not None
            )
            if convergence_enabled:
                if (
                    correction_refiner is None
                    and owned_refiner is None
                    and auto_load_correction_refiner
                ):
                    from ..serve.providers import load_production_sam2_refiner

                    owned_refiner = load_production_sam2_refiner(
                        work_dir=output_dir / "sam2_workhorse"
                    )
                region = repair_regions.get(label)
                repair_roi_xyxy = region.bbox_xyxy if region is not None else full_repair_roi
                neighbor_visual = np.zeros(part_map.shape, dtype=bool)
                for other_label, other_mask in masks.items():
                    if other_label != label:
                        neighbor_visual |= other_mask
                neighbor_visual |= auxiliary_protected
                candidate_inputs, convergence = _converge_label_candidate(
                    label=label,
                    candidate_inputs=candidate_inputs,
                    base_part_map=part_map,
                    source=source,
                    source_path=Path(source_crop_path),
                    output_dir=output_dir,
                    image_id=str(report["image_id"]),
                    instance_id=failure_instance_id,
                    context=autonomy_context,
                    pipeline_fingerprint=autonomy_pipeline_fingerprint,
                    autonomy_config=autonomy_config,
                    cloud_config=cloud_config,
                    client=active_client,
                    model=model,
                    generation_options=generation_options,
                    workhorse_prompt_template=Path(
                        config["prompts"]["p_workhorse"]["path"]
                    ).read_text(encoding="utf-8"),
                    workhorse_prompt_version=config["prompts"]["p_workhorse"]["version"],
                    providers=active_teacher_providers,
                    budget=active_teacher_budget,
                    refiner=correction_refiner or owned_refiner,
                    map_qa_validator=map_qa_validator,
                    repair_roi_xyxy=repair_roi_xyxy,
                    person_bbox_xyxy=effective_person_bbox,
                    immutable_protected=immutable_protected,
                    immutable_label_ids=immutable_label_ids,
                    neighbor_visual=neighbor_visual,
                    pose_document=pose_document,
                    context_origin_xy=context_origin_xy,
                    cloud_call_quota=active_teacher_quota,
                )
                autonomy_inputs[label] = candidate_inputs
                autonomy_convergence[label] = convergence
                autonomy_provider_votes[label] = tuple(convergence["final_votes"])
                autonomy_uncertainties[label] = tuple(convergence["remaining_uncertainties"])
            evidence = build_mask_candidate_evidence(
                tuple(candidate_inputs),
                protected_neighbor=immutable_protected,
                # Candidate application is an atomic PART-map transaction. Exclusivity
                # is measured on the composed map, not against possibly-wrong incumbents.
                mutually_exclusive=np.zeros_like(immutable_protected),
                ontology_max_components=max(
                    1, int(get_ontology().label(label).max_components or 1)
                ),
            )
            revoked = certificate_is_revoked(
                autonomy_revocations_root,
                label=label,
                context=autonomy_context,
                pipeline_fingerprint=autonomy_pipeline_fingerprint,
            )
            certificate = (
                None
                if revoked
                else load_scoped_certificate(
                    autonomy_certificate_root, label=label, context=autonomy_context
                )
            )
            autonomy_decision = run_candidate_tournament(
                evidence,
                label=label,
                context=autonomy_context,
                pipeline_fingerprint=autonomy_pipeline_fingerprint,
                config=autonomy_config,
                certificate=certificate,
            )
            lifecycle = write_lifecycle_sidecar(
                output_dir / "autonomy" / f"{label}.json",
                image_id=str(report["image_id"]),
                instance_id=failure_instance_id,
                pipeline_fingerprint=autonomy_pipeline_fingerprint,
                decision=autonomy_decision,
            )
            autonomy_lifecycle.append(lifecycle)
            review_selection = select_pre_review_candidate(
                autonomy_decision,
                policy=autonomy_config["operations"],
                provider_votes=autonomy_provider_votes.get(label, ()),
                remaining_uncertainties=autonomy_uncertainties.get(label, ()),
            )
            if review_selection is not None:
                region = repair_regions.get(label)
                review_draft_selections.append(
                    replace(
                        review_selection,
                        repair_roi_xyxy=(
                            region.bbox_xyxy if region is not None else full_repair_roi
                        ),
                        allow_label_reassignment=bool(
                            repair_policy["allow_transactional_draft_reassignment"]
                        ),
                        immutable_label_ids=immutable_label_ids,
                        maximum_displaced_labels=int(
                            repair_policy["maximum_displaced_labels_per_transaction"]
                        ),
                    )
                )
        review_draft = build_autonomous_review_draft(
            part_map_path,
            tuple(review_draft_selections),
            output_dir / "autonomy_review_draft",
            map_validator=map_qa_validator,
        )
        if owned_refiner is not None:
            owned_refiner.close()
        review_map = np.asarray(Image.open(review_draft["review_part_map"]))
        render_part_overlays(
            source,
            review_map,
            output_dir / "autonomy_review_draft" / "qa_panels",
            label_colors=viz["label_colors"],
        )
        if autonomy_lifecycle:
            counts: dict[str, int] = {}
            for lifecycle in autonomy_lifecycle:
                counts[lifecycle["status"]] = counts.get(lifecycle["status"], 0) + 1
            autonomy_status = {
                "enabled": True,
                "mode": autonomy_config["mode"],
                "context": autonomy_context,
                "pipeline_fingerprint": autonomy_pipeline_fingerprint,
                "decision_count": len(autonomy_lifecycle),
                "status_counts": dict(sorted(counts.items())),
                "lifecycle_dir": "autonomy",
                "review_draft": _portable_review_draft(review_draft, output_dir),
                "convergence": autonomy_convergence,
                "authoritative_gold": False,
            }
        if workhorse_enabled and workhorse_audits:
            report_path = write_workhorse_report(
                output_dir / "workhorse_report.json",
                audits=workhorse_audits,
                candidates=workhorse_candidates,
                verifications=workhorse_verifications,
            )
            workhorse_status: dict[str, Any] = {
                "enabled": True,
                "mode": config["workhorse"]["mode"],
                "report": report_path.name,
                "audit_count": len(workhorse_audits),
                "candidate_created_count": sum(
                    item.status == "candidate_created" for item in workhorse_candidates
                ),
                "candidate_better_count": sum(
                    item.decision == "better" and item.confidence >= 0.7
                    for item in workhorse_verifications
                ),
                "authoritative_map_write": False,
                "non_gold_review_draft_write": bool(review_draft["applied"]),
                "human_approval_required": True,
            }
        else:
            workhorse_status = {"enabled": False, "reason": "legacy_review_mode"}
        cloud_teacher_status = {
            "enabled": cloud_config["enabled"] is True,
            "mode": "shadow_only",
            "provider_count": len(active_teacher_providers),
            "judgment_count": len(cloud_judgments),
            "candidate_created_count": sum(
                item.status == "candidate_created" for item in cloud_candidates
            ),
            "errors": cloud_errors,
            "may_approve_gold": False,
            "may_write_authoritative_masks": False,
        }
        image_review = _review_whole_image(
            active_client,
            model=model,
            source_path=source_crop_path,
            overlay_path=output_dir / "qa_panels/all_parts.png",
            labels=masks,
            prompt_path=Path("src/maskfactory/vlm/prompts/p_image.txt"),
            output_dir=output_dir,
            generation_options=generation_options,
        )
        report = json.loads(qa_report_path.read_text(encoding="utf-8"))
        if report["overall"] != "fail" and any(
            verdict["verdict"] != "pass" or verdict["confidence"] < 0.7
            for verdict in report["vlm_review"]["verdicts"]
        ):
            report["overall"] = "needs_human"
            qa_report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        if report["overall"] != "fail" and (
            image_review["status"] != "complete"
            or any(
                image_review[key]
                for key in ("missing", "mislabeled", "lr_suspect", "impossible_claims")
            )
        ):
            report["overall"] = "needs_human"
            qa_report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        status = {
            "enabled": True,
            "model": model,
            "gate_fingerprint": gate["fingerprint"],
            "routes": routes,
            "whole_image_review": image_review,
            "manifest_review": {"status": "skipped_until_draft_manifest"},
            "workhorse": workhorse_status,
            "cloud_teacher": cloud_teacher_status,
            "autonomy": autonomy_status,
        }
    (output_dir / "vlm_routing.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    final_report = json.loads(qa_report_path.read_text(encoding="utf-8"))
    issues = validate_document(final_report, "qa_report")
    if issues:
        raise ArtifactValidationError(issues)
    return status


def _validate_candidate_map(
    base_part_map: np.ndarray,
    *,
    label: str,
    candidate_mask_path: Path,
    output_dir: Path,
    tag: str,
    validator: MapQaValidator | None,
    repair_roi_xyxy: tuple[int, int, int, int] | None = None,
    immutable_label_ids: tuple[int, ...] = (),
    maximum_displaced_labels: int = 8,
) -> CandidateQaOutcome:
    """Compose a complete map and rerun hard QA for this exact candidate."""
    if repair_roi_xyxy is not None:
        candidate_map, construction_vetoes, _ = compose_candidate_map_transactional(
            base_part_map,
            label=label,
            candidate_mask_path=candidate_mask_path,
            repair_roi_xyxy=repair_roi_xyxy,
            immutable_label_ids=immutable_label_ids,
            maximum_displaced_labels=maximum_displaced_labels,
        )
    else:
        candidate_map, construction_vetoes = compose_candidate_map(
            base_part_map,
            label=label,
            candidate_mask_path=candidate_mask_path,
        )
    if construction_vetoes:
        return CandidateQaOutcome(tuple(construction_vetoes), None, "fail")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    map_path = write_label_map(output_dir / "label_map_part.png", candidate_map, bits=16)
    if validator is None:
        return CandidateQaOutcome((), None, "not_run")
    return validator(map_path, tag)


def _converge_label_candidate(
    *,
    label: str,
    candidate_inputs: list[MaskCandidateInput],
    base_part_map: np.ndarray,
    source: Image.Image,
    source_path: Path,
    output_dir: Path,
    image_id: str,
    instance_id: str,
    context: str,
    pipeline_fingerprint: str,
    autonomy_config: dict[str, Any],
    cloud_config: dict[str, Any],
    client: OllamaClient,
    model: str,
    generation_options: dict[str, Any],
    workhorse_prompt_template: str,
    workhorse_prompt_version: str,
    providers: dict[str, TeacherProvider],
    budget: DailyBudgetLedger,
    refiner: CorrectionRefiner | None,
    map_qa_validator: MapQaValidator | None,
    repair_roi_xyxy: tuple[int, int, int, int],
    person_bbox_xyxy: tuple[int, int, int, int],
    immutable_protected: np.ndarray,
    immutable_label_ids: tuple[int, ...],
    neighbor_visual: np.ndarray,
    pose_document: dict[str, Any] | None,
    context_origin_xy: tuple[int, int],
    cloud_call_quota: CloudJobQuota,
) -> tuple[list[MaskCandidateInput], dict[str, Any]]:
    """Re-audit actual winners and turn every failed review into another proposal.

    This is deliberately limited to a non-gold review-draft path. A reviewer verdict
    never edits the map directly: every correction is materialized, locally guarded,
    composed into a complete map, rerun through deterministic QA, and retournamented.
    """
    repair = autonomy_config["repair"]
    maximum_rounds = int(repair["maximum_committee_rounds_per_label"])
    maximum_candidates = min(
        int(repair["maximum_total_candidates_per_label"]),
        int(autonomy_config["tournament"]["maximum_candidates_per_label"]),
    )
    target = float(repair["target_reviewer_pass_confidence"])
    advisory_floor = float(repair["minimum_advisory_pass_confidence"])
    minimum_pass_reviewers = int(repair["minimum_independent_pass_reviewers"])
    require_all = bool(repair["require_all_available_reviewers_for_experimental_convergence"])
    enabled_cloud = tuple(
        name
        for name in (
            cloud_config["selection"]["primary_provider"],
            cloud_config["selection"]["disagreement_critic"],
            cloud_config["selection"]["tie_breaker"],
        )
        if cloud_config["enabled"] is True
        and cloud_config["providers"].get(name, {}).get("enabled") is True
    )
    required_pass_reviewers = min(minimum_pass_reviewers, 1 + len(enabled_cloud))
    cloud_prompt = Path("src/maskfactory/vlm/prompts/p_cloud_teacher.txt").read_text(
        encoding="utf-8"
    )
    rounds: list[dict[str, Any]] = []
    final_votes: list[dict[str, Any]] = []
    uncertainties: list[str] = []
    converged = False
    stop_reason = "bounded_round_limit_reached"
    iteration_feedback: tuple[str, ...] = ()

    def boundary_checked(path: Path, outcome: CandidateQaOutcome) -> CandidateQaOutcome:
        candidate = np.asarray(Image.open(path).convert("L")) != 0
        vetoes = atomic_boundary_vetoes(
            candidate,
            label=label,
            pose_document=pose_document,
            context_origin_xy=context_origin_xy,
            companion_parts_visible=_companion_parts_visible(label, base_part_map),
        )
        if not vetoes:
            return outcome
        block_ids = tuple(dict.fromkeys((*outcome.block_qc_ids, *vetoes)))
        all_block_ids = tuple(dict.fromkeys((*outcome.all_block_qc_ids, *vetoes)))
        return replace(
            outcome,
            block_qc_ids=block_ids,
            all_block_qc_ids=all_block_ids,
            overall="fail",
            non_regressing=False,
        )

    for round_number in range(1, maximum_rounds + 1):
        tournament_evidence = build_mask_candidate_evidence(
            tuple(candidate_inputs),
            protected_neighbor=immutable_protected,
            mutually_exclusive=np.zeros_like(immutable_protected),
            ontology_max_components=max(1, int(get_ontology().label(label).max_components or 1)),
        )
        preliminary = run_candidate_tournament(
            tournament_evidence,
            label=label,
            context=context,
            pipeline_fingerprint=pipeline_fingerprint,
            config=autonomy_config,
            certificate=None,
        )
        winner_id = preliminary.winner_id
        winner = next(
            (item for item in preliminary.ranking if item.candidate_id == winner_id), None
        )
        if winner is None:
            # A QA-clean proposal may enter the review committee to acquire the missing
            # independent critic evidence. This does not waive the final tournament's
            # source-diversity veto; the exact candidate must earn those sources here.
            winner = next(
                (
                    item
                    for item in preliminary.ranking
                    if set(item.vetoes) <= {"insufficient_independent_sources"}
                ),
                None,
            )
            winner_id = winner.candidate_id if winner is not None else None
        if winner is None:
            stop_reason = "no_eligible_candidate_for_committee"
            uncertainties.append(stop_reason)
            break
        candidate_path = Path(winner.evidence.mask_path)
        candidate_mask = np.asarray(Image.open(candidate_path).convert("L")) != 0
        candidate_qa = _validate_candidate_map(
            base_part_map,
            label=label,
            candidate_mask_path=candidate_path,
            output_dir=output_dir / "candidate_qa" / label / f"committee_r{round_number}",
            tag=f"{label}_committee_r{round_number}",
            validator=map_qa_validator,
            repair_roi_xyxy=repair_roi_xyxy,
            immutable_label_ids=immutable_label_ids,
            maximum_displaced_labels=int(repair["maximum_displaced_labels_per_transaction"]),
        )
        candidate_qa = boundary_checked(candidate_path, candidate_qa)
        if candidate_qa.block_qc_ids:
            candidate_inputs = [
                (
                    replace(
                        item,
                        block_qc_ids=tuple(
                            dict.fromkeys((*item.block_qc_ids, *candidate_qa.block_qc_ids))
                        ),
                    )
                    if item.candidate_id == winner_id
                    else item
                )
                for item in candidate_inputs
            ]
        candidate_evidence = render_workhorse_evidence(
            source,
            candidate_mask,
            neighbor_visual,
            output_dir / "committee_evidence" / label / f"round_{round_number}",
            focus_bbox_xyxy=repair_roi_xyxy,
        )
        local_audit = review_part_workhorse(
            client,
            label=label,
            evidence=candidate_evidence,
            model=model,
            prompt_template=workhorse_prompt_template,
            prompt_version=workhorse_prompt_version,
            gpu_lock_path=output_dir / ".vlm_gpu.lock",
            generation_options=generation_options,
            qa_findings=_qa_findings(candidate_qa),
        )
        request = TeacherRequest(
            image_id,
            instance_id,
            label,
            source_path,
            candidate_evidence,
            local_audit,
            _qa_findings(candidate_qa),
            repair_roi_xyxy,
            build_pose_side_evidence(
                label,
                pose_document,
                context_origin_xy=context_origin_xy,
                candidate_mask=candidate_mask,
            ),
            iteration_feedback,
        )
        committee_error = None
        cloud_votes: tuple[Any, ...] = ()
        if enabled_cloud:
            try:
                cloud_votes = run_teacher_committee(
                    request,
                    providers=providers,
                    config=cloud_config,
                    budget=budget,
                    prompt_template=cloud_prompt,
                    report_path=(
                        output_dir
                        / "cloud_teacher_reports"
                        / "committee"
                        / label
                        / f"round_{round_number}.json"
                    ),
                    call_quota=cloud_call_quota,
                )
            except Exception as exc:  # noqa: BLE001 - fail closed and preserve evidence
                committee_error = f"{type(exc).__name__}:{exc}"
        observed = {item.provider for item in cloud_votes}
        final_votes = [
            {
                "provider": "self_hosted_qwen",
                "model": local_audit.model,
                "participated": True,
                "verdict": local_audit.verdict,
                "confidence": local_audit.confidence,
                "defects": list(local_audit.problems),
                "candidate_id": winner_id,
                "round": round_number,
            },
            *(
                {
                    "provider": item.provider,
                    "model": item.model,
                    "participated": True,
                    "verdict": item.verdict,
                    "confidence": item.confidence,
                    "defects": list(item.defects),
                    "candidate_id": winner_id,
                    "round": round_number,
                }
                for item in cloud_votes
            ),
            *(
                {
                    "provider": provider_name,
                    "model": cloud_config["providers"][provider_name]["model"],
                    "participated": False,
                    "verdict": "not_run",
                    "confidence": None,
                    "defects": [],
                    "candidate_id": winner_id,
                    "round": round_number,
                    "reason": committee_error or "provider_unavailable_or_call_failed",
                }
                for provider_name in enabled_cloud
                if provider_name not in observed
            ),
        ]
        local_pass = local_audit.verdict == "pass" and local_audit.confidence >= advisory_floor
        cloud_pass = all(
            any(
                item.provider == provider_name
                and item.verdict == "pass"
                and item.confidence >= advisory_floor
                for item in cloud_votes
            )
            for provider_name in enabled_cloud
        )
        qa_pass = candidate_qa.passed and not candidate_qa.block_qc_ids
        pass_reviewer_count = int(local_pass) + sum(
            item.verdict == "pass" and item.confidence >= advisory_floor for item in cloud_votes
        )
        required_participation = not require_all or len(observed) == len(enabled_cloud)
        round_converged = (
            qa_pass
            and local_pass
            and cloud_pass
            and required_participation
            and pass_reviewer_count >= required_pass_reviewers
        )
        round_record: dict[str, Any] = {
            "round": round_number,
            "candidate_id": winner_id,
            "candidate_path": str(candidate_path),
            "candidate_score": winner.score,
            "complete_map_qa": asdict(candidate_qa),
            "local_audit": asdict(local_audit),
            "cloud_votes": [asdict(item) for item in cloud_votes],
            "committee_error": committee_error,
            "target_confidence": target,
            "minimum_advisory_pass_confidence": advisory_floor,
            "pass_reviewer_count": pass_reviewer_count,
            "required_pass_reviewer_count": required_pass_reviewers,
            "converged": round_converged,
            "generated_candidates": [],
            "correction_attempts": [],
        }
        rounds.append(round_record)
        if round_converged:
            converged = True
            stop_reason = "all_required_reviewers_passed_exact_candidate"
            candidate_inputs = [
                (
                    replace(
                        item,
                        independent_sources=tuple(
                            dict.fromkeys(
                                (*item.independent_sources, "self_hosted_qwen", *enabled_cloud)
                            )
                        ),
                        critic_pass_weight=1.0,
                        critic_disagreement=False,
                    )
                    if item.candidate_id == winner_id
                    else replace(item, critic_disagreement=True)
                )
                for item in candidate_inputs
            ]
            break

        failed_reviewer_ids = []
        if not local_pass:
            failed_reviewer_ids.append("self_hosted_qwen")
        failed_reviewer_ids.extend(
            provider_name
            for provider_name in enabled_cloud
            if not any(
                item.provider == provider_name
                and item.verdict == "pass"
                and item.confidence >= advisory_floor
                for item in cloud_votes
            )
        )
        if not qa_pass:
            failed_reviewer_ids.append("complete_map_qa")
        uncertainties = [f"candidate_not_converged:{item}" for item in failed_reviewer_ids]
        reviewer_results = [
            (local_audit.verdict, local_audit.confidence),
            *((item.verdict, item.confidence) for item in cloud_votes),
        ]
        failed_support = sum(
            confidence if verdict == "pass" else 0.5 * confidence if verdict == "uncertain" else 0
            for verdict, confidence in reviewer_results
        ) / max(1, len(reviewer_results))
        candidate_inputs = [
            (
                replace(
                    item,
                    critic_pass_weight=float(failed_support),
                    critic_disagreement=True,
                )
                if item.candidate_id == winner_id
                else item
            )
            for item in candidate_inputs
        ]
        if len(candidate_inputs) >= maximum_candidates:
            stop_reason = "maximum_candidate_count_reached"
            break

        generated: list[tuple[str, Path, tuple[str, ...], CandidateQaOutcome]] = []
        if local_audit.verdict == "fail":
            local_candidate = generate_correction_candidate(
                local_audit,
                source=np.asarray(source),
                current_mask=candidate_mask,
                protected_neighbor=immutable_protected,
                refiner=refiner,
                output_path=(
                    output_dir / "committee_candidates" / label / f"round_{round_number}_qwen.png"
                ),
                max_changed_fraction=float(repair["ordinary_max_changed_fraction"]),
                max_protected_overlap_fraction=float(repair["maximum_protected_overlap_fraction"]),
                repair_roi_xyxy=repair_roi_xyxy,
                person_bbox_xyxy=person_bbox_xyxy,
                reconstruction_max_changed_fraction=float(
                    repair["reconstruction_max_changed_fraction"]
                ),
                maximum_outside_roi_fraction=float(repair["maximum_outside_roi_fraction"]),
                expected_area_slack=float(repair["expected_area_slack"]),
            )
            workhorse_candidate_path = local_candidate.candidate_path
            round_record["correction_attempts"].append(
                {
                    "provider": "self_hosted_qwen",
                    "status": local_candidate.status,
                    "reason": local_candidate.reason,
                    "path": local_candidate.candidate_path,
                }
            )
            if local_candidate.status == "candidate_created" and workhorse_candidate_path:
                path = Path(workhorse_candidate_path)
                qa = _validate_candidate_map(
                    base_part_map,
                    label=label,
                    candidate_mask_path=path,
                    output_dir=(
                        output_dir / "candidate_qa" / label / f"committee_r{round_number}_qwen"
                    ),
                    tag=f"{label}_committee_r{round_number}_qwen",
                    validator=map_qa_validator,
                    repair_roi_xyxy=repair_roi_xyxy,
                    immutable_label_ids=immutable_label_ids,
                    maximum_displaced_labels=int(
                        repair["maximum_displaced_labels_per_transaction"]
                    ),
                )
                qa = boundary_checked(path, qa)
                generated.append(
                    (f"committee_r{round_number}_qwen", path, ("self_hosted_qwen", "sam2"), qa)
                )
        for judgment in cloud_votes:
            if (
                judgment.verdict != "fail"
                or len(candidate_inputs) + len(generated) >= maximum_candidates
            ):
                continue
            teacher_candidate = materialize_teacher_candidate(
                judgment,
                request=request,
                current_mask=candidate_mask,
                protected_neighbor=immutable_protected,
                refiner=refiner,
                output_path=(
                    output_dir
                    / "committee_candidates"
                    / label
                    / f"round_{round_number}_{judgment.provider}.png"
                ),
                max_changed_fraction=float(repair["ordinary_max_changed_fraction"]),
                max_protected_overlap_fraction=float(repair["maximum_protected_overlap_fraction"]),
                reconstruction_max_changed_fraction=float(
                    repair["reconstruction_max_changed_fraction"]
                ),
                maximum_outside_roi_fraction=float(repair["maximum_outside_roi_fraction"]),
                expected_area_slack=float(repair["expected_area_slack"]),
                person_bbox_xyxy=person_bbox_xyxy,
            )
            round_record["correction_attempts"].append(
                {
                    "provider": judgment.provider,
                    "status": teacher_candidate.status,
                    "reason": teacher_candidate.reason,
                    "path": teacher_candidate.path,
                }
            )
            if teacher_candidate.status != "candidate_created" or not teacher_candidate.path:
                continue
            path = Path(teacher_candidate.path)
            qa = _validate_candidate_map(
                base_part_map,
                label=label,
                candidate_mask_path=path,
                output_dir=(
                    output_dir
                    / "candidate_qa"
                    / label
                    / f"committee_r{round_number}_{judgment.provider}"
                ),
                tag=f"{label}_committee_r{round_number}_{judgment.provider}",
                validator=map_qa_validator,
                repair_roi_xyxy=repair_roi_xyxy,
                immutable_label_ids=immutable_label_ids,
                maximum_displaced_labels=int(repair["maximum_displaced_labels_per_transaction"]),
            )
            qa = boundary_checked(path, qa)
            generated.append(
                (
                    f"committee_r{round_number}_{judgment.provider}",
                    path,
                    (judgment.provider, judgment.correction.tool),
                    qa,
                )
            )
        existing_masks = {
            Image.open(item.mask_path).convert("L").tobytes() for item in candidate_inputs
        }
        novel_count = 0
        winner_input = next(item for item in candidate_inputs if item.candidate_id == winner_id)
        for candidate_id, path, correction_sources, qa in generated:
            content = Image.open(path).convert("L").tobytes()
            if content in existing_masks or len(candidate_inputs) >= maximum_candidates:
                continue
            existing_masks.add(content)
            candidate_inputs.append(
                MaskCandidateInput(
                    candidate_id,
                    path,
                    tuple(dict.fromkeys((*winner_input.independent_sources, *correction_sources))),
                    0.5,
                    True,
                    winner_input.pose_consistency,
                    qa.block_qc_ids,
                )
            )
            round_record["generated_candidates"].append(
                {
                    "candidate_id": candidate_id,
                    "path": str(path),
                    "complete_map_qa": asdict(qa),
                }
            )
            novel_count += 1
        if novel_count == 0:
            rejected = tuple(
                f'{item["provider"]}:{item["reason"]}'
                for item in round_record["correction_attempts"]
                if item["status"] != "candidate_created"
            )
            unresolved = tuple(
                f"{provider_name}:missing_or_below_advisory_pass_floor"
                for provider_name in enabled_cloud
                if not any(
                    item.provider == provider_name
                    and item.verdict == "pass"
                    and item.confidence >= advisory_floor
                    for item in cloud_votes
                )
            )
            terminal_committee_error = bool(
                committee_error
                and (
                    committee_error.startswith("CloudBudgetError:")
                    or "maximum calls per" in committee_error
                )
            )
            if terminal_committee_error:
                stop_reason = "cloud_committee_budget_or_job_quota_unavailable"
                uncertainties = [
                    stop_reason,
                    f"committee_error:{committee_error}",
                ]
                break
            if (rejected or unresolved) and round_number < maximum_rounds:
                iteration_feedback = (*rejected, *unresolved)
                round_record["replanning_required"] = True
                continue
            stop_reason = "reviewers_produced_no_novel_safe_candidate"
            break

    result = {
        "enabled": True,
        "converged": converged,
        "target_confidence": target,
        "target_confidence_kind": "requires_gold_calibration_not_raw_provider_scores",
        "minimum_advisory_pass_confidence": advisory_floor,
        "calibrated_95_claim": False,
        "round_count": len(rounds),
        "stop_reason": stop_reason,
        "final_votes": final_votes,
        "remaining_uncertainties": [] if converged else uncertainties or [stop_reason],
        "rounds_report": f"autonomy/convergence_{label}.json",
        "authoritative_gold": False,
        "publication_target": "reversible_non_gold_review_draft",
    }
    report_path = output_dir / "autonomy" / f"convergence_{label}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps({**result, "rounds": rounds}, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return candidate_inputs, result


def _companion_parts_visible(label: str, part_map: np.ndarray) -> bool:
    """Return whether the complete map exposes the atomic neighbor of a split label."""
    authority = get_ontology()
    side = authority.label(label).side
    companion_names: tuple[str, ...] = ()
    if label.endswith("foot_base"):
        companion_names = (f"{side}_toes",)
    elif label.endswith("toes"):
        companion_names = (f"{side}_foot_base",)
    elif label.endswith("hand_base"):
        companion_names = tuple(
            f"{side}_{suffix}"
            for suffix in (
                "thumb",
                "index_finger",
                "middle_finger",
                "ring_finger",
                "pinky",
            )
        )
    for name in companion_names:
        definition = authority.label(name)
        if definition.id is not None and np.any(np.asarray(part_map) == int(definition.id)):
            return True
    return False


def _qa_findings(outcome: CandidateQaOutcome) -> tuple[dict[str, Any], ...]:
    document = (
        json.loads(Path(outcome.report_path).read_text(encoding="utf-8"))
        if outcome.report_path and Path(outcome.report_path).is_file()
        else {}
    )
    findings = tuple(
        check
        for check in document.get("checks", ())
        if isinstance(check, dict) and check.get("result") in {"fail", "warn", "route"}
    )
    semantic = tuple(
        {
            "check_id": qc_id,
            "result": "fail",
            "severity": "BLOCK",
            "message": "candidate violates the atomic ontology boundary contract",
        }
        for qc_id in outcome.block_qc_ids
        if qc_id.startswith("MF-BOUNDARY-")
    )
    return (*findings, *semantic)


def _portable_review_draft(document: dict[str, Any], stage_root: Path) -> dict[str, Any]:
    portable = dict(document)
    root = Path(stage_root).resolve()
    for key in ("proposed_part_map", "review_part_map"):
        value = portable.get(key)
        if value:
            try:
                portable[key] = Path(value).resolve().relative_to(root).as_posix()
            except ValueError:
                pass
    qa = dict(portable.get("qa", {}))
    if qa.get("report_path"):
        try:
            qa["report_path"] = Path(qa["report_path"]).resolve().relative_to(root).as_posix()
        except ValueError:
            pass
    portable["qa"] = qa
    return portable


def _review_whole_image(
    client: OllamaClient,
    *,
    model: str,
    source_path: Path,
    overlay_path: Path,
    labels: dict[str, np.ndarray],
    prompt_path: Path,
    output_dir: Path,
    generation_options: dict,
) -> dict:
    source_prepared = prepare_panel_input(source_path, output_dir / "prepared/source_full.png")
    prepared = prepare_panel_input(overlay_path, output_dir / "prepared/all_parts.png")
    authority = get_ontology()
    digest = "\n".join(
        f"{item.name}:{'present_predicted' if item.name in labels else 'absent_or_not_visible'}:"
        f"{int(labels[item.name].sum()) if item.name in labels else 0}"
        for item in authority.labels_for_map("part", enabled_only=True)
        if item.id
    )
    prompt = (
        prompt_path.read_text(encoding="utf-8")
        + "\n\nVISIBLE LABEL DIGEST — PREDICTED ONLY (absence does not prove not-visible):\n"
        + digest
    )
    started = time.perf_counter()
    with GpuLock(path=output_dir / ".vlm_gpu.lock", purpose="S11_vlm_image_qa"):
        raw = client.generate(
            model=model,
            prompt=prompt,
            images=(source_prepared, prepared),
            options=generation_options,
            think=False,
        )
        parsed = _parse_image_review(raw)
        if parsed is None:
            raw = client.generate(
                model=model,
                prompt=prompt + "\nYour prior response was invalid. JSON only.",
                images=(source_prepared, prepared),
                options=generation_options,
                think=False,
            )
            parsed = _parse_image_review(raw)
    if parsed is None:
        parsed = {
            "missing": [],
            "mislabeled": [],
            "lr_suspect": [],
            "impossible_claims": [],
            "notes": "Invalid response after retry; route carefully.",
        }
        parsed["status"] = "uncertain_invalid_response"
    else:
        parsed["status"] = "complete"
    parsed["model"] = model
    parsed["prompt_version"] = "p-image-v2-source-overlay"
    parsed["latency_ms"] = round((time.perf_counter() - started) * 1000)
    return parsed


def _parse_image_review(raw: str) -> dict | None:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    required = {"missing", "mislabeled", "lr_suspect", "impossible_claims", "notes"}
    if set(value) != required or not all(
        isinstance(value[key], list) for key in required - {"notes"}
    ):
        return None
    if not isinstance(value["notes"], str):
        return None
    return value


def _is_disagreement(auto_qa: str, verdict) -> bool:
    return (auto_qa == "all_pass" and verdict.verdict == "fail") or (
        auto_qa in {"route", "block"} and verdict.verdict == "pass" and verdict.confidence >= 0.7
    )


def _label_use_weight(label: str) -> float:
    if any(token in label for token in ("finger", "thumb", "hand", "wrist")):
        return 1.0
    if any(token in label for token in ("chest", "breast")):
        return 1.0
    if any(token in label for token in ("foot", "toe", "ankle")):
        return 0.8
    return 0.3
