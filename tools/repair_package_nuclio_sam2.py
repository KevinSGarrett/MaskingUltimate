"""Agent-executable package part re-seg/repair via CVAT Nuclio pth-sam2 (no WSL).

Usage (PowerShell, from repo root):

  python tools/repair_package_nuclio_sam2.py ^
    --image-id img_51945db358cb --instance p0 --label left_thigh ^
    --defect-class fragmentation --apply

Without --apply: invoke + guard + seal candidate only (package unchanged).
Never claims VISUAL_QA_PASS_BOUNDED / gold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maskfactory.autonomy.repair import evaluate_repair_candidate  # noqa: E402
from maskfactory.autonomy.review_draft import compose_candidate_map_transactional  # noqa: E402
from maskfactory.io.hashing import sha256_file  # noqa: E402
from maskfactory.io.png_strict import write_binary_mask, write_label_map  # noqa: E402
from maskfactory.ontology import get_ontology  # noqa: E402
from maskfactory.providers.nuclio_sam2 import (  # noqa: E402
    BLOCKED_VISUAL_PASS_CLAIM,
    HIGHEST_VISUAL_TIER_WITH_RESIDUALS,
    SAM2_NUCLIO_PART_REFINE_HYPOTHESIS,
    NuclioSam2Client,
    NuclioSam2Error,
    decide_sam2_nuclio_promotion,
    derive_clicks_from_mask,
    load_cvat_token,
)
from maskfactory.qa.panels import render_boundary_panel, render_part_overlays  # noqa: E402


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _load_part_mask(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        arr = np.asarray(image)
    return arr > 0 if arr.dtype != np.bool_ else arr


def _protected_neighbor(part_map: np.ndarray, label_id: int) -> np.ndarray:
    return (part_map != 0) & (part_map != label_id)


def _update_manifest_hashes(manifest: dict, package: Path, relative_paths: list[str]) -> None:
    files = manifest.setdefault("files", {})
    for rel in relative_paths:
        path = package / rel
        if path.is_file():
            files[rel.replace("\\", "/")] = sha256_file(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--instance", default="p0")
    parser.add_argument("--label", required=True)
    parser.add_argument("--defect-class", default="fragmentation")
    parser.add_argument("--packages-root", type=Path, default=ROOT / "data" / "packages")
    parser.add_argument("--apply", action="store_true", help="Promote into live package if gated")
    parser.add_argument("--base-url", default="http://localhost:8080")
    args = parser.parse_args()

    package = Path(args.packages_root) / args.image_id / "instances" / args.instance
    source_path = package / "source.png"
    mask_rel = f"masks/{args.label}.png"
    mask_path = package / mask_rel
    map_path = package / "label_map_part.png"
    manifest_path = package / "manifest.json"
    for required in (source_path, mask_path, map_path, manifest_path):
        if not required.is_file():
            raise SystemExit(f"missing required package file: {required}")

    ontology = get_ontology()
    label_def = ontology.label(args.label)
    label_id = int(label_def.id)
    max_cc = max(1, int(label_def.max_components or 1))

    current = _load_part_mask(mask_path)
    with Image.open(map_path) as image:
        part_map = np.asarray(image)
    protected = _protected_neighbor(part_map, label_id)
    before_cc = int(ndimage.label(current)[1])
    baseline_excess = max(0, before_cc - max_cc)

    work = package / "annotations" / "autonomy" / "nuclio_sam2_repair" / args.label
    work.mkdir(parents=True, exist_ok=True)
    backup_dir = work / "backup_before"
    backup_dir.mkdir(parents=True, exist_ok=True)

    pos, neg, roi = derive_clicks_from_mask(current, protected=protected)
    person_bbox = None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    primary = (manifest.get("person") or {}).get("primary_person_bbox")
    if isinstance(primary, list) and len(primary) == 4:
        person_bbox = tuple(int(v) for v in primary)

    token = load_cvat_token(ROOT / ".env")
    client = NuclioSam2Client(base_url=args.base_url, token=token, timeout_seconds=300)
    task_name = f"MaskFactory nuclio repair {args.image_id}/{args.instance}"
    try:
        function = client.ensure_interactor()
        task_id = client.get_or_create_image_task(task_name=task_name, image_path=source_path)
        invoke = client.refine_part_mask(
            task_id=task_id,
            current_mask=current,
            pos_points=pos,
            neg_points=neg,
            roi_xyxy=roi,
        )
    except (NuclioSam2Error, OSError, Exception) as exc:  # noqa: BLE001 - service boundary
        # Catch requests ConnectionError / HTTP errors as honest reachability seals.
        report = {
            "artifact_type": "package_nuclio_sam2_repair",
            "outcome": "RUNTIME_UNREACHABLE_OR_INVOKE_FAIL",
            "error": f"{type(exc).__name__}: {exc}",
            "target": f"{args.image_id}/{args.instance}/{args.label}",
            "wsl_required": False,
            "runtime": "cvat_nuclio_pth_sam2",
            "base_url": args.base_url,
            "next_step": (
                "Restore production CVAT v2.24 + nuclio-pth-sam2 "
                "(python tools/bootstrap_cvat.py), re-run tools/smoke_cvat_sam2.py, "
                "then re-run this tool with --apply."
            ),
            "visual_qa_pass_bounded_claimed": False,
            "metrics_pre_invoke": {
                "before_components": before_cc,
                "baseline_excess": baseline_excess,
                "before_area_px": int(current.sum()),
            },
        }
        out = (
            ROOT
            / "qa"
            / "live_verification"
            / f"package_nuclio_sam2_repair_{args.image_id}_{args.instance}_{args.label}_fail.json"
        )
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        print(f"evidence={out}")
        return 2

    candidate = invoke.mask > 0
    after_cc = int(ndimage.label(candidate)[1])
    candidate_path = write_binary_mask(
        work / "candidate_mask.png",
        candidate.astype(np.uint8) * 255,
        source_size=(current.shape[1], current.shape[0]),
    )

    guard = evaluate_repair_candidate(
        candidate,
        current_mask=current,
        protected_mask=protected,
        label=args.label,
        roi_xyxy=roi,
        person_bbox_xyxy=person_bbox,
        ordinary_max_changed_fraction=0.75,
        reconstruction_max_changed_fraction=2.0,
        maximum_protected_overlap_fraction=0.02,
        maximum_outside_roi_fraction=0.005,
        expected_area_slack=0.5,
    )

    composed, vetoes, displaced = compose_candidate_map_transactional(
        part_map,
        label=args.label,
        candidate_mask_path=candidate_path,
        repair_roi_xyxy=roi,
        immutable_label_ids=(),
        maximum_displaced_labels=8,
    )
    map_ok = not vetoes
    proposed_map_path = write_label_map(work / "proposed_label_map_part.png", composed, bits=16)

    # Local hard-QC proxy: ontology CC + nonempty + exclusive compose.
    hard_qc = bool(guard.eligible and map_ok and after_cc <= max_cc and candidate.any())
    cc_drop = max(0, before_cc - after_cc)
    drop_px = int(np.count_nonzero(current & ~candidate))  # removed mass (noise islands)

    promotion = decide_sam2_nuclio_promotion(
        defect_class=args.defect_class,
        executor_accepted=bool(guard.eligible and map_ok),
        baseline_excess=baseline_excess,
        hard_qc_passed=hard_qc,
    )

    applied = False
    verify_rc = None
    changed_rels: list[str] = [
        str(candidate_path.relative_to(package)).replace("\\", "/"),
        str(proposed_map_path.relative_to(package)).replace("\\", "/"),
    ]

    if args.apply and promotion.may_promote:
        shutil.copy2(mask_path, backup_dir / f"{args.label}.png")
        shutil.copy2(map_path, backup_dir / "label_map_part.png")
        shutil.copy2(manifest_path, backup_dir / "manifest.json")
        for panel_name in (f"{args.label}.png", "all_parts.png"):
            panel = package / "qa_panels" / panel_name
            if panel.is_file():
                shutil.copy2(panel, backup_dir / f"qa_panels_{panel_name}")
        overlay_all = package / "overlays" / "all_parts.png"
        if overlay_all.is_file():
            shutil.copy2(overlay_all, backup_dir / "overlays_all_parts.png")
        write_binary_mask(
            mask_path,
            candidate.astype(np.uint8) * 255,
            source_size=(current.shape[1], current.shape[0]),
        )
        write_label_map(map_path, composed, bits=16)
        viz = yaml.safe_load((ROOT / "configs" / "viz.yaml").read_text(encoding="utf-8"))
        with Image.open(source_path) as source_image:
            source_rgb = source_image.convert("RGB")
            overlay_dir = work / "overlays_refresh"
            render_part_overlays(
                source_rgb,
                composed,
                overlay_dir,
                label_colors=viz["label_colors"],
            )
            all_parts_src = overlay_dir / "all_parts.png"
            if all_parts_src.is_file():
                shutil.copy2(all_parts_src, package / "qa_panels" / "all_parts.png")
                overlays_dir = package / "overlays"
                overlays_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(all_parts_src, overlays_dir / "all_parts.png")
            render_boundary_panel(
                source_rgb,
                candidate,
                protected,
                package / "qa_panels" / f"{args.label}.png",
            )
        # Update part entry + file hashes for mutated artifacts.
        entry = dict((manifest.get("parts") or {}).get(args.label) or {})
        ys, xs = np.where(candidate)
        entry.update(
            {
                "mask_file": mask_rel,
                "mask_area_px": int(candidate.sum()),
                "components": after_cc,
                "mask_bbox": [
                    int(xs.min()),
                    int(ys.min()),
                    int(xs.max()) + 1,
                    int(ys.max()) + 1,
                ],
                "mask_sha256": sha256_file(mask_path),
                "status": "draft_model_generated",
                "provenance": {
                    "draft_source": "nuclio_sam2_part_refine",
                    "human_edit": False,
                    "sam2_prompt_id": args.label,
                    "repair_hypothesis": SAM2_NUCLIO_PART_REFINE_HYPOTHESIS,
                    "prior_components": before_cc,
                },
            }
        )
        manifest.setdefault("parts", {})[args.label] = entry
        changed_rels.extend(
            [
                mask_rel,
                "label_map_part.png",
                f"qa_panels/{args.label}.png",
                "qa_panels/all_parts.png",
                "overlays/all_parts.png",
            ]
        )
        _update_manifest_hashes(manifest, package, sorted(set(changed_rels)))
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        applied = True
        verify = subprocess.run(
            [
                sys.executable,
                "-m",
                "maskfactory",
                "verify-package",
                args.image_id,
                "--root",
                str(args.packages_root),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        verify_rc = verify.returncode
        (work / "verify_package_stdout.txt").write_text(
            (verify.stdout or "") + "\n" + (verify.stderr or ""), encoding="utf-8"
        )
        if verify_rc != 0:
            # Roll back on hard verify failure.
            shutil.copy2(backup_dir / f"{args.label}.png", mask_path)
            shutil.copy2(backup_dir / "label_map_part.png", map_path)
            shutil.copy2(backup_dir / "manifest.json", manifest_path)
            for panel_name in (f"{args.label}.png", "all_parts.png"):
                backup_panel = backup_dir / f"qa_panels_{panel_name}"
                if backup_panel.is_file():
                    shutil.copy2(backup_panel, package / "qa_panels" / panel_name)
            backup_overlay = backup_dir / "overlays_all_parts.png"
            if backup_overlay.is_file():
                shutil.copy2(backup_overlay, package / "overlays" / "all_parts.png")
            applied = False
            promotion_outcome = "ROLLED_BACK_VERIFY_FAIL"
        else:
            promotion_outcome = promotion.outcome
    elif args.apply and not promotion.may_promote:
        promotion_outcome = promotion.outcome
    else:
        promotion_outcome = "CANDIDATE_ONLY_" + (
            "ELIGIBLE" if promotion.may_promote else promotion.outcome
        )

    report = {
        "artifact_type": "package_nuclio_sam2_repair",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "project_head": _git_head(),
        "lane": "WSL-independent package part re-seg via CVAT/Nuclio pth-sam2",
        "target": {
            "image_id": args.image_id,
            "instance": args.instance,
            "label": args.label,
            "defect_class": args.defect_class,
            "package": str(package.relative_to(ROOT)).replace("\\", "/"),
        },
        "runtime": {
            "path": "cvat_nuclio_pth_sam2",
            "wsl_ubuntu_required": False,
            "host_cuda_required": False,
            "base_url": args.base_url,
            "function_id": "pth-sam2",
            "function_version": invoke.function_version,
            "function_name": function.get("name"),
            "task_id": task_id,
            "task_name": task_name,
            "latency_seconds": invoke.latency_seconds,
        },
        "clicks": {"pos_points": pos, "neg_points": neg, "roi_xyxy": list(roi)},
        "metrics": {
            "before_components": before_cc,
            "after_components": after_cc,
            "max_components": max_cc,
            "baseline_excess": baseline_excess,
            "cc_drop": cc_drop,
            "before_area_px": int(current.sum()),
            "after_area_px": int(candidate.sum()),
            "drop_px_removed": drop_px,
            "foreground_pixels_raw": invoke.foreground_pixels,
        },
        "guards": {
            "eligible": guard.eligible,
            "reconstruction": guard.reconstruction,
            "changed_fraction": guard.changed_fraction,
            "protected_overlap_fraction": guard.protected_overlap_fraction,
            "outside_roi_fraction": guard.outside_roi_fraction,
            "component_count": guard.component_count,
            "vetoes": list(guard.vetoes),
            "compose_vetoes": list(vetoes),
            "displaced_labels": displaced,
            "hard_qc_proxy": hard_qc,
        },
        "promotion": {
            "hypothesis_id": SAM2_NUCLIO_PART_REFINE_HYPOTHESIS,
            "may_promote": promotion.may_promote,
            "outcome": promotion.outcome,
            "reason": promotion.reason,
            "visual_tier": promotion.visual_tier,
            "claims_forbidden": list(promotion.claims_forbidden),
            "applied": applied,
            "apply_requested": bool(args.apply),
            "final_outcome": promotion_outcome,
            "verify_package_returncode": verify_rc,
        },
        "honesty": [
            f"{BLOCKED_VISUAL_PASS_CLAIM} is never claimed by this tool",
            f"highest visual tier retained: {HIGHEST_VISUAL_TIER_WITH_RESIDUALS}",
            "WSL Ubuntu VHD is not required; Docker/CVAT/Nuclio is the sole runtime",
            "Whole-instance VISUAL_QA_PASS_BOUNDED still requires clearing all residual defect classes",
        ],
        "visual_qa_pass_bounded_claimed": False,
        "candidate_dir": str(work.relative_to(ROOT)).replace("\\", "/"),
    }
    digest = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    report["self_sha256"] = digest

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = (
        ROOT
        / "qa"
        / "live_verification"
        / f"package_nuclio_sam2_repair_{args.image_id}_{args.instance}_{args.label}_{stamp}.json"
    )
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (work / "repair_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"evidence={out}")
    return 0 if (guard.eligible or not args.apply) else 1


if __name__ == "__main__":
    raise SystemExit(main())
