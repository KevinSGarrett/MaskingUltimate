"""Production S11 panel generation, calibration gating, local review, and routing."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict
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
from ..autonomy.review_draft import (
    CandidateQaOutcome,
    MapQaValidator,
    ReviewDraftSelection,
    build_autonomous_review_draft,
    compose_candidate_map,
)
from ..autonomy.tournament import run_candidate_tournament
from ..gpu import GpuLock
from ..io.png_strict import write_binary_mask, write_label_map
from ..ontology import get_ontology
from ..qa.failure_mining import append_failure_once, make_failure_record
from ..qa.panels import render_boundary_panel, render_part_overlays, render_workhorse_evidence
from ..validation import ArtifactValidationError, validate_document
from .client import OllamaClient, VlmVerdict, append_verdict, prepare_panel_input, review_part
from .cloud_budget import DailyBudgetLedger
from .cloud_providers import build_teacher_providers
from .cloud_teacher import (
    TeacherProvider,
    TeacherRequest,
    load_cloud_teacher_config,
    materialize_teacher_candidate,
    run_teacher_cascade,
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
) -> dict:
    """Run gated local VLM review, or safely route every part when the gate is unavailable."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    qa_report_path = output_dir / "qa_report.json"
    shutil.copy2(s10_report_path, qa_report_path)
    report = json.loads(qa_report_path.read_text(encoding="utf-8"))
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    cloud_config = load_cloud_teacher_config(cloud_teacher_config_path)
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
    viz = yaml.safe_load(Path("configs/viz.yaml").read_text(encoding="utf-8"))
    render_part_overlays(
        source,
        part_map,
        output_dir / "qa_panels",
        label_colors=viz["label_colors"],
    )
    panels: dict[str, Path] = {}
    for label, mask in sorted(masks.items()):
        protected = np.zeros(mask.shape, dtype=bool)
        for other, other_mask in masks.items():
            if other != label:
                protected |= other_mask
        panels[label] = render_boundary_panel(
            source, mask, protected, output_dir / "qa_panels" / f"{label}.png"
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
        owned_refiner = None
        active_teacher_providers = teacher_providers or build_teacher_providers(cloud_config)
        budget_settings = cloud_config["budget"]
        active_teacher_budget = teacher_budget or DailyBudgetLedger(
            Path(budget_settings["ledger_path"]),
            timezone_name=budget_settings["timezone"],
            hard_limit_usd=budget_settings["hard_limit_usd"],
            lock_timeout_sec=float(budget_settings["lock_timeout_sec"]),
        )
        for label, panel in panels.items():
            if workhorse_enabled and config.get("workhorse", {}).get("enabled") is True:
                protected = np.zeros(masks[label].shape, dtype=bool)
                for other, other_mask in masks.items():
                    if other != label:
                        protected |= other_mask
                evidence = render_workhorse_evidence(
                    source,
                    masks[label],
                    protected,
                    output_dir / "workhorse_evidence" / label,
                    tile_size=int(config["prompts"]["p_workhorse"]["independent_image_long_side"]),
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
                    ),
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
                    current_mask=masks[label],
                    protected_neighbor=protected,
                    refiner=active_refiner,
                    output_path=output_dir / "correction_candidates" / f"{label}.png",
                    max_changed_fraction=float(settings["max_changed_fraction"]),
                    max_protected_overlap_fraction=float(
                        settings["max_protected_overlap_fraction"]
                    ),
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
                        protected,
                        output_dir / "workhorse_evidence_after" / label,
                        tile_size=int(
                            config["prompts"]["p_workhorse"]["independent_image_long_side"]
                        ),
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
                if cloud_config["enabled"] is True:
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
                                protected_neighbor=protected,
                                refiner=teacher_refiner,
                                output_path=output_dir
                                / "cloud_teacher_candidates"
                                / f"{teacher_judgment.provider}_{label}.png",
                                max_changed_fraction=float(
                                    config["workhorse"]["max_changed_fraction"]
                                ),
                                max_protected_overlap_fraction=float(
                                    config["workhorse"]["max_protected_overlap_fraction"]
                                ),
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
                                    protected,
                                    output_dir
                                    / "cloud_teacher_evidence_after"
                                    / label
                                    / teacher_judgment.provider,
                                    tile_size=int(
                                        config["prompts"]["p_workhorse"][
                                            "independent_image_long_side"
                                        ]
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
                        critic_disagreement,
                        1.0,
                        block_ids,
                    )
                ]
                if candidate.status == "candidate_created" and candidate.candidate_path:
                    local_qa = _validate_candidate_map(
                        part_map,
                        label=label,
                        candidate_mask_path=Path(candidate.candidate_path),
                        output_dir=output_dir / "candidate_qa" / label / "local_r1",
                        tag=f"{label}_local_r1",
                        validator=map_qa_validator,
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
                            critic_disagreement,
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
                            protected_neighbor=protected,
                            refiner=active_refiner,
                            output_path=(
                                output_dir
                                / "correction_candidates"
                                / f"{label}_r{round_number}.png"
                            ),
                            max_changed_fraction=float(settings["max_changed_fraction"]),
                            max_protected_overlap_fraction=float(
                                settings["max_protected_overlap_fraction"]
                            ),
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
                            protected,
                            output_dir
                            / "workhorse_evidence_after"
                            / label
                            / f"round_{round_number}",
                            tile_size=int(
                                config["prompts"]["p_workhorse"]["independent_image_long_side"]
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
                                critic_disagreement,
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
                                critic_disagreement,
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
        if owned_refiner is not None:
            owned_refiner.close()
        autonomy_lifecycle = []
        review_draft_selections: list[ReviewDraftSelection] = []
        for label, candidate_inputs in sorted(autonomy_inputs.items()):
            protected = np.zeros_like(masks[label])
            for other_label, other_mask in masks.items():
                if other_label != label:
                    protected |= other_mask
            evidence = build_mask_candidate_evidence(
                tuple(candidate_inputs),
                protected_neighbor=protected,
                mutually_exclusive=protected,
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
            winner = next(
                (
                    ranked
                    for ranked in autonomy_decision.ranking
                    if ranked.candidate_id == autonomy_decision.winner_id
                ),
                None,
            )
            if winner is not None and autonomy_decision.status in {
                "machine_verified_candidate",
                "calibrated_auto_accepted",
            }:
                review_draft_selections.append(
                    ReviewDraftSelection(
                        label=label,
                        candidate_id=winner.candidate_id,
                        mask_path=winner.evidence.mask_path,
                        mask_sha256=winner.evidence.mask_sha256,
                        status=autonomy_decision.status,
                        score=winner.score,
                    )
                )
        review_draft = build_autonomous_review_draft(
            part_map_path,
            tuple(review_draft_selections),
            output_dir / "autonomy_review_draft",
            map_validator=map_qa_validator,
        )
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
) -> CandidateQaOutcome:
    """Compose a complete map and rerun hard QA for this exact candidate."""
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


def _qa_findings(outcome: CandidateQaOutcome) -> tuple[dict[str, Any], ...]:
    if not outcome.report_path or not Path(outcome.report_path).is_file():
        return ()
    document = json.loads(Path(outcome.report_path).read_text(encoding="utf-8"))
    return tuple(
        check
        for check in document.get("checks", ())
        if isinstance(check, dict) and check.get("result") in {"fail", "warn", "route"}
    )


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
