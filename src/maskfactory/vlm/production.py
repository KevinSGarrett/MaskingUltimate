"""Production S11 panel generation, calibration gating, local review, and routing."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import numpy as np
import yaml
from PIL import Image

from ..gpu import GpuLock
from ..ontology import get_ontology
from ..qa.failure_mining import append_failure_once, make_failure_record
from ..qa.panels import render_boundary_panel, render_part_overlays
from ..validation import ArtifactValidationError, validate_document
from .client import OllamaClient, append_verdict, prepare_panel_input, review_part
from .eval import VlmEvalError, require_current_gate
from .router import route

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
) -> dict:
    """Run gated local VLM review, or safely route every part when the gate is unavailable."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    qa_report_path = output_dir / "qa_report.json"
    shutil.copy2(s10_report_path, qa_report_path)
    report = json.loads(qa_report_path.read_text(encoding="utf-8"))
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    model = config["models"]["primary_vlm"]
    prompt_version = config["prompts"]["p_part"]["version"]
    generation_options = config["runtime"]["generation_options"]
    prompt_template = Path(prompt_path).read_text(encoding="utf-8")
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
        }
        report["overall"] = "fail" if report["overall"] == "fail" else "needs_human"
        qa_report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    else:
        active_client = client or OllamaClient(config["runtime"]["base_url"])
        auto_qa = (
            "block"
            if report["overall"] == "fail"
            else "all_pass"
            if report["overall"] == "pass"
            else "route"
        )
        routes = {}
        for label, panel in panels.items():
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
            decision = route(auto_qa, verdict)
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
        image_review = _review_whole_image(
            active_client,
            model=model,
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
        }
    (output_dir / "vlm_routing.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    final_report = json.loads(qa_report_path.read_text(encoding="utf-8"))
    issues = validate_document(final_report, "qa_report")
    if issues:
        raise ArtifactValidationError(issues)
    return status


def _review_whole_image(
    client: OllamaClient,
    *,
    model: str,
    overlay_path: Path,
    labels: dict[str, np.ndarray],
    prompt_path: Path,
    output_dir: Path,
    generation_options: dict,
) -> dict:
    prepared = prepare_panel_input(overlay_path, output_dir / "prepared/all_parts.png")
    digest = "\n".join(f"{name}:visible:{int(mask.sum())}" for name, mask in sorted(labels.items()))
    prompt = prompt_path.read_text(encoding="utf-8") + "\n\nVISIBLE LABEL DIGEST:\n" + digest
    started = time.perf_counter()
    with GpuLock(path=output_dir / ".vlm_gpu.lock", purpose="S11_vlm_image_qa"):
        raw = client.generate(
            model=model,
            prompt=prompt,
            images=(prepared,),
            options=generation_options,
        )
        parsed = _parse_image_review(raw)
        if parsed is None:
            raw = client.generate(
                model=model,
                prompt=prompt + "\nYour prior response was invalid. JSON only.",
                images=(prepared,),
                options=generation_options,
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
    parsed["prompt_version"] = "p-image-v1-doc10"
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
